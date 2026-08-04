import app.bot.handlers.transactions as handlers
from app.config import ALLOWED_USER_ID
from app.llm_parser import RouterParseError
from app.models import RouterResult


class _Message:
    """Stands in for a Telegram message, capturing what we would have sent."""

    def __init__(self, text: str):
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class _Update:
    """Minimal stand-in for a Telegram update from the authorised user."""

    def __init__(self, text: str):
        self.message = _Message(text)
        self.effective_user = type("_User", (), {"id": ALLOWED_USER_ID})()


def test_legacy_single_call_path_is_gone():
    # The router handles single transactions strictly better; the flag protected nothing.
    import app.config
    assert not hasattr(handlers, "_handle_log_direct")
    assert not hasattr(app.config, "USE_INTENT_ROUTER")


async def test_a_lexicon_hit_is_logged_without_calling_the_model(monkeypatch):
    logged = []

    async def _capture_log(update, transactions):
        logged.extend(transactions)

    async def _explode(text):
        raise AssertionError("the model must not be called for a lexicon hit")

    monkeypatch.setattr(handlers, "_handle_log", _capture_log)
    monkeypatch.setattr(handlers, "route_message", _explode)

    update = _Update("carwash 250")
    await handlers.message_handler(update, None)

    assert len(logged) == 1
    assert logged[0].category == "Transport"
    assert logged[0].amount == 250


async def test_an_unreadable_answer_does_not_look_like_a_genuine_unknown(monkeypatch):
    async def _unreadable(text):
        raise RouterParseError("model returned nonsense")

    monkeypatch.setattr(handlers, "route_message", _unreadable)

    update = _Update("mystery purchase 999")
    await handlers.message_handler(update, None)

    assert update.message.replies == [handlers._UNREADABLE_REPLY]
    assert handlers._UNREADABLE_REPLY != handlers._UNKNOWN_REPLY


async def test_a_genuine_unknown_gets_the_unknown_reply(monkeypatch):
    async def _unknown(text):
        return RouterResult(intent="unknown")

    monkeypatch.setattr(handlers, "route_message", _unknown)

    update = _Update("mystery purchase 999")
    await handlers.message_handler(update, None)

    assert update.message.replies == [handlers._UNKNOWN_REPLY]
