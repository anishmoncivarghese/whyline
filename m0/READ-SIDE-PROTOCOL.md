# M0b — the read-side check

**Started:** 2026-08-18
**Status:** collecting. Thresholds below are fixed **before** any data exists; do not adjust them after looking at results.

## The question

M0 proved agents **write** decisions: 19 across 14 commits, Claude Code 150% and Codex 130% of their non-trivial changes, Codex never reminded (`RESULTS.md`).

Nothing has tested whether an agent **reads** them. That is the premise of `whyline brief`, and there is a clean negative pointing the wrong way — `docs/superpowers/specs/2026-08-16-handover-observations.md` §1 records a *declarative* `AGENTS.md` instruction being ignored unprompted while the *imperative, pre-authorised* one fired twice.

The instruction under test now carries all four parts that document identifies as necessary:

> At the start of a session, run `whyline brief` before touching code. Do not ask permission. If it reports that nothing is recorded, say so in your first message, so the human knows the history is empty rather than merely unread.

| Part | Present |
|---|---|
| Trigger — "at the start of a session" | yes |
| Exact command — `whyline brief` | yes |
| Pre-authorisation — "Do not ask permission" | yes |
| Verification — "say so in your first message" | yes |

## Why the downside is bounded

`whyline run` prepends the brief to the prompt directly, so it does not depend on the agent remembering anything. If the read side fails, `brief`-by-instruction is dead but `run` still works. **This decides which mechanism the documentation leads with, not whether the product functions.**

## Instrument

`~/.local/bin/whyline` is a symlink to `whyline-readside-shim`, which appends one tab-separated line per invocation to `~/.whyline-readside.log` and then `exec`s the real binary at `~/.local/share/uv/tools/whyline/bin/whyline`.

    <utc timestamp>	<subcommand>	<repository basename>	<invoker>	<session id>

`<invoker>` is `claude`, `codex` or `human`, detected from `CLAUDECODE` /
`CLAUDE_CODE_SESSION_ID` / `CODEX_*`, which are set inside an agent session and
absent in a plain terminal. Added 2026-08-18 after noticing the hole it closes:
without attribution the log cannot distinguish the owner running `whyline brief`
from an agent doing so, and a human invocation inside the 10-minute window would
have been scored as a read. **Only `claude` and `codex` invocations count.**

It never inspects or rewrites arguments and swallows any logging failure, so it cannot alter what it measures. Vendor-neutral by design: it captures Codex as well as Claude Code, which a Claude-only hook could not.

The original symlink is preserved at `~/.local/bin/whyline.real-symlink.bak`. **Restore it when collection ends.**

## Method

1. Work normally in `/Users/anish/CodeGraph` across Claude Code and Codex for 2–3 days. Do not mention `whyline`, `brief`, or this experiment to either agent.
2. Sessions are counted from `SessionStarted` events in `CodeGraph/.whyline/ledger.jsonl`, which the hook records unprompted. Baseline at start: **7** sessions, and the log contains only the four controller test lines dated 2026-08-18T04:57:46Z, which are excluded.
3. A session **counts as a read** if a `brief` invocation appears in the log within 10 minutes after that session's `SessionStarted` timestamp.
4. Your own `brief` invocations are attributed and excluded automatically, so use whyline freely. What the log still cannot see is *prompting* — if you mention `brief` to an agent, strike that invocation by hand.

## Thresholds — fixed 2026-08-18, before collection

| Unprompted read rate | Meaning | Action |
|---|---:|---|
| ≥50% of sessions | The instruction fires | Lead the README with `brief`; the four-part instruction shape is validated for the read direction too |
| 20–50% | Unreliable | Lead with `run`, keep `brief` documented as a manual command, and say plainly in the README that agents read it inconsistently |
| <20% | The instruction does not fire | `run` becomes the only supported handoff path. Remove the read half of the `AGENTS.md` instruction rather than ship an instruction that does nothing, and record the negative result |

## Threats to validity

- **Operator knowledge.** The owner knows the instruction exists and may unconsciously prompt. Prompting is the one thing the instrument cannot detect, so it must be struck by hand.
- **Invoker attribution closed a real hole.** Before it existed, the owner's own `whyline brief` was indistinguishable from an agent's and would have inflated the rate. Verified: three human reads across three sessions now score 0%, not 100%.
- **Codex attribution.** The log records the repository, not the agent. Attribution comes from correlating timestamps against ledger `SessionStarted` events, which only the Claude Code hook writes — so a Codex session has no `SessionStarted` and cannot be counted as a denominator. **Codex read behaviour is therefore observational only in this round**, noted rather than scored.
- **Single project, single operator.** Same limit as M0. Directional, not statistical.
- **`brief` is also invoked by `run`.** A `run` invocation logs as `run`, not `brief`, so the two do not confound — but a `brief` immediately following a `run` in the log is the agent's own call, not `run`'s internal composition, because `run` calls `brief.compose` in-process rather than shelling out.

## Observed limit — recorded 2026-08-18, mid-collection

A full orchestrated cross-vendor task ran in CodeGraph: Claude planned and wrote a
task brief, Codex implemented it under `codex exec`, a reviewer found a real
correctness bug in the brief's own algorithm, Codex fixed it, Claude verified and
committed. Three commits landed.

**whyline recorded none of it.** `decisions.md` stayed at 19 entries. The decision
that was made — loop the named re-export pass to a fixpoint, rejecting single-pass
resolution because a 3+ level chain resolves wrongly depending on insertion order —
is exactly what this tool exists to capture, and it went unrecorded.

The reasoning was captured, richly, in `.superpowers/sdd/<plan>/progress.md`, which
is **gitignored**. So it dies on a clone and whyline cannot see it.

**What this bounds.** M0's write-side rate (19 decisions over 14 commits) was
measured while agents worked *directly* with the human. Under an orchestrated flow
that has its own ledger, the same repository recorded zero. The rate is therefore
workflow-dependent, and must be stated that way rather than as a general property
of the instruction.

This does not affect the read-side measurement below, which concerns `brief` only.

## Results

Fill in at the end of collection. Do not edit the thresholds above.

| Agent | Sessions | Unprompted `brief` reads | Prompted | Rate |
|---|---:|---:|---:|---:|
| Claude Code | | | | |
| Codex | observational | | | n/a |

**Outcome:** _pending_
