import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.xapi import Post, _parse_created_at, _select_post, fetch_latest


def _tweet(
    id="1",
    text="hello",
    is_reply=False,
    in_reply_to=None,
    created="Tue Jan 13 12:56:12 +0000 2026",
    url="https://x.com/a/status/1",
):
    return {
        "id": id,
        "text": text,
        "isReply": is_reply,
        "inReplyToId": in_reply_to,
        "createdAt": created,
        "url": url,
    }


def test_parse_created_at():
    dt = _parse_created_at("Tue Jan 13 12:56:12 +0000 2026")
    assert dt == datetime(2026, 1, 13, 12, 56, 12, tzinfo=timezone.utc)


def test_select_post_skips_retweets():
    tweets = [_tweet(id="1", text="RT @someone: cool stuff"), _tweet(id="2", text="my own post")]
    assert _select_post(tweets).id == "2"


def test_select_post_skips_replies_via_is_reply_flag():
    tweets = [_tweet(id="1", text="@someone reply", is_reply=True), _tweet(id="2", text="my own post")]
    assert _select_post(tweets).id == "2"


def test_select_post_skips_replies_via_in_reply_to_id():
    tweets = [_tweet(id="1", text="looks like a reply", in_reply_to="999"), _tweet(id="2", text="my own post")]
    assert _select_post(tweets).id == "2"


def test_select_post_returns_none_when_nothing_qualifies():
    tweets = [_tweet(id="1", text="RT @a: x"), _tweet(id="2", text="@b reply", is_reply=True)]
    assert _select_post(tweets) is None


def test_select_post_picks_newest_by_created_at_not_list_order():
    # X's API puts a pinned tweet first regardless of how old it is; the
    # rest of the list is genuinely reverse-chronological after that.
    tweets = [
        _tweet(id="pinned-old", text="old pinned post", created="Thu Jul 16 18:54:49 +0000 2026"),
        _tweet(id="newest", text="actually the latest", created="Fri Aug 28 11:37:48 +0000 2026"),
        _tweet(id="older-still", text="older than newest", created="Tue Aug 25 14:54:50 +0000 2026"),
    ]
    assert _select_post(tweets).id == "newest"


def test_select_post_empty_list_returns_none():
    assert _select_post([]) is None


def test_fetch_latest_builds_post_from_first_qualifying_tweet(monkeypatch):
    monkeypatch.setenv("GETXAPI_KEY", "test-key")
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {"tweets": [_tweet(id="42", text="hi", url="https://x.com/a/status/42")]}
    fake_resp.raise_for_status = MagicMock()

    with patch("src.xapi.requests.get", return_value=fake_resp) as mock_get:
        post = fetch_latest("naval")

    assert post == Post(
        id="42", text="hi", created_at=_parse_created_at("Tue Jan 13 12:56:12 +0000 2026"), url="https://x.com/a/status/42"
    )
    called_kwargs = mock_get.call_args.kwargs
    assert called_kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert called_kwargs["params"] == {"userName": "naval"}
    assert called_kwargs["timeout"] == 25


def test_retries_on_timeout_then_succeeds(monkeypatch):
    monkeypatch.setenv("GETXAPI_KEY", "test-key")
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {"tweets": []}
    fake_resp.raise_for_status = MagicMock()

    with patch("src.xapi.time.sleep", return_value=None):
        with patch(
            "src.xapi.requests.get", side_effect=[requests.Timeout(), requests.Timeout(), fake_resp]
        ) as mock_get:
            post = fetch_latest("naval")

    assert post is None
    assert mock_get.call_count == 3


def test_gives_up_after_max_retries_on_repeated_timeout(monkeypatch):
    monkeypatch.setenv("GETXAPI_KEY", "test-key")
    with patch("src.xapi.time.sleep", return_value=None):
        with patch("src.xapi.requests.get", side_effect=requests.Timeout()) as mock_get:
            with pytest.raises(requests.Timeout):
                fetch_latest("naval")
    assert mock_get.call_count == 3  # initial attempt + 2 retries


def test_retries_on_5xx_then_succeeds(monkeypatch):
    monkeypatch.setenv("GETXAPI_KEY", "test-key")
    bad_resp = MagicMock()
    bad_resp.status_code = 503
    good_resp = MagicMock()
    good_resp.status_code = 200
    good_resp.json.return_value = {"tweets": []}
    good_resp.raise_for_status = MagicMock()

    with patch("src.xapi.time.sleep", return_value=None):
        with patch("src.xapi.requests.get", side_effect=[bad_resp, good_resp]) as mock_get:
            post = fetch_latest("naval")

    assert post is None
    assert mock_get.call_count == 2


def test_never_retries_4xx(monkeypatch):
    monkeypatch.setenv("GETXAPI_KEY", "test-key")
    bad_resp = MagicMock()
    bad_resp.status_code = 404
    bad_resp.raise_for_status.side_effect = requests.HTTPError("404")

    with patch("src.xapi.requests.get", return_value=bad_resp) as mock_get:
        with pytest.raises(requests.HTTPError):
            fetch_latest("naval")

    assert mock_get.call_count == 1
