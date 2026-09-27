# Grok Plan for Enhancement

**Status:** suggested. Written 2026-09-26. Not approved. Do not execute this file as an implementation plan.

This is the brainstorm for one enhancement: you sit in one terminal inside the project, Whyline decides which named workflow runs, the coding agents do the thinking, and the relay's existing state machine decides whether the loop may continue. Voice is how you answer when that loop stops.

Each phase below is a separate spec and a separate implementation plan. This document picks the approach, the order, and the boundaries. It does not contain tasks an agent should start coding.

**Depends on, and does not replace:**

- `docs/superpowers/specs/2026-09-26-chat-repl-design.md` (approved). Decision D3 stands until Phase 4 explicitly offers an opt-in override.
- `docs/superpowers/specs/2026-09-20-whyline-relay-design.md`. The agent writes the handoff. The relay routes on a new event id. It does not infer a verdict from output.
- `docs/superpowers/specs/2026-09-23-relay-n-roles-design.md`. Named profiles. The relay commits after approval on a configured pipeline. No two processes share one working tree.
- The 2026-08-22 decision: Whyline itself does not schedule agents. That decision stays true.

## 1. What you asked for

You want to stop opening Claude and invoking Whyline from inside it. In the project directory you start Whyline. That session is the control plane. From the words of the request it chooses the next workflow and the agents. Later, a small local model can make that choice. A hosted classifier (Jev) can make it before the local model exists. When a run is blocked, the terminal can speak the question and take the answer by voice.

## 2. What this plan assumes

Correct these before treating the plan as accepted.

- Local-only stays the default. No account, no telemetry, no uploaded prompts, no source files sent anywhere, unless you opt into one named provider.
- Whyline core keeps the record, `whyline run`, and the thin launcher. Orchestration stays in whyline-relay.
- The router chooses a **named profile** that already exists in relay config. It does not invent a team of six roles per sentence.
- The only execution mode is sequential. A parallel label is not emitted, because the relay cannot run two agents on one tree.
- There is no committer role. On a configured pipeline the relay commits, as N-roles decision D6 already says.
- The classifier never judges whether the code is correct, whether tests passed, or whether a commit exists.
- Voice is the human channel for a pause and an optional input method for chat. It is not an always-on microphone, and agents never open the mic or the speaker.
- Chat decision D3 (fixed default agent, no content-based routing) remains the default. Routing is a switch you turn on.

## 3. Approaches

### A. Jev assembles a new team for every request

One classifier call returns workflow, planner, orchestrator, developer, tester, reviewer, committer, and sequential-or-parallel. Whyline executes that graph. A second call assigns roles again after brainstorming.

This matches the largest version of the discussion. It also throws away profiles, the relay-commits rule, and the ban on shared-tree parallelism. A typo can be assigned a six-agent pipeline whenever the probability vector is confident and wrong. A hosted call sees whatever context you put in the request. Rejected as the shape to build.

### B. Rules only, forever

Keep today's relay: a human writes `plan.md` and names a profile per task. No classifier, no voice.

This is the system that already works, and it is the right default behavior. It does not answer the request. You would still choose the workflow yourself, and a blocked run would still wait until you notice the terminal. Rejected as the whole enhancement. Kept as the provider that ships first and as the fallback for every later provider.

### C. Recommended. A profile router with three providers, and voice on the pause

```
you, in one terminal
        |
        v
whyline  --->  whyline-relay chat          (already specified)
                    |
                    |  routing off: text goes to the fixed default agent
                    |  routing on:  text goes to the router
                    v
              route(task) -> Proposal
                    |
        +-----------+-----------+
        |           |           |
      rules        jev        local
     (default)   (opt-in)   (only after
                             labeled logs)
                    |
                    v
         named profile: direct | plan | full
                    |
                    v
            you confirm (v1 always)
                    |
                    v
         existing relay state machine
         handoff id, git, tests, visit caps
                    |
              pause with a question
                    |
                    v
         print it; optionally speak it
         answer by keyboard or push-to-talk
         write the answer where the next
         fresh process will read it
```

The router decides where thinking should happen. Claude, Codex, Antigravity, and Grok do the thinking. The relay decides whether the loop may continue. Jev is one provider behind a protocol, not the orchestrator.

## 4. Decisions this plan locks

