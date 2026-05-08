"""Slack frontend — Socket Mode, single-owner bot.

Required env vars:
  SLACK_BOT_TOKEN        xoxb-... Bot User OAuth Token
  SLACK_APP_TOKEN        xapp-... App-Level Token (connections:write scope)
  SLACK_ALLOWED_USER_IDS comma-separated Slack member IDs (e.g. U012AB3CD)

In DMs  : responds to every message from allowed users.
In channels: responds only when @mentioned (strips the mention before passing to LLM).
Channel name is prepended as context so the LLM can adapt behavior per channel
(e.g. #lifenotes → personal wiki mode, #scinotes → research mode).
"""

from __future__ import annotations

import asyncio
import logging
import os

import httpx

from .core import WIKI_PATH, WikiClient

logger = logging.getLogger(__name__)


class SlackFrontend:
    name = "slack"

    def __init__(self, wiki: WikiClient):
        self.wiki = wiki
        self.bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
        self.app_token = os.environ.get("SLACK_APP_TOKEN", "")
        raw_ids = os.environ.get("SLACK_ALLOWED_USER_IDS", "")
        self.allowed_user_ids = {u.strip() for u in raw_ids.split(",") if u.strip()}
        self._bot_user_id: str | None = None  # cached after first auth_test
        self._handler = None

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.environ.get("SLACK_BOT_TOKEN") and os.environ.get("SLACK_APP_TOKEN"))

    def preflight(self) -> str | None:
        if not self.bot_token:
            return "SLACK_BOT_TOKEN missing"
        if not self.app_token:
            return "SLACK_APP_TOKEN missing (needed for Socket Mode)"
        if not self.allowed_user_ids:
            return (
                "SLACK_ALLOWED_USER_IDS missing — bot would accept anyone's messages. "
                "Find your member ID in Slack profile → ⋯ → Copy member ID."
            )
        return None

    def _is_allowed(self, user_id: str) -> bool:
        return user_id in self.allowed_user_ids

    async def _get_bot_user_id(self, client) -> str:
        if not self._bot_user_id:
            res = await client.auth_test()
            self._bot_user_id = res["user_id"]
        return self._bot_user_id

    async def start(self) -> None:
        err = self.preflight()
        if err:
            raise RuntimeError(f"slack preflight failed: {err}")

        try:
            from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
            from slack_bolt.async_app import AsyncApp
        except ImportError as e:
            raise RuntimeError(
                "slack-bolt not installed. Install scinotes with the slack extra: "
                "`uv tool install 'scinotes[slack]'` or `pip install 'scinotes[slack]'`"
            ) from e

        app = AsyncApp(token=self.bot_token)

        @app.event("message")
        async def handle_message(event, say, client):
            user_id = event.get("user", "")
            if not user_id or not self._is_allowed(user_id):
                return
            # Skip bot messages and subtypes (edits, joins, etc.)
            if event.get("bot_id") or event.get("subtype"):
                return

            channel = event.get("channel", "")
            channel_type = event.get("channel_type", "")
            text = event.get("text", "").strip()

            # In channels (not DMs): only respond when @mentioned
            if channel_type != "im":
                bot_id = await self._get_bot_user_id(client)
                mention = f"<@{bot_id}>"
                if mention not in text:
                    return
                text = text.replace(mention, "").strip()

            files = event.get("files", [])
            if files:
                for f in files:
                    if f.get("mimetype") == "application/pdf":
                        await self._handle_pdf(f, text, channel, say, client)
                        return

            if not text:
                return

            # Resolve channel name for LLM context
            channel_name = ""
            if channel_type != "im":
                try:
                    info = await client.conversations_info(channel=channel)
                    channel_name = info["channel"].get("name", "")
                except Exception:
                    pass

            prompt = f"[channel: #{channel_name}]\n{text}" if channel_name else text

            # Post placeholder then update in-place
            thread_ts = event.get("thread_ts") or event.get("ts")
            placeholder = await say(text="…", thread_ts=thread_ts)
            placeholder_ts = placeholder.get("ts")
            logger.info(f"Slack placeholder posted: channel={channel} ts={placeholder_ts} user={user_id}")

            try:
                response = await asyncio.wait_for(self.wiki.chat(prompt), timeout=180)
                await client.chat_update(channel=channel, ts=placeholder_ts, text=response)
                logger.info(f"Slack response sent: channel={channel} ts={placeholder_ts}")
            except asyncio.TimeoutError:
                await client.chat_update(channel=channel, ts=placeholder_ts, text="（LLM 响应超时，请重试）")
                logger.error("slack handler: wiki.chat() timed out after 180s")
            except Exception as e:
                logger.exception("slack message handler failed")
                await client.chat_update(channel=channel, ts=placeholder_ts, text=f"Error: {e}")

        # Register app_mention to silence slack-bolt's "unhandled event" warning.
        # Actual handling is done in handle_message above (which also fires in channels).
        @app.event("app_mention")
        async def handle_mention(event, say, client):
            pass

        self._handler = AsyncSocketModeHandler(app, self.app_token)
        await self._handler.start_async()
        logger.info("Slack frontend ready (Socket Mode)")

    async def _handle_pdf(self, file_info: dict, caption: str, channel: str, say, client) -> None:
        cache_dir = WIKI_PATH / ".cache_pdf"
        cache_dir.mkdir(exist_ok=True)
        filename = file_info.get("name", "upload.pdf")
        file_path = cache_dir / filename

        placeholder = await say(text="Receiving PDF, analyzing…")
        placeholder_ts = placeholder.get("ts")

        try:
            url = file_info.get("url_private_download") or file_info.get("url_private", "")
            async with httpx.AsyncClient(timeout=60) as http:
                resp = await http.get(url, headers={"Authorization": f"Bearer {self.bot_token}"})
                resp.raise_for_status()
            file_path.write_bytes(resp.content)

            prompt = (
                f"[system: PDF saved at {file_path}. Use read_local_pdf to extract & summarize.]\n"
                f"User note: {caption or 'summarize the key points'}"
            )
            response = await self.wiki.chat(prompt)
            await client.chat_update(channel=channel, ts=placeholder_ts, text=response)
        except Exception as e:
            logger.exception("slack pdf handler failed")
            await client.chat_update(channel=channel, ts=placeholder_ts, text=f"PDF error: {e}")
        finally:
            if file_path.exists():
                file_path.unlink(missing_ok=True)

    async def stop(self) -> None:
        if self._handler:
            await self._handler.close_async()
