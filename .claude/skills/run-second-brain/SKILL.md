---
name: run-second-brain
description: Refine new or updated Obsidian notes from the vault, then generate flashcards and quizzes from the refined output, and sync new content to the Railway database. Use when asked to "refine my notes", "process new notes", "run the second brain", "sync my vault", "refine notes", "generate flashcards", "create quizzes", or "sync to railway".
---

Run these four commands in sequence from the repo root:

**Step 1 — Refine notes**
```bash
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/refine_vault.py
```

**Step 2 — Generate flashcards**
```bash
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/generate_flashcards.py
```

**Step 3 — Generate quizzes**
```bash
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/generate_quizzes.py
```

**Step 4 — Sync to Railway DB**
```bash
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/sync_to_railway.py
```

All scripts handle everything automatically:
- Read new/updated notes from `notes_location` / `refined_location` in `.env`
- Skip notes already processed and unchanged
- Write output to their respective destinations
- Track progress via `_flashcard_manifest.json` and `_quiz_manifest.json`
- Step 4 is additive-only: existing notes/cards are never overwritten, so SM-2 review state (due dates, intervals, ease factors) is always preserved

After all four finish, report:
- Step 1: how many notes refined vs skipped, stubs added to `_stubs_to_create.json`, errors
- Step 2: how many notes flashcarded vs skipped, total cards generated, domain breakdown, errors
- Step 3: how many domains quizzed vs skipped, total questions generated, domain breakdown, errors
- Step 4: notes inserted, cards inserted, quiz items inserted, notes skipped (already in DB), quiz items skipped (already in DB), errors

---

**Partial runs:**

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

Run only Railway sync (after flashcards/quizzes already generated):
```bash
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/sync_to_railway.py
```

Preview sync without sending:
```bash
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/sync_to_railway.py --dry-run
```

Specific folder only (Steps 1 & 2):
```bash
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/refine_vault.py "<folder_path>" --vault /Users/ajikumar/Documents/Main_Notes
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/generate_flashcards.py "<refined_folder_path>"
```

Specific domain only (Step 3):
```bash
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/generate_quizzes.py _flashcards/deep-learning.json
```

Preview without API calls (dry-run Steps 1–3):
```bash
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/refine_vault.py --dry-run
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/generate_flashcards.py --dry-run
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/generate_quizzes.py --dry-run
```

Force reprocess everything (Steps 1–3):
```bash
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/refine_vault.py --force
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/generate_flashcards.py --force
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/generate_quizzes.py --force
```
