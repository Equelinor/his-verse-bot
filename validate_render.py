#!/usr/bin/env python3
"""
validate_render.py — layout-fit validation against ALL 800 records
(400 Night + 400 Morning), using the real fit_scale_for_block() logic
from bot.py. Uses a controlled solid-color background (not live Unsplash
downloads) since only text/layout geometry is being tested here.

Usage: python validate_render.py
Exit code 0 if 800/800 pass, 1 otherwise.
"""
import sys
import csv
from pathlib import Path
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
import bot

DATA_DIR = Path(__file__).parent / "data"

def check_night_record(draw, fonts, row):
    scripture_block = f"\u201C{row['scripture']}\u201D\n— {row['scripture_ref']}"
    segments = [
        (row['hook'], fonts['hook'], 1.42, 20),
        (row['prayer'], fonts['verse'], 1.42, 16),
        (scripture_block, fonts['ref'], 1.21, 34),
        (row['ending'], fonts['handle'], 1.42, 0),
    ]
    scale, fits = bot.fit_scale_for_block(draw, segments)
    return fits, scale

def check_morning_record(draw, fonts, row):
    choice_display = " / ".join(c.split(" ",1)[-1] if " " in c else c for c in row['choices'].split(" | "))
    scripture_block = f"\u201C{row['scripture']}\u201D\n— {row['scripture_ref']}"
    segments = [
        (row['question'], fonts['hook'], 1.42, 24),
        (choice_display, fonts['verse'], 1.30*4, 20),
        (scripture_block, fonts['ref'], 1.21, 34),
        (row['cta'], fonts['handle'], 1.42, 0),
    ]
    scale, fits = bot.fit_scale_for_block(draw, segments)
    return fits, scale


def main():
    fonts = bot.load_fonts()
    dummy = Image.new("RGB", (bot.POST_SIZE[0], bot.POST_SIZE[1]), (20, 20, 20))
    draw = ImageDraw.Draw(dummy)

    with open(DATA_DIR / "before_you_sleep.csv", newline="", encoding="utf-8") as f:
        night = list(csv.DictReader(f))
    with open(DATA_DIR / "what_do_you_need_today.csv", newline="", encoding="utf-8") as f:
        morning = list(csv.DictReader(f))

    print("═══════════════════════════════════════════════════")
    print("   800-Record Render Validation")
    print("═══════════════════════════════════════════════════\n")

    night_fail = []
    for r in night:
        fits, scale = check_night_record(draw, fonts, r)
        if not fits:
            night_fail.append((r["id"], scale))

    morning_fail = []
    for r in morning:
        fits, scale = check_morning_record(draw, fonts, r)
        if not fits:
            morning_fail.append((r["id"], scale))

    print(f"Night layout validation:")
    print(f"{len(night) - len(night_fail)}/{len(night)} PASS")
    if night_fail:
        print(f"  FAILED IDs: {night_fail}")

    print(f"\nMorning layout validation:")
    print(f"{len(morning) - len(morning_fail)}/{len(morning)} PASS")
    if morning_fail:
        print(f"  FAILED IDs: {morning_fail}")

    total = len(night) + len(morning)
    total_fail = len(night_fail) + len(morning_fail)
    print(f"\nTotal: {total - total_fail}/{total} PASS")

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
