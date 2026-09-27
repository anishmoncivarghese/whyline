# Codex Whyline Eahnancment

**Status:** Amended brainstorming roadmap, 2026-09-26, after comparison with
`2026-09-26-grok-plan-for-enhancement.md`. No implementation is authorized by
this document. Each release phase gets its own reviewed specification and
implementation plan before code starts.

**Goal:** Make `whyline` the terminal entry point for a local-first coding-agent
control plane. A user describes work once; Whyline either answers through a
chosen agent, drafts a plan, starts a reviewed relay workflow, or asks for human
input. An optional bounded classifier (rules first, hosted Jev experimentally,
and eventually a local model) chooses only among workflows the repository has
already declared. An optional voice layer lets the same human gates be heard
and answered without giving individual agents control of the microphone.

**Repositories:**

- `/Users/anish/agentdock` (`whyline`) remains the thin user-facing launcher,
  history store, and handoff protocol.
- `/Users/anish/whyline-relay` owns chat, classification, subprocess
  supervision, workflow execution, human gates, and voice I/O.

**Depends on:**

- `docs/superpowers/specs/2026-09-26-chat-repl-design.md`
- `docs/superpowers/plans/2026-09-26-relay-chat-repl.md`
- `docs/superpowers/plans/2026-09-26-whyline-chat-delegation.md`
- `docs/superpowers/plans/2026-09-26-grok-plan-for-enhancement.md`
- The shipped relay planner, Role/Stage/Profile engine, model selection,
  adapter layer, crash-safe resume, and relay-owned configured-pipeline commit.

---

## 0. What changed after the Codex/Grok comparison

The Grok plan is adopted as the product-sequencing baseline: fix the stale
handoff context first, ship the already-approved chat REPL unchanged, add a
small rules router that always asks for confirmation, add durable human answers
before voice, then experiment with Jev and a local model. The original Codex
plan remains the source for strict provider validation, privacy tripwires, a
safe ad-hoc task runner, exact-once human responses and measured release gates.

The merged decisions are:

- V1 routing is disabled by default and never auto-accepts a route.
- V1 has four route kinds: `chat`, `work`, `plan`, and `human`.
- `work` carries one logical depth: `direct`, `standard`, or `full`. A repo maps
  those aliases to any configured profile names; the router never requires the
  profiles themselves to be named `direct`, `plan`, or `full`.
- A missing preferred profile never silently falls back to less review. It uses
  an explicitly configured fallback or asks the human.
- Destructive, ambiguous and security-sensitive signals are evaluated before
  task length or design verbs. A short OAuth/credential task cannot route to a
  shallow profile merely because it has few words.
- Deterministic rules report their matched rule, not a fabricated confidence of
  `1.0`. Probabilistic confidence is optional and provider-specific.
- Accepted work uses a dedicated ad-hoc relay workflow. It does not create and
  tick a temporary committed `plan.md`.
- A structured, task/stage-bound human request/response protocol precedes voice;
  a single delete-after-read `answer.json` is not sufficiently crash-safe.
- A separate brainstorm/synthesis workflow and automatic routing are post-v1.
- The local-model experiment may begin after 200 completed observations with
  at least 30 overrides or rewinds. Automatic routing requires the stronger
  500-observation/200-explicit-label gate and its own review.

One real prerequisite discovered by Grok is accepted as a separate Phase 0:
today a stored handoff whose status is `closed` still becomes `sync`'s implicit
task filter and hides unrelated history. The defect is real, but its solution
must define explicit lifecycle semantics; Whyline must not guess that arbitrary
user-defined strings such as `approved`, `done`, or `complete` are universally
terminal.

---

## 1. Brainstorming result

### 1.1 The product shape

```text
                         whyline terminal
                                │
                         user request
                                │
                    explicit /agent or /profile?
                         │              │
                        yes             no
                         │              ▼
                         │       Router provider
                         │     rules | Jev | local
                         │              │
                         └───────┬──────┘
                                 ▼
                       Validated workflow profile
               ┌─────────┬────────┬─────────┐
               ▼         ▼        ▼         ▼
             CHAT       WORK     PLAN      HUMAN
               │         │        │         │
               │    named relay   │     clarification
               │      profile     │       or refusal
               │         │   planner loop
               └─────────┴────────┘
                                 │
                                 ▼
                         Python relay engine
                                 │
                       stages and handoffs
                                 │
                        tests and review
                                 │
                       deterministic commit
                                 │
                    structured human requests
                                 │
                       terminal or voice I/O
```

