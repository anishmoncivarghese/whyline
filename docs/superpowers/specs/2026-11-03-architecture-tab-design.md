# Architecture tab: see how the repo is built, kept fresh after every release

Date: 2026-11-03. Plan: `plans/architecture.plan.md` (ARC- tasks, kept small). Runs after `plans/safe-pause.plan.md` and before `plans/sdlc-pipeline.plan.md`.

## Why

The user runs long relays that change the repo a lot. After a plan finishes they want to see the repo's architecture as it is now: the big parts, how files connect, how the main flows run, and what the plan changed. Today the Files pane shows one file at a time (Working file, Plan, All files, and Chat once `relay-chat` ships), but nothing shows the whole.

Inspiration: archify (github.com/tt-a1i/archify). An agent reads a repo, writes a typed JSON description, and archify renders it as an interactive HTML page. We borrow the approach, not the tool. Archify needs Node and is an agent skill, and our plans add no dependencies.

## What the user gets

### The tab

The Files pane gets a new tab, **Architecture**, after Chat: **Working file · Plan · All files · Chat · Architecture**. Like the others it shows in Relay mode. It works for whichever repo the console is pointed at (agentdock, whyline-relay, …), and each repo has its own diagram.

Top line, with **Refresh** and **Open in browser** next to it:

| State | Top line |
|---|---|
| Never built | `No architecture yet — press Refresh to build it.` |
| Idle | `Last refreshed: 3 Nov, 16:02 · after relay-chat release · by claude` (or `· you asked`) |
| Refreshing (manual) | `⠹ Refreshing — you asked… (claude, 40s)` (animated spinner, elapsed time ticking) |
| Refreshing (automatic) | `⠹ Refreshing after the relay-chat release… (claude, 1m 20s)` |
| Switched to backup | `⠹ Refreshing — you asked… (codex, 2m 05s) · switched to codex (claude's usage ran out)` |
| Failed | `Refresh failed: <one-line reason> — showing the 3 Nov, 16:02 diagram.` with **Try again** |

- While a refresh runs, Refresh is disabled, so only one refresh runs at a time. The old diagram stays visible until the new one is ready, and then it is swapped in.
- If the user switches to another tab while a refresh runs, it keeps going and the Architecture tab button shows a busy dot (`Architecture •`). If the finished refresh has changes, the dot becomes a "new" marker (`Architecture ✱`) until the tab is opened.
- Under the top line: `Since last refresh: 2 new parts, 5 new files, 3 new connections, 1 removed` (hidden when there was no earlier diagram or nothing changed). The comparison is always with the previous refresh, and the line names it: `Since 3 Nov, 16:02 (relay-chat release)`. A hand refresh partway through a plan therefore moves the comparison point; that is intended, and the line always says which refresh it compares with.

### Levels and views

Buttons under the top line: **Overview · Parts · Files · Flows**, plus a **Show changes only** toggle.

1. **Overview:** the big parts, about 5–10, each with a one-line purpose, and which part uses which (`Console → Relay control: starts, pauses and reads the relay`). This is what the tab opens on.
2. **Part:** a part opened shows its files, each with a one-line purpose and the files in other parts it uses.
3. **File:** a file opened shows its top-level functions and classes and what calls them. Selecting one opens the file at that line in the Working file tab, through the same function All files uses.

In the console this is a tree. Enter or a click expands, Esc goes up, and a path line shows `Overview › Console › tui.py`. The Overview, Parts and Files buttons jump to a level: Parts expands every part, and Files expands every part and file.

**Change marks** at every level: `+` new (green), `−` removed (red, shown faded), `~` changed (a file whose imports or top-level names changed, a part whose files changed, a connection whose label changed). A closed part shows a count: `Console (+3 ~1)`. **Show changes only** hides everything unmarked, keeping the parents of marked items.

**Flows:** a list of step-by-step paths through the code. Each starts from something a user does, for example "Press Start on a relay", "A task's review is rejected", "Resolve a pause" or "Refresh this diagram". Opening one shows numbered steps:

```
1. Console › tui.py › on_start_pressed — checks a plan is picked
2. Relay control › relay_ops.py › start_relay — launches whyline-relay
3. whyline-relay › loop.run_plan — picks the first unticked task
```

