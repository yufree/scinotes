"""Tests for model registry, slash commands, and runtime self-healing."""

from __future__ import annotations

import asyncio
import json
import sys


def _slash(client, message: str):
    """Helper: synchronously run the now-async _handle_slash_command."""
    return asyncio.run(client._handle_slash_command(message))


def _fresh_core(monkeypatch, **env):
    """Reload scinotes.client.core with a fresh env. Returns the module."""
    for k in (
        "DEFAULT_MODEL",
        "FALLBACK_CHAIN",
        "OLLAMA_DISABLE",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GLM_API_KEY",
        "DEEPSEEK_API_KEY",
        "MIMO_API_KEY",
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


def test_default_when_only_ollama(monkeypatch, tmp_path):
    core = _fresh_core(monkeypatch, WIKI_PATH=str(tmp_path))
    assert "ollama" in core.MODELS
    assert core.DEFAULT_MODEL == "ollama"
    assert core.FALLBACK_CHAIN == ["ollama"]


def test_default_when_vps_with_only_anthropic(monkeypatch, tmp_path):
    """VPS scenario: no ollama wanted, only ANTHROPIC_API_KEY set."""
    core = _fresh_core(
        monkeypatch,
        WIKI_PATH=str(tmp_path),
        OLLAMA_DISABLE="1",
        ANTHROPIC_API_KEY="sk-ant-test",
    )
    assert "ollama" not in core.MODELS
    assert "claude" in core.MODELS
    assert core.DEFAULT_MODEL == "claude"
    assert core.FALLBACK_CHAIN == ["claude"]


def test_default_when_ollama_plus_cloud(monkeypatch, tmp_path):
    """Hybrid: ollama + claude both configured. Default = ollama (free), fallback to claude."""
    core = _fresh_core(
        monkeypatch,
        WIKI_PATH=str(tmp_path),
        ANTHROPIC_API_KEY="sk-ant-test",
    )
    assert core.DEFAULT_MODEL == "ollama"
    assert "claude" in core.FALLBACK_CHAIN
    assert "ollama" in core.FALLBACK_CHAIN


def test_models_json_extras_loaded(monkeypatch, tmp_path):
    """Models added to <wiki>/models.json should appear in MODELS."""
    extras = [
        {
            "name": "kimi",
            "provider": "openai_compat",
            "model": "moonshot-v1-128k",
            "base": "https://api.moonshot.cn/v1",
            "key": "sk-test",
            "timeout": 90,
        }
    ]
    (tmp_path / "models.json").write_text(json.dumps(extras), encoding="utf-8")
    core = _fresh_core(monkeypatch, WIKI_PATH=str(tmp_path), OLLAMA_DISABLE="1")
    assert "kimi" in core.MODELS
    assert core.MODELS["kimi"]["base"] == "https://api.moonshot.cn/v1"


def test_slash_add_model_persists(monkeypatch, tmp_path):
    core = _fresh_core(monkeypatch, WIKI_PATH=str(tmp_path), OLLAMA_DISABLE="1", ANTHROPIC_API_KEY="sk-test")
    client = core.WikiClient.__new__(core.WikiClient)  # bypass __init__
    client.history = None  # not used by slash commands

    # Add a kimi model
    msg = (
        "/add-model name=kimi provider=openai_compat "
        "base=https://api.moonshot.cn/v1 key=sk-xxx model=moonshot-v1-128k"
    )
    result = _slash(client, msg)
    assert "Added @kimi" in result, result
    assert "kimi" in core.MODELS

    extras_path = tmp_path / "models.json"
    assert extras_path.exists()
    extras = json.loads(extras_path.read_text(encoding="utf-8"))
    assert any(e["name"] == "kimi" for e in extras)


def test_slash_add_model_validates_required(monkeypatch, tmp_path):
    core = _fresh_core(monkeypatch, WIKI_PATH=str(tmp_path), OLLAMA_DISABLE="1", ANTHROPIC_API_KEY="sk-test")
    client = core.WikiClient.__new__(core.WikiClient)
    client.history = None
    result = _slash(client, "/add-model name=foo")
    assert "Missing keys" in result


def test_slash_list_and_remove(monkeypatch, tmp_path):
    extras = [
        {
            "name": "kimi",
            "provider": "openai_compat",
            "model": "moonshot-v1-128k",
            "base": "https://api.moonshot.cn/v1",
            "key": "sk-test",
            "timeout": 90,
        }
    ]
    (tmp_path / "models.json").write_text(json.dumps(extras), encoding="utf-8")
    core = _fresh_core(monkeypatch, WIKI_PATH=str(tmp_path), OLLAMA_DISABLE="1", ANTHROPIC_API_KEY="sk-test")
    client = core.WikiClient.__new__(core.WikiClient)
    client.history = None

    listing = _slash(client, "/list-models")
    assert "@kimi" in listing
    assert "@claude" in listing

    result = _slash(client, "/remove-model kimi")
    assert "Removed @kimi" in result
    assert "kimi" not in core.MODELS
    extras_after = json.loads((tmp_path / "models.json").read_text(encoding="utf-8"))
    assert all(e["name"] != "kimi" for e in extras_after)


def test_slash_set_default(monkeypatch, tmp_path):
    core = _fresh_core(monkeypatch, WIKI_PATH=str(tmp_path), ANTHROPIC_API_KEY="sk-test")
    client = core.WikiClient.__new__(core.WikiClient)
    client.history = None

    assert core.DEFAULT_MODEL == "ollama"
    result = _slash(client, "/set-default claude")
    assert "set to @claude" in result
    assert core.DEFAULT_MODEL == "claude"


def test_slash_help(monkeypatch, tmp_path):
    core = _fresh_core(monkeypatch, WIKI_PATH=str(tmp_path))
    client = core.WikiClient.__new__(core.WikiClient)
    client.history = None
    result = _slash(client, "/help")
    assert "/add-model" in result
    assert "/list-models" in result


def test_non_slash_passes_through(monkeypatch, tmp_path):
    core = _fresh_core(monkeypatch, WIKI_PATH=str(tmp_path))
    client = core.WikiClient.__new__(core.WikiClient)
    client.history = None
    result = _slash(client, "hello world")
    assert result is None  # not a slash command


def test_unknown_slash_returns_none(monkeypatch, tmp_path):
    """Unknown slash command falls through to LLM (in case it's user content)."""
    core = _fresh_core(monkeypatch, WIKI_PATH=str(tmp_path))
    client = core.WikiClient.__new__(core.WikiClient)
    client.history = None
    result = _slash(client, "/random-thing arg")
    assert result is None
