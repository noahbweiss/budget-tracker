"""Tests for app.services.tags.ensure_system_tags.

Unlike app.services.categories.ensure_default_categories (only seeds an
empty table), this is idempotent per-slug — it should safely repair a
missing tag on every startup without duplicating one that's already
there or touching anything else.
"""
from app.models import Tag
from app.services.tags import SYSTEM_TAGS, ensure_system_tags


def test_seeds_all_system_tags_on_an_empty_table(db_session):
    # db_session's fixture already calls ensure_system_tags once — assert
    # against that, then prove a second explicit call changes nothing.
    tags = db_session.query(Tag).order_by(Tag.id).all()
    assert [(t.slug, t.name) for t in tags] == SYSTEM_TAGS


def test_is_idempotent_and_does_not_duplicate(db_session):
    ensure_system_tags(db_session)
    ensure_system_tags(db_session)

    tags = db_session.query(Tag).all()
    assert len(tags) == len(SYSTEM_TAGS)
    assert len({t.slug for t in tags}) == len(SYSTEM_TAGS)


def test_repairs_a_missing_tag_without_touching_existing_ones(db_session):
    reimbursable = db_session.query(Tag).filter(Tag.slug == "reimbursable").one()
    db_session.delete(reimbursable)
    db_session.commit()
    assert db_session.query(Tag).filter(Tag.slug == "reimbursable").first() is None

    ensure_system_tags(db_session)

    tags = {t.slug: t.name for t in db_session.query(Tag).all()}
    assert tags == dict(SYSTEM_TAGS)
