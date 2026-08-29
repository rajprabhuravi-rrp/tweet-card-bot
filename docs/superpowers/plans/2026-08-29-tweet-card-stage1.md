# Tweet Card Bot — Stage 1 (Renderer) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify the local, credential-free half of the Tweet Card Bot: config loading, text measurement/splitting, HTML-to-PNG card rendering, and a `preview.py` CLI — with two throwaway stand-in templates so it's runnable today.

**Architecture:** `src/config.py` loads and validates `users.yaml` into typed dataclasses. `src/compose.py` is the rendering core: pure-logic text splitting/escaping (unit tested, no browser), a `Measurer` that binary-searches font size via a hidden Playwright page, and a `Renderer` that fills `overlay.html`'s DOM via `page.evaluate` and screenshots the `#card` element. `tools/preview.py` wires config + compose together into a CLI with no network calls. `tools/make_test_template.py` is throwaway scaffolding that generates two placeholder 1200×675 PNGs so the pipeline is exercisable before real templates exist.

**Tech Stack:** Python 3.14, Playwright (sync API) for headless Chromium screenshotting, Pillow for template validation/generation, PyYAML for config, pytest for tests.

**Spec:** `BUILD.md` (repo root) — sections 1 (settled decisions), 2 (layout), 3 (config contract), 4 (compose.py), 5 (overlay.html), 10 (preview.py), 11 (tests).

## Global Constraints

- No image-generation model anywhere — cards are HTML screenshotted with headless Chromium (BUILD.md §1.1).
- Code draws nothing but the text zone and badge — avatars/names/branding live in the template PNG (BUILD.md §1.2).
- Font size and split decisions come from real browser-measured `scrollHeight`, never character counts (BUILD.md §1.3).
- `MAX_FONT=44`, `COMFORTABLE=26`, `MIN_FONT=19`, `MAX_PARTS=4`, `BADGE_H=46` (BUILD.md §4.1) — exact values, not tunable in this pass.
- Templates must be exactly 1200×675px; the overlay renders at `device_scale_factor=2` (2400×1350 output).
- The measurement page's font-family/line-height/weight/letter-spacing must exactly match `overlay.html`'s `#text` styling, or measurements lie (BUILD.md §4.2).
- Escape tweet text for HTML, then wrap `@mentions`/`#hashtags`/links in accent-colored spans — escape-then-wrap, never the reverse (BUILD.md §4.6).
- **Out of scope for this pass:** `src/xapi.py`, `src/telegram.py`, `src/pipeline.py`, `.github/workflows/post.yml`. Do not build these yet.
- Use YAML (not JSON) for `users.yaml` (BUILD.md §2).

---

## File Structure

- `requirements.txt` — playwright, pillow, pyyaml, pytest.
- `src/config.py` — `Zone`, `UserConfig`, `Config`, `ConfigError`, `load_config()`. Owns all `users.yaml` validation.
- `src/compose.py` — the rendering core: constants, `highlight_entities`, `split_balanced`, `plan_parts`, `Measurer`, `Renderer`, `template_data_uri`, `TextPart`, `CardPlan`.
- `overlay.html` — the on-disk render template: `#card` (1200×675) with a `#zone`/`#text` div and a `#badge` div, styled to match the measurement page exactly.
- `users.yaml` — real config file, pointing at the two throwaway test templates for this pass.
- `tools/make_test_template.py` — throwaway scaffolding (Pillow) generating `templates/testleft.png` and `templates/testright.png`. Marked for deletion once real templates exist.
- `tools/preview.py` — CLI: `--handle`, one of `--text`/`--file`/`--lorem`, `--open`. No network calls.
- `tests/test_split.py` — pure-logic tests for `split_balanced` and `highlight_entities` (no browser).
- `tests/test_config.py` — validation tests for `load_config`.

`src/compose.py` owns both pure-logic (testable) and browser-dependent (manually verified) code in one file per BUILD.md's layout — it stays under ~200 lines for this pass, so no further split is warranted yet.

---

### Task 1: Project scaffolding — requirements.txt and throwaway test templates

