from telegram.ext import CallbackQueryHandler, CommandHandler

from app.bot.app import build_application


def test_build_application_registers_all_handlers():
    app = build_application()
    handlers = app.handlers[0]  # default group
    names = {h.commands and tuple(h.commands) for h in handlers if isinstance(h, CommandHandler)}
    # A representative sample of the commands that must be wired:
    flat = {c for tup in names if tup for c in tup}
    for expected in {"start", "help", "summary", "months", "insights", "ask", "search",
                     "addsub", "subs", "rmsub", "togglesub", "setbudget", "budgets",
                     "undo", "rebuild"}:
        assert expected in flat, f"/{expected} not registered"
    assert any(isinstance(h, CallbackQueryHandler) for h in handlers), "quick-fix callback missing"
