# Tools, skills and knowledge for agents

Status: draft for review, 2026-11-10. Runs before `plans/workflows-2-to-4.plan.md`, which keeps only the Workflows side.

## Problem

An agent in **Agents → New agent** can read files (**Sources**) and nothing else. It can't search Notion, read a Google Sheet, file a GitHub issue or send a Slack message, and it can't reuse a skill the user wrote once. Claude users have MCP servers and skills already, but those only reach Claude, and only through Claude's own settings. Whyline runs codex, grok and Antigravity too, and switches to a backup CLI when the main one fails, so anything tied to one CLI breaks the moment another one runs.

The Workflows plan (Part 2) planned an MCP registry and client for workflow steps. Agents need the same registry, the same credentials and the same client, so they move into one shared plan that runs first.

## What the user gets

### One tools library

A **Tools** button in the Agents bar opens the library, with four tabs. Everything in it is personal (in `~/.whyline/`), usable by any agent in any repository, and later by Workflows.

- **Connectors**: MCP servers. **Add** (command, arguments, environment variables mapped to credentials), **Import…** (a checklist of the servers already in `~/.claude.json`, Claude Desktop's config and `~/.codex/config.toml`), **Test** (starts the server and lists its tools), **Remove** (refused while an agent uses it, naming the agents). Each server shows its tools, each marked **reads** or **writes** from the server's own `readOnlyHint` (a tool with no hint counts as writes).
- **Skills**: skills in the Agent Skills format (a folder with `SKILL.md` that has `name` and `description` front matter). Whyline finds them in four places and shows where each came from:
  - whyline personal: `~/.whyline/skills/<name>/`
  - whyline repository: `<repo>/.whyline/skills/<name>/`
  - Claude personal: `~/.claude/skills/<name>/`
  - Claude project: `<repo>/.claude/skills/<name>/`

  **New skill** writes a whyline skill (name, description, body). Claude skills are read where they are and never changed. **Copy to whyline** makes an editable whyline copy. A whyline skill and a Claude skill with the same name are both shown; the agent form says which one it uses.
- **Knowledge**: reusable **knowledge packs**, each a named list of files, folders and web pages. Today's per-agent Sources still work.
- **Credentials**: API keys and tokens, stored in the macOS Keychain (Linux: Secret Service). Values are typed into a masked field, never shown again, and never written to a file, an argument list, a log or a prompt. A server gets a credential only as an environment variable at start.

### The New agent form

Three sections replace **Sources**:

- **Knowledge**: **Add files**, **Add web page**, **Add pack**, and the list.
- **Skills**: **Add skills…** opens a checklist of the library's skills with their origin and description.
- **Tools**: **Add tools…** opens the connectors, each expandable to its tools. A ticked tool gets a permission:
  - **Allowed**: the agent uses it without asking.
  - **Ask first** (the default for a tool that writes): the run waits for your approval for each call.
  Reading tools default to Allowed.

**Review** lists them before saving, for example: `Can read: notion.search, github.list_issues · Can write: gmail.send_email (ask first) · Skills: research-digest (whyline), pdf (Claude) · Knowledge: 2 folders, 1 web page, pack "company"`.

The **Main CLI** and **Backup CLIs** lists only offer CLIs that can use what the agent needs (below), and say why one is missing, for example `grok · needs one-time tools setup`.

### Every CLI gets the same skills

Skills are delivered by whyline, not by the CLI, so they work the same in claude, codex, grok and Antigravity, and when a backup takes over:

- The prompt gets a **Skills** block: each selected skill's name, description and full `SKILL.md` body. The body is treated as instructions from the user, because the user chose the skill.
- A skill's other files (scripts, references) are copied into the run folder (`<run>/skills/<name>/`) and listed by path, and the CLI gets read access to that folder where it supports it (`--add-dir` for claude and codex).
- Limits: 20 KB per `SKILL.md`, 60 KB for all skills in one agent. Saving an agent over the limit is refused with the sizes.

Knowledge works the same way: files and folders are listed by path as today. Web pages are fetched at run start into `<run>/knowledge/` as text (at most 2 MB each, http and https only), so every CLI reads a local file. Knowledge content is data, not instructions.

### Every CLI gets the same tools, through whyline

Whyline doesn't hand the real servers to the CLI. It hands it **one** MCP server, whyline's own (`whyline tools serve`), which:

- offers only the tools this agent ticked, named `<server>__<tool>`
- starts the real servers itself when a tool is first called, with their credentials in the environment
- forwards each call and returns the result
- waits for approval on **Ask first** tools
- writes every call to the run's record (tool, arguments with credentials redacted, allowed or approved or denied, result size and time)

How each CLI is pointed at it:

| CLI | How | Setup |
|---|---|---|
| claude | `--mcp-config <run file> --strict-mcp-config --allowedTools mcp__whyline__*` on each run | none |
| codex | `-c mcp_servers.whyline.command=…` and `.args=…` on each run | none |
| grok | grok has no per-run option, so one saved entry, `grok mcp add whyline -- whyline tools serve`, added once by **Set up grok** in the library. The server reads which run it serves from the environment. Outside a whyline run it offers no tools | once |
| Antigravity (`agy`) | not supported until its MCP support is checked. An agent with tools doesn't offer it | — |

So the user's own Claude, codex and grok settings are never changed, except the single `whyline` entry for grok, which the user adds with a button.

### Approvals

- An **Ask first** call pauses that call (not the whole run) and shows it in **Agents → Runs**: `research-digest wants to use gmail.send_email: to=…, subject=…` with **Approve** and **Deny**. `whyline agents approve <run> <n>` and `deny` do the same.
- Scheduled runs wait the same way. A call not answered in 10 minutes is denied, and the agent is told `Not approved in time`.
- A denied call returns `The user denied this call` to the agent, which carries on without it.
- Tool results are outside data. The prompt says so, as it does for Sources.

## Storage

- `~/.whyline/mcp.toml` (0600): one `[servers.<name>]` table per server (`command`, `args`, `cwd`, `env` as variable → credential name, `enabled`, `tools_hash`, and the last tested tool list).
- `~/.whyline/credentials.toml` (0600) holds credential metadata. Values are in the Keychain.
- `~/.whyline/skills/` and `~/.whyline/knowledge/<pack>.toml`.
- The agent's TOML gains `skills` (a list of `origin:name`, for example `whyline:research-digest`, `claude:pdf`), `knowledge` (paths, URLs and `pack:<name>`, replacing `sources`, which still loads), and `[tools]` (`"<server>.<tool>" = "allowed" | "ask"`).
- A changed tool list on a server (a different `tools_hash`) puts every agent that uses it in **needs review**, like an edited definition today. It doesn't run until accepted again.

## What moves out of the Workflows plan

- WF-14 (credential store) moves here whole.
- WF-15 keeps only what is about workflows: `needs_credential`, the workflows-using column, and testing a credential with an HTTP request. The `whyline cred` CLI and the Credentials screen move here.
- WF-27 (MCP registry and import) and WF-28 (MCP client) move here, in `whyline.tools` instead of `whyline.workflows`, at `~/.whyline/mcp.toml` instead of `~/.whyline/workflows/mcp.toml`.
- Workflows keeps the integration: the `mcp` step (WF-29), the step picker (WF-31) and its docs. WF-27 becomes a small task that registers workflows as users of servers, and links Workflows' connectors section to the shared library.

## Goals

- Add a connector, a skill or a knowledge pack once; use it from any agent and any CLI.
- Agents can use tools that write, with **Ask first** as the default and every call recorded.
- No change to the user's CLI settings beyond the one grok entry they choose to add.

## Non-goals

- Remote (HTTP, SSE) MCP servers and OAuth sign-in. Local command servers only, as Workflows planned.
- A skill marketplace or sharing skills between people.
- Search over knowledge (embeddings, retrieval). Knowledge is files the agent reads.
- Tools in Chat, Relay or Assistant. Those can follow later, through the same proxy.

## Anti-goals

- A credential value anywhere outside the Keychain and a server's environment.
- Changing the user's `~/.claude.json`, codex config or Claude skills.
- A tool that writes running without the user having chosen Allowed for it.
- Skills that only work when Claude runs.

## Constraints

- Console first: every CLI command has a console counterpart calling the same function.
- No new dependency. The MCP client and whyline's MCP server are written with `subprocess` and `json` (JSON-RPC 2.0, one message per line).
- Tests never start a real vendor server, a real agent or use the network. They use a fake MCP server script.

## How it fits the code today

- **Agents:** `whyline.agents.definitions.AgentDef` (TOML, with `sources`), `runner.build_prompt` and `runner._command` (which wraps every CLI in `capabilities.read_only_command`), `records.run_folder(run_id)` for the run folder, and `console/agents_screens.py` for the New agent form (the `na-*` fields).
- **Read-only runs:** agents stay read-only for files and shell. Tools are the one way they act, and only through whyline's server, so every write is a tool call that is recorded and, by default, approved.
- **New code:** `src/whyline/credentials.py` (as WF-14 planned), `src/whyline/tools/` (`mcp_config.py`, `mcp.py`, `serve.py`, `approvals.py`, `skills.py`, `knowledge.py`, `cli.py`), `src/whyline/console/tools_screens.py`.

## Left to the builder

- Layout of the library tabs and the pickers, within the console's style.
- How a long tool list is grouped in the picker.

## Calls I made (please check)

- One whyline MCP server in front of all real servers, instead of handing each CLI the real servers. It is what makes approvals, recording and grok possible.
- Skills are put into the prompt by whyline for every CLI, including Claude, rather than loaded by Claude natively. The same agent then behaves the same whichever CLI runs it.
- Writing tools default to **Ask first**; scheduled runs wait up to 10 minutes for approval, then deny.
- Antigravity gets no tools until its MCP support is checked.
- The library is personal (`~/.whyline/`), not per repository, except whyline repository skills, which live in the repository so they travel with it.
