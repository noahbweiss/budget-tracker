"""Tests for app.services.aggregation.

The dashboard shows one period at a time (today / this week / this month /
this quarter / this year), navigable via `offset` (0 = current, 1 = one
period back, etc.) — not an all-history chart. Most of the real risk here
is date math: period boundaries across month/quarter/year edges, and
zero-filling every sub-bucket in a period (not just the ones with data).
"""
from datetime import date
from decimal import Decimal

import pytest

from app.services import aggregation


# ---- period_bounds ----


@pytest.mark.parametrize(
    "today,offset,expected_start,expected_end",
    [
        (date(2026, 8, 28), 0, date(2026, 8, 28), date(2026, 8, 28)),
        (date(2026, 8, 28), 1, date(2026, 8, 27), date(2026, 8, 27)),
        (date(2026, 1, 1), 1, date(2025, 12, 31), date(2025, 12, 31)),
    ],
)
def test_daily_bounds(today, offset, expected_start, expected_end):
    assert aggregation.period_bounds("daily", offset, today) == (expected_start, expected_end)


def test_weekly_bounds_current_week_starts_monday():
    # 2026-08-28 is a Friday.
    start, end = aggregation.period_bounds("weekly", 0, date(2026, 8, 28))
    assert start == date(2026, 8, 24)  # Monday
    assert end == date(2026, 8, 30)  # Sunday


def test_weekly_bounds_previous_week():
    start, end = aggregation.period_bounds("weekly", 1, date(2026, 8, 28))
    assert start == date(2026, 8, 17)
    assert end == date(2026, 8, 23)


def test_weekly_bounds_crosses_year_boundary():
    # 2026-01-01 is a Thursday, in the week of Dec 29, 2025 - Jan 4, 2026.
    start, end = aggregation.period_bounds("weekly", 0, date(2026, 1, 1))
    assert start == date(2025, 12, 29)
    assert end == date(2026, 1, 4)


def test_monthly_bounds_current_month():
    start, end = aggregation.period_bounds("monthly", 0, date(2026, 7, 15))
    assert start == date(2026, 7, 1)
    assert end == date(2026, 7, 31)


def test_monthly_bounds_crosses_year_boundary():
    start, end = aggregation.period_bounds("monthly", 1, date(2026, 1, 15))
    assert start == date(2025, 12, 1)
    assert end == date(2025, 12, 31)


def test_monthly_bounds_leap_year_february():
    start, end = aggregation.period_bounds("monthly", 0, date(2028, 2, 10))
    assert start == date(2028, 2, 1)
    assert end == date(2028, 2, 29)


def test_quarterly_bounds_current_quarter():
    # August is in Q3 (Jul-Sep).
    start, end = aggregation.period_bounds("quarterly", 0, date(2026, 8, 28))
    assert start == date(2026, 7, 1)
    assert end == date(2026, 9, 30)


def test_quarterly_bounds_previous_quarter():
    start, end = aggregation.period_bounds("quarterly", 1, date(2026, 8, 28))
    assert start == date(2026, 4, 1)
    assert end == date(2026, 6, 30)


def test_quarterly_bounds_crosses_year_boundary():
    # January is in Q1; one quarter back is Q4 of the previous year.
    start, end = aggregation.period_bounds("quarterly", 1, date(2026, 1, 15))
    assert start == date(2025, 10, 1)
    assert end == date(2025, 12, 31)


def test_yearly_bounds():
    start, end = aggregation.period_bounds("yearly", 0, date(2026, 8, 28))
    assert start == date(2026, 1, 1)
    assert end == date(2026, 12, 31)
    start, end = aggregation.period_bounds("yearly", 2, date(2026, 8, 28))
    assert start == date(2024, 1, 1)
    assert end == date(2024, 12, 31)


def test_unknown_range_type_raises():
    with pytest.raises(ValueError):
        aggregation.period_bounds("decade", 0, date(2026, 1, 1))


# ---- get_period_dashboard ----


def _txn(session, account_id, d, amount, description="x", category_id=None):
    from app.models import Transaction

    t = Transaction(account_id=account_id, category_id=category_id, date=d, amount=amount, description=description)
    session.add(t)
    return t