**Files:**
- Create: `requirements.txt`
- Create: `tools/make_test_template.py`
- Test: none (visual scaffolding; verified by running it in Task 7)

**Interfaces:**
- Produces: `templates/testleft.png`, `templates/testright.png` (1200×675 PNGs), used by `users.yaml` (Task 2) and `preview.py` (Task 7).

- [ ] **Step 1: Write requirements.txt**

```
playwright>=1.47
pillow>=11.0
pyyaml>=6.0
pytest>=8.0
```

- [ ] **Step 2: Install dependencies and the Chromium binary**

Run: `pip install -r requirements.txt && python -m playwright install chromium`
Expected: installs succeed with no errors.

- [ ] **Step 3: Write the throwaway template generator**

```python
"""Scaffolding: generates two 1200x675 stand-in templates for local preview,
so tools/preview.py is runnable before real per-user templates exist.

DELETE THIS FILE once real templates are added under templates/.
"""
from pathlib import Path

from PIL import Image, ImageDraw

W, H = 1200, 675
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def _make(path: Path, photo_cx: int) -> None:
    img = Image.new("RGB", (W, H), "#1c1f26")
    draw = ImageDraw.Draw(img)
    draw.ellipse(
        [photo_cx - 150, H // 2 - 150, photo_cx + 150, H // 2 + 150],
        fill="#3a3f4b",
        outline="#5eaee0",
        width=4,
    )
    img.save(path)


def main() -> None:
    TEMPLATES_DIR.mkdir(exist_ok=True)
    left = TEMPLATES_DIR / "testleft.png"
    right = TEMPLATES_DIR / "testright.png"
    _make(left, photo_cx=220)   # photo on the LEFT, empty zone on the right
    _make(right, photo_cx=980)  # photo on the RIGHT, empty zone on the left
    print(f"wrote {left}")
    print(f"wrote {right}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run it and confirm both PNGs exist at 1200x675**

Run: `python tools/make_test_template.py`
Expected: prints two `wrote ...` lines; `templates/testleft.png` and `templates/testright.png` exist.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt tools/make_test_template.py templates/testleft.png templates/testright.png
git commit -m "chore: add dependencies and throwaway test templates"
```

---

### Task 2: `src/config.py` — load and validate `users.yaml`

