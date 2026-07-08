from app.sheets.dashboard import compute_index_rows, ytd_totals, top_categories


def test_compute_index_rows_sorts_and_accumulates_running():
    rows = compute_index_rows([
        ("2026-02", 50000, 20000),
        ("2026-01", 48000, 12000),
        ("2026-03", 48000, 15000),
    ])
    assert [r[0] for r in rows] == ["2026-01", "2026-02", "2026-03"]
    # net = income - expense; running is cumulative net
    assert rows[0] == ("2026-01", 48000, 12000, 36000, 36000)
    assert rows[1][3] == 30000 and rows[1][4] == 66000
    assert rows[2][4] == 99000


def test_ytd_totals_filters_by_year_and_takes_last_running():
    rows = compute_index_rows([
        ("2025-12", 40000, 10000),
        ("2026-01", 48000, 12000),
        ("2026-02", 50000, 20000),
    ])
    ytd = ytd_totals(rows, 2026)
    assert ytd["income"] == 98000
    assert ytd["expense"] == 32000
    assert ytd["net"] == 66000
    assert ytd["running"] == rows[-1][4]  # cumulative across all time


def test_ytd_totals_empty():
    assert ytd_totals([], 2026) == {"income": 0.0, "expense": 0.0, "net": 0.0, "running": 0.0}


def test_top_categories_sorts_desc_and_limits():
    totals = {"Food": 12400, "Rent": 10000, "Transport": 6200, "Health": 100}
    top = top_categories(totals, limit=3)
    assert top == [("Food", 12400), ("Rent", 10000), ("Transport", 6200)]
