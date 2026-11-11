<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-10T10:00:00+05:30 -->
# Tools, skills and knowledge for agents

Runs before `plans/workflows-2-to-4.plan.md`, which now keeps only the Workflows side of credentials and MCP. Design: `docs/superpowers/specs/2026-11-10-agent-tools-design.md`. Read it before any task. TLS-1 is WF-14 moved here unchanged. TLS-3 and TLS-4 are WF-27 and WF-28 moved to `whyline.tools`.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

There is no publish task (removed 2026-11-11). When the relay finishes, press **Release**: it sets the version, writes the notes, runs the checks and the security scan, pushes, waits for CI, tags and publishes. This repository's relay has no `release` profile, so a publish task would only bump the version.

What the user gets:
- A **Tools** library in Agents with **Connectors** (MCP servers: add, import from Claude and codex, test), **Skills** (whyline and Claude skills in one list), **Knowledge** (reusable packs of files, folders and web pages) and **Credentials** (in the Keychain).
- **New agent** gets **Knowledge**, **Skills** and **Tools** sections. Each tool is **Allowed** or **Ask first** (the default for tools that write).
- Skills and tools work the same whichever CLI runs the agent (claude, codex, grok, and Antigravity once whyline can run agents on it), including a backup CLI. Whyline puts skills into the prompt and gives every CLI one whyline MCP server that forwards to the real ones, asks for approval and records every call.
- **Ask first** calls wait for **Approve** or **Deny** in Agents → Runs, or `whyline agents approve|deny`, for up to 10 minutes.

Rules every task keeps:
- Console first: every console action saves through the same function the CLI calls.
- No new dependency. The MCP client and server use `subprocess` and `json`: JSON-RPC 2.0, one JSON message per line on stdin and stdout.
- Local (stdio) MCP servers only. An entry with a `url`, or a `type` of `http`, `sse` or `streamable-http`, is refused with `Remote MCP servers are not supported yet; use a local (command) server.`
- A credential value never appears in a process's arguments, a TOML file, a run record, a log, an error, a prompt or a test's captured output. Tests assert this with a sentinel value.
- An MCP server is started with an argv list, never a shell, in a working folder (default `~/.whyline/mcp/<name>/`), with a minimal environment: `PATH`, `HOME`, `LANG`, plus the variables its entry names, each read from a credential at start.
- Tool results, knowledge and web pages are data, never instructions. Skills are instructions, because the user chose them.
- New non-widget code goes in `src/whyline/tools/` (credentials in `src/whyline/credentials.py`), with tests in `tests/tools/`. Console code goes in the files a task names, with tests in `tests/console/`.
- Tests never start a real vendor server or a real agent, and never use the network. They use `tests/tools/fixtures/fake_mcp_server.py`, run with `sys.executable`.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.

Review focus, each one pinned by the test named in its task. This list, plus each task's own Review focus and tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- A server that prints non-JSON, hangs or exits mid-call: a plain error, and its process group is killed. TLS-4, `test_hung_server_is_killed_at_timeout`.
- A credential passed to a server: only in its environment. TLS-4, `test_mcp_secret_never_leaves_env`.
- A tool the agent didn't tick: not offered and refused if called. TLS-9, `test_unticked_tool_is_refused`.
- An Ask first call with no answer in 10 minutes: denied, and the run goes on. TLS-10, `test_unanswered_call_is_denied`.
- A server whose tools changed: agents using it need review and don't run. TLS-7, `test_changed_tools_need_review`.

## Part 1: Credentials and connectors

