"""Tests for the Transactions page: listing/filtering/pagination, the
per-row category select, and the bulk select-then-act endpoints (mark as
transfer, mark as reimbursable, mark as resolved, delete) that replaced
the earlier per-row transfer/tag/reimbursed controls — see
docs/2026-08-30-transactions-page-redesign.md.
"""
from datetime import date, timedelta

from app.models import Account, Transaction, TransactionTag


def _bulk_post(client, action, ids, view="all", page=1):
    # httpx's TestClient needs a dict-with-list-value to send a repeated
    # form key like transaction_id=1&transaction_id=2 — a list of
    # (key, value) tuples (the `requests`-style way) isn't supported by
    # httpx's `data=` and silently produces an empty body instead.
    data = {"transaction_id": [str(i) for i in ids], "current_view": view, "current_page": str(page)}
    return client.post(f"/transactions/bulk/{action}", data=data)


def test_list_transactions_empty(client):
    response = client.get("/transactions/")
    assert response.status_code == 200
    assert "No transactions yet" in response.text


def test_list_transactions_shows_seeded_rows(seeded_session, client):
    response = client.get("/transactions/")
    assert response.status_code == 200
    assert "Grocery run" in response.text
    assert "Paycheck" in response.text


# ---- description truncation ----


def test_short_description_renders_plain(seeded_session, client):
    # Every seeded description is well under the truncation threshold —
    # none of them should get wrapped in a <details> disclosure at all.
    response = client.get("/transactions/")
    assert "description-details" not in response.text


def test_long_description_is_collapsed_behind_details(db_session, client):
    account = Account(name="Checking", account_type="checking")
    db_session.add(account)
    db_session.flush()
    long_description = "ACH Payment - CAPITAL ONE TYPE: CRCARDPMT ID: 9541719318 CO: CAPITAL ONE NAME: Noah B Weiss ACH ECC WEB"
    db_session.add(Transaction(account_id=account.id, date=date(2026, 1, 1), amount=-1, description=long_description))
    db_session.commit()

    response = client.get("/transactions/")

    assert "description-details" in response.text
    assert "…</summary>" in response.text
    assert long_description in response.text  # full text still present, just inside description-full
    # the truncated preview should not itself contain the untruncated string
    row = response.text[response.text.index("<summary>") : response.text.index("</summary>")]
    assert long_description not in row


def test_description_just_over_the_threshold_still_truncates(db_session, client):
    # Jinja's truncate() filter has a default leeway of 5 — it leaves a
    # string alone if it's only a few chars past the limit, rather than
    # truncating it. That's the wrong behavior for a hard column-width
    # cap: real bank-generated descriptions around 65 chars (5 over the
    # 60-char threshold here) were rendering in full, untruncated, until
    # this was pinned with an explicit leeway=0. This description is
    # deliberately sized to land in exactly that gap.
    account = Account(name="Checking", account_type="checking")
    db_session.add(account)
    db_session.flush()
    description = "Point Of Sale Withdrawal - COSTCO WHSE #0671  HAWTHORNE      CAUS"  # 65 chars
    assert len(description) == 65
    db_session.add(Transaction(account_id=account.id, date=date(2026, 1, 1), amount=-1, description=description))
    db_session.commit()

    response = client.get("/transactions/")

    row = response.text[response.text.index("<summary>") : response.text.index("</summary>")]
    assert description not in row
    assert "…" in row


# ---- category (unchanged: still a per-row action) ----


def test_update_transaction_category(seeded_session, client):
    from app.models import Category

    txn = seeded_session.query(Transaction).filter(Transaction.description == "Uncategorized expense").one()
    groceries = seeded_session.query(Category).filter(Category.name == "Groceries").one()
    assert txn.category_id is None

    response = client.post(f"/transactions/{txn.id}/category", data={"category_id": str(groceries.id)})
    assert response.status_code == 200
    assert "Groceries" in response.text

    seeded_session.refresh(txn)
    assert txn.category_id == groceries.id


def test_clear_transaction_category(seeded_session, client):
    txn = seeded_session.query(Transaction).filter(Transaction.description == "Grocery run").one()
    assert txn.category_id is not None

    response = client.post(f"/transactions/{txn.id}/category", data={"category_id": ""})
    assert response.status_code == 200

    seeded_session.refresh(txn)
    assert txn.category_id is None


def test_update_category_on_missing_transaction_404(client):
    response = client.post("/transactions/999/category", data={"category_id": ""})
    assert response.status_code == 404


def test_update_transaction_to_missing_category_400(seeded_session, client):
    txn = seeded_session.query(Transaction).first()
    response = client.post(f"/transactions/{txn.id}/category", data={"category_id": "999"})
    assert response.status_code == 400


