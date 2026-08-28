"""Default category seeding.

There's no category-management UI yet (not in Phase 3's scope — see
PLAN.md), so without this, the transaction categorization UI would have
nothing to assign transactions to on a fresh install. `ensure_default_categories`
is idempotent — it only inserts if the table is empty — so it's safe to
call unconditionally on every app startup.

TODO: once category management (create/rename/delete) exists, this can
shrink to just a "suggested starting set" a user can accept or skip,
rather than always auto-inserting.
"""
from sqlalchemy.orm import Session

from app.models import Category

DEFAULT_CATEGORIES: list[tuple[str, str]] = [
    ("Salary", "income"),
    ("Other Income", "income"),
    ("Groceries", "expense"),
    ("Dining Out", "expense"),
    ("Rent/Mortgage", "expense"),
    ("Utilities", "expense"),
    ("Transportation", "expense"),
    ("Shopping", "expense"),
    ("Entertainment", "expense"),
    ("Health", "expense"),
    ("Other Expense", "expense"),
]


def ensure_default_categories(db: Session) -> None:
    """Insert DEFAULT_CATEGORIES if the categories table is currently empty.
    No-op otherwise — never overwrites or duplicates existing categories.
    """
    if db.query(Category).count() > 0:
        return
    db.add_all(Category(name=name, kind=kind) for name, kind in DEFAULT_CATEGORIES)
    db.commit()
