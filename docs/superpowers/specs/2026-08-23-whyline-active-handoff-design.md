# Whyline active handoff — design

**Date:** 2026-08-23  
**Status:** Approved for implementation by the owner  
**Target:** whyline 0.2.0  
**Extends:** `2026-08-09-whyline-v1-design.md`

## 1. Goal

Make a two-terminal Codex/Claude relay cheap and explicit without turning
Whyline into an orchestrator.

Version 1 preserves durable decisions. It does not preserve the active task,
current Git state, test evidence, the next owner, or overlapping write
ownership. It also relies on agents reading `whyline brief` on their own, which
the completed read-side experiment now measures as unreliable.

Version 2 adds a compact active-task handoff layered on top of the durable
decision history. Git remains authoritative and every coordination mechanism is
advisory.

## 2. Decisions

### 2.1 Global executable, checkout-local state

The executable remains installed once per machine. `whyline init` initializes
the nearest Git root. Each checkout has independent mechanical history, active
handoff, and ownership state.

### 2.2 Durable versus ephemeral state

Committed:

- `.whyline/decisions.md` — durable decisions and rejected alternatives.

Gitignored:

- `.whyline/ledger.jsonl` — prompts and mechanical events.
- `.whyline/active-handoff.json` — the latest operational handoff.
- `.whyline/ownership.json` — current advisory claims.

Handoffs and ownership are deliberately not committed. An active owner or dirty
working tree from one checkout must not become authoritative in another clone.
The durable reasoning inside a handoff is recorded separately with `note`.

### 2.3 No orchestration and no hard locks

Whyline never launches two agents, schedules work, blocks a write, or resolves a
conflict. Ownership claims produce warnings and machine-readable conflict data.
Git and the human remain authoritative.

### 2.4 One shared history loader

`brief`, `explain`, and `status` must use one merge-and-deduplication path for
local ledger notes plus committed `decisions.md` entries.

Committed entries carry day precision. They may support a file-level
explanation or a medium-confidence same-day line match, but never a
high-confidence timestamp-window claim.

## 3. Event and record schemas

### 3.1 Decision fields

`Note` adds optional, backward-compatible fields:

```json
{
  "actor": "codex",
  "role": "implementer",
  "task": "CG-42"
}
```

`decisions.md` renders these as optional `Actor`, `Role`, and `Task` fields.
Older entries parse with empty values.

Actors and roles are free single-line strings. Whyline does not maintain an
allowlist of vendor or workflow names.

### 3.2 Handoff record

`whyline handoff TASK` writes a `Handoff` event to the ledger and atomically
replaces `.whyline/active-handoff.json`:

```json
{
  "v": 1,
  "id": "uuid",
  "ts": "ISO-8601",
  "type": "Handoff",
  "task": "CG-42",
  "from_actor": "codex",
  "to_actor": "claude",
  "status": "ready-for-review",
  "summary": "Implemented bounded cache invalidation",
  "files": ["src/cache.py"],
  "tests": [{"command": "pytest -q", "result": "passed"}],
  "risks": ["large repositories not benchmarked"],
  "questions": ["should the default limit remain 25?"],
  "base_commit": "full SHA or empty",
  "current_commit": "full SHA or empty"
}
```

Fields supplied by the caller win. Missing files and commit values are derived
from Git. A handoff may be recorded from a dirty tree; that is the primary use
case.

Status is a free single-line string rather than an enum so Whyline does not
become a workflow engine.

### 3.3 Ownership record

`.whyline/ownership.json` is an atomically replaced object:

```json
{
  "v": 1,
  "claims": [
    {
      "task": "CG-42",
      "actor": "codex",
      "role": "implementer",
      "files": ["src/cache.py"],
      "claimed_at": "ISO-8601"
    }
  ]
}
```

Claims conflict when different actors claim the same task or intersecting file
sets. Empty file sets conflict only on identical task ids. Conflicts warn but
return success because ownership is advisory.

## 4. Commands

### 4.1 `note`

Adds optional flags:

```text
--actor ACTOR
--role ROLE
--task TASK
```

### 4.2 `handoff`

```text
whyline handoff TASK --from ACTOR --to ACTOR --status STATUS
  [--summary TEXT]
  [--file PATH]...
  [--test "COMMAND: RESULT"]...
  [--risk TEXT]...
  [--question TEXT]...
  [--base SHA]
  [--current SHA]
  [--json]
```

If no `--file` is passed, tracked and untracked changed paths are read from Git.
If no commit flags are passed, both values default to current `HEAD`. Output
states when the tree is dirty so equal base/current commits are not mistaken for
no work.

### 4.3 `sync`

