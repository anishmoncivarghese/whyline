# Relay plan flow: background planning, questions, named plans

Date: 2026-10-04
Status: approved 2026-10-04 (sections 8-9 added the same day)
Repos: whyline-relay (relay 0.2.27) and whyline (console)

## Why

Testing the console in a fresh repo (TradingPlatform) showed five problems:

1. Plan failed with "claude exited without handing off". The cause was that
   claude's `.whyline/relay/claude-settings.json` is only written by `init`, and
   Plan runs before Set up. **Fixed already** on whyline-relay branch
   `fix/run-agent-permission-files` (d3c9606); it ships in relay 0.2.27 with
   this work.
2. Plan blocks the whole console in a modal popup for many minutes, and its
   progress is only visible inside that popup.
3. When an agent needs a decision it hands off `blocked` with `--question`,
   but the console shows that as a single error line with no way to answer.
4. In "Draft from a description" mode there is no way to pick the drafter or
   the reviewer; they come silently from `[planner]` in the relay config.
5. Set up does not show which plan it will run, cannot choose between plans,
   and does not say why grok and antigravity are missing.

## What the user asked for

- Pressing "Make the plan" (any source, including a new brainstorm) closes the
  popup. Progress streams into the main console window.
- An agent's questions appear in the main window. The user types the answer
  in the normal prompt, and the answer goes back to the agent.
  **Option A was chosen:** the agent stops with its questions and the plan
  step resumes with the answers. Agents are not kept running between turns.
- Planning is a required step. Every source (description, paste, brainstorm)
  produces a plan file in one recognisable format, so Set up can find all of
  them automatically.
- Set up shows a dropdown of saved plans, then the implementer, tester and
  reviewer. With no plan it tells the user to make one first; so do Start and
  a typed `start`.
- Plan lets the user pick the models.

Added on 2026-10-04, after a brainstorm in TradingPlatform skipped grok and
antigravity ("not set up for chat here") and reported Claude's usage limit
as "generic non-zero failure":

- grok and antigravity are set up automatically in every repository, for
  chat, brainstorm and every relay role, with no hand-written config. For
  Antigravity's machine-wide trust setting, the console **asks once per
  repository** (section 8).
- A failed agent turn says why, in the agent's own words. A usage limit is
  recognised as one (section 9).

## Design

### 1. Plan files

- Every plan lives at `plans/<slug>.plan.md`. `<slug>` comes from a "Plan
  name" field in the Plan popup. Left empty, the name is taken from the
  description, the brainstorm topic or the pasted plan's first heading.
  The slug is lower-case `[a-z0-9-]`, at most 40 characters. If the name is already
  taken, the user is asked "Replace it?" (the existing `ConfirmScreen`).
- The first line of the file is the marker, a Markdown comment:

  ```
  <!-- whyline-plan v1 | source: draft | drafted-by: codex (reviewed by claude) | created: 2026-10-04T10:12:00+05:30 -->
  ```

  `source` is `draft`, `paste` or `brainstorm`. The relay's plan parser
  already skips lines that aren't tasks, so the marker needs no parser change.
- A plan counts as a plan when it has the marker on line 1 and passes
  `planner.validate`. Saved plans are listed by
  `relay_ops.list_plans(root) -> list[PlanInfo]`, newest first, with
  `PlanInfo(path, name, source, created, done, total)`.
- A legacy root `plan.md` that validates is also listed, as
  `plan.md (older format)`. It is never rewritten.
- A pasted plan gets the marker added; if it already has one, it is
  replaced. Approving still commits only that one file
  (`gitcheck.commit_paths`), with the message `docs: add plan <slug> drafted by <who>`.

Relay change: `planner.approve(..., target: Path | None = None)`. The default
stays `config.plan` (`plan.md`), so the CLI is unchanged.

### 2. Which plan the relay runs

Set up writes the chosen plan into `.whyline/relay/config.toml` as
`plan = "plans/<slug>.plan.md"`, through a new relay function
`setup.write_plan(root, path)` that edits only that key and keeps every other
key. A terminal `whyline relay start` then runs the same plan. A paused run
keeps using the plan saved in its state, as it does today.

### 3. Plan popup: a form only

The popup keeps its three sources and gains:

- **Plan name**: the input described above.
- **Draft from a description**: **Drafter** and **Reviewer** dropdowns
  listing `relay_ops.relay_agents()`, prefilled from `[planner]`. On "Make
  the plan" they are saved to `[planner] draft` / `review` through a new
  relay function `setup.write_planner(root, draft, review)`, so a resumed
  draft and the CLI use the same agents.
- **From a brainstorm**: unchanged. "Final write-up" (new brainstorm) or
  "Plan writer" (existing brainstorm) already picks the model.

