"""Pre-change snapshot of src/lab/invoice_filter.py. Not the live module.

Task invoice-date-range. Amount and status filters are applied. Date bounds are
accepted and ignored, so date-range tests fail while amount and status tests pass.
"""

REVISION = "amount-status-only"


def filter_invoices(invoices, *, min_amount=None, max_amount=None, status=None,
                    start_date=None, end_date=None):
    """Return invoices matching amount and status. Date bounds are ignored."""
    del start_date, end_date
    selected = []
    for invoice in invoices:
        amount = invoice["amount"]
        if min_amount is not None and amount < min_amount:
            continue
        if max_amount is not None and amount > max_amount:
            continue
        if status is not None and invoice["status"] != status:
            continue
        selected.append(invoice)
    return selected
