"""App settings — not built yet.

Added as a header stub per the Figma wireframe's top-right profile/
settings area: a real route and a real rendered page, so the icon button
that links here isn't a dead link, but there's nothing configurable yet.
This is a genuinely local-first, single-user app with no login system —
whatever "settings" ends up meaning (theme override? default dashboard
range? SimpleFin connection management?) is unscoped; follow the
router/service split once it's decided, same as plan.py.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.templating import templates

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/")
def index(request: Request, db: Session = Depends(get_db)):
    context = {"active_nav": "settings"}
    return templates.TemplateResponse(request, "settings/index.html", context)