| # | Decision | Why |
|---|---|---|
| E1 | Enhancement work lives in whyline-relay, except Phase 0 | Whyline's published job is the record and the exec handoff. The 2026-08-22 decision stays literal. |
| E2 | The router returns one profile name plus a confidence and the rule or provider that produced it | A profile is a reviewable object in `config.toml`. A free role vector is not. |
| E3 | v1 profiles are exactly `direct`, `plan`, and `full` | `direct` is the legacy implement-then-review pipeline. `plan` runs the existing planner workflow, then that pipeline. `full` is the configured pipeline whose profile includes tester or security-review. No fourth name until a phase ships the machinery for it. |
| E4 | If the chosen profile is not configured in this repo, the router falls back to `direct` and says so | A missing profile must not be a silent skip and must not be an error that blocks a typo fix. |
| E5 | v1 always asks you to confirm. An auto threshold exists in the config and defaults to off | An uncalibrated probability is not a probability yet. Confirmation is also how the training label is born: what you accepted, not what the model proposed. |
| E6 | Routing off is the chat default, preserving D3 | Turning on content-based routing is a config flag, `[routing] enabled = false` by default. `/claude`, `/codex`, `/agy`, `/grok` still send one turn to that agent either way. |
| E7 | Provider order of failure is local or jev, then rules | A network error, a missing key, or a local-model failure prints one line and uses the rules provider. The session does not stop. |
| E8 | The Jev request body is the task text, the profile vocabulary, which agent binaries exist, and coarse repo facts (file-extension counts, task length). No file contents, no diffs, no prompts from other agents | Source leaving the machine is a new data path. The router does not need it to pick a profile. |
| E9 | The route log is gitignored, local, and never uploaded | Same category as `chat-history.jsonl`. Collecting it for a future model is not telemetry. |
| E10 | Voice defaults off. When on, it speaks only a pause question, a block, and completion. Push-to-talk is the only listening mode | An open microphone records the room and would drop that audio into an agent prompt. |
| E11 | A spoken or typed answer is stored in `.whyline/relay/answer.json` and injected into the next stage prompt. `whyline resume` already starts a fresh process; it has no live session to receive a reply | Confirmed in whyline-relay `cli.py`: `resume` takes no answer argument. N-roles D4 also forbids inventing handoff fields for this. |
| E12 | The local model is not scheduled until the log holds at least 200 rows that have both an accepted profile and a finished outcome | Fewer rows trains a copy of the rules or of Jev. The useful label is your override plus whether a later stage sent the task back. |

## 5. Phases

### Phase 0 — Stop a finished handoff from hiding history

**Repo:** whyline. **Do this before any router**, because the control plane reads `whyline sync`, and sync currently lies.

Observed on this checkout on 2026-09-26: `whyline sync` printed an active handoff for `WL-0.2.0` with status `closed`, then "Relevant decisions (2 of 2 for task WL-0.2.0; 85 recorded in total)." `sync._state` treats any active-handoff task as an explicit task filter. `brief.select_entries` then drops every other decision before the token budget runs. A decision from 2026-08-31 already says that handoff was closed so later sessions would not re-review shipped work. The code still presents it as active.

Build:

- Statuses `closed`, `done`, `complete`, and `approved` are terminal for inference. `sync` prints one line, `Last handoff: <task> (<status>)`, and does not use that record as the task filter. `approved` belongs on this list because both the legacy relay and a configured pipeline write it when a task is finished, and whyline never clears `active-handoff.json` afterward. The relay's own prompts call `whyline sync --task <id>` (`whyline_relay.whylinecmd.sync`), so they keep the narrow packet. `blocked`, `ready-for-review`, `changes-requested`, and `assigned` stay active: a pause is the thing the next session must see.
- A task inferred from a non-terminal handoff ranks that task's decisions first and then fills the budget with the rest. `whyline sync --task` still narrows, because that is the caller asking.
- Tests cover a closed handoff with 3 decisions on that task and 10 on others: the closed case shows the others; an `approved` handoff does the same; a `blocked` handoff still ranks that task first and keeps the rest while budget remains; `--task` still narrows even when the stored status is `approved`.

This phase gets its own short implementation plan after you accept this document. It does not wait for the relay work.

### Phase 1 — Land the chat control plane as already specified

**Repo:** whyline-relay, plus the thin `whyline` launcher the chat spec already describes.

No new design. `docs/superpowers/specs/2026-09-26-chat-repl-design.md` is the spec: bare `whyline` execs into `whyline-relay chat` when the relay is installed, one fixed default agent, slash commands for the others, shared transcript, existing permission floor.

This enhancement does not reopen D3, D5, or D6 while Phase 1 is being built. The router is a later flag on top of that REPL, not a reason to change the REPL's first version.

Exit: you can `cd` a repo, run `whyline`, and talk to the default agent without opening a vendor terminal.

### Phase 2 — Rules router

**Repo:** whyline-relay. First new feature in this enhancement.

A pure function, no I/O:

```python
@dataclass(frozen=True)
class Facts:
    task: str
    profiles_available: tuple[str, ...]  # subset of direct, plan, full
    agents_installed: tuple[str, ...]

@dataclass(frozen=True)
class Proposal:
    profile: str          # direct, plan, or full
    confidence: float     # rules always returns 1.0
    provider: str         # "rules"
    reason: str           # one sentence naming the rule that fired
    fell_back: bool       # True when the preferred profile was not configured

def route_rules(facts: Facts) -> Proposal: ...
```

