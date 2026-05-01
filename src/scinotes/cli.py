"""scinotes command-line entry point.

Subcommands:
    scinotes init <wiki-path> [--lang en|zh-CN]   bootstrap a wiki + .env
    scinotes doctor                                self-check (env, models, MCPs)
    scinotes run [--frontends ...]                 start the bot
    scinotes serve-mcp                             run only the MCP server
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shutil
import sys
from importlib.resources import files
from pathlib import Path


# ---------------------------------------------------------------------------
# .env loading (no extra dep; supports KEY=value, optional quotes, # comments)
# ---------------------------------------------------------------------------
def _load_env_file(path: Path) -> int:
    if not path.exists():
        return 0
    n = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if val and val[0] in ("'", '"') and val[-1] == val[0]:
            val = val[1:-1]
        os.environ.setdefault(key, val)
        n += 1
    return n


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------
def cmd_init(args: argparse.Namespace) -> int:
    wiki_path = Path(args.path).expanduser().resolve()
    lang = "zh-CN" if args.lang.lower().startswith("zh") else "en"

    print(f"[init] wiki path: {wiki_path}")
    print(f"[init] language : {lang}")

    if not wiki_path.exists():
        wiki_path.mkdir(parents=True)
        print("[init] created directory")
    elif not wiki_path.is_dir():
        print(f"[init] error: {wiki_path} exists but is not a directory", file=sys.stderr)
        return 1

    template_dir = files("scinotes.templates") / lang
    n_written = 0
    n_skipped = 0
    for entry in template_dir.iterdir():
        if not entry.name.endswith(".md"):
            continue
        target = wiki_path / entry.name
        if target.exists():
            print(f"[init] skip (already exists): {entry.name}")
            n_skipped += 1
            continue
        target.write_text(entry.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"[init] wrote: {entry.name}")
        n_written += 1

    # Drop a .env.example next to the wiki for convenience
    env_example_target = wiki_path / ".env.example"
    if not env_example_target.exists():
        try:
            # Load the .env.example bundled with scinotes via repo root (alternate path)
            # It's not packaged inside src/, so fall back to writing a minimal one.
            env_example_target.write_text(_DEFAULT_ENV_EXAMPLE, encoding="utf-8")
            print("[init] wrote: .env.example")
        except Exception as e:
            print(f"[init] note: could not write .env.example ({e})")

    env_target = wiki_path / ".env"
    if not env_target.exists():
        env_target.write_text(_DEFAULT_ENV_EXAMPLE, encoding="utf-8")
        print("[init] wrote: .env (please edit before `scinotes run`)")

    print()
    print(f"[init] done — wrote {n_written}, skipped {n_skipped}")
    print()
    print("Next steps:")
    print(f"  1. $EDITOR {env_target}")
    print("  2. scinotes doctor")
    print("  3. scinotes run")
    return 0


_DEFAULT_ENV_EXAMPLE = """# scinotes runtime configuration. See README.md for details.

# Language: en | zh-CN
BOT_LANG=en

# Path to your wiki (this dir, usually).
WIKI_PATH=.

# Frontends: comma-separated list. telegram | qq | cli
FRONTENDS=telegram

# ----- Telegram -----
# Create a bot via @BotFather → token.
TELEGRAM_BOT_TOKEN=
# Your numeric user ID (from @userinfobot). REQUIRED — bot refuses to start without it.
TELEGRAM_USER_ID=

# ----- QQ (mainland China only, optional) -----
# QQ_APP_ID=
# QQ_APP_SECRET=
# QQ_ALLOWED_OPENID=

# ----- LLM models (configure at least one) -----
# DEFAULT_MODEL    — leave commented to auto-pick (ollama if installed, else first cloud model)
# FALLBACK_CHAIN   — leave commented for "all configured models, default-first"
# DEFAULT_MODEL=ollama
# FALLBACK_CHAIN=ollama,claude

# Ollama (local; auto-skipped if unreachable). Set OLLAMA_DISABLE=1 on a VPS without local inference.
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3.2:latest
# OLLAMA_DISABLE=1

