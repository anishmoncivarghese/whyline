# Workflows: local, resumable automations in the whyline console

Date: 2026-10-29
Source: `docs/brainstorm/i-want-you-do-a-brainstorming-i-was-thinking-of-adding-addit.md` (codex final synthesis, with Claude's and Antigravity's research).
Plans: `plans/workflows-1-engine.plan.md`, `plans/workflows-2-connections.plan.md`, `plans/workflows-3-telegram.plan.md`.

## 1. What this is

Workflows is a fifth console mode beside Chat, Relay, Agents and Assistant. A workflow is a small, saved automation: a trigger, then a chain of steps such as "fetch this", "have Claude summarise it", "if it mentions me, send it to Telegram", "ask me before posting". It runs on this Mac, uses the agent subscriptions the user already has for its Agent steps, and can be run, watched and approved from the console or from Telegram.

It is a trustworthy subset of n8n or Power Automate for one person on one machine, not all of n8n in a terminal.

User decisions (2026-10-29):

- Scope of this spec: the first public release. MCP and the drag-and-drop canvas come in a later spec.
- Workflow files are TOML.
- A write that outside data can influence asks for approval each time, with a per-step "always allow for this version" choice.
- A daily cap on Agent steps exists as a setting, off by default.

## 2. Boundaries

- **Chat**: talk to one agent. **Relay**: the Git delivery pipeline. **Agents**: saved single-purpose read-only jobs. **Assistant**: personal intake over Telegram and email. **Workflows**: multi-step automation.
- Workflows reuse the Agents runner (`whyline.agents.runner.execute_once`), the scheduler heartbeat (`whyline.agents.tick.run_tick`), the time rules (`whyline.agents.schedule`), Telegram and email sending, and the inbox's allowed chats. They do not reuse Relay's runtime.
- Agents and Workflows stay separate screens in this release.

Out of scope for this release, and refused by validation where they could be written: MCP, the visual canvas, loops, parallel branches, sub-workflows, inbound webhooks, OAuth, shell or code steps, relay steps, DELETE requests, remote anything.

## 3. Files and state

| Path | What |
|---|---|
| `~/.whyline/workflows/<name>.toml` | personal workflow (default scope) |
| `<repo>/.whyline/workflows/<name>.toml` | repo workflow; inert until accepted on this machine |
| `~/.whyline/workflows/state.sqlite` | activations, runs, step runs, approvals, dedupe. WAL, mode 0600 |
| `~/.whyline/workflows/runs/<run_id>/` | redacted step outputs, mode 0700 |
| `~/.whyline/workflows/settings.toml` | workflow settings (daily Agent cap, retention) |
| `~/.whyline/credentials.toml` | credential metadata only, mode 0600 (plan 2) |
| Keychain service `whyline-cred`, account = credential name | credential values (plan 2) |

Workflow files never contain secret values or acceptance state. A workflow's id is `personal:<name>` or `repo:<resolved root>:<name>`, as for saved Agents. Names match `^[a-z][a-z0-9-]{0,39}$`.

## 4. Workflow file

```toml
name = "pr-digest"
description = "Weekday PR summary to Telegram"
version = 1

[trigger]
kind = "weekdays"          # manual | daily | weekdays | every | folder | telegram
at = "08:00"               # daily, weekdays
# every_hours = 4          # every
# folder = "~/Inbox/scans" # folder

[[input]]                  # optional typed inputs for manual and Telegram runs
name = "topic"
type = "string"            # string | number | boolean
default = ""

[[step]]
id = "fetch"
type = "http"              # plan 2
method = "GET"
origin = "https://api.github.com"
path = "/search/issues"
query = { q = "is:pr is:open author:@me" }
credential = "github"

[[step]]
id = "summarise"
type = "agent"
runner = "claude"
backup = ["codex"]
instructions = "Summarise these PRs: what needs my action today."
inputs = ["{{ steps.fetch.body }}"]
output = "text"            # text | json

[[step]]
id = "send"
type = "deliver"
to = "telegram"
text = "{{ steps.summarise.output }}"

[layout]                   # positions for a later canvas; never semantic
fetch = [0, 0]
```

### 4.1 Steps and routing

- Steps run in file order. Each step has one outgoing edge per port. The default port is `next`, which goes to the following step.
- A `condition` step has ports `true` and `false`. A `switch` step has one port per case plus `default`. Their targets are step ids in `then`, `else` and `cases.<name>.goto` / `default`. A target must come later in the file, so the graph cannot cycle.
- A step reached by no taken edge is `skipped`. Execution follows exactly one path, so there is no parallelism and no join.
- `stop` ends the run as succeeded.

### 4.2 Step types in this release

