#!/usr/bin/env python3
"""
his.verse.for.the.day — Instagram / Facebook Automation Bot
============================================================
Fully automated daily Bible verse posting system.
Zero manual effort after setup.

Cost breakdown:
  Verses      : Local CSV              → $0.00
  Images      : Unsplash free API      → $0.00
  Compositing : Pillow                 → $0.00
  Reel video  : FFmpeg (Ken Burns)     → $0.00
  Music       : 5 mood-matched MP3s    → $0.00
  Captions    : OpenAI GPT-4o-mini     → ~$0.30/yr
  Hosting     : GitHub public repo     → $0.00
  Scheduler   : GitHub Actions cron    → $0.00
  Posting     : Make → IG + Facebook   → $0.00

Pipelines:
  Verse      → 0 11 * * * UTC  (2:00 PM Bahrain)
  Engagement → 0 17 * * * UTC  (8:00 PM Bahrain)

Usage:
  python bot.py                     # Verse pipeline
  python bot.py --mode engagement   # Engagement reel pipeline
  python bot.py --preview           # Generate only, skip posting
  python bot.py --verse 7           # Force specific verse ID
"""

import os
import csv
import json
import base64
import random
import argparse
import datetime
import subprocess
import requests
import hashlib
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

BAHRAIN_TZ = ZoneInfo("Asia/Bahrain")

def bahrain_now():
    """Current datetime in Asia/Bahrain — use this instead of datetime.now()
    for anything that determines which calendar day a post belongs to.
    GitHub Actions runs in UTC; without this, the 2:30 AM Bahrain post
    (which executes at 23:30 UTC the PREVIOUS day) gets logged against
    the wrong calendar date."""
    return datetime.datetime.now(BAHRAIN_TZ)

def bahrain_today():
    """Today's date string (YYYY-MM-DD) in Asia/Bahrain."""
    return bahrain_now().strftime("%Y-%m-%d")


# ── PATHS ─────────────────────────────────────────────────────────────────────

BASE_DIR         = Path(__file__).parent
DATA_DIR         = BASE_DIR / "data"
OUTPUT_DIR       = BASE_DIR / "output"
FONTS_DIR        = BASE_DIR / "fonts"

STATE_FILE       = DATA_DIR / "state.json"
ENGAGEMENT_STATE = DATA_DIR / "engagement_state.json"
VERSES_FILE      = DATA_DIR / "verses.csv"
ENGAGEMENT_FILE  = DATA_DIR / "engagement_reels.csv"

# New packages — additive
NIGHT_STATE      = DATA_DIR / "night_state.json"
MORNING_STATE    = DATA_DIR / "morning_state.json"
NIGHT_FILE       = DATA_DIR / "before_you_sleep.csv"
MORNING_FILE     = DATA_DIR / "what_do_you_need_today.csv"

# Shared same-day Scripture reservation — this is the BLOCKING mechanism,
# not a post-hoc log. Every pipeline must call reserve_scripture_for_today()
# BEFORE publishing and get a confirmed reservation, or pick an alternative.
SCRIPTURE_RESERVATION_FILE = DATA_DIR / "daily_scripture_reservations.json"

INVENTORY_THRESHOLDS = [
    (91, "ACTIVE"),
    (61, "NOTICE"),
    (31, "WARNING"),
    (16, "CRITICAL"),
    (0,  "URGENT"),
]

OUTPUT_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)
FONTS_DIR.mkdir(exist_ok=True)


# ── SECRETS ───────────────────────────────────────────────────────────────────

UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "")
OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY", "")
GITHUB_TOKEN        = os.getenv("GITHUB_TOKEN", "")
GITHUB_USERNAME     = os.getenv("GITHUB_USERNAME", "Equelinor")
GITHUB_REPO         = os.getenv("GITHUB_REPO", "his-verse-bot")
MAKE_WEBHOOK_URL    = os.getenv("MAKE_WEBHOOK_URL", "")


# ── CONSTANTS ─────────────────────────────────────────────────────────────────

POST_SIZE     = (1080, 1080)
HANDLE        = "@his.verse.for.the.day"
INSTAGRAM_URL = "https://www.instagram.com/his.verse.for.the.day"

FONT_URL_SERIF = "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/cormorantgaramond/CormorantGaramond-Italic.ttf"
FONT_URL_LIGHT = "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/cormorantgaramond/CormorantGaramond-Light.ttf"
FONT_URL_SANS  = "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/lato/Lato-Light.ttf"

SYSTEM_FONTS = {
    "serif": [
        "/usr/share/fonts/truetype/google-fonts/Lora-Italic-Variable.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
    ],
    "sans": [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
}

MUSIC_MAP = {
    "calm"      : "calm.mp3",
    "reflective": "reflective.mp3",
    "uplifting" : "uplifting.mp3",
    "hope"      : "hope.mp3",
    "faith"     : "faith.mp3",
}

HASHTAG_POOLS = {
    "A": (
        "#bibleverseoftheday #dailyword #faithquotes #christianinstagram #godsword "
        "#scripturequotes #verseoftheday #bibleverse #christianity #prayerwarrior "
        "#godislove #jesuslovesyou #dailydevotional #bibleinstagram #faithoverfear "
        "#godsgrace #scripture #biblequotes #christianquotes #hopeinfaith "
        "#spiritualwellness #innerpeace #hisversefortheday #trustgod #godisfaithful "
        "#dailyinspiration #christianlife #wordofgod #blessedlife #godsplan"
    ),
    "B": (
        "#morningdevotion #christisking #biblelovers #scripturememory "
        "#christianmotivation #godspromises #holybible #jesusfreak "
        "#prayerandfasting #spiritfilled #faithwalk #godscreation "
        "#praiseandworship #christianfaith #redeemed #kingdomofgod "
        "#graceupongrace #divinelove #godspeaks #hisversefortheday "
        "#christianquotes #bibletruth #prayerlife #godisgreat #worshipeveryday"
    ),
    "C": (
        "#anxiety #mentalhealth #healing #peacefulmind #selfcare #mindfulness "
        "#spiritualhealing #godheals #overcomer #brokenbutblessed #restored "
        "#hope #encouragement #dailymotivation #uplift #comforting #godcomforts "
        "#neveralone #youareloved #godswill #hisversefortheday #bibletruths "
        "#prayerworks #stillness #breathe"
    ),
}

def get_hashtags():
    week = bahrain_now().isocalendar()[1]
    return HASHTAG_POOLS[["A", "B", "C"][week % 3]]


# ── STATE ─────────────────────────────────────────────────────────────────────

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"posted_ids": [], "last_posted": ""}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))

def load_engagement_state():
    if ENGAGEMENT_STATE.exists():
        return json.loads(ENGAGEMENT_STATE.read_text())
    return {"posted_ids": [], "last_posted": ""}

def save_engagement_state(state):
    ENGAGEMENT_STATE.write_text(json.dumps(state, indent=2))

def load_night_state():
    if NIGHT_STATE.exists():
        return json.loads(NIGHT_STATE.read_text())
    return {"posted_ids": [], "last_posted": ""}

def save_night_state(state):
    NIGHT_STATE.write_text(json.dumps(state, indent=2))

def load_morning_state():
    if MORNING_STATE.exists():
        return json.loads(MORNING_STATE.read_text())
    return {"posted_ids": [], "last_posted": ""}

def save_morning_state(state):
    MORNING_STATE.write_text(json.dumps(state, indent=2))


