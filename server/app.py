"""Flask application: client files and the REST API. Started by run.py."""
import logging
import uuid

import psycopg
from flask import Flask, jsonify, request, send_from_directory
from psycopg_pool import PoolTimeout
from werkzeug.exceptions import HTTPException

from server import config, db, pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("phishcheck")

MAX_MESSAGE_CHARS = 8000


def error(status: int, message: str):
    return jsonify({"error": message}), status


def parse_session_id(raw) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)

    # ------------------------------------------------------------------ client
    @app.get("/")
    def index():
        return send_from_directory(config.CLIENT_DIR, "index.html")

    @app.get("/static/<path:filename>")
    def static_files(filename):
        return send_from_directory(config.CLIENT_DIR, filename)

    # ------------------------------------------------------------------- API
    @app.get("/health")
    def health():
        try:
            db.ping()
            chunks = db.chunk_count()
        except Exception as exc:
            log.warning("Health check: database unreachable: %s", exc)
            return jsonify({"status": "error", "database": "unreachable"}), 503
        return jsonify({
            "status": "ok",
            "database": "ok",
            "knowledge_chunks": chunks,
            "llm_configured": bool(config.ANTHROPIC_API_KEY),
        })

    @app.get("/history")
    def history():
        session_id = parse_session_id(request.args.get("session_id"))
        if session_id is None:
            return error(400, "Query parameter 'session_id' must be a valid UUID.")
        return jsonify({"session_id": str(session_id), "messages": db.get_history(session_id)})

    @app.post("/chat")
    def chat():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return error(400, "Request body must be a JSON object.")
        session_id = parse_session_id(body.get("session_id"))
        if session_id is None:
            return error(400, "Field 'session_id' must be a valid UUID.")
        message = body.get("message")
        if not isinstance(message, str) or not message.strip():
            return error(400, "Field 'message' must be a non-empty string.")
        if len(message) > MAX_MESSAGE_CHARS:
            return error(400, f"Message is too long (max {MAX_MESSAGE_CHARS} characters).")

        return jsonify(pipeline.run(session_id, message.strip()))

    # ---------------------------------------------------------------- errors
    @app.errorhandler(HTTPException)
    def http_error(exc: HTTPException):
        return error(exc.code or 500, exc.description)

    @app.errorhandler(psycopg.OperationalError)
    @app.errorhandler(PoolTimeout)
    def database_error(exc: Exception):
        log.error("Database unavailable: %s", exc)
        return error(503, "The database is unavailable. Check that the Docker container is "
                          "running (docker compose up -d) and try again.")

    @app.errorhandler(Exception)
    def unexpected_error(exc: Exception):
        log.exception("Unhandled error")
        return error(500, "Something went wrong on the server. Please try again.")

    return app