### 1.2 The boundary that must remain fixed

The relay process is the orchestrator. Claude, Codex, Antigravity, Grok and
future tools are workers filling configured roles. No agent becomes a privileged
controller that recursively launches and supervises the others. This keeps
process ownership, permissions, timeouts, state, handoffs, test exit codes and
Git checks in ordinary code.

The router is also not an orchestrator. It returns a bounded decision; code
validates the result and executes it.

### 1.3 What the router may decide

The smallest useful v1 contract is:

```json
{
  "route": "work",
  "depth": "full",
  "profile": "security",
  "confidence": null,
  "provider": "rules",
  "matched_rule": "security-sensitive"
}
```

Allowed v1 routes:

- `chat`: explanation, exploration or discussion; no autonomous workflow.
- `work`: execute one bounded task through the configured profile mapped from
  logical depth `direct`, `standard`, or `full`.
- `plan`: draft and review a plan, then use the existing human approval gate.
- `human`: the request is ambiguous, destructive, unsupported or too uncertain.

An existing plan or paused run is discovered deterministically before routing:
the terminal offers `resume` or `start` instead of asking a classifier to infer
their existence. A separate brainstorm/synthesis route is deferred until the
core router has real usage data.

The resolved `profile` must name a configured, prevalidated relay profile.
Profiles determine stages; roles determine agents; agent configuration
determines models. The classifier must not construct an arbitrary stage graph,
choose a committer, or weaken a permission floor.

### 1.4 What remains deterministic

The classifier is never asked whether:

- a file changed;
- a command or test passed;
- an agent committed;
- a handoff exists;
- a process timed out;
- the tree is clean;
- a reviewed terminal outcome permits a commit.

Git, subprocess exit status, the relay state machine and Whyline handoffs remain
authoritative. Semantic correctness stays with configured reviewer/tester/
security stages, never with the small classifier.

### 1.5 Manual control always wins

Explicit `/claude`, `/codex`, `/agy`, `/grok`, `/profile NAME`, `/plan` and
`/human` directives bypass automatic classification. The existing fixed default
agent remains usable when routing is disabled. Unknown slash commands fail
without spending an agent or classifier turn.

### 1.6 Router providers

```text
rules  -> local, deterministic baseline and default
jev    -> hosted, opt-in experiment with bounded typed outputs
local  -> future Whyline-specific classifier using the same contract
```

Jev is optional and off by default because it sends data to an external service
and therefore cannot inherit Whyline's local-only promise. It receives only a
minimal routing state by default: the user's request, coarse repository type,
available profiles and available agent/model names. It receives no source,
diff, environment, secrets, full paths, chat history or Whyline decision text.

### 1.7 Confidence policy

`confidence` is advisory and provider-specific. It is not proof of correctness.
Thresholds are calibrated against Whyline's own accepted/overridden routes,
not copied from vendor marketing.

Modes:

- `off`: fixed default/manual routing only.
- `shadow`: predict and record, but never affect execution.
- `suggest`: print the proposed route and ask the human to accept or edit it.

V1 supports only those three modes and always asks before a suggested route is
executed. `auto` is a later, separately reviewed release gated by section 3.3.
`shadow` is the required starting mode for every intelligent provider.

### 1.8 Voice is an interface, not an agent capability

Whyline-relay alone owns microphone and speaker access. Agents emit structured
events; the voice layer may speak only selected event types:

- `human-question`
- `approval-required`
- `blocked`
- `error`
- `task-complete`
- `project-complete`

Normal agent logs and reviews remain text-only. Push-to-talk is the v1 input
mode. A transcript is shown before submission, and consequential answers require
confirmation. Typed input always remains available.

### 1.9 A missing prerequisite for voice

A blocked handoff can contain a question today, but the control plane needs a
durable answer object before voice is useful:

