<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-03T16:30:00+05:30 -->
# Architecture: a Files tab that shows how the repo is built, refreshed by hand or after every release

Runs after `plans/assistant-triggers.plan.md`, and before `plans/workflows-2-to-4.plan.md`. Needs the Chat tab from `plans/relay-chat.plan.md` (RCH-7). Design: `docs/superpowers/specs/2026-11-03-architecture-tab-design.md`. Read it before any task. Where this plan and the design differ, this plan wins. Where a name in the repository has moved, follow the repository and keep the design's behaviour.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

There is no publish task (removed 2026-11-11). When the relay finishes, press **Release**: it sets the version, writes the notes, runs the checks and the security scan, pushes, waits for CI, tags and publishes. This repository's relay has no `release` profile, so a publish task would only bump the version.

What the user gets:
- In Relay mode, the Files pane gets a fifth tab: **Working file · Plan · All files · Chat · Architecture**.
- The tab shows:
  - the big parts of the repo and how they connect, opening down to files and then functions
  - step-by-step flows through the code
  - what changed since the last refresh, marked `+ − ~`
- A top line shows `Last refreshed: …` with **Refresh** and **Open in browser**. While a refresh runs it shows an animated spinner with the reason (`you asked` or `after the <plan> release`), the agent and the elapsed time. If you switch tabs, the tab button shows a busy dot, and then a "new" marker.
- A refresh runs on its own after a release task is ticked.
- The selected agent writes the descriptions. When its usage runs out, the backup agent takes over.
- Diagrams stay local in `~/.whyline/architecture/` and are never committed.
- `whyline architecture …` on the command line, calling the same functions.

Rules every task keeps:
- **Never disturbs the relay:**
  - Agents run only in their CLI's read-only mode (`whyline.agents.capabilities.read_only_command`); an agent without one can't be chosen.
  - Every git call passes `--no-optional-locks`, and agent environments set `GIT_OPTIONAL_LOCKS=0`.
  - No code in `src/whyline/architecture/` or `src/whyline/console/architecture_tab.py` calls the relay launcher, stop, interrupt, pause, resume or Resolve.
  - That code writes only under the architecture base dir, never into the repo.
- **Console first:** every console control saves through the same function the CLI calls.
- **No new dependency.** The browser page is self-contained: inline SVG, CSS and JS, and no URL starting with `http`.
- **Where code goes:**
  - Non-widget code goes in `src/whyline/architecture/`, with tests in `tests/architecture/`.
  - Widget code goes in `src/whyline/console/architecture_tab.py`, with tests in `tests/console/`.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Tests:**
  - They never run a real agent or relay, and never contain "/Users/".
  - Use fakes for the agent runner, relay state and the clock.
  - Real `git` is allowed only on temporary repos made inside the test.
- Agent answers and repo text are untrusted data in prompts. Wrap them in `<untrusted-data section="…">` tags.

## Part 1: The engine

- [ ] ARC-1: Storage and settings
  Create `src/whyline/architecture/__init__.py`, `store.py`, `settings.py` and their tests.
  1. `store.base_dir(repo, base=None) -> Path` gives `~/.whyline/architecture/<repo-slug>/`. Use the same slug function relay-chat's history uses; if it is private there, move it to a shared helper and keep relay-chat calling it. `base` is injectable.
  2. `store` reads and writes, all atomically (temp file then `os.replace`):
     - `current.json`, `previous.json` and `changes.json`: `load_current`, `load_previous`, `load_changes`, and `save_diagram(repo, diagram_dict)`, which moves current to previous first
     - `status.json`: `load_status`, `write_status`, `clear_status`. `load_status` clears an entry whose pid is not alive and returns it with `stale=True`.
     - `releases.json`: `release_done(repo, key) -> bool` and `mark_release(repo, key)`, where `key` is `"<plan>:<task-id>"`
     - `flows.toml`: `load_questions(repo) -> list[str]`, `add_question`, `remove_question(index)`
     - `html_path(repo) -> Path`
  3. `settings.load(repo) -> ArchSettings(agent: str | None, call_timeout_seconds: int = 300)` and `settings.save(repo, **changes)`. They are stored in `~/.whyline/architecture/settings.toml`, keyed by the resolved repo path. An unknown key or a bad value is refused with a plain message.
  Tests:
  - round trips
  - save moves current to previous
  - a stale status is cleared
  - a release key is marked once
  - two repos don't mix
  - bad settings are refused

