# Contributing to scinotes

Thanks for your interest. scinotes is a small project; PRs are welcome but please open an issue first for anything beyond a typo or a minor doc fix — that way we can talk through scope before you spend time.

## Dev setup

```bash
git clone https://github.com/scinotes/scinotes
cd scinotes
uv sync --extra dev --extra qq
```

The package installs in editable mode. Run with:

```bash
uv run scinotes init /tmp/scinotes-dev-wiki --lang en
$EDITOR /tmp/scinotes-dev-wiki/.env
uv run scinotes doctor
uv run scinotes run --frontends cli
```

## Lint & format

```bash
uv run ruff check .
uv run ruff format .
```

## Tests

```bash
uv run pytest
```

Tests are intentionally light. Smoke-test on a fresh wiki with `scinotes init`, run a couple tool calls via the CLI frontend, and ensure `wiki_undo_last` round-trips.

## What we like

- Bug fixes with minimal scope.
- New language packs: drop `prompts/system.<lang>.md` + `templates/<lang>/*.md`.
- New frontends as plug-in modules following the same `start/stop/preflight` shape.
- New optional MCP server integrations.

## What we'd push back on

- Proprietary lock-in (vector DB requirements, hosted-only flows).
- Removing the markdown-first invariant — every state must remain greppable / git-trackable.
- Tools that exfiltrate user data or make outbound calls without explicit user action.

## Code style

- Python 3.10 syntax (`X | Y`, `from __future__ import annotations` where helpful).
- 110-char line length, ruff-formatted.
- Public API: type hints required.
- No new mandatory deps without a strong case. We deliberately stay slim.

## License

By contributing, you agree your code is licensed under the MIT license, same as the project.
