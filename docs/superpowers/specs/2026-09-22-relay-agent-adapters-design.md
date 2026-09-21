# whyline-relay: pluggable agent adapters

Status: design, reviewed against the relay source on 2026-09-22; section 9 corrects it and wins where they differ. Written 2026-09-22.
Relates to: `2026-09-20-whyline-relay-design.md` (the relay's original design) and
`plans/2026-09-21-relay-0.2.1-and-combined-install.md` (the release this follows).

## 1. Summary

Today the relay runs exactly two agents in fixed roles: Codex implements and Claude
reviews and commits. The owner has subscriptions to more than one agent (Claude, Codex,
Gemini) and wants to choose which agent fills which role, and eventually to run
multi-stage pipelines (plan, develop, test, commit) across them.

That is four independent pieces: (1) agent adapters, (2) pipeline stages, (3) a planner
stage, (4) subscription-aware behaviour such as moving a stage to another agent when one
runs out of quota. **This design covers only piece 1**, the foundation the others need.
Pieces 2 to 4 each get their own design.

Piece 1 makes the two existing roles pluggable: any built-in agent (`codex`, `claude`,
`gemini`) or an explicitly configured generic agent can be the implementer or the
reviewer. Nothing about existing behaviour changes for existing configurations.

## 2. Where the relay is today

The two names are hard-coded in eight files (measured 2026-09-22 on relay 0.2.1), and a ninth, `handoff.py`, lacks a field the design needs:

| File | What is fixed |
|---|---|
| `routing.py` | `IMPLEMENTER = "codex"`, `REVIEWER = "claude"`; a handoff is routed only if its `to_actor` equals these |
| `config.py` | the default command for exactly `codex` and `claude` |
| `loop.py` | which agent runs a move (`"codex" if implement else "claude"`), the progress verb, the `claim` actor (`whylinecmd.claim(..., "codex", "implementer")`), and the check that only the `codex` agent must not move HEAD |
| `preflight.py` | login checks exist only for programs named `codex` (`codex login status`) and `claude` (`claude auth status`) |
| `prompts.py` | the built-in prompts contain the literal `--from codex --to claude`, `--actor claude`, and so on |
| `init.py` | writes `claude-settings.json` and the two default commands |
| `cli.py`, `running.py` | names in messages and the running marker |
| `handoff.py` | reads `to_actor`, `status`, `summary`, `questions`, `task` and the event id, but **not** `from_actor` |

Agent-independent code already exists and stays as it is: the loop, reading whyline
handoffs, the HEAD-moved check, commit verification, the clean-tree check, the plan tick,
timeouts and process-group kill, progress lines, the running marker and saved state.

## 3. Goals and non-goals

Goals

- Any built-in agent can fill either role, chosen in `config.toml`.
- Existing repositories and configs keep working with no migration.
- Each adapter carries its own safety story, and the relay says plainly what it does
  and does not manage for every configured agent.
- The Gemini adapter is added, built from facts measured in a real run.

Non-goals (later designs or never)

- Pipeline stages, a planner stage, quota fallback between agents.
- The relay writing handoffs on an agent's behalf. Agents record their own work; that is
  the point of the record.
- MCP, ACP, or any protocol beyond running a headless command.

## 4. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | Build the adapter foundation first | Every later piece depends on it, and it delivers a concrete win alone (for example Gemini reviewing Codex's work) |
| D2 | Handoffs and notes record the **agent's name** as the actor (`--from gemini --to claude`) | whyline's purpose is provenance: the record must say which model did the work. Existing `codex`/`claude` history keeps its meaning |
| D3 | Built-in adapters **plus** a `generic` adapter | Flexibility for other tools, with the limits in section 7 made explicit |
| D4 | The same agent may fill both roles, with a visible warning | One-subscription users are not blocked; the weaker independence is stated, not hidden |
| D5 | Adapters are code modules with one interface (approach A), not TOML profiles | Denial parsing and permission enforcement do not fit data well, and misconfigured data would weaken the safe-by-default promise |

Rejected: swapping only the command under the fixed names (no login checks or permission
files for the substitute, confusing labels, no path to pipelines); TOML adapter profiles
(D5).

## 5. Design

### 5.1 Configuration and roles

```toml
[roles]                       # new; both optional, these are the defaults
implementer = "codex"
reviewer    = "claude"

[agents.codex]                # as today: optional overrides of the command
command = ["codex", "exec", "-s", "workspace-write", "--color", "never"]

[agents.gemini]               # a built-in agent needs no adapter line

[agents.aider]                # anything else opts in explicitly
adapter = "generic"
command = ["aider", "--message"]
```

- An agent named `codex`, `claude` or `gemini` uses its built-in adapter. Any other name
  must set `adapter = "generic"` and a `command`, or configuration loading fails. There
  is no silent fallback.
- The default `[roles]` reproduce today's behaviour exactly, so existing `config.toml`
  files need no change.
- Routing compares a handoff's `to_actor` with the configured agent names instead of two
  constants. Status strings (`ready-for-review` and the rest) do not change.
- Prompt templates gain the placeholders `{implementer}` and `{reviewer}` so the handoff
  commands name the right agents. Templates written by relay 0.2.x contain the literal
  names. They stay valid while the roles are the defaults. If a role is changed and a
  template still has the literal names, the preflight refuses with a message telling the
  user to run `init --overwrite`, so no agent is ever told to hand off under the wrong
  name.

### 5.2 The adapter interface

An adapter answers only what is specific to one tool:

| Question | codex | claude | gemini | generic |
|---|---|---|---|---|
| default command | `codex exec -s workspace-write --color never` | `claude -p ... --settings <file>` | `gemini -p ...` plus policy and trust flags (final form from the spike) | none: required in config |
| login check | `codex login status` | `claude auth status` | none in its help; set by the spike (possibly only a "cannot verify" warning) | none |
| permission files written by `init` | none | `claude-settings.json` | a policy file for `--policy` | none |
| reading a denial from output | last line, as today | JSON `permission_denials`, as today | from its JSON output, per the spike | last line |
| extra quota wording | shared markers | shared markers | its own, per the spike | shared markers |
| bypass flags it refuses | the `--dangerously-*` set | `--dangerously-skip-permissions` | `--yolo`, `-y`, `--approval-mode yolo` | not inspectable |
| what it manages | permissions, login, denials | permissions, login, denials | per the spike | nothing |

Sketch (illustrative, names may change in the plan):

```python
@dataclass(frozen=True)
class Adapter:
    name: str
    default_command: tuple[str, ...] | None
    permission_files: Callable[[str], dict[str, str]]     # stack -> {relative path: content}
    login_check: Callable[[Runner], CheckResult] | None
    diagnose: Callable[[str], str]                        # log text -> human detail
    quota_markers: tuple[str, ...]
    bypass_flags: tuple[str, ...]
    manages: Manages                                      # permissions / login / denials / sandbox
ADAPTERS = {"codex": ..., "claude": ..., "gemini": ..., "generic": ...}
```

### 5.3 What changes, by module

| Module | Change |
|---|---|
| `config.py` | parse `[roles]`; resolve each role to an agent spec (name, adapter, command); keep today's defaults |
| `adapters/` (new) | the registry and one module per adapter |
| `routing.py` | compare with the configured agent names |
| `loop.py` | take the agent and command from the resolved spec; the progress verb and the `claim` actor come from the role; the HEAD check applies to whoever is the implementer; ask the adapter for denial detail and quota markers; check the handoff's `from` actor |
| `handoff.py` | also read `from_actor` |
| `preflight.py` | per role: program on PATH, login via the adapter, permission files exist; same-agent warning; generic notice; template-vs-roles check; bypass-flag refusal |
| `prompts.py`, `init.py` | placeholders; write only the permission files for agents in use; `--implementer` and `--reviewer` options |
| `cli.py` | new `init` options; messages unchanged |

### 5.4 Safety

The rule is unchanged: the relay never passes a permission-bypass flag and never widens an agent's permissions. What a generic agent's own tool allows by default is outside the relay's control, which is why generic agents are opt-in and labelled.

Guarantees for every agent, built-in or generic (all agent-independent code): never
`git push` and never pass a bypass flag; the implementer may not commit (HEAD is checked
after its turn); an approval needs a commit naming the task and a clean tree; timeouts,
process-group kill, one relay per repository, stop at the first problem.

New checks:

1. **Bypass flags are refused per adapter.** If a built-in agent's configured command
   contains one of that adapter's bypass flags, `doctor` and `start` refuse. The source
   guard test (`test_no_bypass`) gains the Gemini flags. A generic agent's command cannot
   be inspected reliably, so it gets only the notice in item 3.
2. **The handoff must come from the agent that just ran.** A mismatch pauses the run
   (for example a template that makes Gemini hand off as `codex`).
3. **An honest per-agent summary**, printed by `doctor` and once by `start`:
   `implementer: gemini  permissions: policy file  sandbox: yes  login: not verifiable`
   `reviewer: aider      generic: the relay does not manage its permissions, login or denials`

A generic agent must be able to run `whyline handoff` and `git` in a shell. If it cannot,
the relay pauses with "exited without handing off". A generic agent runs with whatever
permissions its own tool grants and inherits the relay's environment, including any API
keys. The line `adapter = "generic"` is the owner's explicit acceptance of that.

### 5.5 `init` and `doctor`

- `init` writes the roles into `config.toml` and the permission files only for the
  agents in use. `init --implementer NAME --reviewer NAME` sets the roles at setup.
- `doctor` prints one summary line per role (5.4 item 3) plus the warnings and refusals
  above.

### 5.6 The Gemini adapter and the spike

Known from `gemini --help` (version 0.60.0, package `@google/gemini-cli`, read on
2026-09-22 from an isolated install with its own `HOME`; help text kept in the
scratchpad):

- Headless: `-p/--prompt`, and `-o/--output-format` with `text`, `json`, `stream-json`.
- Approvals: `--approval-mode` with `default` (prompt), `auto_edit`, `yolo` and `plan`
  (read-only). `-y/--yolo` auto-approves everything and is a bypass for our purposes.
- Permissions without a bypass: `--policy <files>` and `--admin-policy` load policy files
  (the Policy Engine). `--allowed-tools` is deprecated in its favour.
- Workspace trust: `--skip-trust` ("Trust the current workspace for this session"), the
  same kind of trap Claude has, with a flag as the remedy.
- `-s/--sandbox`, `-w/--worktree`, ACP mode, extensions, skills, hooks and MCP exist.
- There is **no auth-status command** in the help.

Unknown until a real, signed-in run (the spike, build step 0):

1. Can headless Gemini run `git` and `whyline handoff` under a policy, without a bypass?
2. Does its sandbox stop it committing?
3. Does it read `AGENTS.md`, or only `GEMINI.md`?
4. How does a denial appear in its JSON output, and what are its exit codes?
5. What does a small task cost?

The spike is one small headless task in a throwaway repository, measured the way the
Codex and Claude assumptions were measured in the relay's first real-CLI run, which
disproved two of them. The Gemini adapter is written only after it. `~/.gemini` already
exists on the owner's machine with an OAuth credentials file, so a sign-in may not be
needed; the spike must not read that file's contents.

## 6. Build order and testing

0. **Spike** (needs the owner): the Gemini facts above.
1. **Adapter refactor with no behaviour change**: registry with `codex`, `claude`,
   `generic`; `[roles]`; placeholders; the from-actor check; preflight and `init` use
   adapters. **Regression net: all existing tests and all 97 acceptance tests pass
   unchanged.**
2. **The Gemini adapter** from the spike, with its policy file. Then a real run with
   Gemini reviewing Codex's work, then Gemini implementing.
3. **`doctor` summaries, bypass-flag refusal, README, release notes.**

Each step is a relay task run through the relay itself, with independent acceptance tests
written before the run, as for 0.2.0 and 0.2.1. Contract tests run against every adapter
with fakes; black-box tests use `codex`, `claude` and `gemini` stand-ins on PATH that
can be logged in or out (the technique used for the `doctor` tests).

## 7. Risks and open questions

- **Gemini login check.** With no status command, the check may only warn. The spike
  decides whether a cheap reliable check exists.
- **Policy file format and trust behaviour** are unmeasured; step 2 may reshape the
  adapter interface. The interface is deliberately small so that is cheap.
- **Sandbox availability.** `--sandbox` on macOS uses Seatbelt and elsewhere Docker or
  Podman; an adapter default must not assume it. The per-agent summary reports whether
  the sandbox is on.
- **Old prompt templates** need `init --overwrite` when roles change (5.1). Users who
  edited their templates must merge by hand.
- **Same agent in both roles** gives a weaker check (D4).
- **Release coordination.** whyline 0.3.0 pins `whyline-relay>=0.2.1,<0.3`. Adapters are
  backward compatible, so release them as relay 0.2.2, or widen the pin in a whyline
  patch. Decide when the plan is written.
- **API stability.** The relay is 0.x and `cli.main` is its embedding API; adapters do not
  change it.

## 8. Decision log (this design session, 2026-09-22)

| Question | Answer |
|---|---|
| Which piece first? | Agent adapters |
| Actor identity when any agent can fill a role? | The agent's name |
| Built-in only, or also a generic adapter? | Built-in plus generic |
| Same agent in both roles? | Allowed with a visible warning |
| Approach? | A: code adapters with one interface |
| Sections 1 to 4 of the design | Each approved as presented |

## 9. Corrections found when the design was checked against the source (2026-09-22)

The design was re-read line by line against relay 0.2.1 before the implementation plan was
written. These points were wrong or missing; where they differ from sections 1 to 7, this
section wins. The plan (`plans/2026-09-22-relay-agent-adapters.md`) implements them.

| # | Finding | Correction |
|---|---|---|
| C1 | `running.py:42` rejects any marker whose agent is not `codex` or `claude`, so a marker written for any other agent reads as "no relay running". The one-relay-per-repository guard would fail open for every non-default agent. Section 2 listed `running.py` only as "names in messages". | The marker accepts any non-empty agent name and gains a `role` field (default empty, so old markers stay valid). This is a safety fix, not naming. |
| C2 | 5.2 and 5.4 put bypass flags in each adapter, and add the Gemini flags to the guard test. `tests/test_no_bypass.py` fails the build if any file under `src/` contains one of those strings, so the design contradicts its own guard. | One module, `adapters/bypass.py`, holds the refused flags and is the only file the guard exempts. A test pins the exempt set to that one file. Adapters carry no flag strings. |
| C3 | The refusal was described for `doctor` and `start`. `--skip-checks` skips the preflight, so a bypass flag would still run. | The loop refuses too, before launching an agent. Also refused: Claude's `--permission-mode bypassPermissions`, which the old guard never named. |
| C4 | The from-actor check (5.4 item 2) breaks two existing fixtures: `tests/fake_agent.py` writes `from_actor: "fake"`. | The check ships in its own task, with a one-line fixture change (`FAKE_ACTOR`, default empty). An empty `from_actor` is not checked. Comparison is case-insensitive. `resume` does not check, because no agent has just run. |
| C5 | Placeholders in the built-in templates break two assertions in `tests/test_prompts.py` that look for the literal `--from codex --to claude`. So "all existing tests pass unchanged" is not achievable for step 1. | Those two assertions change to the placeholder form. A golden test, captured from 0.2.1 before any edit, proves the default roles still render byte-identical prompts. |
| C6 | `preflight.py` walks every configured agent. Defaults always include both `codex` and `claude`, so a Gemini-plus-Claude setup would fail with "codex is not on PATH". | Preflight checks only the agents that fill a role. |
| C7 | Login checks today key on the program name in the command, not the agent name, so a stand-in command is not login-checked. | Keep that: the adapter's login check runs only when the command's program is the adapter's binary. |
| C8 | Two agents in one role pair with the same name (D4) would write the same log file `<task>-<round>-<agent>.log`, so the review overwrites the implementation log. | When implementer and reviewer are the same agent the log name gains `-implementer` or `-reviewer`. Distinct agents keep today's names. |
| C9 | `cli.py` derives the `status` verb from `agent == "codex"` and the dry-run prints `settings.agents["codex"]`. The design missed both. | The verb comes from the marker's `role`, with today's rule as the fallback for old markers. Dry-run uses the configured implementer. |
| C10 | Tests build `config.Config(...)` by hand without `roles`. | New `Config` fields have defaults, and `Config.agents` stays a name-to-command mapping. |
| C11 | 5.5 prints role summary lines always. That changes the output of every default `doctor` and `start`. | Summary rows appear only when roles are not the defaults or a generic agent is in use. `init` without role options writes a `config.toml` byte-identical to 0.2.1, with no `[roles]` block. |
| C12 | 5.2's interface has a `login_check` callable, `quota_markers` and `bypass_flags`. Phase 1 needs none of the last two in the adapters. | Login is data: `binary`, `login_argv`, `login_fix`. `quota_markers` arrives with Gemini. Bypass flags live in `bypass.py` (C2). |
| C13 | "Release coordination" was left open. | Relay 0.2.2. whyline's pin `whyline-relay>=0.2.1,<0.3` already admits it, so no whyline release is needed. |
| C14 | A generic agent's command is run with the prompt appended as its last argument, as for the built-ins. A tool that reads the prompt from stdin or a file cannot be a generic agent. | Stated as a limit in the README; not a defect. |

Scope of the plan: build steps 1 and 3 of section 6 with `codex`, `claude` and `generic`. Step 0
(the Gemini spike) and step 2 (the Gemini adapter) get their own plan once the spike has produced
facts, so the plan contains no guesses about Gemini.
