"""Time-range dashboard views: daily / weekly / monthly / quarterly / yearly.

Renders HTML (see CLAUDE.md's frontend direction — this router never
returns JSON): a full page on a normal navigation, or just the inner
fragment when triggered by an HTMX range-switch request, so the switcher
can swap #dashboard-content in place instead of reloading the page.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import aggregation
from app.templating import templates

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

VALID_RANGES = {"daily", "weekly", "monthly", "quarterly", "yearly"}


@router.get("/{range_type}")
def get_dashboard(request: Request, range_type: str, db: Session = Depends(get_db)):
    if range_type not in VALID_RANGES:
        raise HTTPException(
            status_code=400,
            detail={"error": f"unknown range_type '{range_type}'", "valid": sorted(VALID_RANGES)},
        )

    data = aggregation.bucket_transactions(db, range_type)
    # Chart.js only needs the bucket series as JSON (via the |tojson filter
    # on the canvas's data-buckets attribute); Decimal isn't JSON-serializable
    # and float precision is plenty for a chart, so convert just for that.
    chart_buckets = [
        {"period": b["period"], "income": float(b["income"]), "spending": float(b["spending"])}
        for b in data["buckets"]
    ]
    context = {
        "range_type": range_type,
        "valid_ranges": sorted(VALID_RANGES),
        "active_nav": "dashboard",
        **data,
        "buckets": chart_buckets,
    }

    template_name = "dashboard/_content.html" if request.headers.get("hx-request") == "true" else "dashboard/index.html"
    return templates.TemplateResponse(request, template_name, context)