Rules, in order, first match wins:

1. The task text names a profile (`profile: full`, or a leading `/profile full`). Use it. This is how you override without a classifier.
2. Word count under 25, and none of the verbs in rule 3, and the word `security` is absent. Profile `direct`. Reason: short task with no design verb.
3. The text contains a design verb: `design`, `architecture`, `redesign`, `migrate`, `migration`, `plan`, `brainstorm`, `rfc`. Profile `plan` if `plan` is available, else `direct` with `fell_back=True`.
4. The text contains `security`, `auth`, `oauth`, `passkey`, or `credential`. Profile `full` if available, else `plan` if available, else `direct`, with `fell_back=True` whenever the first choice was missing.
5. Otherwise `direct`.

`brainstorm` is only a verb that selects the `plan` profile. There is no brainstorm profile until a later spec adds a second proposer to the planner. Saying brainstorm and running the existing planner is the honest behavior.

Command, outside chat:

```
whyline relay route "Redesign auth to add OAuth"
```

Prints the proposal and asks `Run profile plan? [Y/n]`. Enter accepts. `n` asks which profile. Nothing launches until an answer. `--yes` accepts the proposal for scripts.

Inside chat, only when `[routing] enabled = true`:

- Ordinary text is routed, the proposal is printed, and the same confirm prompt runs.
- `/claude` and the other slash commands bypass the router.
- `/route off` and `/route on` flip the flag for this session and persist it in `.whyline/relay/routing.json` (gitignored, same list as `chat.json`).

On accept, chat does not invent a new runner. It writes a one-task plan in the relay's existing plan format and calls the existing start path with that profile. The task text is the user's sentence. The profile is the confirmed one.

Log, append-only, gitignored at `.whyline/relay/route-log.jsonl`:

```json
{"ts":"...","task":"...","proposed":"plan","accepted":"direct","provider":"rules","reason":"...","fell_back":false,"outcome":null}
```

`outcome` is filled by the relay when that task reaches `@complete` or pauses for a human: `completed`, `rewound` (any stage visited more than once), or `blocked`. The log line is matched by a `route_id` the relay stores in its own state, not by parsing the task text.

Tests: one test per rule, including fallback when `full` is absent; confirm-decline does not start a run; routing off leaves chat behavior identical to the Phase 1 spec; the log file is in the relay gitignore list; a rules proposal never contains a role name, a committer, or `parallel`.

### Phase 3 — Voice on the pause, and push-to-talk in chat

**Repo:** whyline-relay. Independent of Phase 2. Can be specced in parallel once Phase 1 exists. Ships as an optional extra so the relay's default install stays free of audio libraries.

Defaults in config, all safe:

```toml
[voice]
enabled = false
listen = "push-to-talk"   # the only legal value in this phase
tts = "system"            # macOS `say`. Other platforms print the question and skip speech.

[voice.speak]
question = true
blocked = true
completed = true
logs = false              # not configurable to true in this phase
```

Speak path: when `loop.py` raises `Paused` and the reason contains a question (the string `_blocked_reason` already builds), the reporter prints the reason as it does today, and if voice is enabled and `say` is on `PATH`, it runs `say` with that same string, truncated to the 300 characters `_blocked_reason` already uses. Completion uses one fixed sentence: `Task <id> completed.` Agent logs are never passed to `say`.

Listen path: `whyline relay answer` (and the chat prompt, when voice is enabled) waits for the space bar, records while it is held, and transcribes on release. Phase 3 ships the key binding and the file write even if transcription is a separate optional binary.

The transcript is written to `.whyline/relay/answer.json`:

```json
{"route_id": "...", "task_id": "...", "text": "Migrate them. Nothing should be deleted.", "source": "voice"}
```

The next `resume` reads that file once, includes the text in the next stage prompt under a fenced heading `Human answer to the blocked question`, then deletes the file. If the file is absent, resume behaves exactly as it does today. The answer is untrusted data, fenced the same way `whyline sync` fences its packet, and it is not written into `decisions.md` unless an agent later decides it was a real decision.

Speech-to-text is `whisper.cpp` invoked as a subprocess when `WHYLINE_WHISPER` points at a binary. Missing binary: print `Voice input needs WHYLINE_WHISPER; type the answer instead` and accept keyboard input. Whyline does not download a model. No cloud STT provider in this phase.

Tests: voice disabled produces no `say` subprocess (the runner is injected, as `account.detect_claude` already injects its runner); `logs` cannot be set true by config, a bad value is a config error; answer.json is included once and then gone; resume with no answer.json matches current resume; the spoken string never exceeds the pause reason already shown on screen.

### Phase 4 — Jev as an optional provider

