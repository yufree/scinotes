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

## Releasing (maintainer notes)

Releases are tag-driven. Push a `vX.Y.Z` tag → `.github/workflows/release.yml` runs →
PyPI publish via [Trusted Publishing](https://docs.pypi.org/trusted-publishers/) +
GitHub release draft.

### One-time setup (before the first release)

#### 1. PyPI: register a pending trusted publisher

1. Sign in at https://pypi.org (or create an account first).
2. Go to https://pypi.org/manage/account/publishing/.
3. Under **Add a new pending publisher**, fill:
   - **PyPI Project Name**: `scinotes`
   - **Owner**: your GitHub username/org
   - **Repository name**: `scinotes`
   - **Workflow name**: `release.yml`
   - **Environment name**: `pypi`
4. Submit. PyPI now trusts that workflow to publish under that project name on the
   first push, no API token needed.

After the first successful publish, the project becomes a regular PyPI project; the
trusted publisher is auto-promoted to "active".

#### 2. GitHub: create the `pypi` environment

1. Repo → **Settings** → **Environments** → **New environment** → name it `pypi`.
2. (Optional but recommended) add **Required reviewers** so a human approves before
   each PyPI push, and **Deployment branches** to restrict release to main / tags.

That's it. No API tokens, no secrets to manage.

### Cutting a release

```bash
# 1. Bump version in pyproject.toml + add a CHANGELOG entry. Commit.
# 2. Tag and push:
git tag -a v0.2.0 -m "v0.2.0"
git push origin v0.2.0
# 3. Watch GitHub Actions. Once the publish-pypi job succeeds, review the drafted
#    GitHub release and publish it via the UI.
```

### Testing the package locally before tagging

```bash
uv build
uv run --with "scinotes[ocr]" --refresh-package scinotes \
    --from "$(ls -t dist/*.whl | head -1)" scinotes --help
```

For TestPyPI dry-runs, use `uv publish --repository testpypi` manually — the CI
workflow only targets prod PyPI.

## License

By contributing, you agree your code is licensed under the MIT license, same as the project.
