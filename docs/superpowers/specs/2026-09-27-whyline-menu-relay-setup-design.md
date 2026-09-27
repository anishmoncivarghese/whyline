# Whyline Entry Menu and Relay Setup Wizard Design

**Status:** Approved by user, section-by-section, 2026-09-27.

## Goal

Bare `whyline` asks "Chat or Relay?" instead of jumping straight into chat.
Choosing Chat optionally lets you set a model first. Choosing Relay walks
you through using or drafting a plan, assigning implementer/tester/reviewer,
and running `doctor`'s existing correctness checks — refusing to offer
`start` until they pass — closing the exact gap that prompted this: no
guided path from "I have a plan" to "it's safely running unattended."

## Non-goals

- **Replacing `doctor`'s checks with something new.** `doctor` already
  validates every role has an agent, every stage's prompt exists, every
  agent is installed and logged in, and every `relay-profile:` annotation is
  valid. This design reuses those checks completely unchanged — the new
  work is the guided flow *around* them, not a new validation engine.
- **A fully open-ended pipeline builder.** The wizard offers exactly one
  fixed template — implementer → tester → reviewer, matching the README's
  own already-documented example — not arbitrary custom stages or
  transitions. Anything more exotic still means hand-editing `config.toml`.
- **Chat gaining per-agent model flags.** The Chat path's "set a model
  first" option delegates to the existing, unchanged `whyline model`
  command; chat's own turn pipeline does not gain new model-selection
  mechanics.
- **A content/quality review of plan text.** Explicit user choice: the
  correctness review is the existing structural `doctor` checks, not an
  agent judging whether task instructions are well-written.

## Decisions

- **M1 — The menu lives in whyline, not whyline-relay.** Bare `whyline`
  (no args) prompts `Chat or relay? [chat]:` before doing anything else. If
  `whyline-relay` isn't installed (checked via the same `which` used today),
  the menu is skipped entirely and `whyline` falls straight through to its
  existing usage output — this is a strict superset of today's behavior for
  anyone not using the relay side.
- **M2 — Chat's model sub-choice runs as a real subprocess, not an exec.**
  `os.execvp` replaces the process and never returns, so a step that must
  finish and hand control back (running `whyline model` interactively, then
  proceeding to chat) has to be a blocking `subprocess.run` inheriting the
  terminal, not part of the exec chain. Only the final step — into
  `whyline-relay chat` — is a real exec, exactly as today.
- **M3 — Relay asks "use existing plan, or draft one?" explicitly**, rather
  than silently assuming either (explicit user choice, given twice: option A
  assumes one exists, option B offers to draft — the user wants both
  offered as a real choice each time). "Draft" calls the existing
  `whyline-relay plan "..."` planner workflow, unchanged.
- **M4 — The role wizard writes one fixed template.** Three questions
  (implementer / tester / reviewer), each defaulting to the role's existing
  `Roles`/`DEFAULTS` value. Output is byte-for-byte the README's own
  documented 3-stage example (`draft`/`test`/`review` stages, `full`
  profile), with the three answers substituted into `[roles]`.
