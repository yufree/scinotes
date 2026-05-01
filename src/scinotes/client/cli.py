"""Interactive terminal frontend (REPL). Useful for first-run testing without IM."""

from __future__ import annotations

import asyncio
import sys

from .core import DEFAULT_MODEL, MODELS, WIKI_PATH, WikiClient


class CLIFrontend:
    name = "cli"

    def __init__(self, wiki: WikiClient):
        self.wiki = wiki
        self._task: asyncio.Task | None = None

    @classmethod
    def is_configured(cls) -> bool:
        return True  # always available

    def preflight(self) -> str | None:
        return None

    async def _repl(self) -> None:
        print()
        print(f"  scinotes — wiki at {WIKI_PATH}")
        print(f"  default model: {DEFAULT_MODEL}; available: {', '.join(sorted(MODELS.keys()))}")
        print("  type 'quit' or Ctrl-D to exit; prefix with @<model> to switch model")
        print()
        loop = asyncio.get_running_loop()
        while True:
            try:
                user_input = await loop.run_in_executor(None, lambda: input("you> "))
            except (EOFError, KeyboardInterrupt):
                print()
                break
            user_input = user_input.strip()
            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "q"):
                break
            try:
                response = await self.wiki.chat(user_input)
                print(f"\nbot> {response}\n")
            except Exception as e:
                print(f"\nerror: {e}\n", file=sys.stderr)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._repl())

    async def wait(self) -> None:
        if self._task:
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
