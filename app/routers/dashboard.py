"""Time-range dashboard views: daily / weekly / monthly / quarterly / yearly.

Each range shows one period at a time (today / this week / this month /
...), navigable via an `offset` query param (0 = current period, 1 = one
back, etc.) — see app.services.aggregation for why. `account_id`
(optional) scopes the whole view to one account, via a persistent
sidebar (dashboard-only, not a global layout element — see CLAUDE.md's
UI conventions) built from the account list here.

Renders HTML (see CLAUDE.md's frontend direction — this router never
returns JSON): a full page on a normal navigation, or just the inner
fragment when triggered by an HTMX range-switch/period-navigation/
account-switch request, so the switcher can swap #dashboard-content in
place instead of reloading the page.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Account
from app.services import aggregation
from app.templating import templates

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/{range_type}")
def get_dashboard(
    request: Request,
    range_type: str,
    offset: int = 0,
    account_id: int | None = None,
    db: Session = Depends(get_db),
):
    if range_type not in aggregation.RANGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail={"error": f"unknown range_type '{range_type}'", "valid": list(aggregation.RANGE_TYPES)},
        )

    selected_account = None
    if account_id is not None:
        selected_account = db.get(Account, account_id)
        if selected_account is None:
            raise HTTPException(status_code=404, detail=f"account {account_id} not found")

    data = aggregation.get_period_dashboard(db, range_type, offset=offset, account_id=account_id)
    # Chart.js only needs the bucket series as JSON (via the |tojson filter
    # on the canvas's data-buckets attribute); Decimal isn't JSON-serializable
    # and float precision is plenty for a chart, so convert just for that.
    chart_buckets = [
        {"period": b["period"], "label": b["label"], "income": float(b["income"]), "spending": float(b["spending"])}
        for b in data["buckets"]
    ]
    chart_categories = [
        {"category": c["category"], "kind": c["kind"], "total": float(c["total"])} for c in data["by_category"]
    ]
    context = {
        "valid_ranges": list(aggregation.RANGE_TYPES),
        "accounts": db.query(Account).order_by(Account.name).all(),
        "selected_account": selected_account,
        "active_nav": "dashboard",
        **data,
        "buckets": chart_buckets,
        "chart_categories": chart_categories,
    }

    template_name = "dashboard/_content.html" if request.headers.get("hx-request") == "true" else "dashboard/index.html"
    return templates.TemplateResponse(request, template_name, context)
