# PLAN.md — Roadmap

This is a working roadmap, not a locked spec — phases and details can shift as UI decisions get made along the way. See `CLAUDE.md` for architecture/conventions context behind these phases.

## Phase 0 — Infra foundation

Small, mechanical, unblocks everything else (including the README's documented "just clone and run" paths actually working).

- [x] `git init`, initial commit.
- [x] `.gitignore` — at minimum: `data/*.db`, `venv/`, `__pycache__/`, `.env`, `*.pyc`.
- [x] `.env.example` documenting `DATABASE_URL` and `SIMPLEFIN_ACCESS_URL` (both optional — defaults already exist in `config.py`), so `docker compose up` works out of the box per the README. (README's Docker instructions also updated to `cp .env.example .env` first, since `docker-compose.yml`'s `env_file` directive errors if `.env` is missing outright.)
- [x] Fix `app/routers/dashboard.py`: return HTTP 400 (not 200) for an unknown `range_type`, via `HTTPException`. Test updated in `tests/test_health.py`.

## Phase 1 — Frontend scaffolding ✅ (2026-08-27)

- [x] Mount `Jinja2Templates` and `StaticFiles` in `app/main.py` (paths anchored to `Path(__file__).parent`, not cwd).
- [x] Base layout template (`app/templates/base.html`): nav shell (Dashboard/Accounts/Transactions), light/dark CSS variables in `app/static/css/style.css` (`prefers-color-scheme` default, no manual toggle yet). Design direction: ledger-inspired — paper background + hairline rules, tabular-numeral monospace (`.figure`) reserved for money amounts, restrained slate-navy accent (not decorative green/red, which stay reserved for income/expense per the existing convention). No webfonts — system font stacks only, consistent with the offline-first principle.
- [x] Vendor HTMX 2.0.10 and Chart.js 4.5.1 into `app/static/vendor/` (see `VENDORED.md` there for versions/upgrade path).
- [x] Replace the root `/` stub with a real rendered page (`index.html`) — currently an honest empty-state home page (no accounts/transactions exist yet), with working links to the existing JSON endpoints and "coming soon" markers for CSV import / SimpleFin connect, which don't have GET pages yet.

Not done yet, deliberately deferred to later phases: dashboard template with real data/charts (Phase 2), manual dark-mode toggle (nice-to-have, not blocking).

## Phase 2 — Dashboard, end-to-end ✅ (2026-08-27)

- [x] Implement `app/services/aggregation.py`: `bucket_transactions(db, range_type, start=None, end=None)`. Bucketing happens in Python (not SQL strftime) — simpler to test, and resolves the quarterly TODO by deriving the quarter from the month directly rather than fighting SQLite's lack of a native quarter format. Covered by `tests/test_aggregation.py` (9 tests, TDD'd against an in-memory SQLite fixture in `tests/conftest.py`).
- [x] Wire `app/routers/dashboard.py` to call `aggregation.bucket_transactions`. The route now renders HTML only (no JSON mode) — a full page on a normal request, or just the `dashboard/_content.html` fragment when `HX-Request` is set, per the HTMX convention.
- [x] Dashboard templates (`app/templates/dashboard/index.html` + `_content.html`): range switcher (daily/weekly/monthly/quarterly/yearly) via `hx-get`/`hx-target`/`hx-swap`, Chart.js bar chart of income/spending per bucket, category-breakdown list with proportional bars. Chart colors are read from the CSS custom properties at render time (`app/static/js/dashboard.js`), so they follow the light/dark palette automatically; the chart is rebuilt on `htmx:afterSwap` since HTMX doesn't execute `<script>` tags from a swapped fragment.
- [x] Tests extended: `tests/test_health.py`'s dashboard tests now assert HTML (not the old JSON stub shape), plus a new test confirming the HTMX path returns a bare fragment (no `<!doctype html>`).