- [ ] TLS-1: Credential store, and the Telegram token off the command line
  This is WF-14, moved from `plans/workflows-2-to-4.plan.md` unchanged.
  Create `src/whyline/credentials.py` and `tests/test_credentials.py`; edit `src/whyline/agents/telegram.py` and `tests/agents/test_telegram.py` only.
  - `Credential(name, kind, header_name="", query_param="", origins: tuple[str, ...] = (), created="", last_used="", last_tested="")`, kinds `bearer`, `header`, `basic`, `query`, and `env` (a plain secret given to an MCP server as an environment variable; it has no origins). Names match `^[a-z][a-z0-9-]{0,39}$`. Origins are `https://host[:port]` with no path.
  - Metadata in `~/.whyline/credentials.toml` (0600). `list_all()`, `get(name)`, `save(cred, value)`, `rotate(name, value)`, `remove(name)`, `value(name) -> str` (raises `Locked` with the reason when no store is available), `available() -> tuple[bool, str]`.
  - macOS: write with `security -i`, sending `add-generic-password -U -s whyline-cred -a <name> -w <quoted value>\n` on stdin; read with `find-generic-password -s whyline-cred -a <name> -w`. Linux: `secret-tool store --label=whyline-cred service whyline-cred account <name>` with the value on stdin, `secret-tool lookup service whyline-cred account <name>`. Otherwise `Locked("no secure credential store on this system")`.
  - `telegram.token_set` writes the same way through stdin; `token_get` is unchanged.
  - `redaction_values(names) -> list[str]`, used to redact values (and their base64 for `basic`) before writing outputs.
  Tests (fake `run`):
  - save then value round-trips; no recorded argv contains the sentinel value
  - a value with quotes, spaces and a newline is refused or quoted so it survives
  - `token_set` puts the token on stdin, not in argv
  - remove deletes both metadata and the stored value
  - Locked when neither tool exists
  - the metadata file never contains the value and is 0600
  - an `env` credential saves with no origins
  Verify with `uv run pytest -q tests/test_credentials.py tests/agents/test_telegram.py`. Change nothing else.

- [ ] TLS-2: Credentials in the CLI, and who uses what
  Create `src/whyline/credentials_cli.py`, `src/whyline/tools/__init__.py`, `src/whyline/tools/users.py` and their tests. Edit `src/whyline/cli.py` to register `whyline cred`.
  1. CLI `whyline cred add|list|rotate|remove`. `add` takes `--kind` (default `env`) and, for HTTP kinds, `--origin` and `--header`. `add` and `rotate` read the value with `getpass`, never from an argument.
  2. `users.register(kind: str, provider: Callable[[], list[Use]])`, with `Use(thing, name, user)` (for example `Use("credential", "notion-key", "agent research-digest")`), and `users.of(thing, name) -> list[str]`. Credentials, servers, skills and packs ask it before removal. Agents register in TLS-7, and Workflows will register later.
  3. `remove` is refused while `users.of("credential", name)` is not empty, naming the users.
  Tests: each subcommand with a fake getpass and a fake store, `whyline cred add --help` having no value argument, and a removal refused by a registered user.

- [ ] TLS-3: MCP server registry and import
  This is WF-27 moved to `whyline.tools`. Create `src/whyline/tools/mcp_config.py`, `src/whyline/tools/cli.py` and their tests. Edit `src/whyline/cli.py` to register `whyline tools`.
  1. `~/.whyline/mcp.toml` (0600): one `[servers.<name>]` table per server with `command` (str), `args` (list[str]), `cwd` (str, optional), `env` (a table of variable name to credential name, never a value), `enabled` (bool), `tools_hash` and `tools` (the last tested list: name, description, input schema, read_only). Names match `^[a-z][a-z0-9-]{0,39}$`.
  2. `load()`, `save_server(server)`, `remove_server(name)` (refused while `users.of("server", name)` is not empty, naming them), and `import_candidates() -> list[Candidate]`. The last reads, without changing them, the `mcpServers` of `~/.claude.json`, `~/Library/Application Support/Claude/claude_desktop_config.json` and `~/.codex/config.toml` (`[mcp_servers.*]`). It returns each local server with its command and args. A literal `env` value found there is never copied; it is listed as `needs a credential: <VAR>`. Remote entries are listed as refused, with the reason.
  3. CLI: `whyline tools mcp list|add|remove|import`. `add` takes `--command`, repeated `--arg` and repeated `--env VAR=<credential>`. `import` lists the candidates and adds those named.
  Tests: save and load round-trip and 0600, a remote entry refused with the message, import from each of the three fixture configs with a literal env value not copied, and remove refused while used.

