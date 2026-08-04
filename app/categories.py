"""The category taxonomy: what each category means, and which words pin one down.

This is the only place the twelve categories are described. The prompt, the
sheet's dropdown and the type alias all read from here.
"""
from __future__ import annotations

import re

CATEGORY_GUIDE: dict[str, str] = {
    "Food": "meals, groceries, coffee, restaurants, food delivery, snacks",
    "Transport": (
        "fare, jeep, bus, taxi, Grab, gas, fuel, parking, toll, carwash, "
        "car maintenance, LTO registration"
    ),
    "Bills": "phone load, internet, mobile plan, cable, streaming subscriptions",
    "Salary": "salary or payroll received from an employer",
    "Entertainment": "movies, games, concerts, bars, hobbies",
    "Shopping": "clothes, gadgets, Shopee or Lazada orders, household goods",
    "Health": "medicine, pharmacy, doctor, dentist, gym, haircut, salon, personal care",
    "Utilities": "electricity (Meralco), water (Maynilad), LPG and gas utility bills",
    "Rent": "rent, dorm, condo association dues",
    "Freelance": "income from clients or side projects",
    "Dating": "dates, gifts for a partner",
    "Other": "transfers, cash in or out, anything with no clear home",
}

CATEGORIES: list[str] = list(CATEGORY_GUIDE)

# Terms that settle a category on their own. Income categories are deliberately
# absent: the fast path always writes an Expense, so letting "salary" match here
# would book earnings as spending.
LEXICON: dict[str, str] = {
    # Transport
    "carwash": "Transport", "car wash": "Transport", "grab": "Transport",
    "angkas": "Transport", "jeep": "Transport", "jeepney": "Transport",
    "tricycle": "Transport", "toll": "Transport", "parking": "Transport",
    "gas": "Transport", "gasoline": "Transport", "fuel": "Transport",
    "shell": "Transport", "petron": "Transport", "caltex": "Transport",
    "lto": "Transport", "mrt": "Transport", "lrt": "Transport", "fare": "Transport",
    # Food
    "jollibee": "Food", "mcdo": "Food", "mcdonalds": "Food", "kfc": "Food",
    "chowking": "Food", "mang inasal": "Food", "starbucks": "Food",
    "grocery": "Food", "groceries": "Food", "puregold": "Food",
    "lunch": "Food", "dinner": "Food", "breakfast": "Food", "merienda": "Food",
    # Bills
    "load": "Bills", "globe": "Bills", "smart": "Bills", "converge": "Bills",
    "pldt": "Bills", "netflix": "Bills", "spotify": "Bills",
    # Utilities
    "meralco": "Utilities", "maynilad": "Utilities", "manila water": "Utilities",
    "lpg": "Utilities",
    # Health
    "haircut": "Health", "salon": "Health", "barber": "Health",
    "mercury drug": "Health", "watsons": "Health", "dentist": "Health",
    "gym": "Health", "medicine": "Health",
    # Shopping
    "shopee": "Shopping", "lazada": "Shopping", "uniqlo": "Shopping",
    # Rent
    "rent": "Rent",
}


def render_category_guide() -> str:
    """The category block that goes into the router prompt."""
    return "\n".join(f"{name} - {meaning}" for name, meaning in CATEGORY_GUIDE.items())


def classify_by_lexicon(text: str) -> str | None:
    """The category a message clearly belongs to, or None when it is not clear.

    Returns None when nothing matches, and also when terms from two different
    categories both appear - a mixed message is Tier 1's job, not ours.
    """
    if not text or not text.strip():
        return None
    low = text.lower()
    matched = {
        category
        for term, category in LEXICON.items()
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", low)
    }
    if len(matched) == 1:
        return matched.pop()
    return None
