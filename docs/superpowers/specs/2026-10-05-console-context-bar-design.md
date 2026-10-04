# Console context bar, repo setup and mode-specific controls

Date: 2026-10-05
Status: draft for review
Repo: whyline (console only). It uses the existing whyline-relay functions
(`init.ensure_permission_files`, `antigravity.*`) and whyline's own `init`.

## Why

- The top-right corner (`claude · default model | repo: agentdock ~/agentdock`)
  is display-only. Changing the agent means `/model claude opus`, and changing
  the repo means `/repo ~/path`. A folder that isn't a git repo, or isn't set
  up for whyline, then needs `git init`, `whyline init` and agent permissions
  done by hand. That's what tripped TradingPlatform up.
- The bottom bar is almost the same in every mode, so Brainstorm, Model and
  History sit in modes where they mean nothing.
- Command mode (typed text runs as `whyline <command>`) is the mode the
  console opens in, yet it's the least used. Its commands are just as usable
  as `/` commands from any mode.

## Decisions (with the user, 2026-10-04/05)

- **A context bar row** with Agent ▾, Model, Repo and Save. Save is greyed
  until something differs from what's saved.
- **Save sets this repo's default** agent and model. A **Use for all repos**
  checkbox also makes it the default for repos without their own.
- **Typing a repo that isn't set up** offers to set it up: create the folder
  if missing, `git init`, `whyline init`, relay permission files, and the
  Antigravity trust question. This also delivers the "first-run readiness"
  part of the setup-ease ideas.
- **Command mode is removed.** Any `whyline` command runs from any mode as
  `/<command> …`. Three modes remain: Chat, Relay, Agents. The console opens
  in Chat.
- **Each mode shows only its own bottom-bar buttons;** the rest are hidden.

## Design

### 1. The context bar

A row directly below the mode buttons (`#context-bar`), replacing the
right-aligned `#context` text:

```
 Agent [claude ▾]  Model [default        ]  Repo [~/agentdock                 ]  [ ] all repos  [Save]
```

- **Agent** (`#cb-agent`, a Select) lists the agents that
  `account.agent_status(root)` marks available, labelled
  `claude · pro`. Unavailable ones appear disabled-looking at the end, as
  `grok · not signed in` with value `"!grok"`. Choosing one shows its hint
  ("Run /login grok") and the selection snaps back.
- **Model** (`#cb-model`, an Input, placeholder `default`) holds the model for
  the selected agent. It starts as the saved value from `whyline.model`, and
  an empty field means the CLI's default. There is no fixed list: whyline
  never validates model names (spec M4), and the providers change them.
- **Repo** (`#cb-repo`, an Input) holds the current repo path, `~`-shortened.
- **All repos** (`#cb-global`, a Checkbox, unticked by default) is described
  in section 2.
- **Save** (`#cb-save`) is disabled until the agent, model or repo differs
  from the saved state. Pressing Enter in Model or Repo does the same as
  Save.
- **Width.** At 80 columns, the labels shorten to `A`, `M` and `R`, and the
  inputs share the remaining space. The row never wraps and never pushes
  Save off-screen. A test at size `(80, 24)` checks this.
- **When the agent or repo changes** in any other way (`/model`, `/repo`, the
  Model button, Run's flows), the bar updates to match, and Save goes back
  to disabled.

### 2. Saving the agent and model

- **Repo default:** `.whyline/model.json` gains a `"default_agent"` key next
  to the per-agent model keys, e.g. `{"default_agent": "codex", "codex":
  "gpt-5.6"}`. Saving writes both keys (`model.set_one` for the model and a
  new `model.set_default_agent(root, agent)`), sets `session.agent`, and
  renders `Default for this repo: codex · gpt-5.6`.
- **Global default (`all repos` ticked):** the same two values also go to
  `~/.whyline/console.json` (`{"default_agent": …, "models": {agent:
  model}}`). The message adds `(also for every repo without its own)`.
- **On start, and after switching repo,** the chat agent is the repo's
  `default_agent`, else the global one, else `claude`. The model for that
  agent follows the same order. Today the console always starts on `claude`;
  this makes the saved choice stick.
- `/model claude opus` keeps working, and now also saves the repo default
  agent, so the bar and `/model` never disagree.

### 3. Switching repo, and setting one up

Pressing Save with a different Repo path:

1. **Refusals, checked first:**
   - a relay run, plan, spec or brainstorm job is in progress: "Finish or
     stop the current job before switching repo.";
   - the path is the home folder: the existing `_HOME_REFUSAL`;
   - the path is inside another git repository but isn't its root:
     "<path> is inside the repository <root>. Use <root>, or pick a folder
     outside it." This catches the mistake that left TradingPlatform without
     its own repo.
2. **An existing, set-up repository** (a git root with `.whyline/`): the
   existing switch (`switch_repo` with its confirmation, because switching
   clears the transcript).
3. **Anything else** gets one confirmation, worded for what's missing, e.g.:

   > Set up ~/NewProject for whyline? This will: create the folder · run git
   > init · run whyline init · write the relay's agent permission settings ·
   > make a first commit with those files. Antigravity will ask separately
   > whether to trust this folder.

   On **Set up**, in a worker thread with progress lines `setup · …`:
   1. `mkdir -p` when the folder is missing;
   2. `git init -b main` when it isn't a repository;
   3. `whyline init --yes` when `.whyline/` is missing;
   4. `relay_ops.prepare_agents(root, <installed relay agents>)` (from
      0.3.32) for the permission files;
   5. a first commit of only the files this setup created
      (`gitcheck.commit_paths`), message `chore: set up whyline`. Skipped
      when there's nothing to commit, or when the repo already had commits
      and the user's own files are uncommitted; those are never touched;
   6. switch to the repo;
   7. if Antigravity is installed, the existing once-per-repo trust question
      (`_with_antigravity`).

   **Cancel** leaves everything as it was.
4. **Setup errors** (git missing, no permission to create the folder) appear
   as an error line. Steps already done stay done, and the line says which
   step failed. Retrying with Save repeats only the missing steps, because
   each step is skipped when it's already done.

### 4. Removing Command mode; `/` runs whyline commands

- The mode buttons are **Chat · Relay · Agents**. The console opens in Chat.
  `session.mode` can no longer be `"command"`; any saved or passed `command`
  mode maps to `chat`.
- **Slash routing,** in order:
  1. the console's own slash commands (`/help`, `/model`, `/repo`, `/status`,
     `/history`, `/login`, `/brainstorm`, `/stop`, `/exit`, `/paste`,
     `/route`);
  2. otherwise, when the first word after `/` is a subcommand of the
     `whyline` CLI (read from `cli.build_parser()`'s subparsers, so new
     commands appear automatically), the line runs as `whyline <rest>`
     through the existing `adapters.run_whyline_command`, with output in the
     transcript;
  3. otherwise, the existing unknown-command message, which now lists the
     whyline commands too.