- [ ] ARC-2: The scan: files, imports, top-level names, fingerprints
  Create `src/whyline/architecture/scan.py` and its tests.
  `scan(repo, *, run=subprocess.run) -> Scan`. The types are:
  - `Scan(files: dict[str, FileScan], folders: list[str], default_parts: dict[str, list[str]], fingerprint: str, part_fingerprints: dict[str, str])`
  - `FileScan(path, is_python, imports: list[str], names: list[Name])`
  - `Name(name, kind: "function"|"class"|"method", line)`

  How it scans:
  1. Files come from `git --no-optional-locks ls-files`. Python files are parsed with `ast`. A syntax error leaves that file with no imports or names, and never fails the scan.
  2. `imports` holds the repo-relative paths of the repo files each file imports. Resolve absolute imports against `src/` layouts and the repo root, and resolve relative imports.
  3. `default_parts` groups files by top-level package (under `src/<pkg>/` its sub-packages are the parts) or top-level folder. Test files go with the part they test when the path mirrors it, or else into `tests`.
  4. `fingerprint` is a sha256 over the sorted file list, the import edges and the top-level names (not line numbers). `part_fingerprints` is the same per default part.
  Tests, on temporary repos:
  - absolute, relative and `src/` imports
  - a body-only edit keeps the fingerprint
  - adding a function changes it and only that part's fingerprint
  - a syntax error doesn't fail
  - non-Python files are listed with no edges

- [ ] ARC-3: The scan: call edges and outside packages
  Edit `src/whyline/architecture/scan.py` and its tests.
  1. `FileScan.calls: list[Call(caller, callee_path, callee_name, line)]` records calls by name to a function or class imported from, or defined in, another repo file, including `module.func` through an imported module. Calls on other attributes are skipped.
  2. `Scan.outside: dict[str, OutsidePackage(name, names: set[str])]` covers imports of top-level packages that aren't in the repo, aren't standard library, and are named in the repo's `pyproject.toml` dependencies.
     - Their source is found with `importlib.util.find_spec`, run through the repo's `.venv/bin/python` when it exists (via `run`), and otherwise in-process. Their top-level names are parsed from that source.
     - A package that can't be found is kept with empty `names`.
     - Outside packages are not part of any fingerprint.
  Tests:
  - call edges through `from x import f` and `import x; x.f()`
  - attribute calls are skipped
  - an outside package found via a fake `run`
  - a missing one doesn't fail
  - the fingerprint is unchanged by outside packages

- [ ] ARC-4: The diagram model and validation
  Create `src/whyline/architecture/model.py` and its tests.
  1. Dataclasses with `to_dict` and `from_dict`:
     - `Diagram(parts, files, connections, flows, refreshed_at, trigger, agent, switched_from, scan_fingerprint, part_fingerprints, notes)`
     - `Part(name, purpose, members: list[str], outside: bool)`
     - `FileInfo(path, part, purpose)`
     - `Connection(src_part, dst_part, label)`
     - `Flow(title, question: str | None, steps: list[Step])`
     - `Step(part, path, name, text, verified: bool)`
  2. Validation functions, checked against a `Scan`:
     - `validate_overview(raw: dict, scan) -> (parts, connections)`:
       - members that aren't scanned are dropped
       - each scanned file goes to exactly one part, with leftovers in a part named `Other`
       - connections are kept only where a scanned import edge exists between the two parts
       - outside packages are added as `outside=True` parts
     - `validate_purposes(raw, scan, part) -> dict[path, purpose]` keeps Python files of that part only, with each purpose clipped to 120 characters.
     - `validate_flows(raw, scan) -> list[Flow]`:
       - at most 6 proposed flows, plus one per question
       - a step is `verified` only when its path is scanned and its name is in that file's names, or in an outside package's names
  3. `parse_json_answer(text) -> dict` takes the first fenced or bare JSON object, and raises `BadAnswer` otherwise.
  Tests:
  - invented files, connections and steps are dropped or marked unverified
  - leftovers go to Other
  - the 6-flow cap
  - JSON inside prose and inside a fence
  - `BadAnswer` on garbage

