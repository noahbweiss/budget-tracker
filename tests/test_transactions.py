def test_list_transactions_empty(client):
    response = client.get("/transactions/")
    assert response.status_code == 200
    assert "No transactions yet" in response.text


def test_list_transactions_shows_seeded_rows(seeded_session, client):
    response = client.get("/transactions/")
    assert response.status_code == 200
    assert "Grocery run" in response.text
    assert "Paycheck" in response.text


def test_update_transaction_category(seeded_session, client):
    from app.models import Category, Transaction

    txn = seeded_session.query(Transaction).filter(Transaction.description == "Uncategorized expense").one()
    groceries = seeded_session.query(Category).filter(Category.name == "Groceries").one()
    assert txn.category_id is None

    response = client.post(
        f"/transactions/{txn.id}/category",
        data={"category_id": str(groceries.id)},
    )
    assert response.status_code == 200
    assert "Groceries" in response.text

    seeded_session.refresh(txn)
    assert txn.category_id == groceries.id


def test_clear_transaction_category(seeded_session, client):
    from app.models import Category, Transaction

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
    from app.models import Transaction

    txn = seeded_session.query(Transaction).first()
    response = client.post(f"/transactions/{txn.id}/category", data={"category_id": "999"})
    assert response.status_code == 400