- `/route` accepts `chat`, `relay` and `agents`. `/route command` says
  "Command mode is gone: type /<whyline command> from any mode, e.g.
  /timeline."
- `/help` gains a "whyline commands" section listing each subcommand and its
  one-line help, from the parser.
- **Typing `/`** in the prompt (only the slash, nothing else) shows a one-line
  hint above the prompt with the most-used commands: `/status /timeline
  /note /decisions /handoff /model /repo /help`. The hint disappears on the
  next keystroke.

### 5. Mode-specific bottom bar

| Mode | Buttons |
|---|---|
| Chat | Model · Brainstorm · History |
| Relay | Run · Plan · Set up · Resume |
| Agents | New · Agents · Runs · Scheduler |
| every mode | Stop · Help · Copy |

- Buttons that don't belong to the current mode are hidden (`display =
  False`), not just disabled. The Attach button in the input row shows in
  Chat only, and the Brainstorm button in Chat only. Brainstorm in Relay
  happens through Run / Plan.
- `_sync_mode_buttons()` is the one place that decides visibility. It
  replaces the per-feature visibility code in `_sync_relay_buttons` and
  Agents mode. Enable and disable rules stay where they are (Stop while
  busy, Resume when paused, …).
- A test checks every mode at 80 columns: each visible button's
  `region.right <= 80`, and no hidden button can be focused.

## Error handling

- An unavailable agent picked in the bar snaps back, with its hint.
- A **Model** value with spaces or quotes is rejected with "A model name has
  no spaces", the same rule as `/model`.
- **The Repo path** expands `~` and is resolved. An empty path does nothing.
- **Saving while a reply is in flight** saves the agent and model at once,
  for the next message; a repo switch is refused, as in section 3.
- **`~/.whyline/console.json` unreadable:** ignored, with a warning line
  once; repo defaults still apply.

## Testing

- **Context bar:**
  - Save is disabled until a change, and becomes disabled again after
    saving;
  - picking an unavailable agent snaps back with its hint;
  - the repo default is written to `model.json`; "all repos" also writes
    `console.json`;
  - start-up precedence: repo, then global, then claude;
  - `/model` updates the bar;
  - 80-column fit.
- **Repo setup** (a tmp home, real git):
  - an existing repo switches;
  - a plain folder is set up (git, whyline init, permission files, a first
    commit containing only those files) and switched to;
  - a missing folder is created;
  - home and nested-repo paths are refused;
  - a job in progress refuses the switch;
  - a failing step reports which one and a retry completes it;
  - the user's own uncommitted files are never committed;
  - the Antigravity question is asked when agy is installed (stubbed).
- **Command mode removal:**
  - the mode buttons are Chat, Relay and Agents;
  - the console opens in Chat;
  - `/timeline` runs `whyline timeline` (stubbed `run_whyline_command`);
  - console slash commands win over whyline commands with the same name;
  - `/route command` explains;
  - `/help` lists the whyline commands.
- **Bottom bar:** for each mode, exactly the listed buttons are visible,
  within 80 columns.
- Tests never depend on installed agent CLIs and never touch the real home
  folder.

## Releases

One console release. It follows whyline 0.3.34 (relay guided flow v2), so
it is **whyline 0.3.35**. Agents mode then becomes 0.3.36 (Phase 1) and
0.3.37 (Phase 2). The Agents plan's bottom-bar task (its Task 8) shrinks: it
adds its buttons to the Agents row of `_sync_mode_buttons`.