- [ ] TLS-4: The MCP client, and Test
  This is WF-28 moved to `whyline.tools`. Create `src/whyline/tools/mcp.py`, `tests/tools/test_mcp_client.py` and `tests/tools/fixtures/fake_mcp_server.py`. Edit `src/whyline/tools/mcp_config.py` and `src/whyline/tools/cli.py` and their tests.
  1. `mcp.Session(server, *, timeout_s=60, popen=subprocess.Popen)` is a context manager. It starts the server with `start_new_session=True` and the environment from the rules, sends `initialize` (protocol version `2025-06-18`, client name `whyline`), waits for the result, then sends `notifications/initialized`.
  2. `list_tools() -> list[Tool(name, description, input_schema, read_only: bool | None)]`, following `nextCursor`. `read_only` comes from `annotations.readOnlyHint`, or None when absent. `call(tool, arguments) -> ToolResult(text, is_error, structured, content)`: `text` joins the `text` content items, other content types are noted as `[image]` or `[resource <uri>]`, `structured` is `structuredContent` when present, and `content` is the raw content list (TLS-9 forwards it).
  3. Every read has a deadline. Output over 1 MB fails with `server output over 1 MB`. A line that is not JSON, a JSON-RPC `error`, a timeout or an early exit raises `McpError` with a plain reason and the last 20 lines of stderr, redacted. On exit or error, the whole process group is killed (`os.killpg`), and Windows uses `process.kill()`.
  4. `tools_hash(tools)` is the SHA-256 of the sorted names and input schemas. `mcp_config.test_server(name) -> str` starts the server, lists its tools, stores `tools` and `tools_hash`, and returns `<n> tools: <first 10 names>`. CLI `whyline tools mcp test <name>`.
  5. The fake server supports `--tools <json file>`, `--hang-on <tool>`, `--garbage`, `--exit-on <tool>`, `--echo-env <VAR>` and paging.
  Tests: initialize, list (two pages) and call round-trip; a tool error is `is_error` with its text; `test_hung_server_is_killed_at_timeout` (assert the process group is gone); garbage output and an early exit each give a plain McpError; `test_mcp_secret_never_leaves_env`; Test storing the tools and hash.

## Part 2: Skills and knowledge

