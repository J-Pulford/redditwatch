# Seshn · Reddit Listener

A small, self-hosted **Reddit listening + assisted-reply dashboard** for growing
[Seshn](https://seshn.app) organically. It finds Reddit posts and comments where
Seshn is genuinely relevant (musicians looking for collaborators, vocalists,
producers, mixing, etc.) and lets you reply helpfully — **you approve and send
every reply yourself**.

## Core principle: monitoring-first, human-in-the-loop

- The app **finds and surfaces** matching posts/comments — automatically (on a
  schedule) or on demand.
- **You approve and send every reply yourself** with a click. There is **no
  automated posting path** anywhere in the code.
- Replies go out through **your own authenticated Reddit account** via the
  official API (PRAW).
- A server-side **cooldown** and **daily cap** keep you human-paced and under
  spam filters.

## Stack

- **Python 3.11+**, single long-running process
- **FastAPI + Uvicorn** — serves the JSON API and the static dashboard
- **PRAW** — official Reddit API client (read + reply, with rate-limit backoff)
- **SQLite** (stdlib `sqlite3`) — zero-cost local DB at `./data/app.db`
- **APScheduler** — background auto-refresh job, in-process
- **anthropic** — optional "Draft with AI" reply suggestions
- **Frontend** — plain HTML/CSS/vanilla JS, no build step

## Setup

```bash
# 1. Create a virtualenv and install dependencies
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Configure secrets
cp .env.example .env
#    then edit .env (see below)

# 3. Run
uvicorn app:app --reload
```

Open the dashboard at **http://localhost:8000**.

## What to put in `.env`

**Required — Reddit (for monitoring *and* replies).** Create a *script* app at
<https://www.reddit.com/prefs/apps> (button: "create another app…", type:
`script`). Then fill:

| Variable | Where it comes from |
| --- | --- |
| `REDDIT_CLIENT_ID` | the string just under the app's name |
| `REDDIT_CLIENT_SECRET` | the field labelled **secret** |
| `REDDIT_USERNAME` | the Reddit account that will post replies |
| `REDDIT_PASSWORD` | that account's password |
| `REDDIT_USER_AGENT` | e.g. `seshn-listener/0.1 by u/your_username` |

**Optional — Anthropic** (`ANTHROPIC_API_KEY`): enables the **Draft with AI**
button. Without it, the button is simply hidden.

**Optional — Apify** (`APIFY_TOKEN`): an alternate, higher-volume source for
**posts only** (it cannot post replies). Without it, everything uses the
official Reddit API. To use it, also uncomment `apify-client` in
`requirements.txt` and `pip install` it.

> No secrets are ever written to the database. `.env` and `data/` are
> gitignored.

## Using the dashboard

- The **stats strip** shows matches found, new (unhandled) count, replies sent
  today (`X / cap`), and auto-refresh status + next run time.
- **Refresh now** pulls fresh matches from Reddit on demand.
- The **Feed** lists matches newest-first, with filters for subreddit, keyword,
  type (post/comment), and status. Click a row to open the **reply panel**.
- In the reply panel: optionally **Draft with AI**, always edit the text, then
  **Send reply** (disabled with a reason shown if the cooldown or daily cap is
  hit), or **Ignore** / **Save**.
- The **Settings** tab manages keywords and subreddits (with per-subreddit
  self-promo notes used as AI context), the auto-refresh toggle + interval, the
  reply cooldown, daily cap, and scan limits. Changes apply live.

## Seeded on first run

The database is seeded with musician/producer collaboration subreddits and a set
of collaboration-intent keywords (e.g. *"looking for a producer"*, *"need a
vocalist"*, *"royalty split"*, *"for hire"*). Edit these any time in Settings.

> The big subs (`makinghiphop`, `WeAreTheMusicMakers`) have strict self-promo
> rules and dedicated weekly collab/feedback threads — that's where replies are
> welcome. `shareyourmusic` / `ThisIsOurMusic` are looser. (Seed notes reflect
> this; the AI draft respects them.)

## Layout

```
app.py            FastAPI app: endpoints + static serving + lifespan
config.py         env loading, paths, feature flags
db.py             SQLite schema, seed, CRUD, reply gating
reddit_client.py  PRAW: refresh (fetch/match/dedup) + send_reply
ai.py             Anthropic "Draft with AI" (model constant at top)
prompts.py        editable system prompt
scheduler.py      APScheduler interval job
apify_source.py   optional post source (gated on APIFY_TOKEN)
static/           dashboard (index.html, style.css, app.js)
data/app.db       created at runtime (gitignored)
```

## Guardrails (enforced in code)

- No auto-posting. Every reply is an explicit per-item click. No bulk send.
- Acts only as the single authenticated user. No DMs, no voting, no
  multi-account logic.
- Cooldown + daily cap checked server-side on every send.
- Secrets never logged, never stored in the DB.
