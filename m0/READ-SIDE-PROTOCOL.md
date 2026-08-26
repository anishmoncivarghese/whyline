# M0b — the read-side check

**Started:** 2026-08-18
**Completed:** 2026-08-23. Thresholds below were fixed **before** collection and
were not adjusted after looking at results. Final result: 3 of 7 Claude Code
sessions, **43% — unreliable**.

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

During collection, `~/.local/bin/whyline` was a symlink to
`whyline-readside-shim`, which appended one tab-separated line per invocation to
a log and then `exec`ed the real binary at
`~/.local/share/uv/tools/whyline/bin/whyline`. The real executable symlink was
restored on 2026-08-23 by `m0/end-readside-collection.sh`.

**Two log locations, and which one matters was itself a finding** (`02e52de`). The shim writes to `<repo>/.whyline/readside.log` when invoked inside a repository, falling back to `~/.whyline-readside.log` otherwise; `analyse-readside.py` merges both. The in-workspace log is the authoritative one for sandboxed agents: the original `$HOME`-only design was silently unwritable from Codex's sandbox, and because the shim swallows logging failures by design, Codex's reads simply vanished. Merging is what makes the instrument see both vendors.

    <utc timestamp>	<subcommand>	<repository basename>	<invoker>	<session id>

`<invoker>` is `claude`, `codex` or `human`, detected from `CLAUDECODE` /
`CLAUDE_CODE_SESSION_ID` / `CODEX_*`, which are set inside an agent session and
absent in a plain terminal. Added 2026-08-18 after noticing the hole it closes:
without attribution the log cannot distinguish the owner running `whyline brief`
from an agent doing so, and a human invocation inside the 10-minute window would
have been scored as a read. **Only `claude` and `codex` invocations count.**

It never inspects or rewrites arguments and swallows any logging failure, so it cannot alter what it measures — at the cost that a failed write is indistinguishable from no invocation, which is exactly how Codex's reads went missing.

It captures Codex as well as Claude Code, which a Claude-only hook could not. **It is not, however, "vendor-neutral by design"** — that claim was made and then retracted in `02e52de`: neutrality depended on a log location one vendor's sandbox forbids, so it was a property of the environment, not of the design.

**Collection is closed.** The shim is no longer the active global executable.

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

Final score produced 2026-08-23 via `m0/end-readside-collection.sh`, which first
restored the real executable and then ran `python3 m0/analyse-readside.py`.

| Agent | Sessions | Unprompted `brief` reads | Prompted | Rate |
|---|---:|---:|---:|---:|
| Claude Code | 7 | 3 | 0 (per the operator) | **43%** |
| Codex | no denominator | 9 logged, plus 1 transcript-confirmed but unlogged (Task 11, see `02e52de`) | 0 (per the operator) | n/a |

Superseded figures, kept so the trend is legible rather than silently restated:
67% at 3 sessions (2026-08-18), and a briefly-reported 75% that was an artifact
of the vendor-contamination bug described below.

**Outcome: UNRELIABLE.** 43% falls below the precommitted 50% threshold and in
the 20–50% band. The README therefore leads with `run`, keeps `brief` as a manual
command, and states plainly that instruction-driven reads are inconsistent.

The denominator is still small: each of seven sessions is worth about 14
percentage points. The result is directional rather than statistical, but the
precommitted action is unambiguous because 43% is below the threshold.

Worth separating from the rate itself: Claude Code issued 4 `brief` calls across
7 sessions, but only 3 fell inside a session-start window. A mid-session `brief`
is a real read and still not the behaviour under test, which is specifically
whether an agent orients itself *before* touching code. The instrument is right
to exclude it; the gap between "3 reads" and "2 scoring reads" is a property of
the question, not a measurement error.

