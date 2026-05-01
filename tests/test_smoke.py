"""Smoke tests: each tool round-trip + history persistence + bilingual templates."""

from __future__ import annotations

import sys
from importlib.resources import files
from pathlib import Path

import pytest


def _bootstrap_wiki(tmp_path: Path, lang: str = "en") -> Path:
    """Copy the lang templates into a fresh wiki dir so server.py is happy."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    template_dir = files("scinotes.templates") / lang
    for entry in template_dir.iterdir():
        if entry.name.endswith(".md"):
            (wiki / entry.name).write_text(entry.read_text(encoding="utf-8"), encoding="utf-8")
    return wiki


@pytest.fixture
def wiki_en(tmp_path, monkeypatch):
    wiki = _bootstrap_wiki(tmp_path, "en")
    monkeypatch.setenv("WIKI_PATH", str(wiki))
    monkeypatch.setenv("BOT_LANG", "en")
    monkeypatch.setenv("SCINOTES_JOURNAL_PATH", str(wiki / ".wiki_journal.jsonl"))
    # Force a fresh import so module-level WIKI_PATH gets re-read
    for k in list(sys.modules):
        if k.startswith("scinotes.server"):
            del sys.modules[k]
    return wiki


def test_init_templates_exist():
    """Templates are properly packaged for both languages."""
    for lang in ("en", "zh-CN"):
        d = files("scinotes.templates") / lang
        names = [e.name for e in d.iterdir() if e.name.endswith(".md")]
        assert "CLAUDE.md" in names, f"{lang}/CLAUDE.md missing"
        assert "memory.md" in names, f"{lang}/memory.md missing"
        # English uses ASCII names, Chinese uses CJK names
        if lang == "en":
            assert "paper_notes.md" in names
            assert "research_profile.md" in names
        else:
            assert any("论文笔记" in n for n in names)
            assert any("研究画像" in n for n in names)


def test_citation_key_formats(wiki_en):
    from scinotes.server import _citation_key

    cases = [
        (("Smith J, Doe A", "2024", "The Quantum Theory of Spectroscopy"), "smith2024quantum"),
        (("Smith, J. and Doe, A.", "2024", "On Quantum Theory"), "smith2024quantum"),
        (("John Smith, Jane Doe", "2024", "A Survey"), "smith2024survey"),
        (("Wang Y", "2023", "Metabolomics Review"), "wang2023metabolomics"),
        (("Wang, Y", "2023", "Metabolomics Review"), "wang2023metabolomics"),
        (("", "", ""), "anon0000untitled"),
    ]
    for inputs, expected in cases:
        assert _citation_key(*inputs) == expected, f"failed for {inputs}"


def test_paper_ingest_then_undo_byte_identical(wiki_en):
    from scinotes.server import paper_ingest, wiki_undo_last

    page = wiki_en / "paper_notes.md"
    before = page.read_text(encoding="utf-8")

    msg = paper_ingest("T", "A B", "2024", "", "", "abs", [])
    assert "smith" in msg.lower() or "wrote" in msg.lower()

    after = page.read_text(encoding="utf-8")
    assert after != before

    msg = wiki_undo_last()
    assert "Undone" in msg or "undone" in msg.lower()

    restored = page.read_text(encoding="utf-8")
    assert restored == before, "paper_ingest + undo not byte-identical"


def test_reading_queue_add_pop_undo(wiki_en):
    from scinotes.server import reading_queue_add, reading_queue_pop, wiki_undo_last

    page = wiki_en / "reading_queue.md"

    reading_queue_add("https://example.com/x", "test")
    assert "https://example.com/x" in page.read_text(encoding="utf-8")

    msg = reading_queue_pop()
    assert "https://example.com/x" in msg

    # add another so undo has something to act on
    reading_queue_add("https://example.com/y", "test2")
    wiki_undo_last()
    assert "https://example.com/y" not in page.read_text(encoding="utf-8")


def test_idea_capture_undo(wiki_en):
    from scinotes.server import idea_capture, wiki_undo_last

    page = wiki_en / "idea_box.md"
    before = page.read_text(encoding="utf-8")

    idea_capture("test idea", ["research_questions"])
    assert "test idea" in page.read_text(encoding="utf-8")

    wiki_undo_last()
    assert page.read_text(encoding="utf-8") == before


def test_experiment_log_new_project_then_undo(wiki_en):
    from scinotes.server import experiment_log, wiki_undo_last

    page = wiki_en / "experiment_log.md"
    before = page.read_text(encoding="utf-8")

    experiment_log("test_proj", "starting", "", "next")
    assert "## test_proj" in page.read_text(encoding="utf-8")

    wiki_undo_last()
    assert "## test_proj" not in page.read_text(encoding="utf-8")
    assert page.read_text(encoding="utf-8") == before


def test_research_profile_changelog_appends(wiki_en):
    from scinotes.server import update_research_profile

    page = wiki_en / "research_profile.md"

    update_research_profile(field="Exposomics", keywords="exposome,biomarker")
    text1 = page.read_text(encoding="utf-8")
    assert "Exposomics" in text1
    assert "BEGIN_CHANGELOG" in text1  # changelog block present

    update_research_profile(directions="A,B,C")
    text2 = page.read_text(encoding="utf-8")
    assert "Exposomics" in text2  # preserved
    assert "A,B,C" in text2

    # Two changelog entries
    assert text2.count("###") >= 2


def test_history_persistence(tmp_path, monkeypatch):
    from collections import deque

    monkeypatch.setenv("SCINOTES_HISTORY_FILE", str(tmp_path / "h.jsonl"))
    from scinotes.client.core import _load_history, _save_history

    h = deque(maxlen=20)
    h.append({"role": "user", "content": "hi"})
    h.append({"role": "assistant", "content": "hello"})
    _save_history(h)

    loaded = _load_history(20)
    assert list(loaded) == list(h)
