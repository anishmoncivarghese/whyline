# Agent builder: describe it and get a draft, a fuller agent profile, and agents that call agents

Status: draft for review, 2026-11-14. Builds on saved agents (`whyline.agents`) and agent tools (`plans/agent-tools.plan.md`, TLS-1..16, running). Three parts, each its own small plan, in the order below. Runs after agent-tools is released.

## Where whyline stands

A saved agent today has a name, instructions, a main CLI with backups, a model, sources, a working folder, a `before` step, a trigger (manual, at a time, every N hours, a folder, mail) and deliveries (Telegram, email, a command). It is created in **New agent** from a blank form or a template, reviewed on a **Review** screen, and must be accepted before it runs (`service.accept`, with a definition hash).

Agent tools adds, per agent: **Skills**, **Knowledge** (files, web pages, packs) and **Tools** from MCP connectors, each **Allowed** or **Ask first**, served to the CLI by whyline's own MCP server for that run (`whyline tools serve`), with approvals and a tool-call log.

## Problems

1. **An agent has no description.** The list shows a name and a schedule. Nothing says what it is for, and nothing another agent or the Telegram router could read to decide when to use it.
2. **Creating one means filling a long form.** The user has to know which skills, tools and packs fit, write instructions from scratch, and pick a schedule and delivery. Templates cover six fixed cases.
3. **There is no way to try an agent before saving it.** The first real run is the test.
4. **An agent can't use another agent.** A research agent can't hand a draft to a writing agent. Each one stands alone.

## Part 1: A fuller profile, and Test (plan `agent-profile`)

- **Description.** One line, at most 200 characters, required for a new agent: what it is for and when to use it. Shown in the Agents list, the detail screen, `whyline agents list`, and Telegram's `status` and `run` replies. Existing agents load without one and show `No description — add one in Edit`.
- **Starter prompts.** Up to 4 short example requests an agent can be run with (`Summarise yesterday's mail`). They show as buttons in Telegram after `run <agent>` with no text, and in the console's Run now dialog.
- **Run with a request.** `run <agent> <text>` from Telegram and **Run now…** in the console pass a one-off request to the run. It is added to the prompt as the user's request for this run, after the instructions. Scheduled runs have none.
- **Test.** A **Test** button in New agent and Edit agent runs the agent once as it is on the form, without saving:
  - It uses a temporary run folder and never touches the agent's history or state.
  - Deliveries are not sent. The answer is shown in the form.
  - Tools marked **Ask first** ask in the Test pane itself. Tools that write are **Ask first** in a test whatever the form says.
  - The pane shows the answer, the tool calls, the time taken and which CLI ran.
- **A one-screen summary.** The Review screen and the detail screen show the agent as a profile: description, instructions (first lines, expandable), skills, knowledge, tools with their permission, agents it can call (Part 3), schedule, delivery.

## Part 2: Describe it, get a draft (plan `agent-draft`)

