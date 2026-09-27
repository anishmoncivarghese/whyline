# Chat Multi-Model Brainstorm Design

**Status:** Approved by user, section-by-section, 2026-09-27.

## Goal

`/brainstorm` in `whyline chat` runs a topic through however many models you
pick, in three phases — independent research, N rounds of combined review,
then one designated model's final synthesis — saving every model's own
findings into one shared, real markdown file you can read afterward.

## Non-goals

- **Relay's "create a plan" via brainstorming.** Explicitly deferred to a
  separate, subsequent design that reuses this engine, per the user's own
  sequencing ("similar feature we can add in relay as well").
- **True concurrency.** Chat only ever runs one agent at a time; every phase
  here is a sequence of ordinary, sequential turns — never simulated or
  actual parallelism.
- **A new logging/history mechanism.** Brainstorm turns flow through the
  existing `run_turn`/`chatlog.append` unchanged; they appear in `/history`
  like any other turn, by construction, not by new design.
- **Enforcing blindness through instructions alone for pass 0.** Independence
  during independent research is structurally guaranteed (separate temp
  files, merged only after every model finishes), not merely requested in
  a prompt a model could ignore.

## Decisions

- **B1 — Reuse `run_turn` for every phase, unchanged.** Brainstorming is an
  orchestration layer over ordinary chat turns, not a new file-manipulation
  subsystem: each model's research/review/synthesis step is a normal
  `run_turn(agent, prompt=...)` call whose prompt is auto-generated instead
  of typed, and whose file edits (made by the agent's own tooling, not by
  whyline's code) are auto-committed exactly as any other chat turn already
  is. This means brainstorming inherits the existing permission floor,
  failover (0.2.17), and `AgentMissing`/`AgentTimeout` handling for free.
- **B2 — Pass 0 is structurally blind.** Each selected model's independent
  research writes to its own private, gitignored temp file
  (`.whyline/relay/brainstorm-tmp/<agent>.md`), never the shared file. Only
  after every selected model has finished pass 0 does whyline's own code
  (not an agent) merge the temp files into `docs/brainstorm/<topic-slug>.md`
  under one `## <Agent>` heading each, commit that merge, and delete the
  temp files. A model genuinely cannot see another's pass-0 work, regardless
  of what any prompt says.
- **B3 — Each model's section holds only its latest revision.** From pass 1
  onward, a model re-reads the whole shared file and revises *only* its own
  section in place — no per-pass history kept in the file (recoverable from
  git commits if ever needed). Explicit user choice, favoring a shorter file
  every later pass and the final synthesis has to re-read.
- **B4 — Invocation is `/brainstorm` plus a short Q&A**, not a one-line
  flag syntax — matching the existing first-launch setup wizard's own
  question-sequence style, and giving first-time guidance the flag form
  wouldn't. Four questions: topic, models (comma-separated numbers, matching
  chat's own agent set: `1 claude, 2 codex, 3 antigravity, 4 grok, 5 all`),
  number of review passes, which model does the final synthesis (must be one
  of the selected models; reprompt if not).
- **B5 — Distinct, readable commit messages per phase.** `run_turn`/
  `_execute_agent_call` gain one small, backward-compatible addition: an
  optional `commit_message: str | None = None` parameter, falling back to
  today's `f"chat: {agent} turn"` when omitted. Brainstorm passes
  `brainstorm: <agent> independent research on "<topic>"`,
  `brainstorm: merge independent research on "<topic>"`,
  `brainstorm: <agent> review pass <N> on "<topic>"`, and
  `brainstorm: <agent> final synthesis on "<topic>"` respectively.
- **B6 — Availability is checked before any turn runs.** Every selected
  model is checked against `resolve_command` up front; any that would raise
  `AgentUnavailable` are listed, with a "proceed without them? [y/N]"
  confirmation before a single turn happens. Declining aborts cleanly — no
  files touched, nothing committed.
- **B7 — A mid-brainstorm crash degrades gracefully, never destructively.**
  `AgentMissing`/`AgentTimeout` on one model's turn is caught, printed, and
  that model simply keeps its previous section's content for this phase —
  the rest of the brainstorm continues with the other models. A turn that
  completes but reports failure (`record["ok"]` is `False`) is printed with
  the existing `⚠` convention and also does not stop the session; the human
  reviews the file afterward, the same way any other chat turn already
  works.

## Architecture

```
/brainstorm
  │
  ├─ "What should we research?" → topic
  ├─ "Which models? (1 claude, 2 codex, 3 antigravity, 4 grok, 5 all): "
  ├─ "How many passes? [1]: " → N (0 is valid)
  ├─ "Which model gives the final synthesis? [<first selected>]: "
  │     (must be one of the selected models; reprompt otherwise)
  │
  ├─ availability check (B6): resolve_command for every selected model;
  │     any AgentUnavailable → list them, "proceed without them? [y/N]"
  │
  ▼
Pass 0 (independent, structurally blind -- B2):
  for each selected (available) model:
    run_turn(agent, prompt=RESEARCH_PROMPT, commit_message=...)
    (prompt tells it to write findings to its own temp file)
  │
  ▼
Merge (whyline's own code, not an agent turn):
  read each non-empty temp file → docs/brainstorm/<slug>.md under
  "## <Agent>" headings, in selection order → commit → delete temp files
  │
  ▼
Passes 1..N (combined review):
  for each pass:
    for each selected (available) model:
      run_turn(agent, prompt=REVIEW_PROMPT, commit_message=...)
      (prompt tells it to revise only its own section)
  │
  ▼
Final synthesis:
  run_turn(final_model, prompt=SYNTHESIS_PROMPT, commit_message=...)
  → response printed and logged exactly like any normal chat turn (B1)
```

## Prompts (auto-generated, never typed by the human)

```
RESEARCH_PROMPT = (
    'Research "{topic}" independently. Write your findings to {temp_path} '
    'as plain markdown. This is your own independent pass -- you haven\'t '
    'seen, and shouldn\'t need, any other model\'s perspective yet.'
)

REVIEW_PROMPT = (
    'Combined review pass {pass_number} of a brainstorm on "{topic}". Read '
    '{shared_path} in full. Update your own section ("## {agent_label}") in '
    'place based on what you now see from the others -- replace it with '
    'your revised thinking, rather than appending a new dated block; the '
    'file should only ever show your current view, not a history of past '
    'passes. Do not touch any other model\'s section.'
)

SYNTHESIS_PROMPT = (
    'All review passes are complete for this brainstorm on "{topic}". Read '
    '{shared_path} in full and write a new "## Final Synthesis" section (at '
    'the top, right after the title) combining the strongest ideas from '
    'every model\'s section into one clear, actionable recommendation.'
)
```

`{agent_label}` is the same display label used in the model-selection menu
(e.g. "Antigravity" for `agy`), so a model's own section heading is
human-readable, not the raw agent key.

## File layout

- `docs/brainstorm/<topic-slug>.md` — the real, committed shared file.
  Slugified from the topic (lowercase, non-alphanumeric runs become single
  hyphens, truncated to a reasonable length).
- `.whyline/relay/brainstorm-tmp/<agent>.md` — pass-0 temp files, gitignored
  (added to the existing relay `.gitignore` list generated by
  `init.ensure_relay_gitignore`, alongside `chat.json`/`chat-history.jsonl`).
  Deleted immediately after the merge.

## Error handling

- Invalid model/pass-count/final-model input: reprompt, matching the
  existing setup wizard's own pattern.
- An unavailable selected model: listed and confirmed before any turn runs
  (B6); declining aborts with nothing touched.
- `AgentMissing`/`AgentTimeout` mid-phase: caught, printed, that model keeps
  its previous section, the brainstorm continues (B7).
- A turn reporting failure (`ok: False`): printed with `⚠`, continues (B7).
- An empty or missing pass-0 temp file: skipped in the merge, not an error.
- 0 passes: valid, goes straight from the merge to final synthesis.

## Testing strategy

- Question/validation logic: model-number parsing (comma-separated, "5" =
  all, reprompt on garbage input), pass-count parsing, final-model-must-be-
  among-selected validation.
- Pass 0 + merge: temp files created per model; merged under the right
  headings in selection order; temp files deleted afterward; commit message
  matches; an empty temp file produces no section for that agent.
- Passes 1..N: each selected model re-invoked with the review prompt exactly
  once per pass, using a fake `run_fn` that simulates editing only its own
  section.
- Final synthesis: only the designated model runs this phase; its returned
  record has the same shape any normal chat turn's record already has.
- Error handling: an unavailable model detected and confirmed before any
  turn runs; a mid-phase `AgentMissing` doesn't abort the session; a
  reported failure prints `⚠` and continues.
- End-to-end (once built): a real scratch-repo brainstorm with two real
  agents and one review pass, confirming the actual files and commits look
  right — the same empirical bar every feature this session has been held
  to before shipping.
