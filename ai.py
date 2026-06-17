"""Optional 'Draft with AI' reply suggestions via the Anthropic SDK.

The drafted text always lands in an editable textarea in the dashboard; it is
never auto-sent. This module is only reachable when ANTHROPIC_API_KEY is set.
"""
import config
import prompts

# Cheap + fast, fine for short replies. Swap to "claude-sonnet-4-6" for
# higher-quality drafts.
AI_MODEL = "claude-haiku-4-5-20251001"

_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def draft_reply(item: dict, subreddit_notes: str = "") -> str:
    """Draft a reply for a post/comment, given the target subreddit's notes."""
    if not config.ai_enabled():
        raise RuntimeError("ANTHROPIC_API_KEY is not set; AI drafting is off.")

    client = _get_client()

    kind = item.get("type", "post")
    title = item.get("title") or ("(no title — this is a comment)")
    body = item.get("body_snippet") or "(no body text)"
    notes = subreddit_notes.strip() or "none provided"

    user_content = (
        f"Subreddit: r/{item.get('subreddit', '')}\n"
        f"Subreddit self-promo rules / notes: {notes}\n\n"
        f"The Reddit {kind} I'm replying to:\n"
        f"Title: {title}\n"
        f"Body: {body}\n\n"
        "Draft a helpful reply that follows all the rules in your "
        "instructions. Output only the reply text."
    )

    # Haiku 4.5 does not support adaptive thinking or the effort parameter, so
    # this is a plain Messages request — exactly right for short drafts.
    response = client.messages.create(
        model=AI_MODEL,
        max_tokens=512,
        system=prompts.SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    text = "".join(
        block.text for block in response.content if block.type == "text"
    )
    return text.strip()
