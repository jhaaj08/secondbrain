#!/usr/bin/env python3
"""
refine_vault.py — batch orchestration for the obsidian-refiner skill.

By default processes only NEW or UPDATED notes — notes with no refined
counterpart yet, or whose source file is newer than the last refined output.
Use --force to reprocess everything.

Usage:
  # Process all new/updated notes (reads notes_location from .env):
  python3 scripts/refine_vault.py

  # Single note:
  python3 scripts/refine_vault.py ~/Documents/Main_Notes/Main/Physics/note.md

  # Specific folder:
  python3 scripts/refine_vault.py ~/Documents/Main_Notes/Main/Photography/

  # Dry-run — show what would be processed, no API calls:
  python3 scripts/refine_vault.py --dry-run

  # Force reprocess everything (ignore existing refined outputs):
  python3 scripts/refine_vault.py --force
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SKILL_MD = REPO_ROOT / ".claude/skills/obsidian-refiner/SKILL.md"
ENV_FILE = REPO_ROOT / ".env"
DELIMITER = "---SUGGESTED-NEW-NOTES---"
MODEL = "gpt-4o"


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


def load_skill_instructions() -> str:
    if not SKILL_MD.exists():
        sys.exit(f"Error: skill not found at {SKILL_MD}")
    return SKILL_MD.read_text()


def build_vault_titles(vault_dir: Path) -> list[dict]:
    titles = []
    for md_file in sorted(vault_dir.rglob("*.md")):
        if "Refined_Notes" in md_file.parts or "vault_refined" in md_file.parts:
            continue
        title = md_file.stem
        slug = re.sub(r"[^\w\s-]", "", title.lower())
        slug = re.sub(r"[\s_]+", "-", slug).strip("-")
        titles.append({"id": slug, "title": title})
    return titles


def resolve_output_path(note_path: Path, output_dir: Path, vault_root: Path) -> Path:
    try:
        rel = note_path.resolve().relative_to(vault_root.resolve())
    except ValueError:
        rel = Path(note_path.name)
    return output_dir / rel


def is_new_or_updated(note_path: Path, out_path: Path) -> bool:
    """True if out_path doesn't exist or source is newer than output."""
    if not out_path.exists():
        return True
    return note_path.stat().st_mtime > out_path.stat().st_mtime


def build_user_message(raw_note: str, vault_titles: list[dict], domain_hint: str | None) -> str:
    from datetime import date
    today = date.today().isoformat()
    return (
        f"Today's date is {today}. Use this for `created` (if not already set) and `updated` fields.\n\n"
        "Apply the obsidian-refiner skill to the following note.\n\n"
        f"**vault_titles:**\n{json.dumps(vault_titles, indent=2)}\n\n"
        f"**domain_hint:** {domain_hint or 'infer from content'}\n\n"
        f"**raw_note:**\n{raw_note}\n\n"
        "---\n"
        "OUTPUT FORMAT — copy this structure exactly, replacing the placeholders:\n\n"
        "---\n"
        "<yaml frontmatter>\n"
        "---\n\n"
        "# <Title>\n\n"
        "<refined body with wiki-links>\n\n"
        "## Loose threads\n"
        "<bullets if any — omit section if none>\n\n"
        "---SUGGESTED-NEW-NOTES---\n"
        '[{"proposed_title": "...", "context": "..."}, ...]\n\n'
        "RULES:\n"
        "- Begin your response with `---` (the YAML opening). No code fences, no preamble.\n"
        "- The line `---SUGGESTED-NEW-NOTES---` is REQUIRED. It must appear verbatim.\n"
        "- After it, output a JSON array. Use [] if there are no suggestions.\n"
        "- Nothing comes after the JSON array."
    )


def call_openai(client, system: str, user_msg: str) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=4096,
    )
    return response.choices[0].message.content


