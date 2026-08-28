from app.models import Account


def test_list_accounts_empty(client):
    response = client.get("/accounts/")
    assert response.status_code == 200
    assert "No accounts yet" in response.text


def test_create_account_persists_and_redirects(client, db_session):
    response = client.post(
        "/accounts/",
        data={"name": "Everyday Checking", "institution": "Ledger Bank", "account_type": "checking"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/accounts/"

    accounts = db_session.query(Account).all()
    assert len(accounts) == 1
    assert accounts[0].name == "Everyday Checking"
    assert accounts[0].institution == "Ledger Bank"
    assert accounts[0].account_type == "checking"
    assert accounts[0].source == "manual"


def test_create_account_blank_name_rejected(client, db_session):
    response = client.post(
        "/accounts/",
        data={"name": "", "institution": "", "account_type": "checking"},
    )
    assert response.status_code == 422
    assert db_session.query(Account).count() == 0


def test_list_accounts_shows_created_account_and_net_only_balance(client, db_session):
    client.post("/accounts/", data={"name": "Checking", "institution": "", "account_type": "checking"})
    account = db_session.query(Account).one()

    from datetime import date
    from app.models import Transaction

    db_session.add_all(
        [
            Transaction(account_id=account.id, date=date(2026, 6, 1), amount=1000, description="Paycheck"),
            Transaction(account_id=account.id, date=date(2026, 6, 5), amount=-200, description="Rent"),
        ]
    )
    db_session.commit()

    response = client.get("/accounts/")
    assert response.status_code == 200
    assert "Checking" in response.text
    assert "800.00" in response.text  # net = 1000 - 200, no starting balance or reported balance
    assert "Net of tracked transactions only" in response.text


def test_create_account_with_starting_balance(client, db_session):
    client.post(
        "/accounts/",
        data={"name": "Checking", "institution": "", "account_type": "checking", "starting_balance": "250.00"},
    )
    account = db_session.query(Account).one()
    assert account.starting_balance == 250

    response = client.get("/accounts/")
    assert "250.00" in response.text
    assert "Estimated from starting balance" in response.text


def test_account_list_shows_reported_balance_when_transaction_has_one(client, db_session):
    from datetime import date
    from app.models import Transaction

    account = Account(name="Checking", account_type="checking")
    db_session.add(account)
    db_session.flush()
    db_session.add(Transaction(account_id=account.id, date=date(2026, 7, 1), amount=500, description="Deposit", balance=600))
    db_session.commit()

    response = client.get("/accounts/")
    assert "600.00" in response.text
    assert "As of 2026-07-01" in response.text


def test_get_account_detail(client, db_session):
    account = Account(name="Savings", account_type="savings")
    db_session.add(account)
    db_session.commit()

    response = client.get(f"/accounts/{account.id}")
    assert response.status_code == 200
    assert "Savings" in response.text


def test_get_account_detail_404(client):
    response = client.get("/accounts/999")
    assert response.status_code == 404


def test_update_account(client, db_session):
    account = Account(name="Old Name", account_type="checking")
    db_session.add(account)
    db_session.commit()

    response = client.post(
        f"/accounts/{account.id}",
        data={"name": "New Name", "institution": "New Bank", "account_type": "savings"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/accounts/{account.id}"

    db_session.refresh(account)
    assert account.name == "New Name"
    assert account.institution == "New Bank"
    assert account.account_type == "savings"


def test_update_account_sets_and_clears_starting_balance(client, db_session):
    account = Account(name="Checking", account_type="checking")
    db_session.add(account)
    db_session.commit()

    client.post(
        f"/accounts/{account.id}",
        data={"name": "Checking", "institution": "", "account_type": "checking", "starting_balance": "300.00"},
    )
    db_session.refresh(account)
    assert account.starting_balance == 300

    client.post(
        f"/accounts/{account.id}",
        data={"name": "Checking", "institution": "", "account_type": "checking", "starting_balance": ""},
    )
    db_session.refresh(account)
    assert account.starting_balance is None


def test_update_account_404(client):
    response = client.post(
        "/accounts/999",
        data={"name": "X", "institution": "", "account_type": "checking"},
    )
    assert response.status_code == 404