def test_daily_period_has_no_chart_buckets(db_session):
    from app.models import Account

    account = Account(name="Checking", account_type="checking")
    db_session.add(account)
    db_session.flush()
    _txn(db_session, account.id, date(2026, 8, 28), 100)
    _txn(db_session, account.id, date(2026, 8, 27), 999)  # yesterday — excluded
    db_session.commit()

    result = aggregation.get_period_dashboard(db_session, "daily", offset=0, today=date(2026, 8, 28))
    assert result["buckets"] == []
    assert result["totals"]["income"] == Decimal("100")


def test_weekly_period_zero_fills_every_day(db_session):
    from app.models import Account

    account = Account(name="Checking", account_type="checking")
    db_session.add(account)
    db_session.flush()
    _txn(db_session, account.id, date(2026, 8, 24), -20)  # Monday
    _txn(db_session, account.id, date(2026, 8, 26), -5)  # Wednesday
    db_session.commit()

    result = aggregation.get_period_dashboard(db_session, "weekly", offset=0, today=date(2026, 8, 28))
    assert len(result["buckets"]) == 7
    assert result["buckets"][0]["period"] == "2026-08-24"
    assert result["buckets"][0]["spending"] == Decimal("20")
    assert result["buckets"][1]["spending"] == Decimal("0")  # Tuesday, no data
    assert result["buckets"][2]["spending"] == Decimal("5")  # Wednesday
    assert result["buckets"][-1]["period"] == "2026-08-30"


def test_monthly_period_zero_fills_every_day_of_month(db_session):
    from app.models import Account

    account = Account(name="Checking", account_type="checking")
    db_session.add(account)
    db_session.flush()
    _txn(db_session, account.id, date(2026, 7, 15), -10)
    db_session.commit()

    result = aggregation.get_period_dashboard(db_session, "monthly", offset=0, today=date(2026, 7, 20))
    assert len(result["buckets"]) == 31  # July has 31 days
    assert result["buckets"][14]["period"] == "2026-07-15"
    assert result["buckets"][14]["spending"] == Decimal("10")


def test_quarterly_period_zero_fills_every_month(db_session):
    from app.models import Account

    account = Account(name="Checking", account_type="checking")
    db_session.add(account)
    db_session.flush()
    _txn(db_session, account.id, date(2026, 7, 5), 1000)
    _txn(db_session, account.id, date(2026, 9, 5), -50)
    db_session.commit()

    result = aggregation.get_period_dashboard(db_session, "quarterly", offset=0, today=date(2026, 8, 28))
    assert [b["period"] for b in result["buckets"]] == ["2026-07", "2026-08", "2026-09"]
    assert result["buckets"][0]["income"] == Decimal("1000")
    assert result["buckets"][1]["income"] == Decimal("0")
    assert result["buckets"][1]["spending"] == Decimal("0")
    assert result["buckets"][2]["spending"] == Decimal("50")


def test_yearly_period_zero_fills_every_month(db_session):
    from app.models import Account

    account = Account(name="Checking", account_type="checking")
    db_session.add(account)
    db_session.flush()
    _txn(db_session, account.id, date(2026, 3, 1), 500)
    db_session.commit()

    result = aggregation.get_period_dashboard(db_session, "yearly", offset=0, today=date(2026, 8, 28))
    assert len(result["buckets"]) == 12
    assert result["buckets"][2]["period"] == "2026-03"
    assert result["buckets"][2]["income"] == Decimal("500")


def test_offset_navigates_to_a_different_period(db_session):
    from app.models import Account

    account = Account(name="Checking", account_type="checking")
    db_session.add(account)
    db_session.flush()
    _txn(db_session, account.id, date(2026, 8, 20), -30)  # last week
    _txn(db_session, account.id, date(2026, 8, 27), -40)  # this week
    db_session.commit()

    this_week = aggregation.get_period_dashboard(db_session, "weekly", offset=0, today=date(2026, 8, 28))
    last_week = aggregation.get_period_dashboard(db_session, "weekly", offset=1, today=date(2026, 8, 28))

    assert this_week["totals"]["spending"] == Decimal("40")
    assert last_week["totals"]["spending"] == Decimal("30")


def test_can_go_forward_reflects_offset(db_session):
    result = aggregation.get_period_dashboard(db_session, "monthly", offset=0, today=date(2026, 8, 28))
    assert result["can_go_forward"] is False
    result = aggregation.get_period_dashboard(db_session, "monthly", offset=1, today=date(2026, 8, 28))
    assert result["can_go_forward"] is True