# ---- bulk: mark as transfer ----


def test_bulk_transfer_single_selection_marks_it(seeded_session, client):
    txn = seeded_session.query(Transaction).filter(Transaction.description == "Grocery run").one()

    response = _bulk_post(client, "transfer", [txn.id])
    assert response.status_code == 200
    assert "pill--transfer" in response.text

    seeded_session.refresh(txn)
    assert txn.is_transfer is True


def test_bulk_transfer_single_selection_twice_unmarks(seeded_session, client):
    txn = seeded_session.query(Transaction).filter(Transaction.description == "Grocery run").one()

    _bulk_post(client, "transfer", [txn.id])
    response = _bulk_post(client, "transfer", [txn.id])
    assert response.status_code == 200

    seeded_session.refresh(txn)
    assert txn.is_transfer is False


def test_bulk_transfer_two_selections_pairs_them(seeded_session, client):
    grocery = seeded_session.query(Transaction).filter(Transaction.description == "Grocery run").one()
    other_account = Account(name="Credit Card", account_type="credit")
    seeded_session.add(other_account)
    seeded_session.flush()
    other_side = Transaction(
        account_id=other_account.id, date=grocery.date, amount=-grocery.amount, description="the other side"
    )
    seeded_session.add(other_side)
    seeded_session.commit()

    response = _bulk_post(client, "transfer", [grocery.id, other_side.id])
    assert response.status_code == 200
    assert "↔" in response.text

    seeded_session.refresh(grocery)
    seeded_session.refresh(other_side)
    assert grocery.transfer_pair_id == other_side.id
    assert other_side.transfer_pair_id == grocery.id


def test_bulk_transfer_two_selections_same_account_400(seeded_session, client):
    grocery = seeded_session.query(Transaction).filter(Transaction.description == "Grocery run").one()
    more_groceries = seeded_session.query(Transaction).filter(Transaction.description == "More groceries").one()

    response = _bulk_post(client, "transfer", [grocery.id, more_groceries.id])
    assert response.status_code == 400


def test_bulk_transfer_three_selections_400(seeded_session, client):
    ids = [t.id for t in seeded_session.query(Transaction).limit(3).all()]
    response = _bulk_post(client, "transfer", ids)
    assert response.status_code == 400


def test_bulk_transfer_no_selection_400(client):
    response = _bulk_post(client, "transfer", [])
    assert response.status_code == 400


# ---- bulk: mark as reimbursable ----


def test_bulk_reimbursable_single_toggles(seeded_session, client):
    txn = seeded_session.query(Transaction).filter(Transaction.description == "Grocery run").one()

    response = _bulk_post(client, "reimbursable", [txn.id])
    assert response.status_code == 200
    assert "pill--tag" in response.text
    seeded_session.refresh(txn)
    assert [t.slug for t in txn.tags] == ["reimbursable"]

    _bulk_post(client, "reimbursable", [txn.id])
    seeded_session.refresh(txn)
    assert txn.tags == []


def test_bulk_reimbursable_multi_only_adds(seeded_session, client):
    grocery = seeded_session.query(Transaction).filter(Transaction.description == "Grocery run").one()
    more_groceries = seeded_session.query(Transaction).filter(Transaction.description == "More groceries").one()
    _bulk_post(client, "reimbursable", [grocery.id])  # already tagged

    response = _bulk_post(client, "reimbursable", [grocery.id, more_groceries.id])
    assert response.status_code == 200

    seeded_session.refresh(grocery)
    seeded_session.refresh(more_groceries)
    assert [t.slug for t in grocery.tags] == ["reimbursable"]  # untouched, not removed
    assert [t.slug for t in more_groceries.tags] == ["reimbursable"]  # newly added


# ---- bulk: mark as resolved ----


def test_bulk_resolved_single_toggles(seeded_session, client):
    txn = seeded_session.query(Transaction).filter(Transaction.description == "Grocery run").one()

    response = _bulk_post(client, "resolved", [txn.id])
    assert response.status_code == 200
    seeded_session.refresh(txn)
    assert txn.reimbursed is True

    _bulk_post(client, "resolved", [txn.id])
    seeded_session.refresh(txn)
    assert txn.reimbursed is False


def test_bulk_resolved_multi_only_sets_true(seeded_session, client):
    grocery = seeded_session.query(Transaction).filter(Transaction.description == "Grocery run").one()
    more_groceries = seeded_session.query(Transaction).filter(Transaction.description == "More groceries").one()

    response = _bulk_post(client, "resolved", [grocery.id, more_groceries.id])
    assert response.status_code == 200

    seeded_session.refresh(grocery)
    seeded_session.refresh(more_groceries)
    assert grocery.reimbursed is True
    assert more_groceries.reimbursed is True


