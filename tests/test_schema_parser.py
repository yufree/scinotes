"""Tests for CLAUDE.md schema → PAGE_CATEGORIES auto-discovery."""

from __future__ import annotations

import sys
from pathlib import Path


def _fresh_server(monkeypatch, wiki: Path):
    monkeypatch.setenv("WIKI_PATH", str(wiki))
    monkeypatch.setenv("BOT_LANG", "en")
    monkeypatch.setenv("SCINOTES_JOURNAL_PATH", str(wiki / ".wiki_journal.jsonl"))
    # Clear both scinotes package and submodule from sys.modules so a fresh import
    # actually re-reads CLAUDE.md from the new WIKI_PATH (otherwise the cached
    # `scinotes` package keeps the old `server` attribute attached).
    for k in list(sys.modules):
        if k == "scinotes" or k.startswith("scinotes."):
            del sys.modules[k]
    from scinotes import server  # type: ignore

    return server


def test_default_when_no_claude_md(tmp_path, monkeypatch):
    server = _fresh_server(monkeypatch, tmp_path)
    # No CLAUDE.md → falls back to default research layer
    assert server.PAGE_CATEGORIES == server._DEFAULT_PAGE_CATEGORIES
    assert "research" in server.PAGE_CATEGORIES


def test_default_when_no_table(tmp_path, monkeypatch):
    (tmp_path / "CLAUDE.md").write_text(
        "# My wiki\n\nFreeform documentation, no schema table.\n", encoding="utf-8"
    )
    server = _fresh_server(monkeypatch, tmp_path)
    assert server.PAGE_CATEGORIES == server._DEFAULT_PAGE_CATEGORIES


def test_parses_english_template(tmp_path, monkeypatch):
    """The default English template's table should be parsed back into a single layer."""
    (tmp_path / "CLAUDE.md").write_text(
        """# Wiki

| Layer | Purpose | Pages |
|---|---|---|
| **research** | scinotes-managed research output | paper_notes, reading_queue, research_questions, experiment_log, idea_box, research_profile |
""",
        encoding="utf-8",
    )
    server = _fresh_server(monkeypatch, tmp_path)
    assert "research" in server.PAGE_CATEGORIES
    assert server.PAGE_CATEGORIES["research"] == [
        "paper_notes",
        "reading_queue",
        "research_questions",
        "experiment_log",
        "idea_box",
        "research_profile",
    ]


def test_parses_chinese_eight_layer_schema(tmp_path, monkeypatch):
    """Personal-taxonomy use case: 8 Chinese layers should all be discovered."""
    (tmp_path / "CLAUDE.md").write_text(
        """# 个人 wiki — schema

## 页面分类

| 层级 | 说明 | 页面 |
|------|------|------|
| **资料源** | 信息收集渠道与工具 | 主流信息来源、自主信息来源、网络工具 |
| **基线知识** | 原理性、跨学科的基础认知 | 复杂系统、物理学、环境与健康、经济学、心理学 |
| **历史** | 过往发生的事实 | 中国历史、日本历史、欧美历史、经济史 |
| **现状** | 正在发生的事实 | 贫富差距、人口、教育、房价、全球化 |
| **观点** | 对事实的看法与经验 | 科学技术、法律、财经、传媒 |
| **未来** | 对未来的推演与判断 | 未来 |
| **科研** | 科研活动产出 | 论文笔记、阅读队列、研究问题、实验日志、想法库、研究画像 |
| **特殊** | 特殊页面 | 一本道、名人堂、资料库 |

(more text below...)
""",
        encoding="utf-8",
    )
    server = _fresh_server(monkeypatch, tmp_path)
    assert set(server.PAGE_CATEGORIES.keys()) == {
        "资料源",
        "基线知识",
        "历史",
        "现状",
        "观点",
        "未来",
        "科研",
        "特殊",
    }
    assert "论文笔记" in server.PAGE_CATEGORIES["科研"]
    assert "中国历史" in server.PAGE_CATEGORIES["历史"]
    assert "一本道" in server.PAGE_CATEGORIES["特殊"]


def test_skips_separator_row(tmp_path, monkeypatch):
    (tmp_path / "CLAUDE.md").write_text(
        """| 层级 | 说明 | 页面 |
|:---|:---:|---:|
| **research** | foo | a, b, c |
""",
        encoding="utf-8",
    )
    server = _fresh_server(monkeypatch, tmp_path)
    assert server.PAGE_CATEGORIES == {"research": ["a", "b", "c"]}


def test_strips_bold_and_backticks(tmp_path, monkeypatch):
    (tmp_path / "CLAUDE.md").write_text(
        """| Layer | Pages |
|---|---|
| **a** | `x`, `y`, `z` |
""",
        encoding="utf-8",
    )
    server = _fresh_server(monkeypatch, tmp_path)
    # Two-column table also works as long as last column is pages
    assert server.PAGE_CATEGORIES == {"a": ["x", "y", "z"]}


def test_handles_table_without_purpose_column(tmp_path, monkeypatch):
    (tmp_path / "CLAUDE.md").write_text(
        """| Layer | Pages |
|---|---|
| research | paper_notes, idea_box |
""",
        encoding="utf-8",
    )
    server = _fresh_server(monkeypatch, tmp_path)
    assert server.PAGE_CATEGORIES == {"research": ["paper_notes", "idea_box"]}


def test_ignores_table_unrelated_to_schema(tmp_path, monkeypatch):
    (tmp_path / "CLAUDE.md").write_text(
        """| File | Description |
|---|---|
| README | docs |
""",
        encoding="utf-8",
    )
    server = _fresh_server(monkeypatch, tmp_path)
    # No "Layer/层级 + Pages/页面" header → falls back to default
    assert server.PAGE_CATEGORIES == server._DEFAULT_PAGE_CATEGORIES


def test_pages_split_on_chinese_comma_and_dunhao(tmp_path, monkeypatch):
    (tmp_path / "CLAUDE.md").write_text(
        """| 层级 | 页面 |
|---|---|
| 测 | a、b,c,d |
""",
        encoding="utf-8",
    )
    server = _fresh_server(monkeypatch, tmp_path)
    assert server.PAGE_CATEGORIES == {"测": ["a", "b", "c", "d"]}
