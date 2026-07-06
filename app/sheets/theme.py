"""Bold Finance theme: color palette and reusable Sheets formatting requests.

All builder functions are pure: they take a sheetId + ranges and return
Sheets API request dicts, so they can be unit-tested without any network.
"""
from __future__ import annotations

from app.models import CATEGORIES
from app.sheets.client import grid_range

# --- Palette (hex) ---
COLORS = {
    "income": "#16a34a", "expense": "#dc2626", "net": "#2563eb",
    "running": "#4f46e5", "header": "#1e293b", "band": "#f1f5f9",
    "white": "#ffffff", "amber": "#f59e0b", "ink": "#0f172a",
    "card_income": "#16a34a", "card_expense": "#dc2626",
    "card_net": "#2563eb", "card_running": "#4f46e5",
}

# Per-category tag colors: (background, text)
CATEGORY_COLORS: dict[str, tuple[str, str]] = {
    "Food": ("#fee2e2", "#b91c1c"),
    "Transport": ("#fef9c3", "#a16207"),
    "Bills": ("#e0e7ff", "#4338ca"),
    "Salary": ("#dcfce7", "#15803d"),
    "Entertainment": ("#fce7f3", "#be185d"),
    "Shopping": ("#ffedd5", "#c2410c"),
    "Health": ("#d1fae5", "#047857"),
    "Utilities": ("#cffafe", "#0e7490"),
    "Rent": ("#ede9fe", "#6d28d9"),
    "Freelance": ("#dcfce7", "#065f46"),
    "Dating": ("#fce7f3", "#db2777"),
    "Other": ("#f1f5f9", "#475569"),
}


def rgb(hex_color: str) -> dict:
    """Convert '#rrggbb' to a Sheets API color dict of 0..1 floats."""
    h = hex_color.lstrip("#")
    return {
        "red": int(h[0:2], 16) / 255,
        "green": int(h[2:4], 16) / 255,
        "blue": int(h[4:6], 16) / 255,
    }


def solid_fill(sid, r0, r1, c0, c1, bg, *, text=None, bold=False) -> dict:
    """repeatCell request: background fill (+ optional text color/bold)."""
    cell_fmt: dict = {"backgroundColor": rgb(bg)}
    fields = "userEnteredFormat.backgroundColor"
    text_fmt: dict = {}
    if text:
        text_fmt["foregroundColor"] = rgb(text)
    if bold:
        text_fmt["bold"] = True
    if text_fmt:
        cell_fmt["textFormat"] = text_fmt
        fields += ",userEnteredFormat.textFormat"
    return {
        "repeatCell": {
            "range": grid_range(sid, r0, r1, c0, c1),
            "cell": {"userEnteredFormat": cell_fmt},
            "fields": fields,
        }
    }


def banding(sid, r0, r1, c0, c1, header_hex, band_hex) -> dict:
    """addBanding request producing white/`band_hex` alternating rows."""
    return {
        "addBanding": {
            "bandedRange": {
                "range": grid_range(sid, r0, r1, c0, c1),
                "rowProperties": {
                    "headerColor": rgb(header_hex),
                    "firstBandColor": rgb("#ffffff"),
                    "secondBandColor": rgb(band_hex),
                },
            }
        }
    }


def _col_letter(col0: int) -> str:
    """0-indexed column -> A1 letter (0->A)."""
    letters = ""
    n = col0 + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _cf_rule(sid, r0, r1, c0, c1, formula: str, *, text_hex=None, bg_hex=None) -> dict:
    fmt: dict = {}
    if text_hex:
        fmt["textFormat"] = {"foregroundColor": rgb(text_hex), "bold": True}
    if bg_hex:
        fmt["backgroundColor"] = rgb(bg_hex)
    return {
        "addConditionalFormatRule": {
            "index": 0,
            "rule": {
                "ranges": [grid_range(sid, r0, r1, c0, c1)],
                "booleanRule": {
                    "condition": {
                        "type": "CUSTOM_FORMULA",
                        "values": [{"userEnteredValue": formula}],
                    },
                    "format": fmt,
                },
            },
        }
    }


def sign_color_rules(sid, r0, r1, *, amount_col, type_col) -> list[dict]:
    """Two rules coloring the amount column: green when Type=Income, red when Expense."""
    type_letter = _col_letter(type_col)
    first_row = r0 + 1
    return [
        _cf_rule(sid, r0, r1, amount_col, amount_col + 1,
                 f'=${type_letter}{first_row}="Income"', text_hex=COLORS["income"]),
        _cf_rule(sid, r0, r1, amount_col, amount_col + 1,
                 f'=${type_letter}{first_row}="Expense"', text_hex=COLORS["expense"]),
    ]


def category_tag_rules(sid, r0, r1, *, category_col) -> list[dict]:
    """One conditional-format rule per category, coloring the category cell like a tag."""
    cat_letter = _col_letter(category_col)
    first_row = r0 + 1
    rules: list[dict] = []
    for cat in CATEGORIES:
        bg_hex, text_hex = CATEGORY_COLORS[cat]
        rules.append(
            _cf_rule(sid, r0, r1, category_col, category_col + 1,
                     f'=${cat_letter}{first_row}="{cat}"', text_hex=text_hex, bg_hex=bg_hex)
        )
    return rules


def monthly_theme_requests(sid: int, *, include_banding: bool = True) -> list[dict]:
    """All Bold Finance formatting requests for a monthly tab.

    Layout assumptions match transactions._setup_headers_and_formulas:
      data table A1:E (col 0..4), rows: header row 0, data rows 1..499.

    Set ``include_banding=False`` when re-theming an existing tab: re-adding a
    banded range that overlaps an existing one raises, so callers apply banding
    separately (best-effort).
    """
    reqs: list[dict] = [
        # Dark header on data table A1:E1 (white bold)
        solid_fill(sid, 0, 1, 0, 5, COLORS["header"], text=COLORS["white"], bold=True),
    ]
    if include_banding:
        # Banded data rows A2:E500
        reqs.append(banding(sid, 1, 500, 0, 5, COLORS["header"], COLORS["band"]))
    reqs += [
        # Summary value fills (keep positions; H2 income, H3 expense, H4 net, H7 running)
        solid_fill(sid, 1, 2, 7, 8, COLORS["card_income"], text=COLORS["white"], bold=True),
        solid_fill(sid, 2, 3, 7, 8, COLORS["card_expense"], text=COLORS["white"], bold=True),
        solid_fill(sid, 3, 4, 7, 8, COLORS["card_net"], text=COLORS["white"], bold=True),
        solid_fill(sid, 6, 7, 7, 8, COLORS["card_running"], text=COLORS["white"], bold=True),
    ]
    # Amount coloring by sign + category tags
    reqs += sign_color_rules(sid, 1, 500, amount_col=3, type_col=4)
    reqs += category_tag_rules(sid, 1, 500, category_col=2)
    return reqs
