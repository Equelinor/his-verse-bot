#!/usr/bin/env python3
"""
his.verse.for.the.day — Instagram Automation Bot
================================================
Daily Bible verse post generator. Fully automated. Zero cost.

Cost breakdown:
  - Verses:      Local CSV              → $0.00
  - Images:      Unsplash free API      → $0.00
  - Compositing: Pillow                 → $0.00
  - Captions:    OpenAI GPT-4o-mini     → ~$0.30/year
  - Image host:  GitHub (public repo)   → $0.00
  - Scheduler:   GitHub Actions cron    → $0.00
  - Posting:     Make → Instagram       → $0.00

Pipeline:
  GitHub Actions (daily)
    → picks verse/engagement reel → fetches image → composites post
    → writes caption via OpenAI
    → uploads image to GitHub repo (raw URL)
    → pings Make webhook with image URL + caption
    → Make posts to Instagram + Facebook via his.verse.for.the.day

Usage:
  python bot.py                        # Full pipeline (verse post)
  python bot.py --mode engagement      # Engagement reel post
  python bot.py --preview              # Generate only, no posting
  python bot.py --verse 7              # Force a specific verse ID
"""

import os
import csv
import json
import base64
import random
import argparse
import datetime
import requests
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

# ── CONFIG ────────────────────────────────────────────────────────────────────

BASE_DIR            = Path(__file__).parent
DATA_DIR            = BASE_DIR / "data"
OUTPUT_DIR          = BASE_DIR / "output"
FONTS_DIR           = BASE_DIR / "fonts"
STATE_FILE          = DATA_DIR / "state.json"
ENGAGEMENT_STATE    = DATA_DIR / "engagement_state.json"
VERSES_FILE         = DATA_DIR / "verses.csv"
ENGAGEMENT_FILE     = DATA_DIR / "engagement_reels.csv"

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

# ── POST SETTINGS ─────────────────────────────────────────────────────────────
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

# ── HASHTAG BANK ──────────────────────────────────────────────────────────────
HASHTAG_POOLS = {
    "A": "#bibleverseoftheday #dailyword #faithquotes #christianinstagram #godsword #scripturequotes #verseoftheday #bibleverse #christianity #prayerwarrior #godislove #jesuslovesyou #dailydevotional #bibleinstagram #faithoverfear #godsgrace #scripture #biblequotes #christianquotes #hopeinfaith #spiritualwellness #innerpeace #hisversefortheday #trustgod #godisfaithful #dailyinspiration #christianlife #wordofgod #blessedlife #godsplan",
    "B": "#morningdevotion #christisking #biblelovers #scripturememory #christianmotivation #godspromises #holybible #jesusfreak #prayerandfasting #spiritfilled #faithwalk #godscreation #praiseandworship #christianfaith #redeemed #kingdomofgod #graceupongrace #divinelove #godspeaks #hisversefortheday #christianquotes #bibletruth #prayerlife #godisgreat #worshipeveryday",
    "C": "#anxiety #mentalhealth #healing #peacefulmind #selfcare #mindfulness #spiritualhealing #godheals #overcomer #brokenbutblessed #restored #hope #encouragement #dailymotivation #uplift #comforting #godcomforts #neveralone #youareloved #godswill #hisversefortheday #bibletruths #prayerworks #stillness #breathe",
}

def get_hashtags():
    week = datetime.date.today().isocalendar()[1]
    return HASHTAG_POOLS[["A","B","C"][week % 3]]


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


# ── VERSE SELECTION ───────────────────────────────────────────────────────────