**Files:**
- Create: `src/config.py`
- Create: `src/__init__.py` (empty, makes `src` importable)
- Create: `users.yaml`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Zone(x, y, w, h)`, `UserConfig(handle, template: Path, accent: str, zone: Zone, enabled: bool)`, `Config(users: list[UserConfig])` with `.get(handle) -> UserConfig | None` and `.enabled_users() -> list[UserConfig]`, `ConfigError(Exception)`, `load_config(path) -> Config`.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config.py
import sys
from pathlib import Path

import pytest
import yaml
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import ConfigError, load_config


def _make_png(path, size=(1200, 675)):
    Image.new("RGB", size, "white").save(path)


def _write_yaml(path, data):
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_valid_config_loads(tmp_path):
    _make_png(tmp_path / "naval.png")
    users_yaml = tmp_path / "users.yaml"
    _write_yaml(
        users_yaml,
        {
            "defaults": {
                "accent": "#5eaee0",
                "zone": {"x": 520, "y": 120, "w": 610, "h": 400},
            },
            "users": [{"handle": "naval", "template": "naval.png"}],
        },
    )

    config = load_config(users_yaml)

    assert len(config.users) == 1
    user = config.users[0]
    assert user.handle == "naval"
    assert user.accent == "#5eaee0"
    assert user.zone.x == 520
    assert user.enabled is True


def test_defaults_inheritance(tmp_path):
    _make_png(tmp_path / "paulg.png")
    users_yaml = tmp_path / "users.yaml"
    _write_yaml(
        users_yaml,
        {
            "defaults": {
                "accent": "#5eaee0",
                "zone": {"x": 520, "y": 120, "w": 610, "h": 400},
            },
            "users": [
                {
                    "handle": "paulg",
                    "template": "paulg.png",
                    "accent": "#e88d5c",
                    "zone": {"x": 70},
                }
            ],
        },
    )

    config = load_config(users_yaml)
    user = config.get("paulg")

    assert user.accent == "#e88d5c"  # overridden
    assert user.zone.x == 70  # overridden
    assert user.zone.y == 120  # inherited
    assert user.zone.w == 610  # inherited


def test_zone_outside_canvas_rejected(tmp_path):
    _make_png(tmp_path / "bad.png")
    users_yaml = tmp_path / "users.yaml"
    _write_yaml(
        users_yaml,
        {
            "defaults": {"accent": "#5eaee0"},
            "users": [
                {
                    "handle": "toowide",
                    "template": "bad.png",
                    "zone": {"x": 700, "y": 120, "w": 610, "h": 400},
                }
            ],
        },
    )

    with pytest.raises(ConfigError, match="toowide"):
        load_config(users_yaml)


def test_zone_too_small_rejected(tmp_path):
    _make_png(tmp_path / "tiny.png")
    users_yaml = tmp_path / "users.yaml"
    _write_yaml(
        users_yaml,
        {
            "defaults": {"accent": "#5eaee0"},
            "users": [
                {
                    "handle": "tinyzone",
                    "template": "tiny.png",
                    "zone": {"x": 10, "y": 10, "w": 100, "h": 100},
                }
            ],
        },
    )

    with pytest.raises(ConfigError, match="tinyzone"):
        load_config(users_yaml)


def test_wrong_size_template_rejected(tmp_path):
    _make_png(tmp_path / "small.png", size=(800, 600))
    users_yaml = tmp_path / "users.yaml"
    _write_yaml(
        users_yaml,
        {
            "defaults": {
                "accent": "#5eaee0",
                "zone": {"x": 520, "y": 120, "w": 610, "h": 400},
            },
            "users": [{"handle": "smallcard", "template": "small.png"}],
        },
    )

    with pytest.raises(ConfigError, match="smallcard"):
        load_config(users_yaml)


def test_duplicate_handles_rejected(tmp_path):
    _make_png(tmp_path / "dup.png")
    users_yaml = tmp_path / "users.yaml"
    _write_yaml(
        users_yaml,
        {
            "defaults": {
                "accent": "#5eaee0",
                "zone": {"x": 520, "y": 120, "w": 610, "h": 400},
            },
            "users": [
                {"handle": "dup", "template": "dup.png"},
                {"handle": "dup", "template": "dup.png"},
            ],
        },
    )

    with pytest.raises(ConfigError, match="duplicate"):
        load_config(users_yaml)


def test_bad_accent_rejected(tmp_path):
    _make_png(tmp_path / "badaccent.png")
    users_yaml = tmp_path / "users.yaml"
    _write_yaml(
        users_yaml,
        {
            "defaults": {"zone": {"x": 520, "y": 120, "w": 610, "h": 400}},
            "users": [
                {
                    "handle": "badaccent",
                    "template": "badaccent.png",
                    "accent": "blue",
                }
            ],
        },
    )

    with pytest.raises(ConfigError, match="badaccent"):
        load_config(users_yaml)


def test_enabled_defaults_true_and_can_be_disabled(tmp_path):
    _make_png(tmp_path / "x.png")
    users_yaml = tmp_path / "users.yaml"
    _write_yaml(
        users_yaml,
        {
            "defaults": {
                "accent": "#5eaee0",
                "zone": {"x": 520, "y": 120, "w": 610, "h": 400},
            },
            "users": [
                {"handle": "a", "template": "x.png"},
                {"handle": "b", "template": "x.png", "enabled": False},
            ],
        },
    )

    config = load_config(users_yaml)

    assert config.get("a").enabled is True
    assert config.get("b").enabled is False
    assert [u.handle for u in config.enabled_users()] == ["a"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.config'` (or `src`).

- [ ] **Step 3: Write `src/__init__.py`**

Empty file.

- [ ] **Step 4: Write the implementation**

