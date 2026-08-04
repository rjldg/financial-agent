"""/ask must not go silent when the model gives an unreadable answer.

message_handler already catches RouterParseError and RateLimitError and
replies; ask_handler called route_message with no try/except at all, so a
RouterParseError escaped straight to python-telegram-bot and the user got
no reply whatsoever.
"""
import app.bot.handlers.queries as handlers
from app.config import ALLOWED_USER_ID
from app.llm_parser import RateLimitError, RouterParseError


class _Message:
    """Stands in for a Telegram message, capturing what we would have sent."""

    def __init__(self):
        self.replies: list[str] = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class _Context:
    def __init__(self, args):
        self.args = args


class _Update:
    """Minimal stand-in for a Telegram update from the authorised user."""

    def __init__(self):
        self.message = _Message()
        self.effective_user = type("_User", (), {"id": ALLOWED_USER_ID})()


async def test_ask_replies_instead_of_crashing_on_unreadable_answer(monkeypatch):
    async def _unreadable(text):
        raise RouterParseError("model returned nonsense")

    monkeypatch.setattr(handlers, "route_message", _unreadable)

    update = _Update()
    await handlers.ask_handler(update, _Context(["how", "much", "on", "food"]))

    assert len(update.message.replies) == 1


async def test_ask_replies_instead_of_crashing_when_rate_limited(monkeypatch):
    async def _rate_limited(text):
        raise RateLimitError("Ollama unreachable")

    monkeypatch.setattr(handlers, "route_message", _rate_limited)

    update = _Update()
    await handlers.ask_handler(update, _Context(["how", "much", "on", "food"]))

    assert len(update.message.replies) == 1