```text
whyline sync [--task TASK] [--file PATH]...
  [--token-budget N] [--json]
```

Produces one compact, fenced context packet containing, in order:

1. active handoff;
2. branch, current commit, and dirty paths;
3. ownership claims and conflicts;
4. relevant durable decisions.

The default budget is 1,200 approximate tokens. Whyline uses a conservative
standard-library estimate of `ceil(UTF-8 bytes / 3)`. The header and warnings
are mandatory; optional decisions are packed newest/relevant first until the
budget is reached. Output discloses the estimate and any omitted count.

### 4.4 `brief`

Adds:

```text
--task TASK
--file PATH   # repeatable
--token-budget N
```

The default budget is 1,200 approximate tokens. `--limit` remains a maximum
entry count and must be positive.

Selection order:

1. exact task match;
2. changed/selected file overlap;
3. newest remaining decisions when no relevance filter was supplied.

When a filter is supplied, unrelated entries are not used merely to fill the
budget. Legacy taskless notes can match by file.

### 4.5 `claim` and `release`

```text
whyline claim TASK --actor ACTOR [--role ROLE] [--file PATH]... [--json]
whyline release TASK --actor ACTOR [--json]
```

Repeated claims by the same actor/task replace that claim. `release` is
idempotent. Both commands report conflicts.

### 4.6 `run`

`run` injects `sync` output rather than a decisions-only brief. It adds
`--task-id`, repeatable `--file`, and `--token-budget` flags while retaining the
existing positional agent and prompt.

## 5. Codex mechanical capture

`init` installs project-local `.codex/hooks.json` alongside Claude's
`.claude/settings.json`. It merges with existing hook groups and refuses to
rewrite malformed structures.

The command is `whyline-hook --agent codex` for:

- `SessionStart`
- `SessionEnd`
- `UserPromptSubmit`
- `PostToolUse`

The hook records the documented common fields without reading the unstable
transcript format. `PostToolUse` records explicit write paths and paths parsed
from `apply_patch` headers. It does not guess file mutations from arbitrary shell
commands.

Codex project hooks require user trust. `status` must never report them as live
until a Codex event has actually been observed; it tells the user to inspect
`/hooks` when configured but unseen.

## 6. Hook health

`status` reports Claude and Codex separately:

- configuration completeness;
- hook executable discoverability and executability;
- last observed mechanical event and its age;
- configured-but-unobserved state;
- current handoff;
- ownership conflicts;
- merged durable decision count and local event count.

An old last event is reported factually, not called broken: an idle repository
is valid. Missing binary, malformed configuration, partial event wiring, and
configured-but-never-observed are distinct states.

Legacy JSON fields remain for compatibility for one release.

## 7. Read-side experiment closure

The collection ends at 7 Claude sessions with 3 qualifying reads: 43%, below
the precommitted 50% threshold. The verdict is **unreliable**.

Consequences:

- restore the real global `whyline` executable;
- stop presenting unprompted `brief` reading as a reliable default;
- lead documentation with `whyline run` or an explicit `whyline sync` command;
- retain `AGENTS.md` instructions as a useful best-effort fallback;
- preserve the Codex count as observational because it has no session
  denominator.

## 8. Security and failure behavior

- All model-visible repository-derived text uses a nonce-bearing untrusted-data
  fence and fence-token sanitization.
- Active JSON writes use a temporary sibling plus `os.replace`.
- Hook paths remain inside the Git root after resolution.
- Raw prompts remain local and are never included in `brief` or `sync`.
- Hook entrypoints swallow all exceptions and exit zero.
- Invalid handoff, ownership, hook, and trace data degrade with warnings; they do
  not become trusted context silently.

## 9. Compatibility

- Existing v1 ledgers and `decisions.md` files remain readable without migration.
- Existing `note`, `brief`, and `run` invocations continue to work.
- Re-running `init` upgrades marked instruction blocks, adds ignored active-state
  files, and merges Codex hooks.
- `decisions.md` remains readable without Whyline.

## 10. Definition of done

1. Fresh-clone `explain`, `status`, and `brief` see committed decisions.
2. The read-side shim is removed and 43% is published consistently.
3. Handoff round-trips every required field and derives Git defaults honestly.
4. `sync` includes active/Git/ownership/decision context within its disclosed
   approximate token budget.
5. Actor, role, and task survive ledger and Markdown round trips.
6. Overlapping ownership produces a visible warning without blocking.
7. Claude and Codex hook configs merge safely and both payload shapes record.
8. `status` distinguishes configured, executable, observed, partial, and broken.
9. The full suite, package build, standalone wheel install, and performance
   budgets pass on the local machine; CI retains macOS/Linux 3.11/3.13 coverage.
