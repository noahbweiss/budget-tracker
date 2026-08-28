"""Tests for the /import router: upload -> preview/mapping -> confirm."""
import io

from app.models import Account, Transaction

GOOD_CSV = b"Date,Description,Amount\n2026-07-01,Paycheck,3200.00\n2026-07-02,Rent,-1450.00\n"
UNRECOGNIZED_CSV = b"When,What,HowMuch\n2026-07-01,Paycheck,3200.00\n"
CSV_WITH_BALANCE = (
    b"Date,Description,Amount,Balance\n"
    b"2026-07-01,Deposit,500.00,600.00\n"
    b"2026-07-02,Rent,-1450.00,-850.00\n"
)

SAMPLE_OFX = b"""OFXHEADER:100
<OFX>
<BANKMSGSRSV1>
<STMTTRNRS>
<STMTRS>
<BANKTRANLIST>
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20260701
<TRNAMT>-42.50
<FITID>2026070100001
<NAME>Grocery Store
</STMTTRN>
</BANKTRANLIST>
</STMTRS>
</STMTRNRS>
</BANKMSGSRSV1>
</OFX>
"""


def _make_account(db_session, name="Checking"):
    account = Account(name=name, account_type="checking")
    db_session.add(account)
    db_session.commit()
    return account


def test_upload_page_prompts_to_create_account_when_none_exist(client):
    response = client.get("/import/")
    assert response.status_code == 200
    assert "create an account" in response.text.lower()


def test_upload_page_shows_form_when_accounts_exist(client, db_session):
    _make_account(db_session)
    response = client.get("/import/")
    assert response.status_code == 200
    assert "Checking" in response.text


def test_upload_good_csv_shows_preview_with_no_mapping_needed(client, db_session):
    account = _make_account(db_session)
    response = client.post(
        "/import/upload",
        data={"account_id": str(account.id)},
        files={"file": ("statement.csv", io.BytesIO(GOOD_CSV), "text/csv")},
    )
    assert response.status_code == 200
    assert "Paycheck" in response.text
    assert "3200.00" in response.text
    assert 'name="token"' in response.text


def test_upload_unrecognized_csv_shows_mapping_form(client, db_session):
    account = _make_account(db_session)
    response = client.post(
        "/import/upload",
        data={"account_id": str(account.id)},
        files={"file": ("statement.csv", io.BytesIO(UNRECOGNIZED_CSV), "text/csv")},
    )
    assert response.status_code == 200
    assert "When" in response.text  # raw header offered as a mapping option
    assert "Paycheck" not in response.text  # nothing parsed yet — no mapping applied


