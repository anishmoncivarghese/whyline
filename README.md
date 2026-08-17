# whyline

Records why your code exists, and tells the next agent.

```
$ whyline explain src/tsconfig/resolve.ts:41

Decision          Treat only canonical in-repo workspace package exports as internal
Because           node_modules must be readable for resolution but never indexed
Rejected          classify any resolvable node_modules target as internal
                  indexes third-party declarations and violates FR-005
Confidence        High — a recorded decision matches the commit for this line.
```

Free, Apache-2.0, local-only. No accounts, no telemetry, no paid tier, ever.

## Why

Git made code history durable. AI-assisted development broke that: the code is
versioned, but the reasoning that produced it — the instruction, the alternatives,
the rejection — evaporates when the terminal closes. whyline makes that layer
durable too, and hands it to whichever agent works next.

## Install

Not yet published. From a clone:

```bash
uv tool install --from . whyline
```

Zero production dependencies — standard library only. Python 3.11+, plus `git`.

## Quickstart

```bash
whyline init                     # scaffold, add instructions, install the hook
whyline note "chose X" --because "Y" --rejected "Z: too slow" --file src/a.py
whyline explain src/a.py:14      # why does this line exist?
whyline brief                    # hand context to the next agent
whyline run codex "finish the refactor"
whyline timeline --file src/a.py
whyline status
```

## How it works

Three layers feed one ledger:

1. **git** resolves a line to a commit via `git blame`. Works before whyline has
   recorded anything.
2. **A hook** silently records sessions, instructions and file edits. It can never
   fail your session — every path exits 0.
3. **Your agent** records the reasoning. `whyline init` adds an `AGENTS.md`
   instruction asking agents to log decisions and rejected alternatives. This is
   the only layer that captures *why*.

`.whyline/decisions.md` is committed and readable with whyline uninstalled.
`.whyline/ledger.jsonl` is gitignored, because it holds your prompt text.

## Does the third layer actually work?

It was the design's one unproven assumption, so it was measured before the
features depending on it were built. Over three days across two agents on a real
project, 19 decisions were recorded across 14 commits — Claude Code 150% of its
non-trivial changes, Codex 130%, against a 60% threshold. Every one carried a
rationale and a concrete rejected alternative. Codex was never reminded.

Full method and caveats: [`m0/RESULTS.md`](m0/RESULTS.md).

## Honest limitations

- **Switching agents is a relay, not a shared conversation.** Vendor CLIs are
  separate processes with separate context windows. `brief` hands the next agent a
  written summary; it cannot continue the previous conversation. Nothing can.
- **`explain` reports confidence and will say when it does not know.** An empty
  ledger produces an honest empty answer, not a guess. File-level `explain` never
  claims high confidence, because without a line there is no blamed commit.
- **The hook is Claude Code only** in v1. Codex and Gemini both support hooks, so
  this is a limit of scope, not of design.
- **Gemini is not supported by `run`** — its free personal tier was withdrawn.
- **Parallel agents are not coordinated.** No worktree isolation in v1.
- **`brief` degrades on a fresh clone.** The ledger is gitignored, so a clone has
  only the committed `decisions.md`, which carries day precision rather than full
  timestamps. `brief` merges both sources and tells you which is which.
- **Only macOS is actually verified.** The CI workflow covers macOS and Linux on
  Python 3.11 and 3.13, but the repository has no remote yet, so **CI has never
  run**. Linux and Windows/WSL are untested claims, not observations.

## Credentials

whyline never reads, stores, forwards or proxies a vendor token. `run` replaces
itself with the vendor's own CLI via `exec`, which does its own authentication.
Your subscription works because the official CLI is what talks to the vendor.
Permission-bypass flags are never added.

## Performance

Cold start is ~18 ms for `status`, `explain`, `timeline` and `brief` against a
200 ms budget. `explain` on a 50,000-event ledger takes ~159 ms against a 1 s
budget — which is why there is no SQLite index.

## Licence

Apache-2.0.
