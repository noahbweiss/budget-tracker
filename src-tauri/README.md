# Tauri shell (not yet built)

This folder will hold the Tauri configuration that wraps the FastAPI
backend + web UI into a native desktop installer (Mac/Windows/Linux).

It intentionally contains no app logic of its own — it will just spawn
`app.main:app` as a local subprocess and point a native window at it,
so the Docker/venv/desktop versions all run identical backend code.

This is a later-stage step: it only gets built out once the core app
(models, routes, frontend) is working well via `python run.py` or
`docker compose up`.