```python
# src/config.py
"""Load and validate users.yaml (BUILD.md §3)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from PIL import Image

TEMPLATE_W = 1200
TEMPLATE_H = 675
MIN_ZONE_W = 200
MIN_ZONE_H = 150
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class ConfigError(Exception):
    """Raised when users.yaml fails validation. Message names the offending handle."""


@dataclass(frozen=True)
class Zone:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class UserConfig:
    handle: str
    template: Path
    accent: str
    zone: Zone
    enabled: bool = True


@dataclass(frozen=True)
class Config:
    users: list[UserConfig]

    def enabled_users(self) -> list[UserConfig]:
        return [u for u in self.users if u.enabled]

    def get(self, handle: str) -> UserConfig | None:
        for u in self.users:
            if u.handle == handle:
                return u
        return None


def _merge_zone(raw: dict, defaults: dict, handle: str) -> Zone:
    merged = {**defaults.get("zone", {}), **raw.get("zone", {})}
    for field in ("x", "y", "w", "h"):
        if field not in merged:
            raise ConfigError(f"user '{handle}': zone.{field} is missing and has no default")
    return Zone(x=merged["x"], y=merged["y"], w=merged["w"], h=merged["h"])


def _validate_zone(zone: Zone, handle: str) -> None:
    if zone.w < MIN_ZONE_W or zone.h < MIN_ZONE_H:
        raise ConfigError(
            f"user '{handle}': zone {zone.w}x{zone.h} is smaller than the "
            f"minimum {MIN_ZONE_W}x{MIN_ZONE_H}"
        )
    if zone.x < 0 or zone.y < 0 or zone.x + zone.w > TEMPLATE_W or zone.y + zone.h > TEMPLATE_H:
        raise ConfigError(
            f"user '{handle}': zone {zone.x},{zone.y} {zone.w}x{zone.h} falls outside "
            f"the {TEMPLATE_W}x{TEMPLATE_H} canvas"
        )


def _validate_template(template: Path, handle: str) -> None:
    if not template.exists():
        raise ConfigError(f"user '{handle}': template file not found: {template}")
    with Image.open(template) as img:
        if img.size != (TEMPLATE_W, TEMPLATE_H):
            raise ConfigError(
                f"user '{handle}': template {template} is {img.size[0]}x{img.size[1]}, "
                f"expected {TEMPLATE_W}x{TEMPLATE_H}"
            )


def _validate_accent(accent: str, handle: str) -> None:
    if not HEX_RE.match(accent):
        raise ConfigError(f"user '{handle}': accent '{accent}' is not a #rrggbb hex string")


def load_config(path: str | Path) -> Config:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    defaults = raw.get("defaults", {}) or {}
    raw_users = raw.get("users", []) or []

    seen_handles: set[str] = set()
    users: list[UserConfig] = []

    for raw_user in raw_users:
        handle = raw_user.get("handle")
        if not handle:
            raise ConfigError("a user entry is missing 'handle'")
        if handle in seen_handles:
            raise ConfigError(f"duplicate handle: '{handle}'")
        seen_handles.add(handle)

        template_str = raw_user.get("template") or defaults.get("template")
        if not template_str:
            raise ConfigError(f"user '{handle}': no template configured")
        template = path.parent / template_str

        accent = raw_user.get("accent", defaults.get("accent"))
        if not accent:
            raise ConfigError(f"user '{handle}': no accent configured")

        zone = _merge_zone(raw_user, defaults, handle)
        enabled = raw_user.get("enabled", True)

        _validate_template(template, handle)
        _validate_zone(zone, handle)
        _validate_accent(accent, handle)

        users.append(
            UserConfig(handle=handle, template=template, accent=accent, zone=zone, enabled=enabled)
        )

    return Config(users=users)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS — all 7 tests green.

- [ ] **Step 6: Write the real `users.yaml`, pointing at the throwaway test templates**

```yaml
defaults:
  accent: "#5eaee0"
  zone: { x: 520, y: 120, w: 610, h: 400 }

users:
  - handle: testleft
    template: templates/testleft.png
    accent: "#5eaee0"
    zone: { x: 520, y: 120, w: 610, h: 400 }   # photo on the LEFT

  - handle: testright
    template: templates/testright.png
    accent: "#e88d5c"
    zone: { x: 70, y: 120, w: 610, h: 400 }    # photo on the RIGHT
