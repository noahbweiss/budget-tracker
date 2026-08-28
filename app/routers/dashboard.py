"""Time-range dashboard views: daily / weekly / monthly / quarterly / yearly.

Each range shows one period at a time (today / this week / this month /
...), navigable via an `offset` query param (0 = current period, 1 = one
back, etc.) — see app.services.aggregation for why.

Renders HTML (see CLAUDE.md's frontend direction — this router never
returns JSON): a full page on a normal navigation, or just the inner
fragment when triggered by an HTMX range-switch/period-navigation
request, so the switcher can swap #dashboard-content in place instead of
reloading the page.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import aggregation
from app.templating import templates

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/{range_type}")
def get_dashboard(request: Request, range_type: str, offset: int = 0, db: Session = Depends(get_db)):
    if range_type not in aggregation.RANGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail={"error": f"unknown range_type '{range_type}'", "valid": list(aggregation.RANGE_TYPES)},
        )

    data = aggregation.get_period_dashboard(db, range_type, offset=offset)
    # Chart.js only needs the bucket series as JSON (via the |tojson filter
    # on the canvas's data-buckets attribute); Decimal isn't JSON-serializable
    # and float precision is plenty for a chart, so convert just for that.
    chart_buckets = [
        {"period": b["period"], "label": b["label"], "income": float(b["income"]), "spending": float(b["spending"])}
        for b in data["buckets"]
    ]
    context = {
        "valid_ranges": list(aggregation.RANGE_TYPES),
        "active_nav": "dashboard",
        **data,
        "buckets": chart_buckets,
    }

    template_name = "dashboard/_content.html" if request.headers.get("hx-request") == "true" else "dashboard/index.html"
    return templates.TemplateResponse(request, template_name, context)
