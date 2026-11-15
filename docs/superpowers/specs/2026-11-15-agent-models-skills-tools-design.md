# Agents: pick a model per CLI, a skills catalogue, and tools you can find, add or make

Status: draft for review, 2026-11-15. Builds on agent tools (`plans/done/agent-tools.plan.md`, TLS-1..16, released in 0.3.74) and sits beside agent builder (`2026-11-14-agent-builder-design.md`). Five parts, each its own small plan, in the order below. Everything here is personal (`~/.whyline/`) and works in every repository.

## Where whyline stands (checked in the code, 2026-11-15)

- **Folder.** A personal agent's **Runs in** is a typed path that starts at `~`. There is no folder picker anywhere in the console and no setting for the starting folder.
- **Model.** New agent has one free-text Model box. The definition stores `model`, and **no run ever uses it**: `runner._command` builds the command from the relay config and never adds the model. Backups have no model at all. Model lists exist only for the relay, as a fixed list in `console/relay_ops.py` (`AGENT_MODELS`, `cached_model_options`).
- **Skills.** `tools/skills.py` finds skills in `~/.whyline/skills`, the repository's `.whyline/skills`, `~/.claude/skills` and the repository's `.claude/skills`. It can create, edit, remove and copy a Claude skill. It does not look at `~/.agents/skills` or `~/.codex/skills`, and nothing brings a skill in from outside this Mac. Whyline puts a skill's text into the prompt for every CLI, so any skill whyline holds already works with Claude, Codex, Antigravity and Grok.
- **Tools.** Tools → Connectors adds a local MCP server by its command, imports the ones Claude and Codex already have, tests it and stores its credentials in the Keychain. Remote (HTTP) servers are refused. There is no list to pick a connector from and no way to describe what you need.

## Problems

1. The model an agent is saved with is ignored, and the user has to know model ids by heart.
2. The skills picker offers only what happens to be on this Mac. Thousands of reusable skills exist in public catalogues and none can be reached from whyline.
3. Adding a tool means knowing an MCP server's command line. Gmail, Calendar and payment tools mostly need a browser sign-in, which whyline refuses.
4. Nothing separates a tool that reads from one that sends mail or moves money, beyond Allowed and Ask first.
5. Three defects found on the way (Part 0).

## Part 0: Three fixes (add to `plans/quick-fixes.plan.md`)

- **The focused checkbox hides its label.** Ten screens set `Checkbox { border: none; height: 1 }`. Textual's own `Checkbox:focus` rule puts the border back, and in a one-line widget the border covers the text. Add `border: none` for `:focus` in each, and one test that a focused checkbox still shows its label and its tick.
- **A test wrote into the real `~/.whyline`.** The `files` connector in Add tools (command `cmd`, hash `h1`) is fixture data from `tests/agents/test_definitions_tools.py`, written on 2026-11-14 during the agent-tools relay, with empty `skills` and `knowledge` folders beside it. Add a suite-wide guard that fails any test touching the real home, and fix the test that leaked. The leaked `files` connector is removed by hand in Tools → Connectors; whyline does not delete it for the user.
- **`read · writes`.** A tool whose server does not say whether it only reads is shown as `writes`. Show `not stated` and keep treating it as a writing tool.

## Part 1: A model for each CLI (plan `agent-models`)

- **The model is used.** A run adds the chosen model to the CLI's command through the relay's existing model flag (`whyline_relay.config.with_model`). A CLI with no model flag shows `This CLI has no model setting`.
- **One model per CLI.** The definition gets `[models]` (`claude = "sonnet"`, `codex = "gpt-5.6"`). An old `model` value is read as the main CLI's model. A CLI with no entry runs on its own default.
- **The form.** A Model dropdown sits next to Main CLI, and one next to each ticked backup. Each holds `Default (the CLI decides)`, the known models for that CLI, and `Other…` for a typed id. Picking a different Main CLI refills its dropdown.
- **Where the list comes from**, in this order, merged and cached for a day in `~/.whyline/models.json`:
  1. the CLI itself, where it has a command that lists models (Antigravity does today)
  2. whyline's built-in list, moved out of `relay_ops` into one module that the relay screens, Chat and New agent all read
  3. models the user added with `Other…`
  A **Refresh** button asks again. The list loads in the background and never holds up the form.
- **A model the CLI refuses.** The run retries once on the CLI's default, and the run record says `sonnet-9 was refused; ran on the default`. Review warns about a model not on the list and does not block.
- CLI: `whyline agents models <cli> [--refresh]`.

