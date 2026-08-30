"""
check_keys.py — Tamil Nadu political tweet cleaner + highlighter.

Pipeline:
    regex_clean()  -> deterministic removal (URLs, trailing hashtags, CTAs)
    highlight()    -> LLM adds **markers** only; text must come back identical

Setup:
    pip install openai
    $env:GEMINI_KEY="AIza..."      # PowerShell
    $env:GROQ_KEY="gsk_..."
    python check_keys.py
"""

import os
import re
import sys
import time

try:
    from openai import OpenAI
except ImportError:
    sys.exit("Missing dependency. Run:  pip install openai")


PROVIDERS = [
    {
        "label": "Gemini Flash-Lite",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key_env": "GEMINI_KEY",
        "model": "gemini-flash-lite-latest",
    },
    {
        "label": "Groq gpt-oss-120b",
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_KEY",
        "model": "openai/gpt-oss-120b",
    },
]


# ---------------------------------------------------------------- prompt

PROMPT = """You add emphasis markers to Tamil Nadu political news text for an image card.

Your ONLY job is to wrap short spans in **double asterisks**. The text is already
cleaned. Do not remove, add, translate, rephrase, reorder, or correct anything.

HOW MANY SPANS - scale to length:
- Under 10 words: exactly 1 span
- 10 to 20 words: 1 or 2 spans
- Over 20 words: 2 to 4 spans
Fewer is better. Sparse highlights create contrast; dense ones create noise.

WHAT TO MARK, in priority order:
1. The decisive fact - the qualifier, condition or exception that carries the
   point. Phrases beginning "without", "despite", "only if", "even after",
   "instead of" usually hold it.
2. The named actor or institution - who did it.
3. The outcome - the office, figure or verdict.
Mark the qualifier over the actor when the tweet's news value sits there.

HARD RULES:
- Each span is 1 to 5 words.
- Never merge a person's name and a location into one span.
- Never mark a full clause or sentence.
- Never mark an evaluative word (derogatory, shocking, brave, disgraceful)
  unless it sits inside a direct quotation.
- Never mark a qualifier that implies wrongdoing unless it is inside a
  direct quotation.
- Do NOT fact-check or alter names, titles or designations. If the text says
  someone holds a post, keep it exactly as written.
- Tamil stays in Tamil, character for character. Do not fix apparent typos.
- Output ONLY the marked-up text. No quotes around it, no commentary.

EXAMPLES
In:  TN CM Vijay met Union Home Minister Amit Shah
Out: **TN CM Vijay** met Union Home Minister Amit Shah

In:  Study says Tamil Nadu can hit $1.5 trillion economy without Parandur airport
Out: Study says Tamil Nadu can hit **$1.5 trillion economy** **without Parandur airport**

Text:
{text}"""


# ---------------------------------------------------------------- regex layer

URL = re.compile(r"https?://\S+|t\.co/\S+|pic\.twitter\.com/\S+")
TRAIL = re.compile(
    r"\s*(watch|read|read more|full story|link in bio|via|more|thread)"
    r"\s*[:\-\u2013|]?\s*$",
    re.IGNORECASE,
)
# Anchored to $ — only strips a hashtag run at the very END.
# Inline tags such as "Congress slams #DMK over the bill" are preserved.
HASHTAG_BLOCK = re.compile(r"(\s*#[\w\u0b80-\u0bff]+)+\s*$")
HANDLES_END = re.compile(r"(\s+@\w+)+\s*$")


