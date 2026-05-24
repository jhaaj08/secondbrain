"""SM-2 spaced repetition algorithm."""
from __future__ import annotations

from datetime import date, timedelta

# Maps our user-facing rating labels to SM-2 quality scores (1–5)
QUALITY = {
    "again": 1,  # complete blackout
    "hard":  2,  # correct but very difficult
    "good":  4,  # correct with some effort
    "easy":  5,  # perfect recall
}


def sm2_update(card: dict, rating: str) -> dict:
    """
    Apply one SM-2 review to `card` and return the updated card dict.

    SM-2 rules:
    - quality < 3 (again/hard): reset repetitions, set interval=1, mark 'learning'
    - quality >= 3 (good/easy): advance interval using ease factor, mark 'reviewing'
    - ease_factor adjusts after every review; floor is 1.3
    - lapses increment on every "again"
    """
    quality = QUALITY[rating]
    interval = card["interval_days"]
    ease     = card["ease_factor"]
    reps     = card["repetitions"]
    lapses   = card["lapses"]

    if quality < 3:
        reps     = 0
        interval = 1
        status   = "learning"
        if rating == "again":
            lapses += 1
    else:
        if reps == 0:
            interval = 1
        elif reps == 1:
            interval = 6
        else:
            interval = round(interval * ease)
        reps  += 1
        status = "reviewing" if reps > 1 else "learning"

    ease = max(1.3, ease + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))

    card.update({
        "status":       status,
        "ease_factor":  round(ease, 4),
        "interval_days": interval,
        "repetitions":  reps,
        "lapses":       lapses,
        "due_date":     (date.today() + timedelta(days=interval)).isoformat(),
        "last_seen":    date.today().isoformat(),
    })
    return card
