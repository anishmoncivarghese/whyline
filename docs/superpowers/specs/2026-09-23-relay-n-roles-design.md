# whyline-relay: N named roles, pipeline stages, and model selection

Status: design, awaiting the owner's review. Written 2026-09-23.
Relates to: `2026-09-22-relay-agent-adapters-design.md` (piece 1, pluggable roles, shipped as
0.2.2-0.2.3) and `2026-09-22-relay-backup-failover-design.md` (piece 3, shipped as 0.2.4-0.2.5,
whose section 8 named this piece — "A" in that roadmap — as the foundation everything else needs).
This is that foundation, generalized beyond its original scope to also cover model selection,
since the two turned out to share the same underlying mechanism (see 5.10).

**This design was informed by two independent architectural consultations**, run for real against
this repository: Codex (`codex exec -s read-only`) and Antigravity/`agy` (`--mode plan`), each given
the same brief (`docs/n-roles-architecture-consultation.md`) and neither shown the other's answer.
Where they converged independently, this design treats that as a strong signal; where they
disagreed, the owner picked. Both are attributed by name at each such point below.

## 1. Summary

Today the relay runs exactly two roles — implementer and reviewer, the reviewer also commits —
with a routing table, a five-status vocabulary, and a config schema all hard-coded to that shape.
This design generalizes all three to an arbitrary, configured sequence of named roles ("stages"),
while keeping every existing two-role `config.toml` working with **zero change to its behavior or
its files** — the same bar every release so far has held itself to. It also adds model selection
(e.g. Opus for one role, Haiku for another, from the same underlying tool), because building it
turned out to need the same config generalization this piece already does.

## 2. Goals and non-goals

Goals

- Any number of named stages, each with a role (which agent fills it), a prompt, and where a
  rejection sends the task back to.
- A "profile" selects which stages a given task actually runs, so a trivial task doesn't have to
  go through every gate.
- Exactly one thing commits, deterministically, for pipelines that opt into the new model.
- A stage's agent can specify a model (`opus`, `haiku`, a full model name, or a Codex/Antigravity
  model string), without losing the built-in adapter's managed login/permissions/denial-parsing.
- Crash-safe resume: which stage a paused task was on, and that a handoff already consumed is
  never processed twice, survive a restart.
- `whyline-relay roles set <ROLE>` changes a role's permanent agent/model assignment after initial
  setup; `init` asks about every configured role's agent and model once per repo.
- Every existing two-role `config.toml`, with no `[pipeline]` table, behaves identically to 0.2.5.

Non-goals (this design)

- **Subscription-aware setup** (roadmap piece D). Nothing here checks whether an account can
  actually use a chosen model — that needs real measurement of what each CLI can report about its
  own account, which hasn't been done. Picking a model your plan doesn't cover fails at run time,
  same as today.
- **The planner itself**, and its human/auto review gate (roadmap piece E). Both independent
  consultations agreed planner is not a per-task pipeline stage — it produces `plan.md`, which the
  per-task engine this design builds then consumes. Piece E reuses this design's stage/profile
  engine for a separate, outer planning workflow; it is not built here.
- **True concurrency** for the tester role. Interleaved turns from the same task text, in either
  order — not two processes touching the working tree at once (matches the earlier decision that
  ruled out worktree-based parallelism as its own, bigger project).
- More than one backup per role, or a backup for a backup (unchanged from the failover design).

## 3. Decisions

