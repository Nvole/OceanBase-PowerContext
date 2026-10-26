"""Behavior tests for task invoice-date-range."""

import json
import sys
import unittest
from datetime import date
from pathlib import Path

TRACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRACK / "src"))

from lab.invoice_filter import filter_invoices


def load():
    return json.loads((TRACK / "data" / "invoices.json").read_text(encoding="utf-8"))


def ids(rows):
    return [row["id"] for row in rows]


class InvoiceFilterTests(unittest.TestCase):
    def test_filter_by_min_amount(self):
        self.assertEqual(ids(filter_invoices(load(), min_amount=50)), ["B", "C", "D", "E"])

    def test_filter_by_max_amount(self):
        self.assertEqual(ids(filter_invoices(load(), max_amount=50)), ["A", "B", "D", "E"])

    def test_filter_min_amount_is_inclusive(self):
        self.assertEqual(ids(filter_invoices(load(), min_amount=80)), ["C"])

    def test_filter_by_status(self):
        self.assertEqual(ids(filter_invoices(load(), status="open")), ["A", "C"])

    def test_filter_status_is_case_sensitive(self):
        self.assertEqual(filter_invoices(load(), status="Paid"), [])

    def test_filter_amount_and_status(self):
        self.assertEqual(ids(filter_invoices(load(), min_amount=50, status="paid")), ["B", "E"])

    def test_filter_without_constraints_preserves_order(self):
        self.assertEqual(ids(filter_invoices(load())), ["A", "B", "C", "D", "E"])

    def test_filter_does_not_mutate_input(self):
        rows = load()
        snapshot = json.dumps(rows)
        filter_invoices(rows, min_amount=50, start_date="2024-02-01", end_date="2024-02-28")
        self.assertEqual(json.dumps(rows), snapshot)

    def test_omitted_dates_do_not_filter(self):
        self.assertEqual(ids(filter_invoices(load(), min_amount=10, max_amount=80)), ["A", "B", "C", "D", "E"])

    def test_filter_by_date_range(self):
        selected = filter_invoices(load(), start_date="2024-02-01", end_date="2024-02-28")
        self.assertEqual(ids(selected), ["B", "D"])

    def test_filter_date_start_only(self):
        self.assertEqual(ids(filter_invoices(load(), start_date="2024-03-01")), ["C", "E"])

    def test_filter_date_end_only(self):
        self.assertEqual(ids(filter_invoices(load(), end_date="2024-01-31")), ["A"])

    def test_filter_date_single_day_inclusive(self):
        selected = filter_invoices(load(), start_date="2024-02-15", end_date="2024-02-15")
        self.assertEqual(ids(selected), ["B", "D"])

    def test_filter_date_accepts_date_objects(self):
        selected = filter_invoices(load(), start_date=date(2024, 2, 1), end_date=date(2024, 2, 28))
        self.assertEqual(ids(selected), ["B", "D"])

    def test_filter_date_inverted_range_is_empty(self):
        selected = filter_invoices(load(), start_date="2024-03-02", end_date="2024-03-01")
        self.assertEqual(selected, [])

    def test_filter_date_uses_calendar_day(self):
        rows = load()
        rows.append({"id": "T", "amount": 1, "status": "open", "invoice_date": "2024-02-15T08:30:00"})
        rows.append({"id": "N", "amount": 1, "status": "open", "invoice_date": "2024-02-16T00:01:00"})
        selected = filter_invoices(rows, start_date="2024-02-15", end_date="2024-02-15")
        self.assertEqual(ids(selected), ["B", "D", "T"])

    def test_filter_date_with_amount_and_status(self):
        selected = filter_invoices(
            load(), min_amount=50, status="paid", start_date="2024-02-01", end_date="2024-02-28")
        self.assertEqual(ids(selected), ["B"])


if __name__ == "__main__":
    unittest.main()
