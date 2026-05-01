# Changelog

All notable changes to scinotes will be documented in this file. Format roughly follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project tries to honour [SemVer](https://semver.org/).

## [0.1.0] — unreleased

Initial public release.

### Added
- MCP server (`scinotes serve-mcp` / `python -m scinotes.server`) with research-focused tools:
  `paper_ingest`, `reading_queue_add`/`reading_queue_pop`, `experiment_log`, `idea_capture`,
  `update_research_profile`, `wiki_undo_last`, plus generic `wiki_ingest`/`wiki_query`/
  `wiki_read_page`/`wiki_list_pages`/`wiki_lint`/`wiki_memorize`.
- Multi-model routing: Ollama (local, default) + Anthropic Claude + any OpenAI-compatible provider
  (GLM, OpenAI, DeepSeek, Xiaomi MiMo, …). `@<model>` prefix in any message switches LLMs for
  that turn; configurable fallback chain.
- Frontends: Telegram (full text/PDF/voice), QQ (optional, mainland China), CLI REPL.
- Auto-attach to external MCP servers when installed: PubMed, Semantic Scholar, Zotero.
- Persistent conversation history across restarts (`.cache_history.jsonl`).
- LIFO write journal (`.wiki_journal.jsonl`) backing `wiki_undo_last`.
- Bilingual templates (en / zh-CN) and system prompts.
- `scinotes init` to bootstrap a wiki directory; `scinotes doctor` for self-check.
- MIT license.

### Added (post-initial drafting)
- VPS-friendly model routing: ollama auto-skipped via `OLLAMA_DISABLE=1`, smart defaults
  pick the first available cloud model when no DEFAULT_MODEL/FALLBACK_CHAIN is set, and
  any model that fails with `ConnectError` is removed from the registry for the rest of
  the session so subsequent turns skip it.
- Slash commands inside any frontend: `/list-models`, `/add-model name=… provider=… base=… key=… model=…`,
  `/remove-model <id>`, `/set-default <id>`, `/help`. Models added this way persist to
  `<wiki>/models.json` and survive restarts.
- OCR fallback for scanned/image PDFs (optional `[ocr]` extra → pdf2image + pytesseract;
  also requires system `tesseract` + language packs and `poppler`). `read_local_pdf`
  auto-detects sparse text and falls through to OCR; new explicit `read_pdf_ocr` tool
  for non-English scans (e.g. `lang="chi_sim+eng"`). When OCR isn't installed, returns
  a precise install hint.
- Memory hygiene: `/memory-stats` reports memory.md size and token estimate; warns when
  the file gets large. `/compact-memory [@model]` asks the LLM to rewrite memory.md
  (merge dups, drop stale, keep most-recent timestamps), archives the original to
  `<wiki>/.memory_archive_<ts>.md` (gitignored) before overwriting, and refuses to
  apply if the result isn't smaller or shrinks below 10% of original (safety guards
  against misbehaving models).

### Known gaps
- Tool reference is hand-written; auto-generation deferred.
- No Docker compose example yet.
- Test coverage focuses on smoke + routing; deeper coverage deferred.
