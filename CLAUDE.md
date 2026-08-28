# CLAUDE.md — Finance Tracker project context

Reference doc for working on this repo. Read this before making changes; update it when a documented decision changes.

## What this is

A local-first, open-source personal finance tracker (FastAPI + SQLite). Users track budget/spending/income across daily/weekly/monthly/quarterly/yearly views, with tiered bank connectivity: CSV/OFX import as the zero-config default, optional live sync via SimpleFin (user-supplied token, no bank credentials ever touch this app or a server we run). Goal is an open-source project anyone can one-click-run (Docker) and fork/extend, eventually packaged as a native desktop app via Tauri (`src-tauri/`, wraps the same FastAPI backend as a subprocess — no duplicated logic).

**Status:** backend skeleton is real and working. Dashboard (Phase 2), Accounts/Transactions (Phase 3), and CSV/OFX import (Phase 4) are fully wired end-to-end. SimpleFin sync is still a stub — CSV/OFX import is now a real way to get transactions in (alongside manual seeding), so a fresh install only stays empty until the user imports a statement. See `PLAN.md` for the roadmap.

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
  templates/        Jinja2 — base.html (layout/nav) + page templates
  static/          css/style.css (design tokens + base styles), vendor/ (htmx, Chart.js)
```

**Router/service split — preserve this convention:**
- **Routers** are the "shape stub" layer: real `APIRouter`s with real prefixes/tags, `Depends(get_db)` injected even before it's used, module docstring explaining intent + `TODO:` notes. Until implemented, a router returns placeholder success data (`200` + `{"note": "stub — not yet implemented"}` or empty list/dict) — routers should not raise `NotImplementedError` themselves.
- **Services** are the "logic stub" layer: functions/classes with real signatures that `raise NotImplementedError("...")` until implemented. This is where actual business logic (aggregation math, CSV parsing, SimpleFin API calls) lives, kept out of route handlers.

When implementing a stub, replace both halves together: make the service function actually work, then have the router call it instead of returning the placeholder.

**HTML-rendering pattern (established in `routers/dashboard.py`, Phase 2):** a router that renders UI imports `templates` from `app.templating` (not from `app.main` — that would be a circular import, since `main.py` imports the routers). It checks `request.headers.get("hx-request") == "true"` to decide whether to return a full page (extends `base.html`) or just the inner fragment for an HTMX swap target. Keep `<script>` tags out of swapped fragments — HTMX doesn't execute scripts injected via a swap — so any JS that needs to react to new content (e.g. rebuilding a Chart.js chart) belongs in a page-level script listening for `htmx:afterSwap`, not inside the fragment template itself.

**When to use HTMX vs. a plain form (established in Phase 3):** not everything needs to be an HTMX partial. Infrequent, whole-record actions (create/edit an account) use a plain `<form method="post">` + a 303 redirect — works without JS, simplest code. Frequent, per-row actions (categorizing a transaction) use HTMX (`hx-post` + `hx-target="closest tr"` + `hx-swap="outerHTML"`) so there's no full-page reload. Pick based on frequency/graininess of the action, not by default.

**Rendering money in a template:** always use the `money` filter (`{{ amount | money }}`, registered in `app.templating`), never hand-rolled `"%.2f"|format(...)` with a literal `$` — that produces `$-19.99` instead of `-$19.99` for negative values. Exception: values that are already-unsigned magnitudes (e.g. `aggregation.py`'s `totals.income`/`totals.spending`/`by_category[].total`, which are deliberately abs()'d) don't need it, though using it anyway is harmless.

**Dashboard = one period at a time, not all-history (redesigned post-Phase-4, per real usage feedback):** `GET /dashboard/{range_type}?offset=N` shows the *current* period at `offset=0` (today / this week / this month / this quarter / this year), stepping back one period per `offset` increment — never a chart spanning an account's entire history. `aggregation.get_period_dashboard()` is the one function that computes this; don't reintroduce an "all transactions bucketed by granularity" path. If you add a new range-shaped feature, it should default to the current period too, not "everything."

**Multi-step flows without server-side session state (established in `routers/import_csv.py`, Phase 4):** the CSV import flow (upload → adjust mapping → confirm) needs state to survive multiple requests, but there's no session/pending-import table. Instead: the uploaded file is staged to a token-named temp file (OS temp dir — see `IMPORT_TMP_DIR`, deliberately outside `data/`, which is for real app data, not transient staging), and every other piece of state (account_id, file_kind, the column mapping) round-trips through hidden form fields on each step's response. Reach for this pattern before adding a new DB table just to hold "in-progress" state.

## Data model (`app/models.py`)

- **Account** — `id`, `name`, `institution` (nullable), `account_type` (free string: "checking"/"savings"/"credit"/etc, no enum), `source` (default `"manual"`; `"manual"` or `"simplefin"`), `created_at`. Has many `transactions`.
- **Category** — `id`, `name` (unique), `kind` (default `"expense"`; `"income"` or `"expense"`). Has many `transactions`. No category-management UI exists yet — `app/services/categories.py::ensure_default_categories()` seeds a fixed starter set on first startup (idempotent, only fires on an empty table) so the categorization UI has something to offer.
- **Transaction** — `id`, `account_id` (FK), `category_id` (nullable FK), `date`, `amount` (`Numeric(12,2)`, **signed**: positive = income, negative = spending — deliberate, simplifies aggregation math, keep this convention), `description`, `external_id` (nullable — dedup key for re-imports/syncs).

**Open decision:** where the SimpleFin access URL/token gets persisted is undecided — `config.py` currently has a single global `simplefin_access_url` setting (looks like a placeholder, doesn't fit multi-account use), and `simplefin.py`'s docstring flags "Settings or a dedicated table — TODO: decide which." Resolve this in Phase 5, not before — don't let it block earlier phases.

`external_id` in practice: OFX imports use the bank's own `FITID` (a real stable id). CSV imports don't have one, so `csv_importer.py` derives a hash of (date, amount, description) — meaning two genuinely different transactions that happen to share the exact same date/amount/description would collide; within a single file this is disambiguated with a counter suffix, but a stray same-day/same-amount/same-description transaction reappearing across two *separate* CSV exports could still be mistaken for a duplicate and skipped on reimport. A real limitation of CSV lacking stable ids, not a bug to "fix" without a better signal to key off.

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
- Chart.js for spend/income within the selected period — see the dashboard convention below for what "period" means.
- Light + dark mode via CSS custom properties (`:root` variables, no separate stylesheets), respecting `prefers-color-scheme` by default.
- Color used sparingly and meaningfully: green/red reserved for income/expense signal (matching the model's signed-amount convention), not used decoratively elsewhere.
- HTMX handles the interactive bits (range switching, live-updating fragments) — server returns rendered HTML fragments, not JSON, to HTMX-triggered requests. (`dashboard.py`'s own TODO already anticipates this: "return an HTMX-rendered template fragment instead of raw JSON.")

## Known gaps

Resolved in Phase 0 (2026-08-27): git repo initialized, `.gitignore` added, `.env`/`.env.example` added (README's Docker instructions now include `cp .env.example .env`), `dashboard.py` returns a proper 400 via `HTTPException` for an invalid `range_type`.

Resolved in Phase 3 (2026-08-27): `AccountCreate`/`AccountUpdate`/`TransactionUpdate` schemas now exist; accounts/transactions have real CRUD (accounts: create/read/update; transactions: read + category update).

Resolved in Phase 4 (2026-08-28): CSV/OFX import is real — `csv_importer.py` parses both formats, `routers/import_csv.py` has a full upload → preview/mapping → confirm flow with dedup.

Still open:
- Account delete isn't implemented (hard-delete-vs-archive is a real decision, deferred until needed).
- No way to manually create a single transaction — by design for now, transactions arrive via import (Phase 4, done) or sync (Phase 5, not yet).
- No category-management UI — categories come from a fixed default set (`app/services/categories.py`).
- OFX parsing is a pragmatic regex extractor for the standard single-account `<STMTTRN>` structure, not a full SGML/XML parser — see `csv_importer.py`'s `parse_ofx` docstring for what it doesn't handle.

## Working agreement

Claude drives implementation going forward. The user reviews changes and supplies feature requests and UI direction as they come up — check in on visual/UX decisions rather than guessing silently, but don't block on approval for straightforward backend/service implementation that follows the conventions above.
