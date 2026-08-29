"""Measure, split, and render tweet text onto template PNGs (BUILD.md §4)."""
from __future__ import annotations

import base64
import html
import re
from dataclasses import dataclass
from pathlib import Path

from src.config import Zone

MAX_FONT = 44
COMFORTABLE = 26
MIN_FONT = 19
MAX_PARTS = 4
BADGE_H = 46

_ENTITY_RE = re.compile(r'https?://[^\s<>"]+|[@#]\w+')


def highlight_entities(text: str, accent: str) -> str:
    """Escape text for HTML, then wrap @mentions/#hashtags/links in accent spans."""
    out = []
    last = 0
    for m in _ENTITY_RE.finditer(text):
        out.append(html.escape(text[last : m.start()]))
        escaped_entity = html.escape(m.group(0))
        out.append(f'<span class="ent" style="color:{accent}">{escaped_entity}</span>')
        last = m.end()
    out.append(html.escape(text[last:]))
    return "".join(out)


_PARAGRAPH_RE = re.compile(r"\n\s*\n")
_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+")
_WORD_RE = re.compile(r"\s+")
_BOUNDARY_PATTERNS = [(0, _PARAGRAPH_RE), (1, _SENTENCE_RE), (2, _WORD_RE)]


def _boundary_candidates(text: str) -> list[tuple[int, int]]:
    """[(index, rank), ...] for every boundary in text, deduplicated (best rank wins)."""
    best_rank_at: dict[int, int] = {}
    for rank, pattern in _BOUNDARY_PATTERNS:
        for m in pattern.finditer(text):
            idx = m.end()
            if 0 < idx < len(text) and (idx not in best_rank_at or rank < best_rank_at[idx]):
                best_rank_at[idx] = rank
    return sorted(best_rank_at.items())


def split_balanced(text: str, parts: int) -> list[str]:
    """Split at the natural boundary closest to each of the parts-1 target
    positions, ranking paragraph > sentence > word breaks (BUILD.md §4.4)."""
    if parts <= 1:
        return [text.strip()]

    n = len(text)
    candidates = _boundary_candidates(text)

    if not candidates:
        cuts = sorted({c for c in (round(n * k / parts) for k in range(1, parts)) if 0 < c < n})
    else:
        cuts: list[int] = []
        for k in range(1, parts):
            target = n * k / parts
            best_idx, best_score = None, None
            for idx, rank in candidates:
                if idx in cuts:
                    continue
                score = abs(idx - target) + rank * (n / (parts * 2)) * 0.35
                if best_score is None or score < best_score:
                    best_idx, best_score = idx, score
            if best_idx is not None:
                cuts.append(best_idx)
        cuts = sorted(set(cuts))

    chunks = []
    start = 0
    for cut in cuts:
        chunks.append(text[start:cut].strip())
        start = cut
    chunks.append(text[start:].strip())
    return [c for c in chunks if c]


MEASURE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  html, body { margin:0; padding:0; }
  #z { position:absolute; visibility:hidden; }
  #t {
    line-height:1.36; font-weight:500; letter-spacing:-.01em;
    white-space:pre-wrap; overflow-wrap:anywhere;
    font-family: "Liberation Sans","DejaVu Sans","Noto Sans CJK SC",
                  "Noto Color Emoji", sans-serif;
  }