| # | Decision | Reason | Source |
|---|---|---|---|
| D1 | Three separate concepts: `Role` (agent + backup), `Stage` (id, role, prompt, rejection target, visit limit), `Profile` (named ordered stage list) | Lets one role fill several stages, or one agent fill several roles, without conflating identity | Codex |
| D2 | A `config.toml` with no `[pipeline]` table compiles into a fixed, built-in two-stage pipeline reproducing today's exact routing, statuses, and reviewer-commits behavior | The compatibility bar is behavioral, not just "the file still parses" — proven the same way every past release proved it, by running the *old* suite unedited | Codex, matching this project's own established practice |
| D3 | `status_map`'s five names survive only inside that compiled legacy pipeline. A configured `[pipeline]` uses stage-local outcome labels instead | The five names were never really five independent statuses — `approved`/`blocked` are universal, the rest are one specific (status, recipient) pair per adjacent-stage boundary | Codex |
| D4 | Whyline's `Handoff` record is **unchanged** — no new fields. All stage/profile/cursor state lives in new relay-side state, checkpointed before each turn, fingerprinted against the pipeline config | Changing the external whyline handoff protocol would require every generic agent to understand a new concept it was never told about explicitly; unnecessary if relay state is correct | Codex |
| D5 | Optional stages are chosen via named **profiles**, selected per task with a plan-line directive, not free-form per-task skip lists | A typo in a skip list silently drops a required gate; a profile is a reviewable, named, config-level object | Codex over Antigravity (Antigravity proposed skip-tags plus an agent-declared `--status skipped` escape hatch); owner's choice |
| D6 | For a configured `[pipeline]`, **the relay itself commits** after terminal approval — not an agent. Legacy (no `[pipeline]`) keeps today's exact reviewer-commits behavior | Removes an entire class of bug (a committing agent's own judgment being wrong) rather than only guarding against it; also removes the need to invent a "committer" turn that performs no judgment | Codex over Antigravity (Antigravity proposed a designated `can_commit` stage, still an agent action); owner's choice |
| D7 | Every rejection rewinds to one designated target per gate — always ending at the implementer, never autonomously back to the planner. A reviewer that thinks the plan itself is wrong hands off `blocked` for a human | Prevents "goal erosion": an agent quietly rewriting requirements to make failing work pass | Codex and Antigravity independently agreed |
| D8 | Crash-safe resume via a persisted stage cursor (`task, profile, stage, consumed_handoff_id, stage_visits, base_commit, pipeline_fingerprint`) | The same agent can legally fill more than one role; `to_actor` alone can't disambiguate which stage should resume. A fingerprint mismatch (config changed since the run paused) pauses for a human rather than guessing | Codex |
| D9 | Tester is a first-class stage. Documentation is not (task content instead). Security-review is a stage, but profile-gated, not always on | Independent test authorship catches weak/tautological tests the current single-session implementer can produce; a docs-only change doesn't need its own agent turn; not every task needs a security pass | Codex and Antigravity independently agreed |
| D10 | An agent name may declare `adapter = "codex"` or `adapter = "claude"` explicitly (not only `"generic"`), plus an optional `model`, translated into the tool's real flag by a new `model_flag` field on `Adapter` | Verified for real: all three CLIs already support `--model` (`codex exec -m/--model`, `claude --model`, `agy --model`). Without this, two model-variants of the same tool need two full command rewrites and one of them loses managed status by being forced into `generic` | This session, confirmed against real `--help` output |
| D11 | `roles set <ROLE> [--agent NAME] [--model NAME]` extends the existing `roles` command (today: `status`, `reset`) to persist a **permanent** config change; called with no flags, it prompts interactively. `init` asks about every configured role's agent and model once per repo | Same "set it once, change it anytime" pattern the owner asked for; reuses the `roles` command family already shipped in 0.2.4 rather than inventing a new one | Owner's request |

## 4. Where this sits relative to today's code (measured, relay 0.2.5)