| Type | Fields | Writes? | Plan |
|---|---|---|---|
| `set` | `values` (table of name → template) | no | 1 |
| `condition` | `left`, `op` (eq, ne, contains, gt, lt, exists, empty), `right`, `then`, `else` | no | 1 |
| `switch` | `value`, `cases` (table: name → {equals, goto}), `default` | no | 1 |
| `wait` | `minutes` (1..10080) or `until` (HH:MM) | no | 1 |
| `stop` | — | no | 1 |
| `approval` | `message` (template), `expires_hours` (default 24) | no | 1 |
| `agent` | `runner`, `backup`, `model`, `instructions` (literal), `inputs` (templates), `output`, `schema`, `timeout_minutes` (default 15) | no | 1 |
| `deliver` | `to` (telegram, email, file), `chat`, `email`, `subject`, `text` | notify | 1 |
| `http` | `method` (GET, POST, PUT, PATCH), `origin`, `path`, `query`, `headers`, `body`, `credential`, `timeout_seconds` (default 30) | POST/PUT/PATCH | 2 |

**Target fields are never templated.** Validation refuses `{{` in: `runner`, `backup`, `model`, `instructions`, `to`, `chat`, `email`, `origin`, `credential`, `method`, step ids and every routing target. `path` may be templated; `origin` may not, so a template can never change the host.

### 4.3 Templates

`{{ path | filter }}` only. Paths: `trigger.<field>`, `inputs.<name>`, `steps.<id>.<field>`, `run.id`, `run.started`. Filters: `json`, `lower`, `upper`, `trim`, `length`, `first`, `join("sep")`, `default("x")`. No other syntax, no attribute access, no calls, no `eval`. Credentials cannot be referenced. A missing path renders an error naming the path, never an empty string, unless `default` is used.

### 4.4 Hashes and acceptance

- **Semantic hash**: SHA-256 of the canonical JSON of the parsed file without the `layout` table.
- **Layout hash**: the same over `layout` alone.
- Acceptance stores the semantic hash in `state.sqlite`, never in the file, so a Git pull cannot accept itself.
- A changed semantic hash puts the workflow in `needs_review`. New triggers wait. A run already in progress keeps the revision it started with (each run stores its revision and a copy of the parsed definition). Layout changes never affect acceptance.
- Accept shows a **capability summary**: trigger, providers that will see data, recipients, and (plan 2) hosts, credentials, write steps and which writes need approval. A re-accept shows what changed since the accepted revision.

## 5. Engine

- One run at a time per workflow. A trigger that fires while a run is active keeps only the newest queued run (`queue_latest`).
- Before a step runs its row is `running`; its result is written straight after. Run states: `queued`, `running`, `waiting`, `succeeded`, `failed`, `cancelled`, `unknown_outcome`. Step states add `pending` and `skipped`.
- `waiting` carries a reason (`timer`, `approval`, `usage_limit`, `daily_cap`) and a `wake_at`. The tick resumes runs whose `wake_at` has passed, at the waiting step. Earlier steps are not re-run.
- **Crash recovery**: a step found `running` with no live executor is re-run if it does not write; if it writes (`deliver`, a writing `http`), the run becomes `unknown_outcome` and waits for the user to choose Mark done, Mark failed or Retry step.
- Limits: run wall clock 2 hours, 10 Agent steps per run, step output 1 MB (larger output fails the step), 30 steps per workflow.
- Outputs are redacted (credential values used in the run, plus `whyline.ledgerops.redact`) before they are written to disk.
- Runs execute in a detached process, `whyline workflow _execute <run_id>`, started by the tick or by Run now.

## 6. Agent step

- Built as an `AgentDef` named `wf-<workflow>-<step>` and run through `runner.execute_once(..., unattended=True)`, so enabled-provider, unattended-clearance, read-only and backoff rules all apply unchanged.
- `instructions` is trusted literal text. Rendered `inputs` are written as files and passed as event files, which the runner labels untrusted data.
- `output = "json"`: take the first fenced `json` block or the whole answer, parse, check against `schema` (`type`, `required`, `properties` with `type`), and on failure run one repair turn. A second failure fails the step.
- A usage limit puts the run in `waiting(usage_limit)` until the reset time the runner reports.
- **Daily cap**: `daily_agent_cap` in settings, `0` = off (the default). Over the cap, the step waits until local midnight with reason `daily_cap`.

## 7. Deliver step

- `telegram`: `chat` must be one of the inbox's allowed chats. With one allowed chat, it is the default.
- `email`: literal addresses, shown in the capability summary.
- `file`: a Markdown report in `~/.whyline/workflows/reports/<workflow>/`.
- A deliver to the user's own allowed chat, email or report folder is a notification, not a gated write.

## 8. Triggers

- `daily`, `weekdays`, `every`: the same rules as Agents (`schedule.plan_tick`): catch up only the latest missed time, and record the rest as missed.
- `folder`: a new file in a folder under the user's home starts one run with `trigger.files` (paths). The folder is snapshotted on accept so existing files do not fire.
- `manual`: console, CLI or Telegram.
- `telegram` (plan 3): `flow <name> <free text>` starts a run with `trigger.text`.
- Every trigger claims a dedupe key (`workflow + due time`, folder snapshot hash, or Telegram `update_id`). A second claim of the same key starts nothing.

## 9. Credentials and HTTP (plan 2)