```text
HumanRequest(id, task, stage, kind, prompt, created_at)
HumanResponse(request_id, text, created_at, source)
```

The response must be checkpointed and injected into the exact resumed stage.
Terminal typing and speech-to-text are then two adapters for the same protocol.

### 1.10 Brainstorming is not concurrent editing

**Post-v1 only.** A future `brainstorm` route may gather read-only proposals,
store them as relay artifacts, and give them to a configured synthesizer. No two
agents edit the same working tree concurrently. Until that separately reviewed
workflow exists, a request containing “brainstorm” routes to the existing
planner and is described honestly as planning. If true parallel implementation
is ever wanted, it remains a separate worktree/merge project.

---

## 2. Configuration sketch

```toml
[routing]
enabled = false
provider = "rules"            # rules | jev | local
mode = "suggest"              # off | shadow | suggest; v1 always confirms
fallback_depth = "standard"   # explicit fallback, or omit to ask the human
send_repository_metadata = true
send_source = false            # must remain false for hosted providers in v1

[routing.profiles]
direct = "quick"               # logical depth -> this repo's configured profile
standard = "standard"
full = "security"

[voice]
enabled = false
mode = "push-to-talk"
confirm_consequential_answers = true

[voice.stt]
provider = "command"
command = ["whisper-cli", "--model", "/path/to/model.bin"]

[voice.tts]
provider = "system"

[voice.events]
questions = true
blocked = true
approvals = true
errors = true
completed = true
agent_logs = false
```

Environment-held credentials are used for hosted providers. `init` may explain
the expected variable but never writes a secret into configuration or history.

---

## 3. Data and evaluation

### 3.1 Local routing ledger

Store routing observations in gitignored
`.whyline/relay/routing-history.jsonl`. Default records contain no raw request:

```json
{
  "schema": 1,
  "request_hash": "...",
  "decision": {
    "route": "work",
    "depth": "full",
    "profile": "security",
    "provider": "rules",
    "matched_rule": "security-sensitive",
    "confidence": null
  },
  "mode": "suggest",
  "human_action": "accepted",
  "final_route": "work",
  "final_depth": "full",
  "final_profile": "security",
  "rounds": 2,
  "human_interventions": 0,
  "completed": true,
  "duration_seconds": 612
}
```

The full request may be stored only through a separate explicit opt-in. Secrets
and environment values are never recorded.

### 3.2 Useful outcomes

Collect:

- suggested and final route;
- human accept/override/abandon;
- configured profiles and available agents;
- rounds and stage visits;
- pauses, timeouts and rate-limit failovers;
- test result summaries already known to the relay;
- completion, duration and human intervention count.

Do not treat successful tests alone as a correct routing label. Human override
and retrospective route rating are stronger labels.

### 3.3 Local classifier gate

Do not train or ship a local model until all are true:

- an experiment dataset has at least 200 completed observations and at least 30
  contain an override or stage rewind;
- every target profile has enough examples to evaluate separately;
- a held-out chronological evaluation beats the deterministic rules baseline;
- calibration and failure behavior are measured, not inferred;
- the local provider can abstain and fall back without changing workflow state.

The first local provider may be a conventional classifier. It does not need to
be a generative language model. Shipping it as an automatic router has a higher
gate: at least 500 diverse observations, at least 200 explicit human labels,
and the automatic-routing evaluation in CWE-11.

---

## 4. Implementation plan

Every task below requires tests first, the full suite afterwards, no real vendor
CLI in automated tests, no permission-bypass flags, no `git push`, and no agent
writing a Whyline handoff on another agent's behalf.

### CWE-P0: Define and fix terminal handoff lifecycle in Whyline

**Repo:** whyline, not whyline-relay.

Write a short specification before implementation. Define how a handoff becomes
historical without classifying arbitrary user-defined status strings. Then fix
`sync` so a historical handoff can still be displayed as the last handoff but
cannot silently narrow decision history to its old task. A live inferred task
ranks its decisions first and fills remaining budget with other history; an
explicit `whyline sync --task ID` continues to narrow exactly as requested.

The lifecycle specification must also define the producer side, not only how
`sync` reads today's stale `closed` record:

