"""Environment loading, paths, and feature flags.

All secrets come from the environment (via a local .env in development).
Nothing in here is ever written to the database.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# True when running on Vercel (its runtime sets VERCEL=1).
ON_VERCEL = bool(os.getenv("VERCEL"))

# --- Paths -----------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# On Vercel the deployment filesystem is read-only except /tmp, so the SQLite
# file must live there or the function crashes at import. NOTE: /tmp is
# per-instance and ephemeral — data does NOT persist across cold starts on
# serverless (see README → "Deploying"). Locally we use ./data which persists.
if ON_VERCEL:
    DATA_DIR = Path("/tmp/seshn-data")
else:
    DATA_DIR = BASE_DIR / "data"

try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    # Any read-only / sandboxed filesystem — fall back to /tmp.
    DATA_DIR = Path("/tmp/seshn-data")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = str(DATA_DIR / "app.db")

# --- Reddit (script app) ---------------------------------------------------
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USERNAME = os.getenv("REDDIT_USERNAME")
REDDIT_PASSWORD = os.getenv("REDDIT_PASSWORD")
REDDIT_USER_AGENT = os.getenv(
    "REDDIT_USER_AGENT", "seshn-listener/0.1 by u/unknown"
)

# --- Apify (optional) ------------------------------------------------------
APIFY_TOKEN = os.getenv("APIFY_TOKEN")


def reddit_configured() -> bool:
    """True only when every Reddit credential is present."""
    return all(
        [
            REDDIT_CLIENT_ID,
            REDDIT_CLIENT_SECRET,
            REDDIT_USERNAME,
            REDDIT_PASSWORD,
        ]
    )


def apify_enabled() -> bool:
    return bool(APIFY_TOKEN)
