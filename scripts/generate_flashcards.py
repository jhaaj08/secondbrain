#!/usr/bin/env python3
"""
generate_flashcards.py — generate flashcards and quizzes from refined Obsidian notes.

Processes only NEW or UPDATED refined notes. Uses _flashcard_manifest.json to
track what has already been flashcarded.

Usage:
  # Process all new/updated refined notes:
  python3 scripts/generate_flashcards.py

  # Specific note or folder:
  python3 scripts/generate_flashcards.py ~/Documents/Refined_Notes/Main/Artificial\ Intelligence/

  # Preview without API calls:
  python3 scripts/generate_flashcards.py --dry-run

  # Regenerate everything:
  python3 scripts/generate_flashcards.py --force
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
ENV_FILE = REPO_ROOT / ".env"
MANIFEST_FILE = REPO_ROOT / "_flashcard_manifest.json"
MODEL = "gpt-4o"

SYSTEM_PROMPT = """\
You are a flashcard generator for a second-brain spaced-repetition system.

Given a refined Obsidian note, produce a JSON object {"cards": [...]} with 3–7 study cards.
Mix the three types:
  - "basic"  → question + answer (test understanding, not trivia)
  - "cloze"  → a sentence with one key concept hidden as {{blank}}
  - "mcq"    → 4-option multiple choice (exactly one correct answer)

Rules:
- Questions must be self-contained (no "as mentioned above").
- Answers should be concise but complete.
- For MCQ include a brief "explanation" of the correct answer.
- Skip card generation if the note has no real content (stub or empty).
- Return ONLY the JSON object — no preamble, no markdown fences.

Schema:
{
  "cards": [
    {"type": "basic", "question": "...", "answer": "..."},
    {"type": "cloze", "text": "Adam uses {{bias correction}} to fix zero-initialized moments.", "hint": "optional"},
    {"type": "mcq", "question": "...", "options": {"A": "...", "B": "...", "C": "...", "D": "..."}, "answer": "B", "explanation": "..."}
  ]
}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_]+", "-", slug).strip("-") or "general"


def parse_frontmatter(text: str) -> dict:
    """Return a dict of frontmatter fields. Handles inline lists and plain strings."""
    fm: dict = {}
    if not text.startswith("---"):
        return fm
    try:
        end = text.index("---", 3)
    except ValueError:
        return fm
    fm_text = text[3:end].strip()

    for line in fm_text.splitlines():
        if ":" not in line:
            continue
        key, _, raw = line.partition(":")
        key = key.strip()
        raw = raw.strip()
        if not key:
            continue
        # inline list: [a, b, c]
        if raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1]
            fm[key] = [v.strip().strip("'\"") for v in inner.split(",") if v.strip()]
        else:
            fm[key] = raw
    return fm


def load_manifest() -> dict[str, dict]:
    if not MANIFEST_FILE.exists():
        return {}
    try:
        return json.loads(MANIFEST_FILE.read_text())
    except json.JSONDecodeError:
        return {}


def save_manifest(manifest: dict) -> None:
    MANIFEST_FILE.write_text(json.dumps(manifest, indent=2) + "\n")


def is_new_or_updated(note_path: Path, manifest: dict, key: str) -> bool:
    if key not in manifest:
        return True
    return note_path.stat().st_mtime > manifest[key].get("mtime", 0)


def load_domain_file(domain_path: Path) -> list[dict]:
    if not domain_path.exists():
        return []
    try:
        return json.loads(domain_path.read_text())
    except json.JSONDecodeError:
        return []


def save_domain_file(domain_path: Path, entries: list[dict]) -> None:
    domain_path.parent.mkdir(parents=True, exist_ok=True)
    domain_path.write_text(json.dumps(entries, indent=2) + "\n")


def upsert_entry(entries: list[dict], new_entry: dict) -> list[dict]:
    note_id = new_entry["note_id"]
    return [e for e in entries if e.get("note_id") != note_id] + [new_entry]


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def call_openai(client, content: str) -> list[dict]:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Generate flashcards for this note:\n\n{content}"},
        ],
        max_tokens=2048,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content.strip()
    parsed = json.loads(raw)
    if isinstance(parsed, list):
        return parsed
    # unwrap {"cards": [...]} or any single-key object wrapping a list
    for v in parsed.values():
        if isinstance(v, list):
            return v
    return []