- Whyline gains an explicit, idempotent close/archive operation bound to the
  active handoff's event id. It moves or marks that exact record as historical;
  it does not manufacture another agent handoff and does not infer lifecycle
  from `status` text.
- `sync` distinguishes `Active handoff` from `Last handoff`. Only the former may
  supply an inferred task. A last/historical handoff is display context only.
- whyline-relay calls the explicit close/archive operation after a task's
  terminal handoff has been verified and all success-side Git work for that task
  is durable. A successful legacy `approved` handoff and any configured
  pipeline's custom terminal outcome therefore become historical without
  Whyline knowing either status vocabulary.
- The spec fixes crash ordering and retry semantics: closing the same event is a
  safe no-op; closing a different/newer event is refused; a crash cannot archive
  the handoff before its commit/tick is durable or leave a completed task as the
  next session's active context indefinitely.
- Existing checkout-local records get an explicit migration path. The migration
  may recognize this repository's known `closed` record once, but normal runtime
  behavior never grows a magic list of terminal strings.

**Acceptance:** Tests cover the stored closed WL-0.2.0 shape, a live blocked
handoff, an explicit `--task`, limited token budget, and an unknown custom status.
The test must prove unrelated history is visible after closure without treating
unknown statuses as terminal by guesswork. Cross-repository acceptance tests
prove a successful relay task archives its exact terminal handoff and a paused
task leaves its handoff active.

### CWE-0: Ship and verify the terminal chat prerequisite

**Scope:** Complete the two already-approved chat implementation plans without
folding router or voice behavior into them.

**Acceptance:**

- Bare `whyline` starts `whyline-relay chat` when installed.
- Manual agent prefixes, fixed default, shared capped history and existing
  permission floors work as specified.
- Current chat and relay regression suites pass.
- The real smoke test in the chat plan is completed before routing work starts.

### CWE-1: Router contracts and validation

**Create in whyline-relay:** `router.py`, `tests/test_router.py`.

Define immutable `RouteRequest`, `RouteDecision`, `RouteContext`, provider
protocol and validation errors. A decision is valid only when its route/depth is
known, its logical depth maps to a configured profile, any confidence supplied
is finite and within `[0, 1]`, and the requested mode is configured. Rules use
`confidence=None` and expose their matched rule. Validation failures abstain;
they never launch a workflow.

**Acceptance:** Exhaustive unit tests for valid decisions, unknown profiles,
NaN/infinite confidence, malformed providers and abstention.

### CWE-2: Privacy-bounded context builder

**Create:** `routing_context.py`, `tests/test_routing_context.py`.

Build context from the user request, repository stack, clean/dirty state,
existing plan presence, configured profiles, installed/configured agents and
selected models. Hosted context excludes file contents, diffs, decisions,
history, environment values and absolute home paths.

**Acceptance:** Tripwire tests seed secrets in files, environment, decisions and
chat history and prove hosted context contains none of them.

### CWE-3: Deterministic rules provider

**Create:** `routers/rules.py`, `tests/test_router_rules.py`.

Implement the local baseline with explicit, reviewable, first-match rules in
this safety order:

1. Explicit agent/profile/route directive: honor it after validation.
2. Destructive, ambiguous or unsupported request: `human`.
3. Security, authentication, OAuth, passkey, credential, secret or permission
   signal: `work/full`.
4. Architecture, redesign, migration, RFC or explicit planning signal: `plan`.
5. Explicit discussion/explanation/question: `chat`.
6. Small bounded change: `work/direct`.
7. Otherwise: `work/standard`.

Task length never outranks a risk signal. A missing preferred profile uses only
the explicitly configured fallback; without one the result is `human`, never a
silent reduction in review depth. Rules expose the matched rule and do not emit
a probability.

**Acceptance:** A fixed evaluation fixture covers trivial, ordinary,
architecture, migration, security, destructive and ambiguous requests.

### CWE-4: Routing configuration and status

**Modify:** relay config, init, doctor and CLI.

Parse the configuration sketched above. `doctor` validates providers, modes,
logical-to-configured profile mappings, fallback depth and required environment
variables.
Provide `whyline-relay route "<request>"` and `route --json`; neither launches an
agent or changes Git.

