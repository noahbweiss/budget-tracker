"""Tests for the /accounts/merge* routes."""
from datetime import date

from app.models import Account, Transaction


def _account(db_session, **kwargs):
    account = Account(name=kwargs.pop("name", "Account"), account_type=kwargs.pop("account_type", "checking"), **kwargs)
    db_session.add(account)
    db_session.flush()
    return account


def _txn(db_session, account_id, d, amount, description="x"):
    t = Transaction(account_id=account_id, date=d, amount=amount, description=description)
    db_session.add(t)
    db_session.flush()
    return t


def test_merge_form_requires_two_accounts(client, db_session):
    _account(db_session, name="Only One")
    db_session.commit()

    response = client.get("/accounts/merge")
    assert response.status_code == 200
    assert "Nothing to merge yet" in response.text


def test_merge_form_lists_accounts_when_two_exist(client, db_session):
    _account(db_session, name="Card A")
    _account(db_session, name="Card B")
    db_session.commit()

    response = client.get("/accounts/merge")
    assert "Card A" in response.text
    assert "Card B" in response.text


def test_preview_rejects_merging_an_account_into_itself(client, db_session):
    a = _account(db_session, name="Card A")
    db_session.commit()

    response = client.post("/accounts/merge/preview", data={"source_account_id": a.id, "target_account_id": a.id})
    assert response.status_code == 400


def test_preview_shows_candidate_duplicate_pairs_and_unmatched(client, db_session):
    source = _account(db_session, name="CSV Card")
    target = _account(db_session, name="Synced Card")
    _txn(db_session, source.id, date(2026, 7, 1), -20.00, description="Dup on both sides")
    _txn(db_session, target.id, date(2026, 7, 1), -20.00, description="Dup on both sides")
    _txn(db_session, source.id, date(2026, 7, 5), -15.00, description="Only in source")
    db_session.commit()

    response = client.post(
        "/accounts/merge/preview", data={"source_account_id": source.id, "target_account_id": target.id}
    )
    assert response.status_code == 200
    assert "Possible duplicates" in response.text
    assert "Only in source" not in response.text  # in the unmatched summary, not itemized
    assert "1 transaction" in response.text  # the unmatched count


def test_confirm_merges_and_redirects_to_target(client, db_session):
    source = _account(db_session, name="CSV Card")
    target = _account(db_session, name="Synced Card")
    s1 = _txn(db_session, source.id, date(2026, 7, 1), -20.00, description="Unique")
    db_session.commit()

    response = client.post(
        "/accounts/merge/confirm",
        data={"source_account_id": source.id, "target_account_id": target.id},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/accounts/{target.id}"

    db_session.refresh(s1)
    assert s1.account_id == target.id
    assert db_session.get(Account, source.id) is None


def test_confirm_discards_checked_duplicate_pairs(client, db_session):
    source = _account(db_session, name="CSV Card")
    target = _account(db_session, name="Synced Card")
    s1 = _txn(db_session, source.id, date(2026, 7, 1), -20.00, description="dup")
    t1 = _txn(db_session, target.id, date(2026, 7, 1), -20.00, description="dup")
    db_session.commit()

    client.post(
        "/accounts/merge/confirm",
        data={
            "source_account_id": source.id,
            "target_account_id": target.id,
            "discard_transaction_ids": [str(s1.id)],
        },
    )

    remaining = db_session.query(Transaction).filter(Transaction.account_id == target.id).all()
    assert [t.id for t in remaining] == [t1.id]


def test_merged_account_shows_synced_badge_via_simplefin_account_id(client, db_session):
    source = _account(db_session, name="Synced Card", simplefin_account_id="remote-1")
    target = _account(db_session, name="CSV Card")
    db_session.commit()

    client.post("/accounts/merge/confirm", data={"source_account_id": source.id, "target_account_id": target.id})

    response = client.get(f"/accounts/{target.id}")
    assert "Synced" in response.text
