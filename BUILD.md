# BUILD SPEC — Tweet Card Bot

You are building a scheduled job that fetches specific X users' latest posts,
composites each post onto that user's pre-made template image, and delivers the
result to a Telegram chat.

Read this whole file before writing code. The decisions in **§1 are settled** —
they were reached by testing, not preference. Do not substitute alternatives.

---

## 1. Settled decisions — do not change these

### 1.1 No image-generation model. Ever.
The image is produced by **screenshotting an HTML page with headless Chromium**
(Playwright). Not DALL·E, not Imagen, not Flux, not Gemini image, not Stable
Diffusion.

Reason: the card must contain the tweet's exact characters. Diffusion models
render text as plausible-looking shapes — they garble words, drop punctuation,
and produce a different layout every run. No prompt fixes this; it is how the
architecture works. Composition is also ~$0 vs ~$0.04/card and ~1.5s vs 5–15s.

If you find yourself reaching for an image model, you have misread the spec.

### 1.2 The design lives in PNG files, not in code.
Each user has one finished **1200×675 PNG** template that already contains
their photo, name, handle and all branding. The code fills exactly one thing:
a rectangular **text zone** whose coordinates are configuration.

Do not draw avatars, rings, gradients, names or logos in code. Do not add a
photo layer. The photo is already in the PNG.

### 1.3 Text is measured, never character-counted.
To decide font size and whether to split, ask the browser for the real rendered
height (`scrollHeight`) and binary-search the font size. Character counts are
wrong the moment emoji or CJK appear — one emoji is 2–4 chars but renders as
wide as two letters.

### 1.4 Long posts split into multiple cards, sent as one Telegram album.
Never as N separate `sendPhoto` calls — another user's post can land between
card 2 and card 3 and break the sequence. Use `sendMediaGroup`.

### 1.5 Dedupe state is mandatory.
Without it the job reposts the same tweet on every run, forever.

---

## 2. Repository layout

```
.
├── .github/workflows/post.yml
├── src/
│   ├── compose.py          # measure, split, render          ← the core
│   ├── telegram.py         # sendPhoto / sendMediaGroup
│   ├── xapi.py             # GetXAPI adapter
│   ├── config.py           # load + validate users.yaml
│   └── pipeline.py         # orchestration, entry point
├── templates/
│   ├── naval.png           # 1200x675, photo + branding baked in
│   └── ...                 # one per user, 20+ eventually
├── overlay.html            # the text-zone overlay (see §5)
├── users.yaml              # per-user config
├── state.json              # generated; last posted id per user
├── tests/
│   ├── test_split.py
│   └── test_config.py
├── tools/
│   └── preview.py          # render a card locally without API calls
├── requirements.txt
└── README.md
```

Use **YAML, not JSON**, for `users.yaml` — at 20+ users it will be hand-edited
often and needs comments.

---

## 3. Configuration contract

### 3.1 `users.yaml`

```yaml
defaults:
  accent: "#5eaee0"
  zone: { x: 520, y: 120, w: 610, h: 400 }

users:
  - handle: naval
    template: templates/naval.png
    accent: "#5eaee0"
    zone: { x: 520, y: 120, w: 610, h: 400 }   # photo on the LEFT

  - handle: paulg
    template: templates/paulg.png
    accent: "#e88d5c"
    zone: { x: 70, y: 120, w: 610, h: 400 }    # photo on the RIGHT
    enabled: false                              # optional, defaults true
```

`zone` is the empty rectangle in that user's template PNG where tweet text may
be drawn, measured in Canva/Figma. It is the **only** contract between a design
and the code. Fields inherit from `defaults` when omitted.

### 3.2 Validation (`config.py`)

On load, fail loudly with a clear message if:

- a `template` file does not exist
- a template is not exactly 1200×675 (use Pillow to check)
- a `zone` falls outside 1200×675, or has `w < 200` or `h < 150`
- `handle` is duplicated
- `accent` is not a `#rrggbb` hex string

A misconfigured zone silently produces ugly cards for weeks. Catch it at load.

### 3.3 `state.json`