- Selecting a step opens that file at that function.
- A step naming a file or function the scan can't find is marked `?` and isn't shown as fact.
- A flow whose steps changed since the last refresh shows `~` in the list.
- The agent proposes up to 6 flows. The user can add one by typing a question in a box under the list, such as "How does Pause now work?". It's saved and traced again on every refresh, and can be removed with an ✕.

### Browser view

**Open in browser** writes a self-contained HTML page and opens it with Python's `webbrowser`. The page has inline SVG, CSS and JS, with no network, CDN or dependency.

- The same levels: boxes for parts, clicked to open in place, and a back link.
- New boxes and lines are highlighted and removed ones shown faded, with a legend.
- Flows are drawn as numbered sequence diagrams. **Next / Back** steps through them, highlighting each box.
- The top line repeats the last-refreshed text.
- It follows the system's light or dark mode.

### Command line (console first)

`whyline architecture` with subcommands, all calling the same functions as the tab:
- `refresh [--repo PATH] [--agent X]` refreshes, printing the same spinner text (plain lines when not a TTY), and exits 0 on success, 1 on failure.
- `status` prints the top line: last refreshed / refreshing / failed.
- `show [--level overview|parts|files] [--changes]` prints the text tree.
- `flows`, `flows add "<question>"` and `flows remove <n>` manage the flows.
- `open` opens the browser page.
- `--set-agent X` saves the agent choice through the same function as Settings.

## How it works

### Storage (local only)

Everything is kept in `~/.whyline/architecture/<repo-slug>/`, outside the repo so it is never committed. The slug is the same per-repo slug `relay-chat` uses for its history.
- `current.json`: the latest diagram, with its `refreshed_at`, `trigger` (`manual` or `release:<plan>:<task-id>`), `agent`, `switched_from` and `scan_fingerprint`
- `previous.json`: the one before, kept only for the change marks; there is no longer history
- `changes.json`: the comparison of the two
- `status.json`: only the refresh in progress (pid, started, trigger, agent, current step), so the CLI, a second console, and a console restarted mid-refresh all see it. A stale entry, whose pid is gone, is cleared and reported as `Refresh stopped unexpectedly`.
- `releases.json`: the release task ids (`<plan>:<task-id>`) already refreshed for, so an automatic refresh happens once per release, even across restarts.
- `flows.toml`: the user's flow questions for this repo
- `architecture.html`: the browser page, rewritten on each refresh and on Open

The agent choice is kept in `~/.whyline/architecture/settings.toml`, keyed by the resolved repo path, the same layout as relay-chat's settings. `architecture.settings.save` is the one function the Settings section, `--set-agent` and the tab's agent menu all save through.

All writes are atomic. The base dir is injectable for tests.

### The scan (no agent, always accurate)

- Python files are parsed with `ast`. For each file it records the imports within the repo, and the top-level functions, classes and methods with line numbers.
- It also records call edges by name: a call to a name imported from, or defined in, another repo file. This is best effort; calls through attributes on unknown objects are skipped.
- Every other tracked file (from `git --no-optional-locks ls-files`) is listed with no edges.
- Default parts are the top-level packages and folders.
- **Outside packages:** an import of a module not in the repo but installed in the repo's environment (for example `whyline_relay`) becomes one *outside part* per top-level package, shown at the Overview as a dashed box (`whyline-relay (outside)`). Its files aren't listed and it can't be opened. Flow steps into it are checked by locating the module's source through `importlib.util.find_spec` in the repo's `.venv` Python (falling back to the current interpreter) and parsing its top-level names. Outside packages are not part of the fingerprint. Standard library and third-party packages other than those the repo's own `pyproject.toml` names as dependencies are ignored.
- The fingerprint is a hash of the file list, the import edges and the top-level names. It does not include line numbers or bodies, so edits inside a function don't count as a structure change.
- The scan is the source of truth for level 3, for edges, and for checking flow steps.
- The scan reads the repo's working tree as it is when the refresh starts, using whatever branch is checked out (on an automatic refresh, the relay branch right after the release tick).

### The agent pass (meaning only)

