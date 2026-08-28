"""Shared Jinja2Templates instance.

Lives in its own module (rather than on app.main) so routers can import it
without a circular import — app.main imports the routers, so a router
importing back from app.main would fail.
"""
from decimal import Decimal
from pathlib import Path

from fastapi.templating import Jinja2Templates

APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=APP_DIR / "templates")


def format_money(value: Decimal | float) -> str:
    """Render a signed amount as "$12.34" or "-$12.34" — never "$-12.34",
    which "%.2f"|format on a negative value plus a literal "$" prefix would
    otherwise produce. Use this (`{{ amount | money }}`) anywhere a raw
    Transaction.amount (or other signed figure) is shown; totals that are
    already unsigned magnitudes (e.g. aggregation.py's totals/by_category)
    don't need it.
    """
    value = Decimal(value)
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):.2f}"


templates.env.filters["money"] = format_money
