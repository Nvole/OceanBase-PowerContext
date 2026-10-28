"""Invoice filters for task invoice-date-range.

Amount and status filters stay in place. Date bounds are an inclusive calendar-day
range on invoice_date.
"""

from datetime import date, datetime

REVISION = "date-range-applied"


def _as_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip()[:10])


def filter_invoices(
    invoices,
    *,
    min_amount=None,
    max_amount=None,
    status=None,
    start_date=None,
    end_date=None,
):
    """Return invoices matching every constraint that was provided.

    Comparisons are inclusive. status is case-sensitive. A reversed date range
    matches nothing. Omitted constraints are not applied. The input list is not
    modified.
    """
    start = _as_date(start_date)
    end = _as_date(end_date)

    if start is not None and end is not None and start > end:
        return []

    has_date_filter = start is not None or end is not None
    selected = []

    for invoice in invoices:
        amount = invoice["amount"]
        if min_amount is not None and amount < min_amount:
            continue
        if max_amount is not None and amount > max_amount:
            continue
        if status is not None and invoice["status"] != status:
            continue

        if has_date_filter:
            day = _as_date(invoice.get("invoice_date"))
            if start is not None and (day is None or day < start):
                continue
            if end is not None and (day is None or day > end):
                continue

        selected.append(invoice)

    return selected
