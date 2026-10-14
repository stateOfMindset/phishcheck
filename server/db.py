"""PostgreSQL access: connection pool plus the queries the rest of the server needs."""
import json
import uuid

from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from server import config

_pool: ConnectionPool | None = None


def _configure(conn):
    register_vector(conn)


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            config.DATABASE_URL,
            min_size=1,
            max_size=5,
            kwargs={"row_factory": dict_row, "autocommit": True},
            configure=_configure,
            open=True,
            timeout=5,  # fail fast with a clear error when the DB container is down
        )
    return _pool


def ping() -> bool:
    with pool().connection(timeout=3) as conn:
        return conn.execute("SELECT 1 AS ok").fetchone()["ok"] == 1


def chunk_count() -> int:
    with pool().connection() as conn:
        return conn.execute("SELECT count(*) AS n FROM chunks").fetchone()["n"]


# ---------------------------------------------------------------------------
# Sessions and messages
# ---------------------------------------------------------------------------

def ensure_session(session_id: uuid.UUID) -> None:
    with pool().connection() as conn:
        conn.execute(
            "INSERT INTO sessions (id) VALUES (%s) ON CONFLICT (id) DO NOTHING", (session_id,)
        )


def save_message(session_id, role, content, routes=None, route_reason=None, sources=None) -> int:
    with pool().connection() as conn:
        row = conn.execute(
            """INSERT INTO messages (session_id, role, content, routes, route_reason, sources)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (session_id, role, content, routes, route_reason,
             Jsonb(sources) if sources is not None else None),
        ).fetchone()
        return row["id"]


def get_history(session_id, limit: int | None = None) -> list[dict]:
    """Messages for a session, oldest first. With `limit`, only the most recent ones."""
    with pool().connection() as conn:
        if limit is None:
            rows = conn.execute(
                """SELECT id, role, content, routes, route_reason, sources, created_at
                   FROM messages WHERE session_id = %s ORDER BY id""",
                (session_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM (
                       SELECT id, role, content, routes, route_reason, sources, created_at
                       FROM messages WHERE session_id = %s ORDER BY id DESC LIMIT %s
                   ) recent ORDER BY id""",
                (session_id, limit),
            ).fetchall()
    for r in rows:
        r["created_at"] = r["created_at"].isoformat()
    return rows


# ---------------------------------------------------------------------------
# Tool-call log
# ---------------------------------------------------------------------------

def log_tool_call(session_id, tool_name, tool_input, tool_output, success, error=None,
                  duration_ms=None, message_id=None) -> int:
    with pool().connection() as conn:
        row = conn.execute(
            """INSERT INTO tool_calls
                   (session_id, message_id, tool_name, tool_input, tool_output,
                    success, error, duration_ms)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (session_id, message_id, tool_name, Jsonb(tool_input),
             Jsonb(json.loads(json.dumps(tool_output, default=str))) if tool_output is not None else None,
             success, error, duration_ms),
        ).fetchone()
        return row["id"]


def link_tool_calls(tool_call_ids: list[int], message_id: int) -> None:
    if not tool_call_ids:
        return
    with pool().connection() as conn:
        conn.execute(
            "UPDATE tool_calls SET message_id = %s WHERE id = ANY(%s)", (message_id, tool_call_ids)
        )