### Folders: Browse, and a default folder for new agents (same plan)

- **Browse…** sits beside **Runs in**. It opens a folder picker that starts at the current value, shows folders only, has **Up**, **Home**, **New folder** and a path box for pasting, and returns the chosen folder. Today the path has to be typed. The same picker, showing files too, replaces typing in Knowledge → **Add files**.
- **A default folder for new agents.** Settings gets an **Agents** section with `Default folder for new agents` and its own **Browse…**. A new personal agent starts with **Runs in** set to it, where it starts at `~` today. Changing the setting changes nothing for agents that already exist.
- **Where it is saved.** In the console's personal settings, not in any repository, so it is the same whichever repository is open.
- CLI: `whyline agents settings default-folder [PATH]`.

## Part 2: A skills catalogue (plan `skills-catalogue`)

- **Sources.** A source is a public git repository (or a local folder) that holds skill folders, each with a `SKILL.md`. Tools → Skills gets **Browse…** and **Sources…**. Whyline ships with three sources and the user can add any other by its URL:

  | Source | What it is (checked 2026-11-15) |
  |---|---|
  | `anthropics/skills` | Anthropic's own skills, in `skills/` |
  | `sickn33/agentic-awesome-skills` | about 2,950 skills in `skills/`, MIT code and CC BY 4.0 text |
  | `ComposioHQ/awesome-claude-skills` | skill folders at the top level; the repository states no licence |

  `VoltAgent/awesome-agent-skills` and `heilcheng/awesome-agent-skills` are lists of links, not skill folders. They are offered as **Directories**: whyline opens them in the browser, and **Add from a link** takes any GitHub link to a skill folder found there.
- **Browse.** One search box over name and description across all sources, with the source and licence on each row. A source is fetched with a shallow `git` clone into `~/.whyline/skill-sources/` on first use and on **Refresh**, never in the background.
- **Preview before install.** The whole `SKILL.md`, the file list, the size, the licence, and warnings from a fixed check: scripts in the folder, text that tells the agent to ignore its instructions, download-and-run commands, encoded blobs, anything the secret scan flags. Warnings never block; they are shown above the **Install** button.
- **Install** copies the folder to `~/.whyline/skills/<name>` with a `source.toml` (repository, path, commit, licence, date). From then on it is a whyline skill, usable by every agent on every CLI. When a skill of that name is already installed, Install asks for another name.
- **Update** shows the diff against the installed copy and asks. An agent that uses a skill whose text changed must be accepted again, the way a changed tool list already requires.
- **Skills already on this Mac.** `~/.agents/skills` and `~/.codex/skills` join the places whyline reads, with the origins `agents` and `codex`.
- **Write one with help.** **New skill** gets **Draft from a description**: the user says what the skill should teach, an agent writes the `SKILL.md`, and the user edits it before saving.
- **The picker.** Search box, full name, origin and the description on its own wrapped line, so nothing is cut off at the edge.
- CLI: `whyline tools skills sources`, `browse <text>`, `install <source>:<name>`, `update <name>`.

## Part 3: A connector catalogue, and Find a tool (plan `connector-catalogue`)

- **Pick from a list.** Tools → Connectors gets **Add from catalogue…**. Whyline ships a list (`connectors.toml`) of connectors that run as local commands. Each entry has a name, one line on what it does, the command, the credentials it needs with a link to where to get each, and its tools with their risk (Part 5). The first list covers files, web fetch, web search, a browser, GitHub, Slack, Notion, Linear, Postgres, SQLite, Gmail, Google Calendar and Google Drive. An entry ships only after someone ran its Test by hand on a real account; the entry records the date (`checked = "2026-11-20"`). The automated tests use a fake server.
- **Adding one** is four steps on one screen: what it will run and what it can do, the credentials (straight into the Keychain), **Test**, then the tool list. Nothing is enabled before Test passes.
- **Search more.** The same screen searches the public MCP registry. Results from there are marked `not checked by whyline` and go through the same four steps.
- **Find a tool.** A box in Add tools and in Tools: `What should the agent be able to do?` The answer is matched against installed connectors, the catalogue and the registry, in that order, and shown as a short list with **Add**. When nothing fits, it offers **Make a tool** (Part 4).

## Part 4: Make a tool (plan `made-tools`)

