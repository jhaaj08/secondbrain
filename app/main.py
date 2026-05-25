"""
Second Brain — FastAPI backend.

Endpoints
---------
GET  /health                       liveness probe
GET  /stats                        overview counts + per-domain breakdown
GET  /cards/due                    cards due today + new cards
GET  /cards/{id}                   single card
POST /cards/{id}/review            submit SM-2 rating → updates card + logs review

GET  /quiz/domains                 list domains with question counts
GET  /quiz/{domain}?limit=10       random quiz questions for a domain
POST /quiz/{item_id}/attempt       record a quiz answer
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.sm2 import sm2_update

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_PATH = os.environ.get(
    "DATABASE_PATH",
    str(Path(__file__).parent.parent / "second_brain.db"),
)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Second Brain API",
    version="1.0.0",
    description="Spaced-repetition flashcards and domain quizzes from your Obsidian vault.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent.parent / "static"

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))

@app.get("/manifest.json", include_in_schema=False)
def manifest():
    return FileResponse(str(STATIC_DIR / "manifest.json"), media_type="application/manifest+json")

@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(str(STATIC_DIR / "sw.js"), media_type="application/javascript")

@app.get("/icon-192.png", include_in_schema=False)
def icon_192():
    return FileResponse(str(STATIC_DIR / "icon-192.png"), media_type="image/png")

@app.get("/icon-512.png", include_in_schema=False)
def icon_512():
    return FileResponse(str(STATIC_DIR / "icon-512.png"), media_type="image/png")

# ---------------------------------------------------------------------------
# DB dependency
# ---------------------------------------------------------------------------

def get_db():
    # check_same_thread=False is required because FastAPI runs sync endpoints
    # in a thread pool — the connection may be created and used in different threads.
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class ReviewRequest(BaseModel):
    rating: str  # "again" | "hard" | "good" | "easy"

class AttemptRequest(BaseModel):
    user_answer: str
    was_correct: bool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def deserialize_row(row) -> dict:
    """Convert a sqlite3.Row to dict, JSON-parsing options/tags fields."""
    d = dict(row)
    for key in ("options", "tags"):
        if d.get(key):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return d

# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "db": DB_PATH}

# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@app.get("/stats", tags=["meta"])
def get_stats(db: sqlite3.Connection = Depends(get_db)):
    today = date.today().isoformat()

    total          = db.execute("SELECT COUNT(*) FROM cards WHERE status != 'archived'").fetchone()[0]
    new_cards      = db.execute("SELECT COUNT(*) FROM cards WHERE status = 'new'").fetchone()[0]
    due_today      = db.execute(
        """SELECT COUNT(*) FROM cards
           WHERE status != 'archived'
             AND (
               (due_date IS NOT NULL AND due_date <= ?)
               OR status = 'new'
             )""",
        (today,),
    ).fetchone()[0]
    reviewed_today = db.execute(
        "SELECT COUNT(*) FROM reviews WHERE DATE(reviewed_at) = ?", (today,)
    ).fetchone()[0]
    total_reviews  = db.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]

    domains = db.execute(
        """
        SELECT
            n.domain,
            COUNT(c.id)                                                       AS total_cards,
            SUM(CASE WHEN c.status = 'new' THEN 1 ELSE 0 END)                AS new_cards,
            SUM(CASE WHEN c.status != 'archived'
                          AND ((c.due_date IS NOT NULL AND c.due_date <= ?) OR c.status = 'new')
                     THEN 1 ELSE 0 END)                                       AS due_cards,
            SUM(CASE WHEN c.status = 'reviewing' THEN 1 ELSE 0 END)          AS reviewing
        FROM cards c
        JOIN notes n ON c.note_id = n.id
        GROUP BY n.domain
        ORDER BY total_cards DESC
        """,
        (today,),
    ).fetchall()

    return {
        "total_cards":     total,
        "new_cards":       new_cards,
        "due_today":       due_today,
        "reviewed_today":  reviewed_today,
        "total_reviews":   total_reviews,
        "domains":         [dict(r) for r in domains],
    }

# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------

@app.get("/cards/due", tags=["cards"])
def get_due_cards(
    limit:     int = Query(20, ge=1, le=100),
    new_limit: int = Query(10, ge=0, le=50),
    domain:    Optional[str] = Query(None),
    db: sqlite3.Connection = Depends(get_db),
):
    """
    Returns cards due for review today (overdue first), then fills remaining
    slots with new (never-seen) cards up to `new_limit`.
    Optionally filter by `domain`.
    """
    today = date.today().isoformat()
    domain_filter = "AND n.domain = ?" if domain else ""
    params_base   = (today, limit) if not domain else (today, domain, limit)
    params_new    = (new_limit,)   if not domain else (domain, new_limit)

    due = db.execute(
        f"""
        SELECT c.*, n.domain, n.title
        FROM cards c JOIN notes n ON c.note_id = n.id
        WHERE c.status != 'archived'
          AND c.due_date IS NOT NULL
          AND c.due_date <= ?
          {domain_filter}
        ORDER BY c.due_date ASC
        LIMIT ?
        """,
        params_base,
    ).fetchall()

    new_cards = []
    if len(due) < limit:
        new_cards = db.execute(
            f"""
            SELECT c.*, n.domain, n.title
            FROM cards c JOIN notes n ON c.note_id = n.id
            WHERE c.status = 'new' AND c.due_date IS NULL
              {domain_filter}
            LIMIT ?
            """,
            params_new,
        ).fetchall()

    cards = [deserialize_row(r) for r in due] + [deserialize_row(r) for r in new_cards]
    return {
        "cards":     cards,
        "due_count": len(due),
        "new_count": len(new_cards),
        "total":     len(cards),
    }


@app.get("/cards/{card_id}", tags=["cards"])
def get_card(card_id: int, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute(
        "SELECT c.*, n.domain, n.title FROM cards c JOIN notes n ON c.note_id = n.id WHERE c.id = ?",
        (card_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Card not found")
    return deserialize_row(row)


@app.post("/cards/{card_id}/review", tags=["cards"])
def review_card(
    card_id: int,
    body: ReviewRequest,
    db: sqlite3.Connection = Depends(get_db),
):
    """Submit a rating for a card. Runs SM-2 and logs the review."""
    if body.rating not in ("again", "hard", "good", "easy"):
        raise HTTPException(status_code=400, detail="rating must be: again | hard | good | easy")

    row = db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Card not found")

    card            = dict(row)
    interval_before = card["interval_days"]
    updated         = sm2_update(card, body.rating)

    db.execute(
        """
        UPDATE cards SET
            status = ?, ease_factor = ?, interval_days = ?,
            repetitions = ?, lapses = ?, due_date = ?, last_seen = ?
        WHERE id = ?
        """,
        (
            updated["status"], updated["ease_factor"], updated["interval_days"],
            updated["repetitions"], updated["lapses"],
            updated["due_date"], updated["last_seen"],
            card_id,
        ),
    )
    db.execute(
        "INSERT INTO reviews (card_id, rating, interval_before, interval_after) VALUES (?, ?, ?, ?)",
        (card_id, body.rating, interval_before, updated["interval_days"]),
    )
    db.commit()
    return updated

# ---------------------------------------------------------------------------
# Quiz
# ---------------------------------------------------------------------------

@app.get("/quiz/domains", tags=["quiz"])
def quiz_domains(db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute(
        """
        SELECT domain,
               COUNT(*)                                         AS question_count,
               SUM(times_seen)                                  AS total_attempts,
               ROUND(AVG(CASE WHEN times_seen > 0
                         THEN CAST(times_correct AS REAL) / times_seen
                         ELSE NULL END) * 100, 1)               AS avg_accuracy_pct
        FROM quiz_items
        GROUP BY domain
        ORDER BY domain
        """
    ).fetchall()
    return [dict(r) for r in rows]


@app.get("/quiz/{domain}", tags=["quiz"])
def get_quiz(
    domain: str,
    limit: int = Query(10, ge=1, le=50),
    db: sqlite3.Connection = Depends(get_db),
):
    """Return `limit` randomly selected questions for a domain."""
    rows = db.execute(
        "SELECT * FROM quiz_items WHERE domain = ? ORDER BY RANDOM() LIMIT ?",
        (domain, limit),
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail=f"No quiz items found for domain '{domain}'")
    return {"domain": domain, "questions": [deserialize_row(r) for r in rows]}


@app.post("/quiz/{item_id}/attempt", tags=["quiz"])
def record_attempt(
    item_id: int,
    body: AttemptRequest,
    db: sqlite3.Connection = Depends(get_db),
):
    """Record a quiz attempt and update the item's accuracy counters."""
    row = db.execute("SELECT id FROM quiz_items WHERE id = ?", (item_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Quiz item not found")

    db.execute(
        "INSERT INTO quiz_attempts (quiz_item_id, user_answer, was_correct) VALUES (?, ?, ?)",
        (item_id, body.user_answer, int(body.was_correct)),
    )
    db.execute(
        """
        UPDATE quiz_items SET
            times_seen    = times_seen + 1,
            times_correct = times_correct + ?
        WHERE id = ?
        """,
        (int(body.was_correct), item_id),
    )
    db.commit()
    return {"recorded": True, "item_id": item_id, "was_correct": body.was_correct}

# ---------------------------------------------------------------------------
# Admin — sync
# ---------------------------------------------------------------------------

class SyncPayload(BaseModel):
    flashcards: dict  # domain → list of note entries (from _flashcards/*.json)
    quizzes: dict     # domain → quiz object (from _quizzes/*.json)


@app.post("/admin/sync", tags=["admin"])
def sync_data(payload: SyncPayload, db: sqlite3.Connection = Depends(get_db)):
    """
    Additive-only upsert of notes, cards, and quiz items.

    - New notes  → inserted with all their cards (status='new', no due_date)
    - Existing notes → skipped entirely so SM-2 review state is never lost
    - Quiz items → inserted only if (domain, question) pair is not already present
    """
    notes_inserted    = 0
    notes_skipped     = 0
    cards_inserted    = 0
    quiz_items_inserted = 0
    quiz_items_skipped  = 0

    # ── Flashcards ──────────────────────────────────────────────────────
    for _domain, entries in payload.flashcards.items():
        for entry in entries:
            note_id = entry.get("note_id", "")
            if not note_id:
                continue

            existing_note = db.execute(
                "SELECT id FROM notes WHERE id = ?", (note_id,)
            ).fetchone()

            if existing_note:
                notes_skipped += 1
                continue

            # Insert note
            tags = entry.get("tags", [])
            db.execute(
                "INSERT INTO notes (id, title, domain, tags, source_path, updated) VALUES (?, ?, ?, ?, ?, ?)",
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

            # Insert all cards for this new note
            for card in entry.get("cards", []):
                ctype = card.get("type", "basic")
                db.execute(
                    """
                    INSERT INTO cards
                        (note_id, card_type, question, answer, cloze_text, hint, options, explanation)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        note_id, ctype,
                        card.get("question"),
                        card.get("answer"),
                        card.get("text"),
                        card.get("hint"),
                        json.dumps(card["options"]) if "options" in card else None,
                        card.get("explanation"),
                    ),
                )
                cards_inserted += 1

    # ── Quiz items ───────────────────────────────────────────────────────
    for domain, quiz in payload.quizzes.items():
        for q in quiz.get("questions", []):
            question_text = q.get("question") or q.get("prompt", "")
            if not question_text:
                continue

            existing = db.execute(
                "SELECT id FROM quiz_items WHERE domain = ? AND question = ?",
                (domain, question_text),
            ).fetchone()

            if existing:
                quiz_items_skipped += 1
                continue

            db.execute(
                """
                INSERT INTO quiz_items (domain, topic, item_type, question, answer, options, explanation)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    domain,
                    q.get("topic", ""),
                    q.get("type", "mcq"),
                    question_text,
                    q.get("answer", ""),
                    json.dumps(q["options"]) if "options" in q else None,
                    q.get("explanation"),
                ),
            )
            quiz_items_inserted += 1

    db.commit()
    return {
        "notes_inserted":     notes_inserted,
        "notes_skipped":      notes_skipped,
        "cards_inserted":     cards_inserted,
        "quiz_items_inserted": quiz_items_inserted,
        "quiz_items_skipped":  quiz_items_skipped,
    }
