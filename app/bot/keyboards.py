"""Inline keyboards for quick-fixing a logged transaction."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.models import CATEGORIES


def parse_callback(data: str) -> tuple[str, str, int, str | None]:
    """Parse 'action|YYYY-MM|row[|extra]' -> (action, ym, row, extra)."""
    parts = data.split("|")
    action, ym, row = parts[0], parts[1], int(parts[2])
    extra = parts[3] if len(parts) > 3 else None
    return action, ym, row, extra


def quick_fix_keyboard(ym: str, row: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Fix category", callback_data=f"fixcat|{ym}|{row}"),
         InlineKeyboardButton("↔️ Type", callback_data=f"type|{ym}|{row}")],
        [InlineKeyboardButton("🗑 Delete", callback_data=f"del|{ym}|{row}")],
    ])


def category_picker_keyboard(ym: str, row: int) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    current: list[InlineKeyboardButton] = []
    for cat in CATEGORIES:
        current.append(InlineKeyboardButton(cat, callback_data=f"setcat|{ym}|{row}|{cat}"))
        if len(current) == 3:
            buttons.append(current)
            current = []
    if current:
        buttons.append(current)
    buttons.append([InlineKeyboardButton("⬅ Back", callback_data=f"back|{ym}|{row}")])
    return InlineKeyboardMarkup(buttons)
