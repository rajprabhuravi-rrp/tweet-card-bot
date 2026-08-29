#!/usr/bin/env python
"""Fetch one handle via GetXAPI and print the normalised Post.

Verifies the adapter on its own before anything else depends on it
(BUILD.md §6, stage-2 build notes).

Usage: python tools/check_api.py <handle>
"""
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.xapi import fetch_latest


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python tools/check_api.py <handle>", file=sys.stderr)
        return 1

    handle = sys.argv[1]
    post = fetch_latest(handle)
    if post is None:
        print(f"no qualifying post found for @{handle}")
        return 0

    print(f"id:         {post.id}")
    print(f"created_at: {post.created_at}")
    print(f"url:        {post.url}")
    print(f"text:       {post.text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