Caught during end-to-end verification (not by the unit tests, which never touched the template layer): `Decimal` isn't JSON-serializable, so the `|tojson` filter on the chart's `data-buckets` attribute 500'd against real data. Fixed by converting just the chart-bound bucket values to `float` at the router/template boundary — `aggregation.py` itself still returns `Decimal` throughout for precision. Worth remembering: **aggregation unit tests alone don't cover template rendering — always smoke-test a route against seeded data, not just an empty DB.**

## Phase 3 — Accounts & transactions pages ✅ (2026-08-27)

- [x] `AccountCreate`/`AccountUpdate` (in `routers/accounts.py`) and `TransactionUpdate` (in `routers/transactions.py`) Pydantic schemas, following `simplefin.py`'s existing precedent of defining request schemas inline in the router file rather than a shared schemas module.
- [x] Real CRUD in `app/routers/accounts.py` (Create/Read/Update — list, create, detail, edit) and `app/routers/transactions.py` (Read + category Update). Account create/update use plain POST + a 303 redirect (progressive enhancement, no JS required); transaction categorization uses HTMX (`hx-post` on a `<select>`, swaps just its own `<tr>`) since it's a frequent per-row action. Covered by 15 new tests (`tests/test_accounts.py`, `tests/test_transactions.py`) against an isolated in-memory DB — see the new `client` fixture in `tests/conftest.py`.
- [x] List/detail templates: `accounts/{index,_list,detail}.html`, `transactions/{index,_row}.html`.
- [x] Manual transaction categorization UI — the category `<select>` in every transaction row.
- [x] `app/services/categories.py`: `ensure_default_categories()`, called once at startup (`main.py`). Not originally scoped, but added because there was no way to create a category at all otherwise — the categorization UI would have had nothing to assign. Idempotent (only seeds an empty table), and documented as a stand-in until real category management exists.

**Deliberately not done:** account delete (hard-delete-vs-archive is a real design decision, not a default to guess at — revisit when actually needed); manual transaction creation (transactions are still meant to arrive via import/sync in Phase 4/5, per `TransactionUpdate` — not `TransactionCreate` — being the only schema this phase called for); inline form-validation UX (a bad submission gets a plain 422/400, not a re-rendered form with field errors).

Caught during end-to-end verification against seeded data (again, not by the router tests — same lesson as Phase 2): raw `"%.2f"|format(amount)` on a negative signed `Decimal` plus a literal `$` prefix rendered as `$-19.99` instead of `-$19.99`. Fixed with a shared `money` Jinja filter (`app/templating.py`) rather than patching each template — every future page that renders a raw transaction amount should use `{{ amount | money }}`, not hand-rolled `%.2f` formatting.

Also found: SQLite `:memory:` test databases are connection-scoped — `TestClient` runs sync route handlers in a worker thread, which can grab a different pooled connection than the one `Base.metadata.create_all()` ran DDL on, producing "no such table" errors. Fixed with `poolclass=StaticPool` in `tests/conftest.py`'s `db_session` fixture.

## Phase 4 — CSV/OFX import ✅ (2026-08-28)

- [x] `app/services/csv_importer.py`: `parse_csv()` and `parse_ofx()`. CSV mapping is a flexible auto-detector (`detect_mapping()` matches common header-name variants — "Date"/"Transaction Date"/"Posted Date", "Description"/"Memo"/"Payee"/"Name", single "Amount" or split "Debit"/"Credit") rather than a hardcoded per-bank preset list — there's no real bank sample data in this repo to build or verify named presets against, so an honest general detector plus manual override beats fabricated "Chase preset"/"Amex preset" support. Handles `$`/comma-formatted amounts, parenthesized negatives, and several date formats. `parse_ofx()` is a deliberately hand-rolled regex extractor (not a real SGML/XML parser — OFX 1.x tags often aren't closed) covering the common `<STMTTRN>` case; uses OFX's own `FITID` as the dedup id instead of a synthetic hash, since it's a real stable id CSV doesn't have. 26 tests (`tests/test_csv_importer.py`).
- [x] `app/routers/import_csv.py`: full upload → preview/mapping → confirm flow. The uploaded file is staged to a temp path (OS temp dir, not `data/`) keyed by a token; account_id, file_kind, and the confirmed column mapping round-trip through hidden form fields between steps — no new DB table or server-side session needed. Column-mapping adjustment is HTMX (live-updates the preview table on change, matching the "frequent small interaction → HTMX" convention); "Confirm import" and "Cancel" are plain form posts (matching the "whole-record action → plain form" convention). Duplicate rows (by `external_id`, scoped to the account) are skipped and reported, not silently dropped or double-inserted — verified live by uploading and confirming the same file twice. 12 tests (`tests/test_import_router.py`).
- [x] Upload + column-mapping + preview UI: `import/{index,preview,_preview_body,result}.html`. Preview is capped at 50 displayed rows (with a "…and N more" note) but still imports every row on confirm.