```

- [ ] **Step 7: Commit**

```bash
git add src/__init__.py src/config.py tests/test_config.py users.yaml
git commit -m "feat: load and validate users.yaml"
```

---

### Task 3: `src/compose.py` — pure-logic text splitting and entity highlighting

**Files:**
- Create: `src/compose.py` (this task writes the pure-logic top half; Task 4 appends the browser-dependent half)
- Test: `tests/test_split.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `MAX_FONT`, `COMFORTABLE`, `MIN_FONT`, `MAX_PARTS`, `BADGE_H` (ints); `highlight_entities(text: str, accent: str) -> str`; `split_balanced(text: str, parts: int) -> list[str]`. Task 4 and Task 5 build on these.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_split.py
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.compose import highlight_entities, split_balanced


def _words(text):
    return set(re.findall(r"\S+", text))


def test_parts_one_returns_input_unchanged():
    text = "  hello world  "
    assert split_balanced(text, 1) == [text.strip()]


def test_never_cuts_mid_word():
    text = ("Play long-term games with long-term people. " * 10).strip()
    chunks = split_balanced(text, 3)
    for chunk in chunks:
        assert not chunk[:1].isspace()
        assert not chunk[-1:].isspace()
    assert _words(" ".join(chunks)) <= _words(text)


def test_prefers_paragraph_over_word_break_even_when_farther():
    prefix = "a" * 43 + "\n\n"  # paragraph boundary ends at index 45
    mid = "b" * 5 + " "  # word boundary ends at index 51
    suffix = "c" * 44
    text = prefix + mid + suffix  # length 95, target for parts=2 is 47.5

    chunks = split_balanced(text, 2)

    assert chunks[0] == "a" * 43
    assert chunks[1] == "b" * 5 + " " + "c" * 44


def test_prefers_sentence_over_word_break_even_when_farther():
    prefix = "a" * 40 + ". "  # sentence boundary ends at index 42
    mid = "b" * 5 + " "  # word boundary ends at index 48
    suffix = "c" * 44
    text = prefix + mid + suffix  # length 91, target for parts=2 is 45.5

    chunks = split_balanced(text, 2)

    assert chunks[0] == "a" * 40 + "."
    assert chunks[1] == "b" * 5 + " " + "c" * 44


def test_reassembles_to_original_modulo_whitespace():
    text = "One two three four five six seven eight nine ten eleven twelve."
    chunks = split_balanced(text, 3)
    normalized_original = re.sub(r"\s+", " ", text).strip()
    normalized_joined = re.sub(r"\s+", " ", " ".join(chunks)).strip()
    assert normalized_joined == normalized_original


def test_no_whitespace_does_not_crash():
    text = "a" * 500
    chunks = split_balanced(text, 3)
    assert "".join(chunks) != ""


def test_highlight_escapes_script_tag():
    out = highlight_entities("<script>alert(1)</script>", "#5eaee0")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_highlight_wraps_mention_hashtag_and_link():
    out = highlight_entities("hi @naval check #stoicism at https://example.com/x?y=1&z=2", "#5eaee0")
    assert out.count('<span class="ent"') == 3
    assert "&amp;" in out  # the & inside the URL query is still escaped
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_split.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.compose'`.

- [ ] **Step 3: Write the implementation (pure-logic half)**

```python
# src/compose.py
"""Measure, split, and render tweet text onto template PNGs (BUILD.md §4)."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_split.py -v`
Expected: PASS — all 8 tests green.

- [ ] **Step 5: Commit**

```bash
git add src/compose.py tests/test_split.py
git commit -m "feat: pure-logic text splitting and entity highlighting"
```

---

### Task 4: `src/compose.py` — font measurement (`Measurer`)

**Files:**
- Modify: `src/compose.py` (append)
- Test: none — requires a live Chromium page; verified manually via `preview.py` in Task 7, per BUILD.md §11 ("skip browser-dependent tests in CI unless Chromium is already cached").

**Interfaces:**
- Consumes: `MIN_FONT`, `MAX_FONT` from Task 3.
- Produces: `Measurer(page)` with `.best_font(html_content: str, w: int, h: int) -> int`. Task 5's `plan_parts` depends on this exact signature.

