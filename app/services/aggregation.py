"""Time-bucketed aggregation logic for the dashboard views.

Design note: daily/weekly/monthly/quarterly/yearly are all the same
underlying query — sum transactions grouped by a date bucket — just with
a different bucket size. TODO: implement bucket_transactions() once
models are populated with real data, likely using SQLAlchemy's
func.strftime (SQLite) to bucket by day/week/month/quarter/year.
"""
from datetime import date
from sqlalchemy.orm import Session

RANGE_TO_BUCKET = {
    "daily": "%Y-%m-%d",
    "weekly": "%Y-%W",
    "monthly": "%Y-%m",
    "quarterly": None,  # SQLite has no native quarter format — TODO: derive from month
    "yearly": "%Y",
}


def bucket_transactions(db: Session, range_type: str, start: date | None = None, end: date | None = None):
    """TODO: query transactions, group by the bucket for range_type, and
    return [{bucket, income, spending, by_category}, ...].
    """
    raise NotImplementedError("aggregation not yet implemented")