```json
{
  "naval": { "last_id": "1234567890", "posted_at": "2026-08-29T10:30:00Z", "parts": 1 }
}
```

Write it after **each** user, not once at the end, so a crash on user 15 does
not cause users 1–14 to repost next run.

---

## 4. `compose.py` — the core

### 4.1 Constants

```python
MAX_FONT    = 44   # never larger
COMFORTABLE = 26   # below this, prefer splitting over shrinking
MIN_FONT    = 19   # absolute floor
MAX_PARTS   = 4    # beyond this, truncate the last card
BADGE_H     = 46   # vertical space reserved for the "1/4" pill
```

These are tuned, not arbitrary. Measured on a 1141-char post in a 610×400 zone:

| Parts | Resulting font | Verdict |
|-------|----------------|---------|
| 2     | 21px           | too small |
| 3     | 23px           | too small |
| **4** | **31px**       | ✅ chosen |

### 4.2 Measuring

Create one hidden measurement page per run:

```html
<div id="z" style="position:absolute;visibility:hidden">
  <div id="t" style="line-height:1.36;font-weight:500;letter-spacing:-.01em;
                     white-space:pre-wrap;overflow-wrap:anywhere"></div>
</div>
```

`best_font(html, w, h) -> int` sets `#z` width to `w`, injects `html`, then
**binary-searches** font size in `[MIN_FONT, MAX_FONT]` for the largest value
where `#t.scrollHeight <= h`. Returns 0 if nothing fits.

Binary search, not a linear loop — it is ~5 evaluations instead of ~25, and
`page.evaluate` round-trips are the slow part.

The measurement page's font stack, line-height, weight and letter-spacing
**must exactly match** the render overlay, or measurements lie.

### 4.3 Split planning

```python
def plan_parts(page, text, zone) -> list[tuple[str, int]]:
    """Returns [(chunk_text, font_size), ...]"""
```

Algorithm:

1. `size = best_font(full_text, zone.w, zone.h)`.
   If `size >= COMFORTABLE` → return `[(text, size)]`. **One card, no badge.**
2. Otherwise, for `parts` in `2..MAX_PARTS`:
   - `chunks = split_balanced(text, parts)`
   - measure each chunk against `zone.h - BADGE_H`
   - if `min(sizes) >= COMFORTABLE` → return all chunks at **one common size**
     (`min(sizes)`), so the set looks consistent
3. If still failing at `MAX_PARTS`: use `MAX_PARTS` chunks at the best common
   size, and **truncate the final chunk** — trim whole words off the end until
   `chunk + " …"` fits, then append `" …"`.

Return the fewest parts that keep every card readable. Not a fixed count.

### 4.4 `split_balanced(text, parts) -> list[str]`

Split at natural boundaries, ranked:

| Rank | Boundary | Regex |
|------|----------|-------|
| 0 (best) | paragraph break | `\n\s*\n` |
| 1 | sentence end | `(?<=[.!?…])\s+` |
| 2 (acceptable) | word break | `\s+` |

For each of the `parts - 1` cut points, target position `len(text) * k / parts`
and choose the candidate minimising:

```
abs(candidate_index - target) + rank * (len(text) / (parts * 2)) * 0.35
```

This lets a paragraph break a little further from the target beat a word break
right on it. **Never cut mid-word.** Strip whitespace from each chunk.

### 4.5 Rendering

Launch Chromium **once** and reuse the page across all cards and all users —
launching per card is ~10× slower.

- viewport `1200×675`, `device_scale_factor=2` (crisp text; output is 2400×1350)
- screenshot the `#card` element, not the page
- when `total > 1`, shrink the text zone height by `BADGE_H` and render a badge
  at `zone.y + zone.h - BADGE_H + 8`

Badge copy — exactly this, not "see more":

- cards `1..N-1`: pill `i/N` + muted text `continues below ↓`
- card `N`: pill `N/N` + muted text `end of post`

Output naming: `{handle}_{tweet_id}_{i}of{N}.png`.

### 4.6 Entity highlighting

Escape the tweet text first, **then** wrap `@mentions`, `#hashtags` and
`https?://` links in `<span class="ent">` coloured with the user's accent.
Escaping after wrapping would destroy the spans; escaping never would allow
HTML injection from tweet text into your page.

