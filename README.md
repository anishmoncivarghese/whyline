# whyline

Use Claude Code and Codex on the same project without either one starting blind.

```
$ whyline explain src/tsconfig/resolve.ts:41

Decision          Treat only canonical in-repo workspace package exports as internal
Because           node_modules must be readable for resolution but never indexed
Rejected          classify any resolvable node_modules target as internal
                  indexes third-party declarations and violates FR-005
Confidence        High — a recorded decision matches the commit for this line.
```

Free, Apache-2.0, local-only. No accounts, no telemetry, no paid tier, ever.

## The problem this solves

Claude Code and Codex are good at different things. You might want Claude to plan
a feature and write the tests, then Codex to review the diff — or the reverse.
That combination is genuinely useful, and today it is genuinely painful: the
second agent starts from nothing. It has no idea what the first one concluded,
what it tried, or what it deliberately ruled out. So you re-explain, or paste, or
just give up and use one agent for everything.

whyline fixes that with a decision record both agents write to and read from. The
one that finishes leaves behind what it decided and what it rejected; the one that
starts picks it up. Neither has to be told twice.

**On the subscriptions you already pay for.** whyline never touches a credential.
It launches the vendor's own CLI with `exec`, so Claude Code authenticates as
Claude Code and Codex authenticates as Codex. No API keys, no per-token billing,
nothing metered on top of what you already have.

And because the record is committed to your repository as plain Markdown, it
outlives the session. Six months later, `whyline explain` still answers why a line
of code exists — which is the same mechanism, read at a longer horizon.

## Install

Not yet published. From a clone:

```bash
uv tool install --from . whyline
```

Zero production dependencies — standard library only. Python 3.11+, plus `git`.

## Quickstart

```bash
whyline init                     # scaffold, add instructions, install the hook
```

Then work normally. Your agents record their own decisions, because `init` adds an
instruction to `AGENTS.md` asking them to. When you want to switch:

```bash
whyline run codex "review the caching change"
```

That composes what Claude decided and hands the terminal to Codex with it attached.
The reverse works the same way: `whyline run claude "..."`.

The rest of the surface:

```bash
whyline brief                    # print the handoff context without launching
whyline explain src/a.py:14      # why does this line exist?
whyline note "chose X" --because "Y" --rejected "Z: too slow" --file src/a.py
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
- **macOS and Linux are verified; Windows is not.** CI passes on `ubuntu-latest`
  and `macos-latest` across Python 3.11 and 3.13. Windows via WSL is untested — a
  plausible claim, not an observation.

## Credentials

whyline never reads, stores, forwards or proxies a vendor token. `run` replaces
itself with the vendor's own CLI via `exec`, which does its own authentication.
Your subscription works because the official CLI is what talks to the vendor.
Permission-bypass flags are never added.

## Performance

Measured on an M-series Mac, median of seven runs, against a 200 ms target:

| Command | Total | whyline's own cost |
|---|---:|---:|
| `brief` | 41 ms | 23 ms |
| `timeline` | 46 ms | 27 ms |
| `status` | 47 ms | 28 ms |
| `explain` | 79 ms | 60 ms |

Bare Python interpreter startup is 19 ms of every figure above, so the right-hand
column is what whyline actually costs. `explain` is dearer because it shells out
to `git blame`.

On a 50,000-event, 6.5 MB ledger `explain` takes ~159 ms against a 1 s target —
which is why there is no SQLite index.

## Licence

Apache-2.0.
