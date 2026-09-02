"""Tests for app.services.transfers.

A transfer is the user's own money moving between their own accounts
(paying off a credit card from checking, most commonly) — never real
income or spending. Pairing is optional, not required: marking one side
is a fully valid end state (e.g. the other account isn't tracked in this
app). link_transfer_pair confirms a specific match; the Transactions page
gets a user to one by having them select both sides themselves (see
routers/transactions.py's bulk/transfer route) rather than through a
suggested-candidate heuristic — an earlier find_transfer_candidates()
here was retired once that replaced it.
"""
from datetime import date

from app.models import Account, Transaction
from app.services import transfers


def _account(db_session, **kwargs):
    account = Account(name=kwargs.pop("name", "Account"), account_type=kwargs.pop("account_type", "checking"), **kwargs)
    db_session.add(account)
    db_session.flush()
    return account


def _txn(db_session, account_id, d, amount, description="x", **kwargs):
    t = Transaction(account_id=account_id, date=d, amount=amount, description=description, **kwargs)
    db_session.add(t)
    db_session.flush()
    return t


# ---- mark / unmark ----


def test_mark_as_transfer_is_unpaired_by_default(db_session):
    checking = _account(db_session, name="Checking")
    txn = _txn(db_session, checking.id, date(2026, 7, 1), -500.00)
    db_session.commit()

    transfers.mark_as_transfer(db_session, txn)
    db_session.commit()

    db_session.refresh(txn)
    assert txn.is_transfer is True
    assert txn.transfer_pair_id is None


def test_unmark_clears_both_sides_of_a_pair(db_session):
    checking = _account(db_session, name="Checking")
    credit = _account(db_session, name="Credit Card", account_type="credit")
    payment = _txn(db_session, checking.id, date(2026, 7, 1), -500.00)
    payoff = _txn(db_session, credit.id, date(2026, 7, 1), 500.00)
    db_session.commit()

    transfers.link_transfer_pair(db_session, payment, payoff)
    db_session.commit()

    transfers.unmark_transfer(db_session, payment)
    db_session.commit()

    db_session.refresh(payment)
    db_session.refresh(payoff)
    assert payment.is_transfer is False
    assert payment.transfer_pair_id is None
    assert payoff.is_transfer is False  # the *other* side, not the one unmark was called on
    assert payoff.transfer_pair_id is None


def test_unmark_an_unpaired_transfer_is_safe(db_session):
    checking = _account(db_session, name="Checking")
    txn = _txn(db_session, checking.id, date(2026, 7, 1), -500.00, is_transfer=True)
    db_session.commit()

    transfers.unmark_transfer(db_session, txn)  # must not raise
    db_session.commit()

    db_session.refresh(txn)
    assert txn.is_transfer is False


# ---- link_transfer_pair ----


def test_link_transfer_pair_sets_both_sides_symmetrically(db_session):
    checking = _account(db_session, name="Checking")
    credit = _account(db_session, name="Credit Card")
    payment = _txn(db_session, checking.id, date(2026, 7, 1), -500.00)
    payoff = _txn(db_session, credit.id, date(2026, 7, 1), 500.00)
    db_session.commit()

    transfers.link_transfer_pair(db_session, payment, payoff)
    db_session.commit()

    db_session.refresh(payment)
    db_session.refresh(payoff)
    assert payment.is_transfer is True and payment.transfer_pair_id == payoff.id
    assert payoff.is_transfer is True and payoff.transfer_pair_id == payment.id


# ---- clear_pair_on_delete ----


def test_clear_pair_on_delete_unlinks_the_surviving_partner(db_session):
    checking = _account(db_session, name="Checking")
    credit = _account(db_session, name="Credit Card")
    payment = _txn(db_session, checking.id, date(2026, 7, 1), -500.00)
    payoff = _txn(db_session, credit.id, date(2026, 7, 1), 500.00)
    db_session.commit()
    transfers.link_transfer_pair(db_session, payment, payoff)
    db_session.commit()

    transfers.clear_pair_on_delete(db_session, payment)
    db_session.delete(payment)
    db_session.commit()

    db_session.refresh(payoff)
    assert payoff.is_transfer is False
    assert payoff.transfer_pair_id is None


def test_clear_pair_on_delete_is_a_noop_for_an_unpaired_transaction(db_session):
    checking = _account(db_session, name="Checking")
    txn = _txn(db_session, checking.id, date(2026, 7, 1), -500.00, is_transfer=True)
    db_session.commit()

    transfers.clear_pair_on_delete(db_session, txn)  # must not raise
    db_session.commit()
