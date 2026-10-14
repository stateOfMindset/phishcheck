-- PhishCheck schema. Runs automatically the first time the Docker volume is created.
-- To re-run from scratch: docker compose down -v && docker compose up -d

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- Conversations
-- ---------------------------------------------------------------------------

CREATE TABLE sessions (
    id          UUID PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE messages (
    id            BIGSERIAL PRIMARY KEY,
    session_id    UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role          TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content       TEXT NOT NULL,
    -- Assistant turns only: which paths the router chose (e.g. {tool,rag}) and why.
    routes        TEXT[],
    route_reason  TEXT,
    sources       JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX messages_session_idx ON messages (session_id, id);

-- Every tool invocation: what was called, with what, and what came back.
CREATE TABLE tool_calls (
    id           BIGSERIAL PRIMARY KEY,
    session_id   UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    message_id   BIGINT REFERENCES messages(id) ON DELETE SET NULL,
    tool_name    TEXT NOT NULL,
    tool_input   JSONB NOT NULL,
    tool_output  JSONB,
    success      BOOLEAN NOT NULL,
    error        TEXT,
    duration_ms  INTEGER,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX tool_calls_session_idx ON tool_calls (session_id);

-- ---------------------------------------------------------------------------
-- Knowledge base (RAG). pgvector lives in the same database as everything else.
-- ---------------------------------------------------------------------------

CREATE TABLE documents (
    id           SERIAL PRIMARY KEY,
    source_file  TEXT NOT NULL UNIQUE,
    title        TEXT NOT NULL,
    -- 'general' = public guidance, 'college' = our fictional college's own procedures.
    source_type  TEXT NOT NULL CHECK (source_type IN ('general', 'college')),
    source_url   TEXT,
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE chunks (
    id           SERIAL PRIMARY KEY,
    document_id  INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index  INTEGER NOT NULL,
    heading      TEXT NOT NULL,
    content      TEXT NOT NULL,
    -- all-MiniLM-L6-v2 produces 384-dimensional embeddings.
    embedding    vector(384) NOT NULL,
    UNIQUE (document_id, chunk_index)
);
CREATE INDEX chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);

-- ---------------------------------------------------------------------------
-- Router evaluation (optional): expected vs. actual routes per test query.
-- ---------------------------------------------------------------------------

CREATE TABLE eval_results (
    id               BIGSERIAL PRIMARY KEY,
    run_id           UUID NOT NULL,
    query            TEXT NOT NULL,
    expected_routes  TEXT[] NOT NULL,
    actual_routes    TEXT[] NOT NULL,
    correct          BOOLEAN NOT NULL,
    router_reason    TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
