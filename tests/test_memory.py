"""Tests for /memory-stats and /compact-memory slash commands."""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock


def _fresh_core(monkeypatch, **env):
    for k in (
        "DEFAULT_MODEL",
        "FALLBACK_CHAIN",
        "OLLAMA_DISABLE",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "WIKI_PATH",
    ):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    for mod in list(sys.modules):
        if mod.startswith("scinotes.client.core") or mod == "scinotes.client":
            del sys.modules[mod]
    from scinotes.client import core  # type: ignore

    return core


def _slash(client, message: str):
    return asyncio.run(client._handle_slash_command(message))


def _make_client(core):
    c = core.WikiClient.__new__(core.WikiClient)
    c.history = None  # not used by slash commands
    return c


def test_memory_stats_no_file(monkeypatch, tmp_path):
    core = _fresh_core(monkeypatch, WIKI_PATH=str(tmp_path))
    out = _slash(_make_client(core), "/memory-stats")
    assert "doesn't exist" in out


def test_memory_stats_reports_size(monkeypatch, tmp_path):
    (tmp_path / "memory.md").write_text(
        "# Long-term memory\n\n"
        + "\n".join(f"- [2026-04-{d:02} 10:00] fact number {d}" for d in range(1, 21)),
        encoding="utf-8",
    )
    core = _fresh_core(monkeypatch, WIKI_PATH=str(tmp_path))
    out = _slash(_make_client(core), "/memory-stats")
    assert "20 fact entries" in out
    assert "tokens" in out


def test_memory_stats_warns_when_large(monkeypatch, tmp_path):
    big = "# Long-term memory\n\n" + "\n".join(
        f"- [2026-04-01 10:00] this is a very wordy fact number {i} " * 10 for i in range(200)
    )
    (tmp_path / "memory.md").write_text(big, encoding="utf-8")
    core = _fresh_core(monkeypatch, WIKI_PATH=str(tmp_path))
    out = _slash(_make_client(core), "/memory-stats")
    assert "/compact-memory" in out
    assert "loaded into EVERY conversation" in out


def test_compact_memory_no_file(monkeypatch, tmp_path):
    core = _fresh_core(monkeypatch, WIKI_PATH=str(tmp_path), ANTHROPIC_API_KEY="sk-test", OLLAMA_DISABLE="1")
    out = _slash(_make_client(core), "/compact-memory")
    assert "doesn't exist" in out


def test_compact_memory_too_small_no_op(monkeypatch, tmp_path):
    (tmp_path / "memory.md").write_text(
        "# Long-term memory\n\n- [2026-04-01 10:00] tiny fact\n", encoding="utf-8"
    )
    core = _fresh_core(monkeypatch, WIKI_PATH=str(tmp_path), ANTHROPIC_API_KEY="sk-test", OLLAMA_DISABLE="1")
    out = _slash(_make_client(core), "/compact-memory")
    assert "too small" in out


def test_compact_memory_archives_and_writes(monkeypatch, tmp_path):
    """Happy path: model returns smaller text, compaction succeeds, original archived."""
    big = "# Long-term memory\n\n" + "\n".join(
        f"- [2026-04-{(i % 28) + 1:02} 10:00] verbose fact number {i} with a lot of repeated text"
        for i in range(50)
    )
    memory_file = tmp_path / "memory.md"
    memory_file.write_text(big, encoding="utf-8")
    chars_before = len(big)

    core = _fresh_core(monkeypatch, WIKI_PATH=str(tmp_path), ANTHROPIC_API_KEY="sk-test", OLLAMA_DISABLE="1")

    # Stub _call_model to return a plausibly-compacted response (~30% size — passes both guards)
    compacted = "# Long-term memory\n\n" + "\n".join(
        f"- [2026-04-28 10:00] consolidated fact group {i}" for i in range(20)
    )
    fake_call = AsyncMock(return_value={"message": {"content": compacted}})
    monkeypatch.setattr(core.WikiClient, "_call_model", fake_call)

    client = _make_client(core)
    out = _slash(client, "/compact-memory")

    assert "✓ Compacted memory.md" in out
    assert "smaller" in out
    # File overwritten
    new_content = memory_file.read_text(encoding="utf-8").strip()
    assert "consolidated fact group" in new_content
    assert len(new_content) < chars_before
    # Archive exists
    archives = list(tmp_path.glob(".memory_archive_*.md"))
    assert len(archives) == 1
    assert archives[0].read_text(encoding="utf-8").strip() == big.strip()


