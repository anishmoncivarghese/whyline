<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-11-15-release-hardening-design.md | created: 2026-11-15T14:00:00+05:30 -->
# Release notes review: a fixed check, a second agent, and a readable fallback

Runs after `plans/console-restart.plan.md`, and before `plans/relay-live-models.plan.md`. Spec: `docs/superpowers/specs/2026-11-15-release-hardening-design.md`, Part 1. Read it before every task. Where this plan and the spec differ, this plan wins. In particular:
- **The Telegram go-ahead's notes summary** is added by `plans/waiting-on-you.plan.md` (WAIT-5), which runs later. This plan only makes the summary line available as `notes.Checked.summary`.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Why: the release notes for 0.3.70, 0.3.71 and 0.3.72 each carried the writing agent's own chatter ("here are the release notes I created, please review") and were cleaned by hand. The `<notes>` markers cut text outside them, but nothing checks the text inside. When an answer is unusable the fallback is the raw commit list, which is how v0.3.73's notes came to list `chore: tick RCR-6 in the plan`.

What the user gets:
- Notes are checked by fixed rules, reviewed by a second agent that can only remove and reword, and checked again.
- The confirm window says who wrote them, who checked them and how many lines were removed, with a before and after.
- When notes can't be used, a grouped, readable commit list instead of the raw one.

Rules every task keeps:
- **Console first.** Every setting and action has a console counterpart saving through the same function as its CLI command.
- **A release never blocks on notes.** Any failure in the check or the review ends in the fallback, never in a stopped release.
- **The reviewer never adds.** Code enforces it by comparing the reviewer's output with the draft and the commit subjects. The reviewer's word is not trusted.
- **Both agent turns are read-only**, through `release.plan.default_ask_agent`'s path, in an empty temporary folder. Commit subjects and the draft are data inside labelled blocks.
- **No secret's value in a log, a dialog or a problem list.** A flagged secret is shown as its rule name and line number.
- **No new dependency.**
- **Tests:** never invoke a real provider, `gh` or a remote. Use fakes. Keep Python 3.11 compatibility.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- The chatter lines that reached 0.3.70 to 0.3.72 are flagged. NOTE-1, `test_known_chatter_is_flagged`.
- An ordinary notes line that happens to contain "review" or "I/O" is not flagged. NOTE-1, `test_ordinary_lines_pass`.
- A line the reviewer invented is removed. NOTE-3, `test_reviewer_cannot_add`.
- Every failure path ends in notes, never in an exception that stops the release. NOTE-4, `test_notes_never_block_a_release`.
- A release with only process commits gets `Maintenance release.`, not an empty file. NOTE-2, `test_only_process_commits`.

- [ ] NOTE-1: The fixed check
  Edit `src/whyline/release/notes.py` and `tests/release/test_notes.py` only.
  1. `@dataclass(frozen=True) class Problem`: `line: int`, `text: str` (cut to 120 characters, a secret replaced by its rule name), `reason: str`, `removable: bool`.
  2. `lint(text: str, *, version: str, allowed_emails: frozenset[str] = frozenset()) -> list[Problem]`. A line is flagged, with these reasons:
     - `talks to the reader`: it matches, case-insensitively, at the start of the line or after a list marker: `here are`, `here is`, `here's`, `below are`, `below is`, `i have`, `i've`, `i created`, `i wrote`, `as requested`, `let me know`, `please review`, `please let`, `hope this helps`, `feel free`, `happy to`, or it ends with a question mark
     - `first person`: the words `I`, `I'm`, `I'll`, `my` or `me` as whole words, outside inline code (`` `…` ``)
     - `process noise`: after an optional list marker it starts with `chore: tick`, `chore: release`, `chore: record`, `chore: move finished plans`, `setup:`, `merge:` or `plan:`
     - `repeats the title`: a second `# v<version>` heading
     - `code fence around everything`: the first and last non-empty lines are fences (both are flagged, removable)
     - `secret`: a `security.secrets.scan_text` match (not removable by itself: the whole line is removed)
     - `home path`: `/Users/<name>`, `/home/<name>` or `C:\Users\<name>`
     - `email address`: one not in `allowed_emails`
     Every flagged line can be removed. A heading left with no bullets under it after removal is removed too.
  3. `clean(text, problems) -> str` removes the flagged lines and empty headings, and collapses runs of blank lines.
  4. `usable(text) -> bool`: at least one bullet or sentence remains besides headings.
  Tests: `test_known_chatter_is_flagged` (six real lines from the 0.3.70 to 0.3.72 drafts, written into the test), `test_ordinary_lines_pass` (`Review rounds now show…`, `Fixed I/O errors…`, `my-package` in code, `Improved the "I have a plan already" form`), each reason, a secret shown as its rule name, the empty-heading removal, and `usable`.