def test_negative_offset_clamps_to_current_period(db_session):
    result = aggregation.get_period_dashboard(db_session, "monthly", offset=-5, today=date(2026, 8, 28))
    assert result["offset"] == 0
    assert result["period_start"] == date(2026, 8, 1)


def test_progress_only_present_for_current_offset_and_not_daily(db_session):
    current = aggregation.get_period_dashboard(db_session, "monthly", offset=0, today=date(2026, 8, 10))
    assert current["progress"] == {"elapsed": 10, "total": 31}

    past = aggregation.get_period_dashboard(db_session, "monthly", offset=1, today=date(2026, 8, 10))
    assert past["progress"] is None

    daily = aggregation.get_period_dashboard(db_session, "daily", offset=0, today=date(2026, 8, 10))
    assert daily["progress"] is None


def test_period_label_examples(db_session):
    monthly = aggregation.get_period_dashboard(db_session, "monthly", offset=0, today=date(2026, 8, 10))
    assert monthly["period_label"] == "August 2026"

    quarterly = aggregation.get_period_dashboard(db_session, "quarterly", offset=0, today=date(2026, 8, 10))
    assert quarterly["period_label"] == "Q3 2026 (Jul–Sep)"

    yearly = aggregation.get_period_dashboard(db_session, "yearly", offset=0, today=date(2026, 8, 10))
    assert yearly["period_label"] == "2026"


def test_by_category_still_works_within_a_period(db_session):
    from app.models import Account, Category

    account = Account(name="Checking", account_type="checking")
    groceries = Category(name="Groceries", kind="expense")
    db_session.add_all([account, groceries])
    db_session.flush()
    _txn(db_session, account.id, date(2026, 8, 5), -40, category_id=groceries.id)
    db_session.commit()

    result = aggregation.get_period_dashboard(db_session, "monthly", offset=0, today=date(2026, 8, 28))
    assert result["by_category"] == [{"category": "Groceries", "kind": "expense", "total": Decimal("40"), "share": 1.0}]


def test_get_period_dashboard_unknown_range_type_raises(db_session):
    with pytest.raises(ValueError):
        aggregation.get_period_dashboard(db_session, "decade", offset=0, today=date(2026, 1, 1))


# ---- account_id filter ----


def test_account_id_filters_to_just_that_account(db_session):
    from app.models import Account

    checking = Account(name="Checking", account_type="checking")
    savings = Account(name="Savings", account_type="savings")
    db_session.add_all([checking, savings])
    db_session.flush()
    _txn(db_session, checking.id, date(2026, 8, 5), -40)
    _txn(db_session, savings.id, date(2026, 8, 6), 500)
    db_session.commit()

    result = aggregation.get_period_dashboard(db_session, "monthly", offset=0, today=date(2026, 8, 28), account_id=checking.id)

    assert result["totals"]["spending"] == Decimal("40")
    assert result["totals"]["income"] == Decimal("0")


def test_account_id_none_includes_all_accounts(db_session):
    from app.models import Account

    checking = Account(name="Checking", account_type="checking")
    savings = Account(name="Savings", account_type="savings")
    db_session.add_all([checking, savings])
    db_session.flush()
    _txn(db_session, checking.id, date(2026, 8, 5), -40)
    _txn(db_session, savings.id, date(2026, 8, 6), 500)
    db_session.commit()

    result = aggregation.get_period_dashboard(db_session, "monthly", offset=0, today=date(2026, 8, 28), account_id=None)

    assert result["totals"]["spending"] == Decimal("40")
    assert result["totals"]["income"] == Decimal("500")


def test_account_id_scopes_category_breakdown_too(db_session):
    from app.models import Account, Category

    checking = Account(name="Checking", account_type="checking")
    savings = Account(name="Savings", account_type="savings")
    groceries = Category(name="Groceries", kind="expense")
    db_session.add_all([checking, savings, groceries])
    db_session.flush()
    _txn(db_session, checking.id, date(2026, 8, 5), -40, category_id=groceries.id)
    _txn(db_session, savings.id, date(2026, 8, 6), -15, category_id=groceries.id)
    db_session.commit()

    result = aggregation.get_period_dashboard(db_session, "monthly", offset=0, today=date(2026, 8, 28), account_id=checking.id)

    assert result["by_category"] == [{"category": "Groceries", "kind": "expense", "total": Decimal("40"), "share": 1.0}]
