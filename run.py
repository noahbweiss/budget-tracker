"""Local entrypoint: `python run.py` starts the dev server.

Docker uses the same app object (app.main:app) directly via uvicorn in
the Dockerfile CMD, so this file is only needed for the venv workflow.
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
