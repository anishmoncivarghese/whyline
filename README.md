# whyline

Records why your code exists, and tells the next agent.

Claude Code, Codex, Grok, and Antigravity can work in the same repository. The agent that finishes writes what it chose and what it rejected. The next agent starts from that record.

Free, Apache-2.0, and local. There is no whyline account, no telemetry, and no paid tier.

whyline has no API key of its own, and it adds no bill. `whyline run` starts the CLI you already signed in to, on that vendor's subscription: Claude, ChatGPT for Codex, Grok, or Antigravity. Run the one you have. `whyline account status` shows the Claude and Codex plan that is signed in. `whyline model set <agent> <model>`, or `/model` in the console, picks the model for this repository.

```
$ whyline explain src/whyline/runner.py:46

src/whyline/runner.py:46

Last touched by   anish
Commit            bc677e4  ·  2026-08-17

Decision          Resolve runner injection points at call time, not in the signature
Because           default arguments bind at import time, so monkeypatching runner.shutil.which had no effect and a test exec'd the real codex binary, replacing the pytest process
Rejected          patch the default argument tuple in tests
                  couples every test to CPython internals

Confidence        High — a recorded decision matches the commit for this line.
                  one recorded decision matches the commit that wrote this line
```

That output is from this repository. An empty record produces an empty answer. `explain` says when it is guessing.

## Install

Once per machine:

```bash
uv tool install whyline
```

Once per Git repository:

```bash
cd your-project && whyline init
```

Python 3.11 or newer, and git. The executable is global. `init` is per repository, including each worktree, so one project's decisions never bleed into another.

`init` creates `.whyline/`, offers to add a short instruction to `AGENTS.md` and `CLAUDE.md`, and offers to install the Claude Code and Codex hooks. Pressing Enter accepts. `--yes` accepts both without asking. Re-run `init` any time; it upgrades the instruction block in place and leaves the rest of those files alone.

Codex runs a project hook only after you open `/hooks` and approve it. Until a real event arrives, `whyline status` says configured but never observed. If the `agy` binary is on your `PATH`, or the repository already has `.agents/`, `init` also installs the Antigravity hook. Grok has no hook. It still picks up the instruction in `AGENTS.md`.

Typing `whyline` with no arguments opens the console.

## What gets written down

| Path | What it is | Committed? |
|---|---|---|
| `.whyline/decisions.md` | The choice, the reason, the rejected alternatives, who made it, and which files it touches | Yes |
| `.whyline/active-handoff.json` | The current task, status, tests, and risks | No |
| `.whyline/ownership.json` | Advisory claims on a task or file | No |
| `.whyline/ledger.jsonl` | Sessions, prompts, and file touches | No |

`decisions.md` stays readable after you uninstall whyline. `whyline sync` packs the active handoff, git state, claims, and the relevant decisions into about 1,200 tokens, and leaves raw prompt text out. The full layout is in [docs/recording.md](docs/recording.md).

## Hand a task to the next agent

You decide who implements and who reviews. whyline carries the record across.

```bash
cd your-project
whyline claim WL-42 --actor codex --role implementer --file src/cache.py
whyline run codex "implement bounded cache invalidation" --task-id WL-42

whyline handoff WL-42 --from codex --to claude --status ready-for-review \
  --summary "bounded invalidation implemented" \
  --file src/cache.py --test "pytest -q: passed" \
  --risk "large repositories not benchmarked"

whyline run claude "review and commit the cache change" --task-id WL-42
```

`run` works with `claude`, `codex`, `grok`, and `antigravity`. Run it from your shell. It replaces the current process, so launching it from inside another agent's tool call leaves the new agent with no terminal.

`claim` warns when two agents claim the same task or file. It does not lock anything.

Codex's sandbox cannot write `.git`. Codex implements, tests, and stops. You or another agent makes the commit.

```bash
whyline sync                         # handoff, git state, claims, relevant decisions
whyline brief --file src/a.py        # decisions for the next agent, token-bounded
whyline explain src/a.py:14          # why this line exists
whyline note "chose X" --because "Y" --rejected "Z: too slow" \
  --file src/a.py --actor codex --role implementer --task WL-42
whyline status                       # is recording actually live?
```

## Optional: run a plan

[whyline-relay](https://github.com/anishmoncivarghese/whyline-relay) ships with whyline and stays off until you set it up. You give it a Markdown plan. It runs each task through an implementer and a reviewer, routes on the handoff record, and stops when a person needs to decide. It spends the subscription quota of the CLIs it launches.

```bash
whyline init --relay       # also fine later: whyline relay init
whyline relay doctor
whyline relay start
whyline relay status
```

`--yes` on `init` does not turn the relay on. `--relay` does.

## Also in the box

The console (`whyline`, or `whyline console`) is a full-screen app with Command, Chat, and Relay. Chat talks to whichever of the four CLIs is installed and signed in. `/model` lists them.

`whyline agents` saves a prompt you can run again, on a schedule, or when Mail receives a matching message. An unattended run is read-only. The result can go out by Mail or Telegram. The scheduler and the Mail rule are macOS. The Mail setup is [docs/agents-mail-recipe.md](docs/agents-mail-recipe.md).

`whyline account detect` refreshes the Claude and Codex plan names. Grok and Antigravity are reported as installed or missing, because those CLIs do not expose a plan check. The stored value is the plan name. The token is not stored and is not sent anywhere. A CLI that is already signed in with its own API key still launches; whyline never asks for that key.

## Limits

- A handoff is the explicit record. It is a separate session from the previous agent's hidden conversation.
- Agents record decisions when they own the session. Unprompted, Claude Code ran the brief near the start of 3 of 7 sessions (43%). Use `whyline run` or `whyline sync` when the handoff has to happen. The method and the reviewer gap are in [docs/measurement.md](docs/measurement.md).
- Claude Code's hooks have been observed in real use. Codex and Antigravity hooks are installed and reported separately by `whyline status`. Grok has no hook.
- macOS and Linux are tested in CI. Windows is not.
- Timings measured on the 0.2.0 worktree are in [docs/performance.md](docs/performance.md).

## Licence

Apache-2.0.
