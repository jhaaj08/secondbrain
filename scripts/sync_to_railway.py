#!/usr/bin/env python3
"""
sync_to_railway.py — push new notes, cards, and quiz items to the Railway DB.

Reads all domain JSON files from _flashcards/ and _quizzes/, then POSTs them
to the /admin/sync endpoint on the Railway deployment.

Design: additive-only. Existing notes and cards are never overwritten, so
SM-2 review state (ease factor, intervals, due dates) is always preserved.
Only net-new notes/cards/quiz-items are inserted.

Usage:
  python3 scripts/sync_to_railway.py            # sync to Railway
  python3 scripts/sync_to_railway.py --dry-run  # preview payload, no network call
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
ENV_FILE  = REPO_ROOT / ".env"
FLASHCARDS_DIR = REPO_ROOT / "_flashcards"
QUIZZES_DIR    = REPO_ROOT / "_quizzes"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if not ENV_FILE.exists():
        return env
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        env[key.strip()] = val.strip()
    return env


def main() -> None:
    env = load_env()
    for k, v in env.items():
        os.environ.setdefault(k.upper(), v)
        os.environ.setdefault(k, v)

    parser = argparse.ArgumentParser(
        description="Sync new flashcards and quiz items to Railway DB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--dry-run", action="store_true", help="Show payload size, no network call")
    args = parser.parse_args()

    railway_url = (
        os.environ.get("RAILWAY_URL") or os.environ.get("railway_url") or ""
    ).rstrip("/")

    if not railway_url and not args.dry_run:
        sys.exit(
            "Error: RAILWAY_URL not set in .env\n"
            "Add a line like: RAILWAY_URL=https://secondbrain-production-fde2.up.railway.app"
        )

    # ── Load flashcard domain files ──────────────────────────────────────
    flashcards: dict[str, list] = {}
    fc_notes = 0
    fc_cards = 0
    for f in sorted(FLASHCARDS_DIR.glob("*.json")):
        entries = json.loads(f.read_text())
        flashcards[f.stem] = entries
        fc_notes += len(entries)
        fc_cards += sum(len(e.get("cards", [])) for e in entries)
        print(f"  _flashcards/{f.name}: {len(entries)} notes")

    # ── Load quiz domain files ───────────────────────────────────────────
    quizzes: dict[str, dict] = {}
    qz_items = 0
    for f in sorted(QUIZZES_DIR.glob("*.json")):
        quiz = json.loads(f.read_text())
        quizzes[f.stem] = quiz
        qz_items += len(quiz.get("questions", []))
        print(f"  _quizzes/{f.name}: {len(quiz.get('questions', []))} questions")

    payload_bytes = json.dumps({"flashcards": flashcards, "quizzes": quizzes}).encode()
    print(f"\nPayload: {fc_notes} notes · {fc_cards} cards · {qz_items} quiz items "
          f"({len(payload_bytes) / 1024:.0f} KB)")
    print(f"Target:  {railway_url}/admin/sync" if railway_url else "Target:  (dry-run, no URL needed)")

    if args.dry_run:
        print("Dry run — nothing sent.")
        return

    # ── POST to Railway ──────────────────────────────────────────────────
    print("\nSyncing...", flush=True)
    try:
        req = urllib.request.Request(
            f"{railway_url}/admin/sync",
            data=payload_bytes,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        sys.exit(f"HTTP {e.code}: {body}")
    except Exception as e:
        sys.exit(f"Sync failed: {e}")

    print(f"Done.")
    print(f"  Notes inserted:     {result['notes_inserted']}")
    print(f"  Cards inserted:     {result['cards_inserted']}")
    print(f"  Quiz items inserted:{result['quiz_items_inserted']}")
    print(f"  Notes skipped:      {result['notes_skipped']}  (already in DB — review state preserved)")
    print(f"  Quiz items skipped: {result['quiz_items_skipped']}  (already in DB)")


if __name__ == "__main__":
    main()