Pressing "Make the plan" checks the form (empty description, missing
reference files, invalid paste, name clash), then dismisses with a
`PlanRequest` (source, name, inputs, agents). The popup no longer has a
working state or a review state; those move to the main window. "Paste a
plan" + Save stays instant and still saves from inside the popup.

The "Resume draft" / "Discard it" buttons for an unfinished draft stay in the
popup. Resume dismisses with a `PlanRequest(source="resume")`.

### 4. The plan job in the main window

`WhylineConsoleApp` runs a `PlanRequest` as a background job, the same way
`_start_brainstorm` does today: a dispatch token, `_set_busy(True, "planning")`,
a worker thread, and Stop drops a late result.

- **Progress.** Every progress line from the relay is rendered as
  `plan · <line>`: a new brainstorm's phases, then "codex is drafting the
  plan", "claude is reviewing the plan", and so on.
- **Result: a draft.** The transcript shows a summary (name, task count,
  phases or the first 15 task titles) and the draft's path. The console enters
  the **plan-review** state: the prompt placeholder becomes
  `Type "approve", or say what to change`, and the bottom bar shows
  **Approve**, **View draft** and **Discard**.
  - `approve` (typed or the button) writes `plans/<slug>.plan.md` and commits
    it. The transcript then says "Saved plans/<slug>.plan.md. Next: Set up."
  - Any other text is change feedback. It goes to `relay_ops.revise_plan`, the
    job runs again, and progress streams in as before.
  - **View draft** opens a read-only, scrollable popup with the full draft.
  - **Discard** drops the draft (`relay_ops.discard_draft`) and leaves the
    state.
- **Result: questions.** See section 5.
- **Result: failure.** An error event with the relay's reason and the log
  path. The checkpoint stays, so Plan → Resume draft retries.

While any of these states is active, the text the user types goes to the plan
job, not to chat. The mode indicator shows `relay · plan review` or
`relay · answering`, so it is clear where the text goes. Stop or Esc leaves
the state without discarding anything.

### 5. Questions (option A)

The planner prompts already tell agents to hand off `--status blocked` with
one or more `--question`. Today `planner._run_pipeline` turns that into a
generic `loop.Paused`.

Relay changes:

- A new `planner.PlanQuestions(loop.Paused)` exception carrying
  `questions: tuple[str, ...]`, `stage` and `agent`. `_run_pipeline` raises it
  instead of the generic `Paused` when the decision is `blocked` and the
  handoff has at least one question. The checkpoint already records the
  stage.
- A new `planner.answer(root, settings, answers: str, *, print_fn, runner)`
  re-runs the **saved stage**, not always `draft`, with feedback built like
  this:

  ```
  You asked:
  1. <question>
  2. <question>
  The human answered:
  <answers>
  ```

  It returns the draft path as `draft` and `revise` do, and can raise
  `PlanQuestions` again.
- `PLAN_DRAFT` and `PLAN_REVIEW` gain one sentence: put each choice in the
  question itself, as `(a) … (b) …`, and ask only about decisions the
  reference documents don't settle.
- The plan writer for a brainstorm (`generate_plan_from_synthesis`) is a chat
  turn, not a pipeline. It is told to put any open decisions under an
  `## Open questions` heading at the top of the draft. The console treats
  that section's items as questions in the same way, and answers go back
  through `revise_plan`.

Console:

- On `PlanQuestions` (or a draft containing `## Open questions`), the
  transcript shows:

  ```
  claude needs answers before the plan can continue:
    1. Which broker? (a) Kite (b) Upstox
    2. Paper trading in V1? (a) yes (b) no
  Answer in the prompt below, e.g. "1a, 2: yes but only for the pilot".
  ```

  The console enters the **answering** state.
- Whatever the user types is sent as the answers (`relay_ops.answer_plan`).
  The job continues and streams progress again. It ends in another set of
  questions, a draft (plan-review state) or a failure.
- The console does not parse the answers. The agent reads the user's text
  as-is, so free text, letters and partial answers all work.
- The questions and answers are kept in the transcript, and Copy includes
  them.

### 6. Set up

- First row: **Plan**, a dropdown over `list_plans(root)` showing
  `<name> · <done>/<total> done · <source> · <date>`. The default is the plan
  `config.plan` names if it is listed, otherwise the newest.
- No plans: the form shows "No plan yet. Make one first." and a **Make a
  plan** button, which closes Set up and opens Plan. Check and Start are
  disabled.
- Role and backup choices list every agent the relay can run that is
  installed (`relay_ops.relay_agents(root)`, section 8): claude, codex,
  antigravity and grok when all four are on PATH.
