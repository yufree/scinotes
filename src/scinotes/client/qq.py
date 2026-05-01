"""QQ frontend (mainland China). Optional — requires `qq-botpy` (`pip install scinotes[qq]`).

NOTE: The QQ Open Platform requires a registered bot which currently demands a
mainland China business verification flow. This frontend is therefore opt-in
and disabled by default.
"""

from __future__ import annotations

import asyncio
import logging
import os

from .core import WikiClient

logger = logging.getLogger(__name__)


class QQFrontend:
    name = "qq"

    def __init__(self, wiki: WikiClient):
        self.wiki = wiki
        self.app_id = os.environ.get("QQ_APP_ID", "")
        self.app_secret = os.environ.get("QQ_APP_SECRET", "")
        self.allowed_openid = os.environ.get("QQ_ALLOWED_OPENID", "")
        self.client = None
        self._task: asyncio.Task | None = None

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.environ.get("QQ_APP_ID")) and bool(os.environ.get("QQ_APP_SECRET"))

    def preflight(self) -> str | None:
        if not self.app_id or not self.app_secret:
            return "QQ_APP_ID / QQ_APP_SECRET missing"
        if not self.allowed_openid:
            return (
                "QQ_ALLOWED_OPENID missing — bot would respond to anyone's C2C messages. "
                "(scinotes refuses to start an open QQ bot.)"
            )
        return None

    async def start(self) -> None:
        err = self.preflight()
        if err:
            raise RuntimeError(f"qq preflight failed: {err}")

        try:
            import botpy
            from botpy import Intents
            from botpy.message import C2CMessage
        except ImportError as e:
            raise RuntimeError(
                "qq-botpy not installed. Install scinotes with the qq extra: "
                "`uv tool install scinotes[qq]` or `pip install scinotes[qq]`"
            ) from e

        wiki = self.wiki
        allowed = self.allowed_openid

        class _Bot(botpy.Client):
            async def on_ready(self_inner):  # noqa: N805
                logger.info(f"QQ bot [{self_inner.robot.name}] online")

            async def on_c2c_message_create(self_inner, message: C2CMessage):  # noqa: N805
                if message.author.user_openid != allowed:
                    return
                text = (message.content or "").strip()
                if not text:
                    return
                logger.info(f"QQ message: {text[:80]}")
                try:
                    response = await wiki.chat(text)
                    await self_inner.api.post_c2c_message(
                        openid=message.author.user_openid,
                        msg_type=0,
                        msg_id=message.id,
                        content=response,
                    )
                except Exception:
                    logger.exception("QQ reply failed")

        intents = Intents(public_messages=True)
        self.client = _Bot(intents=intents)
        self._task = asyncio.create_task(self.client.start(appid=self.app_id, secret=self.app_secret))
        logger.info("QQ frontend task spawned")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