- [ ] ARC-5: Running an agent call, with the backup
  Create `src/whyline/architecture/agent.py` and its tests.
  1. `choices(repo) -> list[str]` lists the installed agents with `capabilities.can_run`.
  2. `primary(repo) -> str | None` is the saved agent if it is in `choices`, otherwise the relay's implementer agent from the relay config if it is in `choices`, otherwise the first entry of `choices`.
  3. `backups(repo, after) -> list[str]` is `whyline_relay.setup.read_backup(repo)` filtered to `choices`, without `after`.
  4. `call(repo, prompt, *, agent, runner=None, timeout, cancel_event=None) -> CallResult(ok, text, agent, failure: str | None, reason)`:
     - Build the command, wrap it read-only, run it in the repo with `GIT_OPTIONAL_LOCKS=0`, and kill the process group on timeout or cancel. Do this exactly as `whyline.relaychat.ask` does, by extracting a shared helper from it if it has none, and keep relay-chat's tests passing.
     - `failure` is `runner._classify`'s kind.
  5. `call_json(repo, prompt, *, start_agent, on_switch, …) -> (dict, agent_used)`:
     - On `BadAnswer` it retries once with "Reply with only the JSON object."
     - On `usage_limit` it calls `on_switch(old, new, reason)` and moves to the next backup.
     - On any other failure, or with no backup left, it raises `CallFailed(reason)`.
  Tests:
  - read-only arguments and the env var reach the fake runner
  - a retry after bad JSON
  - the switch on `usage_limit` calls `on_switch`
  - a login failure doesn't switch
  - no read-only agent gives a plain `CallFailed`

- [ ] ARC-6: Refresh
  Create `src/whyline/architecture/refresh.py` and its tests.
  `refresh(repo, *, trigger: str, agent=None, progress=None, cancel_event=None, clock=None, scanner=scan.scan, caller=agent.call_json) -> RefreshResult(ok, diagram, message, skipped: bool, undescribed_parts: list[str])`:
  1. If `store.load_status` shows a live refresh, return `ok=False`, "A refresh is already running". Otherwise write the status (pid, started, trigger, agent, step).
  2. Scan.
     - If the fingerprint and the flow questions match `current.json`, update only `refreshed_at` and `trigger`, save, and return `skipped=True`, "No structural changes".
  3. Run the overview call, then one part call per part whose part fingerprint changed (all parts on the first refresh), then the flows call.
     - The prompts follow the design's "agent pass".
     - Each call calls `progress(step_text, agent)` with step texts `overview`, `part <name> (i of n)` and `flows`, and updates `status.json`'s step.
     - A part call that fails keeps that part's previous purposes and adds the part to `undescribed_parts`.
     - An overview or flows failure fails the refresh: the old diagram is kept, the status is cleared, and the result is `ok=False` with the reason.
  4. Build the `Diagram`, `store.save_diagram`, and clear the status. (ARC-7 adds writing `changes.json` here, and ARC-10 adds writing the HTML.)
  5. `cancel_event` stops the current call, keeps the old diagram, and returns "Refresh stopped".
  Tests with a fake scanner and caller:
  - the skip rule
  - only changed parts are called
  - a part failure is reported, not fatal
  - an overview failure keeps the old diagram
  - progress steps arrive in order
  - a second refresh while one runs is refused
  - the status is always cleared, even on an exception

- [ ] ARC-7: What changed
  Create `src/whyline/architecture/changes.py` and edit `refresh.py` to call it, with tests.
  `compare(previous: Diagram | None, current: Diagram) -> Changes`:
  1. Marks per item:
     - parts, files and connections: `added`, `removed` or `changed`
     - a file is changed when its imports or names changed
     - a part is changed when any member changed
     - a connection is changed when its label changed
     - flows: `changed` when the sequence of (path, name) of its steps changed
  2. `counts` gives new parts, new files, new connections and removed items. Each part also gets a count for its closed form, e.g. `+3 ~1`.
  3. `summary_line(changes, previous)` gives `Since last refresh: 2 new parts, 5 new files, 3 new connections, 1 removed`, and the empty string when there was no previous diagram or nothing changed. `since_line(previous)` gives `Since 3 Nov, 16:02 (relay-chat release)` or `(you asked)`.
  4. `Changes` round-trips to `changes.json`.
  Tests: each mark kind, the counts, the lines' exact text, and a first refresh with no previous diagram.

