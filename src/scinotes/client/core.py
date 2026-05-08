"""WikiClient — connects to MCP servers, routes LLM calls, persists history."""

from __future__ import annotations

import json
import os
import re
import sys
from collections import deque
from contextlib import AsyncExitStack
from importlib.resources import files
from pathlib import Path

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# ---------------------------------------------------------------------------
# Wiki path & language
# ---------------------------------------------------------------------------
WIKI_PATH = Path(os.environ.get("WIKI_PATH", str(Path.cwd())))
BOT_LANG = os.environ.get("BOT_LANG", "en").lower()

# ---------------------------------------------------------------------------
# Optional API keys (passed through to MCP server subprocesses)
# ---------------------------------------------------------------------------
NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "")
SEMANTIC_SCHOLAR_API_KEY = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
ZOTERO_API_KEY = os.environ.get("ZOTERO_API_KEY", "")


# ---------------------------------------------------------------------------
# Model registry — built from env vars; only providers with credentials appear.
# ---------------------------------------------------------------------------
def _build_models() -> dict:
    models: dict = {}
    # Ollama is opt-out: include unless OLLAMA_DISABLE=1.
    # If unreachable at runtime, the call site will auto-remove it.
    if os.environ.get("OLLAMA_DISABLE", "").lower() not in ("1", "true", "yes"):
        models["ollama"] = {
            "provider": "ollama",
            "model": os.environ.get("OLLAMA_MODEL", "llama3.2:latest"),
            "base": os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
            "timeout": int(os.environ.get("OLLAMA_TIMEOUT", "120")),
        }
    if os.environ.get("ANTHROPIC_API_KEY"):
        models["claude"] = {
            "provider": "anthropic",
            "model": os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
            "base": os.environ.get("ANTHROPIC_API_BASE", "https://api.anthropic.com"),
            "key": os.environ["ANTHROPIC_API_KEY"],
            "timeout": int(os.environ.get("CLAUDE_TIMEOUT", "120")),
            "max_tokens": int(os.environ.get("CLAUDE_MAX_TOKENS", "4096")),
        }
    if os.environ.get("GLM_API_KEY"):
        models["glm"] = {
            "provider": "openai_compat",
            "model": os.environ.get("GLM_MODEL", "GLM-4"),
            "base": os.environ.get("GLM_API_BASE", "https://open.bigmodel.cn/api/paas/v4"),
            "key": os.environ["GLM_API_KEY"],
            "timeout": 90,
        }
    if os.environ.get("MIMO_API_KEY"):
        models["mimo"] = {
            "provider": "openai_compat",
            "model": os.environ.get("MIMO_MODEL", "mimo-v2.5-pro"),
            "base": os.environ.get("MIMO_API_BASE", "https://token-plan-cn.xiaomimimo.com/v1"),
            "key": os.environ["MIMO_API_KEY"],
            "timeout": int(os.environ.get("MIMO_TIMEOUT", "90")),
        }
    if os.environ.get("OPENAI_API_KEY"):
        models["openai"] = {
            "provider": "openai_compat",
            "model": os.environ.get("OPENAI_MODEL", "gpt-4o"),
            "base": os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1"),
            "key": os.environ["OPENAI_API_KEY"],
            "timeout": 90,
        }
    if os.environ.get("DEEPSEEK_API_KEY"):
        models["deepseek"] = {
            "provider": "openai_compat",
            "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
            "base": os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1"),
            "key": os.environ["DEEPSEEK_API_KEY"],
            "timeout": 90,
        }
    # Load extra models from <wiki>/models.json (added via /add-model slash command)
    extras_path = WIKI_PATH / "models.json"
    if extras_path.exists():
        try:
            extras = json.loads(extras_path.read_text(encoding="utf-8"))
            if isinstance(extras, list):
                for entry in extras:
                    name = entry.get("name")
                    if name and name not in models:
                        models[name] = {k: v for k, v in entry.items() if k != "name"}
        except Exception as e:
            print(f"[scinotes] failed to load {extras_path}: {e}", file=sys.stderr)
    return models


MODELS = _build_models()

# Smart defaults — if env unset, derive from MODELS so VPS users with only a cloud key
# don't have to manually edit DEFAULT_MODEL / FALLBACK_CHAIN.
_DEFAULT_ENV = os.environ.get("DEFAULT_MODEL", "").strip()
if _DEFAULT_ENV:
    DEFAULT_MODEL = _DEFAULT_ENV