| File | Today | What changes |
|---|---|---|
| `routing.py` | `decide()`, a pure function keyed on `(to_actor, status)`, five fixed statuses, a binary implementer/reviewer choice | Becomes stage-aware: `decide(record, previous_id, current_stage, pipeline, effective_agents) -> Decision`. The legacy two-role table (D2) becomes one built-in compiled `Pipeline` value, not special-cased code |
| `config.py` | `Roles(implementer, reviewer)`; `[roles]`/`[roles.backup]` key on exactly those two names; agent validation requires `adapter = "generic"` for any non-built-in name | Gains `[pipeline]`, `[pipeline.profiles]`, `[pipeline.stages.*]` (new, optional); a non-built-in agent name may set `adapter` to a built-in adapter name, not only `"generic"`, plus an optional `model`; `[roles]` generalizes to any stage's role name when `[pipeline]` is present, and keeps meaning exactly `implementer`/`reviewer` when it is absent |
| `handoff.py` | `Handoff(event_id, task, to_actor, status, summary, questions, from_actor)` | **Unchanged** (D4) |
| `state.py` | `RelayState` holds enough to resume a two-role task | Gains the stage-cursor fields from D8, additive, so a legacy pause/resume record still round-trips |
| `loop.py` | `_run_task`'s `while True:` binary role choice; the implementer-never-commits HEAD check; the reviewer commits inline in its own prompt | Drives the compiled `Pipeline` instead of a hard-coded binary choice; the HEAD-check generalizes to "any non-committing stage"; for a `[pipeline]` config, the relay commits directly after terminal approval (D6) instead of the agent doing it |
| `prompts.py` | Two built-in templates, `{implementer}`/`{reviewer}` placeholders, routing commands embedded directly in the editable template text | Legacy templates and placeholders **unchanged**. A configured pipeline's stages get a relay-generated protocol footer (stage, role, actor, permitted outcomes, exact recipient, handoff command) appended to an editable stage-instruction body, so a stale hand-edited template can't send a handoff to the wrong place |
| `adapters/base.py` | `Adapter(name, default_command, binary, login_argv, login_fix, permission_files, diagnose, manages)` | Gains `model_flag: tuple[str, ...] | None` (D10) |
| `adapters/__init__.py` | `BUILTIN = {"codex": ..., "claude": ...}`; `get(name)` returns `GENERIC` for `"generic"`, else a `BUILTIN` lookup | `get` also resolves a config-declared `adapter = "codex"|"claude"` under a custom name to the same built-in `Adapter`, with `model` layered on top of its `default_command` |
| `roles.py` | `status`, `reset` | Gains `set` (D11) |
| `cli.py`, `init.py` | `init --implementer/--reviewer` (built-in names only) | `init` asks about every configured role's agent and model (D11); `roles set` wired in |

## 5. Design

### 5.1 The internal model

```python
@dataclass(frozen=True)
class Role:
    name: str
    agent: str
    backup: str | None = None

@dataclass(frozen=True)
class Stage:
    id: str
    role: str                    # a Role.name
    prompt: str                   # which prompt template to render
    transitions: dict[str, str]    # outcome name -> a Stage.id, or "@next"/"@complete"/"@blocked"
    max_visits: int = 3

@dataclass(frozen=True)
class Profile:
    name: str
    stages: tuple[str, ...]    # ordered Stage.ids

@dataclass(frozen=True)
class Pipeline:
    roles: dict[str, Role]
    stages: dict[str, Stage]
    profiles: dict[str, Profile]
    default_profile: str
    legacy: bool               # True for the compiled two-role compatibility pipeline
```

Stage IDs and role names are deliberately distinct namespaces (one role can fill several stages;
one agent can fill several roles), matching Codex's proposal exactly. `transitions` mirrors the
TOML `[pipeline.stages.<id>.on]` table one to one — every outcome a stage's agent may report maps
to exactly one target, so D7's "rejection always rewinds to one designated target" is just each
stage's own `transitions["changes-requested"]` (or whichever outcome name that stage uses)
pointing at `implement`, not a separate mechanism.

### 5.2 Configuration

```toml
[roles]
implementer = "codex"
tester      = "claude"
security    = "claude"
reviewer    = "claude"

[roles.backup]
implementer = "antigravity"
tester      = "codex"

[pipeline]
default_profile = "full"

[pipeline.profiles]
full  = ["implement", "test", "security", "review"]
small = ["implement", "review"]

[pipeline.stages.implement]
role = "implementer"
prompt = "implement"
[pipeline.stages.implement.on]
ready = "@next"
blocked = "@blocked"

[pipeline.stages.test]
role = "tester"
prompt = "test"
[pipeline.stages.test.on]
passed = "@next"
changes-requested = "implement"
blocked = "@blocked"

[pipeline.stages.security]
role = "security"
prompt = "security-review"
[pipeline.stages.security.on]
approved = "@next"
changes-requested = "implement"
blocked = "@blocked"

[pipeline.stages.review]
role = "reviewer"
prompt = "review"
[pipeline.stages.review.on]
approved = "@complete"
changes-requested = "implement"
blocked = "@blocked"
```