The agent pass is split into small calls, so a large repo (agentdock has about 670 tracked files, 325 of them Python) never needs one huge answer:
1. **Overview call:** the agent receives the folder tree, the part-level edges and the previous overview. It returns the parts (name, one-line purpose, member folders or files; every scanned file is in exactly one part, and files left out go to an "Other" part) and a label for each part-to-part connection that exists in the scan.
2. **Part calls:** one per part whose files changed since the previous diagram (all parts on the first refresh). The agent receives that part's Python files with their imports and top-level names, and returns a one-line purpose per Python file. Non-Python files (docs, plans, config) get no purpose line; tests are grouped under their part as `tests (n files)`.
3. **Flows call:** the agent receives the overview, the part summaries and the flow questions. It returns up to 6 flows, plus one per user question, each as steps of file and function.

Each call returns JSON in its answer, and the agent never writes files. Each call has its own time limit (default 5 minutes), its own single retry on bad JSON, and the backup switch applies per call. A part call that still fails leaves that part's previous purposes (or none) and the refresh reports `1 part not described` instead of failing.
- whyline validates the JSON against the scan: unknown files are dropped, invented connections dropped, and unknown steps marked `?`. Bad JSON is retried once, then the refresh fails.
- The agent runs in its CLI's read-only mode, exactly as the relay-chat ask does (`capabilities.read_only_command`), with `GIT_OPTIONAL_LOCKS=0`.

**Skip rule:** if the scan fingerprint equals `current.json`'s and the flow questions haven't changed, no agent runs. Per-part fingerprints decide which part calls are needed. The refresh only updates `refreshed_at` and trigger, and says `No structural changes`.

### Choosing the agent, and the backup

- The agent is the one chosen for Architecture, saved through the **Architecture** section of the console's Settings screen, the tab's agent menu, or `--set-agent`. With none saved, it's the relay's implementer agent.
- Only agents with a read-only mode can be chosen (`capabilities.can_run`), the same rule as Chat.
- If the agent fails with `usage_limit`, as classified by `whyline.agents.runner._classify`, the refresh moves to the next agent in the relay backup chain (`whyline_relay.setup.read_backup`) that has a read-only mode. The top line says so, and `current.json` records `switched_from`.
- A login problem or an unknown failure doesn't fall back. It fails the refresh with the reason.
- With no read-only agent installed, Refresh is disabled and the top line explains why.

### Automatic refresh after a release

The console already polls relay state. When it sees a task whose `relay-profile` is `release` go from unticked to ticked in the running plan, it starts a refresh with trigger `release:<plan>:<task-id>`, once per task id, recorded in `releases.json`. The tick is the trigger: the relay ticks a release task only after the release steps are done, so a release whose checks failed is never ticked and never refreshes. A plan without a release task never auto-refreshes.

- The refresh runs in the background, uses only read-only commands, and never calls the relay launcher, stop, pause or resume.
- If a refresh is already running, the automatic one is queued and runs right after.
- If the console wasn't open when the release was ticked, opening the console on that repo notices the ticked release task has no refresh yet and starts one.

## Decisions (my calls)

- Our own generator, not archify, because of no new dependency and no Node.
- Scan plus agent: the scan gives facts, the agent gives names and meaning. Level 3 never uses the agent.
- Only one previous diagram is kept, for the change marks.
- The agent is read-only and returns JSON; whyline writes every file.
- Python gets edges and levels; other languages are listed as files only. More languages are a later change.
- The tab follows the other Files tabs: Relay mode only.
- Run order: after `safe-pause`, before `sdlc-pipeline`. It builds on the Chat tab's place in the Files pane, and sdlc's Docs screen can link to it later.

## Out of scope

- Non-Python import graphs.
- Editing the diagram by hand.
- History beyond one previous diagram.
- Exporting to PNG or PDF (the browser's print covers it).
- Committing or sharing the diagram.

## Testing

- Scan tests run on small temporary repos: imports, call edges, the fingerprint staying stable across body edits, and non-Python files.
- Agent-pass tests use a fake runner returning JSON: validation drops invented items, `?` steps, the retry on bad JSON, the switch to the backup on `usage_limit`, and the skip rule.
- Change tests: `+ − ~` at each level and the counts.
- Pilot tests with fakes for the console: the tab, the spinner text and elapsed time with a fake clock, the busy and new markers, the levels and navigation, the auto-refresh on a release tick (once), and that the relay's controls are untouched.
- HTML tests: the page is self-contained (no `http` URLs), and it contains every part and the legend.
- Tests never run a real agent or relay, and never contain "/Users/".