elif "ollama" in MODELS:
    DEFAULT_MODEL = "ollama"  # privacy / free first
elif MODELS:
    DEFAULT_MODEL = next(iter(MODELS))
else:
    DEFAULT_MODEL = ""

_CHAIN_ENV = os.environ.get("FALLBACK_CHAIN", "").strip()
if _CHAIN_ENV:
    FALLBACK_CHAIN = [m.strip() for m in _CHAIN_ENV.split(",") if m.strip()]
else:
    # Default chain = all configured models, default first.
    # Ensures VPS users with cloud key don't get stuck on ollama failure.
    FALLBACK_CHAIN = ([DEFAULT_MODEL] if DEFAULT_MODEL else []) + sorted(
        m for m in MODELS if m != DEFAULT_MODEL
    )

# Filter to actually-registered models
if DEFAULT_MODEL and DEFAULT_MODEL not in MODELS:
    if MODELS:
        new_default = next(iter(MODELS))
        print(
            f"[scinotes] DEFAULT_MODEL={DEFAULT_MODEL!r} unavailable; using {new_default!r}",
            file=sys.stderr,
        )
        DEFAULT_MODEL = new_default
    else:
        print("[scinotes] no models configured; bot will not be able to answer.", file=sys.stderr)
FALLBACK_CHAIN = [m for m in FALLBACK_CHAIN if m in MODELS]


# ---------------------------------------------------------------------------
# System prompt loader (i18n)
# ---------------------------------------------------------------------------
def _load_system_prompt() -> str:
    # Allow fully custom prompt via env var (e.g. for lifenotes persona)
    custom_path = os.environ.get("SCINOTES_SYSTEM_PROMPT", "").strip()
    if custom_path:
        p = Path(custom_path)
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
        print(
            f"[scinotes] SCINOTES_SYSTEM_PROMPT={custom_path!r} not found, falling back to built-in",
            file=sys.stderr,
        )
    fname = "system.zh-CN.md" if BOT_LANG.startswith("zh") else "system.en.md"
    try:
        return (files("scinotes.prompts") / fname).read_text(encoding="utf-8").strip()
    except Exception as e:
        print(f"[scinotes] failed to load prompt {fname}: {e}", file=sys.stderr)
        return "You are a research assistant. Be concise and helpful."


SYSTEM_PROMPT = _load_system_prompt()


# ---------------------------------------------------------------------------
# History persistence (cross-restart)
# ---------------------------------------------------------------------------
HISTORY_FILE = Path(
    os.environ.get(
        "SCINOTES_HISTORY_FILE",
        str(WIKI_PATH / ".cache_history.jsonl"),
    )
)


def _load_history(maxlen: int) -> deque:
    h: deque = deque(maxlen=maxlen)
    if not HISTORY_FILE.exists():
        return h
    try:
        for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                h.append(json.loads(line))
    except Exception as e:
        print(f"[scinotes] history load failed: {e}", file=sys.stderr)
    return h


