#!/usr/bin/env python3
"""
generate_quizzes.py — generate domain-level quizzes from flashcard files.

Reads the per-domain JSON files in _flashcards/, aggregates all cards, and asks
GPT-4o to produce a cohesive 10–15 question quiz per domain.  Only regenerates a
domain quiz when the underlying flashcard file has changed since the last run.

Usage:
  # Process all domains with new/updated flashcards:
  python3 scripts/generate_quizzes.py

  # Specific domain file:
  python3 scripts/generate_quizzes.py _flashcards/deep-learning.json

  # Preview without API calls:
  python3 scripts/generate_quizzes.py --dry-run

  # Regenerate everything:
  python3 scripts/generate_quizzes.py --force
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
MANIFEST_FILE = REPO_ROOT / "_quiz_manifest.json"
MODEL = "gpt-4o"

SYSTEM_PROMPT = """\
You are a quiz generator for a spaced-repetition second-brain system.

You will receive a collection of flashcards from a single knowledge domain.
Produce a JSON object {"questions": [...]} with 10–15 quiz questions that test
deep understanding of the domain — not just recall of individual card facts.

Mix these three question types:
  - "mcq"          → 4-option multiple choice, exactly one correct answer
  - "short_answer" → open-ended question requiring a 1–3 sentence answer
  - "scenario"     → a short real-world or applied problem; answer explains the reasoning

Rules:
- Questions must be self-contained (no "as mentioned above" or "as stated in the note").
- Cover as many distinct topics in the domain as possible — don't cluster on one subtopic.
- Each question must include a "topic" field (2–4 word label for the sub-topic it tests).
- For MCQ include a brief "explanation" of the correct answer.
- Difficulty should range from foundational to advanced within the domain.
- Return ONLY the JSON object — no preamble, no markdown fences.

Schema:
{
  "questions": [
    {
      "type": "mcq",
      "topic": "gradient descent",
      "question": "...",
      "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
      "answer": "B",
      "explanation": "..."
    },
    {
      "type": "short_answer",
      "topic": "regularization",
      "question": "...",
      "answer": "..."
    },
    {
      "type": "scenario",
      "topic": "overfitting",
      "prompt": "Your model achieves 99% training accuracy but 60% validation accuracy. Walk through two techniques you would apply and why.",
      "answer": "..."
    }
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


def load_manifest() -> dict[str, dict]:
    if not MANIFEST_FILE.exists():
        return {}
    try:
        return json.loads(MANIFEST_FILE.read_text())
    except json.JSONDecodeError:
        return {}


def save_manifest(manifest: dict) -> None:
    MANIFEST_FILE.write_text(json.dumps(manifest, indent=2) + "\n")


def is_new_or_updated(domain_file: Path, manifest: dict) -> bool:
    key = domain_file.name
    if key not in manifest:
        return True
    return domain_file.stat().st_mtime > manifest[key].get("mtime", 0)


def build_context(entries: list[dict]) -> str:
    """Flatten all flashcard entries into a text context for the quiz prompt."""
    parts: list[str] = []
    for entry in entries:
        title = entry.get("title", "Untitled")
        parts.append(f"## {title}")
        for card in entry.get("cards", []):
            ctype = card.get("type")
            if ctype == "basic":
                parts.append(f"Q: {card.get('question', '')}\nA: {card.get('answer', '')}")
            elif ctype == "cloze":
                parts.append(f"Cloze: {card.get('text', '')}")
            elif ctype == "mcq":
                opts = card.get("options", {})
                opts_str = " | ".join(f"{k}: {v}" for k, v in opts.items())
                parts.append(
                    f"MCQ: {card.get('question', '')}\nOptions: {opts_str}\n"
                    f"Answer: {card.get('answer', '')}. {card.get('explanation', '')}"
                )
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def call_openai(client, domain: str, context: str) -> list[dict]:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Domain: {domain}\n\n"
                    f"Flashcard content:\n\n{context}\n\n"
                    "Generate a domain quiz based on the above."
                ),
            },
        ],
        max_tokens=4096,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content.strip()
    parsed = json.loads(raw)
    if isinstance(parsed, list):
        return parsed
    for v in parsed.values():
        if isinstance(v, list):
            return v
    return []


