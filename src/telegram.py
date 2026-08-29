"""Telegram delivery: sendPhoto for single cards, sendMediaGroup for albums
(BUILD.md §7). Never sends a multi-card post as separate sendPhoto calls --
another user's post could land between them and break the sequence.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import requests

TIMEOUT = 25


class TelegramError(Exception):
    """Raised on a non-2xx response or a 200 with body {"ok": false}."""


def _base_url() -> str:
    return f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}"


def _check(resp: requests.Response) -> dict:
    body = resp.json()
    if not resp.ok or not body.get("ok"):
        raise TelegramError(f"Telegram API error ({resp.status_code}): {body}")
    return body


def _caption(handle: str, url: str) -> str:
    return f'<b>@{handle}</b>\n<a href="{url}">Read the full post on X →</a>'


def send_cards(handle: str, url: str, paths: list[Path]) -> None:
    """Sends 1 card via sendPhoto, or 2-4 via sendMediaGroup (one album)."""
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    caption = _caption(handle, url)

    if len(paths) == 1:
        _send_photo(chat_id, paths[0], caption)
    else:
        _send_media_group(chat_id, paths, caption)


def _send_photo(chat_id: str, path: Path, caption: str) -> None:
    fh = open(path, "rb")
    try:
        resp = requests.post(
            f"{_base_url()}/sendPhoto",
            data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
            files={"photo": fh},
            timeout=TIMEOUT,
        )
        _check(resp)
    finally:
        fh.close()


def _send_media_group(chat_id: str, paths: list[Path], caption: str) -> None:
    handles = [open(p, "rb") for p in paths]
    try:
        media = []
        files = {}
        for i, fh in enumerate(handles):
            attach_name = f"file{i}"
            item = {"type": "photo", "media": f"attach://{attach_name}"}
            if i == 0:
                item["caption"] = caption
                item["parse_mode"] = "HTML"
            media.append(item)
            files[attach_name] = fh

        resp = requests.post(
            f"{_base_url()}/sendMediaGroup",
            data={"chat_id": chat_id, "media": json.dumps(media)},
            files=files,
            timeout=TIMEOUT,
        )
        _check(resp)
    finally:
        for fh in handles:
            fh.close()
