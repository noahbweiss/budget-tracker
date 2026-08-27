# CLAUDE.md — Finance Tracker project context

Reference doc for working on this repo. Read this before making changes; update it when a documented decision changes.

## What this is

A local-first, open-source personal finance tracker (FastAPI + SQLite). Users track budget/spending/income across daily/weekly/monthly/quarterly/yearly views, with tiered bank connectivity: CSV/OFX import as the zero-config default, optional live sync via SimpleFin (user-supplied token, no bank credentials ever touch this app or a server we run). Goal is an open-source project anyone can one-click-run (Docker) and fork/extend, eventually packaged as a native desktop app via Tauri (`src-tauri/`, wraps the same FastAPI backend as a subprocess — no duplicated logic).

**Status:** backend skeleton is real and working; frontend is unbuilt. See `PLAN.md` for the roadmap.

## Architecture

```
app/
  main.py          FastAPI entrypoint — includes all routers, creates tables via
                    Base.metadata.create_all() at import time (TODO: Alembic later)
  config.py        pydantic-settings Settings, reads .env
  database.py      SQLAlchemy engine/session, Base, get_db() dependency
  models.py        Account, Category, Transaction (SQLAlchemy 2.0 typed style)
  routers/         HTTP layer — one file per feature area
  services/        Business logic, called from routers
  templates/        Jinja2 (empty — Phase 1)
  static/          CSS/JS/Chart.js (empty — Phase 1)
```

**Router/service split — preserve this convention:**
- **Routers** are the "shape stub" layer: real `APIRouter`s with real prefixes/tags, `Depends(get_db)` injected even before it's used, module docstring explaining intent + `TODO:` notes. Until implemented, a router returns placeholder success data (`200` + `{"note": "stub — not yet implemented"}` or empty list/dict) — routers should not raise `NotImplementedError` themselves.
- **Services** are the "logic stub" layer: functions/classes with real signatures that `raise NotImplementedError("...")` until implemented. This is where actual business logic (aggregation math, CSV parsing, SimpleFin API calls) lives, kept out of route handlers.

When implementing a stub, replace both halves together: make the service function actually work, then have the router call it instead of returning the placeholder.

## Data model (`app/models.py`)

- **Account** — `id`, `name`, `institution` (nullable), `account_type` (free string: "checking"/"savings"/"credit"/etc, no enum), `source` (default `"manual"`; `"manual"` or `"simplefin"`), `created_at`. Has many `transactions`.
- **Category** — `id`, `name` (unique), `kind` (default `"expense"`; `"income"` or `"expense"`). Has many `transactions`.
- **Transaction** — `id`, `account_id` (FK), `category_id` (nullable FK), `date`, `amount` (`Numeric(12,2)`, **signed**: positive = income, negative = spending — deliberate, simplifies aggregation math, keep this convention), `description`, `external_id` (nullable — dedup key for re-imports/syncs).

**Open decision:** where the SimpleFin access URL/token gets persisted is undecided — `config.py` currently has a single global `simplefin_access_url` setting (looks like a placeholder, doesn't fit multi-account use), and `simplefin.py`'s docstring flags "Settings or a dedicated table — TODO: decide which." Resolve this in Phase 5, not before — don't let it block earlier phases.

## Conventions

- SQLAlchemy 2.0 typed style throughout: `Mapped[...]` / `mapped_column(...)`, not the legacy `Column(...)` style.
- Full type hints everywhere, including `str | None` union syntax (Python 3.10+; base image is `python:3.12-slim`).
- Every module opens with a docstring stating purpose, and explicit `TODO:` comments for known-deferred work — keep adding these as you go, don't silently defer things.
- `requirements.txt` pins exact versions (`==`), no ranges.
- No linter/formatter configured yet (no ruff/black/mypy) — match existing style by hand until one is added.

## Frontend direction (Phase 1+)

**Stack: server-rendered Jinja2 + HTMX + Chart.js, vanilla CSS. No JS framework, no npm/build step.**

Rationale: keeps "clone and run" trivial for forkers (no `npm install`/build pipeline), and means the eventual Tauri desktop shell has nothing extra to package — it just points a webview at the same FastAPI server. `jinja2` and `python-multipart` are already in `requirements.txt` for this. Vendor HTMX and Chart.js as local static files rather than loading from a CDN — this app is meant to work fully offline/local-first.

**Visual style guideline (starting point, revise as pages get built):**
- Clean, minimal budgeting-app aesthetic — think restrained dashboard, not marketing-site flashy. Card-based layout for account summaries, category breakdowns, and totals.
- Chart.js for time-bucketed views (line/bar charts for spend & income over the selected range).
- Light + dark mode via CSS custom properties (`:root` variables, no separate stylesheets), respecting `prefers-color-scheme` by default.
- Color used sparingly and meaningfully: green/red reserved for income/expense signal (matching the model's signed-amount convention), not used decoratively elsewhere.
- HTMX handles the interactive bits (range switching, live-updating fragments) — server returns rendered HTML fragments, not JSON, to HTMX-triggered requests. (`dashboard.py`'s own TODO already anticipates this: "return an HTMX-rendered template fragment instead of raw JSON.")

## Known gaps

Resolved in Phase 0 (2026-08-27): git repo initialized, `.gitignore` added, `.env`/`.env.example` added (README's Docker instructions now include `cp .env.example .env`), `dashboard.py` returns a proper 400 via `HTTPException` for an invalid `range_type`.

Still open:
- No `AccountCreate`/`TransactionUpdate`-style Pydantic request schemas yet (only `simplefin.py`'s `ConnectRequest` exists) — `POST /accounts/` doesn't accept a body yet. Tracked as Phase 3 in `PLAN.md`.

## Working agreement

Claude drives implementation going forward. The user reviews changes and supplies feature requests and UI direction as they come up — check in on visual/UX decisions rather than guessing silently, but don't block on approval for straightforward backend/service implementation that follows the conventions above.