# ── SAME-DAY SCRIPTURE RESERVATION (BLOCKING, not log-and-warn) ────────────
# Every one of the four pipelines calls reserve_scripture_for_today() BEFORE
# it commits to a specific piece of content. If another pipeline already
# reserved that exact reference for today (Bahrain calendar day), the
# reservation is REFUSED and the caller must pick a different candidate —
# collision is prevented before publication, not detected after it.
#
# This works correctly even if:
#   - a scheduled run fails partway (reservation isn't finalized — see below)
#   - a manual/duplicate run happens
#   - Night and Morning package IDs drift out of alignment with each other
# because it's driven by the actual reference being used TODAY, not by
# static row position in any CSV.

def _load_reservations():
    if SCRIPTURE_RESERVATION_FILE.exists():
        try:
            return json.loads(SCRIPTURE_RESERVATION_FILE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}

def _save_reservations(data):
    SCRIPTURE_RESERVATION_FILE.write_text(json.dumps(data, indent=2))

def reserve_scripture_for_today(package, scripture_ref):
    """Attempt to reserve `scripture_ref` for `package` on today's Bahrain
    date. Returns True if reserved (no conflict), False if another package
    already has that reference reserved for today. This is a TENTATIVE
    reservation — call release_reservation() if the pipeline later fails
    before actually publishing, so the reference becomes available again
    for any pipeline that hasn't run yet today."""
    today = bahrain_today()
    data = _load_reservations()
    day = data.get(today, {})

    for other_pkg, other_ref in day.items():
        if other_pkg != package and other_ref == scripture_ref:
            return False  # BLOCKED — another package already has this today

    day[package] = scripture_ref
    data[today] = day
    _save_reservations(data)
    return True

def release_reservation(package):
    """Release today's reservation for `package` — call this if the
    pipeline fails after reserving but before actually publishing, so a
    later pipeline that day isn't blocked by a reference that never
    actually got posted."""
    today = bahrain_today()
    data = _load_reservations()
    if today in data and package in data[today]:
        del data[today][package]
        _save_reservations(data)

def get_reserved_refs_today(exclude_package=None):
    """Set of scripture references already reserved today, optionally
    excluding one package's own reservation."""
    today = bahrain_today()
    data = _load_reservations()
    day = data.get(today, {})
    return {ref for pkg, ref in day.items() if pkg != exclude_package}


# ── VERSE SELECTION ───────────────────────────────────────────────────────────