`@next` resolves against the active profile; an explicit stage id is a backward edge; `@complete`
and `@blocked` are terminal. A `config.toml` with **no `[pipeline]` table** parses exactly as today
— `[roles]` still means only `implementer`/`reviewer`, `[roles.backup]` still validates against
only those two keys, and `status_map` still governs routing directly, byte for byte.

**Preflight refuses**, before anything launches: an unknown role, stage, profile, or agent in a
transition target; `@next` on a pipeline's last stage; a profile with no reachable `@complete`; an
unbounded cycle (no stage's `transitions` can return to itself without an intervening
`max_visits`-bounded stage); and a `[pipeline]` table combined with a hand-written `[status_map]`,
since the combination is ambiguous about which vocabulary governs.

### 5.3 Legacy compatibility

Compiled in code, not written out as TOML, when no `[pipeline]` table exists:

- Stage `implement`, role `implementer`: `transitions = {"ready-for-review": "review"}`; nothing
  transitions into it as a rejection target from itself, and `assigned`/`changes-requested`
  (recipient must be the implementer) simply repeat this same stage.
- Stage `review`, role `reviewer`: `transitions = {"approved": "@complete", "changes-requested":
  "implement"}`.
- `approved` and `blocked` remain universal terminal outcomes regardless of recipient, exactly as
  `routing.py`'s current docstring describes.
- The reviewer keeps committing directly, inline in its own prompt turn (D6 applies only when a
  `[pipeline]` table is present).

The regression proof is the same technique used for the adapters and failover pieces: the entire
existing 313+38-test suite, and the existing acceptance suites, pass **unedited** against a build
of this design with no `[pipeline]` configured anywhere.

### 5.4 Routing, the handoff, and crash-safe resume

`routing.decide()`'s new shape:

```python
def decide(
    record: handoff.Handoff | None,
    previous_id: str | None,
    current_stage: str,
    pipeline: Pipeline,
    effective_agents: dict[str, str],   # role name -> the agent actually filling it right now
) -> Decision:
    ...

@dataclass(frozen=True)
class Decision:
    kind: str            # "advance" | "reject" | "complete" | "blocked" | "no-handoff" | "unknown"
    target_stage: str | None
```

`Handoff` itself does not change (D4): `from_actor` is the agent that just ran, `to_actor` is the
effective agent for the target stage, `status` is a stage-local outcome string. Role and stage
identity live only in relay state, never in the whyline-authored record.

New, additive fields on the paused-run state (existing legacy fields untouched, so an old
`state.json` still loads):

```json
{
  "task_id": "T-1",
  "profile": "full",
  "stage": "test",
  "consumed_handoff_id": "event-17",
  "stage_visits": {"implement": 2, "test": 1},
  "base_commit": "...",
  "pipeline_fingerprint": "sha256 of the compiled pipeline"
}
```

The relay checkpoints the target stage and the event id it is about to consume **before** launching
the next agent. A crash before that save re-processes the same handoff on resume; a crash after it
does not consume the same event twice. A `pipeline_fingerprint` mismatch on resume (the owner
edited `[pipeline]` while a task was paused) pauses for a human rather than guessing which shape of
pipeline to continue under.

### 5.5 Optional stages

A task line may declare a profile:

```markdown
- [ ] DOC-4: Correct the heading
      relay-profile: small
```

Missing the directive uses `pipeline.default_profile`. `plan.parse()` reads it the same way it
already reads a task's id and detail lines. The selected profile is part of the resumable state
cursor (5.4), so resuming a paused task never re-derives or re-guesses which stages apply.

### 5.6 Commit ownership

For a configured `[pipeline]`: every non-terminal stage keeps the existing HEAD-comparison guard
(generalized from "if role == implementer" to "if this stage is not the terminal one"). After the
terminal stage hands off its accepted outcome, the relay itself:

1. Records an `approved-pending-commit` checkpoint.
2. Verifies HEAD still equals the base commit recorded for this task (no stage sneaked a commit in).
3. Creates the commit, with the task id in the message, itself.
4. Verifies the new commit and a clean working tree, via the existing `gitcheck` functions.
5. Ticks the plan through the existing relay-owned commit path, unchanged.

