# scinotes

> Your Obsidian-native research assistant — chat through Telegram/QQ/CLI, backed by markdown, augmented by LLMs.

[中文版 README](README.zh-CN.md) | MIT License | Status: alpha (v0.1)

scinotes turns a folder of markdown files into a research notebook that you can talk to. Drop a paper link in Telegram, get a structured note in your wiki. Capture an idea, query your own past entries, log experiment progress — all from your phone, all stored as plain `.md` files you fully own.

## What makes it different

- **Markdown-native.** Your notes live as `.md` files in a folder you choose. Open them in Obsidian, Logseq, VS Code, or commit them to git. No proprietary database.
- **Research-specific tools.** First-class commands for paper ingest (with BibTeX), reading queue, experiment log, idea capture, research-profile tracking, and undo.
- **Multi-model routing.** Default to local Ollama for free; prefix any message with `@claude`, `@glm`, etc. to escalate to a cloud model only when needed. Cost stays transparent.
- **MCP-orchestrated.** Talks to Zotero, PubMed, Semantic Scholar (and any MCP server you point it at) for literature search. Bring your own.
- **Self-host first.** Runs on your laptop or any small VPS. Your data, your keys, your model choice.

## 60-second demo

```text
You: Add this paper https://doi.org/10.1234/foo to my reading queue
Bot: Added — "[2026-04-30 10:42] https://doi.org/10.1234/foo"
     ——
     ✓ reading_queue_add → [[reading_queue]]

You: Summarize and ingest the PDF I just dropped
Bot: [Reads PDF, drafts summary, generates BibTeX, writes note]
     Citation key: smith2024spectroscopy
     ——
     ✓ read_local_pdf
     ✓ paper_ingest → [[paper_notes]] / smith2024spectroscopy

You: Actually that ingest got the year wrong, undo it
Bot: Reverted.
     ——
     ✓ wiki_undo_last → [[paper_notes]] / smith2024spectroscopy removed
```

## Install

Requires Python ≥ 3.10 and (recommended) [Ollama](https://ollama.com) for free local inference.

```bash
# Install via uv (recommended — fast, isolated, single binary)
uv tool install scinotes

# Or via pipx
pipx install scinotes
```

## Quick start

```bash
# 1. Bootstrap a wiki
scinotes init ~/research-wiki --lang en

# 2. Edit the .env that init created
$EDITOR ~/research-wiki/.env
#   - Set TELEGRAM_BOT_TOKEN  (create via @BotFather)
#   - Set TELEGRAM_USER_ID    (your numeric ID — get it from @userinfobot)
#   - Pick at least one LLM. For pure-local: pull an Ollama model.
#     For cloud: set ANTHROPIC_API_KEY or GLM_API_KEY etc.

# 3. Verify your config
scinotes doctor

# 4. Run the bot
scinotes run

# Or, no Telegram set up yet? Drive it from the terminal first:
scinotes run --frontends cli
```

## Architecture

```
┌─────────────┐       ┌────────────────────────┐
│  Telegram   │──┐    │   scinotes WikiClient  │
├─────────────┤  │    │  (model router + MCP)  │
│     QQ      │──┼───►│                        │
├─────────────┤  │    │  ┌──────────────────┐  │
│  CLI REPL   │──┘    │  │ system prompt    │  │
└─────────────┘       │  │ (en / zh-CN)     │  │
                      │  └──────────────────┘  │
                      │                        │
                      │  Models registry:      │
                      │   ollama, claude, …    │
                      └────────┬───────────────┘
                               │  MCP stdio
              ┌────────────────┼────────────────┬───────────────┐
              ▼                ▼                ▼               ▼
        ┌──────────┐    ┌─────────────┐  ┌────────────┐   ┌──────────┐
        │  local   │    │   Zotero    │  │   PubMed   │   │ Semantic │
        │  wiki    │    │     MCP     │  │     MCP    │   │ Scholar  │
        │   MCP    │    │             │  │            │   │   MCP    │
        └────┬─────┘    └─────────────┘  └────────────┘   └──────────┘
             │
             ▼
   ┌─────────────────────┐
   │ ~/research-wiki/    │
   │  ├─ paper_notes.md  │
   │  ├─ reading_queue.md│
   │  ├─ idea_box.md     │
   │  └─ ...             │
   └─────────────────────┘
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for details.

## Documentation

- [SETUP.md](SETUP.md) — full configuration walkthrough (every env var explained, how to obtain API keys)
- [ARCHITECTURE.md](ARCHITECTURE.md) — how the pieces fit together
- [SECURITY.md](SECURITY.md) — **read before exposing this on the public internet**
- [CONTRIBUTING.md](CONTRIBUTING.md)

## Tools (for the LLM)

The bot exposes these MCP tools to whichever LLM is in use:

| Tool | Purpose |
|---|---|
| `wiki_query` | keyword search across all wiki pages |
| `wiki_read_page` | fetch a single page's full content |
| `wiki_list_pages` | list pages by category |
| `wiki_ingest` | append a free-form item to a chosen page |
| `wiki_lint` | health check (orphans, broken links, dead URLs) |
| `wiki_memorize` | append to `memory.md` (loaded into every prompt) |
| `wiki_undo_last` | undo the most recent write |
| `paper_ingest` | append a paper note (metadata + BibTeX + summary) |
| `reading_queue_add` / `reading_queue_pop` | manage reading queue |
| `experiment_log` | log experiment progress per project |
| `idea_capture` | append idea cards to the idea box |
| `update_research_profile` | update research profile (sentinel-protected, changelog appended) |
| `read_local_pdf` | extract PDF text locally (pypdf, with OCR fallback if installed) |
| `read_pdf_ocr` | force OCR on a PDF (tesseract; requires `scinotes[ocr]` + system binaries) |
| `web_fetch_url` | fetch web page text (Jina Reader) |
| `web_search` | Brave web search |
| `extract_video_subtitles` | YouTube / Bilibili captions |

External MCP servers (auto-attached if installed): Zotero, PubMed, Semantic Scholar.

## Companion projects

scinotes is the **note-keeping** layer of a research workflow. For complementary capabilities you may want to install alongside it:

- **[yufree/sciguideskill](https://github.com/yufree/sciguideskill)** — a Claude Code / Desktop skill providing candid, opinionated research-mentorship grounded in《现代科研指北》(*Modern Guide to Scientific Research*). Covers research thinking, experimental design, statistics, paper writing, academic careers, cognitive biases. Chinese-language. Pairs naturally with scinotes inside Claude Desktop: scinotes manages your wiki, sciguide answers career / methodology questions with stance.

If you have other small MCP servers / skills that fit the research workflow, a PR adding them here is welcome.

## Status & roadmap

This is **v0.1 alpha**. Core flows work; expect rough edges. Roadmap → v0.2:
- Full bilingual error messages
- Auto-generated tool reference
- Docker compose example
- Tests + CI
- Community frontends (Slack / Discord / Matrix)

## License

MIT. See [LICENSE](LICENSE).
