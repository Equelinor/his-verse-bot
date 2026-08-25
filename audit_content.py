#!/usr/bin/env python3
"""
audit_content.py — permanent, rerunnable content quality audit.

Run this any time new content is generated (Year 2, Year 3, etc.) to
verify all hard requirements. Exits non-zero if any hard check fails.

Usage: python audit_content.py
"""
import csv
import sys
import unicodedata
from pathlib import Path
from collections import defaultdict, Counter

DATA_DIR = Path(__file__).parent / "data"
NIGHT_FILE = DATA_DIR / "before_you_sleep.csv"
MORNING_FILE = DATA_DIR / "what_do_you_need_today.csv"

NIGHT_FIELDS = ["id","theme","hook","prayer","scripture","scripture_ref","ending","visual_concept"]
MORNING_FIELDS = ["id","question","choices","dominant_theme","scripture","scripture_ref","cta","visual_concept"]

CONFLICT_PAIRS = [
    {"Guidance","Direction"}, {"Faith","Trust"}, {"Rest","Peace"},
    {"Restoration","Renewal"}, {"Courage","Confidence"},
]
ENGAGEMENT_BAIT_MARKERS = ["tag someone", "drop a ", "drop the ", "type '", "comment your"]
OVERPROMISE_MARKERS = ["you are safe", "you're safe", "you are covered",
                        "exactly where you need", "already prepared",
                        "nothing bad", "nothing can harm"]

results = []  # (check_name, passed_bool, detail_str)

def record(name, passed, detail=""):
    results.append((name, passed, detail))
    icon = "✅" if passed else "❌"
    print(f"{icon} {name}{': ' + detail if detail else ''}")


def min_gap(rows, field):
    positions = defaultdict(list)
    for i, r in enumerate(rows):
        positions[r[field]].append(i)
    gaps = []
    for idxs in positions.values():
        if len(idxs) > 1:
            for k in range(1, len(idxs)):
                gaps.append(idxs[k] - idxs[k-1])
    return (min(gaps) if gaps else None), len(positions)


