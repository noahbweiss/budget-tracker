"""Tests for app.services.aggregation.bucket_transactions."""
from decimal import Decimal

import pytest

from app.services import aggregation


def test_empty_range_returns_zeroed_totals(db_session):
    result = aggregation.bucket_transactions(db_session, "monthly")

    assert result["totals"] == {
        "income": Decimal("0"),
        "spending": Decimal("0"),
        "net": Decimal("0"),
    }
    assert result["buckets"] == []
    assert result["by_category"] == []


def test_monthly_buckets_group_by_year_month(seeded_session):
    result = aggregation.bucket_transactions(seeded_session, "monthly")

    periods = [b["period"] for b in result["buckets"]]
    assert periods == ["2026-06", "2026-07"]

    june = result["buckets"][0]
    assert june["income"] == Decimal("2000")
    assert june["spending"] == Decimal("80")

    july = result["buckets"][1]
    assert july["income"] == Decimal("2100")
    assert july["spending"] == Decimal("15")


def test_totals_sum_across_the_whole_range(seeded_session):
    result = aggregation.bucket_transactions(seeded_session, "monthly")

    assert result["totals"]["income"] == Decimal("4100")
    assert result["totals"]["spending"] == Decimal("95")
    assert result["totals"]["net"] == Decimal("4005")


def test_by_category_sums_and_labels_uncategorized(seeded_session):
    result = aggregation.bucket_transactions(seeded_session, "monthly")
    by_name = {c["category"]: c for c in result["by_category"]}

    assert by_name["Salary"]["kind"] == "income"
    assert by_name["Salary"]["total"] == Decimal("4100")

    assert by_name["Groceries"]["kind"] == "expense"
    assert by_name["Groceries"]["total"] == Decimal("80")

    assert by_name["Uncategorized"]["total"] == Decimal("15")


def test_by_category_sorted_descending_by_total(seeded_session):
    result = aggregation.bucket_transactions(seeded_session, "monthly")
    totals = [c["total"] for c in result["by_category"]]
    assert totals == sorted(totals, reverse=True)


def test_quarterly_bucket_derived_from_month(seeded_session):
    result = aggregation.bucket_transactions(seeded_session, "quarterly")
    periods = [b["period"] for b in result["buckets"]]
    # June is Q2, July is Q3 (Q1=Jan-Mar, Q2=Apr-Jun, Q3=Jul-Sep, Q4=Oct-Dec).
    assert periods == ["2026-Q2", "2026-Q3"]
    assert result["buckets"][0]["income"] == Decimal("2000")
    assert result["buckets"][1]["income"] == Decimal("2100")


def test_yearly_bucket(seeded_session):
    result = aggregation.bucket_transactions(seeded_session, "yearly")
    assert [b["period"] for b in result["buckets"]] == ["2026"]


def test_start_and_end_filter_the_range(seeded_session):
    from datetime import date

    result = aggregation.bucket_transactions(
        seeded_session, "monthly", start=date(2026, 7, 1), end=date(2026, 7, 31)
    )
    assert [b["period"] for b in result["buckets"]] == ["2026-07"]
    assert result["totals"]["income"] == Decimal("2100")


def test_unknown_range_type_raises_value_error(db_session):
    with pytest.raises(ValueError):
        aggregation.bucket_transactions(db_session, "decade")
