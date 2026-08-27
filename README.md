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

## Install globally, initialise per project

**Once per machine:**

```bash
uv tool install whyline
```

**Once per repository:**

```bash
cd your-project && whyline init
```

The executable is global; do **not** reinstall it inside every directory.
`whyline init` is per Git repository (and per worktree/checkout): it creates the
project-local `.whyline/` state, adds shared instructions, and installs both
Claude Code and Codex project hooks. This separation is intentional — decisions
and active work from one project must never bleed into another.

Codex requires explicit trust for non-managed project hooks. After `init`, open
`/hooks` once in Codex and approve the Whyline definitions. `whyline status`
will say “configured but never observed” until a real event arrives; it does not
mistake a JSON file for a working hook.

`init` asks before touching `AGENTS.md`, `CLAUDE.md` and the hook files, and
pressing Enter accepts — running the command is the consent. Answer `n`, or pass
`--no-instructions` / `--no-hooks`, to skip either part; `--yes` accepts both
without asking, for scripts. Whatever block `init` replaces is copied to
`.whyline/AGENTS.md.bak` first.

Zero production dependencies — standard library only. Python 3.11+, plus `git`.

Re-run `whyline init` any time; it upgrades an outdated instruction block in place
and leaves everything you wrote around it untouched.

## Then just work

Open Claude Code or Codex and build as you normally would. Two things can happen
without you doing anything:

- each vendor's **hook** records sessions, prompts and explicit file edits;
- your **agent** records its own decisions and rejected alternatives, because it
  read the instruction `init` added.

Automatic reading is best-effort, not guaranteed. Use `whyline run` for a handoff
that must reach the next agent, or run `whyline sync` explicitly after opening a
vendor CLI directly.

## Switching agents — the thing this exists for

There are two ways to do it. Both work. They fail differently, so pick with your
eyes open.

### Pattern 1 — two terminals (recommended)

Each agent gets its own session. You decide who does what by which tab you type in.

```bash
# tab 1 — implementation, with context attached reliably
cd your-project
whyline claim WL-42 --actor codex --role implementer --file src/cache.py
whyline run codex "implement bounded cache invalidation" --task-id WL-42

# when implementation is ready
whyline handoff WL-42 --from codex --to claude --status ready-for-review \
  --summary "bounded invalidation implemented" \
  --file src/cache.py --test "pytest -q: passed" \
  --risk "large repositories not benchmarked"

# tab 2 — review, with the same project context attached
cd your-project
whyline run claude "review and commit the cache change" --task-id WL-42
```

You are the switch; whyline is the relay. `run` attaches the history directly,
so it does not depend on an agent remembering to call `brief`. You can still open
`codex` and `claude` directly, but automatic reads from the repository instruction
were measured at only 43%, so that path is best-effort rather than guaranteed.

`claim` is advisory. If both agents claim the same task or file, Whyline warns in
`claim`, `sync`, and `status`; it never locks a file or blocks either agent. This
is how two terminals can coordinate without Whyline becoming an orchestrator.

> Run `run` from your shell, not from inside an agent session. It replaces the
> current process with the agent (`exec`), so launching it from within another
> agent's tool call gives the new agent no terminal and it will fail.

### Pattern 2 — dispatch from inside a session

Ask the agent you are already talking to to call the other one:

> get codex to review the caching change

Claude runs `codex exec …` and the result comes back into your current
conversation. Convenient for a one-shot second opinion, with three limitations:

- **A dispatched agent follows its dispatcher's prompt, not `AGENTS.md`.** In one
  observed run, an orchestrated task recorded **no** decisions, while the same
  agent leading its own session on the next task recorded two and read the history
  unprompted. If provenance matters for a piece of work, let the agent own its
  session.
- **It is one shot.** The dispatched agent has no terminal, so it cannot ask you a
  clarifying question or iterate — it answers once and exits.
- **It does not work in reverse.** Codex cannot launch Claude, because Claude Code
  writes session state outside the workspace and Codex's sandbox blocks that. Do
  not disable the sandbox to force it; use a second terminal.

### Either way

**Codex cannot commit.** Its sandbox blocks writes to `.git`, so it will implement,
test and report, then stop. You or Claude makes the commit. That is a fixed cost of
the sandbox, not a whyline limitation.

Everything else is optional:

```bash
whyline sync --task WL-42        # active handoff + Git + ownership + decisions
whyline brief --file src/a.py    # decisions-only, relevant and token-bounded
whyline explain src/a.py:14      # why does this line exist?
whyline note "chose X" --because "Y" --rejected "Z: too slow" \
  --file src/a.py --actor codex --role implementer --task WL-42
whyline release WL-42 --actor codex
whyline timeline --file src/a.py
whyline status                   # is recording actually live?
```

## What context Whyline keeps

Whyline does not preserve either vendor's hidden conversation. It keeps a small,
explicit relay that both can read:

- `.whyline/decisions.md` — committed durable decisions, rationale, rejected
  options, actor, role, task, and affected files;
- `.whyline/active-handoff.json` — local current task, from/to agent, status,
  changed files, tests/results, risks/questions, and base/current commit;
- `.whyline/ownership.json` — local advisory task/file claims;
- `.whyline/ledger.jsonl` — local mechanical events and prompt text.

