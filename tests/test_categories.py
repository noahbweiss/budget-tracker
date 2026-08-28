from app.models import Category
from app.services.categories import DEFAULT_CATEGORIES, ensure_default_categories


def test_seeds_defaults_into_empty_table(db_session):
    ensure_default_categories(db_session)
    names = {c.name for c in db_session.query(Category).all()}
    assert names == {name for name, _ in DEFAULT_CATEGORIES}


def test_is_a_noop_when_categories_already_exist(db_session):
    db_session.add(Category(name="Custom", kind="expense"))
    db_session.commit()

    ensure_default_categories(db_session)

    names = [c.name for c in db_session.query(Category).all()]
    assert names == ["Custom"]