- Check saves the roles and the chosen plan (`setup.write_plan`), then runs
  preflight. Changing the plan clears the check result, like any other edit.
- A typed `start` with no listed plan and no `plan.md` is refused with "No
  plan yet. Use Plan first." `resume` is unaffected.

### 6a. Run: one guided path (added 2026-10-04)

The user should not have to know that Plan comes before Set up, which comes
before Start. A **Run** button in Relay mode, or typing `run` there, walks
through all three in order. Plan and Set up stay as shortcuts.

1. **Which plan.** With no saved plan, the transcript says "No plan yet --
   let's make one." and the Plan form opens. Otherwise a small dialog
   asks **Make a new plan** / **Use an existing plan** / Cancel.
   - *Make a new plan* opens the Plan form (section 3). The plan job runs in
     the main window (section 4). When the plan is approved, or a pasted
     plan is saved, the flow continues to step 2 with that plan selected.
     Cancelling, discarding or a failure ends the flow, with a line saying
     so.
   - *Use an existing plan* goes straight to step 2.
2. **Who does what.** Set up opens in guided mode, titled "Run: check who
   does what, then start", with the plan dropdown first.
   - If this repository's config already assigns roles, they are shown as
     one line, `Implementer: antigravity · Tester: claude · Reviewer: codex
     · Backup: claude → codex`, with **Looks good** and **Change**.
     *Change* shows the dropdowns and backup checkboxes. *Looks good* runs
     the check straight away.
   - With no roles configured yet, the dropdowns show directly.
   - The backup chain stays per repository (`[backup] chain`, as today),
     and applies to every role.
3. **Ready check and Start.** This is Set up's existing Check (it saves the
   roles and the plan, then runs the relay's preflight checks) and Start.
   Start launches the run, and progress streams into the main window.

Nothing about the repository changes in this flow. The console always works
on the repository shown at the top right, and plans are listed from that
repository only.

### 7. Error handling

- A missing agent or timeout: an error event with the agent's own message
  and the log path. The checkpoint is kept.
- A console closed mid-job: the checkpoint survives (the same as today).
  Plan → Resume draft continues it. If it was waiting on questions, Resume
  shows them again. The questions are re-read from the last handoff when
  `stage` is still the blocked stage.
- A Stop mid-job: the token drops the late result. The agent process is left
  to finish, exactly as for chat and brainstorm today, and its handoff is
  picked up by the next Resume.

### 8. grok and antigravity work in every repository

**Why it happened:** the relay knows built-in commands only for claude and
codex. agentdock works because its `.whyline/relay/config.toml` has
hand-written `[agents.antigravity]` and `[agents.grok]` tables (the README
recipes); TradingPlatform has no config, so `chat.resolve_command` raises
"not configured for chat in this repo" and the brainstorm skips them.

**Relay change:** a new `whyline_relay.recipes` module holds the two README
recipes as defaults:

- `antigravity`: `["agy", "--output-format", "json", "--mode", "accept-edits",
  "--add-dir", ".", "--new-project", "-p"]`
- `grok`: the recipe in agentdock's config (deny `git push` and `rm -rf`;
  allow Edit, git add/commit/diff/status/log, whyline, python3, uv, mkdir, ls,
  find, touch, cat; `-p` last).

`config.load` adds each recipe as a generic agent when the repository's
config doesn't define that name. It does not look at PATH, so loading stays
deterministic; a missing binary is reported where the agent is used, as it
is for claude and codex today ("skipped: missing executable"). A
repository's own `[agents.<name>]` always wins, so customised commands are
untouched. Role, backup and `[planner]` validation then accept both names
everywhere.

**Console change:** `relay_ops.relay_agents(root)` returns the agents in the
loaded config whose binary is on PATH (`agy` for antigravity), sorted. Set
up, Plan's Drafter/Reviewer and the backup checkboxes all use it.

**Antigravity's trust (asked once per repository):** `agy` refuses even to
read files unless the repository is listed in `trustedWorkspaces` in
`~/.gemini/antigravity-cli/settings.json`, and that file covers the whole
machine. Relay change: `whyline_relay.antigravity` gets
`is_trusted(root) -> bool` and `trust(root) -> Path`. `trust` adds the
resolved repository path to `trustedWorkspaces` and adds the four verified
`permissions.allow` entries (`read_file(*)`, `write_file(*)`, `edit_file(*)`,
`command(*)`) when missing, keeping every other key in the file and writing
it atomically.

Before the console starts anything that runs antigravity (a brainstorm that
includes it, a chat turn with it, a plan job or relay run that gives it a
role), it checks `is_trusted`. If the repository isn't trusted and the user
hasn't declined for this repository, it asks:

