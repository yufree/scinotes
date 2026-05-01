# scinotes — wiki schema

This file documents the structure of your personal research wiki. scinotes (and humans) read it to understand how pages are organized.

## Layers

| Layer | Purpose | Pages |
|---|---|---|
| **research** | scinotes-managed research output | paper_notes, reading_queue, research_questions, experiment_log, idea_box, research_profile |

You are free to add your own pages and your own layers below this. scinotes will list them via `wiki_list_pages` even though they aren't in the categorization above.

## How pages are written

scinotes' research-layer tools maintain these pages with predictable structure:

- `paper_notes` ← `paper_ingest`: one section per paper, with metadata + BibTeX + summary
- `reading_queue` ← `reading_queue_add` / `reading_queue_pop`: a FIFO list of unread URL/DOI items
- `research_questions` ← LLM uses `wiki_ingest` here, three buckets: in-progress / open / shelved
- `experiment_log` ← `experiment_log`: per-project sections, dated entries top-down
- `idea_box` ← `idea_capture`: time-ordered idea cards with [[wikilinks]]
- `research_profile` ← `update_research_profile`: research background. **Loaded on demand** (not every conversation), only the basic-info block + changelog are tool-managed; other sections are yours to edit freely

## Operating principles

### Ingest (writing)
1. Pick the page (or pages) the entry belongs to.
2. Append the entry plus a one-line "why I'm saving this".
3. Add `[[cross-references]]` when relevant.
4. The bot will append a line to `log.md` automatically.

### Query (reading)
1. Search wiki via `wiki_query`.
2. Synthesize from one or more pages.
3. Say "no coverage in the wiki" if appropriate, then optionally external search.

### Lint (health)
- **dead links**: external URLs no longer reachable
- **orphans**: pages no other page links to
- **stale dates**: claims tied to time-bound data
- **cross-references**: pages talking about the same topic should link to each other

## Files

- `CLAUDE.md` (this file) — schema
- `log.md` — append-only change log (one line per write)
- `memory.md` — long-term facts, auto-loaded into every conversation
- `<page>.md` — wiki content