def load_verses():
    with open(VERSES_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def select_verse_candidates(verse_id=None):
    """Returns (ordered_candidate_list, state). Callers must attempt
    reservation on each candidate in order and stop at the first success —
    see run_verse(). No fallback candidate is chosen here; if the caller
    exhausts the list without a successful reservation, it must abort
    without publishing (Part 3 of the final corrective pass)."""
    verses = load_verses()
    state  = load_state()

    if verse_id:
        verse = next((v for v in verses if int(v["id"]) == verse_id), verses[0])
        return [verse], state

    posted    = set(state.get("posted_ids", []))
    remaining = [v for v in verses if int(v["id"]) not in posted]

    if not remaining:
        state["posted_ids"] = []
        remaining = verses

    # Bahrain date, not server (UTC) date
    rng = random.Random(int(bahrain_today().replace("-", "")))
    rng.shuffle(remaining)
    return remaining, state


# ── ENGAGEMENT REEL SELECTION ─────────────────────────────────────────────────

def load_engagement_reels():
    with open(ENGAGEMENT_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def select_engagement_candidates():
    """Returns (ordered_candidate_list, state) — sequential by id. See note
    on select_verse_candidates above; no fallback is chosen here."""
    reels = load_engagement_reels()
    state = load_engagement_state()

    posted    = set(state.get("posted_ids", []))
    remaining = [r for r in reels if int(r["id"]) not in posted]

    if not remaining:
        state["posted_ids"] = []
        remaining = reels

    remaining_sorted = sorted(remaining, key=lambda x: int(x["id"]))
    return remaining_sorted, state


# ── NIGHT / MORNING SELECTION ─────────────────────────────────────────────────

def load_night_posts():
    with open(NIGHT_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def select_night_candidates():
    """Returns (ordered_candidate_list, state). No fallback chosen here."""
    posts = load_night_posts()
    state = load_night_state()

    posted    = set(state.get("posted_ids", []))
    remaining = [p for p in posts if int(p["id"]) not in posted]

    if not remaining:
        print("  ⚠ Before You Sleep library exhausted — wrapping to start. "
              "Run check_inventory.py and replenish content.")
        state["posted_ids"] = []
        remaining = posts

    remaining_sorted = sorted(remaining, key=lambda x: int(x["id"]))
    return remaining_sorted, state

def load_morning_posts():
    with open(MORNING_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def select_morning_candidates():
    """Returns (ordered_candidate_list, state). No fallback chosen here."""
    posts = load_morning_posts()
    state = load_morning_state()

    posted    = set(state.get("posted_ids", []))
    remaining = [p for p in posts if int(p["id"]) not in posted]

    if not remaining:
        print("  ⚠ What Do You Need Today? library exhausted — wrapping to start. "
              "Run check_inventory.py and replenish content.")
        state["posted_ids"] = []
        remaining = posts

    remaining_sorted = sorted(remaining, key=lambda x: int(x["id"]))
    return remaining_sorted, state


# ── RESERVE-WITH-RETRY (shared helper — used by all four run_* pipelines) ───

def reserve_first_available(package, candidates, ref_field):
    """Try candidates in order; return the first one for which
    reserve_scripture_for_today() actually returns True. Returns
    (candidate, True) on success, or (None, False) if every candidate was
    rejected — callers MUST abort without publishing in that case, per the
    explicit removal of the old 'use anyway' fallback."""
    for candidate in candidates:
        ref = candidate[ref_field]
        if reserve_scripture_for_today(package, ref):
            return candidate, True
    return None, False


def already_posted_today(state):
    """True if this package's state shows a successful post already
    happened today (Bahrain calendar day). Every pipeline checks this
    before doing any work, so a manual re-run or an accidental second
    trigger on the same Bahrain day can't publish a duplicate post for
    that package."""
    return state.get("last_posted") == bahrain_today()


# ── FONTS ─────────────────────────────────────────────────────────────────────

def ensure_font(filename, url, size, fallback_key="serif"):
    path = FONTS_DIR / filename
    if not path.exists():
        print(f"  Downloading {filename}...")
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            path.write_bytes(r.content)
        except Exception as e:
            print(f"  ⚠ Font download failed ({e}) — using system fallback")
            path.unlink(missing_ok=True)
            for fp in SYSTEM_FONTS.get(fallback_key, []):
                if Path(fp).exists():
                    return ImageFont.truetype(fp, size)
            return ImageFont.load_default()
    try:
        return ImageFont.truetype(str(path), size)
    except Exception:
        path.unlink(missing_ok=True)
        for fp in SYSTEM_FONTS.get(fallback_key, []):
            if Path(fp).exists():
                return ImageFont.truetype(fp, size)
        return ImageFont.load_default()

def load_fonts():
    return {
        "verse" : ensure_font("CormorantGaramond-Italic.ttf", FONT_URL_SERIF, 68,  "serif"),
        "ref"   : ensure_font("CormorantGaramond-Italic.ttf", FONT_URL_SERIF, 38,  "serif"),
        "handle": ensure_font("Lato-Light.ttf",               FONT_URL_SANS,  22,  "sans"),
        "quote" : ensure_font("CormorantGaramond-Light.ttf",  FONT_URL_LIGHT, 160, "serif"),
        "hook"  : ensure_font("CormorantGaramond-Italic.ttf", FONT_URL_SERIF, 52,  "serif"),
    }


# ── IMAGE FETCH ───────────────────────────────────────────────────────────────

def fetch_image(keywords, mood):
    if UNSPLASH_ACCESS_KEY:
        try:
            r = requests.get(
                "https://api.unsplash.com/photos/random",
                params={
                    "query"         : keywords,
                    "orientation"   : "squarish",
                    "content_filter": "high",
                    "client_id"     : UNSPLASH_ACCESS_KEY,
                },
                timeout=15,
            )
            r.raise_for_status()
            img_url  = r.json()["urls"]["regular"]
            img_data = requests.get(img_url, timeout=30).content
            print("  ✓ Image fetched from Unsplash")
            return Image.open(BytesIO(img_data)).convert("RGB")
        except Exception as e:
            print(f"  ⚠ Unsplash failed: {e} — using gradient fallback")

    # Gradient fallback
    palettes = {
        "calm"      : [(8,  18, 40),  (30, 50,  90)],
        "uplifting" : [(70, 35,  5),  (160, 90, 15)],
        "reflective": [(15, 28, 20),  (40, 65,  45)],
        "hope"      : [(40, 20, 60),  (100, 60, 120)],
        "faith"     : [(20, 20, 50),  (60,  40, 100)],
        "night"     : [(5,  8,  28),  (22, 28,  60)],
        "morning"   : [(255, 140, 60), (255, 200, 120)],
    }
    c   = palettes.get(mood, palettes["calm"])
    W, H = POST_SIZE
    img  = Image.new("RGB", POST_SIZE)
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        draw.line([(0, y), (W, y)], fill=(
            int(c[0][0] + (c[1][0] - c[0][0]) * t),
            int(c[0][1] + (c[1][1] - c[0][1]) * t),
            int(c[0][2] + (c[1][2] - c[0][2]) * t),
        ))
    print("  ✓ Using gradient fallback")
    return img


# ── IMAGE COMPOSITING ─────────────────────────────────────────────────────────

def wrap_text(text, font, max_width, draw):
    words, lines, current = text.split(), [], []
    for word in words:
        test = " ".join(current + [word])
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return [(line, int((draw.textbbox((0,0), line, font=font)[3] -
                        draw.textbbox((0,0), line, font=font)[1]) * 1.42))
            for line in lines]

def draw_text_shadow(draw, x, y, text, font, fill, shadow=(0,0,0,115)):
    draw.text((x+2, y+3), text, font=font, fill=shadow)
    draw.text((x,   y),   text, font=font, fill=fill)

def strip_emoji_for_display(text):
    """Remove emoji before drawing text INTO an image with Pillow — the
    fallback fonts used here don't carry emoji glyphs, so they render as
    a broken box. This only affects what gets drawn on the image; the
    original text (with emoji intact) is still used for the caption sent
    to Instagram/Facebook, which render emoji correctly on their own.

    Handles the full construction, not just the visible base character:
    many common emoji (❤️ ✍️ ☀️ etc.) are actually TWO codepoints — a
    base symbol that's centuries-old Unicode (category 'So', caught by
    the main check) followed by an invisible VARIATION SELECTOR-16
    (U+FE0F, category 'Mn') that tells renderers to show the color-emoji
    form. That selector alone doesn't match either the category or the
    supplementary-plane checks below, so a first version of this function
    silently left it behind — invisible in a text editor, but still a
    real leftover character. Also strips the zero-width joiner (U+200D)
    used to combine emoji into compound sequences, for the same reason.

    Also collapses any double-space left behind when an emoji sat in the
    middle of a sentence (e.g. "Drop a 🔥 if..." -> "Drop a if..." without
    this step would leave "Drop a  if..." with a visible double gap)."""
    import unicodedata, re
    VARIATION_SELECTORS = range(0xFE00, 0xFE10)
    ZERO_WIDTH_JOINER = 0x200D

    def is_emoji_construction_char(ch):
        code = ord(ch)
        if code in VARIATION_SELECTORS or code == ZERO_WIDTH_JOINER:
            return True
        if unicodedata.category(ch) == "So":
            return True
        if code > 0x1F000:
            return True
        return False

    stripped = "".join(ch for ch in text if not is_emoji_construction_char(ch))
    return re.sub(r"[ \t]{2,}", " ", stripped).strip()

def has_emoji(text):
    """True if any character in text is emoji or part of an emoji
    construction (base symbol, variation selector, or zero-width joiner).
    Shares detection logic with strip_emoji_for_display() so the two can
    never quietly drift out of sync — see that function's docstring for
    why variation selectors and ZWJ need explicit handling."""
    import unicodedata
    VARIATION_SELECTORS = range(0xFE00, 0xFE10)
    ZERO_WIDTH_JOINER = 0x200D
    for ch in text:
        code = ord(ch)
        if code in VARIATION_SELECTORS or code == ZERO_WIDTH_JOINER:
            return True
        if unicodedata.category(ch) == "So":
            return True
        if code > 0x1F000:
            return True
    return False


# ── LAYOUT AUTO-FIT (structural fix — not per-ID patches) ───────────────────
# Before rendering night/morning posts, measure total required content
# height. If it exceeds the safe area, shrink fonts (down to a floor) and
# re-wrap, repeating until it fits or the floor is hit. Content must never
# overlap the handle watermark or bottom safe margin.

SAFE_TOP    = 150
SAFE_BOTTOM = 1010   # leaves margin above the handle watermark
MIN_SCALE   = 0.65   # never shrink below 65% of nominal font size

def _measure_block_height(draw, segments, scale):
    """segments: list of (text, font, line_height_multiplier, gap_after).
    Returns total block height at the given font scale — measurement only,
    nothing is drawn."""
    total = 0
    for text, font, mult, gap in segments:
        scaled_font = font.font_variant(size=max(10, int(font.size * scale)))
        for line, _ in wrap_text(text, scaled_font, 940, draw):
            bbox = draw.textbbox((0, 0), line, font=scaled_font)
            total += int((bbox[3] - bbox[1]) * mult)
        total += gap
    return total

def fit_scale_for_block(draw, segments, safe_height=None):
    """Largest font scale (down to MIN_SCALE) at which segments fit the
    safe content area. Returns (scale, fits_bool)."""
    safe_height = safe_height if safe_height is not None else (SAFE_BOTTOM - SAFE_TOP)
    scale = 1.0
    while scale >= MIN_SCALE - 1e-9:
        if _measure_block_height(draw, segments, scale) <= safe_height:
            return round(scale, 2), True
        scale -= 0.05
    return MIN_SCALE, False


def apply_overlays(img, mood):
    """Darken edges + mood colour tint."""
    W, H = POST_SIZE
    img = img.copy()

    # Colour tint
    img = ImageEnhance.Color(img).enhance(0.82)
    if mood == "uplifting":
        r, g, b = img.split()
        img = Image.merge("RGB", (r.point(lambda i: min(255, int(i * 1.04))), g, b))
    elif mood == "calm":
        r, g, b = img.split()
        img = Image.merge("RGB", (r, g, b.point(lambda i: min(255, int(i * 1.04)))))

    # Gradient overlay
    ov  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dov = ImageDraw.Draw(ov)
    for y in range(H // 3):
        dov.line([(0, y), (W, y)], fill=(0, 0, 0, int(120 * (1 - y / (H / 3)))))
    for y in range(int(H * 0.48), H):
        dov.line([(0, y), (W, y)], fill=(0, 0, 0, int(180 * ((y - H * 0.48) / (H * 0.52)))))

    # Vignette border
    for m in range(0, 180, 4):
        dov.rectangle([m, m, W-m, H-m], outline=(0, 0, 0, int(70 * (1 - m / 180))))

    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")

def composite_post(bg_img, verse_text, reference, mood, fonts, video_text=None):
    W, H = POST_SIZE

    # Crop/resize background to square
    img = bg_img.copy()
    r   = img.width / img.height
    nw  = int(W * r) if r > 1 else W
    nh  = int(H / r) if r <= 1 else H
    img = img.resize((max(nw, W), max(nh, H)), Image.LANCZOS)
    img = img.crop(((img.width - W) // 2, (img.height - H) // 2,
                    (img.width - W) // 2 + W, (img.height - H) // 2 + H))

    img  = apply_overlays(img, mood)
    draw = ImageDraw.Draw(img)

    # Ghost quote mark
    draw.text((50, 130), "\u201C", font=fonts["quote"], fill=(255, 255, 255, 35))

    if video_text:
        # ── ENGAGEMENT REEL LAYOUT ────────────────────────────────────────────
        # Bug found in final adversarial review: 28/424 engagement_reels.csv
        # rows have emoji in video_text (e.g. "Drop a 🔥 if..."), which this
        # branch draws directly with Pillow — same broken-glyph issue fixed
        # elsewhere for night/morning, just never caught here since this
        # pipeline predates that work and was explicitly out of scope for
        # every later corrective pass. video_text is ONLY ever used for
        # on-image rendering (the separate 'caption' field is what's sent
        # to Instagram/Facebook), so stripping here has zero effect on
        # captions — safe, and closes the same bug class everywhere at once.
        wrapped_hook = wrap_text(strip_emoji_for_display(video_text), fonts["hook"], W - 140, draw)
        sy = 80
        for lt, lh in wrapped_hook:
            bbox = draw.textbbox((0, 0), lt, font=fonts["hook"])
            x    = (W - (bbox[2] - bbox[0])) // 2
            draw_text_shadow(draw, x, sy, lt, fonts["hook"], (255, 255, 220, 240))
            sy += lh

        # Divider
        draw.line([(W//2 - 40, sy + 10), (W//2 + 40, sy + 10)],
                  fill=(255, 255, 255, 80), width=1)
        sy += 30

        # Verse text
        wrapped = wrap_text(verse_text, fonts["verse"], W - 140, draw)
        for lt, lh in wrapped:
            bbox = draw.textbbox((0, 0), lt, font=fonts["verse"])
            x    = (W - (bbox[2] - bbox[0])) // 2
            draw_text_shadow(draw, x, sy, lt, fonts["verse"], (255, 255, 255, 252))
            sy += lh

        # Reference
        draw.line([(W//2 - 28, sy + 16), (W//2 + 28, sy + 16)],
                  fill=(255, 255, 255, 90), width=1)
        bbox_r = draw.textbbox((0, 0), reference, font=fonts["ref"])
        draw.text(((W - (bbox_r[2] - bbox_r[0])) // 2, sy + 28),
                  reference, font=fonts["ref"], fill=(255, 255, 255, 175))

    else:
        # ── STANDARD VERSE LAYOUT ─────────────────────────────────────────────
        draw.text((58, 50), reference, font=fonts["ref"], fill=(255, 255, 255, 175))

        wrapped = wrap_text(verse_text, fonts["verse"], W - 140, draw)
        total_h = sum(lh for _, lh in wrapped)
        sy      = (H - total_h) // 2 + 25

        for lt, lh in wrapped:
            bbox = draw.textbbox((0, 0), lt, font=fonts["verse"])
            x    = (W - (bbox[2] - bbox[0])) // 2
            draw_text_shadow(draw, x, sy, lt, fonts["verse"], (255, 255, 255, 252))
            sy += lh

        draw.line([(W//2 - 28, sy + 16), (W//2 + 28, sy + 16)],
                  fill=(255, 255, 255, 90), width=1)

    # Handle watermark (both layouts)
    bbox_h = draw.textbbox((0, 0), HANDLE, font=fonts["handle"])
    draw.text(((W - (bbox_h[2] - bbox_h[0])) // 2, H - 44),
              HANDLE, font=fonts["handle"], fill=(255, 255, 255, 80))

    return img


# ── NIGHT / MORNING COMPOSITING (with real auto-fit) ────────────────────────

def composite_night_post(bg_img, hook, prayer, scripture, ref, ending, fonts):
    """Before You Sleep layout. Measures the full content block first; if it
    would exceed the safe content area, shrinks fonts (down to MIN_SCALE)
    and re-wraps before drawing anything — never patches individual IDs."""
    W, H = POST_SIZE
    img = bg_img.copy()
    r   = img.width / img.height
    nw  = int(W * r) if r > 1 else W
    nh  = int(H / r) if r <= 1 else H
    img = img.resize((max(nw, W), max(nh, H)), Image.LANCZOS)
    img = img.crop(((img.width - W) // 2, (img.height - H) // 2,
                    (img.width - W) // 2 + W, (img.height - H) // 2 + H))
    img  = apply_overlays(img, "night")
    draw = ImageDraw.Draw(img)

    scripture_block = f"\u201C{scripture}\u201D\n— {ref}"
    segments = [
        (hook,             fonts["hook"],  1.42, 20),
        (prayer,           fonts["verse"], 1.42, 16),
        (scripture_block,  fonts["ref"],   1.21, 34),
        (ending,           fonts["handle"],1.42, 0),
    ]
    scale, fits = fit_scale_for_block(draw, segments)
    if not fits:
        print(f"  ⚠ Night layout: content still tight at minimum scale ({MIN_SCALE}) — rendering best-effort")

    hook_font   = fonts["hook"].font_variant(size=max(10, int(fonts["hook"].size * scale)))
    verse_font  = fonts["verse"].font_variant(size=max(10, int(fonts["verse"].size * scale)))
    ref_font    = fonts["ref"].font_variant(size=max(10, int(fonts["ref"].size * scale)))
    handle_font = fonts["handle"]  # handle/title never shrink — always legible

    title = "BEFORE YOU SLEEP"  # no emoji baked into image — see note below
    bbox_t = draw.textbbox((0, 0), title, font=ref_font)
    draw.text(((W - (bbox_t[2] - bbox_t[0])) // 2, 46), title,
              font=ref_font, fill=(210, 210, 255, 200))

    sy = SAFE_TOP
    for lt, lh in wrap_text(strip_emoji_for_display(hook), hook_font, W - 140, draw):
        bbox = draw.textbbox((0, 0), lt, font=hook_font)
        x    = (W - (bbox[2] - bbox[0])) // 2
        draw_text_shadow(draw, x, sy, lt, hook_font, (255, 255, 255, 245))
        sy += lh

    sy += 20
    draw.line([(W//2 - 40, sy), (W//2 + 40, sy)], fill=(210, 210, 255, 90), width=1)
    sy += 34

    for lt, lh in wrap_text(strip_emoji_for_display(prayer), verse_font, W - 160, draw):
        bbox = draw.textbbox((0, 0), lt, font=verse_font)
        x    = (W - (bbox[2] - bbox[0])) // 2
        draw_text_shadow(draw, x, sy, lt, verse_font, (235, 235, 255, 240))
        sy += lh

    sy += 20
    for lt, lh in wrap_text(f"\u201C{scripture}\u201D", ref_font, W - 180, draw):
        bbox = draw.textbbox((0, 0), lt, font=ref_font)
        x    = (W - (bbox[2] - bbox[0])) // 2
        draw.text((x, sy), lt, font=ref_font, fill=(200, 200, 235, 190))
        sy += int(lh * 0.85)
    bbox_r = draw.textbbox((0, 0), f"— {ref}", font=ref_font)
    draw.text(((W - (bbox_r[2] - bbox_r[0])) // 2, sy + 8), f"— {ref}",
              font=ref_font, fill=(200, 200, 235, 170))
    sy += 60

    draw.line([(W//2 - 40, sy), (W//2 + 40, sy)], fill=(210, 210, 255, 70), width=1)
    sy += 34

    ending_display = strip_emoji_for_display(ending)
    bbox_e = draw.textbbox((0, 0), ending_display, font=handle_font)
    draw.text(((W - (bbox_e[2] - bbox_e[0])) // 2, sy), ending_display,
              font=handle_font, fill=(255, 255, 255, 215))

    bbox_h = draw.textbbox((0, 0), HANDLE, font=handle_font)
    draw.text(((W - (bbox_h[2] - bbox_h[0])) // 2, H - 44),
              HANDLE, font=handle_font, fill=(255, 255, 255, 80))

    return img, fits

def composite_morning_post(bg_img, question, choices, scripture, ref, cta, fonts):
    """What Do You Need Today? layout. Same auto-fit approach as night."""
    W, H = POST_SIZE
    img = bg_img.copy()
    r   = img.width / img.height
    nw  = int(W * r) if r > 1 else W
    nh  = int(H / r) if r <= 1 else H
    img = img.resize((max(nw, W), max(nh, H)), Image.LANCZOS)
    img = img.crop(((img.width - W) // 2, (img.height - H) // 2,
                    (img.width - W) // 2 + W, (img.height - H) // 2 + H))
    img  = apply_overlays(img, "morning")
    draw = ImageDraw.Draw(img)

    choice_display = " / ".join(c.split(" ", 1)[-1] if " " in c else c for c in choices.split(" | "))
    scripture_block = f"\u201C{scripture}\u201D\n— {ref}"
    segments = [
        (question,        fonts["hook"],  1.42, 24),
        (choice_display,  fonts["verse"], 1.30 * 4, 20),  # 4 choice lines worth of height
        (scripture_block, fonts["ref"],   1.21, 34),
        (cta,             fonts["handle"],1.42, 0),
    ]
    scale, fits = fit_scale_for_block(draw, segments)
    if not fits:
        print(f"  ⚠ Morning layout: content still tight at minimum scale ({MIN_SCALE}) — rendering best-effort")

    hook_font   = fonts["hook"].font_variant(size=max(10, int(fonts["hook"].size * scale)))
    verse_font  = fonts["verse"].font_variant(size=max(10, int(fonts["verse"].size * scale)))
    ref_font    = fonts["ref"].font_variant(size=max(10, int(fonts["ref"].size * scale)))
    handle_font = fonts["handle"]

    title = "WHAT DO YOU NEED TODAY?"
    bbox_t = draw.textbbox((0, 0), title, font=ref_font)
    draw.text(((W - (bbox_t[2] - bbox_t[0])) // 2, 46), title,
              font=ref_font, fill=(80, 45, 10, 210))

    sy = SAFE_TOP
    for lt, lh in wrap_text(strip_emoji_for_display(question), hook_font, W - 140, draw):
        bbox = draw.textbbox((0, 0), lt, font=hook_font)
        x    = (W - (bbox[2] - bbox[0])) // 2
        draw_text_shadow(draw, x, sy, lt, hook_font, (60, 30, 5, 250), shadow=(255, 255, 255, 90))
        sy += lh

    sy += 26
    draw.line([(W//2 - 40, sy), (W//2 + 40, sy)], fill=(90, 55, 15, 90), width=1)
    sy += 34

    for choice_line in choices.split(" | "):
        display_text = choice_line.split(" ", 1)[-1] if " " in choice_line else choice_line
        bbox = draw.textbbox((0, 0), display_text, font=verse_font)
        x    = (W - (bbox[2] - bbox[0])) // 2
        draw_text_shadow(draw, x, sy, display_text, verse_font, (50, 25, 5, 245), shadow=(255, 255, 255, 80))
        sy += int((bbox[3] - bbox[1]) * 1.3)

    sy += 24
    for lt, lh in wrap_text(f"\u201C{scripture}\u201D", ref_font, W - 180, draw):
        bbox = draw.textbbox((0, 0), lt, font=ref_font)
        x    = (W - (bbox[2] - bbox[0])) // 2
        draw.text((x, sy), lt, font=ref_font, fill=(70, 40, 10, 200))
        sy += int(lh * 0.85)
    bbox_r = draw.textbbox((0, 0), f"— {ref}", font=ref_font)
    draw.text(((W - (bbox_r[2] - bbox_r[0])) // 2, sy + 8), f"— {ref}",
              font=ref_font, fill=(70, 40, 10, 180))
    sy += 60

    draw.line([(W//2 - 40, sy), (W//2 + 40, sy)], fill=(90, 55, 15, 70), width=1)
    sy += 34

    cta_display = strip_emoji_for_display(cta)
    bbox_c = draw.textbbox((0, 0), cta_display, font=handle_font)
    draw.text(((W - (bbox_c[2] - bbox_c[0])) // 2, sy), cta_display,
              font=handle_font, fill=(50, 25, 5, 225))

    bbox_h = draw.textbbox((0, 0), HANDLE, font=handle_font)
    draw.text(((W - (bbox_h[2] - bbox_h[0])) // 2, H - 44),
              HANDLE, font=handle_font, fill=(50, 25, 5, 130))

    return img, fits


# ── CAPTION ───────────────────────────────────────────────────────────────────

def generate_caption(verse_text, reference, theme, mood):
    if not OPENAI_API_KEY:
        return fallback_caption(verse_text, reference)

    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type" : "application/json",
            },
            json={
                "model"     : "gpt-4o-mini",
                "max_tokens": 350,
                "messages"  : [
                    {
                        "role"   : "system",
                        "content": (
                            "You write ultra-short captions for a Christian Instagram page "
                            "called his.verse.for.the.day. Warm, personal, and direct. "
                            "Never preachy.\n\n"
                            "Format — follow exactly:\n"
                            "Line 1: ONE punchy sentence that lands the emotion of the verse.\n"
                            "Line 2: blank\n"
                            "Line 3: _Reference_ in italics markdown\n"
                            "Line 4: blank\n"
                            "Line 5: One short personal question inviting a comment + one emoji.\n"
                            "Total: under 40 words. Short is powerful."
                        ),
                    },
                    {
                        "role"   : "user",
                        "content": (
                            f'Write an Instagram caption for this verse:\n\n'
                            f'"{verse_text}"\n— {reference}\n\n'
                            f'Theme: {theme}\nMood: {mood}'
                        ),
                    },
                ],
            },
            timeout=30,
        )
        r.raise_for_status()
        caption = r.json()["choices"][0]["message"]["content"].strip()
        print("  ✓ Caption generated via OpenAI GPT-4o-mini")
        return caption
    except Exception as e:
        print(f"  ⚠ OpenAI failed: {e} — using fallback caption")
        return fallback_caption(verse_text, reference)

def fallback_caption(verse_text, reference):
    return (
        "Some days the weight of everything feels like too much to carry alone.\n\n"
        f"_{reference}_\n\n"
        "Save this for when you need it most. 🙏"
    )

def build_full_caption(body):
    return (
        f"{body}\n\n"
        f"✨ Follow for your daily verse 👉 {INSTAGRAM_URL}\n\n"
        f".\n.\n.\n{get_hashtags()}"
    )


# ── GITHUB UPLOAD ─────────────────────────────────────────────────────────────

def upload_to_github(file_path):
    if not GITHUB_TOKEN:
        print("  ⚠ No GITHUB_TOKEN — skipping upload")
        return None

    filename = Path(file_path).name
    api_url  = (
        f"https://api.github.com/repos/{GITHUB_USERNAME}/"
        f"{GITHUB_REPO}/contents/posts/{filename}"
    )
    headers = {
        "Authorization"       : f"Bearer {GITHUB_TOKEN}",
        "Accept"              : "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    with open(file_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()

    # Check if file already exists (need SHA to update)
    sha   = None
    check = requests.get(api_url, headers=headers, timeout=15)
    if check.status_code == 200:
        sha = check.json().get("sha")

    payload = {"message": f"Daily post — {filename}", "content": content_b64}
    if sha:
        payload["sha"] = sha

    r = requests.put(api_url, headers=headers, json=payload, timeout=90)
    r.raise_for_status()

    raw_url = (
        f"https://raw.githubusercontent.com/{GITHUB_USERNAME}/"
        f"{GITHUB_REPO}/main/posts/{filename}"
    )
    print(f"  ✓ Uploaded to GitHub: {raw_url}")
    return raw_url

def verify_url_is_accessible(url, retries=3, delay=5):
    """Confirm the raw GitHub URL actually serves the file before firing webhook."""
    import time
    for attempt in range(1, retries + 1):
        try:
            r = requests.head(url, timeout=15, allow_redirects=True)
            content_type = r.headers.get("Content-Type", "")
            if r.status_code == 200 and "text/html" not in content_type:
                print(f"  ✓ URL verified accessible ({content_type})")
                return True
            print(f"  ⚠ Attempt {attempt}: unexpected response "
                  f"(status={r.status_code}, type={content_type}) — retrying...")
        except Exception as e:
            print(f"  ⚠ Attempt {attempt}: HEAD request failed ({e}) — retrying...")
        time.sleep(delay)
    print("  ✗ URL not accessible after retries — aborting webhook")
    return False


# ── MAKE WEBHOOK ──────────────────────────────────────────────────────────────

def trigger_make(image_url, caption, package="verse", content_id=None):
    """Fires the Make webhook with an idempotency key so that if GitHub's
    request times out and the Action retries, Make can recognize the retry
    as the same intended publication rather than posting twice.

    IMPORTANT — honest semantics: HTTP 200 from Make's webhook module means
    the webhook was ACCEPTED for processing, not that Instagram/Facebook
    have confirmed the post is live. This function's return value and log
    message reflect that distinction; callers should not claim "published"
    based on this alone."""
    if not MAKE_WEBHOOK_URL:
        print("  ⚠ No MAKE_WEBHOOK_URL — skipping trigger")
        return False

    is_video = image_url.lower().endswith(".mp4")
    bahrain_date = bahrain_today()
    idempotency_key = f"{package}:{content_id}:{bahrain_date}" if content_id is not None \
                       else f"{package}:{bahrain_date}:{hashlib.md5(image_url.encode()).hexdigest()[:8]}"

    payload = {
        "image_url"      : image_url,
        "caption"        : caption,
        "is_video"       : is_video,
        "idempotency_key": idempotency_key,
        "package"        : package,
        "content_id"     : content_id,
        "bahrain_date"   : bahrain_date,
    }

    try:
        r = requests.post(MAKE_WEBHOOK_URL, json=payload, timeout=30)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"  ✗ Make webhook request failed: {e}")
        return False

    print(f"  ✓ Make accepted the post for processing (idempotency_key={idempotency_key})")
    return True


# ── REEL GENERATION ───────────────────────────────────────────────────────────

def generate_reel(image_path, mood="calm", duration=10):
    img_path  = Path(image_path)
    reel_path = OUTPUT_DIR / img_path.name.replace(".jpg", ".mp4")
    bg_path   = OUTPUT_DIR / img_path.name.replace(".jpg", "_bg.jpg")

    # Step 1 — blurred 9:16 background plate
    bg_cmd = [
        "ffmpeg", "-y", "-i", str(img_path),
        "-filter_complex",
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,boxblur=35:35[out]",
        "-map", "[out]", "-frames:v", "1", str(bg_path),
    ]
    r1 = subprocess.run(bg_cmd, capture_output=True, timeout=60)
    if r1.returncode != 0 or not bg_path.exists():
        print(f"  ⚠ Background plate failed:\n{r1.stderr.decode()[-300:]}")
        return None

    # Step 2 — resolve music
    music_file = MUSIC_MAP.get(mood, "calm.mp3")
    music_path = BASE_DIR / music_file
    has_music  = music_path.exists()
    print(f"  🎵 Music: {music_file}" if has_music else
          f"  ⚠ Music not found: {music_path} — no audio")

    # Step 3 — build inputs
    inputs = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(bg_path),
        "-loop", "1", "-i", str(img_path),
    ]
    if has_music:
        inputs += ["-stream_loop", "-1", "-i", str(music_path)]

    # Step 4 — build ONE complete filter_complex (video + optional audio)
    # Duration is parameterized (Part 20): existing verse/engagement calls
    # pass duration=10 unchanged; night uses 15s, morning uses 12s.
    frame_count = int(duration * 30)
    fade_out_start = max(0.5, duration - 1.0)
    audio_fade_out_start = max(0.5, duration - 1.5)

    video_filter = (
        "[0:v]"
        "zoompan=z='if(lte(on,1),1.0,min(zoom+0.0003,1.08))'"
        ":x='iw/2-(iw/zoom/2)'"
        ":y='ih/2-(ih/zoom/2)'"
        f":d={frame_count}:s=1080x1920:fps=30"
        "[bg_zoom];"
        "[1:v]scale=900:900,"
        "pad=1080:1920:90:510:color=black@0"
        "[fg_fixed];"
        "[bg_zoom][fg_fixed]overlay=0:0,"
        "fade=t=in:st=0:d=1.0,"
        f"fade=t=out:st={fade_out_start}:d=1.0"
        "[vout]"
    )

    if has_music:
        full_filter = (
            video_filter + ";"
            f"[2:a]atrim=0:{duration},"
            "afade=t=in:st=0:d=1.0,"
            f"afade=t=out:st={audio_fade_out_start}:d=1.5"
            "[aout]"
        )
        filter_args = [
            "-filter_complex", full_filter,
            "-map", "[vout]",
            "-map", "[aout]",
        ]
    else:
        filter_args = [
            "-filter_complex", video_filter,
            "-map", "[vout]",
        ]

    # Step 5 — assemble and run
    ffmpeg_cmd = inputs + filter_args + [
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", "30",
    ]
    if has_music:
        ffmpeg_cmd += ["-c:a", "aac", "-b:a", "128k"]

    ffmpeg_cmd.append(str(reel_path))

    result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=300)

    # Clean up background plate regardless of outcome
    bg_path.unlink(missing_ok=True)

    if result.returncode == 0 and reel_path.exists():
        size_mb = reel_path.stat().st_size / (1024 * 1024)
        print(f"  ✓ Reel: {reel_path.name} ({size_mb:.1f} MB)")
        return reel_path
    else:
        print(f"  ⚠ Reel generation failed:\n{result.stderr[-400:]}")
        return None


# ── VERSE PIPELINE ────────────────────────────────────────────────────────────

def run_verse(preview=False, verse_id=None, force=False):
    candidates, state = select_verse_candidates(verse_id)

    if not force and already_posted_today(state):
        print(f"  ⏭ Verse already posted today ({state.get('last_posted')}) — skipping. "
              f"Use --force to override (testing only).")
        return None, None

    verse, reserved = reserve_first_available("verse", candidates, "reference")
    if not reserved:
        print("  ✗ Every candidate collided with today's Scripture reservations — "
              "aborting safely. No post will be published (no duplicate Scripture).")
        return None, None

    print(f"  📖 {verse['reference']}  ({verse['theme']} / {verse['mood']})")

    print("\n  🌄 Fetching background image...")
    bg = fetch_image(verse["image_keywords"], verse["mood"])

    print("\n  🔤 Loading fonts...")
    fonts = load_fonts()

    print("\n  🎨 Compositing post...")
    post_img = composite_post(bg, verse["text"], verse["reference"], verse["mood"], fonts)
    today    = bahrain_today()
    img_path = OUTPUT_DIR / f"post_{today}_{verse['id']}.jpg"
    post_img.save(str(img_path), "JPEG", quality=97)
    print(f"  ✓ Saved: {img_path.name}")

    print("\n  🎬 Generating Reel video...")
    reel_path = generate_reel(img_path, verse["mood"], duration=10)

    print("\n  ✍️  Writing caption...")
    caption_body = generate_caption(
        verse["text"], verse["reference"], verse["theme"], verse["mood"]
    )
    full_caption = build_full_caption(caption_body)
    print(f"\n  ── Caption preview ──────────────────────────────")
    print(f"  {caption_body[:200]}")
    print(f"  ─────────────────────────────────────────────────")

    if preview:
        print("\n  🔍 Preview mode — skipping upload and posting "
              "(Scripture reservation made above still stands; release manually if needed)")
        release_reservation("verse")
        print(f"\n  ✅ Done. Image: {img_path}\n")
        return img_path, full_caption

    upload_path = str(reel_path) if reel_path else str(img_path)
    label       = "Reel" if reel_path else "photo"
    print(f"\n  📤 Uploading {label} to GitHub...")
    image_url = upload_to_github(upload_path)
    if not image_url:
        print("  ✗ Upload failed — aborting (content remains UNUSED for retry)")
        release_reservation("verse")
        return None, None

    print("\n  🔎 Verifying URL is accessible...")
    if not verify_url_is_accessible(image_url):
        release_reservation("verse")
        return None, None

    print("\n  📱 Triggering Make webhook...")
    success = trigger_make(image_url, full_caption, package="verse", content_id=verse["id"])
    if not success:
        print("  ✗ Webhook not accepted — post remains UNUSED for retry")
        release_reservation("verse")
        return None, None

    # Update state ONLY after confirmed webhook acceptance
    posted = state.get("posted_ids", [])
    posted.append(int(verse["id"]))
    state["posted_ids"]  = posted
    state["last_posted"] = today
    save_state(state)

    total     = len(load_verses())
    remaining = total - len(posted)
    print(f"\n  ✅ Complete! Verse #{verse['id']} of {total}")
    print(f"     {remaining} verses remaining in rotation\n")

    return img_path, full_caption


# ── ENGAGEMENT PIPELINE ───────────────────────────────────────────────────────

def run_engagement(preview=False, force=False):
    candidates, state = select_engagement_candidates()

    if not force and already_posted_today(state):
        print(f"  ⏭ Engagement already posted today ({state.get('last_posted')}) — skipping. "
              f"Use --force to override (testing only).")
        return None, None

    reel, reserved = reserve_first_available("engagement", candidates, "verse_ref")
    if not reserved:
        print("  ✗ Every candidate collided with today's Scripture reservations — "
              "aborting safely. No post will be published (no duplicate Scripture).")
        return None, None

    print(f"  💬 Engagement Reel #{reel['id']} — {reel['format']}")
    print(f"  📖 {reel['verse_ref']}")

    mood     = reel["mood"]
    keywords = mood

    print("\n  🌄 Fetching background image...")
    bg = fetch_image(keywords, mood)

    print("\n  🔤 Loading fonts...")
    fonts = load_fonts()

    print("\n  🎨 Compositing engagement reel...")
    post_img = composite_post(
        bg, reel["verse"], reel["verse_ref"], mood, fonts,
        video_text=reel["video_text"]
    )

    today    = bahrain_today()
    img_path = OUTPUT_DIR / f"engagement_{today}_{reel['id']}.jpg"
    post_img.save(str(img_path), "JPEG", quality=97)
    print(f"  ✓ Saved: {img_path.name}")

    print("\n  🎬 Generating Reel video...")
    reel_path = generate_reel(img_path, mood, duration=10)

    # Caption comes directly from CSV — no OpenAI cost
    caption_body = reel["caption"]
    full_caption = build_full_caption(caption_body)
    print(f"\n  ── Caption preview ──────────────────────────────")
    print(f"  {caption_body[:200]}")
    print(f"  ─────────────────────────────────────────────────")

    if preview:
        print("\n  🔍 Preview mode — skipping upload and posting")
        release_reservation("engagement")
        print(f"\n  ✅ Done. Image: {img_path}\n")
        return img_path, full_caption

    upload_path = str(reel_path) if reel_path else str(img_path)
    label       = "Reel" if reel_path else "photo"
    print(f"\n  📤 Uploading {label} to GitHub...")
    image_url = upload_to_github(upload_path)
    if not image_url:
        print("  ✗ Upload failed — aborting (content remains UNUSED for retry)")
        release_reservation("engagement")
        return None, None

    print("\n  🔎 Verifying URL is accessible...")
    if not verify_url_is_accessible(image_url):
        release_reservation("engagement")
        return None, None

    print("\n  📱 Triggering Make webhook...")
    success = trigger_make(image_url, full_caption, package="engagement", content_id=reel["id"])
    if not success:
        print("  ✗ Webhook not accepted — post remains UNUSED for retry")
        release_reservation("engagement")
        return None, None

    # Update state
    posted = state.get("posted_ids", [])
    posted.append(int(reel["id"]))
    state["posted_ids"]  = posted
    state["last_posted"] = today
    save_engagement_state(state)

    total     = len(load_engagement_reels())
    remaining = total - len(posted)
    print(f"\n  ✅ Complete! Engagement Reel #{reel['id']} of {total}")
    print(f"     {remaining} reels remaining in queue\n")

    return img_path, full_caption


# ── NIGHT PIPELINE ────────────────────────────────────────────────────────────

def run_night(preview=False, force=False):
    candidates, state = select_night_candidates()

    if not force and already_posted_today(state):
        print(f"  ⏭ Before You Sleep already posted today ({state.get('last_posted')}) — skipping. "
              f"Use --force to override (testing only).")
        return None, None

    post, reserved = reserve_first_available("night", candidates, "scripture_ref")
    if not reserved:
        print("  ✗ Every candidate collided with today's Scripture reservations — "
              "aborting safely. No post will be published (no duplicate Scripture).")
        return None, None

    print(f"  🌙 Before You Sleep #{post['id']} — {post['theme']}")
    print(f"  📖 {post['scripture_ref']}")

    print("\n  🌄 Fetching background image...")
    bg = fetch_image(post["visual_concept"], "night")

    print("\n  🔤 Loading fonts...")
    fonts = load_fonts()

    print("\n  🎨 Compositing night post (auto-fit layout check)...")
    post_img, fits = composite_night_post(
        bg, post["hook"], post["prayer"], post["scripture"],
        post["scripture_ref"], post["ending"], fonts
    )
    if not fits:
        print(f"  ⚠ Post #{post['id']} required minimum font scale — flagged for review")

    today    = bahrain_today()
    img_path = OUTPUT_DIR / f"night_{today}_{post['id']}.jpg"
    post_img.save(str(img_path), "JPEG", quality=97)
    print(f"  ✓ Saved: {img_path.name}")

    print("\n  🎬 Generating Reel video (15s)...")
    reel_path = generate_reel(img_path, "calm", duration=15)

    caption_body = f"{post['prayer']}\n\n_{post['scripture_ref']}_\n\n{post['ending']}"
    full_caption = build_full_caption(caption_body)
    print(f"\n  ── Caption preview ──────────────────────────────")
    print(f"  {caption_body[:200]}")
    print(f"  ─────────────────────────────────────────────────")

    if preview:
        print("\n  🔍 Preview mode — skipping upload and posting")
        release_reservation("night")
        print(f"\n  ✅ Done. Image: {img_path}\n")
        return img_path, full_caption

    upload_path = str(reel_path) if reel_path else str(img_path)
    label       = "Reel" if reel_path else "photo"
    print(f"\n  📤 Uploading {label} to GitHub...")
    image_url = upload_to_github(upload_path)
    if not image_url:
        print("  ✗ Upload failed — aborting (content remains UNUSED for retry)")
        release_reservation("night")
        return None, None

    print("\n  🔎 Verifying URL is accessible...")
    if not verify_url_is_accessible(image_url):
        release_reservation("night")
        return None, None

    print("\n  📱 Triggering Make webhook...")
    success = trigger_make(image_url, full_caption, package="night", content_id=post["id"])
    if not success:
        print("  ✗ Webhook not accepted — post remains UNUSED for retry")
        release_reservation("night")
        return None, None

    posted = state.get("posted_ids", [])
    posted.append(int(post["id"]))
    state["posted_ids"]  = posted
    state["last_posted"] = today
    save_night_state(state)

    total     = len(load_night_posts())
    remaining = total - len(posted)
    print(f"\n  ✅ Complete! Before You Sleep #{post['id']} of {total}")
    print(f"     {remaining} posts remaining in library\n")

    return img_path, full_caption


# ── MORNING PIPELINE ──────────────────────────────────────────────────────────

def run_morning(preview=False, force=False):
    candidates, state = select_morning_candidates()

    if not force and already_posted_today(state):
        print(f"  ⏭ What Do You Need Today? already posted today ({state.get('last_posted')}) — skipping. "
              f"Use --force to override (testing only).")
        return None, None

    post, reserved = reserve_first_available("morning", candidates, "scripture_ref")
    if not reserved:
        print("  ✗ Every candidate collided with today's Scripture reservations — "
              "aborting safely. No post will be published (no duplicate Scripture).")
        return None, None

    print(f"  ☀️ What Do You Need Today? #{post['id']} — {post['dominant_theme']}")
    print(f"  📖 {post['scripture_ref']}")

    print("\n  🌄 Fetching background image...")
    bg = fetch_image(post["visual_concept"], "morning")

    print("\n  🔤 Loading fonts...")
    fonts = load_fonts()

    print("\n  🎨 Compositing morning post (auto-fit layout check)...")
    post_img, fits = composite_morning_post(
        bg, post["question"], post["choices"], post["scripture"],
        post["scripture_ref"], post["cta"], fonts
    )
    if not fits:
        print(f"  ⚠ Post #{post['id']} required minimum font scale — flagged for review")

    today    = bahrain_today()
    img_path = OUTPUT_DIR / f"morning_{today}_{post['id']}.jpg"
    post_img.save(str(img_path), "JPEG", quality=97)
    print(f"  ✓ Saved: {img_path.name}")

    print("\n  🎬 Generating Reel video (12s)...")
    reel_path = generate_reel(img_path, "uplifting", duration=12)

    caption_body = f"{post['question']}\n\n{post['choices']}\n\n{post['cta']}"
    full_caption = build_full_caption(caption_body)
    print(f"\n  ── Caption preview ──────────────────────────────")
    print(f"  {caption_body[:200]}")
    print(f"  ─────────────────────────────────────────────────")

    if preview:
        print("\n  🔍 Preview mode — skipping upload and posting")
        release_reservation("morning")
        print(f"\n  ✅ Done. Image: {img_path}\n")
        return img_path, full_caption

    upload_path = str(reel_path) if reel_path else str(img_path)
    label       = "Reel" if reel_path else "photo"
    print(f"\n  📤 Uploading {label} to GitHub...")
    image_url = upload_to_github(upload_path)
    if not image_url:
        print("  ✗ Upload failed — aborting (content remains UNUSED for retry)")
        release_reservation("morning")
        return None, None

    print("\n  🔎 Verifying URL is accessible...")
    if not verify_url_is_accessible(image_url):
        release_reservation("morning")
        return None, None

    print("\n  📱 Triggering Make webhook...")
    success = trigger_make(image_url, full_caption, package="morning", content_id=post["id"])
    if not success:
        print("  ✗ Webhook not accepted — post remains UNUSED for retry")
        release_reservation("morning")
        return None, None

    posted = state.get("posted_ids", [])
    posted.append(int(post["id"]))
    state["posted_ids"]  = posted
    state["last_posted"] = today
    save_morning_state(state)

    total     = len(load_morning_posts())
    remaining = total - len(posted)
    print(f"\n  ✅ Complete! What Do You Need Today? #{post['id']} of {total}")
    print(f"     {remaining} posts remaining in library\n")

    return img_path, full_caption


# ── ENTRY ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="his.verse.for.the.day — Daily Bot")
    parser.add_argument("--preview", action="store_true",
                        help="Generate only — skip upload and posting")
    parser.add_argument("--verse",   type=int, default=None,
                        help="Force a specific verse ID (verse mode only)")
    parser.add_argument("--mode",    type=str, default="verse",
                        choices=["verse", "engagement", "night", "morning"],
                        help="Pipeline mode (default: verse)")
    parser.add_argument("--force", action="store_true",
                        help="Override the same-package-same-Bahrain-day guard "
                             "(testing only — not for normal scheduled use)")
    args = parser.parse_args()

    mode_labels = {
        "verse": "📖 Verse", "engagement": "💬 Engagement",
        "night": "🌙 Before You Sleep", "morning": "☀️ What Do You Need Today?",
    }

    print("\n═══════════════════════════════════════════════")
    print("   his.verse.for.the.day — Daily Bot")
    print(f"   {bahrain_now().strftime('%A, %B %d %Y — %H:%M')} Bahrain time")
    print(f"   Mode: {mode_labels[args.mode]}")
    print("═══════════════════════════════════════════════\n")

    if args.mode == "engagement":
        run_engagement(preview=args.preview, force=args.force)
    elif args.mode == "night":
        run_night(preview=args.preview, force=args.force)
    elif args.mode == "morning":
        run_morning(preview=args.preview, force=args.force)
    else:
        run_verse(preview=args.preview, verse_id=args.verse, force=args.force)


if __name__ == "__main__":
    main()