- **Web request tools first.** A made tool is a saved request: method, URL with named inputs, headers, a credential by name, and which part of the answer to return. No code. Whyline's own MCP server runs it, so every CLI can use it and approvals and the call log apply unchanged.
- **Described, then drafted.** The user describes the tool, an agent drafts the request from the service's public API pages, and whyline shows it in full. **Test** runs it with sample inputs. It must be accepted before any agent can use it, and any later edit needs accepting again.
- **Limits.** `https` only, no private or local addresses (the guard planned as WF-17), a response size cap, and a risk the user can raise but not lower below what the method implies (`GET` reads, everything else writes).
- **Script tools second.** A Python file in `~/.whyline/tools/<name>/` with declared inputs, for what a request can't do. Always **Ask first**, shown in full before accepting, run with no credentials except the ones it names.

## Part 5: Sign-in connectors, and tools that send or pay (plans `remote-connectors`, `tool-risk`)

- **Risk on every tool.** Four levels: `reads`, `writes`, `sends` (a message, mail or post that reaches other people) and `pays` (moves money or places an order). It comes from the catalogue entry, else from what the server states, else `writes`. The user can raise it.
- **What each level allows.**

  | Risk | Can be Allowed | Approval shows |
  |---|---|---|
  | reads | yes | nothing |
  | writes | yes, with the existing warning | the call |
  | sends | yes, per agent | who it goes to and the full text |
  | pays | never; always Ask first | amount, currency, who is paid, and today's total |

- **Limits for `pays`.** An agent can use a `pays` tool only after the user sets a limit per call and per day for that agent. A call over either limit is refused without asking. Approval is in the console or by the Telegram card, never by a rule. The catalogue entry says how to use the provider's test mode, and Test uses it.
- **Sign-in connectors.** Whyline accepts remote MCP servers over `https` with a browser sign-in. The token goes to the Keychain and is refreshed by whyline. Catalogue entries for hosted Gmail, Calendar and payment connectors come only after this and the risk levels are in.

## Goals

- Choose a model from a list for the main CLI and for each backup, and have it used.
- Find, read and install a public skill in under a minute, and use it from any CLI.
- Add a common connector without knowing its command, or describe what is needed and get a suggestion.
- A tool that sends or pays can never run without the user seeing exactly what it will do.

## Non-goals

- Publishing or sharing the user's own skills or tools.
- Auto-updating installed skills or connectors.
- Choosing a payment provider for the user, or holding money.
- Models, skills and tools in Chat and Relay beyond reading the shared model list.

## Anti-goals

- Skill text from the internet reaching an agent before the user has read it.
- A downloaded script running because a skill said so.
- A `pays` tool set to Allowed, by any route.
- Anything that depends on the repository selected in the console.
- A test that writes into the real `~/.whyline`.

## Constraints

- Console first: every command above has a console counterpart calling the same function.
- No new dependency. Sources are fetched with `git`; the registry and made tools use `urllib`.
- Tests never use the network, a real CLI or the real home.
- Existing agents load unchanged.

## Left to the builder

- The exact layout of Browse, Sources and the catalogue screens.
- Which CLIs besides Antigravity can list their own models, checked against the installed versions.
- The packages behind each catalogue entry, each proven by a passing Test.
- The registry's search address and paging.

## Calls I made (please check)

- One model per CLI on the agent, instead of one model for all, because a backup is a different CLI with different model names.
- The two link-list repositories are shown as directories and are not scraped: their links point at hundreds of repositories with their own licences.
- Installing is one skill at a time, with a preview. No "install all".
- A skill from a repository with no stated licence can be installed, with the missing licence shown in the preview.
- Web request tools come before script tools, because they need no code review.
- `pays` tools can never be Allowed, and hosted payment connectors wait for Part 5.
- Order: Part 0, models, skills, connector catalogue, made tools, then sign-in and risk. Parts 1 to 3 need nothing from each other and could run in any order.

## Questions for you

1. By "default folder where all agents are stored" I took you to mean the folder a new agent **runs in**. The agents' own definition files stay in `~/.whyline/agents/`. Say if you also want that location to be movable.
2. Which payment provider do you want first? It decides what the first `pays` entry and its test mode look like.
3. Sign-in connectors (Part 5) are the largest piece. Should hosted Gmail and Calendar wait for it, or should the catalogue ship first with the local-command Gmail and Calendar servers that use an API key or an app password?
4. Should `Find a tool` also search for skills, so one box answers "what should the agent be able to do"?
