"""Telegram frontend — runs as an awaitable lifecycle (start/idle/stop)."""

from __future__ import annotations

import logging
import os

import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from .core import WIKI_PATH, WikiClient

logger = logging.getLogger(__name__)


class TelegramFrontend:
    name = "telegram"

    def __init__(self, wiki: WikiClient):
        self.wiki = wiki
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        user_id_raw = os.environ.get("TELEGRAM_USER_ID", "")
        try:
            self.allowed_user_id = int(user_id_raw) if user_id_raw else None
        except ValueError:
            self.allowed_user_id = None
        self.app: Application | None = None

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.environ.get("TELEGRAM_BOT_TOKEN"))

    def preflight(self) -> str | None:
        """Return None if ready, else error string."""
        if not self.token:
            return "TELEGRAM_BOT_TOKEN missing"
        if not self.allowed_user_id:
            return (
                "TELEGRAM_USER_ID missing or invalid — bot would accept ANYONE's messages. "
                "Get your numeric user id from @userinfobot and set TELEGRAM_USER_ID. "
                "(scinotes refuses to start an open Telegram bot.)"
            )
        return None

    def _is_allowed(self, user_id: int) -> bool:
        return user_id == self.allowed_user_id

    async def _start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not self._is_allowed(user.id):
            await update.message.reply_text("Sorry, this bot serves a single owner.")
            return
        await update.message.reply_html(
            rf"Hi {user.mention_html()}! scinotes ready — your wiki is at <code>{WIKI_PATH}</code>."
        )

    async def _on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update.effective_user.id):
            return
        text = update.message.text
        if not text:
            return
        placeholder = await update.message.reply_text("…thinking")
        try:
            response = await self.wiki.chat(text)
            await placeholder.edit_text(response)
        except Exception as e:
            logger.exception("telegram text handler failed")
            await placeholder.edit_text(f"Error: {e}")

    async def _on_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update.effective_user.id):
            return
        doc = update.message.document
        if not doc or doc.mime_type != "application/pdf":
            await update.message.reply_text("Only PDF documents are supported here.")
            return
        placeholder = await update.message.reply_text("Receiving PDF, analyzing…")
        cache_dir = WIKI_PATH / ".cache_pdf"
        cache_dir.mkdir(exist_ok=True)
        file_path = cache_dir / doc.file_name
        try:
            tg_file = await context.bot.get_file(doc.file_id)
            await tg_file.download_to_drive(str(file_path))
            caption = update.message.caption or "summarize the key points"
            prompt = (
                f"[system: PDF saved at {file_path}. Use read_local_pdf to extract & summarize.]\n"
                f"User note: {caption}"
            )
            response = await self.wiki.chat(prompt)
            await placeholder.edit_text(response)
        except Exception as e:
            logger.exception("telegram document handler failed")
            await placeholder.edit_text(f"PDF error: {e}")
        finally:
            if file_path.exists():
                file_path.unlink(missing_ok=True)

    async def _on_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update.effective_user.id):
            return
        audio = update.message.voice or update.message.audio
        if not audio:
            return
        groq_key = os.environ.get("GROQ_API_KEY", "")
        if not groq_key:
            await update.message.reply_text("Voice messages need GROQ_API_KEY for transcription.")
            return
        placeholder = await update.message.reply_text("🎙 transcribing…")
        cache_dir = WIKI_PATH / ".cache_audio"
        cache_dir.mkdir(exist_ok=True)
        file_path = cache_dir / f"{audio.file_id}.ogg"
        try:
            tg_file = await context.bot.get_file(audio.file_id)
            await tg_file.download_to_drive(str(file_path))
            async with httpx.AsyncClient(timeout=30) as client:
                with open(file_path, "rb") as f:
                    files = {"file": (file_path.name, f, "audio/ogg")}
                    data = {"model": "whisper-large-v3-turbo"}
                    headers = {"Authorization": f"Bearer {groq_key}"}
                    resp = await client.post(
                        "https://api.groq.com/openai/v1/audio/transcriptions",
                        files=files,
                        data=data,
                        headers=headers,
                    )
            resp.raise_for_status()
            text = resp.json().get("text", "").strip()
            if not text:
                await placeholder.edit_text("(transcription empty)")
                return
            await placeholder.edit_text(f"🎤 heard:\n«{text}»\n💬 processing…")
            response = await self.wiki.chat(
                f"[system: voice transcript: {text}]\nuser note: {update.message.caption or ''}"
            )
            await placeholder.edit_text(f"🎤 «{text}»\n\n📝 {response}")
        except Exception as e:
            logger.exception("telegram voice handler failed")
            await placeholder.edit_text(f"Voice error: {e}")
        finally:
            if file_path.exists():
                file_path.unlink(missing_ok=True)

    async def start(self) -> None:
        err = self.preflight()
        if err:
            raise RuntimeError(f"telegram preflight failed: {err}")
        self.app = Application.builder().token(self.token).build()
        self.app.add_handler(CommandHandler("start", self._start))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))
        self.app.add_handler(MessageHandler(filters.Document.ALL, self._on_document))
        self.app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, self._on_voice))
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        logger.info("Telegram frontend ready")

    async def stop(self) -> None:
        if self.app and self.app.updater and self.app.updater.running:
            await self.app.updater.stop()
        if self.app:
            await self.app.stop()
            await self.app.shutdown()