Legacy (no `[pipeline]`) keeps today's behavior exactly: the reviewer commits, `gitcheck.commit_verified` checks its work.

### 5.7 Prompts

A configured pipeline's stage prompts split into an editable body (what to do) and a relay-generated
protocol footer (stage, role, actor, the exact permitted outcomes for *this* stage, the exact
recipient, whether this stage may commit, and the literal handoff command) appended at render time.
This is a deliberate change from today's model, where the routing commands live inside the editable
template text: with configurable transitions, a hand-edited stale template is a much more likely
source of a wrong handoff than it is today with exactly two fixed roles. New placeholders for a
configured pipeline: `{actor}`, `{role}`, `{stage}`, `{profile}`, `{next_actor}`. Legacy
`implement.md`/`review.md` and their `{implementer}`/`{reviewer}` placeholders are unchanged and
never gain a footer — the footer only applies to stages defined under `[pipeline.stages]`.

### 5.8 Which candidate roles get a stage

- **Implementer, reviewer**: unchanged first-class stages (already exist).
- **Tester**: first-class stage. Runs after implement, rejects back to implement, its own
  `max_visits`.
- **Security-review**: first-class stage, but only present in profiles that include it (e.g.
  `full`, not `small`).
- **Documentation**: not a stage. Belongs in task content, or as its own plan task, per both
  consultations.
- **Planner**: not a per-task stage at all (non-goal, section 2) — a separate workflow, built later,
  that reuses this design's `Stage`/`Profile` machinery outside `_run_task`'s loop.

### 5.9 Model selection

```toml
[agents.claude-opus]
adapter = "claude"
model = "opus"

[agents.claude-haiku]
adapter = "claude"
model = "haiku"

[roles]
tester = "claude-haiku"
# a stage's role config elsewhere names "claude-opus" for a different role
```

`config.py`'s validation for a non-built-in name changes from "must set `adapter = \"generic\"`" to
"must set `adapter` to `\"generic\"` or a name in `adapters.BUILTIN`". When it names a built-in
adapter, that name's `default_command` and all managed behavior (login check, bypass-flag refusal,
denial parsing) come from the real adapter; only `command` (if given) and `model` (if given)
override the default. `Adapter` gains `model_flag: tuple[str, ...] | None`:

- `codex`: `("--model",)` (`codex exec -m/--model <MODEL>`, confirmed via `codex exec --help`).
- `claude`: `("--model",)` (confirmed via `claude --help`; accepts an alias like `opus`/`sonnet`/
  `haiku`/`fable` or a full model name).
- `generic`: `None` — a generic agent's command is opaque; if you want to pin its model, put the
  flag directly in `command` yourself, the same way you already can today.

No model string is validated against what an account can actually use (non-goal, section 2); an
invalid or unavailable model fails at run time, surfaced the same way any other agent failure is.

### 5.10 Setup and ongoing changes

- **`init`** asks about every role a `[pipeline]` (or the legacy pair, if none) defines: which
  agent, and optionally which model, writing `[agents.<name>]` blocks and `[roles]` entries as
  needed — the same write-only-what's-needed discipline `init` already has for permission files.
- **`whyline-relay roles set <ROLE> [--agent NAME] [--model NAME]`**, extending the `roles` command
  family shipped in 0.2.4 (`status`, `reset`): writes a **permanent** change to `[roles]` (and, if
  `--model` is given for a name not yet configured, a new `[agents.<name>]` block), distinct from
  `reset`, which only clears a *temporary* failover override. Called with no flags for a role,
  it prompts interactively for agent and model instead of requiring the exact TOML shape by hand.
  Refuses, with the same validation `config.load` already applies, if the named agent doesn't
  resolve to a built-in adapter or an already-configured generic one.

## 6. Build order

Each phase gets its own implementation plan and relay-driven build, the same way the adapters and
failover pieces did. Order matters for dependency reasons noted:

0. **Model selection alone (D10)**, against today's unchanged two-role model. No dependency on
   anything else in this document; ships fastest and is independently useful.
