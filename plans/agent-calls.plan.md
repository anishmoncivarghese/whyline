<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-11-14-agent-builder-design.md | created: 2026-11-15T00:00:00+05:30 -->
# Agent calls: an agent can hand part of its work to another agent

Spec: `docs/superpowers/specs/2026-11-14-agent-builder-design.md`, Part 3. Read it before every task. Where this plan and the spec differ, this plan wins. In particular:
- **An agent with a Can call list but no other tools still gets whyline's MCP server** for its run, so the called agents can be reached. On a CLI whose tool support is `none`, Can call is not offered.

Runs after `plans/agent-draft.plan.md`.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Why: each agent stands alone. A research agent can't hand a draft to a writing agent, and a morning brief can't ask the job-search agent for today's shortlist.

What the user gets:
- A **Can call** list on an agent, each entry **Allowed** or **Ask first**.
- The called agent runs as its own recorded run, with its own instructions and tools, and its answer goes back to the caller.
- Every call is shown under the caller's run, with limits: depth 2, no loops, 5 calls per run.

Rules every task keeps:
- **Console first.** The Can call list and the call history are in the Agents screens, through the same functions as `whyline agents …`.
- **A called agent uses only its own tools, skills, knowledge and permissions.** Nothing of the caller's is passed except the request text.
- **The request and the answer are data.** The request is cut to 4,000 characters and reaches the called agent as PRF-3's one-off request. The answer returns as tool result text, cut to 20,000 characters.
- **A called run never delivers.** Its deliveries are off for that run.
- **Limits are enforced by code in whyline's server and runner**, not by instructions to the agents.
- **Old agents keep working.** An agent without `calls` loads and keeps its hash and accepted state.
- **No new dependency.**
- **Tests:** never invoke a real provider, Telegram or an MCP server other than the fake one in the tools tests. Use temporary folders. Keep Python 3.11 compatibility.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- A called agent can't call another agent. CAL-3, `test_depth_is_two`.
- A loop (A calls A, or A → B → A) is refused when saved. CAL-1, `test_loops_are_refused`.
- A called run has only the called agent's tools, and sends no delivery. CAL-2, `test_called_run_is_isolated`.
- A sixth call in one run is refused. CAL-3, `test_five_calls_per_run`.
- A change to a called agent puts its callers into needs review. CAL-1, `test_callee_change_needs_review`.

- [ ] CAL-1: The Can call list in the definition
  Edit `src/whyline/agents/definitions.py`, `src/whyline/agents/service.py` and their tests only.
  1. `AgentDef` gets `calls: dict[str, str]` (agent name to `allowed` or `ask`), at most 8. `parse` reads it and `render` writes it only when set.
  2. Validation, making the agent broken with the reason:
     - an unknown agent, or one of another kind's scope that can't be found from this agent (`service.find`)
     - an unknown permission
     - itself
     - an agent with no description: `<name> needs a description before it can be called`
     - a loop through the saved lists: `<a> calls <b>, which calls <a>`
  3. `definition_hash` includes, for each called agent, that agent's own definition hash. An agent without `calls` hashes exactly as before.
  4. `service.callers_of(name, repo_root) -> list[str]`. `service.delete` refuses while an agent is called by another, naming the callers. Agents register their calls with `tools.users.register`.
  Tests: `test_loops_are_refused`, `test_callee_change_needs_review`, the unchanged hash without `calls`, the missing description, the cap of 8, and the refused delete.

