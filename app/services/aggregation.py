"""Period-based dashboard aggregation.

The dashboard shows one period at a time — today / this week / this month
/ this quarter / this year — navigable via `offset` (0 = current period,
1 = one period back, 2 = two back, ...), not a chart spanning all
history. This replaced an earlier "bucket every transaction ever, by
range_type granularity" design that showed one bar per day/week/month
across the account's entire lifetime — not what a budgeting dashboard
should default to.

Within the selected period, the chart breaks it into a finer sub-bucket
(a month into its days, a quarter into its months, ...) so there's still
something to look at besides three big totals. "daily" has no sub-bucket
— a single day can't be broken down further with only date-level
transaction data (no time-of-day on Transaction).

Bucketing happens in Python rather than SQL GROUP BY/strftime — this is a
local-first personal app (thousands of rows at most), and doing it in
Python keeps the date math (month/quarter/year boundaries, leap years)
in one place, ordinary and unit-testable, instead of split across
SQLite-specific strftime quirks.
"""
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Category, Transaction

# Ordered finest to coarsest — this is also the range switcher's display
# order (see routers/dashboard.py), so keep it a tuple, not a set.
RANGE_TYPES = ("daily", "weekly", "monthly", "quarterly", "yearly")

# Sub-bucket granularity used to break a period into chart bars. None for
# "daily", which has nothing smaller to show.
_SUB_BUCKET = {
    "daily": None,
    "weekly": "daily",
    "monthly": "daily",
    "quarterly": "monthly",
    "yearly": "monthly",
}


def get_period_dashboard(
    db: Session, range_type: str, offset: int = 0, today: date | None = None, account_id: int | None = None
) -> dict:
    """Aggregate transactions for one period of `range_type`, `offset`
    periods back from the current one (0 = current). `account_id` scopes
    everything (totals, buckets, by_category) to just that account —
    None (the default) means every account.

    Returns:
        {
          "range_type": str, "offset": int,
          "period_start": date, "period_end": date, "period_label": str,
          "can_go_forward": bool,  # False when already at the current period
          "progress": {"elapsed": int, "total": int} | None,  # only set
              # for the current period (offset 0) of a non-daily range —
              # how far into it "today" is.
          "totals": {"income": Decimal, "spending": Decimal, "net": Decimal},
          "buckets": [{"period": "2026-08-24", "label": "Mon 24", "income": Decimal, "spending": Decimal}, ...],
              # zero-filled for every sub-period in range, not just ones
              # with transactions — [] for "daily".
          "by_category": [{"category": str, "kind": "income"|"expense", "total": Decimal, "share": float}, ...],
        }

    Raises:
        ValueError: if range_type isn't one of RANGE_TYPES.
    """
    if range_type not in RANGE_TYPES:
        raise ValueError(f"unknown range_type '{range_type}'")
    if offset < 0:
        offset = 0

    today = today or date.today()
    start, end = period_bounds(range_type, offset, today)
    granularity = _SUB_BUCKET[range_type]

    buckets_by_key = {b["period"]: b for b in _build_period_buckets(start, end, granularity)}

    query = db.query(Transaction).filter(Transaction.date >= start, Transaction.date <= end)
    if account_id is not None:
        query = query.filter(Transaction.account_id == account_id)
    transactions = query.order_by(Transaction.date).all()

    category_totals: dict[int | None, Decimal] = {}
    total_income = Decimal("0")
    total_spending = Decimal("0")

    for txn in transactions:
        amount = Decimal(txn.amount)

        if granularity:
            bucket = buckets_by_key[_sub_bucket_key(txn.date, granularity)]
            if amount >= 0:
                bucket["income"] += amount
            else:
                bucket["spending"] += -amount

        if amount >= 0:
            total_income += amount
        else:
            total_spending += -amount

        category_totals[txn.category_id] = category_totals.get(txn.category_id, Decimal("0")) + amount

    by_category = _summarize_categories(db, category_totals, total_income, total_spending)

    return {
        "range_type": range_type,
        "offset": offset,
        "period_start": start,
        "period_end": end,
        "period_label": _period_label(range_type, start, end),
        "can_go_forward": offset > 0,
        "progress": _period_progress(range_type, start, end, today) if offset == 0 else None,
        "totals": {
            "income": total_income,
            "spending": total_spending,
            "net": total_income - total_spending,
        },
        "buckets": list(buckets_by_key.values()),
        "by_category": by_category,
    }


