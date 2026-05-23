---
name: run-second-brain
description: Refine new or updated Obsidian notes from the vault, then generate flashcards and quizzes from the refined output. Use when asked to "refine my notes", "process new notes", "run the second brain", "sync my vault", "refine notes", "generate flashcards", or "create quizzes".
---

Run these three commands in sequence from the repo root:

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

All scripts handle everything automatically:
- Read new/updated notes from `notes_location` / `refined_location` in `.env`
- Skip notes/domains already processed and unchanged
- Write output to their respective destinations
- Track progress via `_flashcard_manifest.json` and `_quiz_manifest.json`

After all three finish, report:
- Step 1: how many notes refined vs skipped, stubs added to `_stubs_to_create.json`, errors
- Step 2: how many notes flashcarded vs skipped, total cards generated, domain breakdown, errors
- Step 3: how many domains quizzed vs skipped, total questions generated, domain breakdown, errors

---

**Partial runs:**

Run only refinement (no flashcards or quizzes):
```bash
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/refine_vault.py
```

Run only flashcard generation (on already-refined notes):
```bash
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/generate_flashcards.py
```

Run only quiz generation (on already-generated flashcards):
```bash
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/generate_quizzes.py
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

Preview without API calls (dry-run all):
```bash
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/refine_vault.py --dry-run
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/generate_flashcards.py --dry-run
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/generate_quizzes.py --dry-run
```

Force reprocess everything:
```bash
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/refine_vault.py --force
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/generate_flashcards.py --force
python3 /Users/ajikumar/codefiles/SecondBrain/scripts/generate_quizzes.py --force
```
