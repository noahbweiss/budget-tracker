"""Transaction listing, categorization, and bulk row actions.

Categorization stays a per-row action (the category <select> posts on
change, swaps just its own row via hx-target="closest tr") — it's the
single highest-frequency thing done on this page, so it stays inline
rather than routing through selection.

Everything else (marking a transfer, tagging reimbursable, resolving,
deleting) goes through a select-then-act model instead of one HTMX
control per row per action: check the rows you want (a checkbox per row,
name="transaction_id"), then click one action in the bulk action bar
(transactions/index.html, outside the swapped region) which POSTs to one
of the /bulk/ routes below with whatever's checked. This replaced an
earlier per-row-button design (mark/unmark transfer, tag toggle pills, a
reimbursed checkbox) that got cluttered fast once transfers and tags
both landed on the same row — see docs/2026-08-30-transactions-page-
redesign.md for the reasoning and the two things this fixes that aren't
just visual: (1) real N+1-query slowness on the old unpaginated
all-transactions view, fixed here with eager loading + paginated
pagination; (2) "unstructured links" for the All/Owed-to-me/Resolved
filter, replaced with one real <select> (?view=).

The list route mirrors dashboard.py's HTMX-fragment-vs-full-page
pattern: a full page on normal navigation, or just
transactions/_content.html when triggered by HTMX (filter change,
pagination, or a bulk action's response) — so switching filters/pages
never reloads the whole page, addressing the actual reported slowness
along with the query-side fixes above. Every bulk action responds with
that same fragment, re-rendered at the *same* filter/page the action was
taken from (carried back via hidden inputs inside the fragment — see
_content.html's hx-include target — not reset to page 1 on every click).

TODO: manual transaction creation still isn't in scope — transactions
only get into the system via seeding, CSV/OFX import, or SimpleFin sync.
"""
import math

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload, selectinload

from app.database import get_db
from app.models import Category, Tag, Transaction
from app.services import transfers
from app.templating import templates

router = APIRouter(prefix="/transactions", tags=["transactions"])

PAGE_SIZE = 50

# One structured filter control (a real <select>) instead of three
# hand-coded links, per the redesign — each maps to a (tag, resolved)
# pair the query layer already understands from Phase B, so nothing
# about the underlying filtering logic had to change, just how a user
# picks a value.
VIEWS = {
    "all": (None, None),
    "owed": ("reimbursable", False),
    "resolved": ("reimbursable", True),
}


class TransactionUpdate(BaseModel):
    category_id: int | None = None


def _base_query(db: Session):
    # joinedload for account/category/transfer_pair (many-to-one — one
    # extra JOIN each, no row multiplication) and selectinload for tags
    # (many-to-many — a JOIN here would multiply rows per tag, a second
    # query avoids that). Without this, rendering N rows means ~4N extra
    # lazy-load queries — the actual cause of the reported slowness at
    # 1,000+ transactions, pagination alone would only have masked it.
    return db.query(Transaction).options(
        joinedload(Transaction.account),
        joinedload(Transaction.category),
        joinedload(Transaction.transfer_pair).joinedload(Transaction.account),
        selectinload(Transaction.tags),
    )


def _filtered_query(db: Session, view: str):
    tag, resolved = VIEWS.get(view, VIEWS["all"])
    query = _base_query(db)
    if tag is not None:
        query = query.filter(Transaction.tags.any(Tag.slug == tag))
        if resolved is not None:
            query = query.filter(Transaction.reimbursed.is_(resolved))
    return query


def _render_view(request: Request, db: Session, view: str, page: int):
    if view not in VIEWS:
        view = "all"
    query = _filtered_query(db, view)

    total = query.count()
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(max(1, page), total_pages)

    transactions = (
        query.order_by(Transaction.date.desc(), Transaction.id.desc())
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
        .all()
    )

    context = {
        "transactions": transactions,
        "categories": db.query(Category).order_by(Category.name).all(),
        "active_nav": "transactions",
        "view": view,
        "page": page,
        "total_pages": total_pages,
        "total": total,
    }
    template_name = "transactions/_content.html" if request.headers.get("hx-request") == "true" else "transactions/index.html"
    return templates.TemplateResponse(request, template_name, context)


@router.get("/")
def list_transactions(request: Request, view: str = "all", page: int = 1, db: Session = Depends(get_db)):
    return _render_view(request, db, view, page)


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

    categories = db.query(Category).order_by(Category.name).all()
    transaction = _base_query(db).filter(Transaction.id == transaction_id).one()
    return templates.TemplateResponse(request, "transactions/_row.html", {"transaction": transaction, "categories": categories})


