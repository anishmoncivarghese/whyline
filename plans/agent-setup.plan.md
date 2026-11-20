<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-11-15-agent-models-skills-tools-design.md | created: 2026-11-15T21:30:00+05:30 -->
# Agent setup: picker fixes, a model per CLI, folders, a skills catalogue, a connector catalogue, made tools, tool risk and live relay settings

Runs after `plans/watch-agents.plan.md`, and before `plans/release-resolve.plan.md`. Spec: `docs/superpowers/specs/2026-11-15-agent-models-skills-tools-design.md`. Read it before every task. Where this plan and the spec differ, this plan wins. In particular:
- **Not in this plan:** connectors that need a browser sign-in (remote MCP servers), any catalogue entry that pays, and script tools. Risk levels and limits for paying tools are built here so those can follow safely.
- **Find a tool also searches skills.**
- **The default folder is the folder a new agent runs in.** Agent files stay in `~/.whyline/agents/`.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

This is one plan on purpose, so it runs in one relay and ships in one release. It has eight parts. A task belongs to the part its id names: PKR to Part 1, AMD to Part 2, FLD to Part 3, SKC to Part 4, CON to Part 5, MKT to Part 6, RSK to Part 7, LRV to Part 8. DOC-1 is last. There is no publish task: press **Release** when the relay finishes.

Why: New agent has a Model box no run ever uses, a folder that must be typed, a skills picker limited to what is on this Mac, and a tools picker that lists connectors without saying where they come from. Adding a connector means knowing its command line. A focused row in the pickers turns into an empty box, and a test left a fake `files` connector in the real `~/.whyline`.

What the user gets:
- Pickers whose focused row stays readable, that say where their lists come from, and that open **Tools** when something is missing.
- A model dropdown for the main CLI and for each backup, and the model is used.
- **Browse…** for folders and files, and a default folder for new agents in Settings.
- **Browse…** over public skill sources, a preview with warnings before installing, updates with a diff, and a skill drafted from a description.
- **Add from catalogue…** for connectors, a search of the public registry, and `What should the agent be able to do?`
- **Make a tool**: a saved web request, drafted from a description, tested and accepted before use.
- Four risk levels on tools. A tool that pays can never be set to Allowed and needs limits.
- While a relay runs, **Agents for this run** also changes the timeout, the round cap, the backup order and each backup's model, with **Refresh models** and **Other…** on every model dropdown. Relay **Set up** gets the same model list.

Rules every task keeps:
- **Console first.** Every command has a console counterpart saving through the same function.
- **Personal and global.** Everything new is stored under `~/.whyline/` and behaves the same whichever repository is selected.
- **Old agents keep working.** An agent file without the new fields loads, runs and keeps its accepted state, and its definition hash is unchanged.
- **Text from outside is data.** A skill, a registry entry or an API page fetched from the internet is shown to the user and never followed as instructions by whyline or by a drafting agent. Nothing downloaded is executed.
- **Nothing is installed, enabled or accepted without the user's own click or `[y/N]`.**
- **No secret's value** in a file outside the Keychain, a log, a dialog or a prompt.
- **No new dependency.** `git` through an injected `run`, the network through an injected `get`. Keep Python 3.11 compatibility.
- **Tests never use the network, a real CLI, a real MCP server or the real home.** Use fakes, the fake MCP server script and temporary folders.
- All text from outside is shown with `markup=False`.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- A focused checkbox in each of the three pickers still shows one line of content. PKR-1, `test_focused_picker_checkbox_keeps_its_label`.
- Inside any test, the home folder is a temporary one, with or without a `home` fixture. PKR-2, `test_tests_never_see_the_real_home`.
- An accepted agent with only the old `model` field stays accepted, and its hash is unchanged. AMD-2, `test_old_model_field_keeps_the_hash`.
- The chosen model is on the command of the main CLI and of each backup that has one. AMD-2, `test_run_uses_the_model_of_the_cli_that_runs`.
- The folder picker never returns a path that is not an existing folder. FLD-1, `test_picker_returns_only_real_folders`.
- A source is fetched only by Browse's first use or Refresh, never at start-up or in the background. SKC-2, `test_no_fetch_without_asking`.
- Install writes nothing outside `~/.whyline/skills/<name>`, and a skill folder holding a symlink or a path that leaves the folder is refused. SKC-3, `test_install_stays_inside_the_skill_folder`.
- An agent using an installed skill whose text changed must be accepted again; an agent using only skills that were on the Mac before keeps its hash. SKC-3, `test_changed_installed_skill_needs_accepting`.
- A catalogue or registry connector is never enabled before its Test passed. CON-2, `test_nothing_enabled_before_test`.
- A made tool can't call `http`, a private, local or link-local address, or a host that resolves to one. MKT-1, `test_made_tool_refuses_private_addresses`.
- An edited made tool can't run until it is accepted again. MKT-1, `test_edited_tool_needs_accepting`.
- A `pays` tool can't be saved as Allowed by the form, the file or the CLI. RSK-2, `test_pays_is_never_allowed`.
- Saving **Agents for this run** changes only what the user changed, and one refused change does not stop the others. LRV-2, `test_save_applies_only_what_changed`.
- A `pays` call over the per-call or the per-day limit is refused without asking, and a `pays` tool with no limits can't be called. RSK-2, `test_pays_limits_are_enforced`.

