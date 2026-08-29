#!/usr/bin/env python
"""Render a card locally with no network calls and no secrets (BUILD.md §10)."""
import argparse
import sys
import webbrowser
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.compose import Measurer, Renderer, plan_parts, template_data_uri
from src.config import ConfigError, load_config

ROOT = Path(__file__).resolve().parent.parent
OVERLAY_PATH = ROOT / "overlay.html"
USERS_YAML = ROOT / "users.yaml"
OUT_DIR = ROOT / "out"

_LOREM_BASE = (
    "Play long-term games with long-term people. "
    "The world is broken into fast games and slow games. "
    "Play long-term games with people who exhibit long-term thinking. "
    "In the long run, everyone gets what they deserve. "
    "Reading and thinking are the two most important skills. "
)


def _lorem(n: int) -> str:
    return (_LOREM_BASE * (n // len(_LOREM_BASE) + 1))[:n]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handle", required=True, help="handle from users.yaml")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", help="literal post text")
    group.add_argument("--file", help="path to a text file")
    group.add_argument("--lorem", type=int, help="generate N characters of filler text")
    parser.add_argument("--open", action="store_true", help="open the first output PNG")
    args = parser.parse_args()

    try:
        config = load_config(USERS_YAML)
    except ConfigError as e:
        print(f"error: invalid users.yaml: {e}", file=sys.stderr)
        return 1

    user = config.get(args.handle)
    if user is None:
        print(f"error: no user '{args.handle}' in {USERS_YAML}", file=sys.stderr)
        return 1

    if args.text is not None:
        text = args.text
    elif args.file is not None:
        text = Path(args.file).read_text(encoding="utf-8")
    else:
        text = _lorem(args.lorem)

    OUT_DIR.mkdir(exist_ok=True)
    template_uri = template_data_uri(user.template)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1200, "height": 675}, device_scale_factor=2)

        plan = plan_parts(Measurer(page), text, user.zone, user.accent)
        renderer = Renderer(page, OVERLAY_PATH)

        n = len(plan.parts)
        paths = []
        for i, part in enumerate(plan.parts, start=1):
            badge = (i, n) if n > 1 else None
            out_path = OUT_DIR / f"{user.handle}_preview_{i}of{n}.png"
            renderer.render(template_uri, user.zone, part, badge, user.accent, out_path)
            paths.append(out_path)

        browser.close()

    print(f"handle:     {user.handle}")
    print(f"parts:      {n}{'  (truncated)' if plan.truncated else ''}")
    print(f"font sizes: {[p.font_size for p in plan.parts]}")
    for p in paths:
        print(f"wrote:      {p}")

    if args.open and paths:
        webbrowser.open(paths[0].resolve().as_uri())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