def process_domain(
    client,
    domain_file: Path,
    quizzes_dir: Path,
    manifest: dict,
    dry_run: bool,
) -> int:
    """Returns number of questions generated (0 on dry-run or skip)."""
    domain = domain_file.stem
    key = domain_file.name

    if dry_run:
        print(f"  [dry-run] {domain}")
        return 0

    print(f"  Quizzing {domain}...", end=" ", flush=True)

    entries = json.loads(domain_file.read_text())
    if not entries:
        print("→ skipped (empty flashcard file)")
        return 0

    context = build_context(entries)
    questions = call_openai(client, domain, context)

    if not questions:
        print("→ skipped (no questions generated)")
        manifest[key] = {"mtime": domain_file.stat().st_mtime, "question_count": 0,
                         "generated": date.today().isoformat()}
        return 0

    quiz = {
        "domain": domain,
        "generated": date.today().isoformat(),
        "note_count": len(entries),
        "question_count": len(questions),
        "questions": questions,
    }

    quizzes_dir.mkdir(parents=True, exist_ok=True)
    out_file = quizzes_dir / f"{domain}.json"
    out_file.write_text(json.dumps(quiz, indent=2) + "\n")

    manifest[key] = {
        "mtime": domain_file.stat().st_mtime,
        "generated": date.today().isoformat(),
        "question_count": len(questions),
    }

    print(f"→ {out_file.name} ({len(questions)} questions)")
    return len(questions)


def main() -> None:
    env = load_env()
    for k, v in env.items():
        os.environ.setdefault(k.upper(), v)
        os.environ.setdefault(k, v)

    parser = argparse.ArgumentParser(
        description="Generate domain quizzes from flashcard files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "input", nargs="?",
        default=env.get("flashcards_location") or str(REPO_ROOT / "_flashcards"),
        help="Flashcards dir or a single domain .json file (default: _flashcards/)",
    )
    parser.add_argument(
        "--quizzes-dir",
        default=env.get("quizzes_location") or str(REPO_ROOT / "_quizzes"),
        help="Output directory for domain quiz files (default: _quizzes/)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be processed, no API calls")
    parser.add_argument("--force", action="store_true", help="Regenerate quizzes for all domains")
    args = parser.parse_args()

    input_path = Path(args.input).expanduser()
    if not input_path.exists():
        sys.exit(f"Error: {input_path} does not exist")

    domain_files = [input_path] if input_path.is_file() else sorted(
        input_path.glob("*.json")
    )
    if not domain_files:
        sys.exit(f"No .json domain files found in {input_path}")

    quizzes_dir = Path(args.quizzes_dir).expanduser()
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

    to_process, skipped = [], []
    for df in domain_files:
        if args.force or is_new_or_updated(df, manifest):
            to_process.append(df)
        else:
            skipped.append(df)

    print(f"Domains: {len(domain_files)} total | {len(to_process)} to quiz | {len(skipped)} already done")

    if not to_process:
        print("Nothing to do — all domains already have up-to-date quizzes.")
        print("Use --force to regenerate all.")
        return

    print()
    total_questions = 0
    errors = 0
    domain_stats: list[tuple[str, int]] = []

    for df in to_process:
        try:
            n = process_domain(client, df, quizzes_dir, manifest, args.dry_run)
            total_questions += n
            if n > 0:
                domain_stats.append((df.stem, n))
            if not args.dry_run:
                save_manifest(manifest)
        except Exception as e:
            print(f"\n  ERROR on {df.stem}: {e}")
            errors += 1

    print(f"\nDone. {len(to_process) - errors} domain(s) quizzed, {len(skipped)} skipped, {errors} errors.")
    if not args.dry_run:
        print(f"Total questions generated this run: {total_questions}")
        print(f"Quizzes location: {quizzes_dir}/")
        if domain_stats:
            print("\nDomains:")
            for domain, count in domain_stats:
                print(f"  {domain}: {count} question(s)")


if __name__ == "__main__":
    main()
