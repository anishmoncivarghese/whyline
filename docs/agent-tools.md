# Tools, skills and knowledge for agents

A saved Agent can use **connectors** (MCP servers), **skills** and
**knowledge**. Open **Agents → Tools** to manage them, then tick what each
agent may use in **New agent**. Everything in the console has a terminal
counterpart for scripts.

## Connectors

A connector is a local MCP server: a command whyline starts, talks to over
stdin and stdout, and stops when the run ends. Remote servers (a `url`, or a
type of `http`, `sse` or `streamable-http`) are not supported yet.

- **Add** a name, a command, arguments, and the environment variables it
  needs, each pointing at a credential.
- **Import…** lists the servers already set up for Claude (`~/.claude.json`,
  Claude Desktop) and codex (`~/.codex/config.toml`). Those files are only
  read. Tick the ones to add. A secret written directly in an `env` value is
  never copied; the entry shows `needs a credential: <VAR>` and you choose one.
- **Test** starts the server and stores its tool list. Each tool shows
  `reads` or `writes`. If a server's tools change later, every agent using it
  needs review and does not run until you accept it again.
- **Remove** is refused while an agent uses the server, and names the agent.

Terminal: `whyline tools mcp list|add|remove|import|test`.

## Credentials

Credentials are stored in the macOS Keychain. A value is passed to a connector
only in its process environment, at start. It never appears in a command line,
a TOML file, a run record, a log, an error or a prompt, and it is not shown on
screen after you save it. Definitions refer to a credential by name only, so
an agent file can be committed safely. **Rotate** replaces the value;
**Remove** is refused while something uses it.

## Skills

A skill is a folder with a `SKILL.md` (a `name` and `description` in its front
matter, then instructions). Whyline reads four places, in this order:

1. `~/.whyline/skills/` — yours, for whyline
2. `<repository>/.whyline/skills/` — shared with the repository
3. `~/.claude/skills/` — Claude's, personal
4. `<repository>/.claude/skills/` — Claude's, in the project

Whyline skills can be created, edited and removed. Claude skills are read
where they are; use **Copy to whyline** to change one. A skill with no
description, or whose name doesn't match its folder, is listed as broken with
the reason. One skill is limited to 20,000 bytes and one agent's skills to
60,000.

Skills are instructions, because you chose them. Whyline copies each chosen
skill into the run folder and puts it in the prompt, so every CLI gets the
same skills, whether or not that CLI has a skill feature of its own.

Terminal: `whyline skills list|show|new|copy|edit|remove`.

## Knowledge

A knowledge pack is a named list of files, folders and web pages. Add one to
an agent, or add files and pages to the agent directly. Web pages are fetched
at the start of each run (http and https only, 2 MB and 30 seconds each),
turned into text, and saved in the run folder. A page that fails is noted with
its reason and the run goes on. Knowledge, and anything a tool returns, is
data, never instructions.

Terminal: `whyline knowledge list|show|add|remove`.

## Allowed and Ask first

For each tool an agent may use, choose:

- **Allowed**: the call goes ahead. This is the default for tools that read.
- **Ask first**: the call waits for you. This is the default for tools that
  write. Choosing Allowed for a writing tool shows `This tool can change
  things without asking you.`

A tool the agent didn't tick is not offered, and is refused if called.

## Approvals

An Ask first call waits for **Approve** or **Deny**:

- In the console, the Agents bar shows `Approvals 1` and the scheduler line
  says `waiting for you: <agent> wants <tool>`. Open **Approvals** to answer.
- From a terminal: `whyline agents approvals`, `whyline agents approve <run>
  <n>` and `whyline agents deny <run> <n>`.

If nobody answers within **10 minutes**, the call is denied
(`Not approved in time.`). A denied call returns `The user denied this call.`
to the agent, and the run goes on.

## Which CLIs can use tools

Whyline gives every CLI one `whyline` MCP server that forwards to the real
ones, asks for approval and records the calls.

| CLI | How it gets the server |
|-----|------------------------|
| claude | Per run, automatically |
| codex | Per run, automatically |
| grok | One-time setup |
| Antigravity | One-time setup |

For grok and Antigravity, run **Set up grok** or **Set up Antigravity** in
Agents → Tools → Connectors, or `whyline tools setup-grok` /
`whyline tools setup-antigravity`. Each asks first, then adds one saved
`whyline` entry to that CLI (`grok mcp add whyline -- whyline tools serve`,
and the same with `agy`). The screen shows whether it is ready. Antigravity
can save the entry now, but agents can't run on Antigravity yet.

In **New agent**, Main CLI and Backup CLIs offer only CLIs that can use the
agent's tools, with a line for each one left out and why. A run where none can
fails with `No CLI can use this agent's tools: <reasons>`.

## The call log

Every tool call is appended to `tool-calls.jsonl` in the run folder: time,
tool, arguments (credentials redacted, cut to 2,000 characters), decision
(`allowed`, `approved`, `denied` or `timed out`), duration, result size and
error. In **Agents → Runs**, a run's detail shows one line per call, for
example `12:04 gmail__send_email · approved · 1.2s`.
