"""Settings loaded from environment variables (.env). Import this before any network code."""
import os
from pathlib import Path

import truststore
from dotenv import load_dotenv

# Use the operating system's certificate store for HTTPS instead of Python's bundled one.
# Without this, antivirus HTTPS scanning (e.g. AVG Web Shield) or corporate proxies make
# every call to the Anthropic API and the embedding-model download fail certificate checks.
truststore.inject_into_ssl()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable {name}. See .env.example.")
    return value


ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANSWER_MODEL = os.getenv("ANSWER_MODEL", "claude-sonnet-5-5")
FAST_MODEL = os.getenv("FAST_MODEL", "claude-haiku-5-5")

DATABASE_URL = (
    f"postgresql://{_require('POSTGRES_USER')}:{_require('POSTGRES_PASSWORD')}"
    f"@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5433')}"
    f"/{_require('POSTGRES_DB')}"
)

COLLEGE_NAME = os.getenv("COLLEGE_NAME", "Ravenmoor College")
COLLEGE_DOMAIN = os.getenv("COLLEGE_DOMAIN", "ravenmoor.edu").lower()
# Left empty unless you know the real address; answers then refer to "the college IT helpdesk".
HELPDESK_EMAIL = os.getenv("HELPDESK_EMAIL", "").strip()

EMBEDDING_MODEL =os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"
CLIENT_DIR = PROJECT_ROOT / "client"

FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))

# Conversation memory: how many past turns are sent to the model with each request.
HISTORY_TURNS = 10