---

## 5. `overlay.html`

A minimal page: the template PNG as `background-image` (embedded as a `data:`
URI so the screenshot has no network dependency), plus the absolutely
positioned text zone and optional badge. Nothing else.

Font stack, and it matters:

```css
font-family: "Liberation Sans", "DejaVu Sans", "Noto Sans CJK SC",
             "Noto Color Emoji", sans-serif;
```

CJK and colour-emoji fallbacks are required — real tweets contain both. Verify
they render rather than showing tofu boxes.

---

## 6. `xapi.py` — GetXAPI adapter

Isolate all GetXAPI specifics here. The rest of the codebase must depend only
on this shape:

```python
@dataclass
class Post:
    id: str
    text: str
    created_at: datetime
    url: str
```

`fetch_latest(handle: str) -> Post | None`

Rules:

- request the few most recent posts, not just one — the newest may be filtered
- **skip retweets** (text starts with `RT @`)
- **skip replies** (`in_reply_to_status_id` set, or text starts with `@`)
- prefer a long-form/`note_tweet` field over truncated `text` when the API
  provides one, so 4000-char posts arrive whole
- return `None` when nothing qualifies

Leave a clearly marked `# ADAPT: endpoint + response shape` comment at the
request site. Do not invent GetXAPI's schema — write it against the shape above
and let a human wire the real field names.

Timeout every HTTP call (25s). Retry twice on 5xx and timeouts with exponential
backoff; never retry a 4xx.

---

## 7. `telegram.py`

- 1 card → `sendPhoto`
- 2–4 cards → `sendMediaGroup`, caption on the **first** item only
- always check both `response.ok` and the JSON body's `ok` field — Telegram
  returns HTTP 200 with `{"ok": false}` on some errors
- close all file handles in a `finally`
- caption (HTML parse mode):
  `<b>@handle</b>` newline `<a href="{url}">Read the full post on X →</a>`

---

## 8. Scale: this must work at 20+ users

This is a hard requirement, not a future concern. Two constraints bind before
anything else does.

### 8.1 API quota — the real limit

20 users checked every 30 minutes = **960 GetXAPI calls/day, ~29,000/month**.
That will exhaust most affordable plans.

**Implement user rotation.** Each run checks only a slice of the roster:

```yaml
schedule:
  users_per_run: 5     # 20 users → each checked every 4 runs
```

Persist a `cursor` in `state.json` and advance it each run. With
`users_per_run: 5` and a 30-minute cron, each user is checked every 2 hours and
the call volume drops to 240/day — a 4× reduction with no meaningful loss, since
these accounts do not post more than once every two hours.

Also: if GetXAPI offers a **batch/multi-user endpoint**, use it and skip
rotation entirely. Check their docs before implementing rotation.

### 8.2 GitHub Actions minutes

GitHub Free gives **2,000 Actions minutes/month on private repos**, and billing
rounds every job up to the whole minute. At 48 runs/day a 1-minute job costs
~1,440 min/month and a 2-minute job costs ~2,880 — over the limit.

Two mitigations, both required:

**Cache the Playwright browser.** Downloading Chromium takes 30–45s of every
run. Cache `~/.cache/ms-playwright` keyed on the Playwright version, cutting it
to ~10s:

```yaml
- uses: actions/cache@v4
  with:
    path: ~/.cache/ms-playwright
    key: pw-${{ runner.os }}-${{ hashFiles('requirements.txt') }}
- run: playwright install --with-deps chromium
```

**Fetch users concurrently.** 20 sequential HTTP calls at ~500ms each is 10s of
billed time. Use a thread pool of 5–8. Rendering stays sequential — one browser,
one page.

Target: a run that finds nothing new should finish in **under 45 seconds**.

### 8.3 Templates in git — yes, this is fine

A 1200×675 PNG of this kind is ~50 KB. 24 templates ≈ **1.2 MB**; even four
revisions each is ~5 MB. That is nothing. GitHub only warns past 1 GB.