- [ ] ARC-8: Guard test: architecture never touches the relay or the repo
  Create `tests/architecture/test_never_disturbs.py` only.
  1. In a temporary repo with a fake running relay (a state file, plus a log appended by a background thread), run `refresh` with a fake agent runner that tries to write a file and run `git status` through the provided environment. Check that:
     - nothing in the repo or `.git` changed apart from the fake relay's own writes
     - no `index.lock` was ever created
     - the relay launcher, stop, interrupt, pause and resume fakes, patched on `whyline_relay` and `whyline.console.relay_ops`, were never called
     - every file written is under the injected architecture base dir
  2. An AST scan of `src/whyline/architecture/` and `src/whyline/console/architecture_tab.py` checks for:
     - no calls named `start`, `stop`, `interrupt`, `pause`, `request_pause`, `resume` or `launcher`
     - no write calls to paths containing `.whyline/relay`
     - every `"git"` argv list containing `--no-optional-locks`
  Review focus (the complete list): the checks in 1 and 2 above. The agent's read-only mode is the real protection; these checks catch mistakes in our own code. The AST scan covers direct calls and literal argv lists only; calls through `getattr`, variables holding function names, or argv built at runtime are out of scope.
  A gap outside this list is not a reason to reject. The reviewer records it with `whyline handoff ARC-8 --issue "follow-up: <gap>"` and approves; the follow-ups become a later task.

## Part 2: Command line and browser page

- [ ] ARC-9: `whyline architecture`
  Edit `src/whyline/cli.py`. Create `src/whyline/architecture/cli.py` and its tests.
  1. Commands:
     - `refresh [--repo PATH] [--agent X]` prints progress lines as `progress` reports them, then the result. It exits 0, or 1 on failure.
     - `status` prints the same top line the tab shows, from `lines.top_line` (create `src/whyline/architecture/lines.py` here; ARC-11 uses it).
     - `show [--level overview|parts|files] [--changes]` prints the text tree from `render_text` (create `src/whyline/architecture/text.py` here: indented lines with `+ − ~` marks and closed-part counts).
     - `flows` lists the flows with `?` on unverified steps.
     - `flows add "<question>"` and `flows remove N`
     - `open` writes and opens the HTML page through `webbrowser.open`.
     - `--set-agent X` saves through `settings.save`.
  2. `lines.top_line(repo, now) -> str` gives the exact texts from the design's top-line table, without the spinner frame. The caller adds the frame.
  Tests:
  - each command with fakes
  - `top_line` for never built, idle manual, idle release, refreshing with elapsed time, switched to a backup, failed, stale (`Refresh stopped unexpectedly`) and no read-only agent installed (`No agent with a read-only mode is installed — install claude, codex or grok to build the diagram.`)
  - `--set-agent` calls `settings.save`

- [ ] ARC-10: The browser page
  Create `src/whyline/architecture/html.py` and its tests. Edit `refresh.py` to call it.
  `render_html(diagram, changes) -> str` gives one self-contained page:
  - inline CSS that follows `prefers-color-scheme`
  - an inline SVG drawn by inline JS from an embedded JSON copy of the diagram and changes
  - the Overview with parts as boxes (outside parts dashed) and labelled connections
  - clicking a part opens its files in place, with a back link
  - a legend for `+ − ~`, with new items highlighted and removed ones faded
  - a Flows list. A flow draws as a numbered sequence diagram, with **Next / Back** highlighting each step's box, and `?` steps drawn dashed.
  - the top line repeated
  - Embedded JSON is escaped so `</script>` in any purpose text can't break out.
  Tests:
  - no `http` substring anywhere in the page
  - every part name and the legend appear
  - a purpose containing `</script><script>alert(1)</script>` is escaped
  - a flow's steps appear in order

## Part 3: Console

- [ ] ARC-11: The Architecture tab and its top line
  Create `src/whyline/console/architecture_tab.py`. Edit `src/whyline/console/tui.py` only to add the button, mount the panel and route its buttons. Add tests in `tests/console/test_architecture_tab.py`.
  1. Add `Button("Architecture", id="file-architecture")` after `file-chat` in `#file-choices`, with the same display and variant rules in `_sync_file_choice_widgets`.
     - `_select_file_choice("architecture")` hides `#file-view` and `#file-tree` and shows an `ArchitecturePanel`.
     - The panel is mounted once and kept.
  2. The `ArchitecturePanel` contains:
     - the top line from `lines.top_line`, with a spinner frame (`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`) advanced by a 0.2-second timer while refreshing, and the elapsed time from the injectable clock
     - **Refresh**, disabled while refreshing and when `agent.choices` is empty; **Open in browser**, disabled before the first diagram; **Try again** after a failure
     - the summary and since lines from ARC-7
     - an agent menu listing `agent.choices`, saved through `settings.save`
  3. Refresh runs `refresh.refresh(trigger="manual")` on a worker thread. Progress arrives through `call_from_thread`. The old diagram stays shown until the result arrives.
  4. While a refresh runs and another tab is selected, the tab button's label is `Architecture •`. When a finished refresh has changes and the tab isn't selected, it becomes `Architecture ✱` until selected.
  5. A refresh started by the CLI or another console shows as refreshing too: the timer reads `store.load_status` while the tab is visible.
  Pilot tests, with fakes:
  - the tab shows only in Relay mode
  - the spinner text and elapsed time with a fake clock
  - Refresh is disabled while running
  - the busy dot and then the new marker
  - the old diagram stays until done
  - a failure shows Try again
  - the relay's `#stop` state is unchanged throughout