- [x] PKR-1: A focused checkbox keeps its label in the three pickers
  Edit `src/whyline/console/agents_screens.py` and `tests/console/test_new_agent_pickers.py` (new) only.
  Why: `PackPickScreen`, `SkillPickScreen` and `ToolPickScreen` set `Checkbox { border: none; height: 1; … }`. Textual's own `Checkbox:focus` rule adds a tall border, and on a one-line checkbox the border takes the only line, so the focused row looks like an empty box and its tick can't be seen. Eight other screens already carry the fix (`NewAgentScreen Checkbox:focus { border: none; }` and the like).
  1. Add `<Screen> Checkbox:focus { border: none; }` to the `DEFAULT_CSS` of each of the three screens.
  Tests: `test_focused_picker_checkbox_keeps_its_label` (for each of the three: focus its first checkbox, then `content_region.height == 1`, as `test_a_focused_brainstorm_checkbox_keeps_its_label_visible` does), and `test_every_one_line_checkbox_has_a_focus_rule` (each selector in `src/whyline/console/` with a `Checkbox { … height: 1 …}` rule also has `Checkbox:focus { border: none; }` for the same selector).

- [x] PKR-2: Tests never use the real home folder
  Edit `tests/conftest.py`, and any test that fails once the guard is in, only.
  Why: on 2026-11-14 at 15:19, during the agent-tools relay, something run from the test suite wrote `~/.whyline/mcp.toml` with the fixture server from `tests/agents/test_definitions_tools.py` (`files`, command `cmd`, hash `h1`). Only tests that ask for a `home` fixture are protected today.
  1. An autouse fixture in `tests/conftest.py` sets `HOME` and `USERPROFILE` to a fresh temporary folder for every test. The existing `home` fixtures keep working and keep their own folder.
  2. Run the whole suite. A test that now fails because it relied on the real home is fixed to make what it needs in the temporary one. No test is skipped or deleted for this.
  3. Nothing in the real `~/.whyline` is removed or changed by this task.
  Tests: `test_tests_never_see_the_real_home` (with no fixture named, `Path.home()` is under the temporary folder and is not the home recorded when the session started), and `test_saving_a_connector_in_a_plain_test_lands_in_tmp`.

- [x] PKR-3: `not stated` for a tool that doesn't say whether it reads
  Edit `src/whyline/tools/mcp_config.py`, `src/whyline/console/agents_screens.py`, `src/whyline/console/tools_screens.py` and their tests only.
  Why: `mcp.Tool.read_only` is None when a server gives no hint, but `mcp_config` stores it as `false`, and the picker then says `writes` for a tool called `read`.
  1. `mcp_config.Tool.read_only` becomes `bool | None`. `test_server` keeps None. The file writes `read_only` only when it is stated, and a tool with no `read_only` line loads as None.
  2. An existing `mcp.toml` loads as it is: a stored `false` stays `writes` until the server is tested again.
  3. The picker and the Tools library show `reads`, `writes` or `not stated`. A tool that is not stated is treated as a writing tool everywhere: `default_permission` gives `ask`, and **Allowed** shows the write warning.
  4. The tools hash of a server that was already tested does not change.
  Tests: `test_unstated_tool_shows_not_stated_and_asks_first`, the round trip of all three values, an old file loading unchanged, and the hash staying the same.

- [x] PKR-4: The pickers point at the Tools library
  Edit `src/whyline/console/agents_screens.py` and `tests/console/test_new_agent_pickers.py` only.
  Why: connectors, skills and packs are added in **Tools**, and the New agent pickers only list what is there. Nothing in a picker says so, and an empty one is a dead end.
  1. Add tools says, under its title, `Tools come from your connectors. Tick the ones this agent may use, and choose Allowed or Ask first for each.`
  2. An **Open Tools…** button beside Done and Cancel opens `ToolsScreen` on the Connectors tab. When it closes, the list is rebuilt from `mcp_config.load()`, and every tick and permission already chosen is kept for tools that still exist.
  3. With no enabled, tested connector the body says `No connectors yet. Add one in Tools, test it, then choose its tools here.` and **Open Tools…** is the primary button.
  4. A connector that is saved but not usable is one line with the reason and no checkboxes: `github · not tested yet` or `github · turned off`.
  5. Add skills and Add pack get the same line (`Skills come from your library.`, `Packs come from your library.`) and **Open Tools…** on their own tab.
  Tests: `test_open_tools_keeps_the_picks`, the empty state and its primary button, the untested and turned-off lines, and the right tab opening from each picker.

- [x] AMD-1: One list of models for every CLI
  Create `src/whyline/models.py` and `tests/test_models.py`. Edit `src/whyline/console/relay_ops.py` and its tests.
  1. Move `AGENT_MODELS` and the Antigravity listing (`_parse_agy_models`, its cache and `antigravity_models_status`) into `whyline.models`. `relay_ops` keeps its names as thin calls into it, so nothing that imports them changes.
  2. `models.options(cli, *, refresh=False, run=…, now=…) -> list[tuple[str, str]]` (label, id): the CLI's own list where a listing command is known (`LISTERS: dict[str, list[str]]`, Antigravity today), then the built-in list, then the user's additions, each id once, in that order.
  3. `models.cached(cli) -> list[tuple[str, str]]` never starts a process: it reads `~/.whyline/models.json` (per CLI: ids, fetched time) and falls back to the built-in list. A cache older than 24 hours is still returned and marked stale by `models.stale(cli)`.
  4. `models.add(cli, model_id)` and `models.remove(cli, model_id)` keep the user's additions in the same file. An id is 1 to 80 characters of letters, digits and `._:/-[]`.
  5. A lister that fails or times out (10 seconds) leaves the cache as it is and returns the cached list.
  Tests: the merge order and no duplicates, `cached` starting no process, a failed lister keeping the old cache, the stale mark, add and remove with a bad id refused, and `relay_ops`'s existing model tests still passing.

