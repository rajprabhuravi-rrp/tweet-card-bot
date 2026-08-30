"""GetXAPI adapter (BUILD.md §6). Isolates all GetXAPI-specific field names
and request shape so the rest of the codebase only depends on Post.

Endpoint (GET /twitter/user/tweets) and response schema confirmed against
GetXAPI's published OpenAPI spec (https://docs.getxapi.com/openapi.json),
not a live call — the configured GETXAPI_KEY had no remaining credits when
this was written. Re-run tools/check_api.py once credits are available to
confirm field names still match a real response.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime

import requests

BASE_URL = "https://api.getxapi.com"
TIMEOUT = 25
MAX_RETRIES = 2


@dataclass
class Post:
    id: str
    text: str
    created_at: datetime
    url: str


def _parse_created_at(raw: str) -> datetime:
    # e.g. "Tue Jan 13 12:56:12 +0000 2026"
    return datetime.strptime(raw, "%a %b %d %H:%M:%S %z %Y")


def _qualifying_posts(tweets: list[dict]) -> list[Post]:
    """Newest-first list of non-retweet, non-reply posts. GetXAPI (like the
    underlying X API) puts a user's pinned tweet first regardless of how old
    it is -- the rest of the list is genuinely reverse-chronological after
    that -- so this can't just take list order; it must sort by createdAt."""
    candidates = []
    for tweet in tweets:
        text = tweet.get("text", "")
        # ADAPT: GetXAPI's spec has no explicit "is retweet" field, so this
        # relies on the "RT @" text-prefix heuristic from BUILD.md §6.
        # Reconfirm once a live retweet is observed via tools/check_api.py.
        if text.startswith("RT @"):
            continue
        if tweet.get("isReply") or tweet.get("inReplyToId"):
            continue
        candidates.append(
            Post(
                id=tweet["id"],
                text=text,
                created_at=_parse_created_at(tweet["createdAt"]),
                url=tweet["url"],
            )
        )
    candidates.sort(key=lambda post: post.created_at, reverse=True)
    return candidates


def _select_post(tweets: list[dict]) -> Post | None:
    candidates = _qualifying_posts(tweets)
    return candidates[0] if candidates else None


def _request(handle: str) -> dict:
    url = f"{BASE_URL}/twitter/user/tweets"
    headers = {"Authorization": f"Bearer {os.environ['GETXAPI_KEY']}"}
    params = {"userName": handle}

    attempt = 0
    while True:
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=TIMEOUT)
        except (requests.Timeout, requests.ConnectionError):
            if attempt >= MAX_RETRIES:
                raise
            time.sleep(2**attempt)
            attempt += 1
            continue

        if resp.status_code >= 500:
            if attempt >= MAX_RETRIES:
                resp.raise_for_status()
            time.sleep(2**attempt)
            attempt += 1
            continue

        resp.raise_for_status()  # 4xx: never retried
        return resp.json()


def fetch_latest(handle: str) -> Post | None:
    """Most recent original, non-reply, non-retweet post for handle, or None."""
    data = _request(handle)
    return _select_post(data.get("tweets", []))


def fetch_recent(handle: str, limit: int = 5) -> list[Post]:
    """Up to `limit` most recent original, non-reply, non-retweet posts for
    handle, newest first. May return fewer than `limit` if not enough
    qualify in the single page GetXAPI returns."""
    data = _request(handle)
    return _qualifying_posts(data.get("tweets", []))[:limit]