- `whyline.credentials`: metadata in `~/.whyline/credentials.toml` (name, kind `bearer` | `header` | `basic` | `query`, `header_name`, `query_param`, `origins`, timestamps). Values in the macOS Keychain, written through `security -i` with the command on stdin, so a value never appears in a process's arguments. On Linux, `secret-tool` with the value on stdin. Without either, credential steps are locked and say why.
- The Telegram bot token is saved the same way, ending today's `-w <token>` argument.
- A step may use a credential only when its `origin` is in that credential's `origins`. Checked when saving and again when running.
- HTTP: HTTPS only. Hosts that resolve to loopback, private, link-local, CGNAT, multicast or cloud metadata addresses are refused, checked after DNS resolution and pinned for the connection. Redirects: same origin, at most 3. Response at most 1 MB. Writing methods send `Idempotency-Key: <run_id>-<step_id>`. A write whose response was not received (timeout, reset) is `unknown_outcome`, never retried automatically.

## 10. Untrusted data and approvals (plan 2)

- Tainted sources: `http` output, `agent` output, `folder` trigger files, Telegram trigger text and Telegram-typed inputs.
- Taint flows through templates, `set`, and into any step whose fields reference a tainted value.
- A writing step needs approval when any of its fields uses a tainted value, or when it is reached through a `condition` or `switch` that reads a tainted value.
- Before a gated write runs, the engine creates an approval bound to run, step, revision and a hash of the exact redacted arguments, with a random single-use nonce and an expiry (default 24 hours). The run waits.
- Choices: **Approve once**, **Always allow this step for this version**, **Deny**. "Always allow" is stored against the semantic hash and is cleared by any semantic edit. An expired approval fails the step.
- Approvals are decided in the console (plan 1 for `approval` steps, plan 2 for gated writes) and in Telegram (plan 3) with bound buttons only; plain text never approves.

## 11. Console and CLI

Console first: everything below is in `whyline console`; the CLI calls the same `whyline.workflows.service` functions.

- **Workflows mode** (`#mode-workflows`), controls: `Library`, `New`, `Runs`, `Connections` (plan 2).
- **Library**: name, scope, status (on, paused, needs review, needs credential, broken), trigger, next and last run. Actions: Run now, Pause/Resume, Review & accept (capability summary and diff), Edit, and the daily Agent cap.
- **Builder** (outline editor, works at 80x24): step list with Add, Move up/down, Delete; trigger and inputs; an inspector form per step type; routing targets chosen from later steps; Validate; Dry run; Save. Save sets `needs_review` when the meaning changed.
- **Dry run**: runs `set`, `condition`, `switch` and templates for real; shows what `agent`, `deliver` and `http` would receive without running them.
- **Runs**: run list per workflow; a run's step timeline with state, provider used, duration and redacted output; Approve/Deny; Cancel; Mark done/Mark failed/Retry step for `unknown_outcome`; Retry run.
- **Connections** (plan 2): add (masked), test, rotate, remove; which workflows use each.
- CLI: `whyline workflow list|show|validate|new|accept|pause|resume|run|runs|run-show|cancel|approve|deny|cap|doctor|export-run`, and `whyline cred add|list|test|rotate|remove` (plan 2).

## 12. Telegram (plan 3)

- `flows` lists accepted workflows and their status.
- `flow <name> [key=value ...]` runs one, with declared inputs only. A `telegram`-trigger workflow takes free text instead.
- `flow runs [name]`, `flow pause <name>`, `flow resume <name>`, `flow cancel <run>`. Pause, resume and cancel need a tap.
- A run started from Telegram reports in one message edited in place: started, each step, waiting for approval, finished or failed.
- Approval cards: the workflow, step, destination and redacted arguments, with Approve once, Always for this version and Deny. Callback data stays under 64 bytes and carries the approval id and nonce. Only allowed chats can decide; a used or expired card replies `This card is out of date.`
- Names are exact. Unknown names and extra arguments are refused, as for `run <agent>`.

## 13. Operations (plan 3)

- `whyline workflow doctor` and the console Check: state file permissions, credential store available, broken definitions, workflows needing review or a credential, stuck or `unknown_outcome` runs, the next run of each.
- Retention: runs older than 30 days, keeping at least the last 20 per workflow, are pruned by the tick. Settable.
- `export-run <id>` writes a redacted Markdown record for support.

## 14. Acceptance criteria for the release

- Create, validate, dry-run, accept, run, pause, inspect, cancel and recover a workflow entirely in the console at 80x24.
- Workflow files and exports never contain secret values or acceptance state.
- Layout edits never change acceptance. Semantic edits stop new triggers until accepted again.
- Outside data cannot choose a host, credential, recipient, provider, path outside the template rules, or routing target.
- Agent steps are read-only, see no credentials, and keep provider failover and backoff.
- A duplicated trigger starts one run. A crash resumes from stored state and never repeats an uncertain write.
- Telegram runs only exact accepted workflows from allowed chats and uses single-use approval cards.
