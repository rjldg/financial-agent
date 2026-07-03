"""Telegram application bootstrap and entry point."""
from __future__ import annotations

import asyncio
import logging

from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
)

from app.config import TELEGRAM_TOKEN
from app.bot.handlers.reports import start_handler, summary_handler, months_handler
from app.bot.handlers.transactions import message_handler

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO,
)
logger = logging.getLogger(__name__)


def build_application():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("summary", summary_handler))
    app.add_handler(CommandHandler("months", months_handler))
    from app.bot.handlers.reports import rebuild_handler
    app.add_handler(CommandHandler("rebuild", rebuild_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    return app


def main() -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    app = build_application()
    try:
        from app.sheets import dashboard
        dashboard.ensure_core_tabs()
    except Exception:
        logger.exception("Could not ensure core tabs at startup (continuing)")
    try:
        from app.scheduler import register_jobs
        register_jobs(app)
    except Exception:
        logger.exception("Could not register scheduled jobs (continuing)")
    logger.info("Bot started — listening for messages …")
    app.run_polling()


if __name__ == "__main__":
    main()
