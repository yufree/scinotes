# SETUP

How to bring scinotes up from zero on a Mac, Linux laptop, or VPS.

## 1. Prerequisites

- Python ≥ 3.10
- [`uv`](https://github.com/astral-sh/uv) (recommended) or `pipx`
- (Optional but recommended) [Ollama](https://ollama.com) for free local inference
- (Optional, for PubMed/Scholar) Node.js so `npx` is available
- (Optional, for Zotero) `uvx` is bundled with `uv`

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2:latest    # or any model that supports tool calling
```

## 2. Install scinotes

```bash
uv tool install scinotes        # global install, isolated venv
# or
pipx install scinotes
```

To upgrade later: `uv tool upgrade scinotes` (or `pipx upgrade scinotes`).

## 3. Bootstrap a wiki

```bash
scinotes init ~/research-wiki --lang en
# or
scinotes init ~/我的wiki --lang zh-CN
```

This creates:

- `CLAUDE.md` — schema doc
- `paper_notes.md` / `论文笔记.md`
- `reading_queue.md` / `阅读队列.md`
- `research_questions.md` / `研究问题.md`
- `experiment_log.md` / `实验日志.md`
- `idea_box.md` / `想法库.md`
- `research_profile.md` / `研究画像.md`
- `memory.md`
- `log.md`
- `.env` (from a built-in template)

`init` is idempotent — it never overwrites existing files. Re-run after upstream template updates and only the missing files will be added.

## 4. Configure `.env`

Open `~/research-wiki/.env` and fill in **at minimum**:

### Telegram (required for the default frontend)

```ini
TELEGRAM_BOT_TOKEN=123456:ABC...   # from @BotFather
TELEGRAM_USER_ID=987654321         # YOUR numeric id from @userinfobot
```

`TELEGRAM_USER_ID` is **required**. scinotes refuses to start a Telegram bot without it — otherwise anyone on the internet who finds your bot's name could chat with it.

### One LLM

Pick at least one. Order shown is rough cost-benefit.

```ini
# Free (local). Pull a tool-calling-capable model like llama3.2.
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3.2:latest

# Cloud — used when you prefix a message with @claude / @glm / etc.
ANTHROPIC_API_KEY=sk-ant-...        # https://console.anthropic.com
OPENAI_API_KEY=sk-proj-...          # https://platform.openai.com
GLM_API_KEY=...                     # https://open.bigmodel.cn (Zhipu)
DEEPSEEK_API_KEY=sk-...             # https://platform.deepseek.com
MIMO_API_KEY=tp-...                 # https://xiaomimimo.com

# DEFAULT_MODEL / FALLBACK_CHAIN — leave commented to auto-pick.
# scinotes will:
#   - default to ollama if OLLAMA_HOST is reachable, else first cloud model with key
#   - auto-fall back to every other configured model on failure
#   - remove unreachable providers from the live registry mid-session
# Override only if you want a specific order.
# DEFAULT_MODEL=claude
# FALLBACK_CHAIN=claude,glm
```

**VPS without Ollama**: add `OLLAMA_DISABLE=1` so scinotes never tries `localhost:11434`.

### Adding more models at runtime

Once running, talk to the bot from any frontend:

```
/add-model name=kimi provider=openai_compat \
            base=https://api.moonshot.cn/v1 \
            key=sk-xxx \
            model=moonshot-v1-128k
```

The new model becomes available **immediately** as `@kimi` (no restart). It's persisted
to `<wiki>/models.json`, so it survives daemon restarts.

Other commands: `/list-models`, `/remove-model <id>`, `/set-default <id>`, `/help`.

### Optional — research integrations

```ini
# PubMed (free; key avoids rate limit)
NCBI_API_KEY=...

# Semantic Scholar (free; key gives higher quota)
SEMANTIC_SCHOLAR_API_KEY=...

# Zotero — web mode (recommended; works on any machine)
ZOTERO_API_KEY=...                  # https://www.zotero.org/settings/keys
ZOTERO_LIBRARY_ID=12345             # numeric user id from same page
ZOTERO_LIBRARY_TYPE=user            # or "group"

# Or Zotero — local mode (Zotero desktop must be running)
# ZOTERO_LOCAL=true

# Brave Search (web fallback when local + papers can't answer)
BRAVE_API_KEY=...                   # https://api.search.brave.com

# Groq (voice transcription for Telegram voice notes)
GROQ_API_KEY=gsk_...                # https://console.groq.com
```

## 5. Verify

```bash
cd ~/research-wiki
scinotes doctor
```

You should see green check marks for: WIKI_PATH, frontends, configured models, ollama reachability, and external runtimes (`npx`, `uvx`).

## 6. Run

```bash
scinotes run
```

If Telegram isn't configured, scinotes drops to an interactive CLI REPL where you can chat directly in the terminal — useful for sanity-checking before exposing the bot publicly.

To force a specific frontend:

```bash
scinotes run --frontends cli
scinotes run --frontends telegram,qq
```

## 7. Run as a service

### macOS — launchd

Copy `examples/launchd/scinotes.plist` to `~/Library/LaunchAgents/`, edit the paths, then:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/scinotes.plist
launchctl kickstart gui/$(id -u)/scinotes
```

### Linux — systemd

```bash
cp examples/systemd/scinotes.service ~/.config/systemd/user/
# edit paths inside
systemctl --user daemon-reload
systemctl --user enable --now scinotes
journalctl --user -u scinotes -f
```

## Scanned / image PDFs (OCR)

By default `read_local_pdf` uses pypdf — fast, free, but only works for PDFs that
already have an embedded text layer. **Scanned papers, photo-of-paper PDFs, or any
image-based PDF won't yield text.** scinotes auto-detects this case (avg chars / page
< 50) and falls back to OCR if installed.

To enable OCR:

```bash
# 1. Install scinotes' optional OCR Python deps
uv tool install --upgrade 'scinotes[ocr]'      # if installed via uv tool
# or: pip install --upgrade 'scinotes[ocr]'

# 2. Install system binaries
# macOS:
brew install tesseract tesseract-lang poppler
# Debian / Ubuntu:
sudo apt install tesseract-ocr tesseract-ocr-eng tesseract-ocr-chi-sim poppler-utils
# Arch:
sudo pacman -S tesseract tesseract-data-eng tesseract-data-chi_sim poppler

# 3. Verify
tesseract --list-langs   # should include eng (and any extras you installed)
```

`read_local_pdf` then auto-OCRs (English by default). For non-English papers, call the
explicit tool:

```text
> read_pdf_ocr filepath=/path/to/scan.pdf lang=chi_sim+eng
```

Tesseract language codes are joined with `+` for multi-language documents. Common picks
for research: `chi_sim+eng`, `chi_tra+eng`, `jpn+eng`, `kor+eng`, `deu+eng`, `fra+eng`.

OCR is **CPU-intensive and slow** (a few seconds per page). For large papers, expect
30–90 seconds. If you do this routinely on math-heavy papers, consider switching to a
paid service (Mathpix etc.) — that's a v0.2 candidate.

## Memory growth & compaction

`memory.md` is **loaded into every conversation's system prompt**. Each `wiki_memorize`
call appends a line. After months of use this file can grow to thousands of facts —
linear token cost on every turn for facts you may no longer care about.

Two slash commands help you stay on top of this (talk to the bot from any frontend):

- `/memory-stats` — shows current line count, char count, and a rough token estimate.
  Warns when memory.md exceeds ~2000 tokens.
- `/compact-memory [@model]` — asks an LLM to rewrite memory.md: merge duplicates,
  drop stale entries, keep the most-recent timestamp on contradictions.
  - The original file is **always archived first** to
    `<wiki>/.memory_archive_<timestamp>.md` (gitignored). If anything goes wrong, copy
    that back over `memory.md`.
  - Two safety guards: refuses to overwrite if the new content isn't smaller than the
    original (model didn't actually compact), or if it shrank to less than 10% of
    original size (model misbehaved / hallucinated).
  - Optional `@model` arg picks which LLM does the compaction. Defaults to
    `DEFAULT_MODEL`. Use `@claude` (or another strong cloud model) for best results;
    local Ollama works but quality is lower.

Example session:

```text
> /memory-stats
memory.md: 240 fact entries, 18432 chars (~6144 tokens).
⚠ memory.md is ~6144 tokens; this is loaded into EVERY conversation's system prompt.
  Consider running /compact-memory.

> /compact-memory @claude
✓ Compacted memory.md via @claude: 18432 → 6210 chars (66% smaller).
  Original archived at .memory_archive_20260501_154523.md (gitignored).
```

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `scinotes doctor` says "ollama unreachable" | Ollama not running. `ollama serve` (or restart its app/service). |
| Telegram says "Conflict: terminated by other getUpdates" | Two bot instances running with the same token. Stop one. |
| `npx`/`uvx` "not found" | Install Node.js (for npx) and uv (which provides uvx). |
| Bot replies but never calls tools | Some local LLMs have weak tool-calling. Use a larger model or prefix with `@claude` / `@openai`. |
| Tool wrote wrong content | Reply "撤销" / "undo" — the bot will call `wiki_undo_last`. |
