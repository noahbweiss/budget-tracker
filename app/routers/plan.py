"""Budget planning — not built yet.

Added as a nav stub per the Figma wireframe (see PLAN.md's UI-polish
notes): a real route and a real rendered page, so the nav item it
belongs to isn't a dead link, but no planning logic exists yet. What
"Plan" actually does (sample budgets per category? a monthly target vs.
actual comparison?) is a real feature to design, not a default to guess
at here — follow the router/service split once it's scoped: this file
stays the "shape stub," a services module gets added alongside it when
there's real logic to hold.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.templating import templates

router = APIRouter(prefix="/plan", tags=["plan"])


@router.get("/")
def index(request: Request, db: Session = Depends(get_db)):
    context = {"active_nav": "plan"}
    return templates.TemplateResponse(request, "plan/index.html", context)