**Repo:** whyline-relay. Starts only after Phase 2 has been used enough that the rules are visibly wrong on real tasks, or you explicitly want the experiment sooner. The protocol is fixed in Phase 2, so this phase is a new provider, not a new router.

```python
class Provider(Protocol):
    def propose(self, facts: Facts) -> Proposal: ...
```

`JevProvider.propose` asks one choice question whose options are the profiles actually available in this repo. Confidence is the probability Jev returns for the chosen label. The HTTP shape is taken from Jev's docs at spec time and pinned by a recorded fixture. This plan does not invent the URL.

Config:

```toml
[routing]
enabled = false
provider = "rules"          # rules | jev

[routing.jev]
# key is read from the environment variable WHYLINE_JEV_API_KEY
# the key is never written to config.toml, the route log, or decisions.md
```

Behavior:

- Missing key or any HTTP failure: print the failure in one line, call `route_rules`, set `provider` to `rules` and `fell_back` to true.
- Confidence is stored and shown. It does not skip the confirm prompt. Auto-accept stays off (E5). A later spec may enable auto-accept above a threshold after the log shows that threshold is calibrated. That spec is not this phase.
- The request body obeys E8. A test builds the body from a fixture repo and asserts no file contents appear.

The route log records `provider: jev` and the confidence. Your accepted profile is still the label. Training on Jev's proposal alone is forbidden by the Phase 5 entry condition.

### Phase 5 — Local router, only after the log can teach it

**Not designed in detail here.** Entry condition, all of them:

- At least 200 route-log rows with a non-null `outcome`.
- At least 30 of those rows have `accepted != proposed` or `outcome == rewound`. If overrides are rarer than that, the rules are good enough and a model has nothing to learn.
- The model is a classifier over `direct` / `plan` / `full`. It is not a reviewer, a planner, or a role assigner.
- It runs as `provider = "local"`, fails closed to rules, and stays gitignored including its weights.
- No network at inference time.

Until those rows exist, collecting them is the work. Do not fine-tune a general model in anticipation.

## 6. What a session feels like when Phases 1–3 are in

Routing off, which is the default:

```
$ whyline
> fix the typo in README
[claude] Done.
```

Routing on:

```
> Redesign authentication to support OAuth and passkeys
route  plan   provider rules   confidence 1.0
       design verb "Redesign"; profile plan is configured
Run profile plan? [Y/n] y
```

The relay runs the planner, then the pipeline. A later stage blocks:

```
blocked  Codex
Question: Should existing records be migrated or discarded?
```

If voice is enabled the Mac speaks that question. You hold space, say "Migrate them. Nothing should be deleted.", and release. `resume` starts the next fresh agent with that sentence fenced in its prompt.

A one-line fix with routing on hits rule 2 and proposes `direct`. You press enter. It does not brainstorm.

## 7. Non-goals

- A classifier that answers "is the implementation correct?" or "is the task complete?"
- Completeness as a probability. Complete means the mechanical checks passed and the reviewer stage approved.
- Assigning orchestrator, developer, tester, reviewer, and committer as a free combination.
- `PARALLEL` or `MIXED` execution.
- An always-on microphone, or any agent opening the audio device.
- Sending file contents, diffs, or other agents' prompts to Jev.
- A new shared-core package. The chat spec's D2 still holds.
- Changing whyline's handoff schema.
- Auto-accepting a route in the same release that introduces Jev.
- Training a local model on synthetic labels or on Jev's answers alone.
- Replacing the approved chat REPL with this router.

## 8. Success

- With the extras uninstalled, `whyline run`, `whyline sync`, and a relay that has no `[routing]` table behave as they do today.
- With routing on, a short typo task proposes `direct` and a redesign proposes `plan`, and neither starts until you confirm.
- A repo with no `full` profile proposes `direct` or `plan` and the line says it fell back.
- A paused question can be answered by voice, and the next resume is a new process that received the answer once.
- `git status` never shows `route-log.jsonl`, `answer.json`, or `routing.json`.
- The router output cannot name a committer or a parallel mode. A test locks that.

## 9. Order

1. Phase 0 in whyline. Small, and every later session reads its result.
2. Phase 1 as already specified. The control-plane terminal.
3. Phase 2, the rules router. This is the first enhancement to spec in full.
4. Phase 3, voice, specced in parallel with Phase 2 if you want, merged in either order.
5. Phase 4 only after you have seen the rules miss, or you explicitly choose to experiment.
6. Phase 5 only after the entry condition in that phase.

## 10. Open point

One product choice is still yours: when routing is on, should an accepted proposal start the relay immediately, or should it only print the profile and wait for `whyline relay start`? This plan chooses immediate start after the confirm prompt (section 5, Phase 2), because you asked for the terminal to load the next step. Say if you would rather stop at the printed proposal.
