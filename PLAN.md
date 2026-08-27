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

## Phase 2 — Dashboard, end-to-end

- [ ] Implement `app/services/aggregation.py`: `bucket_transactions(db, range_type, start=None, end=None)`. Resolve the quarterly-bucket TODO (`RANGE_TO_BUCKET["quarterly"]` currently `None` — SQLite has no native quarter format, derive it from month).
- [ ] Wire `app/routers/dashboard.py` to call `aggregation.bucket_transactions` instead of returning the stub.
- [ ] Dashboard template: range switcher (daily/weekly/monthly/quarterly/yearly) via HTMX, Chart.js spend/income chart, category-breakdown cards.
- [ ] Add tests covering real aggregation output (extends `tests/test_health.py`'s existing dashboard tests, which currently only assert stub shape).

## Phase 3 — Accounts & transactions pages

- [ ] Add `AccountCreate` / `AccountUpdate` and `TransactionUpdate` Pydantic schemas (none exist yet except `simplefin.py`'s `ConnectRequest`).
- [ ] Real CRUD in `app/routers/accounts.py` and `app/routers/transactions.py` (currently `GET` returns `[]`, `POST` returns a stub note).
- [ ] List/detail templates for accounts and transactions.
- [ ] Manual transaction categorization UI (assign/change `category_id`).

## Phase 4 — CSV/OFX import

- [ ] Implement `app/services/csv_importer.py`: `parse_csv(file_path)` and `parse_ofx(file_path)`. Per its docstring: per-bank column-mapping presets, with a manual-mapping fallback for unrecognized formats.
- [ ] Wire `app/routers/import_csv.py`'s `POST /import/csv` to actually call the importer and insert `Transaction` rows (dedup via `external_id`).
- [ ] Upload + column-mapping + preview UI (show parsed rows before committing the import).

## Phase 5 — SimpleFin sync

- [ ] Resolve the token-storage decision from `CLAUDE.md` (dedicated table vs. settings) — this blocks the rest of the phase.
- [ ] Implement `SimpleFinClient.exchange_setup_token` and `get_accounts_and_transactions` in `app/services/simplefin_client.py`.
- [ ] Wire `app/routers/simplefin.py`'s `/connect` and `/sync` endpoints.
- [ ] "Connect a bank" screen (paste setup token → confirm connected accounts).

## Later / unscheduled

- Alembic migrations (currently `Base.metadata.create_all()` at import time — fine until the schema needs to change without wiping data).
- Tauri desktop packaging (`src-tauri/` — deferred until core app + frontend are solid, per its own README).
- Linter/formatter setup (ruff/black) if the project wants one before accepting outside contributions.