Codex had issued zero *logged* `brief` invocations as of this scoring (its
only logged calls were `note`). That is not the same as no observation:
commit `02e52de` records Codex running `whyline brief` unprompted as its
first action on a bare "start task 11", calling it "the required history
check" — confirmed from the transcript, but invisible to the log, because
the shim then wrote only to `$HOME` and Codex's sandbox blocks that path.
Distinguish **logged** from **observed** everywhere below; conflating them
is what produced a false negative in the first place.

**Re-scored 2026-08-18 after a Task 13 round: unchanged (3 sessions, 67%).**
Task 13 added two more Codex `note` writes (16:04, 17:29) but no new
`SessionStarted` event, because Codex ran via the `codex` CLI directly and
the review/commit ran via Bash from an already-open session elsewhere,
`cd`-ing into the repo rather than starting a `claude` process inside it.
The instrument can only see a Claude Code session that starts *in* the
target repo — a review done by shelling in from another session is
invisible to the denominator. Note this as a methodology limit before
trusting a "no change" reading: it can mean either "the instruction still
doesn't fire more" or "no new session was ever counted," and this round is
the latter.

**Re-scored 2026-08-18 after a Task 14 round (Codex implements, Claude
reviews and commits, same pattern as Task 13): Claude Code unchanged (3
sessions, 67%) for the same reason — no new `claude` process started inside
CodeGraph. Codex produced its first *logged* `brief` call**
(2026-08-18T21:03:15Z, `.whyline/readside.log`). Not its first read — see the
Task 11 transcript-confirmed one above; this is the first the instrument
could actually capture, now that the log lives inside the workspace.

The operator reports not mentioning `whyline` or `brief` to Codex for this
task. Per "Threats to validity" above, prompting is the one thing the
instrument cannot detect, so that is an operator report and not an instrument
reading — the same standing as M0's own unpromptedness claim.

Still no denominator-based rate for Codex: `SessionStarted` is written only by
the Claude Code hook, so there is no way to know how many `codex` invocations
this one `brief` is out of. Treat it as **Codex has been observed reading
unprompted, twice, and logged once** — not as a rate.

## Codex session boundaries are invisible, so its counts are not a rate — 2026-08-19

Codex ran no `brief` for Plan 2 Task 7, having last run one about six hours and
three tasks earlier. That looks like the instruction failing to fire. It is not.
The operator confirmed all of Phase 2 ran in **one continuous Codex session**, and
the instruction's trigger is "at the start of a session" — so reading once and not
re-reading per task is exactly what it asks for. **Codex is compliant.**

The instrument could not settle this on its own, and that is the finding.
`whyline-readside-shim` writes `${CLAUDE_CODE_SESSION_ID:-}` into its session-id
field, so the field is empty for Codex *by construction*. Checked the live Codex
process directly on 2026-08-19: its environment carries only
`CODEX_MANAGED_BY_NPM` and `CODEX_MANAGED_PACKAGE_ROOT`, both constant across
sessions. **Codex exposes no session identifier at all**, so this is not a shim
bug that a better variable would fix.

What that costs, stated plainly:

- A gap between two Codex `brief` calls is **uninterpretable**. One long session
  spanning ten tasks and ten separate sessions that never read produce the same
  log.
- So Codex's `brief` count is **not a numerator over tasks**. If Codex opened
  three sessions and read at the start of each, that is 100% compliance, and the
  log looks identical to three reads scattered across thirty tasks.
- Every earlier statement here counting Codex reads inherits this. They remain
  true as counts and were never rates; read them as "Codex was observed reading
  unprompted at session start, N times", never as a frequency.

Rejected as a fix: deriving a session key by walking the process tree to a Codex
ancestor and using its start time. It would work, but it puts fragile logic in an
instrument whose one safety property is being too simple to alter what it
measures — and the collection it would serve is already concluding.

## The analyser was crediting one vendor's reads to the other — fixed 2026-08-19

`analyse-readside.py` built its numerator from `who in ("claude", "codex")`
while its denominator stayed Claude-only `SessionStarted` events. Any Codex
`brief` landing inside a Claude session's 10-minute window therefore scored
that Claude session as having read.