> Antigravity can only read and edit files in folders listed in
> ~/.gemini/antigravity-cli/settings.json, a setting for the whole machine.
> Add <repo path> to it, and allow Antigravity's file and command tools?

- **Trust it** calls `trust(root)`, then carries on.
- **Not now** records the refusal in `.whyline/relay/antigravity-declined`
  (git-ignored through `RELAY_IGNORE`) and carries on without antigravity:
  a brainstorm drops it with the line "Skipping Antigravity: this repo isn't
  trusted in its settings (Model → Antigravity to ask again)"; a chat turn
  or relay run that needs it stops with that reason instead.
- Choosing antigravity explicitly with Model, or as a role in Set up, removes
  the refusal file and asks again.

### 9. Failures say why

**Why it happened:** when an agent's turn finishes but fails,
`brainstorm.py` prints only `classify_failure`'s category and drops the
agent's own text. The rate-limit check knows "usage limit" and "rate limit",
but not Claude's newer wording, so a usage limit fell through to "generic
non-zero failure".

**Relay changes:**

- `agents.RATE_LIMIT_MARKERS` gains `"hit your limit"`, `"limit reached"`,
  `"session limit"`, `"weekly limit"` and `"out of credits"`.
- A new `brainstorm.failure_reason(record=None, error=None) -> str` returns
  `"<category> — <detail>"`. The detail is the agent's extracted response,
  or the last non-blank line of its raw output, printable characters only,
  at most 160 characters, and is left out when empty or equal to the
  category. Every place that reports a failed turn (pass zero, review
  passes, final synthesis, the plan writer) uses it for both the progress
  line and the status record:

  `[1/4] Claude failed pass-zero (4s): quota/rate-limit — You've hit your limit · resets 3pm`

## Testing

Relay (pytest, with the fake agents in `tests/fake_pipeline_agent.py`):

- A `blocked` handoff with questions raises `PlanQuestions` with those
  questions, and the checkpoint keeps the stage.
- `answer()` re-runs the review stage when review blocked, with the
  answers in the prompt feedback.
- `approve(target=...)` writes and commits only that file. Without `target`
  it still writes `plan.md`.
- `write_plan` and `write_planner` change only their keys and keep a
  hand-edited config.
- The settings-file fix (`tests/test_planner_permission_files.py`, done).
- With no config, `config.load` has `antigravity` and `grok` as generic
  agents with the recipe commands. A repository's own `[agents.grok]` wins.
  `roles.implementer = "grok"` loads without an error.
- `chat.resolve_command(settings, "grok")` works with no config.
- `antigravity.trust` adds the repository once, keeps unrelated keys, and
  creates the file when it is missing. `is_trusted` reads it back.
- A turn whose output says "You've hit your limit · resets 3pm" is
  classified as quota/rate-limit, and the progress line includes that text.
- An exit with an unknown error shows the agent's last line after the
  category.

Console (pytest + Textual pilot, existing `tests/console` patterns):

- "Make the plan" dismisses the popup and streams `plan ·` lines into the
  transcript.
- The plan-review state: `approve` writes `plans/<slug>.plan.md` with the
  marker. Other text calls `revise_plan`.
- The answering state: questions are rendered numbered, and the typed text
  reaches `answer_plan` unchanged.
- `list_plans` reads the marker and counts done/total. It lists a legacy
  `plan.md` and skips Markdown files without the marker.
- Set up with no plans disables Check and Start and offers Make a plan.
  With two plans, the chosen one is written to the config.
- A typed `start` with no plan is refused.
- Run with no plans opens Plan. After the plan is approved, guided Set up
  opens with that plan selected. Run with plans offers new or existing.
- Guided Set up with roles configured shows the summary line. Looks good
  runs the check, and Change reveals the dropdowns.
- `relay_agents(root)` lists grok and antigravity when their binaries are on
  PATH, and leaves them out when they aren't.
- A brainstorm that includes antigravity in an untrusted repository asks
  once. Trust calls `trust`. Not now writes the refusal file, drops
  antigravity with the skip line, and doesn't ask again.

## Releases

0. whyline-relay 0.2.27: the settings-file fix. **Published 2026-10-04.**
1. whyline-relay 0.2.28: sections 8 and 9 (agent recipes, Antigravity trust,
   failure reasons).
2. whyline 0.3.31: requires `whyline-relay>=0.2.28,<0.3`, and adds the
   automatic agent list and the trust question.
3. whyline-relay 0.2.29: `PlanQuestions`, `answer`, `approve(target=)`,
   `write_plan`, `write_planner` and the prompt sentences.
4. whyline 0.3.32: requires `whyline-relay>=0.2.29,<0.3` and contains the
   plan-flow console changes (sections 1-7).

Both are published only after the user approves the release.
