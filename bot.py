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
  GitHub Actions (8AM daily)
    → picks verse → fetches image → composites post
    → writes caption via OpenAI
    → uploads image to GitHub repo (raw URL)
    → pings Make webhook with image URL + caption
    → Make posts to Instagram via his.verse.for.the.day

Usage:
  python bot.py               # Full pipeline
  python bot.py --preview     # Generate image + caption only, no posting
  python bot.py --verse 7     # Force a specific verse ID
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

BASE_DIR    = Path(__file__).parent
DATA_DIR    = BASE_DIR / "data"
OUTPUT_DIR  = BASE_DIR / "output"
FONTS_DIR   = BASE_DIR / "fonts"
STATE_FILE  = DATA_DIR / "state.json"
VERSES_FILE = DATA_DIR / "verses.csv"

OUTPUT_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)
FONTS_DIR.mkdir(exist_ok=True)

# ── SECRETS (set as GitHub Actions secrets) ───────────────────────────────────
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "")
OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY", "")
GITHUB_TOKEN        = os.getenv("GITHUB_TOKEN", "")
GITHUB_USERNAME     = os.getenv("GITHUB_USERNAME", "Equelinor")
GITHUB_REPO         = os.getenv("GITHUB_REPO", "his-verse-bot")
MAKE_WEBHOOK_URL    = os.getenv("MAKE_WEBHOOK_URL", "")  # from Make scenario

# ── POST SETTINGS ─────────────────────────────────────────────────────────────
POST_SIZE = (1080, 1080)
HANDLE    = "@his.verse.for.the.day"

# Fonts (auto-downloaded on first run)
FONT_URL_SERIF = "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/cormorantgaramond/CormorantGaramond-Italic.ttf"
FONT_URL_LIGHT = "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/cormorantgaramond/CormorantGaramond-Light.ttf"
FONT_URL_SANS  = "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/lato/Lato-Light.ttf"

# System font fallbacks
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

# ── HASHTAG BANK (rotates weekly) ─────────────────────────────────────────────
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


# ── FONTS ─────────────────────────────────────────────────────────────────────

def ensure_font(filename, url, size, fallback_key="serif"):
    path = FONTS_DIR / filename
    if not path.exists():
        print(f"  Downloading {filename}...")
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            path.write_bytes(r.content)
            ImageFont.truetype(str(path), size)  # verify
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

    # Gradient fallback
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

