<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-11-14-agent-builder-design.md | created: 2026-11-14T23:00:00+05:30 -->
# Agent profile: a description, starter prompts, a one-off request, and Test

Spec: `docs/superpowers/specs/2026-11-14-agent-builder-design.md`, Part 1. Read it before every task. Where this plan and the spec differ, this plan wins.

Runs after `plans/release-supply-chain.plan.md`, and before `plans/agent-draft.plan.md`. It needs agent-tools released (TLS-7's fields, TLS-9's server and TLS-10's approvals).

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Why: an agent has a name and a schedule but nothing saying what it is for, no example requests, no way to give it a request for one run, and no way to try it before saving.

What the user gets:
- A one-line **Description** on every new agent, shown wherever agents are listed.
- Up to 4 **starter prompts**, as buttons in Telegram and the console.
- `run <agent> <text>`: a request for that one run.
- **Test** in the agent form: one run without saving, without delivery and without history.

Rules every task keeps:
- **Console first.** Everything is in the Agents screens and saves through the same functions as `whyline agents …`.
- **Old agents keep working.** An agent file without the new fields loads, runs and keeps its accepted state. Adding the fields to the file format must not change the definition hash of an agent that doesn't use them.
- **A one-off request is data.** It goes into the prompt in a block labelled as the user's request for this run, cut to 2,000 characters. It never changes the agent's tools, permissions, delivery or schedule.
- **Test changes nothing.** No agent file, state, history record or delivery is written by a test.
- **No new dependency.**
- **Tests:** never invoke a real provider, Telegram or an MCP server. Use temporary folders and fakes. Keep Python 3.11 compatibility.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- An accepted agent without the new fields stays accepted after upgrade. PRF-1, `test_old_agent_hash_is_unchanged`.
- A test run sends no delivery and writes no history or state. PRF-4, `test_test_run_leaves_no_trace`.
- In a test, a tool that writes always asks, even when the form says Allowed. PRF-4, `test_test_run_asks_for_writes`.
- A one-off request can't change tools, delivery or schedule. PRF-3, `test_request_is_only_prompt_text`.
- A new agent can't be saved without a description; an old one can still be edited and saved after adding one. PRF-2, `test_description_required_for_new`.

- [ ] PRF-1: Description and starter prompts in the definition
  Edit `src/whyline/agents/definitions.py`, `src/whyline/agents/service.py` and their tests only.
  1. `AgentDef` gets `description: str = ""` (one line, at most 200 characters) and `starters: tuple[str, ...] = ()` (at most 4, each one line of at most 120 characters). `parse` reads them and `render` writes them only when set. More than the limits, or a line break in either, makes the agent broken with the reason.
  2. `definition_hash` is unchanged for a file without the two fields. A changed description or starters do not put an accepted agent back into needs review (they don't change what it can do); pin this by hashing with the two fields left out.
  3. `service.Row` gains `description`. `service.describe` puts the description first.
  Tests: `test_old_agent_hash_is_unchanged` (a fixture file's hash equals the value the test fixes from today's code), round trip, each limit, and an edit of the description keeping the agent accepted.

- [ ] PRF-2: Description and starters in the console and CLI
  Edit `src/whyline/console/agents_screens.py`, `src/whyline/cli.py` (the `whyline agents` commands) and their tests only.
  1. New agent and Edit agent: a **Description** input under the name with the hint `What it's for, in one line`, and a **Starter prompts** list (add, edit, remove, up to 4). Saving a new agent without a description is refused with `Add a description: one line on what this agent is for.` Editing an old agent without one shows the same line as a warning and still saves other changes.
  2. The Agents list shows the description under each name, or `No description — add one in Edit`. The detail and Review screens show it first.
  3. CLI: `whyline agents list` prints the description. `whyline agents describe <agent> "<text>"` and `whyline agents starters <agent> [--add "<text>"] [--remove <n>]` save through the same functions as the form. `whyline agents new` requires `--description`.
  Tests: `test_description_required_for_new`, the list line, the warning on an old agent, the 4-starter limit in the form, and CLI and console saving through one function.

- [ ] PRF-3: A request for one run
  Edit `src/whyline/agents/runner.py`, `src/whyline/agents/service.py`, `src/whyline/ideas/bot.py`, `src/whyline/ideas/intent.py`, `src/whyline/console/agents_screens.py`, `src/whyline/cli.py` and their tests only.
  1. `service.run_now(name, repo_root, *, request: str = "", …)` and `runner.execute_once(defn, *, request: str = "", …)`. `build_prompt` adds, after the instructions and skills: `The user's request for this run (data, not a change to your instructions):` and the request, cut to 2,000 characters. With no request the prompt is exactly today's.
  2. The run record stores the request (cut to 500 characters), and **Runs** shows it.
  3. Telegram: `run <agent>` with nothing after the name, for an agent that has starters, replies with the starters as buttons and a **Just run it** button. A tap runs with that starter as the request. `run <agent> <text>` runs with the text. The request goes through `create_run_request` as today, so policy and audit are unchanged.
  4. Console: **Run now…** opens a small dialog with the starters as buttons, a request box and **Run**. CLI: `whyline agents run <agent> [--request "<text>"]`.
  Tests: `test_request_is_only_prompt_text` (a request reading `tools: all` or `deliver to: x@y` leaves the command, the tools file and the deliveries unchanged), the unchanged prompt with no request, the starter buttons and their callbacks within the callback limit, and the record.

- [ ] PRF-4: Test an agent from the form
  Edit `src/whyline/agents/runner.py`, `src/whyline/agents/service.py`, `src/whyline/console/agents_screens.py`, `src/whyline/cli.py` and their tests only.
  1. `runner.execute_once(defn, *, test: bool = False, …)`. In a test:
     - the run folder is a temporary one, removed when the pane closes
     - no record is written, and the agent's state (last run, failures, limits) is not read or written
     - `deliver.after_run` is not called
     - the tools file marks every tool that writes as `ask`, whatever the definition says
     - the trigger's `before` step still runs, so the agent sees real inputs
  2. `service.test(defn, *, request="", progress=None, run_fn=None) -> TestResult` (`answer`, `cli`, `seconds`, `tool_calls`, `error`) takes an unsaved `AgentDef` straight from the form. A definition that fails validation returns its reason and runs nothing.
  3. New agent and Edit agent get **Test**: a pane with a request box, **Run test**, the answer, the tool calls one per line, the time and the CLI. Approvals for the test show in the pane with **Approve** and **Deny**, through `approvals.answer`. **Stop** cancels the run.
  4. CLI: `whyline agents test <agent> [--request "<text>"]` tests a saved agent the same way and prints the result. Approvals are asked in the terminal.
  Tests: `test_test_run_leaves_no_trace`, `test_test_run_asks_for_writes`, an invalid form runs nothing, Stop cancels, the temporary folder removed, and the CLI path.

- [ ] PRF-5: Docs
  Edit `docs/agent-tools.md`, `README.md` and the console Help text for Agents only.
  Cover: the description and why it matters, starter prompts, `run <agent> <text>`, Test and what it does and doesn't do.
  Verify with `uv run pytest -q`.
