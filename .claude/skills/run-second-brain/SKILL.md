---
name: run-second-brain
description: Refine new or updated Obsidian notes from the vault, then generate flashcards and quizzes from the refined output, and sync new content to the Railway database. Use when asked to "refine my notes", "process new notes", "run the second brain", "sync my vault", "refine notes", "generate flashcards", "create quizzes", or "sync to railway".
---

Run all four steps as a single pipeline from `/Users/ajikumar/codefiles/SecondBrain`.
After each step completes, immediately post a progress line before starting the next one.
Do not wait until the end to report — update the user as you go.

---

## Step 1 — Refine notes

```bash
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/refine_vault.py
```

Parse output and post this progress line:
```
📚 Step 1/4 — Vault scanned: {total} notes found, {to_process} new/updated → {processed} refined, {skipped} skipped
```
- `total`       = number after "Vault:" on the first line  
- `to_process`  = number after "| X to process |"  
- `processed`   = number after "Done. X note(s) processed"  
- `skipped`     = number after ", Y skipped"
- If `to_process` is 0, say: `📚 Step 1/4 — Vault scanned: {total} notes, nothing new to refine`

---

## Step 2 — Generate flashcards

```bash
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/generate_flashcards.py
```

Parse output and post this progress line:
```
📇 Step 2/4 — Flashcards: {flashcarded} notes → {cards} new cards ({skipped} notes already done)
```
- `flashcarded` = number after "Done. X note(s) flashcarded"  
- `cards`       = number after "Total cards generated this run:"  
- `skipped`     = number after ", X skipped,"
- If nothing to flashcard, say: `📇 Step 2/4 — Flashcards: nothing new to generate`

---

## Step 3 — Generate quizzes

```bash
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/generate_quizzes.py
```

Parse output and post this progress line:
```
🧠 Step 3/4 — Quizzes: {domains} domains → {questions} new questions ({skipped} already done)
```
- `domains`     = number after "Done. X domain(s) quizzed"  
- `questions`   = number after "Total questions generated this run:"  
- `skipped`     = number after ", X skipped,"
- If nothing to quiz, say: `🧠 Step 3/4 — Quizzes: nothing new to generate`

---

## Step 4 — Sync to Railway DB

```bash
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/sync_to_railway.py
```

Parse output and post this progress line:
```
🚀 Step 4/4 — Railway sync: {notes_in} notes + {cards_in} cards + {quiz_in} quiz items pushed ({notes_skip} notes already in DB, review state preserved)
```
- `notes_in`   = number after "Notes inserted:"  
- `cards_in`   = number after "Cards inserted:"  
- `quiz_in`    = number after "Quiz items inserted:"
- `notes_skip` = number after "Notes skipped:"

---

## Final summary

After all four steps, print this block:

```
─────────────────────────────────────
  Second Brain — run complete
─────────────────────────────────────
  Notes refined       {step1_processed} new  ({step1_skipped} unchanged)
  Flashcards added    {step2_cards} new cards across {step2_notes} notes
  Quiz questions      {step3_questions} new questions across {step3_domains} domains
  Railway DB          {step4_notes} notes · {step4_cards} cards · {step4_quiz} quiz items added
─────────────────────────────────────
```

If every step had nothing to process (all zeros), instead say:
> Everything is up to date — no new notes, flashcards, quizzes, or DB changes.

---

## Partial runs

Run only refinement:
```bash
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/refine_vault.py
```

Run only flashcard generation:
```bash
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/generate_flashcards.py
```

Run only quiz generation:
```bash
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/generate_quizzes.py
```

Run only Railway sync:
```bash
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/sync_to_railway.py
```

Preview sync without sending:
```bash
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/sync_to_railway.py --dry-run
```

Force reprocess everything (Steps 1–3):
```bash
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/refine_vault.py --force
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/generate_flashcards.py --force
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/generate_quizzes.py --force
```