- [ ] **Step 1: Append the measurement page HTML and `Measurer` class**

```python
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
```

- [ ] **Step 2: Manually sanity-check with a scratch script**

Run:
```bash
python -c "
from playwright.sync_api import sync_playwright
from src.compose import Measurer

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page()
    m = Measurer(page)
    print(m.best_font('short text', 610, 400))
    print(m.best_font('long text ' * 80, 610, 400))
    browser.close()
"
```
Expected: first call prints a number close to `MAX_FONT` (44), second prints a smaller number — confirming the binary search shrinks font size as content grows. No exceptions.

- [ ] **Step 3: Commit**

```bash
git add src/compose.py
git commit -m "feat: browser-backed font-size measurement"
```

---

### Task 5: `src/compose.py` — split planning (`plan_parts`)

**Files:**
- Modify: `src/compose.py` (append)
- Test: none — depends on `Measurer` (browser). Verified manually via `preview.py` in Task 7 against the acceptance criteria in BUILD.md §12.1–12.2.

**Interfaces:**
- Consumes: `Measurer.best_font`, `highlight_entities`, `split_balanced`, `COMFORTABLE`, `MAX_PARTS`, `BADGE_H`, `MIN_FONT` from Tasks 3–4; `Zone` from `src.config`.
- Produces: `TextPart(html: str, font_size: int)`, `CardPlan(parts: list[TextPart], truncated: bool)`, `plan_parts(measurer: Measurer, text: str, zone: Zone, accent: str) -> CardPlan`. Task 6's `Renderer` and Task 7's `preview.py` depend on this exact shape.

- [ ] **Step 1: Append the planning logic**

```python
from src.config import Zone  # add to the top-of-file imports


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
```

- [ ] **Step 2: Manually sanity-check against the tuned numbers in BUILD.md §4.1**

