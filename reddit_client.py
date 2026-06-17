"""PRAW integration: the refresh (fetch/match/dedup) job and reply sending.

The same `refresh()` function backs both the manual "Refresh now" button and
the scheduled job. Replies are only ever sent through an explicit per-item
dashboard action — there is no automated posting path anywhere in this module.
"""
import logging

import config
import db

log = logging.getLogger("reddit")

_reddit = None


class ReplyBlocked(Exception):
    """Raised when a reply is blocked by the cooldown or daily cap."""


def get_reddit():
    """Lazily build and cache the authenticated PRAW client."""
    global _reddit
    if _reddit is None:
        if not config.reddit_configured():
            raise RuntimeError(
                "Reddit credentials are not configured. Fill the REDDIT_* "
                "values in your .env file."
            )
        import praw

        _reddit = praw.Reddit(
            client_id=config.REDDIT_CLIENT_ID,
            client_secret=config.REDDIT_CLIENT_SECRET,
            username=config.REDDIT_USERNAME,
            password=config.REDDIT_PASSWORD,
            user_agent=config.REDDIT_USER_AGENT,
        )
    return _reddit


def _match_keyword(text: str, keywords: list):
    """Return the first matching keyword phrase (case-insensitive), or None."""
    if not text:
        return None
    low = text.lower()
    for kw in keywords:
        if kw["phrase"].lower() in low:
            return kw["phrase"]
    return None


def _fullname_to_id(fullname: str) -> str:
    """'t3_abc' / 't1_abc' -> 'abc' (PRAW wants the bare base-36 id)."""
    return fullname.split("_", 1)[1] if "_" in fullname else fullname


def refresh() -> dict:
    """Fetch recent posts + comments for every enabled subreddit, match
    enabled keywords, and store new matches (deduped on reddit_fullname).

    Resilient per-subreddit: a failure on one subreddit is logged and skipped
    without aborting the rest.
    """
    settings = db.get_all_settings()
    post_limit = settings["post_scan_limit"]
    comment_limit = settings["comment_scan_limit"]
    keywords = [k for k in db.list_keywords() if k["enabled"]]
    subs = [s for s in db.list_subreddits() if s["enabled"]]

    result = {
        "subreddits_scanned": 0,
        "posts_scanned": 0,
        "comments_scanned": 0,
        "new_items": 0,
        "errors": [],
    }

    if not keywords or not subs:
        result["errors"].append(
            "Nothing to scan: enable at least one keyword and one subreddit."
        )
        return result

    # Optional Apify post source (gated). Comments always come from PRAW.
    apify_posts_by_sub = {}
    if config.apify_enabled():
        try:
            import apify_source

            if apify_source.available():
                apify_posts_by_sub = apify_source.fetch_posts(
                    [s["name"] for s in subs], post_limit
                )
        except Exception as exc:  # never let Apify break the PRAW path
            log.warning("Apify source failed, falling back to PRAW: %s", exc)
            apify_posts_by_sub = {}

    reddit = get_reddit()

    for sub in subs:
        name = sub["name"]
        try:
            subreddit = reddit.subreddit(name)

            # --- Posts ---
            if name in apify_posts_by_sub:
                posts = apify_posts_by_sub[name]
                for post in posts:
                    result["posts_scanned"] += 1
                    text = f"{post.get('title', '')}\n{post.get('selftext', '')}"
                    matched = _match_keyword(text, keywords)
                    if matched and db.insert_item(
                        {**post, "matched_keyword": matched}
                    ):
                        result["new_items"] += 1
            else:
                for submission in subreddit.new(limit=post_limit):
                    result["posts_scanned"] += 1
                    text = f"{submission.title}\n{submission.selftext or ''}"
                    matched = _match_keyword(text, keywords)
                    if matched and db.insert_item(
                        {
                            "reddit_fullname": submission.fullname,
                            "type": "post",
                            "subreddit": name,
                            "author": str(submission.author)
                            if submission.author else "[deleted]",
                            "title": submission.title,
                            "body_snippet": (submission.selftext or "")[:400],
                            "permalink": "https://reddit.com"
                            + submission.permalink,
                            "score": submission.score,
                            "created_utc": submission.created_utc,
                            "matched_keyword": matched,
                        }
                    ):
                        result["new_items"] += 1

            # --- Comments (PRAW only; keyword-matched locally) ---
            for comment in subreddit.comments(limit=comment_limit):
                result["comments_scanned"] += 1
                matched = _match_keyword(comment.body or "", keywords)
                if matched and db.insert_item(
                    {
                        "reddit_fullname": comment.fullname,
                        "type": "comment",
                        "subreddit": name,
                        "author": str(comment.author)
                        if comment.author else "[deleted]",
                        "title": None,
                        "body_snippet": (comment.body or "")[:400],
                        "permalink": "https://reddit.com" + comment.permalink,
                        "score": comment.score,
                        "created_utc": comment.created_utc,
                        "matched_keyword": matched,
                    }
                ):
                    result["new_items"] += 1

            result["subreddits_scanned"] += 1
        except Exception as exc:
            log.warning("Subreddit r/%s failed: %s", name, exc)
            result["errors"].append(f"r/{name}: {exc}")

    return result


def send_reply(item_id: int, text: str) -> dict:
    """Send a reply to a single item through the authenticated account.

    Enforces the cooldown and daily cap server-side. Raises ReplyBlocked with a
    user-facing reason if either is exceeded.
    """
    item = db.get_item(item_id)
    if item is None:
        raise ValueError("Item not found.")
    if item["status"] == "replied":
        raise ReplyBlocked("This item has already been replied to.")

    status = db.get_reply_status()
    if not status["allowed"]:
        raise ReplyBlocked(status["reason"])

    reddit = get_reddit()
    target_id = _fullname_to_id(item["reddit_fullname"])
    if item["type"] == "post":
        target = reddit.submission(id=target_id)
    else:
        target = reddit.comment(id=target_id)

    reply = target.reply(text)
    permalink = "https://reddit.com" + reply.permalink

    db.mark_replied(item_id, permalink)
    db.add_reply_log(item_id, permalink)
    return {"ok": True, "reply_permalink": permalink}