</style></head>
<body><div id="z"><div id="t"></div></div></body></html>"""


class Measurer:
    """Binary-searches the largest font size that fits html_content in w x h."""

    def __init__(self, page):
        self.page = page
        self.page.set_content(MEASURE_HTML)

    def best_font(self, html_content: str, w: int, h: int) -> int:
        self.page.evaluate(
            """([html, w]) => {
                const z = document.getElementById('z');
                const t = document.getElementById('t');
                z.style.width = w + 'px';
                t.innerHTML = html;
            }""",
            [html_content, w],
        )

        lo, hi, best = MIN_FONT, MAX_FONT, 0
        while lo <= hi:
            mid = (lo + hi) // 2
            fits = (
                self.page.evaluate(
                    """(size) => {
                        const t = document.getElementById('t');
                        t.style.fontSize = size + 'px';
                        return t.scrollHeight;
                    }""",
                    mid,
                )
                <= h
            )
            if fits:
                best, lo = mid, mid + 1
            else:
                hi = mid - 1
        return best


@dataclass(frozen=True)
class TextPart:
    html: str
    font_size: int


@dataclass(frozen=True)
class CardPlan:
    parts: list[TextPart]
    truncated: bool


def plan_parts(measurer: Measurer, text: str, zone: Zone, accent: str) -> CardPlan:
    """Fewest parts that keep every card >= COMFORTABLE font size (BUILD.md §4.3)."""
    full_html = highlight_entities(text, accent)
    size = measurer.best_font(full_html, zone.w, zone.h)
    if size >= COMFORTABLE:
        return CardPlan(parts=[TextPart(full_html, size)], truncated=False)

    for parts in range(2, MAX_PARTS + 1):
        chunks = split_balanced(text, parts)
        htmls = [highlight_entities(c, accent) for c in chunks]
        sizes = [measurer.best_font(h, zone.w, zone.h - BADGE_H) for h in htmls]
        if min(sizes) >= COMFORTABLE:
            common = min(sizes)
            return CardPlan(parts=[TextPart(h, common) for h in htmls], truncated=False)

    # Still failing at MAX_PARTS: truncate the final chunk until it fits.
    chunks = split_balanced(text, MAX_PARTS)
    words = chunks[-1].split(" ")
    while words:
        candidate = " ".join(words) + " …"
        candidate_html = highlight_entities(candidate, accent)
        if measurer.best_font(candidate_html, zone.w, zone.h - BADGE_H) >= MIN_FONT:
            chunks[-1] = candidate
            break
        words = words[:-1]
    else:
        chunks[-1] = "…"

    htmls = [highlight_entities(c, accent) for c in chunks]
    sizes = [measurer.best_font(h, zone.w, zone.h - BADGE_H) for h in htmls]
    common = max(MIN_FONT, min(sizes))
    return CardPlan(parts=[TextPart(h, common) for h in htmls], truncated=True)


def template_data_uri(path) -> str:
    data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"


class Renderer:
    """Fills overlay.html's DOM and screenshots #card. Reuse one instance
    across all cards and all users (BUILD.md §4.5) — do not re-launch
    Chromium or re-navigate per card."""

    def __init__(self, page, overlay_path: Path):
        self.page = page
        self.page.goto(overlay_path.resolve().as_uri())

    def render(
        self,
        template_uri: str,
        zone: Zone,
        part: TextPart,
        badge,
        accent: str,
        text_color: str,
        out_path,
    ) -> None:
        badge_i, badge_n = badge if badge else (None, None)
        zone_h = zone.h - BADGE_H if badge else zone.h

        self.page.evaluate(
            """(args) => {
                const card = document.getElementById('card');
                const zone = document.getElementById('zone');
                const text = document.getElementById('text');
                const badgeEl = document.getElementById('badge');

                card.style.setProperty('--accent', args.accent);
                card.style.setProperty('--text-color', args.textColor);
                card.style.backgroundImage = `url(${args.templateUri})`;

                zone.style.left = args.zone.x + 'px';
                zone.style.top = args.zone.y + 'px';
                zone.style.width = args.zone.w + 'px';
                zone.style.height = args.zoneH + 'px';

                text.style.fontSize = args.fontSize + 'px';
                text.innerHTML = args.html;

                if (args.badgeI !== null) {
                    badgeEl.style.display = 'flex';
                    badgeEl.style.left = args.zone.x + 'px';
                    badgeEl.style.top = (args.zone.y + args.zone.h - 46 + 8) + 'px';
                    document.getElementById('badge-pill').textContent = `${args.badgeI}/${args.badgeN}`;
                    document.getElementById('badge-label').textContent =
                        args.badgeI === args.badgeN ? 'end of post' : 'continues below ↓';
                } else {
                    badgeEl.style.display = 'none';
                }
            }""",
            {
                "accent": accent,
                "textColor": text_color,
                "templateUri": template_uri,
                "zone": {"x": zone.x, "y": zone.y, "w": zone.w, "h": zone.h},
                "zoneH": zone_h,
                "fontSize": part.font_size,
                "html": part.html,
                "badgeI": badge_i,
                "badgeN": badge_n,
            },
        )
        self.page.locator("#card").screenshot(path=str(out_path))
