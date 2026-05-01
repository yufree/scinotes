# ARCHITECTURE

How scinotes hangs together. Useful if you want to extend it or debug a sticky issue.

## High-level

```
                          ┌─────────────────┐
   user types in IM ────► │  frontend(s)    │
                          │ telegram/qq/cli │
                          └────────┬────────┘
                                   │ plain text or @model-prefixed text
                                   ▼
                       ┌──────────────────────────┐
                       │      WikiClient.chat     │
                       │ - parse @model prefix    │
                       │ - load memory.md         │
                       │ - dispatch via registry  │
                       └────────┬─────────────────┘
                                │
              ┌─────────────────┼──────────────────┐
              ▼                 ▼                  ▼
        ┌──────────┐      ┌─────────┐         ┌──────────┐
        │ ollama   │      │ claude  │   …     │ openai_  │
        │ provider │      │provider │         │ compat   │
        └────┬─────┘      └────┬────┘         └────┬─────┘
             └──────── tool calls ────────────────┘
                                │ MCP stdio
                ┌───────────────┼────────────────┬─────────┐
                ▼               ▼                ▼         ▼
         ┌──────────┐    ┌─────────────┐  ┌────────────┐ ┌────────┐
         │ scinotes │    │   Zotero    │  │  PubMed    │ │Semantic│
         │  server  │    │     MCP     │  │    MCP     │ │ Scholar│
         │  (local) │    │ (optional)  │  │            │ │  MCP   │
         └────┬─────┘    └─────────────┘  └────────────┘ └────────┘
              │
              ▼
   ┌─────────────────────────┐
   │ ~/wiki/                 │
   │  ├─ paper_notes.md      │
   │  ├─ reading_queue.md    │
   │  ├─ idea_box.md         │
   │  ├─ ...                 │
   │  ├─ memory.md           │
   │  ├─ log.md              │
   │  └─ .wiki_journal.jsonl │ ← undo log
   └─────────────────────────┘
```

## Modules

```
src/scinotes/
├── __init__.py
├── cli.py             # subcommands: init / doctor / run / serve-mcp
├── server.py          # MCP server: wiki + research tools
├── utils_video.py     # YouTube/Bilibili subtitle fetcher
├── client/
│   ├── core.py        # WikiClient (model registry, MCP client, history persistence)
│   ├── telegram.py    # TelegramFrontend
│   ├── qq.py          # QQFrontend (optional)
│   └── cli.py         # CLIFrontend (REPL)
├── prompts/
│   ├── system.en.md   # English system prompt
│   └── system.zh-CN.md
└── templates/
    ├── en/            # paper_notes.md, reading_queue.md, ...
    └── zh-CN/         # 论文笔记.md, 阅读队列.md, ...
```

## Lifecycle

1. **`scinotes run`** loads `.env`, instantiates `WikiClient`, calls `connect()`.
2. `connect()` spawns up to 4 MCP servers as subprocesses over stdio:
   - `python -m scinotes.server` (local wiki — always)
   - `npx -y @cyanheads/pubmed-mcp-server`
   - `npx -y @xbghc/semanticscholar-mcp`
   - `uvx --from zotero-mcp-server zotero-mcp serve` (only if Zotero env present)
   Each tool from each server is registered in `WikiClient.tools`.
3. Frontends start. Each calls `wiki.chat(text)` per user message.
4. `chat()` routes to the chosen LLM, runs up to 5 tool-call iterations, persists history.
5. On Ctrl-C: each frontend's `stop()` runs, then `wiki.close()` tears down MCP subprocesses.

## Model routing

`MODELS` dict is built once at import time from env vars. A provider only appears if its required keys are set. The chain for a given chat is:

```
chain = [forced_model_or_default] + [m for m in FALLBACK_CHAIN if m != primary]
```

Filtered by what's actually in `MODELS`. The first model that returns successfully wins; failures cascade to the next.

Three providers cover all current models:
- `ollama` — Ollama local, native API
- `openai_compat` — `/v1/chat/completions`-shape (GLM, OpenAI, DeepSeek, MiMo, …)
- `anthropic` — `/v1/messages` (Claude); has a per-call OpenAI↔Anthropic format converter

To add a model you can adapt: edit `_build_models()` in `client/core.py` and add an entry pointing at the right provider + base URL + model name. No new code path needed.

## Wiki layout & sentinel-protected files

Tools that write to wiki pages use one of three patterns:

- **append-line**: `reading_queue_add`, `idea_capture`, `wiki_ingest`, `wiki_memorize` — prepend to a `## Section`.
- **insert-section-before-anchor**: `paper_ingest`, `experiment_log` (new project) — insert a new `## ` block just before `## Cross-references`.
- **sentinel-protected merge**: `update_research_profile` — only edits content between `<!-- BEGIN_PROFILE -->` and `<!-- END_PROFILE -->`, plus appends to a similar `<!-- BEGIN_CHANGELOG --> ... <!-- END_CHANGELOG -->` region. Free-form sections are untouched.

Each successful write also records a structured entry in `.wiki_journal.jsonl` so `wiki_undo_last` can replay the inverse.

## State files

| File | Owner | Purpose |
|---|---|---|
| `<wiki>/CLAUDE.md` | user / `init` | schema doc |
| `<wiki>/<page>.md` | tools + user | wiki content |
| `<wiki>/log.md` | tools | append-only change log |
| `<wiki>/memory.md` | `wiki_memorize` + user | facts auto-loaded into every prompt |
| `<wiki>/research_profile.md` | `update_research_profile` + user | research background, on-demand load |
| `<wiki>/.cache_history.jsonl` | client | last 20 user/assistant messages, persisted across restarts |
| `<wiki>/.wiki_journal.jsonl` | tools | undo log (LIFO) |

Anything starting with `.` is in `.gitignore` by default — feel free to `git init` your wiki.

## Extending

- **Add a tool**: write a new `@mcp.tool()` in `server.py`. It auto-appears to all LLMs.
- **Add a frontend**: implement a class with `name` / `is_configured` / `preflight` / `start` / `stop` and wire it in `cli.py:_run_async`.
- **Add a model**: add a provider entry in `client/core.py:_build_models()`.
- **Add a language**: drop `system.<code>.md` into `prompts/` and a `templates/<code>/` folder of pages. Then handle `--lang <code>` in `cli.py:cmd_init`.
