"""Telegram Bot integration with command parsing and media handling."""

from __future__ import annotations

import io
from typing import Any, Callable, Coroutine, Optional

from executiveai.config import get_settings
from executiveai.logging_config import get_logger

logger = get_logger(__name__)

CommandHandler = Callable[..., Coroutine[Any, Any, str]]


class TelegramBot:
    """Full-featured Telegram bot with command routing and media support."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._app = None
        self._command_handlers: dict[str, CommandHandler] = {}
        self._message_handler: Optional[CommandHandler] = None

    @property
    def is_configured(self) -> bool:
        return bool(self._settings.telegram_bot_token)

    def _check_user_allowed(self, user_id: int) -> bool:
        """Check if the Telegram user is in the allowed list."""
        allowed = self._settings.allowed_telegram_ids
        return not allowed or user_id in allowed

    def register_command(self, command: str, handler: CommandHandler) -> None:
        """Register a command handler (e.g., /schedule, /email)."""
        self._command_handlers[command.lstrip("/")] = handler
        logger.debug("telegram_command_registered", command=command)

    def set_message_handler(self, handler: CommandHandler) -> None:
        """Set the default handler for non-command messages."""
        self._message_handler = handler

    async def start(self) -> None:
        """Start the Telegram bot polling loop."""
        if not self.is_configured:
            logger.warning("telegram_not_configured")
            return

        from telegram import Update
        from telegram.ext import (
            Application,
            CommandHandler as TGCommandHandler,
            MessageHandler,
            filters,
        )

        self._app = Application.builder().token(self._settings.telegram_bot_token).build()

        async def _handle_start(update: Update, context) -> None:
            if not update.effective_user or not self._check_user_allowed(update.effective_user.id):
                return
            await update.message.reply_text(
                "ExecutiveAI is ready. Send me a message or use /help for commands."
            )

        async def _handle_help(update: Update, context) -> None:
            if not update.effective_user or not self._check_user_allowed(update.effective_user.id):
                return
            commands = "\n".join(f"/{cmd}" for cmd in self._command_handlers)
            await update.message.reply_text(
                f"Available commands:\n/start\n/help\n{commands}\n\nOr just send a message."
            )

        async def _handle_command(update: Update, context) -> None:
            if not update.effective_user or not self._check_user_allowed(update.effective_user.id):
                await update.message.reply_text("Unauthorized.")
                return
            cmd = update.message.text.split()[0].lstrip("/").split("@")[0]
            handler = self._command_handlers.get(cmd)
            if handler:
                args = update.message.text.split(maxsplit=1)[1] if " " in update.message.text else ""
                try:
                    result = await handler(
                        user_id=str(update.effective_user.id),
                        args=args,
                        message=update.message,
                    )
                    await update.message.reply_text(result, parse_mode="Markdown")
                except Exception as exc:
                    logger.error("telegram_command_error", cmd=cmd, error=str(exc))
                    await update.message.reply_text(f"Error: {exc}")
            else:
                await update.message.reply_text(f"Unknown command: /{cmd}")

        async def _handle_message(update: Update, context) -> None:
            if not update.effective_user or not self._check_user_allowed(update.effective_user.id):
                return
            if self._message_handler:
                try:
                    result = await self._message_handler(
                        user_id=str(update.effective_user.id),
                        text=update.message.text or "",
                        message=update.message,
                    )
                    await update.message.reply_text(result, parse_mode="Markdown")
                except Exception as exc:
                    logger.error("telegram_message_error", error=str(exc))
                    await update.message.reply_text(f"Error processing message: {exc}")

        async def _handle_voice(update: Update, context) -> None:
            if not update.effective_user or not self._check_user_allowed(update.effective_user.id):
                return
            voice = update.message.voice or update.message.audio
            if voice:
                file = await context.bot.get_file(voice.file_id)
                buf = io.BytesIO()
                await file.download_to_memory(buf)
                await update.message.reply_text("Voice message received. Processing...")

        async def _handle_document(update: Update, context) -> None:
            if not update.effective_user or not self._check_user_allowed(update.effective_user.id):
                return
            doc = update.message.document
            if doc:
                file = await context.bot.get_file(doc.file_id)
                buf = io.BytesIO()
                await file.download_to_memory(buf)
                await update.message.reply_text(f"Received file: {doc.file_name} ({doc.file_size} bytes)")

        self._app.add_handler(TGCommandHandler("start", _handle_start))
        self._app.add_handler(TGCommandHandler("help", _handle_help))
        for cmd in self._command_handlers:
            self._app.add_handler(TGCommandHandler(cmd, _handle_command))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_message))
        self._app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, _handle_voice))
        self._app.add_handler(MessageHandler(filters.Document.ALL, _handle_document))

        logger.info("telegram_bot_starting")
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            logger.info("telegram_bot_stopped")

    async def send_message(self, chat_id: int | str, text: str, parse_mode: str = "Markdown") -> None:
        """Send a message to a specific chat."""
        if self._app:
            await self._app.bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)

    async def send_file(self, chat_id: int | str, file_path: str, caption: str = "") -> None:
        """Send a file to a specific chat."""
        if self._app:
            with open(file_path, "rb") as f:
                await self._app.bot.send_document(chat_id=chat_id, document=f, caption=caption)