- **Commit the PNGs to the repo normally.**
- **Do not use Git LFS.** It would actively hurt: the free LFS tier is 1 GB
  bandwidth/month, and every CI checkout pulls LFS objects, so ~1,440 runs/month
  would blow the quota on files that are trivially small in plain git.
- `actions/checkout` defaults to depth 1, so repo history size never affects CI
  checkout time.

The one caveat: templates are binary, so git cannot diff or merge them. Two
people editing the same template concurrently means one overwrites the other.
With one owner this is a non-issue.

### 8.4 Repo visibility

If the repo is **public**, Actions minutes are unlimited and free, and §8.2's
budget stops mattering. Nothing here is secret — the code, the templates and
`users.yaml` are all publishable. All credentials live in Actions secrets, which
are never in the repo.

**Recommend public unless the curation list itself is competitively sensitive.**
If it must be private, the caching and rotation above keep it inside 2,000
minutes; also drop the cron to hourly.

---

## 9. `.github/workflows/post.yml`

```yaml
on:
  schedule:
    - cron: "*/30 * * * *"
  workflow_dispatch:        # manual run button; needed for testing

permissions:
  contents: write           # to commit state.json back

concurrency:
  group: tweet-cards
  cancel-in-progress: false # never cancel mid-post
```

Steps: checkout → setup-python (pip cache) → cache Playwright → install →
run pipeline → commit `state.json` if changed, with `[skip ci]` in the message.

Secrets: `GETXAPI_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

Note: GitHub delays scheduled runs under load. Treat the cron as "at least this
often", never as precise timing. Do not build anything that assumes exact
intervals.

**Do not deploy this to Vercel.** Vercel Hobby cron is capped at once per day —
more frequent expressions fail at deploy time — and timing is only accurate to
±59 minutes.

---

## 10. `tools/preview.py`

A CLI to iterate on templates and zones without touching any API:

```bash
python tools/preview.py --handle naval --text "some test post" --open
python tools/preview.py --handle naval --file long_post.txt
python tools/preview.py --handle naval --lorem 1200   # generate N chars
```

Prints the chosen part count and font size, writes PNGs to `out/`. This is what
someone will use when adding each of the 20+ templates, so make it pleasant:
clear output, helpful errors on a bad zone.

---

## 11. Tests

`tests/test_split.py` — pure logic, no browser:

- splitting never cuts mid-word
- paragraph breaks are preferred over sentence breaks over word breaks
- `parts=1` returns the input unchanged
- chunks reassemble to the original text (modulo whitespace) when not truncated
- text with no whitespace at all does not crash

`tests/test_config.py`:

- a zone outside the canvas is rejected
- a wrong-size template is rejected
- duplicate handles are rejected
- `defaults` inheritance works

Skip browser-dependent tests in CI unless Chromium is already cached.

---

## 12. Acceptance criteria

Done means all of these hold:

1. A 65-char post → **1 card**, no badge, font at or near `MAX_FONT`.
2. A ~1,150-char post → **4 cards** at ~31px, each cut on a paragraph or
   sentence boundary, badged `1/4 … 4/4`, delivered as one album.
3. Running the pipeline twice in a row posts **nothing** the second time.
4. A post containing emoji and Japanese renders both correctly — no tofu boxes.
5. A tweet containing `<script>` renders as literal text, not as markup.
6. `users.yaml` with a zone outside the canvas fails at startup with a message
   naming the offending user.
7. One user's GetXAPI failure does not prevent the other 19 from posting.
8. A no-new-posts run completes in under 45 seconds on a GitHub runner.
9. `tools/preview.py` renders a card with no network access and no secrets.

---

## 13. Explicitly out of scope

Do not build: a web UI, a database, a queue, Docker, an admin panel, an
abstraction layer over multiple social platforms, or a plugin system for
templates. This is a cron job that makes pictures. Keep it under ~600 lines of
Python.

---

## 14. Open questions to raise, not guess

Ask before implementing:

- What should a **quote-tweet** render as — the quoted text too, or just the
  author's own words?
- What about posts that are **only an image or video** with no text?
- Should a **thread** (self-reply chain) be treated as one long post?