def composite_post(bg_img, verse_text, reference, mood, fonts):
    W, H = POST_SIZE

    # Crop to square
    img = bg_img.copy()
    r   = img.width / img.height
    nw  = int(W * r) if r > 1 else W
    nh  = int(H / r) if r <= 1 else H
    img = img.resize((max(nw,W), max(nh,H)), Image.LANCZOS)
    img = img.crop(((img.width-W)//2, (img.height-H)//2,
                    (img.width-W)//2+W, (img.height-H)//2+H))

    # Color grade
    img = ImageEnhance.Color(img).enhance(0.82)
    if mood == "uplifting":
        r,g,b = img.split()
        img = Image.merge("RGB",(r.point(lambda i:min(255,int(i*1.04))),g,b))
    elif mood == "calm":
        r,g,b = img.split()
        img = Image.merge("RGB",(r,g,b.point(lambda i:min(255,int(i*1.04)))))

    # Overlays
    ov  = Image.new("RGBA",(W,H),(0,0,0,0))
    dov = ImageDraw.Draw(ov)
    for y in range(H//3):
        dov.line([(0,y),(W,y)],fill=(0,0,0,int(120*(1-y/(H/3)))))
    for y in range(int(H*0.48),H):
        dov.line([(0,y),(W,y)],fill=(0,0,0,int(180*((y-H*0.48)/(H*0.52)))))
    for m in range(0,180,4):
        dov.rectangle([m,m,W-m,H-m],outline=(0,0,0,int(70*(1-m/180))))

    img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Ghost quote mark
    draw.text((50,130), "\u201C", font=fonts["quote"], fill=(255,255,255,35))

    # Reference top-left
    draw.text((58,50), reference, font=fonts["ref"], fill=(255,255,255,175))

    # Verse text centered
    wrapped = wrap_text(verse_text, fonts["verse"], W-140, draw)
    total_h = sum(lh for _,lh in wrapped)
    sy      = (H-total_h)//2 + 25
    for lt,lh in wrapped:
        bbox = draw.textbbox((0,0),lt,font=fonts["verse"])
        x    = (W-(bbox[2]-bbox[0]))//2
        draw.text((x+2,sy+3), lt, font=fonts["verse"], fill=(0,0,0,115))
        draw.text((x,sy),     lt, font=fonts["verse"], fill=(255,255,255,252))
        sy += lh

    # Divider
    draw.line([(W//2-28,sy+16),(W//2+28,sy+16)], fill=(255,255,255,90), width=1)

    # Handle watermark
    bbox_h = draw.textbbox((0,0),HANDLE,font=fonts["handle"])
    draw.text(((W-(bbox_h[2]-bbox_h[0]))//2, H-44), HANDLE,
              font=fonts["handle"], fill=(255,255,255,80))

    return img


# ── CAPTION (OpenAI GPT-4o-mini) ─────────────────────────────────────────────

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
        f"This verse is not a suggestion — it is a promise.\n\n"
        f"_{reference}_\n\n"
        f"Save this for when you need it most. 🙏"
    )

def build_full_caption(body):
    return f"{body}\n\n.\n.\n.\n{get_hashtags()}"


# ── GITHUB IMAGE UPLOAD ───────────────────────────────────────────────────────

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

    # Check if exists
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


# ── MAKE WEBHOOK TRIGGER ──────────────────────────────────────────────────────

def trigger_make(image_url, caption):
    if not MAKE_WEBHOOK_URL:
        print("  ⚠ No MAKE_WEBHOOK_URL — skipping trigger")
        return False

    # Detect if this is a video (reel) or photo
    is_video = image_url.endswith(".mp4")
    r = requests.post(
        MAKE_WEBHOOK_URL,
        json={"image_url": image_url, "caption": caption, "is_video": is_video},
        timeout=30,
    )
    r.raise_for_status()
    print(f"  ✓ Make webhook triggered — Instagram post queued")
    return True



# ── REEL VIDEO GENERATION ────────────────────────────────────────────────────

def generate_reel(image_path):
    """Ken Burns zoom: converts square post image into a 10s 9:16 Reel MP4."""
    import subprocess
    img_path = Path(image_path)
    reel_path = OUTPUT_DIR / img_path.name.replace(".jpg", ".mp4")

    # Step 1: Scale square image to 9:16 with blurred background
    frame_path = OUTPUT_DIR / img_path.name.replace(".jpg", "_frame.jpg")
    scale_cmd = [
        "ffmpeg", "-y", "-i", str(img_path),
        "-filter_complex",
        "[0:v]scale=1080:1080[fg];"
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,boxblur=25:25[bg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[out]",
        "-map", "[out]", "-frames:v", "1", str(frame_path)
    ]
    r1 = subprocess.run(scale_cmd, capture_output=True, timeout=60)
    src = str(frame_path) if r1.returncode == 0 and frame_path.exists() else str(img_path)

    # Step 2: Ken Burns zoom + fade in/out
    ffmpeg_cmd = [
        "ffmpeg", "-y", "-loop", "1", "-i", src,
        "-filter_complex",
        "[0:v]zoompan=z='min(zoom+0.0008,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        ":d=300:s=1080x1920:fps=30,"
        "fade=t=in:st=0:d=1.5,fade=t=out:st=8.5:d=1.5[out]",
        "-map", "[out]", "-t", "10",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-r", "30",
        str(reel_path)
    ]
    result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=300)

    # Cleanup temp frame
    if frame_path.exists():
        frame_path.unlink(missing_ok=True)

    if result.returncode == 0:
        size_mb = reel_path.stat().st_size / (1024*1024)
        print(f"  ✓ Reel: {reel_path.name} ({size_mb:.1f}MB)")
        return reel_path
    else:
        print(f"  ⚠ Reel failed — using photo post instead")
        return None


# ── MAIN PIPELINE ─────────────────────────────────────────────────────────────

def run(preview=False, verse_id=None):
    print("\n═══════════════════════════════════════════")
    print("   his.verse.for.the.day — Daily Bot")
    print(f"   {datetime.datetime.now().strftime('%A, %B %d %Y — %H:%M')}")
    print("═══════════════════════════════════════════\n")

    # 1. Select verse
    verse, state = select_verse(verse_id)
    print(f"  📖 {verse['reference']} ({verse['theme']} / {verse['mood']})")

    # 2. Fetch background
    print("\n  🌄 Fetching background image...")
    bg = fetch_image(verse["image_keywords"], verse["mood"])

    # 3. Load fonts
    print("\n  🔤 Loading fonts...")
    fonts = load_fonts()

    # 4. Composite
    print("\n  🎨 Compositing post...")
    post_img = composite_post(bg, verse["text"], verse["reference"], verse["mood"], fonts)
    today    = datetime.date.today().strftime("%Y-%m-%d")
    img_path = OUTPUT_DIR / f"post_{today}_{verse['id']}.jpg"
    post_img.save(str(img_path), "JPEG", quality=97)
    print(f"  ✓ Saved: {img_path.name}")

    # 5. Generate Reel
    print("\n  🎬 Generating Reel video...")
    reel_path = generate_reel(img_path)

    # 6. Caption
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

    # 7. Upload to GitHub (reel if available, else photo)
    upload_file = str(reel_path) if reel_path else str(img_path)
    print(f"\n  📤 Uploading {'Reel' if reel_path else 'photo'} to GitHub...")
    image_url = upload_to_github(upload_file)
    if not image_url:
        print("  ✗ Upload failed — aborting post")
        return None, None

    # 7. Trigger Make → Instagram
    print("\n  📱 Triggering Make webhook...")
    trigger_make(image_url, full_caption)

    # 8. Update state
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


# ── ENTRY ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true", help="Generate only, do not post")
    parser.add_argument("--verse",   type=int, default=None, help="Force specific verse ID")
    args = parser.parse_args()
    run(preview=args.preview, verse_id=args.verse)