Only `decisions.md` is committed. The other three are checkout-local and
gitignored, because stale ownership, a dirty tree, and raw prompts should not
travel to another clone. `sync` combines the active handoff, current Git state,
claims, and task/file-relevant decisions into one nonce-fenced packet. Its
default budget is about 1,200 tokens; raw prompt text is never included.

## What whyline does not do

Worth being explicit, because the name of the category invites the wrong guess.

- **It does not orchestrate.** It never runs both agents, never runs them in
  parallel, and never decides which one should act.
- **It does not assign roles.** It records roles such as implementer or reviewer,
  but you decide them in the command or prompt.
- **It does not supervise.** `run` hands your terminal over and gets out of the
  way. Nothing is captured, parsed or wrapped, so no vendor changing its output
  format can break it.
- **It does not touch your credentials.** Each vendor's own CLI authenticates
  itself, which is why your existing subscriptions just work.

## How it works

Three layers feed one ledger:

1. **git** resolves a line to a commit via `git blame`. Works before whyline has
   recorded anything.
2. **A hook** silently records sessions, instructions and explicit file edits. It
   can never fail your session — every path exits 0. **Verified against Claude
   Code only.** `init` also writes a project-local `.codex/hooks.json`, but no
   Codex hook event has been observed yet, so treat Codex mechanical capture as
   untested rather than working: run `whyline status`, which reports each vendor
   separately and will say `configured but never observed` until one arrives.
3. **Your agent** records the reasoning. `whyline init` adds an `AGENTS.md`
   instruction asking agents to log decisions and rejected alternatives. This is
   the only layer that captures *why*.

`.whyline/decisions.md` is committed and readable with Whyline uninstalled.
The operational records and ledger are gitignored.

## Does the third layer actually work?

It was the design's one unproven assumption, so it was measured before the
features depending on it were built. Over three days across two agents on a real
project, 19 decisions were recorded across 14 commits — Claude Code 150% of its
non-trivial changes against a 60% gate, Codex 130% against a separate "at least
one firing" gate. Every one carried a rationale and a concrete rejected
alternative. Codex was never reminded.

**That rate holds when an agent works directly, and not when it is dispatched.**
A later orchestrated task in the same repository recorded nothing at all, because
a dispatched agent follows its dispatcher's prompt rather than `AGENTS.md`. The
figure above is therefore a property of direct work, not a general one — which is
the reason Pattern 1 above is the recommended shape.

The read side was measured separately, because writing a record nobody consults
is worthless. Claude Code ran `whyline brief` unprompted near the start of 3 of 7
sessions it owned — **43%**, below the 50% threshold fixed before collection.
The result is therefore **unreliable**: use `run` when the handoff must happen,
and treat repository-instruction reads as a useful fallback. Codex was observed
calling `brief` nine times, but no reliable Codex session denominator was
available, so that count is not presented as a rate. Earlier 67% and 50% figures
were superseded as the sample grew.

**One gap is known and unfixed: reviewers record less than implementers.** Across
five tasks on one project, the agent *implementing* recorded every time, while
not one ruling by the agent *reviewing* reached the record — those went to a
tracker that was not committed, and died on clone. 0.1.3 widened the instruction
to name reviewers explicitly. Whether that works is not yet measured, and at
least two other causes are plausible, including that a reviewer working from a
different repository never loads the project's `AGENTS.md` at all.

Full method and caveats: [`m0/RESULTS.md`](m0/RESULTS.md).

## Honest limitations

- **Switching agents is a relay, not a shared conversation.** Vendor CLIs are
  separate processes with separate context windows. `sync` hands the next agent
  explicit state; it cannot continue the previous hidden conversation.
- **`explain` reports confidence and will say when it does not know.** An empty
  ledger produces an honest empty answer, not a guess. File-level `explain` never
  claims high confidence, because without a line there is no blamed commit.
- **Gemini is not supported by `run`** — its free personal tier was withdrawn.
- **Ownership is advisory.** Whyline warns about overlapping writes but provides
  no lock, scheduler, merge engine, or worktree isolation.
- **A fresh clone loses operational state, deliberately.** It retains committed
  decisions, so `brief`, `status`, and `explain` still work; those entries carry
  day precision and therefore never justify high-confidence temporal attribution.
- **macOS and Linux are verified; Windows is not.** CI passes on `ubuntu-latest`
  and `macos-latest` across Python 3.11 and 3.13. Windows via WSL is untested — a
  plausible claim, not an observation.

## Credentials

whyline never reads, stores, forwards or proxies a vendor token. `run` replaces
itself with the vendor's own CLI via `exec`, which does its own authentication.
Your subscription works because the official CLI is what talks to the vendor.
Permission-bypass flags are never added.

## Performance

Measured on an M-series Mac from the 0.2.0 worktree, median of seven runs:

| Command | Total |
|---|---:|
| `brief` | 47 ms |
| `sync` | 92 ms |
| `timeline` | 43 ms |
| `status` | 63 ms |
| `explain` | 94 ms |

All remain below the 200 ms interactive target. `sync` asks Git for branch,
commit, and changed paths; `explain` shells out to `git blame`.

On a 50,000-event, 6.5 MB ledger `explain` takes ~159 ms against a 1 s target —
which is why there is no SQLite index.

## Licence

Apache-2.0.