def process_note(
    client,
    note_path: Path,
    flashcards_dir: Path,
    refined_root: Path,
    manifest: dict,
    dry_run: bool,
) -> int:
    """Returns number of cards generated (0 on dry-run or skip)."""
    try:
        rel = note_path.resolve().relative_to(refined_root.resolve())
    except ValueError:
        rel = Path(note_path.name)
    key = str(rel)

    if dry_run:
        print(f"  [dry-run] {rel}")
        return 0

    print(f"  Flashcarding {rel}...", end=" ", flush=True)

    content = note_path.read_text()
    fm = parse_frontmatter(content)

    domain = fm.get("domain") or "general"
    tags = fm.get("tags") or []
    title = fm.get("title") or note_path.stem
    note_id = fm.get("id") or slugify(title)

    if isinstance(tags, str):
        tags = [t.strip() for t in tags.strip("[]").split(",") if t.strip()]

    cards = call_openai(client, content)

    if not cards:
        print("→ skipped (no cards generated)")
        # still update manifest so we don't retry endlessly
        manifest[key] = {"mtime": note_path.stat().st_mtime, "cards_count": 0,
                         "flashcarded_at": date.today().isoformat(), "domain": domain}
        return 0

    entry = {
        "note_id": note_id,
        "source_note": key,
        "title": title,
        "domain": domain,
        "tags": tags,
        "updated": date.today().isoformat(),
        "cards": cards,
    }

    domain_slug = slugify(domain)
    domain_file = flashcards_dir / f"{domain_slug}.json"
    entries = load_domain_file(domain_file)
    entries = upsert_entry(entries, entry)
    save_domain_file(domain_file, entries)

    manifest[key] = {
        "mtime": note_path.stat().st_mtime,
        "flashcarded_at": date.today().isoformat(),
        "domain": domain,
        "cards_count": len(cards),
    }

    print(f"→ {domain_slug}.json ({len(cards)} cards)")
    return len(cards)


def main() -> None:
    env = load_env()
    for k, v in env.items():
        os.environ.setdefault(k.upper(), v)
        os.environ.setdefault(k, v)

    parser = argparse.ArgumentParser(
        description="Generate flashcards from refined notes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "input", nargs="?",
        default=env.get("refined_location") or None,
        help="Refined notes dir or single .md file (default: refined_location from .env)",
    )
    parser.add_argument(
        "--flashcards-dir",
        default=env.get("flashcards_location") or str(REPO_ROOT / "_flashcards"),
        help="Output directory for domain flashcard files",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be processed, no API calls")
    parser.add_argument("--force", action="store_true", help="Regenerate flashcards for all notes")
    args = parser.parse_args()

    if not args.input:
        sys.exit("Error: no input path given and refined_location is not set in .env")

    refined_root = Path(args.input).expanduser()
    flashcards_dir = Path(args.flashcards_dir).expanduser()

    if not refined_root.exists():
        sys.exit(f"Error: {refined_root} does not exist")

    manifest = load_manifest()

    if not args.dry_run:
        try:
            from openai import OpenAI
        except ImportError:
            sys.exit("Error: openai package not installed. Run: pip3 install openai")
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("openai_api_key")
        if not api_key:
            sys.exit("Error: openai_api_key not set in .env")
        client = OpenAI(api_key=api_key)
    else:
        client = None

    all_notes = [refined_root] if refined_root.is_file() else sorted(
        refined_root.rglob("*.md")
    )

    if not all_notes:
        sys.exit(f"No .md files found in {refined_root}")

    to_process, skipped = [], []
    for note_path in all_notes:
        try:
            rel = note_path.resolve().relative_to(refined_root.resolve())
        except ValueError:
            rel = Path(note_path.name)
        key = str(rel)
        if args.force or is_new_or_updated(note_path, manifest, key):
            to_process.append(note_path)
        else:
            skipped.append(note_path)

    print(f"Refined notes: {len(all_notes)} total | {len(to_process)} to flashcard | {len(skipped)} already done")

    if not to_process:
        print("Nothing to do — all notes already have flashcards.")
        print("Use --force to regenerate all.")
        return

    print()
    total_cards = 0
    errors = 0
    for note_path in to_process:
        try:
            n = process_note(client, note_path, flashcards_dir, refined_root, manifest, args.dry_run)
            total_cards += n
            if not args.dry_run:
                save_manifest(manifest)  # persist after each note
        except Exception as e:
            try:
                rel = note_path.resolve().relative_to(refined_root.resolve())
            except ValueError:
                rel = Path(note_path.name)
            print(f"\n  ERROR on {rel}: {e}")
            errors += 1

    print(f"\nDone. {len(to_process) - errors} note(s) flashcarded, {len(skipped)} skipped, {errors} errors.")
    if not args.dry_run:
        print(f"Total cards generated this run: {total_cards}")
        print(f"Flashcards location: {flashcards_dir}/")

        if flashcards_dir.exists():
            print("\nDomains:")
            for f in sorted(flashcards_dir.glob("*.json")):
                try:
                    entries = json.loads(f.read_text())
                    note_count = len(entries)
                    card_count = sum(len(e.get("cards", [])) for e in entries)
                    print(f"  {f.stem}: {note_count} note(s), {card_count} card(s)")
                except Exception:
                    pass


if __name__ == "__main__":
    main()