1. **The `Role`/`Stage`/`Profile` engine and the compiled legacy pipeline (D1-D3, 5.1, 5.3).**
   Regression net: the entire existing suite and every existing acceptance suite pass unedited with
   no `[pipeline]` configured anywhere.
2. **Crash-safe stage cursor and resume (D8, 5.4).** Depends on 1.
3. **Profiles and optional stages (D5, 5.5).** Depends on 1.
4. **Relay-side commit ownership for a configured pipeline (D6, 5.6).** Depends on 1 and 2 (must be
   resumable across a crash between approval and commit).
5. **Tester and security-review as real stages, with their prompts and the protocol footer (D9,
   5.7, 5.8).** Depends on 1, 3, 4.
6. **`init` and `roles set` (D11, 5.10).** Depends on 1 (needs the role/stage vocabulary to ask
   about) and 0 (needs model selection to exist to ask about it).

## 7. Risks and open questions

- **The crash-safety design (5.4) is the least proven part of this document.** Neither consultation
  nor this design session actually built and interrupted a running pipeline mid-stage; the exact
  ordering of "checkpoint, then launch" needs a real test that kills the process at each of several
  points and confirms resume never double-consumes a handoff or loses the paused stage.
- **Model string validity is entirely unmeasured** (non-goal, section 2). A future piece D would
  need to establish whether any of these tools can report which models an account can actually use.
- **The protocol-footer change to prompts (5.7)** is a bigger behavioral change to how instructions
  reach an agent than anything shipped so far; it needs its own careful acceptance testing that a
  configured pipeline's agent actually produces the exact handoff the footer specifies, the same way
  the adapters work proved role names render correctly.
- **Release**: this is large enough that it should not be one relay run. Each build-order phase
  (section 6) ships as its own version, following the same measured-not-guessed release discipline
  as every prior piece.

## 8. Roadmap update

Section 8 of the failover design named this piece "A" and scoped it to the state machine alone.
This design session broadened it to also include model selection (D10-D11), since building one
turned out to need the same config generalization as the other. The rest of that roadmap is
unchanged: **D** (subscription-aware setup) and **C** (first-run interactive setup beyond what 5.10
already covers) remain separate, harder, and explicitly deferred; **E** (planner, with its
human/auto review gate) is now more concretely scoped — it reuses this design's `Stage`/`Profile`
engine as an outer workflow, not a per-task pipeline stage; **F** (tester) and **G** (documentation,
security-review) are substantially specified already by 5.8 and just need their prompts and
acceptance tests written when their turn in the build order (section 6, phase 5) comes.

## 9. Decision log (this design session, 2026-09-22–23)

| Question | Answer |
|---|---|
| Include Codex and Antigravity as real consultants, not just Claude's own analysis? | Yes — both run for real, read-only, against this repository |
| Internal model: three concepts (Role/Stage/Profile) or something simpler? | Codex's three-concept model, adopted |
| Does `Handoff` gain new fields for stage/role identity? | No — unchanged; new state lives relay-side (Codex) |
| Optional stages: named profiles, or free-form skip tags? | Profiles (Codex), over Antigravity's skip-tags |
| Who commits in a configured pipeline: the relay, or a designated agent stage? | The relay itself (Codex), over Antigravity's `can_commit` stage |
| Does rejection ever autonomously reach the planner? | No — always blocks for a human instead (both agreed) |
| Which candidate roles get first-class stages? | Tester yes, documentation no, security-review yes-but-optional, planner not-a-per-task-stage (both agreed) |
| Should per-role model selection exist, and how? | Yes — agent variants (`adapter` decoupled from literal name) plus `model`, verified against real `--model` flags on all three CLIs |
| Is there an "auto" mode that picks a model for you? | No — a model must be fixed before the process starts; omitting it is already "auto" in the only sense that applies |
| Wizard now, or wait for the full subscription-aware setup? | Now, for asking and writing the choice; subscription-awareness itself stays deferred and unmeasured |
| Build order | Model selection first (independent, fast) → the engine and legacy compatibility → resume → profiles → relay-commit → tester/security stages → init/roles set |