**Acceptance:** `route` is pure/read-only, works without network for `rules`,
and fails closed for invalid configuration.

### CWE-5: Local routing observation ledger

**Create:** `routehistory.py`, `tests/test_routehistory.py`.

Append schema-versioned, atomic local observations; tolerate corrupt individual
lines when reading; support an export that excludes raw prompts by default.
Add `routing-history.jsonl` to relay-owned ignore state.

**Acceptance:** No routing history can enter a relay task commit, and concurrent
or interrupted append behavior does not corrupt earlier records.

### CWE-6: REPL route suggestion and manual overrides

**Modify:** chat REPL after CWE-0.

Add `/route`, `/profile`, `/routing off|shadow|suggest`, and a visible route
proposal. Explicit agent/profile directives always win. In `shadow`, the route
is recorded but the fixed default remains authoritative. In `suggest`, the
human accepts, edits or cancels before anything launches. V1 has no auto mode.

**Acceptance:** Unknown slash commands and rejected proposals consume no agent
turn; restart preserves chosen routing mode without storing secrets.

### CWE-7: Single-task relay execution

**Goal:** Give a routed `work` decision a safe execution path that uses the
existing pipeline rather than chat's unreviewed per-turn auto-commit.

Add an ad-hoc task workflow that constructs a synthetic, persisted task from the
user request, selects one configured profile, runs the existing Stage/Profile
engine, and lets the relay commit only after the profile reaches its terminal
accepted outcome. It must not create or mechanically tick a committed `plan.md`.
Crash-safe resume must preserve task id, request, profile, stage, consumed
handoff and pipeline fingerprint.

This is a new entry point, `run_ad_hoc_task`; it must not call `run_plan` or
`_run_plan`, because both are plan-file loops and `_run_plan` unconditionally
calls `_tick_and_commit` after success. Persist the synthetic task and cursor in
gitignored `.whyline/relay/ad-hoc-state.json` (or an equivalently separate,
typed state record) rather than putting a fake path into `RelayState.plan`.
Preflight for this mode validates repository, branch, tree, profile, prompts and
agents but does not require a plan file. Execution calls the existing single-task
stage engine directly. On terminal acceptance it verifies/creates the same
configured-pipeline work commit, archives the terminal handoff per CWE-P0,
clears ad-hoc state, and returns; there is no checkbox and no tick commit.

**Acceptance:** HEAD checks, handoff provenance, visit caps, dirty-tree checks,
configured-pipeline relay commit and resume behave identically to plan tasks.
A tripwire replaces `_tick_and_commit` with an exception and proves every ad-hoc
start/resume/success path completes without calling it. Tests also prove no
`plan.md` or synthetic task file appears in Git status or task commits.

### CWE-8: Connect decisions to workflows

Map validated v1 routes:

- `chat` -> ordinary REPL turn;
- `work` -> CWE-7 ad-hoc workflow;
- `plan` -> existing planner workflow;
- `human` -> no launch, print the clarification need.

Before calling the router, deterministic code checks for a paused run or an
existing plan and offers the existing resume/start path. A classifier never
decides whether those artifacts exist.

No decision may silently change branches or bypass existing preflight checks.

**Acceptance:** Integration tests fake every provider and subprocess; each route
reaches exactly one expected workflow and all invalid decisions launch nothing.

### CWE-9: Deferred read-only brainstorm and synthesis workflow

**Post-v1; do not start until the rules router and ad-hoc workflow have real
usage.** Add a separate outer workflow: configured proposal agents inspect the repository
without editing, responses are captured as local artifacts, a synthesizer drafts
one plan, the existing planner reviewer checks structure, and the existing human
approval gate decides whether `plan.md` is written. Run proposal agents
sequentially in its first release.

**Acceptance:** Any proposal-stage file or HEAD mutation pauses; disagreement is
preserved in the synthesis input; no plan or commit exists before approval.

### CWE-10: Optional Jev provider in shadow mode

**Create:** `routers/jev.py`, `tests/test_router_jev.py`.