**Deliberately not done:** OFX edge cases beyond the standard single-account `<STMTTRN>` structure (multi-account files, unusual field ordering) — would need a real parser library (e.g. `ofxparse`), a new dependency not taken on for a format most banks only offer as a secondary export option to CSV. Per-row partial-failure handling — a single unparseable row fails the whole parse with one error message, rather than importing the good rows and flagging the bad ones individually.

Caught during end-to-end verification against a real uploaded file (same lesson every phase so far — router/unit tests didn't catch this since neither exercises the actual multipart upload path): none this time, actually — first phase where the live walkthrough (debit/credit auto-detection, `$`-prefixed amount, an intentional exact-duplicate row, full confirm → re-upload → dedup round trip) matched the tests exactly. Recorded here anyway, since the pattern of "verify against real data before calling it done" is what caught the Phase 2 and Phase 3 bugs and is worth keeping regardless of whether it finds something every time.

## Post-Phase-4 fixes — real-usage feedback (2026-08-28)

Once real data was actually imported and used, two things turned out to be wrong in ways the phase-by-phase build-out hadn't surfaced:

- [x] **Dashboard redesigned from "all-history chart" to "one period at a time."** The original Phase 2 design bucketed *every* transaction ever, by range_type granularity, into one long chart — so "daily" showed a bar for every single day the account had ever existed, not what a budgeting dashboard should default to. Replaced with `aggregation.get_period_dashboard(db, range_type, offset)`: each range shows the *current* period (today / this week / this month / this quarter / this year) by default, navigable via `offset` (prev/next buttons, 0 = current). Within a period, the chart breaks it into a finer sub-bucket — a month into its days, a quarter into its months, a week into its days — zero-filled for every sub-period, not just ones with transactions, so a sparse month doesn't look like it only has 3 days. "Daily" has no chart (nothing to sub-divide a single day into without time-of-day data) — just totals and category breakdown. The current period also shows a "Day X of Y" progress note (e.g. "Day 59 of 92" for a quarter). This is a full replacement of `bucket_transactions()`, not an addition alongside it — the old all-history behavior is exactly what was wrong. 26 tests (`tests/test_aggregation.py`, rewritten), heavy on date-math edge cases (quarter/year boundaries, leap years) since that's where the real risk was.
- [x] Nav/route-level tests updated (`tests/test_health.py`) for offset navigation and the daily-has-no-chart case.

## Phase 5 — SimpleFin sync

- [ ] Resolve the token-storage decision from `CLAUDE.md` (dedicated table vs. settings) — this blocks the rest of the phase.
- [ ] Implement `SimpleFinClient.exchange_setup_token` and `get_accounts_and_transactions` in `app/services/simplefin_client.py`.
- [ ] Wire `app/routers/simplefin.py`'s `/connect` and `/sync` endpoints.
- [ ] "Connect a bank" screen (paste setup token → confirm connected accounts).

## Later / unscheduled

- Alembic migrations (currently `Base.metadata.create_all()` at import time — fine until the schema needs to change without wiping data).
- Tauri desktop packaging (`src-tauri/` — deferred until core app + frontend are solid, per its own README).
- Linter/formatter setup (ruff/black) if the project wants one before accepting outside contributions.