def clean_note(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.index("\n")
        text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[: text.rfind("```")].rstrip()
    return text


def split_output(response: str) -> tuple[str, list[dict]]:
    if DELIMITER in response:
        note_part, stubs_raw = response.split(DELIMITER, 1)
        try:
            stubs = json.loads(stubs_raw.strip())
        except json.JSONDecodeError:
            stubs = []
    else:
        note_part = response
        stubs = []
    return clean_note(note_part), stubs


def merge_stubs(stubs_file: Path, new_stubs: list[dict]) -> None:
    existing: list[dict] = []
    if stubs_file.exists():
        try:
            existing = json.loads(stubs_file.read_text())
        except json.JSONDecodeError:
            pass
    seen = {s["proposed_title"] for s in existing}
    for stub in new_stubs:
        if stub.get("proposed_title") not in seen:
            existing.append(stub)
            seen.add(stub["proposed_title"])
    stubs_file.write_text(json.dumps(existing, indent=2) + "\n")


def process_note(
    client,
    note_path: Path,
    out_path: Path,
    stubs_file: Path,
    vault_titles: list[dict],
    domain_hint: str | None,
    dry_run: bool,
    system: str,
    rel: Path,
) -> None:
    if dry_run:
        raw_note = note_path.read_text()
        user_msg = build_user_message(raw_note, vault_titles, domain_hint)
        print(f"  [dry-run] {rel} — would send {len(user_msg)} chars to {MODEL}")
        return

    print(f"  Refining {rel}...", end=" ", flush=True)
    raw_note = note_path.read_text()
    user_msg = build_user_message(raw_note, vault_titles, domain_hint)
    response = call_openai(client, system, user_msg)
    refined_md, stubs = split_output(response)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(refined_md + "\n")
    print(f"→ {out_path}")

    if stubs:
        merge_stubs(stubs_file, stubs)
        print(f"    {len(stubs)} stub(s) → {stubs_file.name}")


def main() -> None:
    env = load_env()

    for k, v in env.items():
        os.environ.setdefault(k.upper(), v)
        os.environ.setdefault(k, v)

    parser = argparse.ArgumentParser(
        description="Refine new/updated Obsidian notes via the obsidian-refiner skill",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "input", nargs="?",
        default=env.get("notes_location") or None,
        help="A .md file or directory (default: notes_location from .env)",
    )
    parser.add_argument(
        "--output",
        default=env.get("refined_location") or "vault_refined",
        help="Output directory (default: refined_location from .env)",
    )
    parser.add_argument("--stubs", default="_stubs_to_create.json", help="Stubs accumulation file")
    parser.add_argument("--domain", help="Domain hint (e.g. deep-learning, options, photography)")
    parser.add_argument("--vault", help="Vault root for title indexing (default: input dir)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be processed, no API calls")
    parser.add_argument("--force", action="store_true", help="Reprocess all notes, even already-refined ones")
    args = parser.parse_args()

    if not args.input:
        sys.exit(
            "Error: no input path given and notes_location is not set in .env\n"
            "Usage: python3 scripts/refine_vault.py <note_or_dir>"
        )

    input_path = Path(args.input).expanduser()
    output_dir = Path(args.output).expanduser()
    stubs_file = Path(args.stubs)

    if not input_path.exists():
        sys.exit(f"Error: {input_path} does not exist")

    vault_root = Path(args.vault).expanduser() if args.vault else (
        input_path if input_path.is_dir() else input_path.parent
    )

    vault_titles = build_vault_titles(vault_root)
    system = load_skill_instructions()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not args.dry_run:
        try:
            from openai import OpenAI
        except ImportError:
            sys.exit("Error: openai package not installed. Run: pip3 install openai")
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("openai_api_key")
        if not api_key:
            sys.exit("Error: openai_api_key not set in .env and OPENAI_API_KEY not in environment")
        client = OpenAI(api_key=api_key)
    else:
        client = None

    all_notes = [input_path] if input_path.is_file() else sorted(
        p for p in input_path.rglob("*.md")
        if "Refined_Notes" not in p.parts and "vault_refined" not in p.parts
    )

    if not all_notes:
        sys.exit(f"No .md files found in {input_path}")

    # Partition into new/updated vs already up-to-date
    to_process = []
    skipped = []
    for note_path in all_notes:
        out_path = resolve_output_path(note_path, output_dir, vault_root)
        if args.force or is_new_or_updated(note_path, out_path):
            to_process.append((note_path, out_path))
        else:
            skipped.append(note_path)

    print(f"Vault: {len(vault_titles)} notes indexed from {vault_root}")
    print(f"Found:  {len(all_notes)} total | {len(to_process)} to process | {len(skipped)} already up to date")

    if not to_process:
        print("Nothing to do — all notes are already refined and up to date.")
        print("Use --force to reprocess everything.")
        return

    print()
    for note_path, out_path in to_process:
        try:
            rel = note_path.resolve().relative_to(vault_root.resolve())
        except ValueError:
            rel = Path(note_path.name)
        process_note(client, note_path, out_path, stubs_file,
                     vault_titles, args.domain, args.dry_run, system, rel)

    print(f"\nDone. {len(to_process)} note(s) processed, {len(skipped)} skipped.")


if __name__ == "__main__":
    main()