async def _bulk_request_state(request: Request) -> tuple[list[int], str, int]:
    """Every bulk action shares the same request shape: a set of checked
    transaction_id values, plus the view/page the action bar's hidden
    inputs carried along (see _content.html) so the response can re-render
    at the same spot instead of resetting the list to page 1.
    """
    form = await request.form()
    ids = [int(v) for v in form.getlist("transaction_id")]
    view = form.get("current_view") or "all"
    page = int(form.get("current_page") or 1)
    return ids, view, page


def _selected_transactions(db: Session, ids: list[int]) -> list[Transaction]:
    if not ids:
        raise HTTPException(status_code=400, detail="no transactions selected")
    found = db.query(Transaction).filter(Transaction.id.in_(ids)).all()
    if not found:
        raise HTTPException(status_code=400, detail="no matching transactions found")
    return found


@router.post("/bulk/transfer")
async def bulk_mark_transfer(request: Request, db: Session = Depends(get_db)):
    """Selecting exactly 2 pairs them directly as each other's transfer
    match — replaces the old per-row "here's a possible match" suggestion
    UI with something more direct: if you're selecting both sides
    yourself, there's nothing left to suggest. Selecting 1 marks it alone
    (a fully valid, unpaired end state — see app/services/transfers.py);
    for a single already-marked transaction this un-marks it instead,
    preserving the old toggle behavior for the "I clicked the wrong one"
    case. 3+ has no sensible pairing semantic, so it's rejected.
    """
    ids, view, page = await _bulk_request_state(request)
    selected = _selected_transactions(db, ids)

    if len(selected) == 1:
        txn = selected[0]
        if txn.is_transfer:
            transfers.unmark_transfer(db, txn)
        else:
            transfers.mark_as_transfer(db, txn)
    elif len(selected) == 2:
        a, b = selected
        if a.account_id == b.account_id:
            raise HTTPException(status_code=400, detail="select transactions on two different accounts to pair as a transfer")
        transfers.link_transfer_pair(db, a, b)
    else:
        raise HTTPException(status_code=400, detail="select 1 transaction to mark it alone, or 2 to pair them as a transfer")

    db.commit()
    return _render_view(request, db, view, page)


@router.post("/bulk/reimbursable")
async def bulk_mark_reimbursable(request: Request, db: Session = Depends(get_db)):
    """A single selection toggles the tag (add if missing, remove if
    present) — the correction path for a mistake. Multiple selections
    only ever add the tag (to whichever selected transactions don't
    already have it); removing from many at once isn't offered, since
    "select 5, remove the tag from all of them" is a much rarer need
    than "select 5 dinner charges, flag them all reimbursable."
    """
    ids, view, page = await _bulk_request_state(request)
    selected = _selected_transactions(db, ids)
    tag = db.query(Tag).filter(Tag.slug == "reimbursable").one()

    if len(selected) == 1:
        txn = selected[0]
        if tag in txn.tags:
            txn.tags.remove(tag)
        else:
            txn.tags.append(tag)
    else:
        for txn in selected:
            if tag not in txn.tags:
                txn.tags.append(tag)

    db.commit()
    return _render_view(request, db, view, page)


@router.post("/bulk/resolved")
async def bulk_mark_resolved(request: Request, db: Session = Depends(get_db)):
    """Same single-toggles / multi-only-adds pattern as reimbursable
    above, for the same reason — see that route's docstring. Doesn't
    require the reimbursable tag to be present (see Transaction.reimbursed's
    docstring: it's a decoupled status field, not derived from the tag).
    """
    ids, view, page = await _bulk_request_state(request)
    selected = _selected_transactions(db, ids)

    if len(selected) == 1:
        selected[0].reimbursed = not selected[0].reimbursed
    else:
        for txn in selected:
            txn.reimbursed = True

    db.commit()
    return _render_view(request, db, view, page)


@router.post("/bulk/delete")
async def bulk_delete(request: Request, db: Session = Depends(get_db)):
    """Hard delete — no undo beyond re-importing/re-syncing (which, for a
    CSV or SimpleFin-sourced row, will recreate it if it's re-imported or
    still within a resync's lookback window, since dedup only skips what's
    still in the database). transfers.clear_pair_on_delete keeps a
    deleted transaction's transfer partner from being left pointing at a
    row that no longer exists, same as account_merge's discard path.
    """
    ids, view, page = await _bulk_request_state(request)
    selected = _selected_transactions(db, ids)

    for txn in selected:
        transfers.clear_pair_on_delete(db, txn)
        txn.tags = []
        db.delete(txn)
    db.commit()

    return _render_view(request, db, view, page)
