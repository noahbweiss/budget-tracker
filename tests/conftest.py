"""Shared pytest fixtures.

`db_session` gives each test an isolated in-memory SQLite database (fresh
schema via Base.metadata.create_all, torn down after the test) so
aggregation/CRUD logic can be tested against real queries without touching
the app's actual data/finance.db file.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Account, Category, Transaction


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def seeded_session(db_session):
    """A db_session pre-populated with one account, two categories, and a
    handful of transactions spanning two months — enough to exercise
    bucketing, category totals, and sign handling.
    """
    account = Account(name="Checking", account_type="checking")
    salary = Category(name="Salary", kind="income")
    groceries = Category(name="Groceries", kind="expense")
    db_session.add_all([account, salary, groceries])
    db_session.flush()

    db_session.add_all(
        [
            Transaction(
                account_id=account.id,
                category_id=salary.id,
                date=date(2026, 6, 1),
                amount=2000,
                description="Paycheck",
            ),
            Transaction(
                account_id=account.id,
                category_id=groceries.id,
                date=date(2026, 6, 5),
                amount=-50,
                description="Grocery run",
            ),
            Transaction(
                account_id=account.id,
                category_id=groceries.id,
                date=date(2026, 6, 20),
                amount=-30,
                description="More groceries",
            ),
            Transaction(
                account_id=account.id,
                category_id=None,
                date=date(2026, 7, 3),
                amount=-15,
                description="Uncategorized expense",
            ),
            Transaction(
                account_id=account.id,
                category_id=salary.id,
                date=date(2026, 7, 1),
                amount=2100,
                description="Paycheck",
            ),
        ]
    )
    db_session.commit()
    return db_session