def _save_history(history: deque) -> None:
    try:
        tmp = HISTORY_FILE.with_suffix(".jsonl.tmp")
        tmp.write_text(
            "\n".join(json.dumps(m, ensure_ascii=False) for m in history) + "\n",
            encoding="utf-8",
        )
        tmp.replace(HISTORY_FILE)
    except Exception as e:
        print(f"[scinotes] history save failed: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# WikiClient
# ---------------------------------------------------------------------------
class WikiClient:
    def __init__(self, history_size: int = 20):
        self.sessions: list[ClientSession] = []
        self.exit_stack = AsyncExitStack()
        self.tools: list = []
        self.history = _load_history(history_size)
        if self.history:
            print(f"[scinotes] restored {len(self.history)} history entries", file=sys.stderr)

    # ----- MCP server connections -----
    async def connect(self) -> None:
        # 1. Local wiki MCP — always attached, runs our own server module
        local_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "scinotes.server"],
            env={
                **os.environ,
                "WIKI_PATH": str(WIKI_PATH),
                "BOT_LANG": BOT_LANG,
            },
        )

        # 2. PubMed MCP (free)
        pubmed_params = StdioServerParameters(
            command="npx",
            args=["-y", "@cyanheads/pubmed-mcp-server"],
            env={**os.environ, "NCBI_API_KEY": NCBI_API_KEY} if NCBI_API_KEY else os.environ,
        )

        # 3. Semantic Scholar MCP (free)
        scholar_params = StdioServerParameters(
            command="npx",
            args=["-y", "@xbghc/semanticscholar-mcp"],
            env={**os.environ, "SEMANTIC_SCHOLAR_API_KEY": SEMANTIC_SCHOLAR_API_KEY}
            if SEMANTIC_SCHOLAR_API_KEY
            else os.environ,
        )

        # 4. Zotero MCP — only if env present (web mode) or ZOTERO_LOCAL=true
        zotero_env = {**os.environ}
        zotero_attach = False
        if zotero_env.get("ZOTERO_LOCAL", "").lower() == "true":
            zotero_attach = True
        elif ZOTERO_API_KEY:
            zotero_attach = True
            if not zotero_env.get("ZOTERO_LIBRARY_ID") and zotero_env.get("ZOTERO_USER_ID"):
                zotero_env["ZOTERO_LIBRARY_ID"] = zotero_env["ZOTERO_USER_ID"]
                zotero_env.setdefault("ZOTERO_LIBRARY_TYPE", "user")
        zotero_params = StdioServerParameters(
            command="uvx",
            args=["--from", "zotero-mcp-server", "zotero-mcp", "serve"],
            env=zotero_env,
        )

        configs: list[tuple[str, StdioServerParameters]] = [
            ("local-wiki", local_params),
            ("pubmed", pubmed_params),
            ("semantic-scholar", scholar_params),
        ]
        if zotero_attach:
            configs.append(("zotero", zotero_params))

        for label, cfg in configs:
            try:
                print(f"[scinotes] connecting MCP server: {label} ({cfg.command})", file=sys.stderr)
                transport = await self.exit_stack.enter_async_context(stdio_client(cfg))
                read_stream, write_stream = transport
                session = await self.exit_stack.enter_async_context(ClientSession(read_stream, write_stream))
                await session.initialize()
                self.sessions.append(session)
                response = await session.list_tools()
                for tool in response.tools:
                    self.tools.append((tool, session))
            except Exception as e:
                print(f"[scinotes] MCP {label} failed: {e}", file=sys.stderr)

        names = [t[0].name for t in self.tools]
        print(f"[scinotes] connected; total tools: {len(names)}", file=sys.stderr)
        if names:
            print(f"[scinotes] tools: {', '.join(names)}", file=sys.stderr)

    async def call_tool(self, name: str, arguments: dict) -> str:
        for tool_obj, session in self.tools:
            if tool_obj.name == name:
                result = await session.call_tool(name, arguments)
                return result.content[0].text if result.content else ""
        return f"Tool {name} not found"

    def get_tools_for_llm(self) -> list[dict]:
        out = []
        for tool, _ in self.tools:
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": tool.inputSchema
                        if tool.inputSchema
                        else {
                            "type": "object",
                            "properties": {},
                        },
                    },
                }
            )
        return out

    # ----- Routing -----
    @staticmethod
    def parse_model_prefix(message: str) -> tuple[str | None, str]:
        m = re.match(r"^@([\w\-]+)\s+", message)
        if m and m.group(1) in MODELS:
            return m.group(1), message[m.end() :]
        return None, message

    def _model_chain(self, forced: str | None) -> list[str]:
        primary = forced or DEFAULT_MODEL
        chain = [primary] + [m for m in FALLBACK_CHAIN if m != primary]
        return [m for m in chain if m in MODELS]

    # ----- Slash commands (handled before LLM dispatch) -----
    async def _handle_slash_command(self, message: str) -> str | None:
        msg = message.strip()
        if not msg.startswith("/"):
            return None
        parts = msg.split(maxsplit=1)
        cmd = parts[0]
        args = parts[1] if len(parts) > 1 else ""
        if cmd == "/list-models":
            return self._cmd_list_models()
        if cmd == "/add-model":
            return self._cmd_add_model(args)
        if cmd == "/remove-model":
            return self._cmd_remove_model(args)
        if cmd == "/set-default":
            return self._cmd_set_default(args)
        if cmd == "/memory-stats":
            return self._cmd_memory_stats()
        if cmd == "/compact-memory":
            return await self._cmd_compact_memory(args)
        if cmd == "/help":
            return (
                "scinotes slash commands:\n"
                "  /list-models                                — list configured models\n"
                "  /add-model name=<id> provider=<openai_compat|anthropic|ollama> "
                "base=<url> key=<api_key> model=<model_name> [timeout=<sec>]\n"
                "  /remove-model <id>                          — remove a model from registry\n"
                "  /set-default <id>                           — set default model for this session\n"
                "  /memory-stats                               — size of memory.md (chars + token estimate)\n"
                "  /compact-memory [@model]                    — LLM-rewrite memory.md, "
                "merge dups / drop stale; archives original to .memory_archive_<ts>.md\n"
                "Models added/removed persist to <wiki>/models.json. Compaction archives "
                "to <wiki>/.memory_archive_*.md (gitignored)."
            )
        return None  # not a slash command we handle; treat as regular message

    def _cmd_list_models(self) -> str:
        if not MODELS:
            return "No models configured. Use /add-model to add one."
        lines = ["Configured models:"]
        for name, cfg in MODELS.items():
            mark = " (default)" if name == DEFAULT_MODEL else ""
            lines.append(f"  • @{name}{mark} — {cfg['provider']} → {cfg['model']}")
        lines.append(f"\nFallback chain: {' → '.join(FALLBACK_CHAIN) or '(empty)'}")
        return "\n".join(lines)

    def _cmd_add_model(self, args: str) -> str:
        kv: dict[str, str] = {}
        for token in args.split():
            if "=" in token:
                k, _, v = token.partition("=")
                kv[k.strip()] = v.strip()
        required = {"name", "provider", "base", "key", "model"}
        missing = required - set(kv.keys())
        if missing:
            return (
                f"Missing keys: {', '.join(sorted(missing))}\n"
                "Usage: /add-model name=<id> provider=<openai_compat|anthropic|ollama> "
                "base=<url> key=<api_key> model=<model_name> [timeout=<sec>]"
            )
        name = kv["name"]
        if not re.match(r"^[\w\-]+$", name):
            return f"Invalid name '{name}'. Use letters/digits/_/- only."
        if name in MODELS:
            return f"Model '{name}' already registered. Use /remove-model {name} first to replace."
        if kv["provider"] not in ("openai_compat", "anthropic", "ollama"):
            return f"Invalid provider '{kv['provider']}'. Must be one of: openai_compat, anthropic, ollama"

        entry: dict = {
            "provider": kv["provider"],
            "model": kv["model"],
            "base": kv["base"],
            "key": kv["key"],
            "timeout": int(kv.get("timeout", "90")),
        }
        if kv["provider"] == "anthropic":
            entry["max_tokens"] = int(kv.get("max_tokens", "4096"))

        # In-memory registry — usable immediately
        MODELS[name] = entry

        # Persist to <wiki>/models.json so future restarts see it
        extras_path = WIKI_PATH / "models.json"
        extras: list = []
        if extras_path.exists():
            try:
                extras = json.loads(extras_path.read_text(encoding="utf-8")) or []
            except Exception:
                extras = []
        extras = [e for e in extras if e.get("name") != name]
        extras.append({"name": name, **entry})
        try:
            extras_path.write_text(json.dumps(extras, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            return f"Added '{name}' in-memory but failed to persist: {e}"

        return (
            f"Added @{name} ({entry['provider']} → {entry['model']}). "
            f"Try `@{name} hello` next message. Persisted to {extras_path.name}."
        )

    def _cmd_remove_model(self, args: str) -> str:
        name = args.strip()
        if not name:
            return "Usage: /remove-model <id>"
        global DEFAULT_MODEL
        if name not in MODELS:
            return f"No model '{name}' registered."
        MODELS.pop(name, None)
        # Persist removal
        extras_path = WIKI_PATH / "models.json"
        if extras_path.exists():
            try:
                extras = json.loads(extras_path.read_text(encoding="utf-8")) or []
                extras = [e for e in extras if e.get("name") != name]
                extras_path.write_text(json.dumps(extras, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception as e:
                return f"Removed in-memory but failed to update {extras_path.name}: {e}"
        if DEFAULT_MODEL == name:
            DEFAULT_MODEL = next(iter(MODELS), "")
            return f"Removed @{name}. Default reset to @{DEFAULT_MODEL or '(none)'}."
        return f"Removed @{name}."

    def _cmd_set_default(self, args: str) -> str:
        global DEFAULT_MODEL
        name = args.strip().lstrip("@")
        if not name:
            return "Usage: /set-default <id>"
        if name not in MODELS:
            return f"No model '{name}' in registry. Use /list-models to see available."
        DEFAULT_MODEL = name
        return f"Default model set to @{name}. (Per-session; to persist, set DEFAULT_MODEL in .env.)"

    def _cmd_memory_stats(self) -> str:
        memory_file = WIKI_PATH / "memory.md"
        if not memory_file.exists():
            return "memory.md doesn't exist yet — nothing to stat."
        text = memory_file.read_text(encoding="utf-8")
        n_lines = sum(1 for line in text.splitlines() if line.strip().startswith("- "))
        chars = len(text)
        # Rough heuristic: 3 chars/token (mixed CJK + ASCII). Real GPT-tokenizer would be more accurate.
        tokens_est = chars // 3
        warning = ""
        if tokens_est > 2000:
            warning = (
                f"\n⚠ memory.md is ~{tokens_est} tokens; this is loaded into EVERY conversation's "
                "system prompt. Consider running /compact-memory."
            )
        return f"memory.md: {n_lines} fact entries, {chars} chars (~{tokens_est} tokens).{warning}"

    async def _cmd_compact_memory(self, args: str) -> str:
        """Rewrite memory.md via the LLM: merge duplicates, drop stale, keep most-recent timestamps.
        Archives the original to <wiki>/.memory_archive_<timestamp>.md before overwriting.
        Optional arg: @<model> to pick which model to compact with (defaults to DEFAULT_MODEL).
        """
        import datetime as _dt

        memory_file = WIKI_PATH / "memory.md"
        if not memory_file.exists():
            return "memory.md doesn't exist."
        original = memory_file.read_text(encoding="utf-8").strip()
        if not original:
            return "memory.md is empty — nothing to compact."

        chars_before = len(original)
        if chars_before < 500:
            return f"memory.md is only {chars_before} chars — too small to bother compacting."

        # Pick model
        target_model = args.strip().lstrip("@") if args.strip() else DEFAULT_MODEL
        if not target_model or target_model not in MODELS:
            return (
                f"Model '{target_model or '(default)'}' not in registry. "
                "Use /list-models to see configured models, or pass /compact-memory @<model>."
            )

        # Archive
        ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_path = WIKI_PATH / f".memory_archive_{ts}.md"
        try:
            archive_path.write_text(original + "\n", encoding="utf-8")
        except Exception as e:
            return f"Refusing to compact: archive write failed ({e}). memory.md untouched."

        prompt = (
            "You are compacting a personal long-term memory file for an AI assistant. "
            "Each line `- [timestamp] fact` is one fact the user wanted the assistant to remember "
            "(loaded into every conversation's system prompt — so brevity matters).\n\n"
            "Compaction rules:\n"
            "1. KEEP all user-specific preferences, identity facts, persistent rules.\n"
            "2. MERGE duplicate or near-duplicate facts into a single line.\n"
            "3. On contradiction, keep the MOST RECENT (highest timestamp) version, drop earlier ones.\n"
            "4. DROP trivially-stale items (test entries, expired one-off commitments, dated tasks long past).\n"
            "5. PRESERVE the timestamp of the most-recent occurrence of each surviving fact.\n"
            "6. PRESERVE the original `# Long-term memory` (or equivalent) header at the top.\n"
            "7. Output ONLY the compacted markdown, exactly as it should be written to disk. "
            "No code fences, no commentary, no preamble.\n\n"
            "=== ORIGINAL memory.md ===\n"
            f"{original}\n"
            "=== COMPACTED OUTPUT ==="
        )

        try:
            response = await self._call_model(target_model, [{"role": "user", "content": prompt}], [])
        except Exception as e:
            return f"Compaction failed via @{target_model}: {e}. Archive preserved at {archive_path.name}."

        new_text = (response.get("message", {}) or {}).get("content", "").strip()
        if not new_text:
            return f"Model returned empty content. memory.md unchanged. Archive: {archive_path.name}."

        # Strip accidental code fences
        if new_text.startswith("```"):
            lines = new_text.splitlines()
            new_text = "\n".join(lines[1:-1] if len(lines) > 2 else lines).strip()

        chars_after = len(new_text)
        # Sanity check: must be smaller, otherwise something went wrong
        if chars_after >= chars_before:
            return (
                f"Compaction did not reduce size ({chars_after} ≥ {chars_before}). "
                f"memory.md unchanged. Archive: {archive_path.name}."
            )
        # Sanity check: must not be suspiciously tiny (model misbehaved)
        if chars_after < chars_before * 0.1:
            return (
                f"Compaction shrank too aggressively ({chars_after} < 10% of {chars_before}). "
                f"Refusing to overwrite. Archive: {archive_path.name}; "
                "review and apply manually if it actually looks right."
            )

        memory_file.write_text(new_text + "\n", encoding="utf-8")
        saved_pct = round(100 * (1 - chars_after / chars_before))
        return (
            f"✓ Compacted memory.md via @{target_model}: "
            f"{chars_before} → {chars_after} chars ({saved_pct}% smaller). "
            f"Original archived at {archive_path.name} (gitignored)."
        )

    # ----- Chat loop -----
    async def chat(self, user_message: str) -> str:
        # Slash commands run before LLM dispatch
        slash_result = await self._handle_slash_command(user_message)
        if slash_result is not None:
            return slash_result

        forced_model, user_message = self.parse_model_prefix(user_message)

        # Compose system prompt: base + memory.md + research_profile (basic-info block) + dynamic models line
        sys_parts = [SYSTEM_PROMPT]

        memory_file = WIKI_PATH / "memory.md"
        if memory_file.exists():
            try:
                memory_text = memory_file.read_text(encoding="utf-8").strip()
                if memory_text:
                    sys_parts.append("\n### Long-term memory (always loaded)\n" + memory_text)
            except Exception:
                pass

        sys_parts.append(
            f"\n### Available models\nThe user may prefix messages with @<model>. "
            f"Currently available: {', '.join(sorted(MODELS.keys()))}. "
            f"Default: {DEFAULT_MODEL}."
        )
        current_sys_prompt = "\n".join(sys_parts)

        full_messages: list[dict] = [{"role": "system", "content": current_sys_prompt}]
        full_messages.extend(list(self.history))
        full_messages.append({"role": "user", "content": user_message})

        tools = self.get_tools_for_llm()
        chain = self._model_chain(forced_model)
        if not chain:
            return "[scinotes] error: no LLM is configured. Edit your .env and add at least one API key."

        final_response_content = ""
        for _ in range(5):
            response = None
            last_err: Exception | None = None
            for idx, model_id in enumerate(chain):
                try:
                    response = await self._call_model(model_id, full_messages, tools)
                    if response:
                        if idx > 0:
                            print(
                                f"[scinotes] [Fallback] primary {chain[0]} failed, used {model_id}",
                                file=sys.stderr,
                            )
                        break
                except Exception as e:
                    last_err = e
                    print(f"[scinotes] model {model_id} failed: {e}", file=sys.stderr)
                    continue

            if not response:
                return f"[scinotes] all models failed. Last error: {last_err}"

            msg = response["message"]
            if not msg.get("tool_calls"):
                final_response_content = msg.get("content", "")
                break

            full_messages.append(msg)
            for tc in msg["tool_calls"]:
                fn_name = tc["function"]["name"]
                fn_args = tc["function"]["arguments"]
                if isinstance(fn_args, str):
                    try:
                        fn_args = json.loads(fn_args)
                    except Exception:
                        fn_args = {}
                print(f"[scinotes] tool: {fn_name}", file=sys.stderr)
                try:
                    result = await self.call_tool(fn_name, fn_args)
                except Exception as e:
                    result = f"tool call failed: {e}"
                tool_msg: dict = {"role": "tool", "content": result}
                if "id" in tc:
                    tool_msg["tool_call_id"] = tc["id"]
                full_messages.append(tool_msg)

        if not final_response_content:
            final_response_content = "(empty response)"

        self.history.append({"role": "user", "content": user_message})
        self.history.append({"role": "assistant", "content": final_response_content})
        _save_history(self.history)

        return final_response_content

    # ----- Provider dispatch -----
    async def _call_model(self, model_id: str, messages: list, tools: list) -> dict:
        cfg = MODELS.get(model_id)
        if cfg is None:
            raise ValueError(f"Unknown model: {model_id}")
        provider = cfg["provider"]
        try:
            if provider == "ollama":
                return await self._ollama_chat(messages, tools, cfg)
            if provider == "openai_compat":
                return await self._openai_compat_chat(messages, tools, cfg)
            if provider == "anthropic":
                return await self._anthropic_chat(messages, tools, cfg)
            raise ValueError(f"Unknown provider: {provider}")
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            # Provider unreachable at network level → unhealthy; remove for this session
            # so subsequent turns skip it instead of repeatedly timing out.
            global DEFAULT_MODEL
            if model_id in MODELS:
                print(
                    f"[scinotes] {model_id} unreachable ({type(e).__name__}: {e}); "
                    f"removing from registry for this session.",
                    file=sys.stderr,
                )
                MODELS.pop(model_id, None)
                if DEFAULT_MODEL == model_id:
                    DEFAULT_MODEL = next(iter(MODELS), "")
                    print(
                        f"[scinotes] default model reset to @{DEFAULT_MODEL or '(none)'}",
                        file=sys.stderr,
                    )
            raise

    async def _ollama_chat(self, messages: list, tools: list, cfg: dict) -> dict:
        async with httpx.AsyncClient(timeout=cfg.get("timeout", 120)) as client:
            payload = {"model": cfg["model"], "messages": messages, "stream": False}
            if tools:
                payload["tools"] = tools
            resp = await client.post(f"{cfg['base']}/api/chat", json=payload)
            resp.raise_for_status()
            return resp.json()

    async def _openai_compat_chat(self, messages: list, tools: list, cfg: dict) -> dict:
        if not cfg.get("key"):
            raise RuntimeError(f"Model {cfg['model']} has no API key configured")
        async with httpx.AsyncClient(timeout=cfg.get("timeout", 90)) as client:
            payload: dict = {"model": cfg["model"], "messages": messages}
            if tools:
                payload["tools"] = tools
            headers = {
                "Authorization": f"Bearer {cfg['key']}",
                "Content-Type": "application/json",
            }
            resp = await client.post(f"{cfg['base']}/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return {"message": data["choices"][0]["message"]}

    async def _anthropic_chat(self, messages: list, tools: list, cfg: dict) -> dict:
        if not cfg.get("key"):
            raise RuntimeError("ANTHROPIC_API_KEY not configured")

        # OpenAI-style → Anthropic-native conversion
        system_text = ""
        anthropic_messages: list[dict] = []
        for m in messages:
            role = m.get("role")
            if role == "system":
                system_text = (system_text + "\n\n" + (m.get("content") or "")).strip()
                continue
            if role == "tool":
                anthropic_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.get("tool_call_id", ""),
                                "content": m.get("content", "") or "",
                            }
                        ],
                    }
                )
                continue
            if role == "assistant" and m.get("tool_calls"):
                blocks: list[dict] = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for tc in m["tool_calls"]:
                    args = tc["function"]["arguments"]
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.get("id", f"toolu_{len(anthropic_messages)}"),
                            "name": tc["function"]["name"],
                            "input": args or {},
                        }
                    )
                anthropic_messages.append({"role": "assistant", "content": blocks})
                continue
            anthropic_messages.append({"role": role, "content": m.get("content", "") or ""})

        anthropic_tools = []
        for t in tools or []:
            f = t["function"]
            anthropic_tools.append(
                {
                    "name": f["name"],
                    "description": f.get("description", ""),
                    "input_schema": f.get("parameters", {"type": "object", "properties": {}}),
                }
            )

        payload: dict = {
            "model": cfg["model"],
            "max_tokens": cfg.get("max_tokens", 4096),
            "messages": anthropic_messages,
        }
        if system_text:
            payload["system"] = system_text
        if anthropic_tools:
            payload["tools"] = anthropic_tools

        headers = {
            "x-api-key": cfg["key"],
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=cfg.get("timeout", 120)) as client:
            resp = await client.post(f"{cfg['base']}/v1/messages", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        out_msg: dict = {"role": "assistant", "content": ""}
        text_parts: list[str] = []
        tool_calls: list[dict] = []
        for block in data.get("content", []):
            t = block.get("type")
            if t == "text":
                text_parts.append(block.get("text", ""))
            elif t == "tool_use":
                tool_calls.append(
                    {
                        "id": block.get("id"),
                        "type": "function",
                        "function": {
                            "name": block.get("name"),
                            "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                        },
                    }
                )
        if text_parts:
            out_msg["content"] = "\n".join(text_parts)
        if tool_calls:
            out_msg["tool_calls"] = tool_calls
        return {"message": out_msg}

    async def close(self) -> None:
        await self.exit_stack.aclose()
