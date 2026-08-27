"""Shared Jinja2Templates instance.

Lives in its own module (rather than on app.main) so routers can import it
without a circular import — app.main imports the routers, so a router
importing back from app.main would fail.
"""
from pathlib import Path

from fastapi.templating import Jinja2Templates

APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=APP_DIR / "templates")
