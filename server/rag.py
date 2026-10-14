"""RAG module: chunking, embedding and similarity search over the knowledge base (pgvector).

Chunking strategy: one chunk per '## ' section of a Markdown document. Each section in the
knowledge base covers one self-contained step or idea, so a heading-based split keeps
instructions together instead of cutting a numbered procedure in half the way fixed-size
windows would. The document title and section heading are prepended to the chunk text so the
embedding carries that context. Sections longer than MAX_CHUNK_CHARS (rare) are split on
paragraph boundaries.
"""
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from server import config, db

MAX_CHUNK_CHARS = 1800          # ~400 tokens; bge-small reads up to 512
DEFAULT_TOP_K = 4
# Cosine similarity below this is treated as "not relevant". Calibrated on test queries:
# on-topic questions score 0.65+, off-topic ones (e.g. "how does a firewall work") up to ~0.61.
MIN_SCORE = 0.62

# bge models expect this instruction in front of short search queries (not documents).
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


@dataclass
class Chunk:
    heading: str
    content: str     # text stored and shown as the source
    embed_text: str  # text the embedding is computed from (title + heading + content)


@dataclass
class Document:
    source_file: str
    title: str
    source_type: str
    source_url: str | None
    chunks: list[Chunk]


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer  # heavy import, load once on demand
    return SentenceTransformer(config.EMBEDDING_MODEL)


def embed_documents(texts: list[str]) -> list:
    return list(_model().encode(texts, normalize_embeddings=True, batch_size=16))


def embed_query(text: str):
    return _model().encode(QUERY_PREFIX + text, normalize_embeddings=True)


# ---------------------------------------------------------------------------
# Loading and chunking Markdown documents
# ---------------------------------------------------------------------------

def fill_placeholders(text: str) -> str:
    helpdesk = "the college IT helpdesk"
    if config.HELPDESK_EMAIL:
        helpdesk += f" ({config.HELPDESK_EMAIL})"
    return (text.replace("{{COLLEGE_NAME}}", config.COLLEGE_NAME)
                .replace("{{COLLEGE_DOMAIN}}", config.COLLEGE_DOMAIN)
                .replace("{{HELPDESK}}", helpdesk))


def _parse_front_matter(text: str) -> tuple[dict, str]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not match:
        raise ValueError("missing front matter (--- title / source_type --- block)")
    meta = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, text[match.end():]


def _split_long(body: str) -> list[str]:
    if len(body) <= MAX_CHUNK_CHARS:
        return [body]
    parts, current = [], ""
    for para in re.split(r"\n\s*\n", body):
        if current and len(current) + len(para) + 2 > MAX_CHUNK_CHARS:
            parts.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        parts.append(current)
    return parts


def load_document(path: Path) -> Document:
    meta, body = _parse_front_matter(fill_placeholders(path.read_text(encoding="utf-8")))
    title = meta.get("title")
    source_type = meta.get("source_type")
    if not title or source_type not in ("general", "college"):
        raise ValueError("front matter needs 'title' and source_type 'general' or 'college'")

    chunks: list[Chunk] = []
    # Element 0 is whatever precedes the first '## ' heading; it is not a section.
    for section in re.split(r"(?m)^## ", body)[1:]:
        heading, _, content = section.strip().partition("\n")
        if not content.strip():
            continue
        for i, part in enumerate(_split_long(content.strip())):
            label = heading.strip() + (f" (part {i + 1})" if i else "")
            chunks.append(Chunk(heading=label, content=part,
                                embed_text=f"{title}\n{label}\n\n{part}"))
    if not chunks:
        raise ValueError("no '## ' sections found")

    return Document(source_file=path.relative_to(config.KNOWLEDGE_DIR).as_posix(), title=title,
                    source_type=source_type, source_url=meta.get("source_url") or None,
                    chunks=chunks)


def load_knowledge_base(directory: Path | None = None) -> list[Document]:
    directory = directory or config.KNOWLEDGE_DIR
    return [load_document(p) for p in sorted(directory.rglob("*.md"))]


# ---------------------------------------------------------------------------
# Storing and retrieving
# ---------------------------------------------------------------------------

def store(documents: list[Document]) -> int:
    """Replace the whole knowledge base in one transaction. Returns the number of chunks."""
    all_chunks = [c for d in documents for c in d.chunks]
    vectors = embed_documents([c.embed_text for c in all_chunks])
    vector_iter = iter(vectors)

    with db.pool().connection() as conn, conn.transaction():
        conn.execute("DELETE FROM documents")  # chunks cascade
        for doc in documents:
            doc_id = conn.execute(
                """INSERT INTO documents (source_file, title, source_type, source_url)
                   VALUES (%s, %s, %s, %s) RETURNING id""",
                (doc.source_file, doc.title, doc.source_type, doc.source_url),
            ).fetchone()["id"]
            for index, chunk in enumerate(doc.chunks):
                conn.execute(
                    """INSERT INTO chunks (document_id, chunk_index, heading, content, embedding)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (doc_id, index, chunk.heading, chunk.content, next(vector_iter)),
                )
    return len(all_chunks)


def retrieve(query: str, top_k: int = DEFAULT_TOP_K, min_score: float = MIN_SCORE) -> list[dict]:
    """Most similar chunks to `query`, best first, each with its cosine similarity score.

    Chunks scoring below `min_score` are dropped, so an off-topic question returns an empty
    list instead of loosely related text. Returns [] when the knowledge base is empty.
    """
    vector = embed_query(query)
    with db.pool().connection() as conn:
        rows = conn.execute(
            """SELECT d.title, d.source_type, d.source_url, d.source_file,
                      c.heading, c.content, 1 - (c.embedding <=> %s) AS score
               FROM chunks c JOIN documents d ON d.id = c.document_id
               ORDER BY c.embedding <=> %s
               LIMIT %s""",
            (vector, vector, top_k),
        ).fetchall()
    return [{**r, "score": round(float(r["score"]), 3)} for r in rows if r["score"] >= min_score]