- **New agent** gets a first choice: **Describe it**, **Start from a template**, **Blank**.
- **Describe it.** The user types what they want, for example: `Every weekday morning, check my Gmail for invoices, add them to the Invoices sheet and tell me on Telegram what was added.`
- **One read-only drafting turn** (the assistant's main agent, then the backup) gets the description and the user's own library as data:
  - skills (name, origin, description)
  - connectors and their tools (name, description, reads or writes)
  - knowledge packs
  - other agents (name, description)
  - the CLIs that are enabled, and the delivery targets that are set up
- **It returns a draft**: name, description, instructions, skills, tools with a permission each, knowledge, agents it may call, a trigger, a delivery, up to 4 starter prompts, and a list of **what's missing**.
- **Only from the library.** Every skill, tool, pack, agent, CLI and delivery in the draft must exist. Anything else is removed and listed under what's missing, in plain words with where to add it: `Needs a Google Sheets connector. Add one in Agents → Tools → Connectors, then press Draft again.`
- **Safe defaults, whatever the draft says:**
  - a tool that writes is **Ask first**
  - a schedule more often than every 15 minutes is raised to 15
  - delivery goes only to the user's own Telegram chat or email
- **The draft opens in the New agent form**, every field filled and editable, with a line at the top: `Drafted from your description. Check each section before saving.` Fields the drafter chose are marked `drafted`. Nothing is saved until the user presses Save, and the saved agent still needs Accept, as today.
- **Refine.** A **Change it** box under the form takes a follow-up (`make it weekly, and add the finance pack`) and redrafts, keeping the fields the user edited by hand.
- **From Telegram.** `new agent <description>` replies with the draft as a summary and the buttons **Open in console** and **Discard**. Saving and accepting stay in the console, because the full review needs the form.
- **CLI.** `whyline agents draft "<description>"` prints the draft as the agent file it would write, and what's missing. `--save` writes it, still not accepted.

## Part 3: Agents that call agents (plan `agent-calls`)

- **Can call.** An agent gets a list of other agents it may call, chosen in the form from the agents that have a description. Each has a permission: **Allowed** or **Ask first**.
- **A called agent is a tool.** Whyline's MCP server for the run (`whyline tools serve`) lists each one as `agent__<name>`, with the called agent's description as the tool description and one argument, `request` (text). The calling CLI needs nothing new.
- **A call is a real run.** It runs the called agent with the request, through the same runner, as its own recorded run:
  - with the called agent's own instructions, skills, knowledge, tools and permissions, never the caller's
  - with its deliveries off: the answer goes back to the caller as the tool result
  - linked to the caller's run, and shown under it in **Runs** as `called summariser · 42s · ok`
  - cut to 20,000 characters in the tool result, with the full answer in the called run's folder
- **Limits.**
  - Depth 2: an agent called by an agent can't call a third.
  - No loops: an agent can't call itself, and A → B → A is refused when the list is saved.
  - At most 5 calls per run, and each call has the called agent's own time limit.
  - A called agent must be accepted and not paused. Otherwise the tool returns `That agent isn't ready: <reason>`.
  - A called agent's **Ask first** tools still ask, and the approval card names both: `summariser (called by daily-brief) wants gmail__send_email`.
- **Changes need review.** The caller's definition hash includes the hash of each agent it may call. When a called agent's instructions or tools change, the caller shows `needs review` and doesn't run until accepted. This is the rule TLS-7 sets for a connector whose tools changed.
- **Router.** The Telegram router (`plans/assistant-router.plan.md`) may choose `run <agent>` for a plain message, using the descriptions. This plan only gives it the descriptions; the router's rules don't change.

## Goals

- A useful agent in a minute: describe it, check it, test it, save it.
- Every agent says what it is for.
- Agents can be composed, and every call is visible, limited and reviewable.

## Non-goals

- A visual canvas, or publishing agents to other people or channels.
- Agents that create or edit other agents.
- A marketplace of agents or connectors.
- Conversation memory for an agent across runs (the assistant's memory plan covers the assistant).

## Anti-goals

- A draft that invents a tool, a connector or a credential.
- A drafted agent that runs before the user saved and accepted it.
- A called agent using the caller's tools, or the caller using the called agent's.
- A chain of agents the user can't see or stop.
- Text from a description, a web page or a called agent's answer choosing a tool, a recipient or a schedule. The draft is validated against the library, and a called agent's answer is data to the caller.

## How it fits the code today

- `agents/definitions.py`: `AgentDef` gains `description`, `starters` and `calls`. `parse`, `render`, `definition_hash` and validation extend as TLS-7 extends them for skills, knowledge and tools.
- `agents/runner.py`: `build_prompt` gains the one-off request. `execute_once` gains a test mode (a temporary folder, no deliveries, no state) and a called mode (deliveries off, a parent run id).
- `agents/service.py`: `describe`, `rows`, `save_new`, `accept`, `run_now`.
- `agents/templates.py`: `build` already turns a template into an `AgentDef` for the form. A draft enters the form the same way.
- `tools/serve.py`, `tools/approvals.py` (TLS-9, TLS-10): the per-run server lists `agent__<name>` tools and runs them; approvals name the caller.
- `tools/skills.py`, `tools/mcp_config.py`, `tools/knowledge.py`: the library the drafter is given, and what a draft is validated against.
- `ideas/assistant.py`: the drafting turn uses the assistant's main and backup agent, the same read-only turn `propose` runs. `ideas/bot.py` gets `new agent`.
- `console/agents_screens.py`: `AgentTemplateScreen` (first step of New agent), `NewAgentScreen`, `ReviewScreen`, `AgentDetailScreen`, `RunsScreen`.

## Calls I made (please check)

- **A called agent is exposed as an MCP tool** on whyline's own per-run server. It needs no change in any CLI, and it reuses the approvals and the call log.
- **Depth 2 and 5 calls per run.** Enough for "researcher hands to writer", and small enough to follow.
- **Drafted writing tools are always Ask first.** The user can change one to Allowed in the form, with the warning TLS-14 already shows.
- **Saving and accepting a drafted agent happen in the console only**, not from Telegram.
- **The description is required for new agents and optional for old ones**, so nothing breaks on upgrade. An agent without one can't be called by another.
- **Order:** profile first (the other two need the description), then draft, then calls.
