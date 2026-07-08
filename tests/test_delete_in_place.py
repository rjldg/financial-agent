"""Regression test: deleting a transaction must clear A:E in place, never delete
the whole grid row (which would corrupt the G:H summary block and shift rows out
from under already-issued inline quick-fix keyboards)."""
from unittest.mock import MagicMock, patch

from app.sheets import transactions as tx


def test_delete_clears_ae_in_place_not_whole_row():
    ws = MagicMock()
    ss = MagicMock()
    ss.worksheet.return_value = ws
    with patch.object(tx, "get_spreadsheet", return_value=ss), \
         patch.object(tx, "_reindex") as reindex:
        tx.delete_transaction_row("2026-03", 5)
    ws.batch_clear.assert_called_once_with(["A5:E5"])
    ws.delete_rows.assert_not_called()
    reindex.assert_called_once_with("2026-03")