# Claude
# ANTHROPIC_API_KEY=
# CLAUDE_MODEL=claude-sonnet-4-6

# OpenAI
# OPENAI_API_KEY=
# OPENAI_MODEL=gpt-4o

# DeepSeek (OpenAI-compatible)
# DEEPSEEK_API_KEY=

# GLM (智谱)
# GLM_API_KEY=
# GLM_MODEL=GLM-4

# Xiaomi MiMo
# MIMO_API_KEY=
# MIMO_MODEL=mimo-v2.5-pro

# ----- Optional external MCP servers -----
# NCBI_API_KEY=
# SEMANTIC_SCHOLAR_API_KEY=
# Zotero (web mode):
# ZOTERO_LIBRARY_ID=
# ZOTERO_LIBRARY_TYPE=user
# ZOTERO_API_KEY=
# Or local mode (Zotero desktop must be running):
# ZOTERO_LOCAL=true

# ----- Optional integrations -----
# BRAVE_API_KEY=
# GROQ_API_KEY=
"""


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------
def cmd_doctor(args: argparse.Namespace) -> int:
    import httpx

    GREEN = "\033[32m✓\033[0m"
    YELLOW = "\033[33m~\033[0m"
    RED = "\033[31m✗\033[0m"

    def line(status: str, msg: str) -> None:
        print(f"  {status}  {msg}")

    print("scinotes doctor\n")

    # Wiki
    wiki = os.environ.get("WIKI_PATH", "")
    if not wiki:
        line(RED, "WIKI_PATH not set in env")
    else:
        wp = Path(wiki).expanduser()
        if not wp.exists():
            line(RED, f"WIKI_PATH={wp} does not exist (run `scinotes init {wp}`)")
        else:
            has_claude = (wp / "CLAUDE.md").exists()
            line(
                GREEN if has_claude else YELLOW,
                f"WIKI_PATH={wp} (CLAUDE.md {'present' if has_claude else 'missing'})",
            )

    # Frontends
    frontends_env = os.environ.get("FRONTENDS", "telegram")
    line(GREEN, f"FRONTENDS={frontends_env}")
    if "telegram" in frontends_env:
        if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_USER_ID"):
            line(GREEN, "  telegram: token + allowed user id present")
        else:
            line(RED, "  telegram: missing TELEGRAM_BOT_TOKEN or TELEGRAM_USER_ID")
    if "qq" in frontends_env:
        if os.environ.get("QQ_APP_ID") and os.environ.get("QQ_APP_SECRET"):
            line(GREEN, "  qq: id+secret present")
        else:
            line(RED, "  qq: missing QQ_APP_ID / QQ_APP_SECRET")

    # Models
    print()
    print("models:")
    from .client.core import DEFAULT_MODEL, FALLBACK_CHAIN, MODELS

    if not MODELS:
        line(RED, "no models configured")
    else:
        for name, cfg in MODELS.items():
            mark = " (default)" if name == DEFAULT_MODEL else ""
            line(GREEN, f"{name}{mark}: {cfg['provider']} → {cfg['model']}")

    # Ollama liveness check (only if registered)
    if "ollama" in MODELS:
        try:
            r = httpx.get(f"{MODELS['ollama']['base']}/api/tags", timeout=3)
            if r.status_code == 200:
                tags = [m.get("name", "?") for m in r.json().get("models", [])]
                line(GREEN, f"  ollama reachable; {len(tags)} model(s): {', '.join(tags[:5])}")
                want = MODELS["ollama"]["model"]
                if want not in tags:
                    line(YELLOW, f"  ollama: model '{want}' not pulled yet; run `ollama pull {want}`")
            else:
                line(RED, f"  ollama HTTP {r.status_code}")
        except Exception as e:
            line(RED, f"  ollama unreachable at {MODELS['ollama']['base']}: {e}")

    # External MCP runners
    print()
    print("external runtimes:")
    for binary, hint in [
        ("npx", "needed for PubMed / Semantic Scholar MCP servers"),
        ("uvx", "needed for Zotero MCP server"),
    ]:
        path = shutil.which(binary)
        if path:
            line(GREEN, f"{binary} → {path}")
        else:
            line(YELLOW, f"{binary} not found ({hint})")

    print()
    print(f"fallback chain: {FALLBACK_CHAIN}")
    return 0


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------
async def _run_async(frontends: list[str]) -> None:
    from .client.cli import CLIFrontend
    from .client.core import WikiClient

    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=logging.INFO,
    )
    logger = logging.getLogger("scinotes")

    wiki = WikiClient()
    await wiki.connect()

    started: list = []
    cli_fe: CLIFrontend | None = None

    try:
        if "telegram" in frontends:
            from .client.telegram import TelegramFrontend

            tg = TelegramFrontend(wiki)
            err = tg.preflight()
            if err:
                logger.warning(f"skipping telegram: {err}")
            else:
                await tg.start()
                started.append(tg)

        if "qq" in frontends:
            from .client.qq import QQFrontend

            qq = QQFrontend(wiki)
            err = qq.preflight()
            if err:
                logger.warning(f"skipping qq: {err}")
            else:
                await qq.start()
                started.append(qq)

        if "cli" in frontends or not started:
            if not started:
                logger.info("no IM frontend configured — falling back to interactive CLI")
            cli_fe = CLIFrontend(wiki)
            await cli_fe.start()
            started.append(cli_fe)

        if cli_fe:
            await cli_fe.wait()
        else:
            while True:
                await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("shutting down…")
    finally:
        for fe in started:
            try:
                await fe.stop()
            except Exception:
                pass
        await wiki.close()


def cmd_run(args: argparse.Namespace) -> int:
    if args.frontends:
        frontends = [f.strip() for f in args.frontends.split(",") if f.strip()]
    else:
        frontends = [f.strip() for f in os.environ.get("FRONTENDS", "telegram").split(",") if f.strip()]

    valid = {"telegram", "qq", "cli"}
    bad = set(frontends) - valid
    if bad:
        print(f"unknown frontends: {','.join(bad)} (valid: {','.join(valid)})", file=sys.stderr)
        return 1
    try:
        asyncio.run(_run_async(frontends))
    except KeyboardInterrupt:
        pass
    return 0


# ---------------------------------------------------------------------------
# serve-mcp
# ---------------------------------------------------------------------------
def cmd_serve_mcp(args: argparse.Namespace) -> int:
    from .server import main as server_main

    server_main()
    return 0


# ---------------------------------------------------------------------------
# entry
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        prog="scinotes",
        description="Research assistant bot backed by a markdown wiki.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="bootstrap a wiki dir with templates")
    p_init.add_argument("path", help="directory to create / populate")
    p_init.add_argument("--lang", default="en", help="en | zh-CN (default: en)")
    p_init.set_defaults(func=cmd_init)

    p_doctor = sub.add_parser("doctor", help="self-check env, models, MCP runtimes")
    p_doctor.set_defaults(func=cmd_doctor)

    p_run = sub.add_parser("run", help="start frontends and the bot")
    p_run.add_argument("--frontends", default="", help="comma-separated subset of telegram,qq,cli")
    p_run.set_defaults(func=cmd_run)

    p_serve = sub.add_parser("serve-mcp", help="run only the MCP server (stdio)")
    p_serve.set_defaults(func=cmd_serve_mcp)

    args = parser.parse_args()

    # For run / doctor / serve-mcp: source `.env` from cwd or WIKI_PATH if present
    if args.cmd in ("run", "doctor", "serve-mcp"):
        for cand in (
            Path.cwd() / ".env",
            Path(os.environ.get("WIKI_PATH", "")) / ".env" if os.environ.get("WIKI_PATH") else None,
        ):
            if cand and cand.exists():
                n = _load_env_file(cand)
                print(f"[scinotes] loaded {n} vars from {cand}", file=sys.stderr)
                break

    rc = args.func(args)
    sys.exit(rc)


if __name__ == "__main__":
    main()
