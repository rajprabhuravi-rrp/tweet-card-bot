"""Fetch, render, and deliver new posts for a rotating slice of users
(BUILD.md §8-9). Entry point: `python -m src.pipeline`.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.compose import Measurer, Renderer, plan_parts, template_data_uri
from src.config import UserConfig, load_config
from src.telegram import send_cards
from src.xapi import Post, fetch_latest

USERS_YAML = ROOT / "users.yaml"
STATE_PATH = ROOT / "state.json"
OUT_DIR = ROOT / "out"
OVERLAY_PATH = ROOT / "overlay.html"

MAX_WORKERS = 8


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"cursor": 0, "users": {}}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def select_slice(handles: list[str], cursor: int, users_per_run: int | None) -> tuple[list[str], int]:
    """Returns (handles-to-check-this-run, next-cursor), wrapping around the roster."""
    if not handles:
        return [], 0
    if users_per_run is None or users_per_run >= len(handles):
        return list(handles), 0

    n = len(handles)
    start = cursor % n
    selected = [handles[(start + i) % n] for i in range(users_per_run)]
    next_cursor = (start + users_per_run) % n
    return selected, next_cursor


def fetch_all(handles: list[str]) -> dict[str, Post | None | Exception]:
    """Concurrently fetches each handle's latest post. A failure for one
    handle is captured, not raised, so it can never block the others
    (BUILD.md §12.7)."""
    results: dict[str, Post | None | Exception] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_to_handle = {pool.submit(fetch_latest, h): h for h in handles}
        for future in as_completed(future_to_handle):
            handle = future_to_handle[future]
            try:
                results[handle] = future.result()
            except Exception as e:  # noqa: BLE001 - isolate one user's failure from the rest
                results[handle] = e
    return results


def render_post(renderer: Renderer, measurer: Measurer, user: UserConfig, post: Post) -> list[Path]:
    plan = plan_parts(measurer, post.text, user.zone, user.accent)
    template_uri = template_data_uri(user.template)
    n = len(plan.parts)
    OUT_DIR.mkdir(exist_ok=True)
    paths = []
    for i, part in enumerate(plan.parts, start=1):
        badge = (i, n) if n > 1 else None
        out_path = OUT_DIR / f"{user.handle}_{post.id}_{i}of{n}.png"
        renderer.render(template_uri, user.zone, part, badge, user.accent, user.text_color, out_path)
        paths.append(out_path)
    return paths


def run() -> int:
    config = load_config(USERS_YAML)
    state = load_state()
    state.setdefault("users", {})
    handles = [u.handle for u in config.enabled_users()]

    selected_handles, next_cursor = select_slice(handles, state.get("cursor", 0), config.users_per_run)
    state["cursor"] = next_cursor
    save_state(state)
    print(f"checking {len(selected_handles)}/{len(handles)} users this run: {selected_handles}")

    if not selected_handles:
        return 0

    fetched = fetch_all(selected_handles)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        # Separate pages: Measurer and Renderer each navigate their page to
        # different HTML, so sharing one page across the per-user loop would
        # have each measurement clobbered by the previous render (or vice
        # versa). Both pages still come from a single browser launch.
        measure_page = browser.new_page(viewport={"width": 1200, "height": 675}, device_scale_factor=2)
        render_page = browser.new_page(viewport={"width": 1200, "height": 675}, device_scale_factor=2)
        measurer = Measurer(measure_page)
        renderer = Renderer(render_page, OVERLAY_PATH)

        for handle in selected_handles:
            user = config.get(handle)
            result = fetched[handle]

            if isinstance(result, Exception):
                print(f"[{handle}] fetch failed: {result}")
                continue
            if result is None:
                print(f"[{handle}] no qualifying post")
                continue

            post = result
            last_id = state["users"].get(handle, {}).get("last_id")
            if post.id == last_id:
                print(f"[{handle}] no new post (last_id={last_id})")
                continue

            try:
                paths = render_post(renderer, measurer, user, post)
                send_cards(user.handle, post.url, paths)
            except Exception as e:  # noqa: BLE001 - one user's failure must not stop the others
                print(f"[{handle}] failed to render/send: {e}")
                continue

            state["users"][handle] = {
                "last_id": post.id,
                "posted_at": post.created_at.isoformat(),
                "parts": len(paths),
            }
            save_state(state)
            print(f"[{handle}] posted {post.id} ({len(paths)} card(s))")

        browser.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
