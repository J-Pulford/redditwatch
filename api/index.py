"""Vercel serverless entrypoint — backs the /api/* routes.

The dashboard itself (index.html, style.css, app.js) is served directly by
Vercel as static assets via vercel.json, so the front end renders regardless of
this function. This module only needs to handle /api/* requests.

IMPORTANT: serverless is not the ideal host for this app — the background
auto-refresh scheduler cannot run, and the SQLite database lives in the
per-instance, ephemeral /tmp (data and the reply cooldown/cap log do not
persist across cold starts). See README → "Deploying".
"""
import os
import sys

# Make the repo-root modules (app, config, db, ...) importable from this subdir.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import db
    from app import app  # the real FastAPI app

    # Vercel may not run ASGI lifespan events, so ensure the schema exists.
    db.init_db()
except Exception as _exc:  # never let a backend issue fail the whole deploy
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI()
    _message = f"Backend unavailable on this serverless deployment: {_exc}"

    @app.get("/{full_path:path}")
    @app.post("/{full_path:path}")
    def _unavailable(full_path: str):
        return JSONResponse(status_code=500, content={"detail": _message})