def main():
    if not NIGHT_FILE.exists() or not MORNING_FILE.exists():
        print("❌ CSV files not found — cannot audit.")
        sys.exit(1)

    with open(NIGHT_FILE, newline="", encoding="utf-8") as f:
        night = list(csv.DictReader(f))
    with open(MORNING_FILE, newline="", encoding="utf-8") as f:
        morning = list(csv.DictReader(f))

    print("═══════════════════════════════════════════════════")
    print("   Content Audit — Before You Sleep / What Do You Need Today")
    print("═══════════════════════════════════════════════════\n")

    # 1. Exactly 400 rows per package
    record("1. Night has exactly 400 rows", len(night) == 400, f"actual={len(night)}")
    record("1. Morning has exactly 400 rows", len(morning) == 400, f"actual={len(morning)}")

    # 2. Required schema fields present
    night_headers_ok = list(night[0].keys()) == NIGHT_FIELDS if night else False
    morning_headers_ok = list(morning[0].keys()) == MORNING_FIELDS if morning else False
    record("2. Night schema matches expected fields", night_headers_ok)
    record("2. Morning schema matches expected fields", morning_headers_ok)

    # 3. Unique IDs
    night_ids = [r["id"] for r in night]
    morning_ids = [r["id"] for r in morning]
    record("3. Night IDs unique", len(night_ids) == len(set(night_ids)))
    record("3. Morning IDs unique", len(morning_ids) == len(set(morning_ids)))

    # 4. No duplicate full records
    night_full = [tuple(r.values()) for r in night]
    morning_full = [tuple(r.values()) for r in morning]
    record("4. Night no duplicate full records", len(night_full) == len(set(night_full)))
    record("4. Morning no duplicate full records", len(morning_full) == len(set(morning_full)))

    # 5. 400 unique Night prayers
    prayers = [r["prayer"] for r in night]
    record("5. 400/400 unique Night prayers", len(set(prayers)) == 400, f"unique={len(set(prayers))}")

    # 6. No duplicate choice combinations in Morning
    combos = [r["choices"] for r in morning]
    record("6. No duplicate Morning choice combos", len(set(combos)) == len(combos),
           f"unique={len(set(combos))}/{len(combos)}")

    # 7. Scripture/reference fields not empty
    empty_night = sum(1 for r in night if not r["scripture"].strip() or not r["scripture_ref"].strip())
    empty_morning = sum(1 for r in morning if not r["scripture"].strip() or not r["scripture_ref"].strip())
    record("7. Night scripture fields non-empty", empty_night == 0, f"empty={empty_night}")
    record("7. Morning scripture fields non-empty", empty_morning == 0, f"empty={empty_morning}")

    # 8. Scripture minimum spacing >= 60 days — PER PACKAGE (kept for detail)
    gap, n = min_gap(night, "scripture_ref")
    record("8. Night Scripture min spacing >= 60 days (within-package)", gap is None or gap >= 60, f"min_gap={gap}, unique_refs={n}")
    gap, n = min_gap(morning, "scripture_ref")
    record("8. Morning Scripture min spacing >= 60 days (within-package)", gap is None or gap >= 60, f"min_gap={gap}, unique_refs={n}")

    # 8b. GLOBAL combined Night+Morning 60-day cooldown (Part 1 of final
    # corrective pass) — the HARD requirement. A reference used in either
    # package must not reappear in EITHER package within 60 Bahrain days.
    combined_positions = defaultdict(list)
    for i in range(len(night)):
        combined_positions[night[i]["scripture_ref"]].append(i)
    for i in range(len(morning)):
        combined_positions[morning[i]["scripture_ref"]].append(i)
    combined_gaps = []
    combined_violations = []
    for ref, days in combined_positions.items():
        days_sorted = sorted(days)
        for k in range(1, len(days_sorted)):
            gap = days_sorted[k] - days_sorted[k-1]
            combined_gaps.append(gap)
            if gap < 60:
                combined_violations.append((ref, days_sorted[k-1], days_sorted[k], gap))
    combined_min = min(combined_gaps) if combined_gaps else None
    record("8b. GLOBAL combined Night+Morning Scripture cooldown >= 60 days",
           len(combined_violations) == 0,
           f"min_combined_gap={combined_min}, violations={len(combined_violations)}")
    if combined_violations:
        for v in combined_violations[:10]:
            print(f"      VIOLATION: {v}")

    # 9. Hook reuse spacing >= 30 days
    gap, n = min_gap(night, "hook")
    record("9. Night hook min spacing >= 30 days", gap is None or gap >= 30, f"min_gap={gap}")

    # 10. Night ending reuse spacing >= 30 days
    gap, n = min_gap(night, "ending")
    record("10. Night ending min spacing >= 30 days", gap is None or gap >= 30, f"min_gap={gap}")

    # 11. Morning question reuse spacing >= 30 days
    gap, n = min_gap(morning, "question")
    record("11. Morning question min spacing >= 30 days", gap is None or gap >= 30, f"min_gap={gap}")

    # 12. Morning CTA reuse spacing >= 30 days
    gap, n = min_gap(morning, "cta")
    record("12. Morning CTA min spacing >= 30 days", gap is None or gap >= 30, f"min_gap={gap}")

    # 13. Visual concept reuse spacing >= 30 days
    gap, n = min_gap(night, "visual_concept")
    record("13. Night visual concept min spacing >= 30 days", gap is None or gap >= 30, f"min_gap={gap}")
    gap, n = min_gap(morning, "visual_concept")
    record("13. Morning visual concept min spacing >= 30 days", gap is None or gap >= 30, f"min_gap={gap}")

    # 14. No coffee-cup visual concepts
    coffee = [r for r in night+morning if "coffee" in r["visual_concept"].lower()]
    record("14. No coffee-cup visual concepts", len(coffee) == 0, f"found={len(coffee)}")

    # 15. No Guidance + Direction (or other conflict pairs) combination
    violations = 0
    for r in morning:
        combo = set(c.split(" ",1)[1] if " " in c else c for c in r["choices"].split(" | "))
        if any(p.issubset(combo) for p in CONFLICT_PAIRS):
            violations += 1
    record("15. No conflict-pair choice combinations", violations == 0, f"violations={violations}")

    # 16. No prohibited engagement phrases
    bait = [r for r in morning if any(m in r["cta"].lower() for m in ENGAGEMENT_BAIT_MARKERS)]
    record("16. No engagement-bait CTA phrasing", len(bait) == 0, f"found={len(bait)}")

    # 17. No prohibited over-promising Night phrases
    overpromise = [r for r in night if any(m in r["ending"].lower() for m in OVERPROMISE_MARKERS)]
    overpromise += [r for r in night if any(m in r["prayer"].lower() for m in OVERPROMISE_MARKERS)]
    record("17. No over-promising Night language", len(overpromise) == 0, f"found={len(overpromise)}")

    # 17b. Emoji in the SOURCE fields that get rendered directly INTO the
    # image via Pillow (hook/prayer/ending/theme for Night; question/cta/
    # dominant_theme for Morning) is EXPECTED and fine — those same fields
    # are reused for the caption text, where emoji renders correctly via
    # Instagram/Facebook's own text engine. What actually matters is
    # whether bot.py's draw-time stripping (strip_emoji_for_display)
    # successfully removes it before it reaches Pillow, which lacks emoji
    # glyphs in its fallback fonts and would render a broken box otherwise.
    # This check imports that exact function and verifies it actually
    # works against every real value in the content pool — not just that
    # raw data happens to be emoji-free, which isn't the real requirement.
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from bot import strip_emoji_for_display, has_emoji as _bot_has_emoji
        emoji_check_available = True
    except ImportError:
        emoji_check_available = False

    if emoji_check_available:
        image_fields_night = ["hook", "prayer", "ending", "theme"]
        image_fields_morning = ["question", "cta", "dominant_theme"]
        leaks_night = [(r["id"], f) for r in night for f in image_fields_night
                       if _bot_has_emoji(strip_emoji_for_display(r[f]))]
        leaks_morning = [(r["id"], f) for r in morning for f in image_fields_morning
                         if _bot_has_emoji(strip_emoji_for_display(r[f]))]
        record("17b. Night image-render emoji stripping works for all rows", len(leaks_night) == 0,
               f"leaks_after_strip={len(leaks_night)}")
        record("17b. Morning image-render emoji stripping works for all rows", len(leaks_morning) == 0,
               f"leaks_after_strip={len(leaks_morning)}")
    else:
        print("ℹ️  17b. Skipped — bot.py not importable from this location "
              "(informational only, not a hard requirement here)")

    # 18. Static same-day collisions between Night and Morning = 0
    collisions = sum(1 for i in range(min(len(night), len(morning)))
                      if night[i]["scripture_ref"] == morning[i]["scripture_ref"])
    record("18. Zero same-day Night/Morning collisions", collisions == 0, f"collisions={collisions}")

    # 19. Unique Scripture count report
    night_refs = set(r["scripture_ref"] for r in night)
    morning_refs = set(r["scripture_ref"] for r in morning)
    print(f"\nℹ️  19. Unique Scripture: Night={len(night_refs)}, Morning={len(morning_refs)}, "
          f"combined pool={len(night_refs | morning_refs)}")

    # 19b. Translation consistency (same ref, one wording, across BOTH packages)
    ref_texts = defaultdict(set)
    for r in night + morning:
        ref_texts[r["scripture_ref"]].add(r["scripture"])
    inconsistent = {ref: t for ref, t in ref_texts.items() if len(t) > 1}
    record("19b. Translation consistency (one wording per ref)", len(inconsistent) == 0,
           f"inconsistent_refs={len(inconsistent)}")

    # 20. Unique theme/category count report
    night_themes = set(r["theme"] for r in night)
    morning_themes = set(r["dominant_theme"] for r in morning)
    print(f"ℹ️  20. Unique themes: Night={len(night_themes)}, Morning categories used={len(morning_themes)}")

    # 21. Unique visual-concept count report
    night_visuals = set(r["visual_concept"] for r in night)
    morning_visuals = set(r["visual_concept"] for r in morning)
    print(f"ℹ️  21. Unique visual concepts: Night={len(night_visuals)}, Morning={len(morning_visuals)}")

    # 22. Min/max/avg spacing report for key repeated elements
    print(f"\nℹ️  22. Spacing summary (min / avg):")
    for label, rows, field in [
        ("Night scripture", night, "scripture_ref"), ("Morning scripture", morning, "scripture_ref"),
        ("Night hook", night, "hook"), ("Night ending", night, "ending"),
        ("Morning question", morning, "question"), ("Morning CTA", morning, "cta"),
    ]:
        positions = defaultdict(list)
        for i, r in enumerate(rows):
            positions[r[field]].append(i)
        all_gaps = []
        for idxs in positions.values():
            if len(idxs) > 1:
                all_gaps.extend(idxs[k]-idxs[k-1] for k in range(1, len(idxs)))
        if all_gaps:
            print(f"     {label}: min={min(all_gaps)}, avg={sum(all_gaps)/len(all_gaps):.1f}, max={max(all_gaps)}")
        else:
            print(f"     {label}: no repeats within this content set")

    # ── FINAL RESULT ─────────────────────────────────────────────────────
    hard_checks = [r for r in results]
    failed = [r for r in hard_checks if not r[1]]
    print(f"\n═══════════════════════════════════════════════════")
    print(f"   {len(hard_checks)-len(failed)}/{len(hard_checks)} hard checks PASS")
    print(f"═══════════════════════════════════════════════════")
    if failed:
        print("\nFAILED CHECKS:")
        for name, _, detail in failed:
            print(f"  ❌ {name}: {detail}")
        sys.exit(1)
    else:
        print("\n✓ ALL HARD REQUIREMENTS PASS")
        sys.exit(0)


if __name__ == "__main__":
    main()