def regex_clean(text):
    text = URL.sub("", text)
    text = re.sub(r"\s*\n\s*\n+", "\n\n", text)
    for _ in range(3):
        text = TRAIL.sub("", text.strip())
        text = HASHTAG_BLOCK.sub("", text.strip())
    text = HANDLES_END.sub("", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


# ---------------------------------------------------------------- LLM layer

def expected_spans(text):
    words = len(text.split())
    if words < 10:
        return 1, 1
    if words <= 20:
        return 1, 2
    return 2, 4


def sane_output(out, cleaned_input):
    """Strict: stripping ** must reproduce the input exactly."""
    if not out:
        return False, "empty response"
    if out.count("**") % 2 != 0:
        return False, "unpaired ** marker"
    if out.replace("**", "") != cleaned_input:
        return False, "text was altered, not just marked"
    n = out.count("**") // 2
    lo, hi = expected_spans(cleaned_input)
    if not (lo <= n <= hi):
        return False, str(n) + " spans, want " + str(lo) + "-" + str(hi)
    return True, "ok"


def call_provider(provider, text, timeout=20):
    key = os.environ.get(provider["key_env"])
    if not key:
        raise RuntimeError(provider["key_env"] + " not set")
    client = OpenAI(base_url=provider["base_url"], api_key=key, timeout=timeout)
    resp = client.chat.completions.create(
        model=provider["model"],
        messages=[{"role": "user", "content": PROMPT.format(text=text)}],
        temperature=0,
    )
    return (resp.choices[0].message.content or "").strip()


def highlight(cleaned, verbose=True):
    """Add ** markers. Falls back to plain cleaned text if all providers fail."""
    for provider in PROVIDERS:
        try:
            out = call_provider(provider, cleaned)
            ok, reason = sane_output(out, cleaned)
            if ok:
                return out
            if verbose:
                print("      [" + provider["label"] + "] rejected: " + reason)
        except Exception as exc:
            if verbose:
                print("      [" + provider["label"] + "] failed: "
                      + type(exc).__name__ + ": " + str(exc)[:60])
    return cleaned  # degrade gracefully: correct text, no highlights


def process(raw):
    return highlight(regex_clean(raw))


# ---------------------------------------------------------------- tests

TESTS = [
    "TN CM Vijay met Union Home Minister Amit Shah",
    "Felix Gerald appointed as Chairman for State Minorities Commission.",
    "Thanjavur cops arrive at Leader of the Opposition Udhayanidhi Stalin\u2019s "
    "residence  A case has been registered against him for his derogatory "
    "remarks about women.",
    "Study says Tamil Nadu can hit $1.5 trillion economy without Parandur "
    "airport https://t.co/xyz789 #TamilNadu #Parandur",
    # inline hashtag must SURVIVE, trailing block must go
    "Congress slams #DMK over the delimitation bill in Delhi today "
    "#TamilNadu #Politics",
    # Tamil verbatim check
    "\u0ba4\u0bae\u0bbf\u0bb4\u0b95 \u0bae\u0bc1\u0ba4\u0bb2\u0bcd\u0bb5\u0bb0\u0bcd "
    "\u0bb5\u0bbf\u0b9c\u0baf\u0bcd \u0b9f\u0bbf\u0bb2\u0bcd\u0bb2\u0bbf\u0baf\u0bbf\u0bb2\u0bcd "
    "\u0b85\u0bae\u0bbf\u0ba4\u0bcd \u0bb7\u0bbe\u0bb5\u0bc8 "
    "\u0b9a\u0ba8\u0bcd\u0ba4\u0bbf\u0ba4\u0bcd\u0ba4\u0bbe\u0bb0\u0bcd "
    "Watch: https://t.co/abc123",
]


def check_keys():
    print("=" * 70)
    print("KEY CHECK")
    print("=" * 70)
    for p in PROVIDERS:
        if not os.environ.get(p["key_env"]):
            print("[SKIP] " + p["label"].ljust(20) + p["key_env"] + " not set")
            continue
        start = time.time()
        try:
            client = OpenAI(base_url=p["base_url"],
                            api_key=os.environ[p["key_env"]], timeout=20)
            r = client.chat.completions.create(
                model=p["model"],
                messages=[{"role": "user", "content": "Say: ok"}],
                temperature=0,
            )
            ms = int((time.time() - start) * 1000)
            reply = (r.choices[0].message.content or "").strip()
            print("[ OK ] " + p["label"].ljust(20) + str(ms).rjust(5)
                  + "ms  reply=" + repr(reply[:30]))
        except Exception as exc:
            print("[FAIL] " + p["label"].ljust(20) + str(exc)[:70])
    print()


def main():
    check_keys()
    print("=" * 70)
    print("PIPELINE  (regex clean -> LLM highlight)")
    print("=" * 70)
    fallbacks = 0
    for raw in TESTS:
        cleaned = regex_clean(raw)
        final = highlight(cleaned)
        if final == cleaned:
            fallbacks += 1
        print("\n  RAW   : " + raw)
        if cleaned != raw:
            print("  CLEAN : " + cleaned)
        print("  FINAL : " + final)
    print("\n  unhighlighted fallbacks: " + str(fallbacks) + "/" + str(len(TESTS)))
    print()


if __name__ == "__main__":
    main()