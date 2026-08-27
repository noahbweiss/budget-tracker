"""Time-range dashboard views: daily / weekly / monthly / quarterly / yearly.

TODO: wire these up to app.services.aggregation and render templates once
the frontend work starts. For now these are placeholder JSON responses so
the route shapes exist and can be reviewed/tested independently of the UI.
"""
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

VALID_RANGES = {"daily", "weekly", "monthly", "quarterly", "yearly"}


@router.get("/{range_type}")
def get_dashboard(range_type: str):
    """Returns spending/income aggregated for the given range_type.

    TODO: replace stub with a call into services.aggregation, and return
    an HTMX-rendered template fragment instead of raw JSON once the
    frontend exists.
    """
    if range_type not in VALID_RANGES:
        raise HTTPException(
            status_code=400,
            detail={"error": f"unknown range_type '{range_type}'", "valid": sorted(VALID_RANGES)},
        )

    return {
        "range_type": range_type,
        "income": None,
        "spending": None,
        "by_category": [],
        "note": "stub — not yet implemented",
    }
