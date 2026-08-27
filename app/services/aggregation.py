"""Time-bucketed aggregation logic for the dashboard views.

Design note: daily/weekly/monthly/quarterly/yearly are all the same
underlying operation — sum transactions grouped by a date bucket — just
with a different bucket size. Bucketing happens in Python rather than via
SQL GROUP BY/strftime: this is a local-first personal app (thousands of
rows at most, not a data-warehouse workload), and doing it in Python
sidesteps SQLite's lack of a native quarter format (derived directly from
the month, see `_bucket_key`) and keeps the logic trivially unit-testable
without depending on SQLite-specific strftime quirks.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Category, Transaction

# Python's date.strftime format for each bucket granularity. "quarterly"
# has no direct strftime equivalent — handled specially in _bucket_key.
RANGE_TO_BUCKET = {
    "daily": "%Y-%m-%d",
    "weekly": "%Y-%W",
    "monthly": "%Y-%m",
    "quarterly": None,
    "yearly": "%Y",
}


def bucket_transactions(db: Session, range_type: str, start: date | None = None, end: date | None = None) -> dict:
    """Aggregate transactions into time buckets and category totals.

    Returns:
        {
          "totals": {"income": Decimal, "spending": Decimal, "net": Decimal},
          "buckets": [{"period": "2026-06", "income": Decimal, "spending": Decimal}, ...],
          "by_category": [{"category": str, "kind": "income"|"expense", "total": Decimal, "share": float}, ...],
        }
        `buckets` is chronological. `by_category` is sorted by `total`
        descending. `spending`/`total` values are non-negative magnitudes
        (the model's signed-amount convention is resolved here so
        templates never have to think about sign).

    Raises:
        ValueError: if range_type isn't one of RANGE_TO_BUCKET's keys.
    """
    if range_type not in RANGE_TO_BUCKET:
        raise ValueError(f"unknown range_type '{range_type}'")

    query = db.query(Transaction)
    if start is not None:
        query = query.filter(Transaction.date >= start)
    if end is not None:
        query = query.filter(Transaction.date <= end)
    transactions = query.order_by(Transaction.date).all()

    buckets: dict[str, dict] = {}
    category_totals: dict[int | None, Decimal] = {}
    total_income = Decimal("0")
    total_spending = Decimal("0")

    for txn in transactions:
        amount = Decimal(txn.amount)

        key = _bucket_key(txn.date, range_type)
        bucket = buckets.setdefault(key, {"period": key, "income": Decimal("0"), "spending": Decimal("0")})

        if amount >= 0:
            bucket["income"] += amount
            total_income += amount
        else:
            bucket["spending"] += -amount
            total_spending += -amount

        category_totals[txn.category_id] = category_totals.get(txn.category_id, Decimal("0")) + amount

    by_category = _summarize_categories(db, category_totals, total_income, total_spending)

    return {
        "totals": {
            "income": total_income,
            "spending": total_spending,
            "net": total_income - total_spending,
        },
        "buckets": list(buckets.values()),
        "by_category": by_category,
    }


def _bucket_key(d: date, range_type: str) -> str:
    if range_type == "quarterly":
        quarter = (d.month - 1) // 3 + 1
        return f"{d.year}-Q{quarter}"
    return d.strftime(RANGE_TO_BUCKET[range_type])


def _summarize_categories(
    db: Session,
    category_totals: dict[int | None, Decimal],
    total_income: Decimal,
    total_spending: Decimal,
) -> list[dict]:
    if not category_totals:
        return []

    category_ids = [cid for cid in category_totals if cid is not None]
    categories = {c.id: c for c in db.query(Category).filter(Category.id.in_(category_ids)).all()}

    rows = []
    for category_id, signed_total in category_totals.items():
        category = categories.get(category_id)
        magnitude = abs(signed_total)

        if category is not None:
            name = category.name
            kind = category.kind
        else:
            name = "Uncategorized"
            # No category to say what kind this is — infer from the sign
            # of its net total (mixed-sign "Uncategorized" activity is an
            # edge case; net sign is a reasonable best guess).
            kind = "income" if signed_total >= 0 else "expense"

        denominator = total_income if kind == "income" else total_spending
        share = float(magnitude / denominator) if denominator else 0.0

        rows.append({"category": name, "kind": kind, "total": magnitude, "share": share})

    rows.sort(key=lambda r: r["total"], reverse=True)
    return rows
