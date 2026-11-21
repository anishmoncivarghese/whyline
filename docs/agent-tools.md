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

## Choosing a model per CLI

In **New agent**, Main CLI and each ticked backup have their own model
dropdown. It holds **Default (the CLI decides)**, the models whyline knows for
that CLI, and **Other…** for an id you type. **Default** passes no model, so
the CLI uses whatever it would use on its own. A CLI with no model setting
shows a disabled dropdown. **Refresh models** asks each CLI for its current
list (only Antigravity has one to ask for; the rest use whyline's built-in list
plus your additions). The run uses the model of the CLI that actually runs, so
a backup runs on its own model, not the main one's. If a CLI refuses a model
(`model not found`, `unknown model`), the run is tried once more on that CLI's
Default, and the run record says so, before any backup is tried.

Terminal: `whyline agents models <cli> [--refresh] [--add ID | --remove ID]`
and `--model-for <cli>=<id>` on `whyline agents new` and `edit`.

## Browse and the default folder

**Browse…** next to **Runs in**, and on knowledge **Add files**, opens a folder
and file picker with Up, Home, New folder…, a path box (`~` works) and Show
hidden. It only ever returns a folder or file that exists. A new agent starts
in the **Default folder for new agents** (Settings → Agents, or
`whyline agents settings default-folder [PATH]`); with none set, that is your
home folder. Changing it does not touch existing agents.

## Finding skills: sources, preview and install

Skills are also read from `~/.agents/skills` and `~/.codex/skills`, after the
four places above. The same skill in two places is listed once.

**Skills → Browse…** searches public skill **sources**: repositories of skill
folders. Built in are Anthropic's, `agentic-awesome-skills` and Composio's,
plus two directories that only open in your browser. **Sources…** adds your
own `https://` repository, turns one off, refreshes it or removes it. A source
is downloaded (a shallow `git` clone under `~/.whyline/skill-sources/`) only
when you first browse it or press Refresh, never in the background.

Choosing a result opens a **preview** before anything is installed: the
warnings first, then the licence, size, file list and the whole `SKILL.md`.
Warnings never block; they are things to read before you decide:

- `contains scripts: …`: the folder has `.py`, `.sh`, `.js`, `.rb` or `.ps1`
  files, or executable files.
- `tells the agent to ignore its instructions`: text such as "ignore previous
  instructions".
- `downloads and runs something`: `curl … | sh`, `pip install`, `npx` and the
  like.
- `long encoded text`: a long run of base64.
- a secret-looking value, named by rule only.

The **licence** shown is the source's; `no licence stated` means the source
says none, so check the project before relying on it. **Install** and
**Install as…** copy the folder to `~/.whyline/skills/<name>` and record where
it came from. **Nothing from a skill is run.** Whyline copies the files and
puts the `SKILL.md` text in the prompt; scripts in the folder are never
executed by whyline. A folder with a symlink or a path that leaves it is
refused. **Update…** shows a diff against the source; an agent using an
installed skill whose text changed must be accepted again. **Add from a
link…** takes a `https://github.com/<owner>/<repo>/tree/<branch>/<path>` link
to one skill folder. **Draft from a description…** under New skill has an
agent write a `SKILL.md` for you to edit; nothing is saved until Save.

Terminal: `whyline tools skills sources|browse|show-remote|install|update`.

## The connector catalogue

**Connectors → Add from catalogue…** lists ready-made local connectors (files,
web fetch and search, a browser, GitHub, Slack, Notion, Linear, Postgres,
SQLite, Gmail, Google Calendar and Drive). Each shows the exact command it
will run, its tools with their risk level, and a box for each credential with a
link to where you get it. **Test** must pass before **Add** is enabled, and a
connector is never turned on before its Test passed. If the Test fails it stays
saved but off, with the reason.

`not checked by whyline yet` means nobody has run that entry's Test against a
real account. The command comes from the project's own page, but whyline has
not confirmed it works; your own Test is the check. **Search more…** looks in
the public MCP registry and lists results under `From the public registry ·
not checked by whyline`. Registry servers that are remote (they need a browser
sign-in) are listed with the reason and no button.

Terminal: `whyline tools catalogue [TEXT]`, `catalogue add <name>`,
`catalogue search <text>`.

## Find

The box `What should the agent be able to do?` (in Add tools and the Tools
library) matches your words against connectors you have, the catalogue, skills
in your library and skills in sources you already fetched, with up to five
hits per kind and a button for each (**Tick its tools**, **Add…**, **Add
skill**, **Preview…**). **Search the registry too** is a separate button, so
nothing goes to the network unasked. With no hit, **Make a tool…** is offered.
Terminal: `whyline tools find <text> [--registry]`.

## Made tools

A **made tool** is a saved web request, for a service with no connector.
Describe it and an agent drafts it, or fill the form: method, `https` URL with
`{input}` places, headers, query, a JSON body, its inputs, a credential (kept
in the Keychain, sent in a header or query) and which part of the answer to
return. Limits:

- `https` only. A host that is an IP address, `localhost`, or resolves to a
  private, loopback or link-local address is refused, and so is a redirect to
  another host.
- A request waits 15 seconds and reads at most 200,000 bytes.
- A credential can't go in the URL path, and a tool that isn't `GET` is at
  least `writes`.
- A made tool can't run until you press **Accept**. Editing it clears the
  acceptance, and agents using it need accepting again.

**Test…** shows the exact request (the credential as `•••`), asks `Send it?`
and shows the answer. **A Test really sends the request.** For a tool above
`reads` it says `This test really does it`. Agents name a made tool as
`made.<name>`. Terminal: `whyline tools made list|show|new|test|accept|remove`.

## Risk levels and limits

Every tool has one of four levels, rising in order:

| Level | Meaning |
|-------|---------|
| `reads` | Looks only. |
| `writes` | Changes something. A tool that doesn't say whether it reads is `not stated` and counts as `writes`. |
| `sends` | Sends a message or email to someone. |
| `pays` | Moves money. |

A level can be raised (**Risk…**, `whyline tools risk <server>.<tool> [LEVEL]`),
never lowered. A `sends` tool set to Allowed shows `This agent will be able to
send without asking.` Approvals for `sends` show the recipient and full text.

A `pays` tool can only be **Ask first**, in the form, a hand-edited file and
the CLI, and each call asks, whatever you answered before. Ticking one needs a
**Limit per call**, **Limit per day** and **Currency**
(`whyline agents limit <agent> <server>.<tool> --per-call N --per-day N
--currency C`). Without limits it can't be called. A call over a limit, in a
different currency, with an amount whyline can't read, or with no `pay` hints
for the tool is refused without asking. The approval shows `Pay 12.50 EUR to
<payee> · today so far 30.00 of 100.00`.

**Not in this release:** connectors that need a browser sign-in (remote
servers), and catalogue entries that pay. Pay-capable tools can be added only
as a connector you set up yourself, with limits.