# ---- bulk: delete ----


def test_bulk_delete_removes_transactions(seeded_session, client):
    txn = seeded_session.query(Transaction).filter(Transaction.description == "Grocery run").one()
    txn_id = txn.id

    response = _bulk_post(client, "delete", [txn_id])
    assert response.status_code == 200

    assert seeded_session.get(Transaction, txn_id) is None


def test_bulk_delete_unlinks_transfer_partner(seeded_session, client):
    grocery = seeded_session.query(Transaction).filter(Transaction.description == "Grocery run").one()
    other_account = Account(name="Credit Card", account_type="credit")
    seeded_session.add(other_account)
    seeded_session.flush()
    other_side = Transaction(
        account_id=other_account.id, date=grocery.date, amount=-grocery.amount, description="the other side"
    )
    seeded_session.add(other_side)
    seeded_session.commit()
    _bulk_post(client, "transfer", [grocery.id, other_side.id])

    _bulk_post(client, "delete", [grocery.id])

    seeded_session.refresh(other_side)
    assert other_side.is_transfer is False
    assert other_side.transfer_pair_id is None


def test_bulk_delete_removes_tag_associations(seeded_session, client):
    txn = seeded_session.query(Transaction).filter(Transaction.description == "Grocery run").one()
    txn_id = txn.id
    _bulk_post(client, "reimbursable", [txn_id])

    _bulk_post(client, "delete", [txn_id])

    assert seeded_session.query(TransactionTag).filter(TransactionTag.transaction_id == txn_id).first() is None


def test_bulk_delete_no_selection_400(client):
    response = _bulk_post(client, "delete", [])
    assert response.status_code == 400


# ---- view filter ----


def test_view_owed_shows_only_unresolved_reimbursable(seeded_session, client):
    grocery = seeded_session.query(Transaction).filter(Transaction.description == "Grocery run").one()
    more_groceries = seeded_session.query(Transaction).filter(Transaction.description == "More groceries").one()
    _bulk_post(client, "reimbursable", [grocery.id])
    _bulk_post(client, "reimbursable", [more_groceries.id])
    _bulk_post(client, "resolved", [grocery.id])  # only this one gets resolved

    response = client.get("/transactions/?view=owed")
    assert "More groceries" in response.text
    assert "Grocery run" not in response.text


def test_view_resolved_shows_only_resolved(seeded_session, client):
    grocery = seeded_session.query(Transaction).filter(Transaction.description == "Grocery run").one()
    more_groceries = seeded_session.query(Transaction).filter(Transaction.description == "More groceries").one()
    _bulk_post(client, "reimbursable", [grocery.id])
    _bulk_post(client, "reimbursable", [more_groceries.id])
    _bulk_post(client, "resolved", [grocery.id])

    response = client.get("/transactions/?view=resolved")
    assert "Grocery run" in response.text
    assert "More groceries" not in response.text


def test_view_all_shows_everything(seeded_session, client):
    grocery = seeded_session.query(Transaction).filter(Transaction.description == "Grocery run").one()
    _bulk_post(client, "reimbursable", [grocery.id])

    response = client.get("/transactions/")
    assert "Grocery run" in response.text
    assert "Paycheck" in response.text


def test_unknown_view_falls_back_to_all(seeded_session, client):
    response = client.get("/transactions/?view=not-a-real-view")
    assert response.status_code == 200
    assert "Paycheck" in response.text


# ---- pagination ----


def test_pagination_caps_at_page_size(db_session, client):
    from app.routers.transactions import PAGE_SIZE

    extra = 20  # however many spill onto a second page
    account = Account(name="Checking", account_type="checking")
    db_session.add(account)
    db_session.flush()
    start = date(2026, 1, 1)
    db_session.add_all(
        [
            Transaction(account_id=account.id, date=start + timedelta(days=i), amount=-1, description=f"txn {i}")
            for i in range(PAGE_SIZE + extra)
        ]
    )
    db_session.commit()

    page1 = client.get("/transactions/")
    assert page1.text.count('class="row-select"') == PAGE_SIZE
    assert "Page 1 of 2" in page1.text

    page2 = client.get("/transactions/?page=2")
    assert page2.text.count('class="row-select"') == extra
    assert "Page 2 of 2" in page2.text


def test_pagination_out_of_range_page_clamps(db_session, client):
    account = Account(name="Checking", account_type="checking")
    db_session.add(account)
    db_session.flush()
    db_session.add(Transaction(account_id=account.id, date=date(2026, 1, 1), amount=-1, description="only one"))
    db_session.commit()

    response = client.get("/transactions/?page=99")
    assert response.status_code == 200
    assert "only one" in response.text
