"""Transaction listing and categorization endpoints.

Categorization uses HTMX (unlike accounts.py's plain-form create/update)
because it's a frequent, per-row action that benefits from not reloading
the whole page — the category <select> in transactions/_row.html posts on
change and swaps just its own row.

TODO: filtering by account/category/date range, and manual transaction
creation, aren't in Phase 3's scope — transactions currently only get
into the system by being seeded directly or, once Phase 4/5 land, via
CSV import or SimpleFin sync.
"""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Category, Transaction
from app.templating import templates

router = APIRouter(prefix="/transactions", tags=["transactions"])


class TransactionUpdate(BaseModel):
    category_id: int | None = None


@router.get("/")
def list_transactions(request: Request, db: Session = Depends(get_db)):
    transactions = db.query(Transaction).order_by(Transaction.date.desc(), Transaction.id.desc()).all()
    categories = db.query(Category).order_by(Category.name).all()
    context = {
        "transactions": transactions,
        "categories": categories,
        "active_nav": "transactions",
    }
    return templates.TemplateResponse(request, "transactions/index.html", context)


@router.post("/{transaction_id}/category")
def update_transaction_category(
    request: Request,
    transaction_id: int,
    category_id: str = Form(""),
    db: Session = Depends(get_db),
):
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail=f"transaction {transaction_id} not found")

    payload = TransactionUpdate(category_id=int(category_id) if category_id else None)
    if payload.category_id is not None and db.get(Category, payload.category_id) is None:
        raise HTTPException(status_code=400, detail=f"category {payload.category_id} not found")

    transaction.category_id = payload.category_id
    db.commit()
    db.refresh(transaction)

    categories = db.query(Category).order_by(Category.name).all()
    context = {"transaction": transaction, "categories": categories}
    return templates.TemplateResponse(request, "transactions/_row.html", context)