- [x] AMD-2: A model per CLI on the agent, and the run uses it
  Edit `src/whyline/agents/definitions.py`, `src/whyline/agents/runner.py`, `src/whyline/agents/records.py` and their tests only.
  1. `AgentDef.models: dict[str, str]`, from a `[models]` table (`claude = "sonnet"`). Keys must be the runner or a backup. An old `model = "x"` is read as `models[runner] = "x"`. `render` writes `[models]` only when it is not empty, and writes `model` as before when the only entry is the runner's and the file had `model`, so `test_old_model_field_keeps_the_hash` holds.
  2. `runner._command` adds the model for the CLI it is building, with `whyline_relay.config.with_model` and that CLI's adapter `model_flag`. A CLI with no model flag runs without one.
  3. When a run fails and its output matches a model refusal (`MODEL_REFUSED`: a short list of patterns such as `model not found`, `unknown model`, `invalid model`, case-insensitive, with the model id in the output), it is run once more on the CLI's default before any backup is tried. The run record gets `model` (what ran) and `model_note` (`sonnet-9 was refused; ran on the default`).
  Tests: `test_old_model_field_keeps_the_hash`, `test_run_uses_the_model_of_the_cli_that_runs` (main and a backup, each with its own model), a CLI with no flag, a key that is not a CLI of the agent refused, the refusal retry and its note, and an ordinary failure not retried.

- [x] AMD-3: Model dropdowns in New agent
  Edit `src/whyline/console/agents_screens.py` and its tests only.
  1. The Model `Input` is replaced by a `Select` beside Main CLI (`id="na-model"`), and one beside each ticked backup (`id="na-model-<cli>"`), shown only while that backup is ticked.
  2. Each holds `Default (the CLI decides)`, then `models.cached(cli)`, then `Other…`. `Other…` opens a one-line box; a valid id is added with `models.add` and selected.
  3. Changing Main CLI refills its dropdown and selects that CLI's saved model, or Default.
  4. A **Refresh models** button runs `models.options(cli, refresh=True)` for the shown CLIs in a worker and refills the dropdowns, keeping the selection. A CLI with no model flag shows a disabled dropdown reading `This CLI has no model setting`.
  5. An agent opened for editing shows its saved models, including one that is not on the list.
  6. Review lists `Models: claude sonnet · codex default`, and warns, without blocking, about an id that is not in `models.cached`.
  7. The form still fits 80x24 by scrolling as it does today.
  Tests: the options and their order, the backup dropdown appearing with its tick, `Other…` adding and selecting, the refill on a Main CLI change, Refresh keeping the selection, the disabled case, an edited agent's unlisted model kept, and the Review line and warning.

- [x] AMD-4: Models from the CLI
  Edit `src/whyline/cli.py` and its tests only.
  1. `whyline agents models <cli> [--refresh]` prints the list from `models.options`, one id per line, with `(added by you)` after the user's own.
  2. `whyline agents models <cli> --add <id>` and `--remove <id>` call `models.add` and `models.remove`.
  3. `whyline agents new` and `whyline agents edit` (where they take `--model`) gain `--model-for <cli>=<id>`, repeatable. `--model` keeps meaning the main CLI's model.
  Tests: the listing, add and remove, `--model-for` on a backup, and a CLI that is not the agent's refused with the definition's message.

