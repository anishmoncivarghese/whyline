# Decisions

Append-only. Written by whyline; readable without it.

## 2026-08-14 — Add CodeGraph as the clean-project M0 subject

**Because:** It tests fresh-repository bootstrap and instruction pickup that the three mature repositories cannot exercise

**Rejected:**

- Use only mature repositories — that would leave new-project behavior unmeasured

**Files:** m0/RESULTS.md

<!-- whyline-event: 936f971e4dc940fe9b1045c9e79e3f1a -->

## 2026-08-17 — brief.compose falls back to decisions.md when the ledger has no notes

**Because:** ledger.jsonl is gitignored so a fresh clone has an empty ledger but a committed decisions.md; reading only the ledger would silently break cross-machine handoff

**Rejected:**

- read only the ledger — works only on the machine that recorded the notes
- merge both sources — risks duplicate or conflicting entries with no stable id-based dedup guarantee across formats

**Files:** src/whyline/brief.py, src/whyline/decisions.py

<!-- whyline-event: 1a79534184014dfc9180ea54aaa45ec5 -->

## 2026-08-17 — Merge brief's two sources instead of choosing between them

**Because:** the ledger is gitignored and decisions.md is what travels, so a clone plus one local note hid the entire committed history and reported '1 of 1' when there were twenty

**Rejected:**

- read decisions.md only when the ledger is empty — works solely in the pristine clone state, which nobody is in after their first commit
- commit the ledger so brief always has it — puts raw prompt text in git, which the privacy decision forbids

**Files:** src/whyline/brief.py

<!-- whyline-event: 2aecb907b1f14630b697b9af35ed52eb -->

## 2026-08-17 — Resolve runner injection points at call time, not in the signature

**Because:** default arguments bind at import time, so monkeypatching runner.shutil.which had no effect and a test exec'd the real codex binary, replacing the pytest process

**Rejected:**

- patch the default argument tuple in tests — couples every test to CPython internals

**Files:** src/whyline/runner.py

<!-- whyline-event: 7db46b08486945ab8b229e9ac77c1088 -->
