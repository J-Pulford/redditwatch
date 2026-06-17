"""SQLite data layer: schema, first-run seed, CRUD, and reply-gating logic.

Every function opens its own short-lived connection. FastAPI runs sync route
handlers in a threadpool and APScheduler runs jobs in its own thread, so a
per-call connection avoids cross-thread sharing issues entirely. WAL mode plus
a busy timeout keep the occasional concurrent write safe.
"""
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone

import config

# --- Settings schema (key/value store, typed on read/write) ----------------
SETTINGS_DEFAULTS = {
    "auto_refresh_enabled": False,
    "refresh_interval_minutes": 15,
    "reply_cooldown_minutes": 20,
    "daily_reply_cap": 5,
    "comment_scan_limit": 100,
    "post_scan_limit": 50,
}
SETTINGS_TYPES = {
    "auto_refresh_enabled": bool,
    "refresh_interval_minutes": int,
    "reply_cooldown_minutes": int,
    "daily_reply_cap": int,
    "comment_scan_limit": int,
    "post_scan_limit": int,
}

# --- Starter config seeded on first run (from the build spec appendix) ------
STARTER_SUBREDDITS = [
    ("makinghiphop", "Strict self-promo rules. Replies are welcome in the "
                     "dedicated weekly collab/feedback threads — that's where "
                     "to engage. Avoid dropping links elsewhere."),
    ("WeAreTheMusicMakers", "Strict self-promo rules; use the weekly "
                            "collaboration/feedback threads. No unsolicited "
                            "promotion in regular posts."),
    ("musicproduction", ""),
    ("edmproduction", ""),
    ("Songwriting", ""),
    ("singing", ""),
    ("trapproduction", ""),
    ("futurebeats", ""),
    ("FL_Studio", ""),
    ("ableton", ""),
    ("Logic_Studio", ""),
    ("shareyourmusic", "Looser self-promo rules."),
    ("ThisIsOurMusic", "Looser self-promo rules."),
]