- **M5 — The wizard also generates `prompts/test.md`.** The `test` stage's
  prompt has no built-in template (confirmed: `prompts.TEMPLATES` only has
  `implement`/`review`) — without a generated file, `doctor`'s own
  prompt-existence check would fail immediately after the wizard finishes.
  The generated template matches `IMPLEMENT`/`REVIEW`'s own structure and
  style (`{sync_packet}`/`{task_id}`/`{task_text}` placeholders), instructing
  the tester to run the suite and hand off with `passed`/`failed` outcomes,
  matching the stage's own `[pipeline.stages.test.on]` transitions. It uses
  `{actor}` for the tester's own agent name, not `{implementer}`/`{reviewer}`
  -- confirmed by reading `loop.py`: those two placeholders always resolve to
  whichever agents fill the pipeline's specific `implementer`/`reviewer`
  roles, never to whoever is running the *current* stage. There is no
  generic per-role placeholder; `{actor}` (the stage's actual runner) is the
  only one that means "whoever is testing right now." `{reviewer}`/
  `{implementer}` are still correct for the handoff *destination* fields
  (passed → the reviewer, failed → the implementer), since those genuinely
  do mean the pipeline's fixed reviewer/implementer roles.
- **M6 — The wizard auto-commits its own generated files** (`config.toml`,
  `prompts/test.md`) before running `doctor` or asking to start. Directly
  motivated by a real failure the user hit in this exact session: a paused
  relay run's own uncommitted files caused `whyline-relay resume` to refuse
  with "working tree has uncommitted changes." The wizard must never leave
  the user at that exact wall right after finishing it.
- **M7 — `doctor`'s verdict gates `start`, not just informs it.** A FAIL
  refuses to offer "Ready to start?" at all. A WARN-only result asks
  "Proceed anyway? [y/N]". An all-clear result asks "Ready to start?
  [Y/n]" and, on yes, execs into `whyline-relay start`.
- **M8 — Declining the final "start?" prompt is a clean exit, not a
  failure.** The wizard's own setup is already committed by M6, so
  `whyline-relay start` works correctly whenever the user runs it later —
  nothing needs to be redone.

## Architecture

```
whyline (no args)
  │
  ├─ which("whyline-relay") is None?
  │     yes → fall through to existing usage output (unchanged)
  │
  ▼
"Chat or relay? [chat]:"
  │
  ├─ chat ─┬─ "Start chatting, or set a model first? [chat]:"
  │        │     model → subprocess.run(["whyline", "model"]), inherits
  │        │              the terminal, blocks until it exits
  │        │     (either way, falls through to the next line)
  │        └─ exec_fn("whyline-relay", ["whyline-relay", "chat"])
  │
  └─ relay ──exec──▶ whyline-relay setup   (new subcommand)
                        │
                        ├─ plan.md missing or "draft" chosen?
                        │     → subprocess call into the existing
                        │       `whyline-relay plan "..."` planner workflow
                        │
                        ├─ role wizard (M4/M5): writes config.toml +
                        │     prompts/test.md
                        │
                        ├─ gitcheck.commit_all(root, "setup: assign
                        │     implementer/tester/reviewer roles") (M6)
                        │
                        ├─ preflight.run(...) -- doctor's own existing
                        │     check list, unchanged (M7)
                        │
                        └─ FAIL → print and exit
                           WARN-only → "Proceed anyway? [y/N]"
                           clean → "Ready to start? [Y/n]"
                                       yes → exec_fn("whyline-relay",
                                             ["whyline-relay", "start"])
                                       no  → clean exit (M8)
```

**Package split**, matching the chat-repl precedent: the menu itself (a
handful of lines: one prompt, one conditional subprocess call, one exec)
lives in `whyline`'s `cli.py`. Everything relay-specific — the plan
existing-or-draft branch, the role wizard, the `doctor` gate, the final
start confirmation — is a new module in whyline-relay (`setup.py`, wired to
a new `whyline-relay setup` subcommand), reusing `preflight.run`,
`planner`'s existing entry point, `gitcheck.commit_all`, and `config.py`'s
existing TOML-writing conventions (mirroring `init.py`'s own `_write`
helper). No permission or validation logic is duplicated into whyline.

## Chat path

```
$ whyline
Chat or relay? [chat]: 
Start chatting, or set a model first? [chat]: model
[... whyline model runs interactively here, inheriting the terminal ...]
Detected: claude, codex, agy, grok.
Pick your default agent [claude]: 
Saved. Starting chat -- default agent is claude.
> 
```
Pressing enter at either prompt (accepting the bracketed default) reproduces
exactly today's behavior — bare `whyline` still gets you straight into chat
with zero extra keystrokes if you never touch the new questions.

## Relay path — the wizard's exact output

```
$ whyline
Chat or relay? [chat]: relay
Use the existing plan.md, or draft a new one? [existing]: 
Who implements? [codex]: grok
Who tests?      [claude]: codex
Who reviews?    [claude]: 
Wrote .whyline/relay/config.toml.
Wrote .whyline/relay/prompts/test.md.
Committed as setup: assign implementer/tester/reviewer roles.

  ok    directory is inside a git repository
  ok    whyline is installed and initialised
  ok    relay setup is complete
  ok    grok is on PATH
  ok    codex is on PATH
  ok    codex is logged in
  ok    plan parses and has unchecked tasks: plan.md
  ok    working tree is clean
All checks passed.

Ready to start? [Y/n]: 
```

`config.toml` written (M4):
```toml
[roles]
implementer = "grok"
tester      = "codex"
reviewer    = "codex"

[pipeline]
default_profile = "full"

[pipeline.profiles]
full = ["draft", "test", "review"]

[pipeline.stages.draft]
role   = "implementer"
prompt = "implement"
[pipeline.stages.draft.on]
ready = "@next"

[pipeline.stages.test]
role       = "tester"
prompt     = "test"
max_visits = 5
[pipeline.stages.test.on]
passed = "@next"
failed = "draft"

[pipeline.stages.review]
role   = "reviewer"
prompt = "review"
[pipeline.stages.review.on]
approved = "@complete"
rejected = "draft"
```

`prompts/test.md` written (M5), matching `IMPLEMENT`/`REVIEW`'s own
structure:
```
{sync_packet}

You are the tester for this task. Round {round}.

## Task {task_id}

{task_text}

## How to test

Run the project's own test suite in full, plus anything this task's own
instructions call for. Judge only whether the implementation behaves
correctly -- not whether the diff is well-written; that is the reviewer's
job next.

Record your ruling -- testing is deciding:

    whyline note "<one-line ruling>" --because "<why>" \
      --file <path> --actor {actor} --role tester --task {task_id}

## How to finish

Exactly one of these outcomes.

Passed: hand off to the reviewer.

    whyline handoff {task_id} --from {actor} --to {reviewer} --status passed \
      --summary "<what you verified>" --test "<command>: <result>"

Failed: hand back to the implementer with concrete, actionable detail.

    whyline handoff {task_id} --from {actor} --to {implementer} --status failed \
      --summary "<what failed>" --test "<command>: <result>"

Do not commit either way -- the reviewer commits once this task is fully
approved.
```

## Error handling

- **No plan.md, "existing" chosen**: prints a pointer to
  `whyline-relay plan "..."` or writing one by hand, exits cleanly.
- **`doctor` FAIL**: shown in full, `start` is never offered, exits.
- **`doctor` WARN only**: shown in full, asks "Proceed anyway? [y/N]".
- **Declining "Ready to start?"**: clean exit; setup already committed
  (M6/M8) — nothing to redo before running `whyline-relay start` later.
- **`whyline-relay` not installed**: the whole menu is skipped; `whyline`
  behaves exactly as it does for anyone not using the relay side today.

## Testing strategy

- **whyline**: menu-choice tests with `which`/`exec_fn`/a fake
  `subprocess.run` all mocked — never a real exec or subprocess during
  tests, matching `runner.py`'s own established discipline. Covers: default
  (enter-to-accept) reproduces today's behavior exactly; explicit "relay"
  execs into `whyline-relay setup` instead of `chat`; the model sub-choice
  calls the fake subprocess runner then still proceeds to exec chat
  afterward; `whyline-relay` absent skips the menu entirely.
- **whyline-relay's new `setup` module**: plan existing-or-draft branching
  (mocked planner call); the wizard's exact `config.toml`/`prompts/test.md`
  output byte-for-byte; `gitcheck.commit_all` actually called before
  `doctor`; `doctor`'s three outcomes (FAIL/WARN/clean) each drive the
  correct next step, with `preflight.run` itself mocked to return each case
  deterministically; the final start confirmation execs into
  `whyline-relay start` only on yes.
- **End-to-end** (once built): a real scratch-repo run of the full
  `whyline` → Relay → wizard → `doctor` → `start` chain with real installed
  agents, the same empirical bar every feature this session has been held
  to before shipping.
