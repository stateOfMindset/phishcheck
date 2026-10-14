"""Chunking and document loading. These tests need no database and no embedding model."""
import pytest

from server import config, rag

DOC = """---
title: "{{COLLEGE_NAME}}: test procedure"
source_type: college
---

## First step

Contact {{HELPDESK}} about {{COLLEGE_DOMAIN}}.

## Second step

1. One
2. Two
"""


def write(tmp_path, text, name="doc.md"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_one_chunk_per_section_with_placeholders_filled(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "KNOWLEDGE_DIR", tmp_path)
    monkeypatch.setattr(config, "COLLEGE_NAME", "Test College")
    monkeypatch.setattr(config, "COLLEGE_DOMAIN", "test.ac.il")
    monkeypatch.setattr(config, "HELPDESK_EMAIL", "")
    doc = rag.load_document(write(tmp_path, DOC))

    assert doc.title == "Test College: test procedure"
    assert doc.source_type == "college"
    assert [c.heading for c in doc.chunks] == ["First step", "Second step"]
    assert doc.chunks[0].content == "Contact the college IT helpdesk about test.ac.il."
    assert doc.chunks[1].content == "1. One\n2. Two"  # numbered steps stay together
    assert doc.chunks[0].embed_text.startswith("Test College: test procedure\nFirst step")
    assert "{{" not in "".join(c.content for c in doc.chunks)


def test_helpdesk_email_included_when_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "KNOWLEDGE_DIR", tmp_path)
    monkeypatch.setattr(config, "HELPDESK_EMAIL", "it@test.ac.il")
    doc = rag.load_document(write(tmp_path, DOC))
    assert "the college IT helpdesk (it@test.ac.il)" in doc.chunks[0].content


def test_long_section_split_on_paragraphs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "KNOWLEDGE_DIR", tmp_path)
    paragraph = "word " * 200  # ~1000 characters
    text = f"---\ntitle: Long\nsource_type: general\n---\n\n## Big\n\n{paragraph}\n\n{paragraph}\n"
    doc = rag.load_document(write(tmp_path, text))
    assert len(doc.chunks) == 2
    assert doc.chunks[1].heading == "Big (part 2)"
    assert all(len(c.content) <= rag.MAX_CHUNK_CHARS for c in doc.chunks)


@pytest.mark.parametrize("bad", [
    "no front matter\n## A\ntext",
    "---\ntitle: X\nsource_type: blog\n---\n## A\ntext",
    "---\ntitle: X\nsource_type: general\n---\nno sections here",
])
def test_invalid_documents_rejected(tmp_path, monkeypatch, bad):
    monkeypatch.setattr(config, "KNOWLEDGE_DIR", tmp_path)
    with pytest.raises(ValueError):
        rag.load_document(write(tmp_path, bad))


def test_real_knowledge_base_loads():
    docs = rag.load_knowledge_base()
    assert len(docs) >= 10
    assert {d.source_type for d in docs} == {"general", "college"}
    assert all(d.source_url for d in docs if d.source_type == "general")