- [ ] ARC-12: Levels, navigation and change marks
  Edit `src/whyline/console/architecture_tab.py` and its tests.
  1. The view is a `Tree`:
     - Overview: parts with purposes and outgoing connections as child lines
     - opening a part shows its files with purposes; tests are grouped as `tests (n files)`
     - opening a file shows its names with line numbers and their callers from `Scan` calls. Read this from `current.json` plus a fresh `scan.scan`; the agent is not needed.
  2. **Overview · Parts · Files** buttons collapse to parts, expand all parts, or expand all parts and files. Esc collapses to the parent. A path line shows `Overview › <part> › <file>`.
  3. Marks `+` (green), `−` (red, faded) and `~`, plus the closed-part counts from ARC-7. **Show changes only** hides unmarked nodes, keeping the parents of marked ones.
  4. Selecting a name opens the file at that line in the Working file tab, through the same function the All files tree uses, and selects that tab.
  Pilot tests:
  - each level button
  - Esc goes up
  - the path line
  - marks and counts
  - Show changes only
  - selecting a name opens the file at its line

- [ ] ARC-13: Flows in the tab
  Edit `src/whyline/console/architecture_tab.py` and its tests.
  1. A **Flows** button next to Overview · Parts · Files shows the flow list, with `~` on changed flows.
  2. Opening a flow shows numbered steps `n. <part> › <file> › <name> — <text>`. Unverified steps show `?` and their text in a dimmed style. Selecting a verified step opens the file at that function.
  3. Under the list:
     - an input with **Add flow**, which calls `store.add_question` and shows `Added — it will be traced on the next refresh.`
     - each user flow has an **✕** that calls `store.remove_question`
  Pilot tests:
  - the list with marks
  - step text and `?`
  - a step opens its file
  - add and remove go through `store`

- [ ] ARC-14: Automatic refresh after a release
  Create `src/whyline/architecture/auto.py` and its tests. Edit `src/whyline/console/tui.py` only to call it from the existing relay status poll and at startup.
  1. `due_releases(repo, plan_path) -> list[str]` parses the plan with `whyline_relay.plan.parse` and returns the keys `"<plan-stem>:<task-id>"` of ticked tasks with `profile == "release"` that `store.release_done` doesn't know.
     - On the first call for a plan, it marks every already-ticked release as done without returning them, so old releases never refresh.
  2. When the poll finds a due key, the console marks it with `store.mark_release` and starts a refresh with `trigger="release:<plan-stem>:<task-id>"`. If a refresh is running, the key is queued and starts when it ends. Startup runs the same check once.
  3. The top line reads `after the <plan-stem> release`.
  Tests:
  - a newly ticked release task starts exactly one refresh
  - ticking a non-release task doesn't
  - a restart doesn't repeat it
  - the first look at a plan with old releases starts nothing
  - a queued release runs after the running refresh
  - no relay control is called

## Part 4: Settings, Help and docs

- [ ] ARC-15: Settings section, Help and docs
  Edit `src/whyline/console/settings_screen.py`, the console Help text and `README.md`, and create `docs/architecture.md`, with tests.
  1. The Settings screen gets an **Architecture** section, saved on Save through `architecture.settings.save`, and transactional like the rest of the screen:
     - the agent, from `agent.choices`
     - the time limit per call in minutes
  2. The Help text and `docs/architecture.md` explain:
     - the levels and Flows
     - the marks
     - Refresh and the automatic refresh after a release
     - the backup agent
     - that diagrams stay local in `~/.whyline/architecture/`
     - `whyline architecture`
  Tests: the Settings round trip; the Help mentions the Architecture tab and `whyline architecture`.