STARTER_KEYWORDS = [
    "looking for a producer", "need a producer", "looking for a vocalist",
    "need a vocalist", "looking for a singer", "need a singer", "need a hook",
    "need a topline", "looking for a topliner", "looking to collaborate",
    "open for collab", "open to collab", "anyone want to collab",
    "need someone to mix", "looking for a mixing engineer", "need a mix",
    "need it mixed", "looking for mastering", "looking for a songwriter",
    "need lyrics", "split royalties", "royalty split", "remote collaboration",
    "online collaboration", "session vocalist", "session musician", "for hire",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _conn():
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# --- Schema + seed ---------------------------------------------------------
def init_db() -> None:
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS keywords (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                phrase      TEXT NOT NULL,
                enabled     INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS subreddits (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                name             TEXT NOT NULL UNIQUE,
                enabled          INTEGER NOT NULL DEFAULT 1,
                self_promo_notes TEXT NOT NULL DEFAULT '',
                created_at       TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS items (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                reddit_fullname TEXT NOT NULL UNIQUE,
                type            TEXT NOT NULL,
                subreddit       TEXT NOT NULL,
                author          TEXT,
                title           TEXT,
                body_snippet    TEXT,
                permalink       TEXT,
                score           INTEGER DEFAULT 0,
                created_utc     REAL,
                matched_keyword TEXT,
                status          TEXT NOT NULL DEFAULT 'new',
                fetched_at      TEXT NOT NULL,
                replied_at      TEXT,
                reply_permalink TEXT
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS reply_log (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id   INTEGER,
                sent_at   REAL NOT NULL,
                permalink TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
            CREATE INDEX IF NOT EXISTS idx_items_created ON items(created_utc);
            """
        )
        _seed(c)


def _seed(c: sqlite3.Connection) -> None:
    # Settings: ensure every key exists (don't clobber user changes).
    for key, val in SETTINGS_DEFAULTS.items():
        sval = ("1" if val else "0") if isinstance(val, bool) else str(val)
        c.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
            (key, sval),
        )

    # Subreddits: seed only when the table is empty.
    if c.execute("SELECT COUNT(*) AS n FROM subreddits").fetchone()["n"] == 0:
        for name, notes in STARTER_SUBREDDITS:
            c.execute(
                "INSERT OR IGNORE INTO subreddits(name, enabled, "
                "self_promo_notes, created_at) VALUES (?, 1, ?, ?)",
                (name, notes, _now_iso()),
            )

    # Keywords: seed only when the table is empty.
    if c.execute("SELECT COUNT(*) AS n FROM keywords").fetchone()["n"] == 0:
        for phrase in STARTER_KEYWORDS:
            c.execute(
                "INSERT INTO keywords(phrase, enabled, created_at) "
                "VALUES (?, 1, ?)",
                (phrase, _now_iso()),
            )


# --- Settings --------------------------------------------------------------
def get_all_settings() -> dict:
    with _conn() as c:
        rows = c.execute("SELECT key, value FROM settings").fetchall()
    raw = {r["key"]: r["value"] for r in rows}
    out = {}
    for key, default in SETTINGS_DEFAULTS.items():
        v = raw.get(key)
        if v is None:
            out[key] = default
        elif SETTINGS_TYPES[key] is bool:
            out[key] = v in ("1", "true", "True")
        else:
            out[key] = int(v)
    return out


def update_settings(partial: dict) -> None:
    with _conn() as c:
        for key, val in partial.items():
            if key not in SETTINGS_DEFAULTS:
                continue
            if SETTINGS_TYPES[key] is bool:
                truthy = val is True or str(val).lower() in (
                    "1", "true", "yes", "on",
                )
                sval = "1" if truthy else "0"
            else:
                sval = str(int(val))
            c.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, sval),
            )


# --- Keywords --------------------------------------------------------------
def _kw(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "phrase": row["phrase"],
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
    }


def list_keywords() -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM keywords ORDER BY phrase COLLATE NOCASE"
        ).fetchall()
    return [_kw(r) for r in rows]


def get_keyword(kid: int):
    with _conn() as c:
        row = c.execute("SELECT * FROM keywords WHERE id=?", (kid,)).fetchone()
    return _kw(row) if row else None


def add_keyword(phrase: str, enabled: bool = True) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO keywords(phrase, enabled, created_at) VALUES (?, ?, ?)",
            (phrase.strip(), 1 if enabled else 0, _now_iso()),
        )
        return cur.lastrowid


def update_keyword(kid: int, phrase=None, enabled=None) -> None:
    with _conn() as c:
        if phrase is not None:
            c.execute(
                "UPDATE keywords SET phrase=? WHERE id=?", (phrase.strip(), kid)
            )
        if enabled is not None:
            c.execute(
                "UPDATE keywords SET enabled=? WHERE id=?",
                (1 if enabled else 0, kid),
            )


def delete_keyword(kid: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM keywords WHERE id=?", (kid,))


# --- Subreddits ------------------------------------------------------------
def _sub(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "enabled": bool(row["enabled"]),
        "self_promo_notes": row["self_promo_notes"],
        "created_at": row["created_at"],
    }


def list_subreddits() -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM subreddits ORDER BY name COLLATE NOCASE"
        ).fetchall()
    return [_sub(r) for r in rows]


def get_subreddit(sid: int):
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM subreddits WHERE id=?", (sid,)
        ).fetchone()
    return _sub(row) if row else None


def add_subreddit(name: str, self_promo_notes: str = "",
                  enabled: bool = True) -> int:
    name = name.strip().lstrip("r/").lstrip("/")
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO subreddits(name, enabled, self_promo_notes, "
            "created_at) VALUES (?, ?, ?, ?)",
            (name, 1 if enabled else 0, self_promo_notes, _now_iso()),
        )
        return cur.lastrowid


def update_subreddit(sid: int, name=None, self_promo_notes=None,
                     enabled=None) -> None:
    with _conn() as c:
        if name is not None:
            clean = name.strip().lstrip("r/").lstrip("/")
            c.execute("UPDATE subreddits SET name=? WHERE id=?", (clean, sid))
        if self_promo_notes is not None:
            c.execute(
                "UPDATE subreddits SET self_promo_notes=? WHERE id=?",
                (self_promo_notes, sid),
            )
        if enabled is not None:
            c.execute(
                "UPDATE subreddits SET enabled=? WHERE id=?",
                (1 if enabled else 0, sid),
            )


def delete_subreddit(sid: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM subreddits WHERE id=?", (sid,))


# --- Items -----------------------------------------------------------------
def insert_item(item: dict) -> bool:
    """Insert a matched item. Dedups on reddit_fullname (UNIQUE).

    Returns True if a new row was inserted, False if it already existed.
    """
    with _conn() as c:
        cur = c.execute(
            """
            INSERT OR IGNORE INTO items (
                reddit_fullname, type, subreddit, author, title, body_snippet,
                permalink, score, created_utc, matched_keyword, status,
                fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)
            """,
            (
                item["reddit_fullname"],
                item["type"],
                item["subreddit"],
                item.get("author"),
                item.get("title"),
                item.get("body_snippet"),
                item.get("permalink"),
                item.get("score", 0),
                item.get("created_utc"),
                item.get("matched_keyword"),
                _now_iso(),
            ),
        )
        return cur.rowcount > 0


def list_items(subreddit=None, keyword=None, status=None, type_=None,
               limit=200) -> list:
    query = "SELECT * FROM items WHERE 1=1"
    params = []
    if subreddit:
        query += " AND subreddit=?"
        params.append(subreddit)
    if keyword:
        query += " AND matched_keyword=?"
        params.append(keyword)
    if status:
        query += " AND status=?"
        params.append(status)
    if type_:
        query += " AND type=?"
        params.append(type_)
    query += " ORDER BY created_utc DESC LIMIT ?"
    params.append(limit)
    with _conn() as c:
        rows = c.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_item(item_id: int):
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM items WHERE id=?", (item_id,)
        ).fetchone()
    return dict(row) if row else None


def set_item_status(item_id: int, status: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE items SET status=? WHERE id=?", (status, item_id)
        )


def mark_replied(item_id: int, reply_permalink: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE items SET status='replied', replied_at=?, "
            "reply_permalink=? WHERE id=?",
            (_now_iso(), reply_permalink, item_id),
        )


def get_counts() -> dict:
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) AS n FROM items").fetchone()["n"]
        new = c.execute(
            "SELECT COUNT(*) AS n FROM items WHERE status='new'"
        ).fetchone()["n"]
    return {"total": total, "new": new}


# --- Reply log + gating ----------------------------------------------------
def add_reply_log(item_id: int, permalink: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO reply_log(item_id, sent_at, permalink) "
            "VALUES (?, ?, ?)",
            (item_id, time.time(), permalink),
        )


def get_reply_status() -> dict:
    """Compute whether a reply can be sent right now.

    Enforces the daily cap first, then the per-reply cooldown, using reply_log.
    """
    settings = get_all_settings()
    cap = settings["daily_reply_cap"]
    cooldown = settings["reply_cooldown_minutes"]

    now = time.time()
    now_dt = datetime.now(timezone.utc)
    day_start = now_dt.replace(
        hour=0, minute=0, second=0, microsecond=0
    ).timestamp()

    with _conn() as c:
        replies_today = c.execute(
            "SELECT COUNT(*) AS n FROM reply_log WHERE sent_at >= ?",
            (day_start,),
        ).fetchone()["n"]
        last_row = c.execute(
            "SELECT MAX(sent_at) AS last FROM reply_log"
        ).fetchone()
    last = last_row["last"]

    allowed = True
    reason = None
    next_available_in_min = None

    if replies_today >= cap:
        allowed = False
        reason = f"Daily cap reached ({replies_today}/{cap})"
    elif last is not None:
        elapsed_min = (now - last) / 60.0
        if elapsed_min < cooldown:
            remaining = max(1, int(round(cooldown - elapsed_min)))
            allowed = False
            reason = f"Cooldown: next reply available in {remaining} min"
            next_available_in_min = remaining

    return {
        "replies_today": replies_today,
        "daily_cap": cap,
        "cooldown_minutes": cooldown,
        "allowed": allowed,
        "reason": reason,
        "next_available_in_min": next_available_in_min,
    }
