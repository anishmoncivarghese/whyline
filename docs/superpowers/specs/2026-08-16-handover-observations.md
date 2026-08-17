# Handover observations — CodeGraph session, 2026-08-16

Raw observations from a long agent session in `~/CodeGraph`, a repo instrumented
with whyline + AGENTS.md. Recorded as evidence, **not** as plan changes. The
decisive cross-vendor experiment (§4) has not been run yet; do not amend the
AgentDock plan on the strength of what is here alone.

---

## 1. Negative result: the handover file was not updated unprompted

**Setup.** Claude Opus 5 worked ~6 hours in `~/CodeGraph`: PRD analysis, a design
spec through two revisions, a 16-task implementation plan, and removal of a stale
third-party tool. AGENTS.md was present the whole time and contained:

> Store shared project instructions here, but record evolving decision history
> through whyline rather than appending it to AGENTS.md.

**Result.** AGENTS.md was **not** updated until the human explicitly asked
("confirm you are updating the Agents.md file?"). Once asked, ~60 lines were
written immediately and without difficulty — so this was not a capability limit.

**Contrast, same session, same agent.** The whyline instruction *was* followed
unprompted, twice, with no reminder.

| | whyline note | AGENTS.md |
|---|---|---|
| Trigger condition | "After completing any non-trivial change" | none |
| Form | imperative + exact command | declarative statement of where things live |
| Pre-authorization | "Do not ask permission" | unstated |
| Verification | none | none |
| **Followed unprompted?** | **yes (2×)** | **no** |

**Reading.** An instruction fires when it states *when*, gives the *exact
command*, and pre-authorizes. A statement of fact about where things belong does
not create a felt obligation. The agent's own account was that it read the
"rather than appending to AGENTS.md" clause as a prohibition and inverted a
permission into a restriction.

**Secondary observation.** The agent wrote AGENTS.md spontaneously only when it
became *instrumentally useful to itself* — dispatching its own subagents, which
would read that file and nothing else. It did not write it for the benefit of a
hypothetical future Codex session. Handover written only when the writer benefits
is not handover.

---

## 2. Positive result: a falsifiable handover caught a bad instruction

**Setup.** A fresh implementer subagent, with no access to the session, received a
task brief that contained a wrong dependency pin (`better-sqlite3@^11.0.0`). The
brief also carried a verified claim and a failure protocol:

> expect `prebuilds/` to list `darwin-arm64.node` … if Step 5 fails **here**, that
> is a genuine blocker — report BLOCKED rather than working around it

**Result.** The subagent installed, observed `node-gyp` compiling from source,
recognised the contradiction with the stated constraint, and escalated with a
correct diagnosis — rather than silently bumping the version and proceeding.

**Reading.** The handover carried a **falsifiable claim plus a failure protocol**,
so the receiver could detect that the handover itself was wrong. Had it carried
only the instruction ("install better-sqlite3"), the result would have been a
source-built binary silently violating a project constraint — undetected until
someone tried to install on another machine.

**Principle.** Handover assertions should ship with how the receiver detects they
are false. "Node is v24" is inert. "Run `nvm use`; if `npm install` prints
`EBADENGINE` you are on the wrong node" is self-checking.

---

## 3. Structural observation: handover state is git-ignored

In this session the execution ledger lives at
`.superpowers/sdd/<plan>/progress.md`, and `.superpowers/sdd/.gitignore`
contains `*`.

Consequence:

| Artifact | Committed? | Survives a fresh clone / second machine? |
|---|---|---|
| `AGENTS.md` (stable rules) | yes | yes |
| `.whyline/decisions.md` (history) | yes | yes |
| SDD ledger (current progress) | **no** | **no** |

So handover works agent-to-agent on one machine, and fails across clones or
machines. This is a design question AgentDock should answer deliberately rather
than inherit: **does handover state travel with the repository, or is it
machine-local?** If AgentDock claims cross-machine handoff, a git-ignored ledger
cannot be the mechanism.

A related split was adopted in CodeGraph's AGENTS.md and seems to hold up: stable
rules are written in the handover file; volatile state is *pointed to*, never
copied, because a hand-maintained status section goes stale and then actively
misleads — the same failure mode as the stale index that project exists to fix.

---

## 4. The experiment that has NOT been run

Nobody has verified that Codex (or any non-Claude agent) reads `AGENTS.md` and
acts on it. That is currently an assumption.

**Protocol.** At a clean boundary — one task complete, ledger updated, working
tree clean, nothing else running — open Codex in `~/CodeGraph` and give it exactly
one instruction: *"continue"*. Score:

1. Does it read `AGENTS.md` unprompted?
2. Does it follow the pointer to the ledger and identify the correct resume point?
3. Does it respect the stated invariants without restatement?
4. Does it run `nvm use` before `npm`, or hit `EBADENGINE`?

**Most valuable outcome:** if it *redoes an already-complete task*. That is the
precise failure the ledger exists to prevent, and it would mean the ledger was
either not found or not trusted.

**Caveat for the record.** The observation in §1 is clean — the failure was
recorded before the human intervened. Everything after that prompt is
contaminated for "unprompted" measurement in this session. An imperative,
triggered variant of the AGENTS.md instruction should be A/B'd against the
declarative one in a *fresh* session, not this one.

---

## 5. Candidate requirements (unvalidated — pending §4)

Listed for later evaluation, not adoption:

1. An instruction needs four parts to fire reliably: **trigger, exact command,
   pre-authorization, and verification.** whyline has the first three and is
   followed; nothing in this session had the fourth. Note that the absent fourth
   part is exactly how the `code-review-graph` tool this session removed came to
   fail silently for months — its refresh hook exited 127 on every invocation and
   nothing ever checked.
2. Handover should be written on a **trigger** (session end, task completion),
   not left to the agent to remember. §1 is the evidence.
3. Handover content should be **split by volatility**, with the volatile half
   referenced rather than duplicated.
4. Handover claims should be **falsifiable by the receiver**. §2 is the evidence.