- [x] FLD-1: A folder and file picker
  Create `src/whyline/console/pickers.py` and `tests/console/test_pickers.py` only.
  1. `PathPickScreen(start: Path, *, files: bool = False, many: bool = False, title: str)`: a list of the current folder's entries (folders first, hidden entries off unless **Show hidden** is ticked), with **Up**, **Home**, **New folder…**, a path box that accepts a pasted or typed path (with `~`), **Choose** and **Cancel**.
  2. With `files=False` only folders are listed and **Choose** returns the current folder. With `files=True` files are listed too, and with `many=True` they have checkboxes and **Choose** returns the ticked ones.
  3. It dismisses with a `Path`, a list of `Path`, or None. It never returns a path that does not exist or is of the wrong kind; the path box shows `No such folder` and stays open.
  4. A folder that can't be read shows `Can't open this folder` and stays where it was. A folder with more than 500 entries shows the first 500 and a line saying so.
  5. **New folder…** asks for a name, refuses `/`, `..` and an existing name, creates it and enters it.
  Tests: `test_picker_returns_only_real_folders`, Up, Home, the path box with `~`, hidden entries, the unreadable folder, the 500 cap, New folder and its refusals, and the files and many modes.

- [x] FLD-2: A default folder for new agents
  Create `src/whyline/agents/defaults.py` and `tests/agents/test_defaults.py`. Edit `src/whyline/console/settings_screen.py`, `src/whyline/cli.py` and their tests.
  1. `defaults.folder() -> Path` reads `default_folder` from `paths.settings_file("defaults.toml")`, expanding `~`. With no file, or a folder that no longer exists, it is the home folder.
  2. `defaults.set_folder(path)` refuses a path that is not an existing folder, and stores it with `~` in place of the home folder.
  3. Settings gets an **Agents** section: `Default folder for new agents`, the current value, **Browse…** (`PathPickScreen`) and **Reset**. Saving goes through `defaults.set_folder`.
  4. CLI: `whyline agents settings default-folder [PATH]` prints or sets it.
  5. No existing agent is changed.
  Tests: the default with no file, a missing folder falling back to home, the refusal, `~` stored, the Settings section saving through `set_folder`, and the CLI.

- [x] FLD-3: Browse in New agent
  Edit `src/whyline/console/agents_screens.py` and its tests only.
  1. **Runs in** gets **Browse…**, opening `PathPickScreen` at the field's value (or `defaults.folder()` when it is empty or missing) and writing the chosen folder back with `~` for the home folder.
  2. A new personal agent starts with **Runs in** set to `defaults.folder()`. An agent opened for editing keeps its own.
  3. Knowledge → **Add files** opens `PathPickScreen(files=True, many=True)` starting at **Runs in**, and adds the ticked files. Typing a path still works through the picker's path box.
  Tests: Browse writing the folder back, the new agent's starting folder following the setting, an edited agent keeping its folder, and Add files adding several ticked files.

- [x] SKC-1: Skills from the other CLIs' folders
  Edit `src/whyline/tools/skills.py`, `src/whyline/console/tools_screens.py` and their tests only.
  1. `_places` adds `("agents", ~/.agents/skills)` and `("codex", ~/.codex/skills)` after `claude`. `ORIGINS` gains both.
  2. `copy_to_whyline` accepts any origin that is not whyline's own, and its message becomes `Only skills from another tool's folder are copied; this one is already whyline's.`
  3. The same skill found in two places (same name, same `SKILL.md` text) is listed once, under the first place in the order above. Different text keeps both.
  4. The Tools library's Skills tab shows the origin for each, and **Copy to whyline** for any that is not whyline's.
  Tests: both new places found, the copy from each, the duplicate listed once and the differing pair kept, and a personal agent still getting no repository skill.

- [x] SKC-2: Skill sources
  Create `src/whyline/tools/skill_sources.py` and `tests/tools/test_skill_sources.py` only.
  1. `Source`: `name`, `url`, `path` (the folder inside the repository that holds the skill folders, `""` for the top), `branch`, `licence`, `kind` (`skills` or `directory`), `builtin`.
  2. `BUILTIN`: `anthropic` (`https://github.com/anthropics/skills`, `skills`, no licence stated), `agentic` (`https://github.com/sickn33/agentic-awesome-skills`, `skills`, `MIT, text CC BY 4.0`), `composio` (`https://github.com/ComposioHQ/awesome-claude-skills`, top level, no licence stated), and two of kind `directory` that are only opened in the browser: `https://github.com/VoltAgent/awesome-agent-skills` and `https://github.com/heilcheng/awesome-agent-skills`.
  3. `load()`, `add(name, url, path="", branch="")`, `remove(name)` keep the user's sources in `~/.whyline/skill-sources.toml`. Only `https://` URLs with a host and a path are accepted. A built-in can be turned off, not removed.
  4. `fetch(source, *, run)` makes or updates a shallow clone in `~/.whyline/skill-sources/<name>` with `git` through `run` (argv lists, `--depth 1`, `GIT_TERMINAL_PROMPT=0`, a 120 second timeout, no hooks: `-c core.hooksPath=/dev/null`). It returns the commit. Nothing else calls `git` for a source.
  5. `index(source) -> list[Entry]` (`source`, `name`, `description`, `path`, `size`, `files`) reads each folder's `SKILL.md` front matter from the clone with `skills.parse_front_matter`, never following a symlink, skipping folders with no `SKILL.md` and files over 1 MB.
  6. `search(text) -> list[Entry]` over every fetched source: all words must appear in the name or description, name matches first, at most 200 results. `fetched(source) -> str | None` gives the time of the last fetch.
  Tests: `test_no_fetch_without_asking` (load, index and search call `run` zero times), the git argv, a bad URL refused, a built-in turned off, the index skipping symlinks and folders without `SKILL.md`, and the search order and cap.

