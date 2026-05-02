"""scinotes wiki MCP server.

Exposes wiki + research tools (paper_ingest, reading_queue, experiment_log,
idea_capture, update_research_profile, wiki_undo_last, etc.) over MCP stdio.

Usage:
    scinotes serve-mcp                    # wraps `python -m scinotes.server`
    python -m scinotes.server             # direct invocation, requires WIKI_PATH env
    WIKI_PATH=/path/to/wiki python -m scinotes.server
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Wiki path & language (read from env at import time; main() can override via argv)
# ---------------------------------------------------------------------------
WIKI_PATH = Path(os.environ.get("WIKI_PATH", str(Path.cwd())))
BOT_LANG = os.environ.get("BOT_LANG", "en").lower()
IS_ZH = BOT_LANG.startswith("zh")

# ---------------------------------------------------------------------------
# Page name registry — lang-aware logical names → on-disk filenames
# ---------------------------------------------------------------------------
_PAGES_EN = {
    "paper_notes": "paper_notes",
    "reading_queue": "reading_queue",
    "research_questions": "research_questions",
    "experiment_log": "experiment_log",
    "idea_box": "idea_box",
    "research_profile": "research_profile",
    "memory": "memory",
}
_PAGES_ZH = {
    "paper_notes": "论文笔记",
    "reading_queue": "阅读队列",
    "research_questions": "研究问题",
    "experiment_log": "实验日志",
    "idea_box": "想法库",
    "research_profile": "研究画像",
    "memory": "memory",
}
PAGE = _PAGES_ZH if IS_ZH else _PAGES_EN

# Page section headers also vary by lang.
HEADER_CROSSREF = "## 交叉引用" if IS_ZH else "## Cross-references"
HEADER_QUEUE = "## 待读" if IS_ZH else "## Queue"
HEADER_IDEAS = "## 卡片" if IS_ZH else "## Cards"

# ---------------------------------------------------------------------------
# MCP server instance
# ---------------------------------------------------------------------------
mcp = FastMCP("scinotes-wiki")

# ---------------------------------------------------------------------------
# Page categories (for wiki_ingest suggestions).
#
# Default = the built-in research layer. But if the user's <wiki>/CLAUDE.md contains
# a markdown table whose header looks like "Layer | ... | Pages" (or 中文 等价),
# we parse it and let those layers + pages drive suggestions instead. This way
# users with personal taxonomies (e.g. 资料源 / 基线知识 / 历史 / 现状 / 观点 / 未来 / 科研)
# get accurate suggestions without editing scinotes' source.
# ---------------------------------------------------------------------------
_DEFAULT_PAGE_CATEGORIES: dict[str, list[str]] = {
    "research": [
        PAGE[k]
        for k in (
            "paper_notes",
            "reading_queue",
            "research_questions",
            "experiment_log",
            "idea_box",
            "research_profile",
        )
    ],
}


def _parse_categories_from_claude_md(claude_path: Path) -> dict[str, list[str]] | None:
    """Parse the schema table out of a wiki's CLAUDE.md. Returns None if no
    recognizable table is present.

    Recognizes markdown tables whose header row mentions "层级"/"Layer" plus
    "页面"/"Pages". Page lists are split on `,` `,` `、`. Bold markers `**` are
    stripped from layer labels.
    """
    if not claude_path.exists():
        return None
    try:
        content = claude_path.read_text(encoding="utf-8")
    except Exception:
        return None

    cats: dict[str, list[str]] = {}
    header_seen = False
    for raw in content.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            header_seen = False
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not header_seen:
            joined = " ".join(cells).lower()
            has_layer_word = any(k in joined for k in ("层级", "layer"))
            has_pages_word = any(k in joined for k in ("页面", "pages"))
            if has_layer_word and has_pages_word:
                header_seen = True
            continue
        # In-table row
        if all(c.replace("-", "").replace(":", "").strip() == "" for c in cells):
            continue  # separator row
        if len(cells) < 2:
            continue
        layer = cells[0].strip().strip("*").strip()
        pages_str = cells[-1].strip()  # last column = pages
        if not layer or not pages_str:
            continue
        pages = [p.strip().strip("*").strip("`") for p in re.split(r"[、,,]", pages_str) if p.strip()]
        if pages:
            cats[layer] = pages
    return cats or None


_user_cats = _parse_categories_from_claude_md(WIKI_PATH / "CLAUDE.md")
PAGE_CATEGORIES: dict[str, list[str]] = _user_cats if _user_cats else _DEFAULT_PAGE_CATEGORIES

ALL_PAGES: list[str] = []
for _cat, _ps in PAGE_CATEGORIES.items():
    ALL_PAGES.extend(_ps)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

INFRA_PAGES = {"CLAUDE", "index", "log", "Home", "_Sidebar", "memory", "research_profile", "研究画像"}


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _today() -> str:
    return datetime.date.today().isoformat()


def list_wiki_pages() -> list[str]:
    """Return sorted list of wiki page names (no extension), excluding infra."""
    pages = [f.stem for f in WIKI_PATH.glob("*.md") if f.stem not in INFRA_PAGES]
    return sorted(pages)


def read_page(name: str) -> str | None:
    p = WIKI_PATH / f"{name}.md"
    return p.read_text(encoding="utf-8") if p.exists() else None


def append_to_page(name: str, content: str) -> None:
    p = WIKI_PATH / f"{name}.md"
    with open(p, "a", encoding="utf-8") as f:
        f.write(content)


def append_log(entry: str) -> None:
    today = _today()
    with open(WIKI_PATH / "log.md", "a", encoding="utf-8") as f:
        f.write(f"\n{today} | {entry}")


def search_pages(keyword: str) -> list[dict]:
    results = []
    for name in list_wiki_pages():
        content = read_page(name)
        if content and keyword.lower() in content.lower():
            lines = [line.strip() for line in content.split("\n") if keyword.lower() in line.lower()]
            results.append({"page": name, "matches": lines[:5]})
    return results


def extract_urls(content: str) -> list[str]:
    return re.findall(r"https?://[^\s\)\]>\"]+", content)


# ---------------------------------------------------------------------------
# Generic wiki tools
# ---------------------------------------------------------------------------


@mcp.tool()
def wiki_ingest(
    content: str,
    target_page: str = "",
    source_url: str = "",
) -> str:
    """Append a free-form item to a wiki page (creates page if missing).

    Args:
        content:     The text or note to record (one-liner, link, snippet, etc.).
        target_page: Page filename without extension. Empty → returns the list of
                     existing pages so the caller can pick.
        source_url:  Optional URL; if provided, content is wrapped as `[content](url)`.
    """
    if not target_page:
        pages = list_wiki_pages()
        page_list = "\n".join(f"- {p}" for p in pages)
        cats = "\n".join(f"  {c}: {', '.join(ps)}" for c, ps in PAGE_CATEGORIES.items())
        return (
            f"Specify a target_page. Existing pages:\n{page_list}\n\n"
            f"Built-in research categories:\n{cats}\n\n"
            f"Pass target_page=<name> to write."
        )

    page_path = WIKI_PATH / f"{target_page}.md"
    is_new = not page_path.exists()
    if is_new:
        with open(page_path, "w", encoding="utf-8") as f:
            f.write(f"# {target_page}\n\n")

    if source_url:
        line = f"- [{content}]({source_url})"
    else:
        line = f"- {content}"
    entry = "\n" + line + "\n"
    append_to_page(target_page, entry)

    append_log(f"ingest | {target_page} | {'new page + ' if is_new else ''}{content[:50]}")

    _journal_append(
        {
            "tool": "wiki_ingest",
            "page": target_page,
            "op": "remove_line",
            "line": line,
        }
    )

    status = "Created and wrote" if is_new else "Wrote to"
    return f"{status} [[{target_page}]].\n{entry}"


@mcp.tool()
def wiki_query(question: str) -> str:
    """Keyword search across all wiki pages. Returns matched lines per page."""
    keywords = [w for w in re.split(r"[\s,。?!.，?！]+", question) if len(w) >= 2]
    if not keywords:
        return "Provide at least one keyword (>=2 chars)."

    all_results: dict[str, dict] = {}
    for kw in keywords:
        for r in search_pages(kw):
            page = r["page"]
            all_results.setdefault(page, {"page": page, "matches": []})
            all_results[page]["matches"].extend(r["matches"])

    if not all_results:
        return f"No wiki page matches '{question}'."

    sorted_results = sorted(all_results.values(), key=lambda x: len(x["matches"]), reverse=True)
    out = [f"Found {len(sorted_results)} relevant page(s):\n"]
    for r in sorted_results[:5]:
        page = r["page"]
        matches = list(set(r["matches"]))[:5]
        out.append(f"## [[{page}]]")
        for m in matches:
            out.append(f"  {m[:200]}")
        out.append("")
    return "\n".join(out)


@mcp.tool()
def wiki_lint(check: str = "all") -> str:
    """Health check on the wiki: orphans, dead links, cross-reference completeness.

    Args:
        check: One of "orphan" | "deadlink" | "crossref" | "all" (default).
    """
    out = []
    pages = list_wiki_pages()
    contents = {n: read_page(n) or "" for n in pages}

    if check in ("orphan", "all"):
        # A page is orphan if no other page links to it via [[name]].
        orphans = []
        for name in pages:
            referenced = any(f"[[{name}]]" in c for n, c in contents.items() if n != name)
            if not referenced:
                orphans.append(name)
        out.append(f"### Orphans ({len(orphans)})")
        out.extend(f"- {o}" for o in orphans) if orphans else out.append("- (none)")

    if check in ("crossref", "all"):
        broken = []
        page_set = set(pages)
        for name, content in contents.items():
            for m in re.finditer(r"\[\[([^\]]+)\]\]", content):
                target = m.group(1).split("|")[0].strip()
                if target not in page_set:
                    broken.append((name, target))
        out.append(f"\n### Broken [[wikilinks]] ({len(broken)})")
        out.extend(f"- [[{n}]] → [[{t}]]" for n, t in broken) if broken else out.append("- (none)")

    if check in ("deadlink", "all"):
        urls_per_page = {n: extract_urls(c) for n, c in contents.items()}
        total_urls = sum(len(u) for u in urls_per_page.values())
        out.append(f"\n### URLs ({total_urls} across {len(urls_per_page)} pages)")
        out.append("(scinotes does not auto-check liveness; use a link checker like lychee.)")

    return "\n".join(out)


@mcp.tool()
def wiki_list_pages() -> str:
    """List all wiki pages, grouped by built-in research category vs other."""
    all_pages = list_wiki_pages()
    out = []
    seen = set()
    for cat, ps in PAGE_CATEGORIES.items():
        present = [p for p in ps if p in all_pages]
        if present:
            out.append(f"### {cat}")
            out.extend(f"- {p}" for p in present)
            seen.update(present)

    other = [p for p in all_pages if p not in seen]
    if other:
        out.append("\n### other")
        out.extend(f"- {p}" for p in other)

    return "\n".join(out) if out else "(no wiki pages found)"


@mcp.tool()
def wiki_read_page(page_name: str) -> str:
    """Read the full content of a wiki page by name (no extension)."""
    content = read_page(page_name)
    if content is None:
        return f"Page [[{page_name}]] does not exist."
    return content


@mcp.tool()
def web_fetch_url(url: str) -> str:
    """Fetch and clean a web page's main content via Jina Reader (free, no key)."""
    import urllib.request

    try:
        target = f"https://r.jina.ai/{url}"
        req = urllib.request.Request(target, headers={"User-Agent": "scinotes"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8", errors="replace")
        if len(text) > 20000:
            text = text[:20000] + "\n\n[truncated to 20KB]"
        return text
    except Exception as e:
        return f"web_fetch_url failed: {e}"


@mcp.tool()
def web_search(query: str) -> str:
    """Brave web search (requires BRAVE_API_KEY). Returns top 5 results."""
    import urllib.parse
    import urllib.request

    key = os.environ.get("BRAVE_API_KEY", "")
    if not key:
        return "BRAVE_API_KEY not configured; cannot perform web search."
    url = f"https://api.search.brave.com/res/v1/web/search?q={urllib.parse.quote(query)}&count=5"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": key,
            "User-Agent": "scinotes",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results = data.get("web", {}).get("results", [])
        if not results:
            return f"No results for '{query}'."
        out = [f"Search '{query}':\n"]
        for i, r in enumerate(results[:5], 1):
            out.append(f"{i}. **{r.get('title', '')}**\n   {r.get('description', '')}\n   {r.get('url', '')}")
        return "\n".join(out)
    except Exception as e:
        return f"web_search failed: {e}"


class OCRNotAvailable(Exception):
    """Raised when the OCR pipeline cannot run (missing Python deps or system binaries)."""


def _ocr_pdf_pages(filepath: str, lang: str = "eng", max_pages: int = 30) -> str:
    """Run OCR over a PDF using pdf2image + pytesseract.

    Raises OCRNotAvailable with an actionable install hint when any link in the chain
    (pdf2image / poppler / pytesseract / tesseract / language pack) is missing.
    """
    try:
        import pytesseract
        from pdf2image import convert_from_path
    except ImportError as e:
        raise OCRNotAvailable(
            "OCR Python deps not installed. Run:\n"
            "  uv tool install --upgrade 'scinotes[ocr]'\n"
            "Then install the system binaries (see SETUP.md → Scanned PDFs):\n"
            "  macOS:  brew install tesseract tesseract-lang poppler\n"
            "  Linux:  apt install tesseract-ocr tesseract-ocr-eng tesseract-ocr-chi-sim poppler-utils"
        ) from e

    try:
        images = convert_from_path(filepath, first_page=1, last_page=max_pages, dpi=200)
    except Exception as e:
        raise OCRNotAvailable(
            f"pdf2image failed (poppler likely missing): {e}\n"
            "  macOS:  brew install poppler\n"
            "  Linux:  apt install poppler-utils"
        ) from e

    chunks: list[str] = []
    for i, img in enumerate(images):
        try:
            chunks.append(pytesseract.image_to_string(img, lang=lang))
        except pytesseract.TesseractNotFoundError as e:
            raise OCRNotAvailable(
                "tesseract binary not in PATH:\n"
                "  macOS:  brew install tesseract tesseract-lang\n"
                "  Linux:  apt install tesseract-ocr"
            ) from e
        except pytesseract.TesseractError as e:
            # Often a missing language pack; skip this page rather than fail the whole job
            chunks.append(f"[page {i + 1} OCR failed: {e}]")

    return "\n\n".join(c for c in chunks if c).strip()


@mcp.tool()
def read_local_pdf(filepath: str, max_pages: int = 30) -> str:
    """Extract plain text from a local PDF.

    Tries pypdf first (free, fast — works for born-digital PDFs).
    If pypdf yields little/no text (typical of scanned/image PDFs), automatically
    falls back to OCR via tesseract — but only if `scinotes[ocr]` and the tesseract
    binary are installed. Otherwise returns a friendly hint.

    Args:
        filepath:  Absolute path to the PDF.
        max_pages: Cap pages extracted (default 30) to avoid blowing context.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        return "pypdf not installed; please reinstall scinotes."

    p = Path(filepath)
    if not p.exists():
        return f"PDF not found: {filepath}"
    try:
        reader = PdfReader(str(p))
        total = len(reader.pages)
        n = min(total, max_pages)
        chunks = []
        for i in range(n):
            try:
                chunks.append(reader.pages[i].extract_text() or "")
            except Exception:
                continue
        text = "\n\n".join(chunks).strip()
        truncate_note = f"\n\n[truncated: showed {n} of {total} pages]" if total > max_pages else ""

        # Heuristic: if avg chars/page is very low, the PDF is probably scanned.
        chars_per_page = len(text) / max(n, 1)
        if chars_per_page >= 50:
            return text + truncate_note

        # Sparse text — try OCR fallback
        try:
            ocr_text = _ocr_pdf_pages(str(p), lang="eng", max_pages=max_pages)
        except OCRNotAvailable as exc:
            if text:
                return (
                    text + truncate_note + "\n\n[note: text appears sparse (likely scanned PDF). "
                    f"To enable OCR fallback:\n{exc}]"
                )
            return f"(PDF appears scanned/image-based.)\n\n{exc}"

        if ocr_text:
            note = (
                f"[via OCR fallback — pypdf yielded {len(text)} chars, OCR yielded {len(ocr_text)}; "
                "for non-English text, call read_pdf_ocr explicitly with lang= e.g. 'chi_sim+eng']"
            )
            return f"{note}\n\n{ocr_text}{truncate_note}"
        return text + truncate_note or "(PDF extracted no text via pypdf or OCR.)"
    except Exception as e:
        return f"read_local_pdf failed: {e}"


@mcp.tool()
def read_pdf_ocr(filepath: str, lang: str = "eng+chi_sim", max_pages: int = 30) -> str:
    """Run OCR on a PDF directly (skip pypdf). Use when you know it's a scanned/image PDF
    or when text needs non-English language packs.

    Args:
        filepath:  Absolute path to the PDF.
        lang:      Tesseract lang code, possibly compound. Examples:
                     "eng"             — English only (most reliable, default lang pack)
                     "chi_sim+eng"     — Simplified Chinese + English (default here)
                     "chi_tra+eng"     — Traditional Chinese + English
                     "jpn+eng"         — Japanese + English
                   Each language requires its tesseract data pack installed
                   (e.g. `tesseract-ocr-chi-sim` on Linux, `tesseract-lang` on macOS).
        max_pages: Cap pages OCR'd (default 30 — OCR is slow).
    """
    p = Path(filepath)
    if not p.exists():
        return f"PDF not found: {filepath}"
    try:
        text = _ocr_pdf_pages(str(p), lang=lang, max_pages=max_pages)
    except OCRNotAvailable as e:
        return str(e)
    except Exception as e:
        return f"read_pdf_ocr failed: {e}"
    return text or "(OCR returned no text — page may be blank or unreadable)"


@mcp.tool()
def extract_video_subtitles(url: str) -> str:
    """Download and clean subtitles from a YouTube/Bilibili video URL."""
    try:
        if str(Path(__file__).resolve().parent) not in sys.path:
            sys.path.append(str(Path(__file__).resolve().parent))
        from .utils_video import fetch_subtitle  # type: ignore

        return fetch_subtitle(url)
    except Exception as e:
        return f"extract_video_subtitles failed: {e}"


@mcp.tool()
def wiki_memorize(fact: str) -> str:
    """Append a long-term fact to memory.md (loaded into every conversation's system prompt).

    Use when the user explicitly says "remember X" or for cross-session preferences.
    """
    memory_file = WIKI_PATH / "memory.md"
    try:
        is_new = not memory_file.exists() or memory_file.stat().st_size == 0
        line = f"- [{_now()}] {fact}"
        with open(memory_file, "a", encoding="utf-8") as f:
            if is_new:
                header = "# Long-term memory\n\n" if not IS_ZH else "# 长期记忆胶囊 (AI Memory)\n\n"
                f.write(header)
            f.write(line + "\n")
        _journal_append(
            {
                "tool": "wiki_memorize",
                "page": "memory",
                "op": "remove_line",
                "line": line,
            }
        )
        return "Stored to memory.md (loaded next conversation)."
    except Exception as e:
        return f"wiki_memorize failed: {e}"


# ---------------------------------------------------------------------------
# Research-layer helpers
# ---------------------------------------------------------------------------

_BIBTEX_STOPWORDS = {"the", "a", "an", "of", "on", "in", "and", "for", "to", "with", "from", "by"}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _citation_key(authors: str, year: str, title: str) -> str:
    """firstauthor_lastname + year + first_significant_word(title).

    Supports inputs:
      - "Smith J, Doe A"          (CSV; each "Lastname Initial")
      - "Smith, J. and Doe, A."   (BibTeX)
      - "John Smith, Jane Doe"    (CSV; "Firstname Lastname")
      - "Wang Y"                  (single author)
    """
    if " and " in authors:
        first_author = authors.split(" and ")[0].strip()
    else:
        first_author = authors.split(",")[0].strip()
    if "," in first_author:
        last = first_author.split(",")[0].strip()
    else:
        parts = first_author.replace(".", "").split()
        if not parts:
            last = "anon"
        elif len(parts) == 1:
            last = parts[0]
        elif len(parts[-1]) <= 2:
            last = parts[0]
        else:
            last = parts[-1]
    last = _slug(last) or "anon"
    year_clean = re.sub(r"[^0-9]", "", str(year))[:4] or "0000"
    for w in re.findall(r"[A-Za-z]+", title or ""):
        if w.lower() not in _BIBTEX_STOPWORDS:
            return f"{last}{year_clean}{_slug(w)}"
    return f"{last}{year_clean}untitled"


def _insert_under_header(page_name: str, header: str, new_line: str) -> bool:
    """Insert a single line at the top of a `## section`. Returns False if header missing."""
    p = WIKI_PATH / f"{page_name}.md"
    if not p.exists():
        return False
    lines = p.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.strip() == header:
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or lines[j].strip().startswith("<!--")):
                j += 1
            next_is_header = j >= len(lines) or lines[j].lstrip().startswith("#")
            lines.insert(j, new_line)
            if next_is_header:
                lines.insert(j + 1, "")
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return True
    return False


def _insert_before_header(page_name: str, target_header: str, block: str) -> bool:
    """Insert a multi-line block just before a `## section`. Appends to file end if not found."""
    p = WIKI_PATH / f"{page_name}.md"
    if not p.exists():
        return False
    lines = p.read_text(encoding="utf-8").splitlines()
    block_lines = block.strip("\n").splitlines()
    for i, line in enumerate(lines):
        if line.strip() == target_header:
            new_lines = lines[:i] + [""] + block_lines + [""] + lines[i:]
            p.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")
            return True
    with open(p, "a", encoding="utf-8") as f:
        f.write("\n" + "\n".join(block_lines) + "\n")
    return False


# ---------------------------------------------------------------------------
# Write-audit journal — backs wiki_undo_last
# ---------------------------------------------------------------------------
_JOURNAL_PATH = Path(os.environ.get("SCINOTES_JOURNAL_PATH", str(WIKI_PATH / ".wiki_journal.jsonl")))


def _journal_append(entry: dict) -> None:
    entry = {"ts": _now(), **entry}
    try:
        with open(_JOURNAL_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[scinotes] journal append failed: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Research-layer tools
# ---------------------------------------------------------------------------


@mcp.tool()
def paper_ingest(
    title: str,
    authors: str,
    year: str = "",
    venue: str = "",
    doi: str = "",
    summary: str = "",
    tags: list[str] = [],  # noqa: B006 — mutable default kept for MCP tool schema simplicity
) -> str:
    """Append a paper note (metadata + BibTeX + summary) to the paper-notes wiki page.

    Args:
        title:    Paper title.
        authors:  Author list, comma-separated (e.g., "Smith J, Doe A"). First-author
                  surname is extracted to build the citation key.
        year:     4-digit year (optional).
        venue:    Journal/conference name (optional).
        doi:      DOI or arxiv ID (optional).
        summary:  Your prose summary + comments. Markdown OK.
        tags:     List of tag strings (without leading #).

    Returns:
        Confirmation including the generated citation key.
    """
    page = PAGE["paper_notes"]
    p = WIKI_PATH / f"{page}.md"
    if not p.exists():
        return f"Page {page}.md missing — run `scinotes init` to create templates."

    key = _citation_key(authors, year, title)
    tag_str = " ".join(f"#{t.lstrip('#')}" for t in tags) if tags else ""
    bibtex_authors = " and ".join(a.strip() for a in authors.split(",") if a.strip())

    section = f"""

## {key} — {title}
- **Authors**: {authors}
- **Year/Venue**: {year}{" / " + venue if venue else ""}
- **DOI**: {doi or "(none)"}
- **Tags**: {tag_str or "(none)"}
- **Ingested**: {_now()}

### Summary

{summary or "(to fill)"}

### BibTeX

```bibtex
@article{{{key},
  title   = {{{title}}},
  author  = {{{bibtex_authors}}},
  year    = {{{year or "n.d."}}},
  journal = {{{venue}}},
  doi     = {{{doi}}}
}}
```
"""
    try:
        _insert_before_header(page, HEADER_CROSSREF, section)
        append_log(f"paper_ingest: [[{page}]] new entry {key}")
        _journal_append(
            {
                "tool": "paper_ingest",
                "page": page,
                "op": "remove_section",
                "header": f"## {key} — {title}",
            }
        )
        return f"Wrote to [[{page}]], citation key: {key}"
    except Exception as e:
        return f"paper_ingest failed: {e}"


@mcp.tool()
def reading_queue_add(url_or_doi: str, why: str = "") -> str:
    """Append a URL/DOI to the reading queue's top. Use when user shares a link without
    asking for immediate processing.
    """
    page = PAGE["reading_queue"]
    line = f"- [{_now()}] {url_or_doi}" + (f" — {why}" if why else "")
    if _insert_under_header(page, HEADER_QUEUE, line):
        append_log(f"reading_queue_add: {url_or_doi}")
        _journal_append(
            {
                "tool": "reading_queue_add",
                "page": page,
                "op": "remove_line",
                "line": line,
            }
        )
        return f"Added to [[{page}]]: {url_or_doi}"
    return f"Failed: page [[{page}]] or '{HEADER_QUEUE}' header missing"


@mcp.tool()
def reading_queue_pop() -> str:
    """Pop the OLDEST queued item (FIFO) from the reading queue and return it."""
    page = PAGE["reading_queue"]
    p = WIKI_PATH / f"{page}.md"
    if not p.exists():
        return f"Page [[{page}]] missing."
    lines = p.read_text(encoding="utf-8").splitlines()
    in_section = False
    for i, line in enumerate(lines):
        if line.strip() == HEADER_QUEUE:
            in_section = True
            continue
        if in_section:
            if line.strip().startswith("## "):
                break
            if line.strip().startswith("- "):
                bottom = i
                for j in range(len(lines) - 1, i - 1, -1):
                    if lines[j].strip().startswith("- "):
                        bottom = j
                        break
                popped = lines[bottom]
                del lines[bottom]
                p.write_text("\n".join(lines) + "\n", encoding="utf-8")
                append_log(f"reading_queue_pop: {popped.strip()[:80]}")
                return f"Popped: {popped.strip()}"
    return f"Reading queue [[{page}]] is empty."


@mcp.tool()
def experiment_log(project: str, status: str, blockers: str = "", next_steps: str = "") -> str:
    """Log a structured experiment progress entry. Auto-creates a per-project section."""
    page = PAGE["experiment_log"]
    p = WIKI_PATH / f"{page}.md"
    if not p.exists():
        return f"Page {page}.md missing."

    today = _today()
    none = "(none)" if not IS_ZH else "(无)"
    entry = (
        f"\n### {today}\n"
        f"- **Status**: {status}\n"
        f"- **Blockers**: {blockers or none}\n"
        f"- **Next steps**: {next_steps or none}\n"
    )

    content = p.read_text(encoding="utf-8")
    project_header = f"## {project}"
    is_new_project = project_header not in content.splitlines()
    if not is_new_project:
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if line.strip() == project_header:
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                entry_lines = entry.strip("\n").splitlines()
                for k, new_l in enumerate(entry_lines):
                    lines.insert(j + k, new_l)
                lines.insert(j + len(entry_lines), "")
                p.write_text("\n".join(lines) + "\n", encoding="utf-8")
                break
    else:
        new_section = f"{project_header}\n{entry}"
        _insert_before_header(page, HEADER_CROSSREF, new_section)

    append_log(f"experiment_log: [[{page}]] {project} — {status[:50]}")
    if is_new_project:
        _journal_append(
            {
                "tool": "experiment_log",
                "page": page,
                "op": "remove_section",
                "header": project_header,
            }
        )
    else:
        _journal_append(
            {
                "tool": "experiment_log",
                "page": page,
                "op": "remove_block_text",
                "block": entry.strip("\n"),
            }
        )
    return f"Logged {project} @ {today} to [[{page}]]"


@mcp.tool()
def idea_capture(content: str, related_pages: list[str] = []) -> str:  # noqa: B006
    """Append an idea card to the idea-box page top.

    Args:
        content:       The idea (one or two sentences).
        related_pages: List of wiki page names (without [[]]) to link to.
    """
    page = PAGE["idea_box"]
    links = " ".join(f"[[{p.strip().strip('[]')}]]" for p in related_pages if p.strip())
    line = f"- [{_now()}] {content}" + (f" {links}" if links else "")
    if _insert_under_header(page, HEADER_IDEAS, line):
        append_log(f"idea_capture: {content[:60]}")
        _journal_append(
            {
                "tool": "idea_capture",
                "page": page,
                "op": "remove_line",
                "line": line,
            }
        )
        return f"Captured to [[{page}]]"
    return f"Failed: page [[{page}]] or '{HEADER_IDEAS}' header missing"


# ---------------------------------------------------------------------------
# Research profile — sentinel-protected basic-info block + append-only changelog
# ---------------------------------------------------------------------------
PROFILE_BEGIN = "<!-- BEGIN_PROFILE -->"
PROFILE_END = "<!-- END_PROFILE -->"
CHANGELOG_BEGIN = "<!-- BEGIN_CHANGELOG -->"
CHANGELOG_END = "<!-- END_CHANGELOG -->"

# (key, label_en, label_zh)
PROFILE_FIELDS = [
    ("field", "Field", "研究领域"),
    ("directions", "Directions", "研究方向"),
    ("keywords", "Keywords", "关键词"),
    ("goals", "Goals", "研究目标"),
    ("collaborators", "Collaborators / Affiliations", "合作者/机构"),
    ("notes", "Notes", "备注"),
]


def _profile_label(key: str) -> str:
    for k, en, zh in PROFILE_FIELDS:
        if k == key:
            return zh if IS_ZH else en
    return key


def _render_profile_block(values: dict) -> str:
    title = "## 基本信息" if IS_ZH else "## Basics"
    placeholder = "(待填)" if IS_ZH else "(to fill)"
    lines = [PROFILE_BEGIN, title, ""]
    for key, _en, _zh in PROFILE_FIELDS:
        v = (values.get(key) or "").strip()
        lines.append(f"- **{_profile_label(key)}**: {v if v else placeholder}")
    lines.append(PROFILE_END)
    return "\n".join(lines)


def _parse_profile_block(text: str) -> dict:
    out = {}
    if PROFILE_BEGIN not in text or PROFILE_END not in text:
        return out
    block = text.split(PROFILE_BEGIN, 1)[1].split(PROFILE_END, 1)[0]
    placeholder = "(待填)" if IS_ZH else "(to fill)"
    for key, _en, _zh in PROFILE_FIELDS:
        label = _profile_label(key)
        m = re.search(rf"-\s+\*\*{re.escape(label)}\*\*:\s*(.+)", block)
        if m:
            v = m.group(1).strip()
            if v != placeholder:
                out[key] = v
    return out


def _format_changelog_entry(changes: dict, is_first: bool = False) -> str:
    suffix = " (initial)" if not IS_ZH and is_first else (" (首次创建)" if is_first else "")
    lines = [f"### {_now()}{suffix}"]
    for k, v in changes.items():
        lines.append(f"- {_profile_label(k)}: {v}")
    return "\n".join(lines)


@mcp.tool()
def update_research_profile(
    field: str = "",
    directions: str = "",
    keywords: str = "",
    goals: str = "",
    collaborators: str = "",
    notes: str = "",
) -> str:
    """Update the research-profile basic-info block + append a changelog entry.

    Free-form sections (current projects / methods / reading interests) in the same
    file are NEVER touched — they live outside the BEGIN/END_PROFILE sentinel.
    Only fields you provide get updated; others retain previous values.
    """
    page = PAGE["research_profile"]
    p = WIKI_PATH / f"{page}.md"

    incoming = {
        "field": field,
        "directions": directions,
        "keywords": keywords,
        "goals": goals,
        "collaborators": collaborators,
        "notes": notes,
    }
    incoming = {k: v.strip() for k, v in incoming.items() if v.strip()}

    if not p.exists():
        return (
            f"Page {page}.md missing. Run `scinotes init` to create templates first, then re-call this tool."
        )

    text = p.read_text(encoding="utf-8")
    if not incoming:
        existing = _parse_profile_block(text)
        return f"No fields supplied. Currently set: {', '.join(existing.keys()) or '(empty)'}"

    existing = _parse_profile_block(text)
    merged = {**existing, **incoming}

    if PROFILE_BEGIN in text and PROFILE_END in text:
        before, _, rest = text.partition(PROFILE_BEGIN)
        _, _, after = rest.partition(PROFILE_END)
        text = before + _render_profile_block(merged) + after

    entry = _format_changelog_entry(incoming)
    if CHANGELOG_END in text:
        text = text.replace(CHANGELOG_END, f"\n{entry}\n\n{CHANGELOG_END}")
    else:
        title = "## 变更记录" if IS_ZH else "## Changelog"
        text = text.rstrip() + f"\n\n{title}\n\n{CHANGELOG_BEGIN}\n\n{entry}\n\n{CHANGELOG_END}\n"

    p.write_text(text, encoding="utf-8")
    append_log(f"update_research_profile: {len(incoming)} fields")
    return f"Updated: {', '.join(incoming.keys())}"


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------


@mcp.tool()
def wiki_undo_last() -> str:
    """Undo the most recent unwritten-back wiki write.

    Supported: paper_ingest / reading_queue_add / idea_capture / experiment_log /
               wiki_ingest / wiki_memorize.
    Not supported: reading_queue_pop (manually re-add) and update_research_profile
    (free-form interleaving makes safe revert non-trivial).
    """
    if not _JOURNAL_PATH.exists():
        return "No undo log present (.wiki_journal.jsonl)."

    lines = _JOURNAL_PATH.read_text(encoding="utf-8").splitlines()
    target_idx = None
    target = None
    for i in range(len(lines) - 1, -1, -1):
        try:
            entry = json.loads(lines[i])
        except json.JSONDecodeError:
            continue
        if entry.get("undone"):
            continue
        target_idx = i
        target = entry
        break

    if target is None:
        return "Nothing to undo (all entries already undone)."

    page = target.get("page")
    op = target.get("op")
    if not page or not op:
        return f"Malformed journal entry: {target}"

    p = WIKI_PATH / f"{page}.md"
    if not p.exists():
        return f"Target page [[{page}]] no longer exists."

    text = p.read_text(encoding="utf-8")
    new_text = text

    if op == "remove_section":
        header = target["header"]
        text_lines = text.splitlines()
        start = None
        for i, line in enumerate(text_lines):
            if line.strip() == header:
                start = i
                break
        if start is None:
            return f"Section header `{header}` not found — page may have been edited manually."
        end = start + 1
        while end < len(text_lines) and not text_lines[end].lstrip().startswith("## "):
            end += 1
        if start > 0 and not text_lines[start - 1].strip():
            start -= 1
        del text_lines[start:end]
        new_text = "\n".join(text_lines).rstrip() + "\n"
    elif op == "remove_line":
        line = target["line"]
        if line + "\n" in text:
            new_text = text.replace(line + "\n", "", 1)
        elif line in text:
            new_text = text.replace(line, "", 1)
        else:
            return f"Line `{line[:60]}...` not found — page may have been edited manually."
    elif op == "remove_block_text":
        block = target["block"]
        if block in text:
            new_text = text.replace(block, "", 1)
        elif block.strip() in text:
            new_text = text.replace(block.strip(), "", 1)
        else:
            return "Block not found — page may have been edited manually."
    else:
        return f"Unsupported op: {op}"

    new_text = re.sub(r"\n{3,}", "\n\n", new_text)
    if not new_text.endswith("\n"):
        new_text += "\n"
    p.write_text(new_text, encoding="utf-8")

    target["undone"] = True
    target["undone_at"] = _now()
    lines[target_idx] = json.dumps(target, ensure_ascii=False)
    _JOURNAL_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    append_log(f"wiki_undo_last: reverted {target.get('tool')} on [[{page}]]")
    return f"Undone {target.get('tool')} (originally @ {target['ts']}); page [[{page}]] restored."


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    # Allow `python -m scinotes.server /path/to/wiki` as a CLI override
    global WIKI_PATH, _JOURNAL_PATH
    if len(sys.argv) > 1:
        WIKI_PATH = Path(sys.argv[1])
        _JOURNAL_PATH = Path(os.environ.get("SCINOTES_JOURNAL_PATH", str(WIKI_PATH / ".wiki_journal.jsonl")))
    if not WIKI_PATH.exists():
        print(f"[scinotes] error: wiki path does not exist: {WIKI_PATH}", file=sys.stderr)
        print("[scinotes] hint: run `scinotes init <path>` first", file=sys.stderr)
        sys.exit(1)
    print(f"[scinotes] MCP server starting; WIKI_PATH={WIKI_PATH}; lang={BOT_LANG}", file=sys.stderr)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
