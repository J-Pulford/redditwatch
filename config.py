"""Environment loading, paths, and feature flags.

All secrets come from the environment (via a local .env in development).
Nothing in here is ever written to the database.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Paths -----------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = str(DATA_DIR / "app.db")
STATIC_DIR = BASE_DIR / "static"

# --- Reddit (script app) ---------------------------------------------------
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USERNAME = os.getenv("REDDIT_USERNAME")
REDDIT_PASSWORD = os.getenv("REDDIT_PASSWORD")
REDDIT_USER_AGENT = os.getenv(
    "REDDIT_USER_AGENT", "seshn-listener/0.1 by u/unknown"
)

# --- Anthropic (optional) --------------------------------------------------
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

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


def ai_enabled() -> bool:
    return bool(ANTHROPIC_API_KEY)


def apify_enabled() -> bool:
    return bool(APIFY_TOKEN)