Use a small injectable HTTP client surface and the bounded question types the
provider documents. Batch questions sharing the same state. Apply short timeout,
response-size limit, strict schema validation, retry only documented transient
statuses, and circuit-break repeated failure to the configured fallback. Read
the key only from an environment variable.

Jev first ships only in `shadow`. Moving it to `suggest` requires a reviewed
fixture against the live provider contract and preserves the mandatory human
confirmation. Enabling `auto` is a separate post-v1 release held for CWE-11's
measured gate.

**Acceptance:** Tests cover success, malformed JSON, unknown choice, timeout,
rate limit, overload, missing key, secret-exclusion tripwires and fallback.

### CWE-11: Post-v1 confidence-gated automatic routing

Build an offline evaluation command comparing provider decisions with explicit
human final routes. Report coverage, override rate, per-profile precision,
abstention and calibration buckets. Do not enable `auto` until a documented
sample passes thresholds fixed before evaluation.

Initial proposed release gates:

- at least 500 diverse routing observations;
- at least 200 explicit accepted/overridden labels;
- at most 5% harmful under-routing on `security`/`full` labels;
- at least 80% acceptance above the proposed auto threshold;
- 100% abstention/fallback on provider errors and invalid outputs.

Thresholds may change before collection begins, not after seeing the result.

### CWE-12: Structured human request/response state

**Create:** `humanio.py`, persistent local state and tests.

When planner, workflow or reviewer needs input, save `HumanRequest` before
notifying. Add terminal commands to inspect and answer the active request. Save
`HumanResponse` atomically and inject it once into the exact resumed stage,
tracking consumption so a crash cannot apply it twice.

This protocol explicitly replaces the synchronous `input()` calls in
`planner._human_gate`, not merely wraps them. When the planner reaches
`PlanState.stage == "@complete"`, it persists an approval `HumanRequest` before
reading the terminal. An interactive CLI may immediately collect and persist a
response, but EOF/no terminal leaves the draft and plan state paused at the
approval gate; it must never take the current `except EOFError: answer = "d"`
path that discards the session. “Request changes” creates a second bound request
for feedback. “Replace existing plan?” and “start now?” are likewise represented
as explicit gates or deliberately remain synchronous only when an interactive
terminal is present—the phase specification must choose and test one behavior.

The same mechanism later represents questions from blocked task stages. A
response carries request id, task id, stage/profile identity, source and a
fingerprinted prompt/question. Resume checkpoints consumption before launching
the fresh agent and retains enough state to distinguish “not yet injected” from
“injected, agent outcome not yet consumed” after a crash.

**Acceptance:** Stale, mismatched and duplicate answers are refused; resume after
a crash consumes the answer exactly once; answer text is fenced as untrusted.
EOF at every planner gate preserves the draft and a resumable pending request;
an acceptance test proves it can no longer discard the draft.

### CWE-13: Voice provider contracts and system TTS

**Create:** `voice.py`, `tests/test_voice.py`.

Define STT/TTS provider protocols and event filtering. Implement best-effort
macOS system TTS first, with Linux/unknown platforms returning a clear
unsupported result rather than failing the relay. Speech subprocess failures are
never fatal to the workflow.

**Acceptance:** Only configured event types are spoken; agent logs and untrusted
text cannot be interpreted as shell or AppleScript; no real audio runs in tests.

### CWE-14: Push-to-talk external STT

Implement an optional command-based recorder/transcriber adapter suitable for a
local `whisper.cpp` installation. Whyline does not download models silently.
Setup reports the expected executable/model and microphone permission. Record to
a private temporary file, delete it after transcription, show the transcript,
and require confirmation for consequential answers.

**Acceptance:** Ctrl+C terminates recorder/transcriber process groups and removes
temporary audio; an unavailable STT provider leaves typed interaction working.

### CWE-15: Voice human-gate integration

On selected `HumanRequest` events, speak a compact question, enter push-to-talk,
show the transcript and persist the confirmed `HumanResponse`. Completion and
error events may be spoken without opening the microphone. Never let an agent
activate voice directly.

**Acceptance:** End-to-end fake-provider tests cover question, correction,
confirmation, resume, timeout, silence, cancellation and typed fallback.

### CWE-16: Local classifier provider experiment