- [x] SKC-3: Check, install and update a skill
  Create `src/whyline/tools/skill_install.py` and `tests/tools/test_skill_install.py`. Edit `src/whyline/agents/definitions.py` and its tests.
  1. `check(folder) -> list[str]`, plain warnings from fixed rules, none of which block:
     - `contains scripts: <names>` for `.py`, `.sh`, `.js`, `.rb`, `.ps1` and files with an executable bit
     - `tells the agent to ignore its instructions` for lines matching a short fixed list (`ignore (all )?(previous|prior|above) instructions`, `disregard your`, `you are now`)
     - `downloads and runs something` for `curl … | sh`, `wget … | sh`, `pip install`, `npx `, `bash -c "$(`
     - `long encoded text` for a run of 400 or more base64 characters
     - whatever `security.secrets.scan_text` reports, by rule name only
  2. `preview(entry) -> Preview`: the `SKILL.md` text, the file list with sizes, the total size, the source's licence (or `no licence stated`), the commit and the warnings.
  3. `install(entry, *, name=None) -> Skill` copies the folder to `~/.whyline/skills/<name>` and writes `source.toml` there (`source`, `url`, `path`, `commit`, `licence`, `installed`). It refuses a folder holding a symlink, a file whose path leaves the folder, a total over 2 MB, a `SKILL.md` over `SKILL_LIMIT`, an invalid name, and a name already installed (`Choose another name`). The front matter's `name` is rewritten to the installed name.
  4. `update_diff(name) -> str` (a unified diff of every text file against the source's fetched copy, `""` when the same) and `update(name)`, which replaces the folder and its commit. A skill with no `source.toml` has no update.
  5. `definitions.definition_hash` adds `_skills_hash` holding, for each skill the agent names that has a `source.toml`, the sha256 of its files. Skills with no `source.toml` add nothing, so today's agents keep their hash.
  Tests: `test_install_stays_inside_the_skill_folder`, `test_changed_installed_skill_needs_accepting`, each warning firing and its harmless twin not, the preview, the name clash, the rewritten name, the diff and update, and a skill with no source having no update.

- [ ] SKC-4: Browse and Sources in the Tools library
  Edit `src/whyline/console/tools_screens.py` and its tests only.
  1. The Skills tab gets **Browse…** and **Sources…**.
  2. **Sources…** lists each source with its kind, licence and last fetch, with **Add…** (name, URL, folder), **Turn off / on**, **Remove** (the user's own only), **Refresh** and, for a directory, **Open in browser**.
  3. **Browse…** shows a search box and the results (`name · source · licence` and the description on its own wrapped line). A source that was never fetched is fetched first, with `Fetching <name>…` in a worker and **Cancel**. Offline or on a failed fetch it says `Couldn't fetch <name>: <reason>` and lists what is already there.
  4. Choosing a result opens the preview: warnings first, then licence, size, files, and the whole `SKILL.md` in a scrolling pane, with **Install**, **Install as…** and **Close**. After Install the skill is in the library and the line says `Installed <name>. Add it to an agent in New agent → Add skills.`
  5. **Add from a link…** takes a `https://github.com/<owner>/<repo>/tree/<branch>/<path>` link to one skill folder, adds its repository as a source named `<owner>-<repo>` if it is not one, fetches it and opens that skill's preview. Any other link is refused with the expected form.
  6. An installed skill's row shows `from <source>` and **Update…**, which shows `update_diff` with **Update** and **Cancel**, or `Already up to date`.
  Tests: the first-use fetch and its cancel, the offline line, the preview's order with warnings first, Install and Install as, the link parsed and a bad link refused, and Update's diff and its up-to-date line.

- [ ] SKC-5: Draft a skill from a description
  Create `src/whyline/tools/skill_draft.py` and `tests/tools/test_skill_draft.py`. Edit `src/whyline/console/tools_screens.py` and its tests.
  1. `skill_draft.prompt(description) -> str` asks for one `SKILL.md`: front matter with `name` and a one-line `description`, then the body, and nothing else. The user's description is in a labelled block as data.
  2. `skill_draft.parse(answer) -> tuple[str, str, str]` (name, description, body) takes the first fenced block or the whole answer, and raises `DraftError` with a plain reason when the front matter, name or description is missing or the text is over `SKILL_LIMIT`.
  3. `skill_draft.draft(description, *, ask_agent) -> tuple[str, str, str]` runs it once through the read-only agent call the release notes use (`release.plan.default_ask_agent`), and once more with the reason when parsing fails.
  4. **New skill** gets **Draft from a description…**: a box for the description, `Drafting…` in a worker, then the normal New skill form filled in for editing. Nothing is saved until **Save**.
  Tests: the prompt holding the description as data, parse on a good answer, each `DraftError`, the single retry, and the form filled and nothing saved before Save.

- [ ] SKC-6: A skills picker you can search, and the commands
  Edit `src/whyline/console/agents_screens.py`, `src/whyline/tools/cli.py` and their tests only.
  1. `SkillPickScreen` gets a search box that filters by name and description, and each row shows `name · origin` with the description on its own wrapped line underneath, so nothing is cut off. Ticks are kept while filtering. A broken skill is listed last, disabled, with its reason.
  2. CLI, each calling the functions above: `whyline tools skills sources [add NAME URL [--path P] | remove NAME | refresh [NAME]]`, `browse <text>`, `show-remote <source>:<name>` (the preview), `install <source>:<name> [--as NAME] [--yes]` (prints the warnings and asks `[y/N]`), and `update <name> [--yes]` (prints the diff and asks).
  Tests: the filter keeping ticks, the wrapped description, the broken row, and each command, with install and update writing nothing on `n`.

- [ ] CON-1: The connector catalogue
  Create `src/whyline/tools/catalogue.py`, `src/whyline/tools/connectors.toml` and `tests/tools/test_catalogue.py`. Edit `pyproject.toml` only to ship the data file.
  1. `Entry`: `name`, `title`, `about` (one line), `command`, `args`, `credentials` (each `var`, `label`, `where` — a URL saying where to get it), `tools` (each `name` and `risk`), `source` (the project's own page), `checked` (a date, or `""`).
  2. `catalogue.load() -> list[Entry]` reads the packaged file and refuses an entry with no `source`, a command that is not a bare program name (`npx`, `uvx`, `docker`, `python3`, `node`), or a credential value in place of a variable name.
  3. `connectors.toml` holds entries for: files, web fetch, web search, a browser, GitHub, Slack, Notion, Linear, Postgres, SQLite, Gmail, Google Calendar and Google Drive. Each entry's command and arguments are copied from that project's own page, whose URL goes in `source`. An entry the builder can't confirm from its own page is left out and named in the handoff. No entry whose tools pay.
  4. Every entry ships with `checked = ""`. The console shows such an entry as `not checked by whyline yet`. A date is put in only by a person who ran its Test on a real account.
  5. `catalogue.search(text)` matches all words against the title, about line and tool names.
  Tests: the loader's three refusals, the packaged file loading with every entry having a `source` and no credential values, no `pays` risk in the file, and search.

- [ ] CON-2: Add a connector from the catalogue
  Edit `src/whyline/tools/catalogue.py`, `src/whyline/console/tools_screens.py`, `src/whyline/tools/cli.py` and their tests only.
  1. `catalogue.add(entry, credentials: dict[str, str], *, test=mcp_config.test_server) -> str`: stores each credential in the Keychain under `<entry.name>-<var>` with `whyline.credentials`, saves the server **disabled** with its env pointing at those names, runs the test, and enables it only when the test passed. On a failed test the server stays saved and disabled, and the message is the test's reason.
  2. The Connectors tab gets **Add from catalogue…**: the list with a search box, then one screen for the chosen entry with four parts in order: what it will run (the full command) and its tools with their risk, a box per credential with its `where` link and **Open**, **Test**, and the result. **Add** is enabled only after a passing Test.
  3. A catalogue entry that is already added shows `added` and opens the existing connector.
  4. CLI: `whyline tools catalogue [TEXT]` lists, `whyline tools catalogue add <name>` asks for each credential without echo, tests, and prints the result.
  Tests: `test_nothing_enabled_before_test`, a failed test leaving it disabled with the reason, credentials going only to the fake Keychain, the already-added line, and the CLI.

- [ ] CON-3: Search the public registry
  Create `src/whyline/tools/registry.py` and `tests/tools/test_registry.py`. Edit `src/whyline/console/tools_screens.py`, `src/whyline/tools/cli.py` and their tests.
  1. `registry.search(text, *, get, limit=20) -> list[Entry]` asks the public MCP registry (`REGISTRY_URL`, the registry's documented search endpoint, checked by the builder against its own documentation and recorded in a comment with the date) through `get` with a 10 second timeout, and turns each result that runs as a local command into a catalogue `Entry` with `checked = ""` and every tool's risk left to the Test. Results that are remote servers are returned with `refused = "needs a browser sign-in, which whyline can't do yet"`.
  2. Any failure returns an empty list and a reason (`registry.last_error()`); nothing is cached to disk.
  3. Add from catalogue gets **Search more…**, showing registry results under the heading `From the public registry · not checked by whyline`, going through the same four-part screen. Refused results are listed with their reason and no button.
  4. CLI: `whyline tools catalogue search <text>`.
  Tests: results mapped from a recorded response in `tests/tools/fixtures/`, remote results refused with the reason, a timeout giving an empty list and a reason, and the heading.

- [ ] CON-4: What should the agent be able to do?
  Create `src/whyline/tools/find.py` and `tests/tools/test_find.py`. Edit `src/whyline/console/agents_screens.py`, `src/whyline/console/tools_screens.py`, `src/whyline/tools/cli.py` and their tests.
  1. `find.match(text, *, registry_search=None) -> list[Hit]` (`kind`: `connector`, `catalogue`, `skill`, `remote-skill`, `registry`; `title`; `about`; `ref`), in that order: connectors already added (by tool name and description), catalogue entries, skills in the library, skills in fetched sources, and registry results only when `registry_search` is given. All words must match; at most 5 per kind.
  2. Add tools and the Tools library get a box `What should the agent be able to do?` with **Find**. Hits are listed by kind with one button each: **Tick its tools** (added connector), **Add…** (catalogue or registry, the four-part screen), **Add skill** (library), **Preview…** (remote skill). **Search the registry too** is a separate button, so nothing goes to the network unasked.
  3. With no hit it says `Nothing found. You can make a tool for it.` with **Make a tool…**, which is disabled with `Coming in this release` until MKT-3 wires it.
  4. CLI: `whyline tools find <text> [--registry]`.
  Tests: the order and the cap, no registry call without the flag or the button, each hit's button doing its action, and the empty state.

- [ ] MKT-1: A made tool: a saved web request
  Create `src/whyline/tools/made.py` and `tests/tools/test_made.py` only.
  1. `MadeTool`: `name`, `about`, `method` (`GET`, `POST`, `PUT`, `PATCH`, `DELETE`), `url` (with `{input}` places), `headers`, `query`, `body` (a JSON template), `inputs` (each `name`, `type` of `string`, `number` or `boolean`, `about`, `required`), `credential` (a Keychain name) and `credential_in` (`header:<Name>` or `query:<name>`), `pick` (a dotted path into a JSON answer, `""` for all), `risk`, `accepted_hash`.
  2. Stored one per file in `~/.whyline/tools/<name>.toml`. `load_all()`, `save(tool)`, `remove(name)`, `accept(name)` (stores the hash of everything but `accepted_hash`) and `accepted(tool) -> bool`.
  3. `validate(tool)` refuses: a URL that is not `https`, a host that is an IP literal or `localhost`, a credential placed in the URL path, an input used but not declared, a header named `Host` or `Content-Length`, and a risk below `writes` for any method but `GET`. `reads` is allowed only for `GET`.
  4. `call(tool, args, *, get_credential, resolve, request) -> str`: checks the tool is accepted, fills the template (inputs are URL-encoded in the URL and query, JSON-encoded in the body), resolves the host with `resolve` and refuses a private, loopback, link-local or reserved address, sends with `request` (15 second timeout, no redirects followed to another host, at most 200,000 bytes read), and returns the picked part as text. A non-2xx answer returns `HTTP <code>` and the first 500 characters. The credential's value appears in no return value or error.
  Tests: `test_made_tool_refuses_private_addresses` (IP literal, `localhost`, a name resolving to `10.0.0.1`, `127.0.0.1`, `169.254.169.254` and `::1`, and a redirect to another host), `test_edited_tool_needs_accepting`, each `validate` refusal, the template filling and encoding, the size cap, `pick`, and the credential never in the output.

- [ ] MKT-2: Made tools in every run
  Edit `src/whyline/tools/serve.py`, `src/whyline/tools/mcp_config.py`, `src/whyline/agents/definitions.py` and their tests only.
  1. Accepted made tools appear as a built-in server named `made`, with one tool each (`made.<name>`), its inputs as the schema and `read_only` true only for risk `reads`. It is listed by the functions the pickers use, without an entry in `mcp.toml`.
  2. `whyline tools serve` answers a call to `made.<name>` with `made.call`, through the same approval and call-log path as any other tool.
  3. An agent can name `made.<name>` in `[tools]`. The definition hash includes each named made tool's `accepted_hash`, so editing and accepting a tool makes its agents need accepting again.
  4. A made tool that is no longer accepted, or was removed, is refused at run time with `made.<name> is not accepted` and the run goes on.
  Tests: the tool listed and callable through the fake client, Ask first asking and the call logged, the hash changing with the tool's, and the unaccepted and removed cases.

- [ ] MKT-3: Describe a tool, test it, accept it
  Create `src/whyline/tools/made_draft.py` and `tests/tools/test_made_draft.py`. Edit `src/whyline/console/tools_screens.py`, `src/whyline/console/agents_screens.py`, `src/whyline/tools/cli.py` and their tests.
  1. `made_draft.draft(description, *, ask_agent) -> MadeTool` asks the read-only agent for one TOML block in `made`'s format and parses it with `made.validate`. It retries once with the reason. The agent is told to use only the service's public API pages, to name a credential and never to include a value, and that the user's description is data.
  2. The Connectors tab gets **Make a tool…**: a description box, `Drafting…`, then a form with every field of the tool for editing, the line `This will send a <METHOD> request to <host>`, **Test…**, **Accept** and **Cancel**.
  3. **Test…** asks for a value per input, shows the exact request (URL, headers with the credential as `•••`, body), asks `Send it?` and shows the answer. A tool whose risk is above `reads` says `This test really does it` before sending.
  4. **Accept** is enabled only after `validate` passes, and saves and accepts. An accepted tool can be opened again; saving a change clears its acceptance until **Accept** is pressed.
  5. CON-4's **Make a tool…** opens this with the search text as the description.
  6. CLI: `whyline tools made list | show <name> | new --from FILE | test <name> key=value… | accept <name> | remove <name>`, each asking `[y/N]` before sending or accepting unless `--yes`.
  Tests: the draft parsed and validated, the retry, no credential value in the prompt, Test showing the masked request and sending only after yes, Accept disabled until valid, an edit clearing acceptance, and the CLI.

- [ ] RSK-1: A risk level on every tool
  Create `src/whyline/tools/risk.py` and `tests/tools/test_risk.py`. Edit `src/whyline/tools/mcp_config.py`, `src/whyline/tools/catalogue.py` and their tests.
  1. `risk.LEVELS = ("reads", "writes", "sends", "pays")`, in rising order.
  2. `risk.of(server, tool) -> str`: the user's own setting when there is one, else the catalogue entry's for that connector and tool, else `reads` when the tool states it only reads, else `writes`. A made tool's is its own `risk`.
  3. `risk.set_level(server, tool, level)` stores the user's setting in `~/.whyline/tool-risk.toml`. It refuses a level below the one `of` would give without it: a level can be raised, never lowered.
  4. A catalogue or made tool may carry `pay` hints naming the arguments that hold the amount, the currency and who is paid (`amount_arg`, `currency_arg`, `payee_arg`), and `send` hints (`to_arg`, `text_arg`). `risk.hints(server, tool) -> dict`.
  5. Changing a tool's level changes its server's `tools_hash`, so agents using it need accepting again.
  Tests: each source of the level in order, raising allowed and lowering refused, the hints, and the hash change.

- [ ] RSK-2: Limits and permissions by risk
  Edit `src/whyline/agents/definitions.py`, `src/whyline/tools/approvals.py`, `src/whyline/tools/serve.py` and their tests only.
  1. A `pays` tool's permission can only be `ask`. `definitions.parse` refuses `allowed` for one with `<tool> moves money and can only be Ask first`, and `serve` treats a stored `allowed` as `ask`.
  2. `AgentDef.limits: dict[str, Limit]`, from `[limits."<server>.<tool>"]` with `per_call`, `per_day` (numbers above zero) and `currency`. A `pays` tool with no limits can't be called: `serve` answers `Set a limit for <tool> first` without asking.
  3. Before asking, `serve` reads the amount and currency from the call with the tool's `pay` hints. A `pays` tool with no hints, an amount that is not a number, a different currency, an amount over `per_call`, or one that takes today's approved total (from the call log, the user's local day) over `per_day` is refused without asking, with the reason.
  4. The approval request for a `pays` call carries `amount`, `currency`, `payee`, `today` (the total approved so far today) and the limits. For a `sends` call it carries `to` and the full `text`. `approvals` shows these fields first.
  5. `pays` and `sends` approvals are never answered by a remembered choice: each call asks.
  6. A scheduled run's `pays` call waits for approval as other calls do, and is denied when the wait ends.
  Tests: `test_pays_is_never_allowed` (parse, a hand-edited file at run time, and the CLI), `test_pays_limits_are_enforced` (no limits, no hints, a bad amount, a wrong currency, over per call, over per day across two calls, and a new day), the approval fields for `pays` and `sends`, and no remembered answer for either.

- [ ] RSK-3: Risk in the pickers, the library and approvals
  Edit `src/whyline/console/agents_screens.py`, `src/whyline/console/tools_screens.py`, `src/whyline/tools/cli.py` and their tests only.
  1. Add tools and the Tools library show each tool's level (`reads`, `writes`, `sends`, `pays`, or `not stated`, which counts as `writes`).
  2. For a `pays` tool the permission dropdown holds only **Ask first**, and ticking it shows `Limit per call`, `Limit per day` and `Currency` boxes. Done is refused with `Set both limits for <tool>` while they are empty or not above zero.
  3. A `sends` tool set to **Allowed** shows `This agent will be able to send without asking.` under it.
  4. The Tools library gets **Risk…** on a tool, offering only the levels at or above its current one.
  5. The approval dialog, and the Runs view of a past call, show the `pays` and `sends` fields first, in plain lines: `Pay 12.50 EUR to <payee> · today so far 30.00 of 100.00`.
  6. CLI: `whyline tools risk <server>.<tool> [LEVEL]`, and `whyline agents limit <agent> <server>.<tool> --per-call N --per-day N --currency C`.
  Tests: the level shown, the single choice and the limit boxes for `pays`, Done refused without limits, the `sends` line, Risk offering no lower level, the approval lines, and the CLI.

- [ ] LRV-1: Console functions for live run settings
  Needs whyline-relay 0.2.45 on PyPI (whyline-relay's `plans/live-run-settings.plan.md`, LRS-4). When `uv lock` can't find it, stop and say so with `whyline handoff LRV-1 --issue "whyline-relay 0.2.45 is not on PyPI yet"`; do not lower the floor to make the lock pass.
  Edit `src/whyline/console/relay_ops.py` and `pyproject.toml` (and `uv.lock`), with tests in `tests/console/test_relay_ops_live_settings.py`.
  1. Both `whyline-relay>=…,<0.3` lines in `pyproject.toml` become `whyline-relay>=0.2.45,<0.3`, and `uv.lock` is refreshed.
  2. `RunSetting` (`name`, `current`, `configured`, `changed: bool`) and `run_settings(root) -> dict[str, RunSetting]` for `timeout`, `rounds` and `backup`, from `whyline_relay.run_settings.effective`.
  3. `set_run_timeout(root, minutes, *, keep)`, `set_run_rounds(root, rounds, *, keep)` and `set_run_backup(root, chain, *, keep)` call the relay's functions with the run's settings and return its message. `set_run_rounds` passes the running task's round. `RunSettingsError` becomes `ValueError` with the relay's message, as `switch_live` does for roles.
  4. `model_options_for_agent` and `cached_model_options` read `whyline.models` (AMD-1), so the relay screens, Chat and New agent show one list.
  Tests: each setter writing `run-settings.json` and returning the relay's message, `keep` reaching `config.toml`, the round-cap refusal as a `ValueError`, `run_settings` after a change, and the model options coming from `whyline.models`.

- [ ] LRV-2: Timeout, round cap, backups and their models in "Agents for this run"
  Edit `src/whyline/console/relay_screens.py` (`RunAgentsScreen`), with tests in `tests/console/test_relay_screens.py`.
  1. The window becomes 110 columns wide (`max-width: 100%`) and scrolls when it is taller than the screen. Each role row is one line: the role, the agent dropdown, the model dropdown (LMD-2) and its reason line underneath.
  2. Under the roles, a **Backups** block: the backup order as the console's `OrderedChain` (tick to use, **Up** and **Down** to order), and a model dropdown beside each ticked backup. A backup that also holds a role shows that role's model and `same as its role`.
  3. Under that, **Timeout** (minutes, `0` for no limit) and **Round cap** (1 to 99), each showing `was 30` after it when it differs from the configured value.
  4. Every model dropdown holds `Default`, the agent's models from `whyline.models.cached`, and `Other…`, which takes a typed id, adds it with `models.add` and selects it. One **Refresh models** button refreshes the lists of every agent shown, in a worker, keeping each selection.
  5. **Save** applies, in this order and only for what changed: role switches, model switches (roles and backups, once per agent), the backup order, the timeout, the round cap. Each uses the **Keep for future runs** checkbox. An error from one goes to `#ra-error` with the relay's message and the rest still apply.
  6. The summary lists what will change and when: `Timeout 45m from the next turn · Round cap 5 from the next check · Backups codex, grok from the next time one is needed`.
  7. The `READ_ONLY` text becomes `The plan stays as it is while the relay runs.`
  8. With no relay running the screen is not offered, as today; Set up is used instead.
  Tests: `test_save_applies_only_what_changed` (change only the timeout: one call, to `set_run_timeout`; then make the round cap refuse and check the timeout and a model switch still applied), the backup order and a backup's model saved, `same as its role`, Other… adding and selecting, Refresh keeping selections, the summary line, Keep unticked passing `keep=False` everywhere, and the screen usable at 80x24 by scrolling.

- [ ] LRV-3: The same model list in relay Set up
  Edit `src/whyline/console/relay_screens.py` (`RelaySetupScreen`) and its tests only.
  1. Set up's model pickers (`rs-model-<agent>`) read `whyline.models.cached`, with `Default`, `Other…` and a **Refresh models** button, as in LRV-2. The separate typed-model input (`rs-model-input-<agent>`) is replaced by `Other…`.
  2. The backup agents listed in Set up each get a model picker too, saved with `set_agent_model_in_toml`.
  3. The window is widened to 110 columns when the model column would not fit, and still scrolls at 80x24.
  4. A saved model that is not on the list is shown and kept.
  Tests: the options and Other…, Refresh keeping the selection, a backup's model saved to `config.toml`, an unlisted saved model kept, and the screen at 80x24.

- [ ] DOC-1: Docs
  Edit `docs/agent-tools.md`, `docs/agents-capabilities.md`, the page that documents the relay screens and `README.md` only.
  Cover: choosing a model per CLI and what Default means; Browse and the default folder; skill sources, what the preview's warnings mean, licences, and that nothing from a skill is run; the connector catalogue and what `not checked by whyline yet` means; Find; made tools, their limits and that a Test really sends; the four risk levels, limits for paying tools, and that browser sign-in connectors and paying catalogue entries are not in this release. In `docs/relay-chat.md` or the relay page: changing agents, models, backups, the timeout and the round cap while a relay runs, and when each change applies.
  Verify with `uv run pytest -q`.