- [ ] CAL-2: Running a called agent
  Edit `src/whyline/agents/runner.py`, `src/whyline/agents/records.py`, `src/whyline/agents/service.py` and their tests only.
  1. `runner.execute_once(defn, *, called_by: Caller | None = None, …)`. `Caller` has `agent`, `run_id` and `depth`. For a called run:
     - the source is `call`
     - `deliver.after_run` is not called, and failure alerts are not sent
     - the record stores `called_by` (agent and run id) and the request
     - the called agent's own tools file, skills, knowledge and CLI choice are built exactly as for a normal run
     - its time limit is its own `timeout_minutes`
  2. `service.call(caller: Caller, name, request, repo_root, *, run_fn=None) -> CallResult` (`ok`, `text`, `run_id`, `seconds`). It refuses, with a plain reason as `text`, when the called agent is not accepted, is paused, is broken, or needs review. The answer is cut to 20,000 characters with `… (cut; the full answer is in run <id>)`.
  3. `records` gains `calls_of(run_id) -> list[Record]`.
  Tests: `test_called_run_is_isolated` (the tools file holds only the called agent's tools, no delivery is sent, the caller's environment and folders are not passed), each refusal reason, the cut, and the linked records.

- [ ] CAL-3: Called agents as tools on whyline's server
  Edit `src/whyline/tools/serve.py`, `src/whyline/agents/runner.py`, `src/whyline/agents/capabilities.py` and their tests only.
  1. The run's `tools.json` gains `calls` (name, description, permission), `agent`, `run_id` and `depth`. `prepare_run` writes it, and starts whyline's server for an agent that has calls even when it has no other tools. `usable_clis` drops a CLI whose `tools_support` is `none` for such an agent.
  2. `tools/list` adds one tool per called agent: `agent__<name>`, the description `Ask the <name> agent: <its description>`, and the input schema `{request: string}`. With `depth` 1 or more, no `agent__` tools are listed.
  3. `tools/call` on `agent__<name>`:
     - refuses when the name is not in this run's `calls`: `This agent may not call <name>.`
     - refuses with `depth` 1 or more: `An agent that was called can't call another agent.`
     - refuses the sixth call in a run: `This run has used its 5 agent calls.`
     - for `ask`, goes through `approvals.request` with the tool shown as `call <name>` and the request as its argument
     - otherwise runs `service.call` with `depth + 1` and returns its text, with `isError` when it wasn't ok
  4. Each call is appended to `tool-calls.jsonl` like any tool call, with the called run's id.
  5. A called run's own approvals name both agents: `<called> (called by <caller>) wants <tool>`.
  Tests: `test_depth_is_two`, `test_five_calls_per_run`, the listed tools and none at depth 1, an unlisted agent refused, ask-first approved and denied, the call log line, and the approval wording.

- [ ] CAL-4: Can call in the console and CLI
  Edit `src/whyline/console/agents_screens.py`, `src/whyline/agents/draft.py`, `src/whyline/cli.py` and their tests only.
  1. New agent and Edit agent get a **Can call** section: **Add agents…** opens a checklist of the agents that have a description (not itself, and not ones that would make a loop, each shown greyed with the reason), with a permission select per entry defaulting to **Ask first**. The Review and detail screens show `Can call: <names>`.
  2. **Runs**: a run's detail lists its calls under it, `called <name> · <seconds>s · ok|failed`, each opening the called run. A called run shows `called by <agent>`.
  3. An agent whose called agent changed shows `needs review: <name> changed`, and Accept shows what changed in it.
  4. The drafter (`draft.library`, `build_prompt`, `validate`) now includes other agents (name and description) and may fill `calls`. Every drafted call is `ask`, and an unknown agent is removed and listed as missing.
  5. CLI: `whyline agents calls <agent> [--add <name> [--allowed]] [--remove <name>]`, and `whyline agents runs <agent>` shows calls indented under their run.
  Tests: the checklist with the greyed entries and reasons, saving through `definitions`, the run tree, the needs-review line, a drafted call set to ask, and the CLI.

- [ ] CAL-5: Docs
  Edit `docs/agent-tools.md`, `README.md` and the console Help text for Agents only.
  Cover: Can call and its permissions, that a called agent uses only its own tools, the limits (depth 2, 5 calls, no loops), why a caller needs review after a called agent changes, and how calls show in Runs.
  Verify with `uv run pytest -q`.
