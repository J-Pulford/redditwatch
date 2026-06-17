"""Optional Apify-based post source.

Only used when APIFY_TOKEN is set AND the apify-client package is installed.
Apify can scrape posts at higher volume than the official API, but it CANNOT
post replies — replies always go through PRAW (see reddit_client.send_reply).

This is an experimental swap-in. The actor and its output field names may need
adjusting for your chosen Apify actor; refresh() falls back to PRAW if anything
here raises. Comments are always fetched via PRAW regardless.
"""
import logging

import config

log = logging.getLogger("apify")

# A public Reddit scraper actor. Swap for whichever actor you prefer.
ACTOR_ID = "trudax/reddit-scraper-lite"


def available() -> bool:
    """True only when a token is set and the client library is importable."""
    if not config.apify_enabled():
        return False
    try:
        import apify_client  # noqa: F401
        return True
    except ImportError:
        log.warning(
            "APIFY_TOKEN is set but apify-client is not installed; "
            "uncomment it in requirements.txt to use the Apify source."
        )
        return False


def fetch_posts(subreddit_names: list, limit: int) -> dict:
    """Return {subreddit_name: [normalized post dicts]} for the given subs.

    Each post dict matches the shape reddit_client.insert_item expects
    (minus matched_keyword, which the caller fills in after matching).
    """
    from apify_client import ApifyClient

    client = ApifyClient(config.APIFY_TOKEN)
    run_input = {
        "startUrls": [
            {"url": f"https://www.reddit.com/r/{name}/new/"}
            for name in subreddit_names
        ],
        "maxItems": limit * len(subreddit_names),
        "type": "posts",
        "sort": "new",
    }
    run = client.actor(ACTOR_ID).call(run_input=run_input)

    by_sub = {name: [] for name in subreddit_names}
    dataset = client.dataset(run["defaultDatasetId"]).iterate_items()
    for raw in dataset:
        sub = (raw.get("communityName") or raw.get("subreddit") or "").lstrip(
            "r/"
        ).lstrip("/")
        if sub not in by_sub:
            # Match case-insensitively against the requested set.
            match = next(
                (n for n in subreddit_names if n.lower() == sub.lower()), None
            )
            if match is None:
                continue
            sub = match
        post_id = raw.get("id") or raw.get("parsedId") or ""
        fullname = post_id if post_id.startswith("t3_") else f"t3_{post_id}"
        by_sub[sub].append(
            {
                "reddit_fullname": fullname,
                "type": "post",
                "subreddit": sub,
                "author": raw.get("username") or raw.get("author")
                or "[unknown]",
                "title": raw.get("title", ""),
                "selftext": raw.get("body") or raw.get("text") or "",
                "body_snippet": (raw.get("body") or raw.get("text") or "")[:400],
                "permalink": raw.get("url", ""),
                "score": raw.get("upVotes") or raw.get("score") or 0,
                "created_utc": raw.get("createdTimestamp"),
            }
        )
    return by_sub
