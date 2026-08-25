#!/usr/bin/env python3
"""
check_inventory.py — content library health check, corrected thresholds.

  >90 remaining  -> ACTIVE
  61-90 remaining -> NOTICE
  31-60 remaining -> WARNING
  16-30 remaining -> CRITICAL
  0-15 remaining  -> URGENT

Prints to stdout (visible in GitHub Actions logs) and writes a markdown
summary to $GITHUB_STEP_SUMMARY when running inside GitHub Actions, so
inventory status shows up in the job summary without anyone needing to
remember to check manually.
"""
import csv
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

PACKAGES = [
    {"name": "Before You Sleep 🌙",         "csv_file": DATA_DIR / "before_you_sleep.csv",         "state_file": DATA_DIR / "night_state.json"},
    {"name": "What Do You Need Today? ☀️",  "csv_file": DATA_DIR / "what_do_you_need_today.csv",   "state_file": DATA_DIR / "morning_state.json"},
    {"name": "Daily Verse (existing)",       "csv_file": DATA_DIR / "verses.csv",                   "state_file": DATA_DIR / "state.json"},
    {"name": "Engagement Reels (existing)",  "csv_file": DATA_DIR / "engagement_reels.csv",         "state_file": DATA_DIR / "engagement_state.json"},
]

# Corrected boundaries — checked highest floor first
THRESHOLDS = [(91, "ACTIVE"), (61, "NOTICE"), (31, "WARNING"), (16, "CRITICAL"), (0, "URGENT")]
STATUS_ICONS = {"ACTIVE": "✅", "NOTICE": "🟡", "WARNING": "🟠", "CRITICAL": "🔴", "URGENT": "🚨"}

def get_status(remaining):
    for floor, label in THRESHOLDS:
        if remaining >= floor:
            return label
    return "URGENT"

def check_package(pkg):
    if not pkg["csv_file"].exists():
        return {"name": pkg["name"], "error": f"CSV not found: {pkg['csv_file']}"}
    with open(pkg["csv_file"], newline="", encoding="utf-8") as f:
        total = sum(1 for _ in csv.DictReader(f))
    posted = 0
    if pkg["state_file"].exists():
        try:
            state = json.loads(pkg["state_file"].read_text())
            posted = len(state.get("posted_ids", []))
        except (json.JSONDecodeError, FileNotFoundError):
            pass
    remaining = total - posted
    return {"name": pkg["name"], "total": total, "posted": posted,
            "remaining": remaining, "status": get_status(remaining)}

def main():
    print("\n═══════════════════════════════════════════════════")
    print("   Content Library Inventory Check")
    print("═══════════════════════════════════════════════════\n")

    summary_lines = ["## 📦 Content Inventory\n", "| Package | Remaining | Status |", "|---|---|---|"]
    status_counts = {"ACTIVE": 0, "NOTICE": 0, "WARNING": 0, "CRITICAL": 0, "URGENT": 0}
    error_count = 0

    for pkg in PACKAGES:
        result = check_package(pkg)
        if "error" in result:
            print(f"  ⚠️  {result['name']}: {result['error']}")
            summary_lines.append(f"| {result['name']} | — | ⚠️ ERROR |")
            error_count += 1
            continue
        icon = STATUS_ICONS[result["status"]]
        print(f"  {icon} {result['name']}")
        print(f"     {result['remaining']} posts remaining ({result['posted']} used of {result['total']} total) — {result['status']}")
        summary_lines.append(f"| {result['name']} | {result['remaining']} | {icon} {result['status']} |")
        status_counts[result["status"]] += 1

        # GitHub annotations for NOTICE and above — not just CRITICAL/URGENT
        if result["status"] == "NOTICE":
            print(f"::notice::{result['name']} — {result['remaining']} remaining. Early notice; no action needed yet.")
        elif result["status"] == "WARNING":
            print(f"::warning::{result['name']} — {result['remaining']} remaining. Replenishment should be planned.")
        elif result["status"] == "CRITICAL":
            print(f"::warning::{result['name']} — {result['remaining']} remaining. CRITICAL — strong warning, replenish soon.")
        elif result["status"] == "URGENT":
            print(f"::error::{result['name']} — {result['remaining']} remaining. URGENT — immediate action required.")
        print()

    print("═══════════════════════════════════════════════════")
    # Never claim "healthy" unless every package is genuinely ACTIVE
    if error_count > 0:
        print("  ⚠️  One or more packages could not be checked.")
    elif status_counts["URGENT"] > 0:
        print("  🚨 URGENT: at least one package needs immediate replenishment.")
    elif status_counts["CRITICAL"] > 0:
        print("  🔴 CRITICAL: at least one package needs replenishment soon.")
    elif status_counts["WARNING"] > 0:
        print("  🟠 WARNING: replenishment should be planned for at least one package.")
    elif status_counts["NOTICE"] > 0:
        print("  🟡 NOTICE: at least one package is past the healthy threshold — early heads up.")
    else:
        print("  ✅ All packages ACTIVE and healthy.")
    print("═══════════════════════════════════════════════════\n")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write("\n".join(summary_lines) + "\n")

    # Never fail the workflow just because inventory is low — posting must
    # continue regardless, per explicit instruction
    return 0

if __name__ == "__main__":
    exit(main())
