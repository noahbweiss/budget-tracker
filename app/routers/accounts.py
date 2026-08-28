"""Account CRUD endpoints.

Create/update use plain POST + a 303 redirect (not HTMX) — these are
infrequent, form-based actions, and progressive enhancement (works
without JS) matters more here than a snappier partial-page swap. Delete
isn't implemented yet: whether it should be a hard delete (only allowed
once an account has no transactions) or a soft-delete/archive flag is a
real design decision, not something to guess at — revisit when it's
actually needed.
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Account, Transaction
from app.templating import templates

router = APIRouter(prefix="/accounts", tags=["accounts"])

# Presets for the account_type <select> in the create/edit forms. The model
# itself stores a free string (see models.py) — this list is a form-layer
# convenience, not a DB constraint, so an account with some other value
# (e.g. seeded directly, or from a future SimpleFin sync) still round-trips
# correctly; see _account_type_options.
ACCOUNT_TYPES = ["checking", "savings", "credit", "cash", "investment", "loan", "other"]


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    institution: str | None = Field(default=None, max_length=120)
    account_type: str = Field(min_length=1, max_length=50)


class AccountUpdate(AccountCreate):
    pass


def _account_type_options(current: str) -> list[str]:
    if current in ACCOUNT_TYPES:
        return ACCOUNT_TYPES
    return [*ACCOUNT_TYPES, current]


def _account_summaries(db: Session) -> list[dict]:
    accounts = db.query(Account).order_by(Account.name).all()
    summaries = []
    for account in accounts:
        transactions = db.query(Transaction).filter(Transaction.account_id == account.id).all()
        net = sum((Decimal(t.amount) for t in transactions), start=Decimal("0"))
        summaries.append({"account": account, "net": net, "transaction_count": len(transactions)})
    return summaries


@router.get("/")
def list_accounts(request: Request, db: Session = Depends(get_db)):
    context = {
        "accounts": _account_summaries(db),
        "account_types": ACCOUNT_TYPES,
        "active_nav": "accounts",
    }
    return templates.TemplateResponse(request, "accounts/index.html", context)


@router.post("/")
def create_account(
    name: str = Form(...),
    institution: str = Form(""),
    account_type: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        payload = AccountCreate(name=name, institution=institution or None, account_type=account_type)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())

    account = Account(
        name=payload.name,
        institution=payload.institution,
        account_type=payload.account_type,
        source="manual",
    )
    db.add(account)
    db.commit()
    return RedirectResponse(url="/accounts/", status_code=303)


@router.get("/{account_id}")
def get_account(request: Request, account_id: int, db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail=f"account {account_id} not found")

    transactions = (
        db.query(Transaction)
        .filter(Transaction.account_id == account_id)
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .all()
    )
    net = sum((Decimal(t.amount) for t in transactions), start=Decimal("0"))
    context = {
        "account": account,
        "transactions": transactions,
        "net": net,
        "account_types": _account_type_options(account.account_type),
        "active_nav": "accounts",
    }
    return templates.TemplateResponse(request, "accounts/detail.html", context)


@router.post("/{account_id}")
def update_account(
    account_id: int,
    name: str = Form(...),
    institution: str = Form(""),
    account_type: str = Form(...),
    db: Session = Depends(get_db),
):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail=f"account {account_id} not found")

    try:
        payload = AccountUpdate(name=name, institution=institution or None, account_type=account_type)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())

    account.name = payload.name
    account.institution = payload.institution
    account.account_type = payload.account_type
    db.commit()
    return RedirectResponse(url=f"/accounts/{account_id}", status_code=303)