def test_compact_memory_rejects_non_shrinking_output(monkeypatch, tmp_path):
    """If LLM returns same-or-bigger text, refuse to overwrite."""
    big = "# Long-term memory\n\n" + "\n".join(f"- [2026-04-01 10:00] fact {i}" for i in range(60))
    memory_file = tmp_path / "memory.md"
    memory_file.write_text(big, encoding="utf-8")

    core = _fresh_core(monkeypatch, WIKI_PATH=str(tmp_path), ANTHROPIC_API_KEY="sk-test", OLLAMA_DISABLE="1")

    # Model returns the same content (worst-case: model just echoed input)
    fake_call = AsyncMock(return_value={"message": {"content": big + "\nextra junk"}})
    monkeypatch.setattr(core.WikiClient, "_call_model", fake_call)

    out = _slash(_make_client(core), "/compact-memory")
    assert "did not reduce size" in out
    # File untouched
    assert memory_file.read_text(encoding="utf-8") == big
    # Archive still created (safety)
    assert list(tmp_path.glob(".memory_archive_*.md"))


def test_compact_memory_rejects_over_aggressive_shrink(monkeypatch, tmp_path):
    """If LLM returns suspiciously tiny output (<10% of original), refuse."""
    big = "# Long-term memory\n\n" + "\n".join(f"- [2026-04-01 10:00] fact {i}" for i in range(60))
    memory_file = tmp_path / "memory.md"
    memory_file.write_text(big, encoding="utf-8")

    core = _fresh_core(monkeypatch, WIKI_PATH=str(tmp_path), ANTHROPIC_API_KEY="sk-test", OLLAMA_DISABLE="1")

    # Model returns one line
    fake_call = AsyncMock(return_value={"message": {"content": "# Long-term memory\n"}})
    monkeypatch.setattr(core.WikiClient, "_call_model", fake_call)

    out = _slash(_make_client(core), "/compact-memory")
    assert "shrank too aggressively" in out
    assert memory_file.read_text(encoding="utf-8") == big


def test_compact_memory_strips_code_fences(monkeypatch, tmp_path):
    """Some models wrap output in ```markdown ... ```; we strip that."""
    big = "# Long-term memory\n\n" + "\n".join(
        f"- [2026-04-01 10:00] verbose fact {i} with extra text" for i in range(50)
    )
    memory_file = tmp_path / "memory.md"
    memory_file.write_text(big, encoding="utf-8")

    core = _fresh_core(monkeypatch, WIKI_PATH=str(tmp_path), ANTHROPIC_API_KEY="sk-test", OLLAMA_DISABLE="1")

    # Wrapped in fence — should be stripped before write
    wrapped = "```markdown\n# Long-term memory\n\n- [2026-04-28 10:00] compacted\n```"
    fake_call = AsyncMock(return_value={"message": {"content": wrapped}})
    monkeypatch.setattr(core.WikiClient, "_call_model", fake_call)

    _slash(_make_client(core), "/compact-memory")
    new_content = memory_file.read_text(encoding="utf-8")
    assert "```" not in new_content
    assert "# Long-term memory" in new_content


def test_compact_memory_invalid_model(monkeypatch, tmp_path):
    big = "# Long-term memory\n\n" + "\n".join(f"- [2026-04-01 10:00] fact {i}" for i in range(60))
    (tmp_path / "memory.md").write_text(big, encoding="utf-8")
    core = _fresh_core(monkeypatch, WIKI_PATH=str(tmp_path), ANTHROPIC_API_KEY="sk-test", OLLAMA_DISABLE="1")
    out = _slash(_make_client(core), "/compact-memory @nonexistent")
    assert "not in registry" in out