def load_verses():
    with open(VERSES_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def select_verse(verse_id=None):
    verses = load_verses()
    state  = load_state()

    if verse_id:
        verse = next((v for v in verses if int(v["id"]) == verse_id), verses[0])
        return verse, state

    posted    = set(state.get("posted_ids", []))
    remaining = [v for v in verses if int(v["id"]) not in posted]

    if not remaining:
        state["posted_ids"] = []
        remaining = verses

    random.seed(int(datetime.date.today().strftime("%Y%m%d")))
    return random.choice(remaining), state


# ── ENGAGEMENT REEL SELECTION ─────────────────────────────────────────────────

def load_engagement_reels():
    with open(ENGAGEMENT_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def select_engagement_reel():
    reels = load_engagement_reels()
    state = load_engagement_state()

    posted    = set(state.get("posted_ids", []))
    remaining = [r for r in reels if int(r["id"]) not in posted]

    if not remaining:
        state["posted_ids"] = []
        remaining = reels

    # sequential — go in order, not random
    remaining_sorted = sorted(remaining, key=lambda x: int(x["id"]))
    reel = remaining_sorted[0]
    return reel, state


# ── FONTS ─────────────────────────────────────────────────────────────────────

def ensure_font(filename, url, size, fallback_key="serif"):
    path = FONTS_DIR / filename
    if not path.exists():
        print(f"  Downloading {filename}...")
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            path.write_bytes(r.content)
            ImageFont.truetype(str(path), size)
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
        "verse" : ensure_font("CormorantGaramond-Italic.ttf", FONT_URL_SERIF, 68, "serif"),
        "ref"   : ensure_font("CormorantGaramond-Italic.ttf", FONT_URL_SERIF, 38, "serif"),
        "handle": ensure_font("Lato-Light.ttf",               FONT_URL_SANS,  22, "sans"),
        "quote" : ensure_font("CormorantGaramond-Light.ttf",  FONT_URL_LIGHT, 160, "serif"),
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
            print(f"  ✓ Image fetched from Unsplash")
            return Image.open(BytesIO(img_data)).convert("RGB")
        except Exception as e:
            print(f"  ⚠ Unsplash failed: {e} — using gradient")

    palettes = {
        "calm"      : [(8, 18, 40),  (30, 50, 90)],
        "uplifting" : [(70, 35, 5),  (160, 90, 15)],
        "reflective": [(15, 28, 20), (40, 65, 45)],
    }
    c = palettes.get(mood, palettes["calm"])
    W, H = POST_SIZE
    img  = Image.new("RGB", POST_SIZE)
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        draw.line([(0,y),(W,y)], fill=(
            int(c[0][0]+(c[1][0]-c[0][0])*t),
            int(c[0][1]+(c[1][1]-c[0][1])*t),
            int(c[0][2]+(c[1][2]-c[0][2])*t),
        ))
    print("  ✓ Using gradient fallback")
    return img


# ── IMAGE COMPOSITING ─────────────────────────────────────────────────────────

def wrap_text(text, font, max_width, draw):
    words, lines, current = text.split(), [], []
    for word in words:
        test = " ".join(current + [word])
        bbox = draw.textbbox((0,0), test, font=font)
        if bbox[2]-bbox[0] <= max_width:
            current.append(word)
        else:
            if current: lines.append(" ".join(current))
            current = [word]
    if current: lines.append(" ".join(current))
    result = []
    for line in lines:
        bbox = draw.textbbox((0,0), line, font=font)
        result.append((line, int((bbox[3]-bbox[1])*1.42)))
    return result

def composite_post(bg_img, verse_text, reference, mood, fonts, video_text=None):
    W, H = POST_SIZE

    img = bg_img.copy()
    r   = img.width / img.height
    nw  = int(W * r) if r > 1 else W
    nh  = int(H / r) if r <= 1 else H
    img = img.resize((max(nw,W), max(nh,H)), Image.LANCZOS)
    img = img.crop(((img.width-W)//2, (img.height-H)//2,
                    (img.width-W)//2+W, (img.height-H)//2+H))

    img = ImageEnhance.Color(img).enhance(0.82)
    if mood == "uplifting":
        r2,g,b = img.split()
        img = Image.merge("RGB",(r2.point(lambda i:min(255,int(i*1.04))),g,b))
    elif mood == "calm":
        r2,g,b = img.split()
        img = Image.merge("RGB",(r2,g,b.point(lambda i:min(255,int(i*1.04)))))

    ov  = Image.new("RGBA",(W,H),(0,0,0,0))
    dov = ImageDraw.Draw(ov)
    for y in range(H//3):
        dov.line([(0,y),(W,y)],fill=(0,0,0,int(120*(1-y/(H/3)))))
    for y in range(int(H*0.48),H):
        dov.line([(0,y),(W,y)],fill=(0,0,0,int(180*((y-H*0.48)/(H*0.52)))))
    for m in range(0,180,4):
        dov.rectangle([m,m,W-m,H-m],outline=(0,0,0,int(70*(1-m/180))))

    img  = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
    draw = ImageDraw.Draw(img)

    draw.text((50,130), "\u201C", font=fonts["quote"], fill=(255,255,255,35))

    # If engagement reel — show video_text at top, verse smaller below
    if video_text:
        # Video text (hook line) at top
        vt_font = ensure_font("CormorantGaramond-Italic.ttf", FONT_URL_SERIF, 52, "serif")
        wrapped_vt = wrap_text(video_text, vt_font, W-140, draw)
        sy = 80
        for lt, lh in wrapped_vt:
            bbox = draw.textbbox((0,0), lt, font=vt_font)
            x = (W-(bbox[2]-bbox[0]))//2
            draw.text((x+2,sy+3), lt, font=vt_font, fill=(0,0,0,115))
            draw.text((x,sy),     lt, font=vt_font, fill=(255,255,220,240))
            sy += lh

        # Divider
        draw.line([(W//2-40, sy+10),(W//2+40, sy+10)], fill=(255,255,255,80), width=1)
        sy += 30

        # Verse text centered below
        wrapped = wrap_text(verse_text, fonts["verse"], W-140, draw)
        for lt,lh in wrapped:
            bbox = draw.textbbox((0,0),lt,font=fonts["verse"])
            x    = (W-(bbox[2]-bbox[0]))//2
            draw.text((x+2,sy+3), lt, font=fonts["verse"], fill=(0,0,0,115))
            draw.text((x,sy),     lt, font=fonts["verse"], fill=(255,255,255,252))
            sy += lh

        # Reference
        draw.line([(W//2-28,sy+16),(W//2+28,sy+16)], fill=(255,255,255,90), width=1)
        bbox_r = draw.textbbox((0,0), reference, font=fonts["ref"])
        draw.text(((W-(bbox_r[2]-bbox_r[0]))//2, sy+28), reference,
                  font=fonts["ref"], fill=(255,255,255,175))
    else:
        # Standard verse post layout
        draw.text((58,50), reference, font=fonts["ref"], fill=(255,255,255,175))
        wrapped = wrap_text(verse_text, fonts["verse"], W-140, draw)
        total_h = sum(lh for _,lh in wrapped)
        sy      = (H-total_h)//2 + 25
        for lt,lh in wrapped:
            bbox = draw.textbbox((0,0),lt,font=fonts["verse"])
            x    = (W-(bbox[2]-bbox[0]))//2
            draw.text((x+2,sy+3), lt, font=fonts["verse"], fill=(0,0,0,115))
            draw.text((x,sy),     lt, font=fonts["verse"], fill=(255,255,255,252))
            sy += lh
        draw.line([(W//2-28,sy+16),(W//2+28,sy+16)], fill=(255,255,255,90), width=1)

    # Handle watermark
    bbox_h = draw.textbbox((0,0),HANDLE,font=fonts["handle"])
    draw.text(((W-(bbox_h[2]-bbox_h[0]))//2, H-44), HANDLE,
              font=fonts["handle"], fill=(255,255,255,80))

    return img


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
                "model": "gpt-4o-mini",
                "max_tokens": 350,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You write ultra-short captions for a Christian Instagram page called his.verse.for.the.day. "
                            "Warm, personal, and direct. Never preachy.\n\n"
                            "Format — strictly follow this:\n"
                            "Line 1: ONE punchy sentence that lands the emotion of the verse.\n"
                            "Line 2: blank\n"
                            "Line 3: _Reference_ in italics\n"
                            "Line 4: blank\n"
                            "Line 5: One short personal question inviting a comment. End with one emoji.\n"
                            "Total: under 40 words. Short is powerful."
                        )
                    },
                    {"role": "user",
                        "content": (
                            f'Write an Instagram caption for this verse:\n\n'
                            f'"{verse_text}"\n— {reference}\n\n'
                            f'Theme: {theme}\nMood: {mood}'
                        )
                    }
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
        f"Some days the weight of everything feels like too much to carry alone. "
        f"But you were never meant to carry it alone.\n\n"
        f"_{reference}_\n\n"
        f"Save this for when you need it most. 🙏"
    )

def build_full_caption(body):
    follow_line = f"✨ Follow for your daily verse 👉 {INSTAGRAM_URL}"
    return f"{body}\n\n{follow_line}\n\n.\n.\n.\n{get_hashtags()}"


# ── GITHUB UPLOAD ─────────────────────────────────────────────────────────────

def upload_to_github(image_path):
    if not GITHUB_TOKEN:
        print("  ⚠ No GITHUB_TOKEN — skipping upload")
        return None

    filename = Path(image_path).name
    api_url  = (f"https://api.github.com/repos/{GITHUB_USERNAME}/"
                f"{GITHUB_REPO}/contents/posts/{filename}")
    headers  = {
        "Authorization"        : f"Bearer {GITHUB_TOKEN}",
        "Accept"               : "application/vnd.github+json",
        "X-GitHub-Api-Version" : "2022-11-28",
    }

    with open(image_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()

    sha = None
    check = requests.get(api_url, headers=headers, timeout=15)
    if check.status_code == 200:
        sha = check.json().get("sha")

    payload = {"message": f"Daily post — {filename}", "content": content_b64}
    if sha:
        payload["sha"] = sha

    r = requests.put(api_url, headers=headers, json=payload, timeout=60)
    r.raise_for_status()

    raw_url = (f"https://raw.githubusercontent.com/{GITHUB_USERNAME}/"
               f"{GITHUB_REPO}/main/posts/{filename}")
    print(f"  ✓ Uploaded to GitHub: {raw_url}")
    return raw_url


# ── MAKE WEBHOOK ──────────────────────────────────────────────────────────────

def trigger_make(image_url, caption):
    if not MAKE_WEBHOOK_URL:
        print("  ⚠ No MAKE_WEBHOOK_URL — skipping trigger")
        return False

    is_video = image_url.endswith(".mp4")
    r = requests.post(
        MAKE_WEBHOOK_URL,
        json={"image_url": image_url, "caption": caption, "is_video": is_video},
        timeout=30,
    )
    r.raise_for_status()
    print(f"  ✓ Make webhook triggered — post queued")
    return True


# ── REEL GENERATION ───────────────────────────────────────────────────────────

MUSIC_MAP = {
    "calm"      : "calm.mp3",
    "reflective": "reflective.mp3",
    "uplifting" : "uplifting.mp3",
    "hope"      : "hope.mp3",
    "faith"     : "faith.mp3",
}

def generate_reel(image_path, mood="calm"):
    import subprocess
    img_path  = Path(image_path)
    reel_path = OUTPUT_DIR / img_path.name.replace(".jpg", ".mp4")
    bg_path   = OUTPUT_DIR / img_path.name.replace(".jpg", "_bg.jpg")

    bg_cmd = [
        "ffmpeg", "-y", "-i", str(img_path),
        "-filter_complex",
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,boxblur=35:35[out]",
        "-map", "[out]", "-frames:v", "1", str(bg_path)
    ]
    r1 = subprocess.run(bg_cmd, capture_output=True, timeout=60)
    if r1.returncode != 0 or not bg_path.exists():
        print("  ⚠ BG creation failed — using photo post")
        return None

    music_file = MUSIC_MAP.get(mood, "calm.mp3")
    music_path = BASE_DIR / music_file
    has_music  = music_path.exists()

    if has_music:
        print(f"  🎵 Music: {music_file}")
    else:
        print(f"  ⚠ Music file not found: {music_path} — no audio")

    inputs = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(bg_path),
        "-loop", "1", "-i", str(img_path),
    ]
    if has_music:
        inputs += ["-stream_loop", "-1", "-i", str(music_path)]

    video_filter = (
        "[0:v]"
        "zoompan=z='if(lte(on,1),1.0,min(zoom+0.0003,1.08))'"
        ":x='iw/2-(iw/zoom/2)'"
        ":y='ih/2-(ih/zoom/2)'"
        ":d=300:s=1080x1920:fps=30"
        "[bg_zoom];"
        "[1:v]scale=900:900,"
        "pad=1080:1920:90:510:color=black@0"
        "[fg_fixed];"
        "[bg_zoom][fg_fixed]overlay=0:0,"
        "fade=t=in:st=0:d=1.0,"
        "fade=t=out:st=9.0:d=1.0"
        "[vout]"
    )

    filter_complex = ["-filter_complex", video_filter, "-map", "[vout]"]

    if has_music:
        audio_filter = [
            "-filter_complex",
            video_filter + ";"
            "[2:a]atrim=0:10,afade=t=in:st=0:d=1.0,afade=t=out:st=8.5:d=1.5[aout]",
            "-map", "[vout]",
            "-map", "[aout]",
        ]
        filter_complex = audio_filter

    ffmpeg_cmd = inputs + filter_complex + [
        "-t", "10",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", "30",
    ]
    if has_music:
        ffmpeg_cmd += ["-c:a", "aac", "-b:a", "128k"]

    ffmpeg_cmd.append(str(reel_path))

    result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=300)

    if bg_path.exists():
        bg_path.unlink(missing_ok=True)

    if result.returncode == 0:
        size_mb = reel_path.stat().st_size / (1024*1024)
        print(f"  ✓ Reel: {reel_path.name} ({size_mb:.1f}MB)")
        return reel_path
    else:
        print(f"  ⚠ Reel failed — using photo post instead")
        print(f"  {result.stderr[-200:]}")
        return None


# ── MAIN PIPELINE ─────────────────────────────────────────────────────────────

def run(preview=False, verse_id=None, mode="verse"):
    print("\n═══════════════════════════════════════════")
    print("   his.verse.for.the.day — Daily Bot")
    print(f"   {datetime.datetime.now().strftime('%A, %B %d %Y — %H:%M')}")
    print(f"   Mode: {'📖 Verse' if mode == 'verse' else '💬 Engagement'}")
    print("═══════════════════════════════════════════\n")

    if mode == "engagement":
        # ── ENGAGEMENT REEL PIPELINE ──────────────────────────────────────────
        reel, state = select_engagement_reel()
        print(f"  💬 Engagement Reel #{reel['id']} — {reel['format']}")
        print(f"  📖 {reel['verse_ref']}")

        # Use verse keywords to pick a thematic background
        mood     = reel["mood"]
        keywords = mood  # simple keyword — calm/reflective/uplifting

        print("\n  🌄 Fetching background image...")
        bg = fetch_image(keywords, mood)

        print("\n  🔤 Loading fonts...")
        fonts = load_fonts()

        print("\n  🎨 Compositing engagement reel...")
        post_img = composite_post(
            bg,
            reel["verse"],
            reel["verse_ref"],
            mood,
            fonts,
            video_text=reel["video_text"]
        )

        today    = datetime.date.today().strftime("%Y-%m-%d")
        img_path = OUTPUT_DIR / f"engagement_{today}_{reel['id']}.jpg"
        post_img.save(str(img_path), "JPEG", quality=97)
        print(f"  ✓ Saved: {img_path.name}")

        print("\n  🎬 Generating Reel video...")
        reel_path = generate_reel(img_path, mood)

        # Caption is taken directly from CSV — no OpenAI needed
        caption_body = reel["caption"]
        full_caption = build_full_caption(caption_body)

        print(f"\n  ── Caption preview ───────────────────────")
        print(f"  {caption_body[:200]}")
        print(f"  ──────────────────────────────────────────")

        if preview:
            print("\n  🔍 Preview mode — skipping upload and posting")
            print(f"\n  ✅ Done. Image: {img_path}\n")
            return img_path, full_caption

        upload_file = str(reel_path) if reel_path else str(img_path)
        print(f"\n  📤 Uploading {'Reel' if reel_path else 'photo'} to GitHub...")
        image_url = upload_to_github(upload_file)
        if not image_url:
            print("  ✗ Upload failed — aborting post")
            return None, None

        print("\n  📱 Triggering Make webhook...")
        trigger_make(image_url, full_caption)

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

    else:
        # ── VERSE POST PIPELINE (unchanged) ──────────────────────────────────
        verse, state = select_verse(verse_id)
        print(f"  📖 {verse['reference']} ({verse['theme']} / {verse['mood']})")

        print("\n  🌄 Fetching background image...")
        bg = fetch_image(verse["image_keywords"], verse["mood"])

        print("\n  🔤 Loading fonts...")
        fonts = load_fonts()

        print("\n  🎨 Compositing post...")
        post_img = composite_post(bg, verse["text"], verse["reference"], verse["mood"], fonts)
        today    = datetime.date.today().strftime("%Y-%m-%d")
        img_path = OUTPUT_DIR / f"post_{today}_{verse['id']}.jpg"
        post_img.save(str(img_path), "JPEG", quality=97)
        print(f"  ✓ Saved: {img_path.name}")

        print("\n  🎬 Generating Reel video...")
        reel_path = generate_reel(img_path, verse["mood"])

        print("\n  ✍️  Writing caption...")
        caption_body = generate_caption(verse["text"], verse["reference"],
                                        verse["theme"], verse["mood"])
        full_caption = build_full_caption(caption_body)
        print(f"\n  ── Caption preview ───────────────────────")
        print(f"  {caption_body[:200]}...")
        print(f"  ──────────────────────────────────────────")

        if preview:
            print("\n  🔍 Preview mode — skipping upload and posting")
            print(f"\n  ✅ Done. Image: {img_path}\n")
            return img_path, full_caption

        upload_file = str(reel_path) if reel_path else str(img_path)
        print(f"\n  📤 Uploading {'Reel' if reel_path else 'photo'} to GitHub...")
        image_url = upload_to_github(upload_file)
        if not image_url:
            print("  ✗ Upload failed — aborting post")
            return None, None

        print("\n  📱 Triggering Make webhook...")
        trigger_make(image_url, full_caption)

        posted = state.get("posted_ids", [])
        posted.append(int(verse["id"]))
        state["posted_ids"]  = state.get("posted_ids", [])
        state["posted_ids"].append(int(verse["id"]))
        state["last_posted"] = today
        save_state(state)

        total     = len(load_verses())
        remaining = total - len(state["posted_ids"])
        print(f"\n  ✅ Complete! Verse #{verse['id']} of {total}")
        print(f"     {remaining} verses remaining in rotation\n")

        return img_path, full_caption


# ── ENTRY ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true", help="Generate only, do not post")
    parser.add_argument("--verse",   type=int, default=None, help="Force specific verse ID")
    parser.add_argument("--mode",    type=str, default="verse",
                        choices=["verse","engagement"], help="Post mode")
    args = parser.parse_args()
    run(preview=args.preview, verse_id=args.verse, mode=args.mode)