- [ ] NOTE-2: A readable fallback
  Edit `src/whyline/release/notes.py` and its tests only.
  1. `fallback(version, commits)` becomes grouped:
     - `## New` for subjects starting `feat:` or `feat(`
     - `## Fixed` for `fix:`
     - `## Docs` for `docs:`
     - `## Other` for the rest
     - process-noise subjects (NOTE-1's list) are dropped
     - each bullet is the subject without its prefix, without a trailing task id in brackets such as `(RCR-6)`, and with its first letter capitalised
     - an empty group is left out
  2. With nothing left, the body is `Maintenance release.`
  3. The result always passes `lint`.
  Tests: `test_only_process_commits`, each group, the prefix and task id stripped, a `feat(scope):` subject, and the fallback passing `lint` for a list holding every kind of subject.

- [ ] NOTE-3: The second-agent review
  Edit `src/whyline/release/notes.py`, `src/whyline/release/plan.py`, `src/whyline/relaychat/agent_choice.py` and their tests only.
  1. `agent_choice.pick_other(root, not_agent) -> str | None`: an enabled agent with a verified read-only mode other than `not_agent`, else None.
  2. `plan.default_ask_agent(root, *, agent: str | None = None)` takes the agent to use. With None it behaves as today. The function it returns exposes the agent's name as `.agent`.
  3. `notes.build_review_prompt(version, commits, draft, problems) -> str`: the commit subjects and the draft in labelled data blocks, the problems as `line <n>: <reason>`, and the instruction: remove lines that talk to the reader, are in the first person or are process noise; tighten wording; keep every real change; add nothing; return the notes between the same markers.
  4. `notes.review(version, commits, draft, problems, *, ask_agent) -> Reviewed` (`text`, `added: tuple[str, ...]`). After `extract`, each bullet of the result is kept only when it shares at least two words of four or more letters with some draft line or commit subject. A bullet that doesn't is removed and listed in `added`. A failed turn or an answer without markers returns the draft unchanged.
  Tests: `test_reviewer_cannot_add`, a reworded bullet kept, a removed line staying removed, an unmarked answer returning the draft, `pick_other` with one and with two agents, and `default_ask_agent` using the named agent.

- [ ] NOTE-4: Draft, check, review, check again
  Edit `src/whyline/release/notes.py`, `src/whyline/release/config.py`, `src/whyline/release/plan.py` and their tests only.
  1. `ReleaseConfig` gains `notes_review: bool = True` and `notes_reviewer: str = ""` (empty means any agent other than the writer), read and written like the other fields.
  2. `@dataclass(frozen=True) class Checked`: `text`, `writer`, `reviewer`, `removed: tuple[str, ...]`, `before: str`, `used_fallback: bool`, `summary: str`.
  3. `notes.checked(root, cfg, version, *, ask_agent, ask_reviewer=None, run, say=None) -> Checked`:
     - draft as today
     - `lint` and `clean` the draft
     - with `notes_review` on and a reviewer available, `review`, then `lint` and `clean` again
     - when the result is not `usable`, use `fallback`
     - `removed` is the lines taken out at any step. `before` is the first draft.
     - `summary` is one of: `Written by <writer>, checked by <reviewer>. <n> lines removed.`, `Written and checked by <writer> (only one agent is enabled). <n> lines removed.`, `Written by <writer>, checked by fixed rules only.`, or `The agent's notes couldn't be used; this is the commit list.`
     - any exception at any step is caught, and the result is the fallback with the last summary
  4. The release's notes step (`release/plan.py`) uses `checked`, writes `text`, and passes the `Checked` to the confirm function. `say` gets the summary, so it is in the release log in every mode.
  Tests: `test_notes_never_block_a_release` (the writer raising, the reviewer raising, lint raising through a patched rule), each summary, review off, one agent, the fallback when nothing usable is left, and round trip of the two settings.

- [ ] NOTE-5: The confirm window, settings and CLI
  Edit `src/whyline/console/release_screens.py`, `src/whyline/release/cli.py` and their tests only.
  1. The notes confirm window shows the summary line above the notes, and adds:
     - **See what was removed**: the first draft and the final text side by side, with the removed lines marked
     - **Use the commit list instead**: replaces the text with `notes.fallback`
     - **Edit** and **Approve**, as today. Edited text is linted on Approve, and problems are listed with **Approve anyway** and **Remove these lines**.
  2. All text in the window is shown with `markup=False`.
  3. Release → Set up: **Check release notes with a second agent** (checkbox) and **Reviewer** (a select of enabled agents plus `Any other agent`). CLI: `whyline release settings notes-review on|off` and `whyline release settings notes-reviewer <agent|any>`.
  4. CLI: `whyline release notes --check <file>` prints `lint`'s problems as `line <n>: <reason>` and exits 1 when there are any. The terminal confirm (`_confirmers`) prints the summary line and offers `[a]pprove, [e]dit, [c]ommit list, [s]top`.
  Tests: the summary shown, the before and after, the commit list button, an edited text with a problem offering both choices, text with square brackets shown as plain text, settings saved through one function, and `--check` exit codes.

- [ ] NOTE-6: Docs
  Edit `docs/release.md` and `README.md` only.
  Cover: the three steps, what the fixed check flags, that the reviewer can only remove and reword, the summary line and its four forms, the fallback groups, the two settings, and `whyline release notes --check`.
  Verify with `uv run pytest -q`.
