#!/usr/bin/env python3
"""
setup_db.py — one-time database setup and data import.

Creates second_brain.db with the full schema, then loads:
  - All _flashcards/*.json  → notes + cards tables
  - All _quizzes/*.json     → quiz_items table

Safe to re-run: uses INSERT OR REPLACE for notes/cards and ignores
duplicate quiz_items (matched on domain + question text).

Usage:
  python3 scripts/setup_db.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DB_PATH = Path(os.environ.get("DATABASE_PATH", str(REPO_ROOT / "second_brain.db")))
FLASHCARDS_DIR = REPO_ROOT / "_flashcards"
QUIZZES_DIR = REPO_ROOT / "_quizzes"

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    domain TEXT NOT NULL,
    tags TEXT NOT NULL,
    source_path TEXT,
    updated TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id TEXT NOT NULL,
    card_type TEXT NOT NULL,
    question TEXT,
    answer TEXT,
    cloze_text TEXT,
    hint TEXT,
    options TEXT,
    explanation TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    ease_factor REAL NOT NULL DEFAULT 2.5,
    interval_days INTEGER NOT NULL DEFAULT 0,
    repetitions INTEGER NOT NULL DEFAULT 0,
    lapses INTEGER NOT NULL DEFAULT 0,
    due_date TEXT,
    last_seen TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (note_id) REFERENCES notes(id)
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER NOT NULL,
    rating TEXT NOT NULL,
    reviewed_at TEXT DEFAULT CURRENT_TIMESTAMP,
    interval_before INTEGER,
    interval_after INTEGER,
    FOREIGN KEY (card_id) REFERENCES cards(id)
);

CREATE TABLE IF NOT EXISTS quiz_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,
    topic TEXT NOT NULL,
    item_type TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    options TEXT,
    explanation TEXT,
    times_seen INTEGER DEFAULT 0,
    times_correct INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS quiz_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quiz_item_id INTEGER NOT NULL,
    user_answer TEXT,
    was_correct INTEGER,
    attempted_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (quiz_item_id) REFERENCES quiz_items(id)
);

CREATE INDEX IF NOT EXISTS idx_cards_due ON cards(due_date) WHERE status != 'archived';
CREATE INDEX IF NOT EXISTS idx_cards_note ON cards(note_id);
CREATE INDEX IF NOT EXISTS idx_quiz_domain ON quiz_items(domain);
"""


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def load_flashcards(conn: sqlite3.Connection) -> tuple[int, int]:
    """Returns (notes_inserted, cards_inserted)."""
    notes_inserted = 0
    cards_inserted = 0

    for domain_file in sorted(FLASHCARDS_DIR.glob("*.json")):
        entries = json.loads(domain_file.read_text())
        for entry in entries:
            note_id = entry.get("note_id", "")
            if not note_id:
                continue

            tags = entry.get("tags", [])
            conn.execute(
                """
                INSERT OR REPLACE INTO notes (id, title, domain, tags, source_path, updated)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    note_id,
                    entry.get("title", ""),
                    entry.get("domain", "general"),
                    json.dumps(tags),
                    entry.get("source_note"),
                    entry.get("updated", ""),
                ),
            )
            notes_inserted += 1

            # Remove existing cards for this note so we don't duplicate on re-import
            conn.execute("DELETE FROM cards WHERE note_id = ?", (note_id,))

            for card in entry.get("cards", []):
                ctype = card.get("type", "basic")
                conn.execute(
                    """
                    INSERT INTO cards
                        (note_id, card_type, question, answer, cloze_text, hint, options, explanation)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        note_id,
                        ctype,
                        card.get("question"),
                        card.get("answer"),
                        card.get("text"),           # cloze
                        card.get("hint"),
                        json.dumps(card["options"]) if "options" in card else None,
                        card.get("explanation"),
                    ),
                )
                cards_inserted += 1

    conn.commit()
    return notes_inserted, cards_inserted


def load_quizzes(conn: sqlite3.Connection) -> int:
    """Returns number of quiz_items inserted."""
    inserted = 0

    for quiz_file in sorted(QUIZZES_DIR.glob("*.json")):
        quiz = json.loads(quiz_file.read_text())
        domain = quiz.get("domain", quiz_file.stem)

        for q in quiz.get("questions", []):
            item_type = q.get("type", "mcq")
            # scenario questions use "prompt" as the question field
            question_text = q.get("question") or q.get("prompt", "")
            answer = q.get("answer", "")
            options = q.get("options")
            explanation = q.get("explanation")
            topic = q.get("topic", "")

            # Deduplicate: skip if exact (domain, question) already exists
            existing = conn.execute(
                "SELECT id FROM quiz_items WHERE domain = ? AND question = ?",
                (domain, question_text),
            ).fetchone()
            if existing:
                continue

            conn.execute(
                """
                INSERT INTO quiz_items (domain, topic, item_type, question, answer, options, explanation)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    domain,
                    topic,
                    item_type,
                    question_text,
                    answer,
                    json.dumps(options) if options else None,
                    explanation,
                ),
            )
            inserted += 1

    conn.commit()
    return inserted


def print_summary(conn: sqlite3.Connection) -> None:
    print("\nDatabase summary:")
    for table in ("notes", "cards", "reviews", "quiz_items", "quiz_attempts"):
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:<20} {count:>6} row(s)")

    print("\nCards by domain:")
    rows = conn.execute(
        """
        SELECT n.domain, COUNT(c.id) AS card_count
        FROM cards c JOIN notes n ON c.note_id = n.id
        GROUP BY n.domain ORDER BY card_count DESC
        """
    ).fetchall()
    for domain, count in rows:
        print(f"  {domain:<30} {count:>5} card(s)")

    print("\nQuiz items by domain:")
    rows = conn.execute(
        "SELECT domain, COUNT(*) FROM quiz_items GROUP BY domain ORDER BY COUNT(*) DESC"
    ).fetchall()
    for domain, count in rows:
        print(f"  {domain:<30} {count:>5} question(s)")


def main() -> None:
    if not FLASHCARDS_DIR.exists():
        sys.exit(f"Error: {FLASHCARDS_DIR} not found — run generate_flashcards.py first")
    if not QUIZZES_DIR.exists():
        sys.exit(f"Error: {QUIZZES_DIR} not found — run generate_quizzes.py first")

    print(f"Setting up database at {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    print("Creating schema...", end=" ")
    create_schema(conn)
    print("done")

    print("Loading flashcards...", end=" ", flush=True)
    notes, cards = load_flashcards(conn)
    print(f"{notes} notes, {cards} cards")

    print("Loading quizzes...", end=" ", flush=True)
    quiz_items = load_quizzes(conn)
    print(f"{quiz_items} quiz items")

    print_summary(conn)
    conn.close()
    print(f"\nDatabase ready: {DB_PATH}")


if __name__ == "__main__":
    main()
