import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.telegram import TelegramError, send_cards


def _ok_response():
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.json.return_value = {"ok": True, "result": {}}
    return resp


def _fake_png(path):
    path.write_bytes(b"fake-png-bytes")


def test_single_card_uses_send_photo(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    path = tmp_path / "a.png"
    _fake_png(path)

    with patch("src.telegram.requests.post", return_value=_ok_response()) as mock_post:
        send_cards("naval", "https://x.com/naval/status/1", [path])

    assert mock_post.call_args.args[0].endswith("/sendPhoto")
    assert "photo" in mock_post.call_args.kwargs["files"]
    assert (
        mock_post.call_args.kwargs["data"]["caption"]
        == '<b>@naval</b>\n<a href="https://x.com/naval/status/1">Read the full post on X →</a>'
    )


def test_multi_card_uses_send_media_group_with_caption_on_first_only(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    paths = [tmp_path / f"{i}.png" for i in range(3)]
    for p in paths:
        _fake_png(p)

    with patch("src.telegram.requests.post", return_value=_ok_response()) as mock_post:
        send_cards("naval", "https://x.com/naval/status/1", paths)

    assert mock_post.call_args.args[0].endswith("/sendMediaGroup")
    media = json.loads(mock_post.call_args.kwargs["data"]["media"])
    assert len(media) == 3
    assert "caption" in media[0]
    assert "caption" not in media[1]
    assert "caption" not in media[2]


def test_raises_on_ok_false_body_despite_200(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    path = tmp_path / "a.png"
    _fake_png(path)

    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.json.return_value = {"ok": False, "description": "chat not found"}

    with patch("src.telegram.requests.post", return_value=resp):
        with pytest.raises(TelegramError):
            send_cards("naval", "https://x.com/naval/status/1", [path])


def test_closes_file_handles_even_on_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    path = tmp_path / "a.png"
    _fake_png(path)

    resp = MagicMock()
    resp.ok = False
    resp.status_code = 500
    resp.json.return_value = {"ok": False}

    opened_handles = []
    real_open = open

    def tracking_open(p, mode="r", *a, **kw):
        h = real_open(p, mode, *a, **kw)
        opened_handles.append(h)
        return h

    with patch("builtins.open", side_effect=tracking_open):
        with patch("src.telegram.requests.post", return_value=resp):
            with pytest.raises(TelegramError):
                send_cards("naval", "https://x.com/naval/status/1", [path])

    assert opened_handles
    assert all(h.closed for h in opened_handles)