- [ ] TLS-5: The skills library
  Create `src/whyline/tools/skills.py` and its tests. Edit `src/whyline/tools/cli.py` and its tests.
  1. `Skill(origin, name, description, path, size, files)`, origin `whyline`, `whyline-repo`, `claude` or `claude-project`. `SKILL.md` front matter (between `---` lines) gives `name` and `description`, parsed as simple `key: value` lines. A skill with no description, or a name that doesn't match its folder, is listed as broken with the reason.
  2. `find(root: Path | None) -> list[Skill]` reads `~/.whyline/skills/`, `<root>/.whyline/skills/`, `~/.claude/skills/` and `<root>/.claude/skills/`, in that order. `get(ref, root)` takes `origin:name`.
  3. `create(name, description, body, *, repo_root=None) -> Skill` writes `SKILL.md` in `~/.whyline/skills/<name>/` (or the repository's). `copy_to_whyline(ref, root) -> Skill` copies a Claude skill's whole folder. `edit` and `remove` work on whyline skills only; Claude skills are refused with `Claude skills are read where they are. Copy to whyline to change it.` `remove` is refused while `users.of("skill", ref)` is not empty.
  4. `SKILL_LIMIT = 20_000` and `AGENT_SKILLS_LIMIT = 60_000` bytes.
  5. CLI `whyline skills list|show|new|copy|edit|remove`.
  Tests: discovery from all four places with temporary home and repository, front matter parsing, a broken skill, create and copy, edit and remove refused on Claude skills, and removal refused while used.

- [ ] TLS-6: Knowledge packs and web pages
  Create `src/whyline/tools/knowledge.py` and its tests. Edit `src/whyline/tools/cli.py` and its tests.
  1. A pack is `~/.whyline/knowledge/<name>.toml` with `name`, `description` and `items` (paths and `http(s)` URLs). `list_packs()`, `get_pack(name)`, `save_pack(pack)`, `remove_pack(name)` (refused while used).
  2. `resolve(items, base: Path) -> list[Item]` expands `pack:<name>` entries, expands `~` and relative paths against `base`, and keeps URLs.
  3. `fetch_pages(urls, dest: Path, *, opener=None) -> list[Fetched]` saves each page as text in `dest` (HTML stripped to text with `html.parser`, other text types as they are), at most 2 MB each, 30 seconds each. A failure is noted with its reason and the rest go on. Only http and https.
  4. CLI `whyline knowledge list|show|add|remove`.
  Tests: pack round trip, `pack:` expansion, relative paths, a page fetched and stripped with a stub opener, the size limit, a non-http URL refused, and a failed page noted.

## Part 3: Agents use them

- [ ] TLS-7: The agent definition gets skills, knowledge and tools
  Edit `src/whyline/agents/definitions.py`, `src/whyline/agents/records.py` and their tests only.
  1. `AgentDef` gets `skills: tuple[str, ...]` (`origin:name`), `knowledge: tuple[str, ...]` and `tools: dict[str, str]` (`"<server>.<tool>"` to `allowed` or `ask`). `sources` still loads and is added to `knowledge`. Saving writes `knowledge`, never `sources`.
  2. Validation: an unknown skill, pack, server or tool, an unknown permission, or skills over `AGENT_SKILLS_LIMIT` make the agent broken with the reason, as other definition errors do today.
  3. The definition hash used for accepting includes the `tools_hash` of each server the agent uses. `test_changed_tools_need_review`: a changed server hash puts the agent in needs review and it does not run until accepted.
  4. Agents register with `users.register` for credentials (through their servers), servers, skills and packs.
  Tests: old `sources` loading, round trip, each validation error, the size limit, `test_changed_tools_need_review`, and the users provider.

- [ ] TLS-8: Skills and knowledge in every run
  Edit `src/whyline/agents/runner.py` and its tests only.
  1. Before the CLI starts, `prepare_run(defn, run_folder) -> RunExtras` copies each skill's folder to `<run>/skills/<name>/`, and fetches web pages to `<run>/knowledge/` with `knowledge.fetch_pages`.
  2. `build_prompt` adds, after the instructions:
     - `Skills (chosen by the user; follow them when they apply):`, then for each skill its name, description, full `SKILL.md` body, and its other files' paths in `<run>/skills/<name>/`
     - the knowledge paths and fetched pages in the existing Sources wording, which says they are data, plus any page that failed and why
  3. The run folder gets read access with `--add-dir <run>` for claude and codex, added after `capabilities.read_only_command`.
  Tests: the prompt's skill block for each origin, files listed, knowledge and a failed page, `--add-dir` for claude and codex and not for grok, and the same prompt for every CLI.

- [ ] TLS-9: Whyline's MCP server for a run
  Create `src/whyline/tools/serve.py` and its tests. Edit `src/whyline/tools/cli.py` to add `whyline tools serve`.
  1. `whyline tools serve` is an MCP server on stdio. It reads `WHYLINE_TOOLS_RUN`, the path of `<run>/tools.json` (written by TLS-11: run id, agent, and the ticked tools with their permission, server and schema). With no such variable or file, it answers `initialize` and lists no tools.
  2. `tools/list` returns the ticked tools as `<server>__<tool>`, with the real description and input schema. A tool that reads is annotated `readOnlyHint: true`.
  3. `tools/call` checks the tool is ticked (`test_unticked_tool_is_refused` returns an MCP error `This agent may not use <tool>.`), starts that server's `mcp.Session` on first use and keeps it for the run, forwards the call, and returns the real `content` and `isError`. **Ask first** tools go through TLS-10 before forwarding.
  4. Every call is appended to `<run>/tool-calls.jsonl`: time, tool, arguments with `redaction_values` applied and cut to 2,000 characters, decision (`allowed`, `approved`, `denied`, `timed out`), duration, result size, error.
  5. On end of input, it closes every session it started.
  Tests with the fake server: an empty list without the variable, the ticked tools listed and nothing else, a forwarded call, `test_unticked_tool_is_refused`, a server error returned as `isError`, the call log with a sentinel credential redacted, and sessions closed at the end.

- [ ] TLS-10: Ask first approvals
  Create `src/whyline/tools/approvals.py` and its tests. Edit `src/whyline/tools/serve.py`, `src/whyline/cli.py` (the `whyline agents` parser and `cmd_agents`) and their tests only.
  1. `request(run_folder, tool, arguments) -> Decision` writes `<run>/approvals/<n>.json` (tool, redacted arguments, asked at, status `waiting`) and waits for its status to change, checking every second, for at most `APPROVAL_TIMEOUT = 600` seconds. Then it writes `timed out`.
  2. `pending(run_id=None) -> list[Pending]` lists waiting requests across runs. `answer(run_id, n, approve: bool, by="you")` sets `approved` or `denied` with the time.
  3. A denied or timed-out call returns tool text `The user denied this call.` or `Not approved in time.` with `isError: true`, and the run goes on.
  4. CLI `whyline agents approvals`, `whyline agents approve <run> <n>` and `whyline agents deny <run> <n>`.
  Tests with a fake clock: approve, deny, `test_unanswered_call_is_denied`, pending across two runs, answering a finished request refused, and the CLI.

- [ ] TLS-11: Pointing each CLI at whyline's server
  Edit `src/whyline/agents/runner.py`, `src/whyline/agents/capabilities.py`, `src/whyline/tools/cli.py` and their tests only.
  1. `capabilities.tools_support(cli) -> str`: `per-run` for claude and codex, `saved` for grok and antigravity (`agy`), `none` for any other.
  2. When the agent has tools, `prepare_run` writes `<run>/tools.json`, sets `WHYLINE_TOOLS_RUN` in the CLI's environment, and adds to the command:
     - claude: `--mcp-config <run>/mcp.json` (one server `whyline`, command the current `whyline` executable, args `tools serve`), `--strict-mcp-config` and `--allowedTools mcp__whyline__*`
     - codex: `-c mcp_servers.whyline.command="<whyline>"` and `-c mcp_servers.whyline.args=["tools","serve"]`
     - grok and antigravity: nothing on the command line. They need the saved entry from 3.
  3. `saved_setup(cli) -> str` adds the one saved entry after the user confirms, and `saved_ready(cli) -> bool` checks the CLI's list for it:
     - grok: `grok mcp add whyline -- <whyline> tools serve`, checked with `grok mcp list`
     - antigravity: `agy mcp add whyline -- <whyline> tools serve`, checked with `agy mcp list`
     CLI `whyline tools setup-grok` and `whyline tools setup-antigravity`. Each refuses with a plain message when that CLI isn't installed.
  4. `usable_clis(defn) -> list[str]` drops CLIs that can't run this agent's tools: `none`, `saved` without its entry, and any CLI `capabilities.can_run` refuses. Antigravity stays dropped until the read-only spike adds it to `READ_ONLY`, then it is offered once its entry is saved, with no change here. The main CLI and backups are chosen from it. A run whose CLIs are all dropped fails with `No CLI can use this agent's tools: <reasons>`.
  Tests: each CLI's command and environment, no change for an agent without tools, grok and antigravity each with and without the saved entry, antigravity dropped while `can_run` refuses it and offered once it is allowed (patch `READ_ONLY` in the test), the backup order kept, and the no-CLI error.

## Part 4: Console

- [ ] TLS-12: The Tools library: Connectors and Credentials
  Create `src/whyline/console/tools_screens.py` and `tests/console/test_tools_screens.py`. Edit `src/whyline/console/agents_screens.py` and `src/whyline/console/tui.py` only to add the **Tools** button to the Agents bar and open the screen.
  1. `ToolsScreen` with tabs **Connectors**, **Skills**, **Knowledge** and **Credentials**. This task fills Connectors and Credentials; the other two say `Coming in the next update` until TLS-13.
  2. Connectors: the servers with their status and tool count, each expandable to its tools marked `reads` or `writes`. **Add** (name, command, arguments, environment variable → credential select), **Import…** (a checklist of `import_candidates`, with the needs-a-credential and refused notes), **Test** (in a thread worker), **Remove** (names users when refused), and **Set up grok** and **Set up Antigravity**, each showing `saved_ready(cli)` and disabled with a reason when that CLI isn't installed. Antigravity's button also says `Agents can't run on Antigravity yet` while `can_run` refuses it; the entry can still be saved ahead.
  3. Credentials: the list, **Add** with a masked `Input(password=True)`, **Rotate** and **Remove**. A value never appears in the screen text afterwards.
  Tests: each action through the same functions as the CLI, the import checklist adding only ticked servers, a refused removal, the masked field, and both Set up buttons asking first.

- [ ] TLS-13: The Tools library: Skills and Knowledge
  Edit `src/whyline/console/tools_screens.py` and its tests only.
  1. Skills: every skill with its origin label (`whyline`, `whyline · repo`, `Claude`, `Claude · project`), description and size, broken ones with the reason. **New skill** (name, description, body, and personal or this repository), **Copy to whyline**, **Edit** (whyline skills, through the console's editor opening), **Remove**.
  2. Knowledge: packs with their items. **New pack**, **Add files**, **Add web page**, **Remove**.
  Tests: origins shown, Claude skills offering only Copy, new and copy, a pack edited, and refused removals.

- [ ] TLS-14: Knowledge, Skills and Tools in New agent
  Edit `src/whyline/console/agents_screens.py` and its tests only.
  1. **Sources** becomes **Knowledge**: **Add files** (as today), **Add web page**, **Add pack**, and the list.
  2. **Skills**: **Add skills…** opens a checklist from `skills.find(root)` with origin and description, and the total size against the limit.
  3. **Tools**: **Add tools…** opens the enabled, tested servers, each expandable to its tools with a checkbox and a permission select: **Allowed** or **Ask first**, defaulting to Allowed for tools that read and Ask first for tools that write. Choosing Allowed on a writing tool shows `This tool can change things without asking you.`
  4. Main CLI and Backup CLIs offer only `usable_clis`, with a line for each one left out and why.
  5. **Review** shows the design's summary line: what it can read, what it can write and how, the skills with origins, and the knowledge.
  Tests: each section saving through `definitions`, the permission defaults, the warning, the CLI lists narrowing for an agent with tools, and the Review line.

- [ ] TLS-15: Approvals and tool calls in Runs
  Edit `src/whyline/console/agents_screens.py`, `src/whyline/console/tui.py` and their tests only.
  1. While anything waits (`approvals.pending()`), the Agents bar shows `Approvals 1` and the scheduler line says `waiting for you: <agent> wants <tool>`. Checked every 2 seconds while the console is open.
  2. **Approvals** lists each waiting call with the agent, tool, redacted arguments and time left, and **Approve** and **Deny** calling `approvals.answer`.
  3. A run's detail in **Runs** shows its tool calls from `tool-calls.jsonl`, one line each: `12:04 gmail__send_email · approved · 1.2s`.
  Tests: the count, approve and deny through the same function as the CLI, the time left, and the tool-call lines.

## Part 5: Docs and release

- [ ] TLS-16: Docs
  Edit `README.md` where it describes Agents, the console Help text for Agents, and create `docs/agent-tools.md`.
  Cover: connectors and importing from Claude and codex, credentials and why values never leave the Keychain, skills (the four places, whyline versus Claude, why every CLI gets them), knowledge packs and web pages, Allowed versus Ask first, approvals and the 10-minute limit, which CLIs can use tools and the one-time grok and Antigravity setup, and the call log.
  Verify with `uv run pytest -q`.
