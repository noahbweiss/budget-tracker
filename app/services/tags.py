"""System-defined tags — a small, fixed set of labels a transaction can
carry. Unlike Category (user-extensible, no fixed list), tags are
code-owned: there's no UI to create a new one, and SYSTEM_TAGS below is
the single source of truth for which ones exist.

"reimbursable" backs the "owed to me" tracking flow — paired with
Transaction.reimbursed for its resolved/open status (see app/models.py).
"subscription" backs recurring-payment detection (a later phase) — seeded
here alongside "reimbursable" since both slugs are defined together in
this phase, not added incrementally, but nothing about detection is
built yet; for now it's just available for manual tagging like any tag.

Why a Tag/TransactionTag many-to-many table rather than a couple of
booleans on Transaction, for what's currently just two fixed slugs: an
explicit design choice, not an oversight — the user was asked exactly
this tradeoff ("one general tag system" vs. "separate purpose-built
fields") and chose the general mechanism. See
docs/2026-08-29-feature-plan.md's Phase B notes for the full reasoning.
"""
from sqlalchemy.orm import Session

from app.models import Tag

SYSTEM_TAGS = [
    ("reimbursable", "Reimbursable"),
    ("subscription", "Subscription"),
]


def ensure_system_tags(db: Session) -> None:
    """Idempotent per-slug (not empty-table-only, unlike
    categories.ensure_default_categories()): tags are code-owned and never
    user-renamed or deleted, so re-checking on every startup safely
    repairs a lost/missing row with no risk of clobbering anything a
    user set — there's nothing user-set on a Tag row to clobber.
    """
    existing_slugs = {slug for (slug,) in db.query(Tag.slug).all()}
    for slug, name in SYSTEM_TAGS:
        if slug not in existing_slugs:
            db.add(Tag(slug=slug, name=name))
    db.commit()
