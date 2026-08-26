# Whyline active handoff implementation plan

**Goal:** implement the 2026-08-23 active-handoff design as a backward-compatible
0.2.0 release candidate.

**Method:** TDD per task. Each behavioral task begins with a failing focused test,
then implementation, focused tests, and the full suite at phase boundaries.

## Task 1 — Shared committed history

Create `src/whyline/history.py` by extracting the merge, provenance, sorting,
deduplication, and conflict behavior currently private to `brief.py`.

- Add committed-only tests for line and file `explain`.
- Cap committed day-precision line matches at medium confidence.
- Make `status` count merged decisions while retaining local event/note counts.
- Keep `brief` output and hostile-fence tests unchanged.

## Task 2 — Close the read-side experiment

- Run `m0/end-readside-collection.sh` to restore the real global executable.
- Record the final 3/7, 43% result in `m0/RESULTS.md`, protocol, README, and
  handoff status.
- Remove every claim that automatic reading meets the threshold.
- Ignore the completed experiment's local `readside.log`.

## Task 3 — Actor-aware decisions

- Add `--actor`, `--role`, and `--task` to `note`.
- Render and parse optional Markdown fields.
- Include attribution in brief/JSON/text output without breaking old entries.
- Upgrade the canonical instruction examples to name actor, role, and task.

## Task 4 — Explicit handoffs

Create `src/whyline/handoffs.py`.

- Define validation and atomic active-record persistence.
- Add the `Handoff` event type.
- Add Git helpers for branch, `HEAD`, and changed paths.
- Implement `handoff` text and JSON output.
- Test dirty, clean, unborn-branch, malformed-active-file, and full-field cases.

## Task 5 — Advisory ownership

Create `src/whyline/ownership.py`.

- Implement atomic claim replacement and idempotent release.
- Detect same-task and overlapping-file conflicts across actors.
- Implement `claim` and `release` text/JSON output.
- Surface conflicts without returning an error.

## Task 6 — Relevant bounded briefs and sync

Create a small shared context-packing module and `src/whyline/sync.py`.

- Validate positive limits and budgets.
- Filter notes by exact task and file overlap.
- Pack with a conservative UTF-8 token estimate and disclose omissions.
- Compose active handoff, Git state, ownership, and decisions in one fenced
  packet.
- Make `run` inject sync output and expose task/file/budget options.
- Pin output size, hostile-input fencing, and legacy behavior in tests.

## Task 7 — Codex mechanical hooks

Create `src/whyline/codexhooks.py` using the documented project-local
`.codex/hooks.json` schema.

- Merge all four lifecycle events without overwriting existing hooks.
- Use `whyline-hook --agent codex` and require explicit trust review in output.
- Extend the hook entrypoint for explicit agent identity and Codex payloads.
- Parse only explicit edit paths and `apply_patch` file headers.
- Preserve the never-fail, never-print hook contract.

## Task 8 — Honest hook health

- Refactor status into per-agent hook reports.
- Check PATH and executable permission for `whyline-hook`.
- Report last observed mechanical event by agent.
- Distinguish configured/unobserved from live and from malformed/partial.
- Include active handoff and ownership conflict summaries.
- Retain legacy status JSON fields for compatibility.

## Task 9 — Documentation, version, and verification

- Update README setup, two-terminal workflow, storage, commands, limitations,
  privacy, read-side evidence, and Codex trust instructions.
- Update the original design/status documents where later evidence supersedes
  them; do not rewrite historical release notes.
- Set the development version to 0.2.0 and update `uv.lock` mechanically.
- Add `docs/releases/v0.2.0.md` without tagging or publishing.
- Run full tests, performance tests, `uv build`, archive-content inspection, and
  standalone wheel installation in a scratch environment.
- Run `git diff --check` and review the complete diff for over-claims.
- Record the final implementation decisions in Whyline.