def test_manual_mapping_preview_updates_fragment(client, db_session):
    account = _make_account(db_session)
    upload = client.post(
        "/import/upload",
        data={"account_id": str(account.id)},
        files={"file": ("statement.csv", io.BytesIO(UNRECOGNIZED_CSV), "text/csv")},
    )
    token = _extract_hidden_value(upload.text, "token")

    response = client.post(
        "/import/preview",
        data={
            "token": token,
            "account_id": str(account.id),
            "file_kind": "csv",
            "date_column": "When",
            "description_column": "What",
            "amount_column": "HowMuch",
        },
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert "Paycheck" in response.text
    assert "3200.00" in response.text


def test_confirm_inserts_transactions_and_reimport_dedups(client, db_session):
    account = _make_account(db_session)
    upload = client.post(
        "/import/upload",
        data={"account_id": str(account.id)},
        files={"file": ("statement.csv", io.BytesIO(GOOD_CSV), "text/csv")},
    )
    token = _extract_hidden_value(upload.text, "token")

    confirm = client.post(
        "/import/confirm",
        data={
            "token": token,
            "account_id": str(account.id),
            "file_kind": "csv",
            "date_column": "Date",
            "description_column": "Description",
            "amount_column": "Amount",
        },
    )
    assert confirm.status_code == 200
    assert "Imported 2" in confirm.text

    transactions = db_session.query(Transaction).filter(Transaction.account_id == account.id).all()
    assert len(transactions) == 2

    # Re-upload + confirm the exact same file for the same account: every
    # row should be recognized as a duplicate via external_id, not doubled.
    upload2 = client.post(
        "/import/upload",
        data={"account_id": str(account.id)},
        files={"file": ("statement.csv", io.BytesIO(GOOD_CSV), "text/csv")},
    )
    token2 = _extract_hidden_value(upload2.text, "token")
    confirm2 = client.post(
        "/import/confirm",
        data={
            "token": token2,
            "account_id": str(account.id),
            "file_kind": "csv",
            "date_column": "Date",
            "description_column": "Description",
            "amount_column": "Amount",
        },
    )
    assert "Imported 0" in confirm2.text
    assert "skipped 2" in confirm2.text.lower()

    transactions = db_session.query(Transaction).filter(Transaction.account_id == account.id).all()
    assert len(transactions) == 2


def test_confirm_with_unknown_token_404s(client, db_session):
    account = _make_account(db_session)
    response = client.post(
        "/import/confirm",
        data={"token": "does-not-exist", "account_id": str(account.id), "file_kind": "csv"},
    )
    assert response.status_code == 404


def test_cancel_removes_temp_file_and_redirects(client, db_session):
    account = _make_account(db_session)
    upload = client.post(
        "/import/upload",
        data={"account_id": str(account.id)},
        files={"file": ("statement.csv", io.BytesIO(GOOD_CSV), "text/csv")},
    )
    token = _extract_hidden_value(upload.text, "token")

    cancel = client.post("/import/cancel", data={"token": token, "file_kind": "csv"}, follow_redirects=False)
    assert cancel.status_code == 303

    # The token is now invalid — confirming it should 404, proving the
    # temp file was actually removed rather than just ignored.
    confirm = client.post(
        "/import/confirm",
        data={"token": token, "account_id": str(account.id), "file_kind": "csv"},
    )
    assert confirm.status_code == 404


def test_upload_ofx_skips_mapping_straight_to_preview(client, db_session):
    account = _make_account(db_session)
    response = client.post(
        "/import/upload",
        data={"account_id": str(account.id)},
        files={"file": ("statement.ofx", io.BytesIO(SAMPLE_OFX), "application/x-ofx")},
    )
    assert response.status_code == 200
    assert "Grocery Store" in response.text
    assert "-$42.50" in response.text


def test_upload_rejects_unsupported_extension(client, db_session):
    account = _make_account(db_session)
    response = client.post(
        "/import/upload",
        data={"account_id": str(account.id)},
        files={"file": ("statement.txt", io.BytesIO(b"nope"), "text/plain")},
    )
    assert response.status_code == 400


def test_confirm_captures_balance_on_new_transactions(client, db_session):
    account = _make_account(db_session)
    upload = client.post(
        "/import/upload",
        data={"account_id": str(account.id)},
        files={"file": ("statement.csv", io.BytesIO(CSV_WITH_BALANCE), "text/csv")},
    )
    token = _extract_hidden_value(upload.text, "token")

    confirm = client.post(
        "/import/confirm",
        data={
            "token": token,
            "account_id": str(account.id),
            "file_kind": "csv",
            "date_column": "Date",
            "description_column": "Description",
            "amount_column": "Amount",
            "balance_column": "Balance",
        },
    )
    assert confirm.status_code == 200

    transactions = db_session.query(Transaction).filter(Transaction.account_id == account.id).order_by(Transaction.date).all()
    assert transactions[0].balance == 600
    assert transactions[1].balance == -850


def test_reimport_with_balance_backfills_existing_transactions(client, db_session):
    account = _make_account(db_session)
    no_balance_csv = b"Date,Description,Amount\n2026-07-01,Deposit,500.00\n2026-07-02,Rent,-1450.00\n"

    # First import: no balance column mapped at all.
    upload1 = client.post(
        "/import/upload",
        data={"account_id": str(account.id)},
        files={"file": ("statement.csv", io.BytesIO(no_balance_csv), "text/csv")},
    )
    token1 = _extract_hidden_value(upload1.text, "token")
    confirm1 = client.post(
        "/import/confirm",
        data={
            "token": token1,
            "account_id": str(account.id),
            "file_kind": "csv",
            "date_column": "Date",
            "description_column": "Description",
            "amount_column": "Amount",
        },
    )
    assert "Imported 2" in confirm1.text
    transactions = db_session.query(Transaction).filter(Transaction.account_id == account.id).all()
    assert all(t.balance is None for t in transactions)

    # Re-upload the same dates/amounts/descriptions, this time with a
    # Balance column mapped — should backfill, not duplicate.
    upload2 = client.post(
        "/import/upload",
        data={"account_id": str(account.id)},
        files={"file": ("statement.csv", io.BytesIO(CSV_WITH_BALANCE), "text/csv")},
    )
    token2 = _extract_hidden_value(upload2.text, "token")
    confirm2 = client.post(
        "/import/confirm",
        data={
            "token": token2,
            "account_id": str(account.id),
            "file_kind": "csv",
            "date_column": "Date",
            "description_column": "Description",
            "amount_column": "Amount",
            "balance_column": "Balance",
        },
    )
    assert "Imported 0" in confirm2.text
    assert "2 existing transactions" in confirm2.text

    transactions = db_session.query(Transaction).filter(Transaction.account_id == account.id).order_by(Transaction.date).all()
    assert len(transactions) == 2  # still just 2 — not duplicated
    assert transactions[0].balance == 600
    assert transactions[1].balance == -850


def _extract_hidden_value(html: str, field_name: str) -> str:
    import re

    match = re.search(rf'name="{field_name}"\s+value="([^"]*)"', html)
    assert match, f"no hidden field {field_name!r} found in response"
    return match.group(1)