def period_bounds(range_type: str, offset: int, today: date) -> tuple[date, date]:
    """The (start, end) dates — both inclusive — of the period `offset`
    steps back from the one containing `today`.
    """
    if range_type == "daily":
        d = today - timedelta(days=offset)
        return d, d

    if range_type == "weekly":
        # Weeks start Monday. This is a fixed convention (not
        # locale-aware, same spirit as _parse_date's US-leaning date
        # format guesses) — simplest thing that works everywhere the app
        # runs today; revisit if that becomes a real complaint.
        ref = today - timedelta(weeks=offset)
        monday = ref - timedelta(days=ref.weekday())
        return monday, monday + timedelta(days=6)

    if range_type == "monthly":
        y, m = _shift_months(today.year, today.month, offset)
        start = date(y, m, 1)
        return start, date(y, m, monthrange(y, m)[1])

    if range_type == "quarterly":
        quarter_start_month = ((today.month - 1) // 3) * 3 + 1  # 1, 4, 7, or 10
        y, m = _shift_months(today.year, quarter_start_month, offset * 3)
        start = date(y, m, 1)
        end_y, end_m = _shift_months(y, m, -2)  # 2 months forward = quarter's last month
        return start, date(end_y, end_m, monthrange(end_y, end_m)[1])

    if range_type == "yearly":
        y = today.year - offset
        return date(y, 1, 1), date(y, 12, 31)

    raise ValueError(f"unknown range_type '{range_type}'")


def _shift_months(year: int, month: int, delta: int) -> tuple[int, int]:
    """(year, month) shifted `delta` months into the past (negative delta
    shifts into the future). 1-indexed month in, 1-indexed month out.
    """
    index = year * 12 + (month - 1) - delta
    return index // 12, index % 12 + 1


def _period_progress(range_type: str, start: date, end: date, today: date) -> dict | None:
    if range_type == "daily":
        return None
    return {"elapsed": (today - start).days + 1, "total": (end - start).days + 1}


def _period_label(range_type: str, start: date, end: date) -> str:
    if range_type == "daily":
        return f"{start.strftime('%A, %B')} {start.day}, {start.year}"
    if range_type == "weekly":
        if start.month == end.month:
            return f"{start.strftime('%b')} {start.day}–{end.day}, {end.year}"
        return f"{start.strftime('%b')} {start.day} – {end.strftime('%b')} {end.day}, {end.year}"
    if range_type == "monthly":
        return start.strftime("%B %Y")
    if range_type == "quarterly":
        quarter = (start.month - 1) // 3 + 1
        return f"Q{quarter} {start.year} ({start.strftime('%b')}–{end.strftime('%b')})"
    if range_type == "yearly":
        return str(start.year)
    raise ValueError(f"unknown range_type '{range_type}'")


def _build_period_buckets(start: date, end: date, granularity: str | None) -> list[dict]:
    if granularity is None:
        return []

    buckets = []
    if granularity == "daily":
        d = start
        while d <= end:
            buckets.append(
                {
                    "period": d.isoformat(),
                    "label": f"{d.strftime('%a')} {d.day}",
                    "income": Decimal("0"),
                    "spending": Decimal("0"),
                }
            )
            d += timedelta(days=1)
    elif granularity == "monthly":
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            buckets.append(
                {
                    "period": f"{y:04d}-{m:02d}",
                    "label": date(y, m, 1).strftime("%b"),
                    "income": Decimal("0"),
                    "spending": Decimal("0"),
                }
            )
            y, m = _shift_months(y, m, -1)
    else:
        raise ValueError(granularity)
    return buckets


def _sub_bucket_key(d: date, granularity: str) -> str:
    if granularity == "daily":
        return d.isoformat()
    if granularity == "monthly":
        return f"{d.year:04d}-{d.month:02d}"
    raise ValueError(granularity)


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
