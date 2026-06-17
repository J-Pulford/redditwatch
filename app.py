"""FastAPI app: JSON API + static dashboard, plus the background scheduler.

Run with:  uvicorn app:app --reload
Dashboard: http://localhost:8000
"""
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import ai
import config
import db
import reddit_client
import scheduler

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    scheduler.init(reddit_client.refresh)
    yield
    scheduler.shutdown()


app = FastAPI(title="Seshn Reddit Listener", lifespan=lifespan)


# --- Request bodies --------------------------------------------------------
class ReplyBody(BaseModel):
    text: str


class StatusBody(BaseModel):
    status: str


class DraftBody(BaseModel):
    item_id: int


class KeywordCreate(BaseModel):
    phrase: str
    enabled: bool = True


class KeywordUpdate(BaseModel):
    phrase: Optional[str] = None
    enabled: Optional[bool] = None


class SubredditCreate(BaseModel):
    name: str
    self_promo_notes: str = ""
    enabled: bool = True


class SubredditUpdate(BaseModel):
    name: Optional[str] = None
    self_promo_notes: Optional[str] = None
    enabled: Optional[bool] = None


VALID_STATUSES = {"new", "replied", "ignored", "saved"}


# --- Static dashboard ------------------------------------------------------
app.mount(
    "/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static"
)


@app.get("/")
def index():
    return FileResponse(str(config.STATIC_DIR / "index.html"))


# --- Meta ------------------------------------------------------------------
@app.get("/api/config")
def get_config():
    return {
        "ai_enabled": config.ai_enabled(),
        "apify_enabled": config.apify_enabled(),
        "reddit_configured": config.reddit_configured(),
    }


@app.get("/api/stats")
def stats():
    rs = db.get_reply_status()
    counts = db.get_counts()
    settings = db.get_all_settings()
    return {
        "matches_total": counts["total"],
        "new_count": counts["new"],
        "replies_today": rs["replies_today"],
        "daily_cap": rs["daily_cap"],
        "reply_allowed": rs["allowed"],
        "reply_block_reason": rs["reason"],
        "auto_refresh_enabled": settings["auto_refresh_enabled"],
        "next_run": scheduler.next_run_time(),
    }


# --- Feed ------------------------------------------------------------------
@app.get("/api/items")
def items(
    subreddit: Optional[str] = None,
    keyword: Optional[str] = None,
    status: Optional[str] = None,
    type: Optional[str] = None,
    limit: int = 200,
):
    return db.list_items(subreddit, keyword, status, type, limit)


@app.post("/api/refresh")
def refresh_now():
    try:
        return reddit_client.refresh()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/items/{item_id}/reply")
def reply(item_id: int, body: ReplyBody):
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Reply text is empty.")
    try:
        return reddit_client.send_reply(item_id, text)
    except reddit_client.ReplyBlocked as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Reddit error: {exc}")


@app.post("/api/items/{item_id}/status")
def set_status(item_id: int, body: StatusBody):
    if body.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status.")
    if db.get_item(item_id) is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    db.set_item_status(item_id, body.status)
    return {"ok": True, "status": body.status}


# --- AI draft --------------------------------------------------------------
@app.post("/api/draft")
def draft(body: DraftBody):
    if not config.ai_enabled():
        raise HTTPException(
            status_code=400,
            detail="AI drafting is disabled (ANTHROPIC_API_KEY not set).",
        )
    item = db.get_item(body.item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    notes = db.get_subreddit_notes(item["subreddit"])
    try:
        return {"draft": ai.draft_reply(item, notes)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI error: {exc}")


# --- Settings --------------------------------------------------------------
@app.get("/api/settings")
def get_settings():
    return {
        "settings": db.get_all_settings(),
        "keywords": db.list_keywords(),
        "subreddits": db.list_subreddits(),
    }


@app.put("/api/settings")
def put_settings(payload: dict = Body(...)):
    db.update_settings(payload)
    scheduler.apply_settings()  # reschedule live, no restart
    return db.get_all_settings()


# --- Keywords CRUD ---------------------------------------------------------
@app.get("/api/keywords")
def keywords():
    return db.list_keywords()


@app.post("/api/keywords")
def create_keyword(body: KeywordCreate):
    phrase = body.phrase.strip()
    if not phrase:
        raise HTTPException(status_code=400, detail="Phrase is empty.")
    kid = db.add_keyword(phrase, body.enabled)
    return db.get_keyword(kid)


@app.put("/api/keywords/{kid}")
def edit_keyword(kid: int, body: KeywordUpdate):
    if db.get_keyword(kid) is None:
        raise HTTPException(status_code=404, detail="Keyword not found.")
    db.update_keyword(kid, body.phrase, body.enabled)
    return db.get_keyword(kid)


@app.delete("/api/keywords/{kid}")
def remove_keyword(kid: int):
    if db.get_keyword(kid) is None:
        raise HTTPException(status_code=404, detail="Keyword not found.")
    db.delete_keyword(kid)
    return {"ok": True}


# --- Subreddits CRUD -------------------------------------------------------
@app.get("/api/subreddits")
def subreddits():
    return db.list_subreddits()


@app.post("/api/subreddits")
def create_subreddit(body: SubredditCreate):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is empty.")
    try:
        sid = db.add_subreddit(name, body.self_promo_notes, body.enabled)
    except Exception:
        raise HTTPException(
            status_code=409, detail="That subreddit is already in the list."
        )
    return db.get_subreddit(sid)


@app.put("/api/subreddits/{sid}")
def edit_subreddit(sid: int, body: SubredditUpdate):
    if db.get_subreddit(sid) is None:
        raise HTTPException(status_code=404, detail="Subreddit not found.")
    db.update_subreddit(sid, body.name, body.self_promo_notes, body.enabled)
    return db.get_subreddit(sid)


@app.delete("/api/subreddits/{sid}")
def remove_subreddit(sid: int):
    if db.get_subreddit(sid) is None:
        raise HTTPException(status_code=404, detail="Subreddit not found.")
    db.delete_subreddit(sid)
    return {"ok": True}
