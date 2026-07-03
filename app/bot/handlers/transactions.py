"""Transaction logging: router-driven message handler, quick-fix callbacks, /undo."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.config import ALLOWED_USER_ID, now_local
from app.formatting import format_money
from app.insights import compose_query_answer
from app.llm_parser import RateLimitError, parse_receipt, route_message
from app.sheets import transactions as tx
from app.sheets.transactions import append_transaction, get_monthly_summary
from app.bot.keyboards import parse_callback, quick_fix_keyboard, category_picker_keyboard
from app.bot.handlers.reports import is_authorised

logger = logging.getLogger(__name__)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return
    text = update.message.text
    logger.info("Received message from %s: %s", update.effective_user.id, text)
    try:
        result = await route_message(text)
    except RateLimitError:
        await update.message.reply_text(
            "⏳ The AI service is rate-limited right now. Please wait a minute and try again."
        )
        return
    except Exception:
        logger.exception("Routing failed for message: %s", text)
        await update.message.reply_text("❌ Something went wrong understanding that message.")
        return

    if result.intent == "query" and result.query:
        await _handle_query(update, result.query)
        return
    if result.intent == "log" and result.transactions:
        await _handle_log(update, result.transactions)
        return
    await update.message.reply_text(
        "❌ Sorry, I couldn't understand that. Try 'spent 200 on groceries' "
        "or ask 'how much did I spend on food this month?'"
    )


async def _handle_query(update: Update, query) -> None:
    period = query.period or now_local().strftime("%Y-%m")
    try:
        s = get_monthly_summary(period)
    except Exception:
        await update.message.reply_text(f"❌ No data found for {period}.")
        return
    await update.message.reply_text(compose_query_answer(s, query.metric, query.category, period))


async def _handle_log(update: Update, transactions) -> None:
    now = now_local().strftime("%Y-%m-%d %H:%M")
    ym = now[:7]
    for txn in transactions:
        try:
            row = append_transaction(date=now, description=txn.description,
                                     category=txn.category, amount=txn.amount, txn_type=txn.type)
        except Exception:
            logger.exception("Append failed")
            await update.message.reply_text(f"❌ Failed to save: {txn.description}")
            continue
        reply = f"✅ {format_money(txn.amount)} ({txn.category}) — {txn.description}"
        if txn.type == "Expense":
            try:
                from app.sheets.budgets import budget_alert_for
                alert = budget_alert_for(txn.category, ym)
                if alert:
                    reply += f"\n{alert}"
            except Exception:
                logger.exception("Budget alert lookup failed (non-fatal)")
        await update.message.reply_text(reply, reply_markup=quick_fix_keyboard(ym, row))


async def quickfix_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if update.effective_user is None or update.effective_user.id != ALLOWED_USER_ID:
        await q.answer()
        return
    await q.answer()
    action, ym, row, extra = parse_callback(q.data)
    try:
        if action == "fixcat":
            await q.edit_message_reply_markup(reply_markup=category_picker_keyboard(ym, row))
        elif action == "back":
            await q.edit_message_reply_markup(reply_markup=quick_fix_keyboard(ym, row))
        elif action == "setcat":
            tx.update_transaction_category(ym, row, extra)
            await q.edit_message_text(f"✅ Category updated to {extra}.")
        elif action == "type":
            new_type = tx.toggle_transaction_type(ym, row)
            await q.edit_message_text(f"✅ Type set to {new_type}.")
        elif action == "del":
            tx.delete_transaction_row(ym, row)
            await q.edit_message_text("🗑 Deleted.")
    except Exception:
        logger.exception("Quick-fix callback failed: %s", q.data)
        await q.edit_message_text("❌ That entry no longer exists.")


async def undo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return
    ym = now_local().strftime("%Y-%m")
    last = tx.get_last_transaction(ym)
    if not last:
        await update.message.reply_text("Nothing to undo this month.")
        return
    row, vals = last
    tx.delete_transaction_row(ym, row)
    desc = vals[1] if len(vals) > 1 else ""
    await update.message.reply_text(f"↩️ Undid last entry: {desc}")


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return
    await update.message.reply_text("🧾 Reading receipt …")
    try:
        tg_file = await update.message.photo[-1].get_file()
        data = bytes(await tg_file.download_as_bytearray())
        txn = await parse_receipt(data)
    except RateLimitError:
        await update.message.reply_text("⏳ The AI service is unavailable. Try again later.")
        return
    except Exception:
        logger.exception("Receipt parsing failed")
        await update.message.reply_text("❌ Couldn't read the receipt — try typing it instead.")
        return
    now = now_local().strftime("%Y-%m-%d %H:%M")
    ym = now[:7]
    try:
        row = append_transaction(date=now, description=txn.description,
                                 category=txn.category, amount=txn.amount, txn_type=txn.type)
    except Exception:
        logger.exception("Append from receipt failed")
        await update.message.reply_text("❌ I read the receipt but couldn't save it.")
        return
    await update.message.reply_text(
        f"✅ {format_money(txn.amount)} ({txn.category}) — {txn.description}",
        reply_markup=quick_fix_keyboard(ym, row),
    )