Latent from the start; it surfaced only when a Codex `brief` at
2026-08-19T03:34:33Z fell 30 seconds after a Claude session started at
03:34:03Z. The reported rate went to **75% when the true figure was 50%** —
the metric moved in the opposite direction from reality, since that session
had in fact not read. The original filter was written to exclude the *human*;
excluding one vendor from the other's numerator is the same requirement,
missed.

Now scored separately: Claude briefs score Claude sessions, Codex briefs are
reported as an observational count that can never move the rate.

**Standing at 2026-08-19: 4 Claude sessions, 2 with a read, 50%** — exactly on
the 50% threshold rather than comfortably above it. Codex: 3 logged reads,
observational. Read this as *weaker* than the earlier 67%, not stronger: the
sample grew and the newer sessions did not read. Two of the four Claude
sessions ran no `brief` at all.

## The analyser stopped reproducing its own published result — fixed 2026-08-25

Two days after close, `analyse-readside.py` reported **12%** and printed "THE
INSTRUCTION DOES NOT FIRE", against a published **43%** and "unreliable". A
reader running the script would have caught the repository contradicting itself.

Two causes, both in the script, neither in the data:

1. **It counted `SessionStarted` events, not sessions.** Claude Code's
   SessionStart hook fires on resume as well as launch, so a long-lived session
   emits many events. The ledger held 26 events for 10 distinct sessions — 17 of
   them from one session resumed over several days. The denominator therefore
   grew with how often a session was reopened, which is not a measure of
   anything. Now keyed on the `session` field, earliest event per id.
2. **It had no closing boundary.** The hook keeps writing forever, so every
   later session enlarged the denominator and dragged the rate down. Now bounded
   at the moment `end-readside-collection.sh` restored the real executable,
   taken from that symlink's mtime rather than a round number chosen afterwards.

Both fixes move the number *up*, so both deserve suspicion. Two facts settle it,
and they are separate:

- **The boundary is structural, not a choice.** The shim that produced the
  *numerator* wrote its last line at `2026-08-22T18:12:48Z`. After that no read
  could be logged at all, so a later session cannot score one — including such
  sessions in the denominator would guarantee a false negative rather than
  merely add noise. And it is **not verdict-critical**: without the bound the
  rate is 3/9 = **33%**, still inside the 20–50% `UNRELIABLE` band, so the
  published verdict and every precommitted action are unchanged either way.
- **The dedup is verdict-critical, which is why it had to be right.** Scored per
  event the figure is 12%, in the "does not fire" band; scored per session it is
  43%, in "unreliable". The justification cannot be that one number is nicer: it
  is that a denominator which grows when you press resume is not measuring
  sessions, and the hook records the session id explicitly so no inference is
  involved.

With both fixes the script reproduces the published figures exactly — 7
sessions, 4 Claude `brief` invocations, 3 qualifying reads, 43%, `UNRELIABLE`.

**This is the third defect found in this instrument, and the third that pointed
the wrong way about an agent's behaviour.** The `$HOME` log location hid every
Codex read and would have concluded Codex never reads. Cross-vendor scoring
credited a Codex read to a Claude session and inflated 50% to 75%. Now
event-counting understated 43% as 12%. Every examination of this instrument has
found it wrong; the measured *conclusion* has survived each time, which is the
only reason the audit trail is worth more than the number.

## Final collection close — 2026-08-23

The final analyser output was 7 Claude Code sessions, 4 Claude `brief`
invocations, 3 sessions with a qualifying read, and a **43%** unprompted read
rate. Codex produced 9 logged reads, reported only as observations because the
instrument has no Codex session denominator. The global shim was removed and
the real whyline 0.1.4 executable restored. This final result supersedes every
intermediate 67%, 75%, and 50% figure above without erasing the audit trail that
explains how those figures arose.