After the data gate in section 3.3, implement `routers/local.py` behind the same
contract. Keep model acquisition explicit, checksummed and optional. Benchmark
cold start, memory, latency, classification quality and calibration against both
rules and the shadow Jev data. A regression or missing model falls back safely.

**Acceptance:** The local provider works with network disabled, never generates
text, abstains when uncertain and can be removed without changing stored plans,
handoffs or workflow state.

### CWE-17: Release hardening and real smoke tests

Run separate, watched smoke tests for:

1. fixed-default/manual chat;
2. rules suggestion accepted and overridden;
3. ad-hoc standard workflow with real implementer/reviewer;
4. planner route and human approval;
5. Jev shadow failure with rules fallback;
6. blocked workflow answered through terminal human I/O;
7. push-to-talk blocked question on macOS;
8. restart/resume at every persisted decision point.

The release gate audits built artifacts for home paths, raw routing prompts,
audio, credentials and local histories. Documentation must distinguish local
rules/local-model behavior from hosted Jev behavior and state that routing
confidence is not correctness.

---

## 5. Release sequence

The task numbers group related work; they are not permission to implement all
seventeen in one release. Ship in these gates:

1. **Phase 0 — context correctness:** CWE-P0 only.
2. **Phase 1 — terminal control plane:** CWE-0 only, following the already
   approved chat plans without router changes.
3. **Phase 2 — confirmed rules routing:** CWE-1 through CWE-8 except deferred
   CWE-9. This is the first enhancement release and always asks before running.
4. **Phase 3 — human channel and voice:** CWE-12 through CWE-15. Structured
   exact-once keyboard answers ship before speech input.
5. **Phase 4 — hosted experiment:** CWE-10 in shadow mode, then suggestion mode
   only after its live contract fixture and privacy audit pass.
6. **Phase 5 — evidence-dependent work:** CWE-9, CWE-11 and CWE-16 only after
   their usage/data gates. None belongs to v1.
7. **Release hardening:** the applicable CWE-17 smoke tests run at every phase,
   not only at the end of the whole roadmap.

---

## 6. Explicit non-goals for the first release

- Jev or a local classifier judging implementation correctness.
- Automatic free-form workflow graph generation.
- Automatic route acceptance.
- A distinct multi-agent brainstorm/synthesis workflow.
- An LLM acting as the process supervisor.
- Parallel writers in one working tree.
- Always-listening microphone or wake word.
- Speaking full agent logs or diffs.
- Cloud speech as a required dependency.
- Training a generative model from scratch.
- Sending repository source or Whyline history to a hosted router.
- Automatically pushing, merging or deploying completed work.

---

## 7. Principal risks

| Risk | Mitigation |
|---|---|
| Under-routing complex work into a cheap profile | Risk-first rules, logical profile mappings, no silent downgrade, mandatory confirmation in v1 |
| Hosted-router privacy leak | Minimal context builder, tripwire tests, explicit opt-in, no source/history in v1 |
| Provider confidence mistaken for correctness | Own calibration data, abstention, deterministic verification and semantic review remain separate |
| Chat auto-commit bypasses review | Routed coding work uses the ad-hoc relay pipeline, not an ordinary chat turn |
| Agent-as-orchestrator loses control/provenance | Python relay exclusively owns subprocesses, transitions and state |
| Voice answers the wrong paused task | Request ids, task/stage binding, exact-once consumption and confirmation |
| Speech transcription changes meaning | Display/edit transcript; reconfirm consequential answers; typed fallback |
| Local model increases install weight | Optional external/checksummed asset; rules provider always works without it |
| Outcome data encodes bad labels | Prefer human override/rating, evaluate chronologically, compare with rules baseline |
| New router breaks existing users | Routing disabled by default; manual fixed-default chat remains behaviorally unchanged |

---

## 8. Definition of success

The enhancement succeeds when a user can open one terminal in a repository and
say or type a request once; Whyline visibly chooses or proposes a reviewed
workflow; ordinary code—not an LLM—executes and checkpoints it; explicit tests,
Git state and reviewer outcomes determine progress; uncertain or consequential
choices reach a durable human gate; and the same interaction remains fully
usable with routing, network and voice all disabled.
