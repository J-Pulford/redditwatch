"""Vercel serverless entrypoint.

Vercel's Python runtime serves the ASGI ``app`` exported here. All routes are
rewritten to this function via ``vercel.json``.

IMPORTANT: serverless is not the ideal host for this app — the background
auto-refresh scheduler cannot run, and the SQLite database lives in the
per-instance, ephemeral ``/tmp`` (data and the reply cooldown/cap log do not
persist across cold starts). See README → "Deploying" for the recommended
always-on hosting options.
"""
import os
import sys

# Make the repo-root modules (app, config, db, ...) importable from this subdir.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
from app import app  # noqa: E402,F401  (Vercel serves this ASGI `app`)

# Vercel may not run ASGI lifespan events, so ensure the schema exists on import.
db.init_db()
