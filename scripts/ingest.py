"""Load the Markdown knowledge base into PostgreSQL/pgvector.

Usage:  python -m scripts.ingest
Re-run whenever you change files in knowledge/ or the college settings in .env.
The first run downloads the embedding model (~130 MB) and caches it.
"""
import sys
import time

from server import config, rag


def main() -> int:
    started = time.time()
    try:
        documents = rag.load_knowledge_base()
    except ValueError as exc:
        print(f"Could not read the knowledge base: {exc}")
        return 1
    if not documents:
        print(f"No .md files found in {config.KNOWLEDGE_DIR}")
        return 1

    print(f"Loaded {len(documents)} documents from {config.KNOWLEDGE_DIR}")
    for doc in documents:
        print(f"  [{doc.source_type:7}] {doc.source_file:48} {len(doc.chunks)} chunks")

    print(f"Embedding with {config.EMBEDDING_MODEL} (first run downloads the model)...")
    count = rag.store(documents)
    print(f"Stored {count} chunks in {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