Run:
```bash
python -c "
from playwright.sync_api import sync_playwright
from src.compose import Measurer, plan_parts
from src.config import Zone

text = ('Play long-term games with long-term people. ' * 26)[:1150]
zone = Zone(x=520, y=120, w=610, h=400)

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page()
    plan = plan_parts(Measurer(page), text, zone, '#5eaee0')
    print(len(plan.parts), [p.font_size for p in plan.parts])
    browser.close()
"
```
Expected: 4 parts at a font size in the ~28-34px range (BUILD.md's tuned table shows 31px for a 1141-char post; exact number may vary slightly with this text). If it picks 2 or 3 parts instead, re-check `COMFORTABLE`/`BADGE_H` constants before proceeding — do not adjust the algorithm to force a specific number.

- [ ] **Step 3: Commit**

```bash
git add src/compose.py
git commit -m "feat: split planning with badge-aware font sizing"
```

---

### Task 6: `overlay.html` and `Renderer`

**Files:**
- Create: `overlay.html`
- Modify: `src/compose.py` (append `Renderer`, `template_data_uri`)
- Test: none — requires a live Chromium page and produces a visual artifact; verified in Task 7.

**Interfaces:**
- Consumes: `TextPart`, `Zone` from Tasks 3 and 5.
- Produces: `template_data_uri(path) -> str`; `Renderer(page, overlay_path)` with `.render(template_data_uri, zone, part, badge, accent, out_path)`. Task 7's `preview.py` depends on this exact signature. `badge` is `(i, n) | None`.

- [ ] **Step 1: Write `overlay.html`**

Font stack, line-height, weight and letter-spacing on `#text` must match `MEASURE_HTML`'s `#t` from Task 4 exactly.

```html
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  html, body { margin: 0; padding: 0; }
  #card {
    position: relative;
    width: 1200px;
    height: 675px;
    background-size: cover;
    background-position: center;
    overflow: hidden;
  }
  #zone {
    position: absolute;
    display: flex;
    align-items: center;
  }
  #text {
    line-height: 1.36;
    font-weight: 500;
    letter-spacing: -.01em;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    color: #1a1a1a;
    font-family: "Liberation Sans", "DejaVu Sans", "Noto Sans CJK SC",
                 "Noto Color Emoji", sans-serif;
  }
  .ent { font-weight: 600; }
  #badge {
    position: absolute;
    display: none;
    align-items: center;
    gap: 10px;
    font-family: "Liberation Sans", "DejaVu Sans", sans-serif;
  }
  #badge .pill {
    padding: 6px 14px;
    border-radius: 999px;
    background: var(--accent, #5eaee0);
    color: #fff;
    font-weight: 700;
    font-size: 15px;
  }
  #badge .label {
    color: #666;
    font-size: 15px;
  }
</style>
</head>
<body>
  <div id="card">
    <div id="zone">
      <div id="text"></div>
    </div>
    <div id="badge">
      <span class="pill" id="badge-pill"></span>
      <span class="label" id="badge-label"></span>
    </div>
  </div>
</body>
</html>
```

- [ ] **Step 2: Append `template_data_uri` and `Renderer` to `src/compose.py`**

```python
import base64
from pathlib import Path


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

    def render(self, template_uri: str, zone: Zone, part: TextPart, badge, accent: str, out_path) -> None:
        badge_i, badge_n = badge if badge else (None, None)
        zone_h = zone.h - BADGE_H if badge else zone.h

        self.page.evaluate(
            """(args) => {
                const card = document.getElementById('card');
                const zone = document.getElementById('zone');
                const text = document.getElementById('text');
                const badgeEl = document.getElementById('badge');

                card.style.setProperty('--accent', args.accent);
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
```

- [ ] **Step 3: Manually verify a single render**

Run:
```bash
python -c "
from pathlib import Path
from playwright.sync_api import sync_playwright
from src.compose import Measurer, Renderer, plan_parts, template_data_uri
from src.config import Zone

zone = Zone(x=520, y=120, w=610, h=400)
uri = template_data_uri('templates/testleft.png')

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={'width':1200,'height':675}, device_scale_factor=2)
    plan = plan_parts(Measurer(page), 'Hello world, this is a test card.', zone, '#5eaee0')
    r = Renderer(page, Path('overlay.html'))
    Path('out').mkdir(exist_ok=True)
    r.render(uri, zone, plan.parts[0], None, '#5eaee0', 'out/manual_check.png')
    browser.close()
print('wrote out/manual_check.png')
"
```
Expected: `out/manual_check.png` exists, is 2400×1350 (device_scale_factor=2 applied), and visually shows the text zone filled with no badge.

- [ ] **Step 4: Commit**

```bash
git add overlay.html src/compose.py
git commit -m "feat: overlay.html and Renderer"
```

---

### Task 7: `tools/preview.py` CLI and end-to-end verification

**Files:**
- Create: `tools/preview.py`
- Test: none new (this task's own verification runs the acceptance commands from BUILD.md's build-prompt directly)

**Interfaces:**
- Consumes: `load_config`, `ConfigError` from `src.config`; `Measurer`, `Renderer`, `plan_parts`, `template_data_uri` from `src.compose`.

- [ ] **Step 1: Write `tools/preview.py`**

```python
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
```

- [ ] **Step 2: Run the full verification sequence**

Run:
```bash
python tools/make_test_template.py
python tools/preview.py --handle testleft  --text "Play long-term games with long-term people."
python tools/preview.py --handle testright --lorem 1150
pytest -q
```
Expected:
- `testleft` call: 1 part, font size at/near `MAX_FONT` (44), no badge — matches BUILD.md §12 criterion 1.
- `testright` call: ~4 parts at roughly 28-34px, badged — matches BUILD.md §12 criterion 2.
- `pytest -q`: all tests pass (7 config + 8 split = 15).

- [ ] **Step 3: Commit**

```bash
git add tools/preview.py
git commit -m "feat: preview.py CLI"
```

---

## Explicitly deferred to later stages

Per BUILD.md §14 and the stage split, these are **not** part of this plan and should not be started yet: `src/xapi.py` (GetXAPI adapter — needs a real sample response), `src/telegram.py`, `src/pipeline.py`, `.github/workflows/post.yml`, and the open questions about quote-tweets/media-only posts/threads (BUILD.md §14) — those get raised, not guessed, when `xapi.py` is built.
