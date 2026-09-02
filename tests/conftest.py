"""Shared pytest fixtures.

`db_session` gives each test an isolated in-memory SQLite database (fresh
schema via Base.metadata.create_all, torn down after the test) so
aggregation/CRUD logic can be tested against real queries without touching
the app's actual data/finance.db file. It also seeds the system tags
(ensure_system_tags) the same way real startup does — tests exercising
tag toggling, reimbursement, or anything that queries Tag need those
rows to exist, and this fixture is where every other test's DB already
gets set up.

`client` builds on that for router-level tests: a TestClient with the
app's get_db dependency overridden to use the isolated db_session, so
requests that write data (creating an account, categorizing a
transaction) never touch the real database file either.
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Account, Category, Transaction
from app.services.tags import ensure_system_tags


@pytest.fixture()
def db_session():
    # StaticPool forces every checkout to reuse the same underlying
    # connection. Without it, a `:memory:` SQLite database is scoped to a
    # single connection — Base.metadata.create_all() would run its DDL on
    # one pooled connection, and a later query (e.g. one made from the
    # thread FastAPI's TestClient runs sync handlers in) could get handed
    # a *different* connection, i.e. a brand new, table-less database.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    ensure_system_tags(session)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session):
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


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
