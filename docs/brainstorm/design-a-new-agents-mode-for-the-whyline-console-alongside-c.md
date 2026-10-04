# Brainstorm: Design a new "Agents" mode for the whyline console, alongside Command, Chat and Relay. An agent is a saved, reusable job: a name, instructions or a prompt, which CLI agent runs it (claude, codex, grok or antigravity, each via its own subscription login and headless mode, never API keys), optional data sources and tools it may use (for example MCP servers, files or folders), and an optional schedule (daily at a time, weekdays, every N hours, or run on demand). In the console the user can create an agent, list agents, see saved and scheduled prompts, run one now, see past runs and their output, pause or delete one. Scheduled runs must happen on macOS even when the console is closed: research how launchd handles jobs missed while the Mac was asleep, whether and how pmset can wake a MacBook (lid closed, on battery) and what one-time admin setup that needs, and what happens when the Mac was off. Cover: the data model and where it lives (per repo vs per user), how each CLI is configured for tools/MCP and what to verify in a spike, unattended safety (permissions, what an agent may change, no pushes, run logs, macOS notifications on success or failure), usage limits and expired logins during unattended runs, how this reuses whyline's existing chat/relay code, the UI flows in the TUI, and a phased plan with the smallest useful first version. Recommend, don't just list options.

## Final Synthesis

*Combines the strongest, now-converged ideas from the Claude, Codex, and
Antigravity sections below into one recommendation. All three independently
arrived at the same core architecture after reading each other's passes;
this section states that consensus plainly so it can be acted on without
reading three full designs.*

**Build Agents as a thin orchestration layer on top of whyline's existing
relay execution machinery — a new, non-conversational, single-shot execution
path, not a new agent runtime and not a direct reuse of `whyline_relay.chat.run_turn()`.**
An agent is a saved definition (what should run), a local activation (whether
and when this Mac runs it), and a sequence of immutable run records (what
actually happened). Ship it read-only and on-demand first; add scheduling
once the audit trail is trustworthy; add writes only after that; treat
scheduling risk and write risk as separate phases because stacking both
makes failures hard to attribute.

**Data model — three tiers, never collapsed into one:**
- `.whyline/agents/<slug>.toml` — git-tracked, shareable agent *definitions*
  (name, instructions, runner, sources, tools, limits). May include an inert
  `[schedule_suggestion]` for team visibility, but a definition alone can
  never cause execution.
- `~/.whyline/agents/state.sqlite3` — machine-local, per-user SQLite holding
  the activation table (schedule actually accepted on *this* Mac, status,
  accepted-definition hash, next-due time) and an `occurrences` table with a
  unique key on `(agent_id, scheduled_for)` for transactional, idempotent
  claiming. Cloning or pulling a repo must never silently activate or widen
  a schedule — any change to a definition's hash flips its activation to
  `review_required` until a human explicitly re-accepts it on that machine.
- `~/.whyline/agents/runs/<run-id>/` — per-user, `0700`/`0600`, holding
  `metadata.json`, `stdout.log`/`stderr.log`, `events.jsonl`, `final.md`, and
  (write-capable runs) `changes.patch`. Kept out of git by default since
  transcripts can contain private source excerpts; a lightweight
  `AgentRunCompleted`-style event is still appended to `.whyline/ledger.jsonl`
  so runs show up in `whyline timeline` for free.

**Scheduling — one ticking LaunchAgent, not one plist per agent.** Install a
single `~/Library/LaunchAgents/com.whyline.agents.scheduler.plist` that fires
`whyline agents tick` every 60–180s with `RunAtLoad`. Launchd is only a
heartbeat; whyline itself computes what's actually due, claims occurrences
transactionally, and coalesces every missed interval since the last
acknowledged run into **at most one** catch-up execution, bounded by a
freshness window (24h for daily/weekly, one interval for every-N-hours) —
anything staler is recorded `missed`, not run. This one design handles sleep,
wake, login, and power-off identically: nothing runs until whyline next ticks
and checks, no special-casing needed. Do not rely on launchd's own
`StartCalendarInterval` coalescing as the source of truth across many agents;
it only guarantees the *plist* fires, not which logical schedules are due.

**`pmset` wake — be honest, don't oversell.** `pmset schedule wake` needs
root, is a single machine-wide resource (not one slot per agent), and Apple
Silicon's PMU/SMC actively prevents full wake on a closed lid running on
battery for thermal/safety reasons. The product promise should be: reliable
when the Mac is awake or in AC-powered clamshell mode; best-effort, narrow,
and optional elsewhere. If offered at all, it's a Phase 5 add-on — a small
root-owned helper installed via one explicit one-time admin authorization,
programming only the single earliest upcoming wake and reprogramming it each
tick, never a blanket passwordless-sudo grant. A fully powered-off Mac runs
nothing until next login (FileVault blocks everything pre-login anyway);
the same catch-up logic then applies.

**CLI spike before writing scheduler code.** Across `claude`, `codex`,
`antigravity`/`agy`, and `grok`, verify per CLI version: true non-interactive
operation with stdin closed; per-run MCP isolation (not silent inheritance of
ambient servers); a headless deny-list mechanism; absolute-path binary
resolution (a LaunchAgent has no interactive-shell `PATH`); clean,
non-hanging failure on expired/missing subscription login; and — critically,
demonstrated concretely by Antigravity's `agy -p --mode accept-edits`
behavior — that a denied tool call can leave the process exiting **0**, so
success must never be inferred from exit code alone; it requires parsing the
structured event stream and reporting `succeeded_with_denials` as a distinct
outcome from `succeeded`. Ship V1 with `claude` + `codex` only, since both
are already proven headless via `whyline_relay`; gate `antigravity`/`grok` on
passing the same conformance suite.

**Unattended safety — defense in depth, not a prompt instruction.** A global
deny-list (`git push`, `git push --force`, `rm -rf`, `git reset --hard`,
`git clean -f`) applies to every scheduled run regardless of what an agent's
own permissions request; an agent's own scope can only narrow this, never
widen it. Writes, when they ship (Phase 3/4), happen in a disposable `git
worktree` at the recorded base commit, never the user's active checkout;
the run produces a `changes.patch` and file manifest for explicit human
review and apply — **no auto-commit, no push, ever, in the first write
release**, enforced in layers (CLI-level deny rules, stripped
`SSH_AUTH_SOCK`/`GIT_TERMINAL_PROMPT`, restricted child-process network
access, and conformance tests that actively try to push). A cap on
files/lines changed aborts and flags anomalously large runs rather than
applying them. Every run emits a structured result, a raw log, and a ledger
event; macOS notifications fire on every completion — failure louder than
success — and a notification-delivery failure must never change the
recorded run status.

**Auth and quota — two different failure classes, handled differently.**
`auth_required` (expired/revoked login) pauses that agent's activation
immediately, notifies once with the exact re-login command, and never
retries blindly since subscription OAuth can't be refreshed headlessly.
`quota_delayed(until)` is transient: record the provider's reset time if
given, otherwise back off for hours, and auto-resume on the next tick with
no human action needed. After a small threshold of consecutive failures of
either kind, auto-pause the activation so it surfaces as one clear
"needs attention" state instead of a growing pile of identical skip
notifications. Never silently fail over to a different CLI — a different
model is a meaningful, explicit, opt-in choice, not an invisible substitution.

**Code reuse — share the low-level machinery, not the conversational layer.**
Reuse relay's process supervision (subprocess groups, timeouts, SIGTERM/SIGKILL
escalation, streamed log capture), `whyline.account` for pre-flight login
checks, `whyline.model` for model selection, and the existing macOS
notification helper, unmodified. Extract a new, shared, provider-neutral
`execute_once(request, policy)` primitive for Chat, Relay, manual Agent runs,
and scheduled Agent runs to call — but do **not** route Agents through
`whyline_relay.chat.run_turn()` or the interactive `whyline run` handoff
directly: the former does conversational prompt expansion and commits
repository changes per turn; the latter hands off to a terminal session
instead of returning captured, structured output. This is the one place
all three passes agree is genuinely new code, even though everything beneath
it is shared.

**UI — a fourth console mode, "Agents," beside Command/Chat/Relay.** List
view: name, runner, schedule/next-due, last-run status (including
"completed with denials"), paused indicator. Creation wizard: name/storage
scope (repo vs. personal) → instructions → runner (annotated with live
login status) → sources/tools, each explicitly scoped → limits → schedule →
a final plain-language review screen (resolved paths, write/network
capability, next occurrence) before first save — an OAuth-consent-screen
pattern, not a confirmation dialog. Detail view: run history with drill-into
log/diff, Run Now, Pause/Resume, Edit, Delete (warns if a schedule is
active). CLI command parity (`whyline agents list/show/run/pause/resume/
accept/history/tick`) so the TUI and CLI share one application service.

**Phased plan — smallest useful version first:**
- **Phase 0:** spike the CLI conformance matrix above; decide in writing
  which CLIs qualify (expect claude + codex).
- **Phase 1 (the shippable first version):** on-demand only, read-only only,
  **no launchd at all.** Definitions, Agents tab (list/create/Run Now/edit/
  delete), run history from new ledger event types, global deny-list already
  enforced even though nothing writes yet. Zero scheduling risk, zero write
  risk — "save a prompt I run often, with the right CLI and files, and see
  what happened last time" is useful on its own.
- **Phase 2:** the SQLite activation/occurrence store, the single ticking
  LaunchAgent, idempotent catch-up, definition-hash `review_required` gate,
  auth/quota state machine, auto-pause, notifications. Still read-only.
- **Phase 3:** scoped MCP grants and promotion of additional CLIs once they
  pass the spike.
- **Phase 4:** reviewed writes — disposable worktrees, patch capture, explicit
  apply/reject, change-size caps. Still no auto-commit or push.
- **Phase 5 (optional):** the narrow, admin-authorized `pmset` wake helper,
  clearly labeled best-effort.

The honest product promise, not an overpromise: *when the Mac is able to run
it, whyline runs at most one eligible occurrence with the permissions you
approved, records exactly what happened, and never silently widens access or
touches a remote system.*

## Claude

# Agents mode for the whyline console — independent brainstorm (claude)

*Revised after reading Codex's and Antigravity's independent passes in this
same document. Where they changed my mind I say so and why; where they
confirmed my original direction I've kept it and tightened the reasoning.*

## Grounding

Before brainstorming I checked what already exists, rather than designing in
a vacuum:

- `whyline console [--ui]` — the TUI that would gain the new tab. Two render
  modes: keyboard-only and a full mouse-enabled screen.
- `whyline run {claude,codex,antigravity,grok} task [--task-id] [--file]
  [--token-budget]` — already invokes one of the four CLIs headlessly, under
  subscription auth, with file context and a token budget. This is most of
  "run an Agent once," but not the unattended path — see below, I changed my
  mind on reusing it directly for scheduled runs.
- `whyline relay ...` — the existing multi-agent (implementer/reviewer)
  pipeline: `init/doctor/roles/plan/plan-format/setup/start/resume/stop/chat/status`.
  Its per-repo state directory is the closest precedent for where Agents data
  should live, and its process-supervision code (timeouts, log capture,
  termination) is the right thing to extract and share rather than
  reimplement.
- `whyline account {status,detect,enable,disable}` and `whyline model
  {set,status}` — already solve "which CLI is logged into which
  subscription tier" and "which model does each agent use," both per-repo
  cached, no API keys.
- `.whyline/` layout observed in this repo: `decisions.md` (0644, git-visible,
  shared project memory) sits next to `ledger.jsonl`, `active-handoff.json`,
  `ownership.json` (0600, local/sensitive) and a `relay/` subdir holding
  `chat-history.jsonl`, `claude-settings.json`, `draft-plan.md`,
  `plan-state.json`, `running.json`, and `logs/<task>-<round>-<agent>-<stage>.log`.
- `relay/claude-settings.json` already encodes the unattended-safety pattern
  worth reusing: an explicit `permissions.allow` list plus a hard
  `permissions.deny` of `Bash(git push:*)` and `Bash(rm -rf:*)`.
- `ledger.jsonl` events are flat JSON-lines with `type` (`SessionStarted`,
  `Instruction`, `FileTouched`, `Note`, `SessionEnded`), `agent`, `session`,
  `ts`, `v`. `whyline timeline` already reads this for project history.

Everything below sits on top of these primitives rather than duplicating
them.

## Recommendation up front

Build Agents mode as **saved, repeatable headless CLI invocations with a
scheduler on top**, not a new execution engine — but *not* a thin wrapper
around the interactive `whyline run`/chat path either. Unattended execution
is a distinct trust boundary from an interactive session (no TTY to fall
back on, no human watching if a model tries something unexpected), so it
deserves its own orchestration path that happens to share the same provider
adapters and process-supervision code as chat/relay. Store the agent
*definition* per repo and git-tracked; store *scheduling activation* and
*run history* per user/per machine and git-ignored. Ship an on-demand,
read-only version first; add scheduling, then writes, as separate phases.

## Data model and storage

```
.whyline/agents/<slug>.yaml          # definition — git-tracked, shareable
.whyline/relay/agents/<slug>/
    runs/<run-id>.json                # structured result per run — gitignored
    runs/<run-id>.log                 # raw transcript — gitignored
~/.whyline/agents/state.sqlite3       # activation + schedule + run index, per user
```

Definition fields: `name`, `instructions` (inline or a path to a prompt
file), `agent` (one of `claude|codex|antigravity|grok`), `sources`
(files/folders, each read-only or read/write, optional), `mcp` (names of
already-configured MCP servers for that CLI, optional), `schedule`
(`on-demand | daily@HH:MM | weekdays@HH:MM | every:Nh`), and a `permissions`
override block that can only *narrow*, never widen, the global unattended
policy (see Safety).

**What I changed here:** I originally put scheduling *registration* in a
per-agent launchd plist and nothing else. Both other passes convinced me
that's the wrong unit — Codex's point that a single per-user LaunchAgent
should periodically tick and let whyline itself compute due work is better
than N per-agent plists: it avoids launchd-side duplication, makes "which
jobs exist and when do they next run" a single query instead of a plist
scan, and most importantly lets whyline enforce idempotency with a real
transaction (claim an occurrence, unique-key on `(agent_id,
scheduled_for)`) instead of trusting launchd's own at-most-once semantics,
which aren't guaranteed under rapid sleep/wake. I'm adopting that: one
`~/Library/LaunchAgents/com.whyline.agents.scheduler.plist` running
`whyline agents tick` every few minutes, backed by a small SQLite state
store (not a bag of per-agent JSON files) so "did this occurrence already
run" is a real constraint, not a convention.

**Why still split per-repo vs per-user:** the definition is exactly the
kind of thing `decisions.md` already proves whyline is comfortable sharing
via git — a teammate should be able to see "we have a scheduled agent that
drafts a daily PR digest" in a PR review. But schedule activation,
credentials, and run logs are machine-local and must never silently turn on
just because someone cloned or pulled the repo — activating a schedule
needs an explicit local step, separate from the definition existing in git.

## CLI configuration per agent, and what the spike must answer

Headless subscription-auth CLIs are not interchangeable under the hood.
Before writing any scheduler code, spend a short spike building a
compatibility matrix across `claude`, `codex`, `antigravity`, `grok` for:

1. Non-interactive single-shot invocation syntax, and whether it can be
   driven with no TTY at all (stdin from `/dev/null`) without hanging or
   falling back to an interactive prompt.
2. How each exposes MCP server configuration, and critically, whether an
   invocation can be scoped to *only* the servers named for that agent or
   whether it inherits every ambient server configured for that CLI. If a
   CLI can't isolate its MCP config per-run, its scheduled MCP support
   isn't ready regardless of what its flags claim.
3. Whether each can be handed a headless tool/permission deny-list — if a
   CLI has no such mechanism, Agents mode must default that CLI to a
   read-only scope rather than trust the model not to run destructive
   commands.
4. Exit-code and output conventions for distinct failure classes: crash,
   usage-limit hit, expired/missing login, and (the one I'd missed
   originally) *denied-but-still-exit-0* — a tool call can be silently
   refused while the CLI still reports success. A scheduled run's status
   can't just be `exit_code == 0`; it needs to parse structured events and
   be willing to report `succeeded_with_denials` as distinct from
   `succeeded`.
5. Whether a working directory and an explicit file/folder allow-list can be
   passed per invocation, and whether the provider binary needs resolving
   to an absolute path — a LaunchAgent doesn't inherit the interactive
   shell's `PATH`.
6. Subscription-login refresh behavior specifically: does an expired session
   fail cleanly, or does it attempt to fall back to an interactive
   browser/TTY prompt that would just hang forever under launchd? That
   failure mode is fatal for a scheduled run and needs to be confirmed, not
   assumed, per CLI.

**Recommendation:** don't block V1 on all four CLIs. `claude` and `codex`
are already proven headless via `whyline run`/`whyline relay`; ship Agents
mode for those two first and gate `antigravity`/`grok` behind the spike's
findings, defaulting unsupported capabilities (MCP, deny-lists, non-zero-exit
denial semantics) to "not offered in the UI" rather than silently ignored.

## macOS scheduling: launchd, sleep/wake, pmset, power-off

This is the part of the request with the most ways to be quietly wrong, so
the design should not trust calendar precision at all — whyline, not
launchd, should own "is this occurrence due."

**Missed-while-asleep jobs:** a per-user `LaunchAgent` only runs while that
user is logged in and not asleep. `StartCalendarInterval` jobs missed during
sleep do run on wake, and multiple missed intervals coalesce into one
firing — but that only tells the scheduler plist *it got invoked*; it says
nothing about which of potentially several logical schedules (across many
agents) are actually due, which is exactly why a single ticking job with its
own due-work computation is more trustworthy than leaning on launchd's
coalescing behavior per agent.

**Design around it, don't fight it:** the single scheduler tick, on every
firing (on time, late on wake, or at next login), computes all occurrences
since the last acknowledged scheduled time per agent, coalesces them into at
most one catch-up run, and only within a freshness window (default 24h for
daily/weekly schedules, one interval for every-N-hours) — stale misses are
recorded as `missed`, not run. A per-agent `run-missed: once|skip` policy
still applies on top (default `skip` for anything that writes, `once` for
read-only/research agents). This also cleanly covers "Mac was off": nothing
runs until next boot/login, at which point the same catch-up check applies,
with no special case needed for off vs. asleep.

**`pmset` wake:** `pmset repeat wake` / `pmset schedule wake` can request a
wake or power-on ahead of a scheduled run, but changing power-management
schedules requires root, and a repeating wake event is a single shared
system resource — it can't hold one slot per agent. I'm scaling back my
original "print the raw `pmset` command for the user to run" idea in favor
of what both other passes landed on independently, which I now think is
right: if wake support ships at all, it should be a narrow, root-owned
helper installed via one explicit one-time authorization, that only ever
programs the *single earliest upcoming* wake across all agents and
re-programs it after every tick — never a blanket passwordless-sudo grant
for the whole binary. Either way, be honest in the UI: wake is workable when
the Mac is on AC power with the lid open, or in Apple's documented
externally-powered clamshell setup; wake on a closed lid running on battery
should be shown as unsupported, not "best effort," since the hardware is
actively working against it. Don't make any of this mandatory for V1 —
without it, a schedule simply runs whenever the Mac is next awake, which is
still useful.

**"Every N hours" has no native launchd primitive** — generate N discrete
`StartCalendarInterval` dictionaries (e.g. every 4 hours → four entries) at
plist-write time rather than inventing a custom interval mechanism.

## Unattended safety

Reuse, don't reinvent, the pattern already sitting in
`relay/claude-settings.json`: a **global deny-list that no agent definition
can override** — `git push`, `git push --force`, `rm -rf`, `git reset
--hard`, `git clean -f` — applied to every scheduled run regardless of what
the agent's own `permissions` block requests. An agent's declared
permissions can only narrow this further, never widen it. For CLIs that
can't enforce a deny-list headlessly, default that CLI to read-only for
scheduled use.

One thing I underweighted originally: a prompt-level deny-list is not a
security boundary by itself, and both other passes make a stronger case
for defense in depth that I'm adopting:

- No scheduled run gets write access to the user's actual working tree.
  Writes happen in a disposable git worktree checked out at the recorded
  base commit; the run produces a patch and an untracked-file manifest for
  the user to review and apply explicitly. The original checkout is never
  touched, so a scheduled agent can never collide with in-progress,
  uncommitted human work.
- No scheduled run commits or pushes, full stop, in the first write-capable
  release — not even locally. Auto-commit is a plausible-sounding
  convenience but it's a second decision (what belongs in history) layered
  on top of a first one (is this change good), and bundling them removes
  the user's chance to say no to either. Commit creation can be a later,
  separately-reviewed capability once the patch-review flow is trusted.
- "No push" enforced in layers, not one: CLI-level deny rules, neutering
  git credential helpers in the child environment (no `SSH_AUTH_SOCK`,
  no interactive `GIT_TERMINAL_PROMPT`), and restricted network access for
  generated child processes beyond the provider's own control channel and
  explicitly granted MCP servers.
- A cap on files-changed / lines-changed per run, with the run aborted and
  flagged rather than applied if a definition's output is anomalously large
  — catches a model going off the rails without a human watching.

Every run produces: a structured result file, a raw log (mirroring the
existing `logs/<task>-<round>-<agent>-<stage>.log` naming), and ledger
events appended the same way existing session events are — this makes
agent history show up in `whyline timeline` for free, with no new reporting
surface to build. I'm widening the event/status vocabulary from my first
pass's four outcomes to cover the cases above honestly: `AgentRunStarted`,
`AgentRunCompleted`, `AgentRunCompletedWithDenials` (the exit-0-but-refused
case), `AgentRunFailed`, `AgentRunSkippedMissedWindow`,
`AgentRunSkippedAuthExpired`, `AgentRunSkippedUsageLimit`,
`AgentRunSkippedOverlap`.

macOS notifications fire on every completion, success or failure, since the
user is by definition probably not watching. Failure notifications should
be the louder of the two; a notification-delivery failure must never change
the recorded run status.

## Usage limits and expired logins

Call the existing `whyline account status` (or a lightweight equivalent)
immediately before an unattended run. If the chosen CLI's login looks
expired or unavailable, skip the run, log `AgentRunSkippedAuthExpired`, and
notify the user that it needs an interactive re-login — subscription OAuth
generally cannot be refreshed headlessly, so retrying automatically would
just fail again noisily. One refinement worth adding: after a small number
of consecutive auth/quota skips for the same agent, auto-pause its
activation (unload the scheduler's claim on it) instead of leaving it to
fail silently on every future tick forever — surface a single clear
"paused, needs attention" state rather than a growing pile of identical
skip notifications.

If a run fails mid-way with a usage-limit signal, classify and log it as
`AgentRunSkippedUsageLimit`, distinct from a crash, and back off for hours
rather than retrying on the next tick. Do not silently fail over to a
different CLI by default — a different model doing the work is a
meaningful change that deserves to be an explicit, logged opt-in
(`fallback: codex` in the definition) rather than an invisible substitution
the user didn't ask for.

## Reusing whyline's existing chat/relay code

- Extract the relay's process-supervision primitives — subprocess groups,
  timeout/termination handling, streamed log capture, macOS notification
  helper — into a shared execution service used by both the interactive
  chat/relay path and the new unattended Agents path, rather than routing
  scheduled runs through the interactive `whyline run` handoff itself.
  That interactive path is designed to hand off to a terminal session; an
  unattended run needs captured structured output and guaranteed cleanup
  instead, which is the one place I'm now treating as new code rather than
  reuse — the pieces underneath it are still fully shared.
- The relay's log-file naming, run bookkeeping shape, and ledger event
  emission are the same shape Agents mode needs for history — conceptually
  an Agent run is a relay task with one role instead of
  implementer/reviewer, so it should share the logging/ledger layer.
- `whyline account` and `whyline model` are reused unmodified for pre-flight
  checks and per-agent model selection — no new auth or model-selection code
  at all.

## Console UI flow (TUI)

New "Agents" tab alongside Command / Chat / Relay, in both the
keyboard-only and `--ui` mouse-enabled renders.

- **List:** name, CLI, schedule (or "on demand"), last-run status glyph,
  paused indicator, next-due time.
- **Create:** name → multiline instructions editor (reuse whatever widget
  Chat already uses) → CLI picker annotated live with `whyline account
  status` (logged in / expired / unavailable) → optional sources (file/
  folder picker, each marked read-only or read/write) → optional MCP
  servers (picked from each CLI's *already configured* servers — Agents
  mode doesn't manage MCP config itself) → schedule picker → a review
  screen that shows the effective permission scope, resolved paths, and
  write/network capability in plain language before the first save, the
  way an OAuth consent screen does.
- **Detail:** run history (timestamp, duration, status including
  "completed with denials," truncated output, drill into full log and any
  captured diff), "Run now," Pause/Resume, Edit, Delete (Delete warns about
  losing the schedule activation first if one exists).
- Pause = unload this agent's claim from the scheduler's activation table,
  keep the definition. Delete = unload + remove activation + remove
  definition file, blocked while a run is in flight.

## Phased plan

**Phase 0 — spike.** Build the four-CLI compatibility matrix above,
including the exit-0-denial check and the auth-refresh-fallback check.
Decide, in writing, which CLIs are "fully supported" for V1. Expect the
answer to be claude + codex only.

**Phase 1 — smallest useful version: on-demand only, read-only, no launchd
at all.** `.whyline/agents/<slug>.yaml` definitions; Agents tab with
list/create/"Run now"/edit/delete; run history sourced from new ledger event
types and per-run logs; the global unattended deny-list enforced even
though nothing is scheduled yet. This alone is shippable and useful — "save
a prompt I run often, with the right CLI and the right files, and see what
happened last time" — and it carries zero launchd/pmset risk and zero
write-safety risk because there's no scheduling and no writes yet.

**Phase 2 — scheduling.** The SQLite activation/occurrence store; the
single ticking `com.whyline.agents.scheduler.plist`; the idempotent
catch-up logic with per-agent run-missed policy; pre-run `whyline account
status` gate, usage-limit classification, and auto-pause after repeated
skips; macOS notifications. Still read-only — scheduling and writes are
separate risks and shouldn't ship in the same phase.

**Phase 3 — reviewed writes.** Disposable worktree isolation, patch
capture, and an explicit user-driven apply/reject flow; the files-changed
cap and abort-on-anomaly check. Still no auto-commit or push.

**Phase 4 — polish.** MCP server picker reading each CLI's real config
instead of a manual list, gated per-CLI on the spike's isolation findings;
explicit opt-in failover chains; richer history filtering reusing `whyline
timeline`-style queries; per-agent default token budgets; optional,
narrowly-scoped `pmset` wake helper for users who want it, installed via a
single one-time authorization, never a blanket sudo grant.

The reason to gate scheduling behind an on-demand phase, and writes behind
a read-only scheduling phase: launchd/pmset behavior can't be fully
verified without a real Mac going through real sleep/wake cycles over days,
and unattended writes are the highest-blast-radius part of the whole
feature — neither belongs on the critical path to the first useful release,
and stacking both risks into one phase makes it harder to tell which one
caused a problem if something goes wrong.

## Codex

# Agents mode for the whyline console — recommended design

*Revised after reading Claude's and Antigravity's full passes. The main
changes are to make local schedule activation an explicit acceptance of a
versioned repo definition, to treat tool denials as first-class outcomes even
when a CLI exits zero, and to separate permanent authentication failures from
temporary quota backoff. I retain the single ticking LaunchAgent and
read-only-first rollout because the other passes strengthen rather than weaken
those recommendations.*

## Recommendation

Build Agents as a thin orchestration layer around whyline's existing relay execution machinery, not as a second agent runtime. An agent is a saved definition plus a local activation and a sequence of immutable run records. The definition says what should run; the activation says whether and when this Mac should run it; the run record proves what actually happened.

The most important design choices are:

1. Keep shareable agent definitions in the repository, but keep schedule activation, credentials, scheduler state, and run logs per user. Cloning a repository must never silently activate a recurring job.
2. Use one per-user launchd agent that periodically invokes `whyline agents tick`. Let whyline calculate due work, missed-run catch-up, locking, and retries. Do not create one launchd plist per saved agent.
3. Ship saved, on-demand, read-only agents first. Add scheduling once the execution and audit path is trustworthy. Add write access and MCP mutation tools only after provider-specific conformance tests.
4. Treat unattended execution as a separate safety class. Scheduled runs get least privilege, no automatic failover, no commits or pushes, bounded runtime and output, and an immutable record of the exact definition and permissions used.
5. Do not promise that `pmset` will make a closed, battery-powered MacBook execute arbitrary jobs on time. Reliable unattended scheduling requires an awake Mac in a logged-in user session; closed-display operation should be supported only in Apple's documented externally powered clamshell configuration. Power wake can be offered later as a best-effort optimization with a narrow, one-time administrator setup.
6. Treat provider capability as evidence, not configuration. If a CLI cannot prove per-run MCP isolation, structured denial reporting, and non-interactive auth failure under a launchd-like environment, disable that capability for scheduled use instead of silently falling back to ambient config or broader permissions.

## Product shape

Add a fourth top-level console mode beside Command, Chat, and Relay: **Agents**. Reuse the existing Textual shell, mode switcher, session/event model, provider selection, relay process supervisor, transcript rendering, and macOS notification helper.

An agent should have these user-visible properties:

- stable ID and editable name;
- instructions, either inline or in a repository-relative prompt file;
- one selected runner: Claude, Codex, Grok, or Antigravity;
- optional model, with the provider default preferred;
- working directory;
- explicitly selected files and folders, each read-only or read/write;
- explicitly selected MCP servers and individual tools;
- limits: timeout, maximum turns where supported, maximum output size, and concurrency policy;
- schedule: on demand, daily at a local time, weekdays at a local time, or every N hours;
- state: active, paused, running, authentication required, quota delayed, or error.

The product should call these jobs “agents” in the UI but avoid implying that they are persistent autonomous processes. Each run is an isolated, bounded CLI invocation. A saved job that retains an open conversational session would be a different feature and should not be smuggled into the first version.

## Storage and data model

Use a hybrid model because definitions have a different ownership and lifecycle from schedules and run history.

### Repository definitions

Store shareable definitions in:

```text
.whyline/agents/<slug>.toml
```

These files may be committed. They contain no tokens, cookies, passwords, environment values, or machine-specific credential paths. A representative shape is:

```toml
schema_version = 1
id = "5e9ea211-..."
name = "Morning regression triage"
runner = "codex"
prompt_file = ".whyline/prompts/regression-triage.md"
working_directory = "."
mode = "read-only"
timeout_seconds = 1200
max_output_bytes = 5000000

[schedule_suggestion]
kind = "weekdays"
time = "09:00"
time_zone = "Asia/Kolkata"
catch_up = "once_if_fresh"

[[sources]]
path = "src"
access = "read"

[[tools]]
server = "github"
names = ["list_issues", "get_issue"]
access = "read"
```

Paths in a repository definition must be relative to the repository root. Resolve and canonicalize them before a run, reject `..` and symlink escapes, and show the resolved paths in the review screen.

A committed definition may include a **schedule suggestion** so teammates can
share intent, but it is inert. The per-user activation is authoritative and is
created only after the user reviews the resolved definition on this Mac. A
changed definition hash must put the activation into `review_required` rather
than silently granting newly added paths, tools, write mode, or a different
schedule. This is the clearest synthesis of repo-shareable jobs and the other
passes' insistence that cloning or pulling must never start background work.

### Personal definitions

Some prompts are private or span repositories. Store those in:

```text
~/.whyline/agents/definitions/<id>.toml
```

The creation flow must ask whether a new agent is **Repository** or **Personal**, explain the sharing consequence, and default to Repository only when the prompt and selected sources remain inside the repository.

### Local activation and run state

Store machine-local state in a SQLite database such as:

```text
~/.whyline/agents/state.sqlite3
```

The activation table should contain the agent ID, definition location, canonical repository path, enabled/paused/review-required state, the locally accepted schedule, IANA time zone, next due instant, last scheduled instant, catch-up policy, last run ID, and the hash of the definition last accepted by the user. Even when the committed definition carries a schedule suggestion, only this locally accepted copy can cause execution: a checkout, branch switch, or `git pull` must not create or materially change an unattended task without confirmation.

Use tables for definitions/indexes, activations, scheduled occurrences, runs, and notification suppression. Claim a due occurrence in a transaction and enforce a unique key on `(agent_id, scheduled_for)`. This makes scheduler ticks idempotent and prevents duplicate runs after a crash or rapid wake events.

Run artifacts belong outside the repository:

```text
~/.whyline/agents/runs/<run-id>/
  metadata.json
  stdout.log
  stderr.log
  events.jsonl
  final.md
  changes.patch
```

Create user state with mode `0700` and files with `0600`. `metadata.json` should record scheduled time, actual start/end, exit classification, runner and CLI version, selected model, definition hash, resolved source/tool grants, working directory, and whether any permission denial occurred. Never record subscription tokens or MCP credentials. Add byte and age retention limits, with explicit “keep” support for important runs.

Keep run artifacts out of the repository by default. Claude's pass places them
under a gitignored repo directory, which is convenient for discovery, but
provider transcripts can contain private source excerpts and tool output. A
user-level store with a repo/agent index gives the TUI the same discoverability
without making sensitive logs easy to add to Git accidentally. An explicit
export action can copy a redacted run bundle into the repo when sharing is
intentional.

## Reuse the existing whyline execution path

Whyline already has most of the hard process-control pieces in relay: subprocess groups, streamed and captured output, per-run logs, timeouts, termination escalation, heartbeat handling, and macOS notifications. Extract provider command construction and provider-result parsing from Chat/Relay into a shared execution service:

```text
console Agents UI
       ↓
agent definition resolver
       ↓
policy compiler (sources, tools, limits)
       ↓
shared provider adapter + relay process supervisor
       ↓
immutable run record + notification
```

Do not call the existing chat turn function unchanged. The current relay chat path is conversation-oriented and can commit repository changes after a turn. Agent runs need their own orchestration path with `commit_policy = none`, no implicit continuation history, and a definition snapshot. The provider adapters and lower-level supervisor should be shared; chat-specific commit and transcript behavior should remain above that boundary.

Also do not route scheduled execution through the current interactive `whyline run` handoff. An unattended run needs captured structured output, timeouts, exit classification, and descendant-process cleanup rather than terminal replacement.

Antigravity's concrete reuse map is useful, with one boundary correction:
reuse `whyline.console.session`/TUI primitives for presentation and
`whyline_relay.running`, notifications, process supervision, and failure
classification for execution, but do not make `whyline_relay.chat.run_turn()`
the Agents API. Extract a provider-neutral `execute_once(request, policy)`
service and have Chat, Relay, manual Agent runs, and scheduled Agent runs adapt
to it. This prevents Chat's commit and conversational-continuation behavior
from leaking into unattended jobs.

## Provider configuration and required spike

The invariant is subscription login through each vendor's CLI. Whyline must never request, store, or synthesize an inference API key. A provider's MCP server may have its own OAuth/token credential, but that credential remains in the provider's credential store and is referenced only by server name.

### Claude

Use `claude -p`, JSON output, `--permission-prompts none`, and a generated per-run settings/MCP configuration. Claude supports allow/deny tool rules, `--mcp-config`, and `--strict-mcp-config`; its subscription login can be checked with `claude auth status`. On macOS, Claude normally keeps credentials in Keychain. The existing relay Claude adapter and generated deny rules are the best starting point, but scheduled mode must confirm that invalid settings fail visibly rather than being silently ignored. [Claude CLI reference](https://code.claude.com/docs/en/cli-usage), [authentication](https://code.claude.com/docs/en/iam), [MCP configuration](https://code.claude.com/docs/en/mcp)

### Codex

Use stable `codex exec` with structured JSON events, `--output-last-message`, and `--sandbox read-only` or `workspace-write` only when that mode is explicitly enabled. Codex supports ChatGPT subscription login, `codex login status`, cached credential refresh, profiles, and per-MCP-server tool allowlists and approval settings. Avoid the dangerous bypass flag entirely. The existing relay Codex adapter already captures a final output file and uses workspace-write, but scheduled read-only mode should be stricter and must generate an isolated config/profile rather than inherit every ambient MCP server. [Codex CLI reference](https://developers.openai.com/codex/cli/reference), [authentication](https://developers.openai.com/codex/auth), [configuration](https://developers.openai.com/codex/config-reference), [MCP](https://developers.openai.com/codex/mcp)

### Grok

Grok supports `grok -p`, JSON/streaming JSON, permission allow/deny rules, sandboxing, headless `dontAsk`, and project/user MCP configuration. Its browser subscription login is stored locally and refreshed, while an expired session can fall back to an interactive prompt—fatal for a scheduled run. Whyline currently treats Grok as a generic command, so it should not be offered for schedules until it has a first-class adapter that proves authentication, permission, MCP isolation, and denial behavior. Never combine “always approve” with unattended execution. [Grok headless mode](https://docs.x.ai/build/cli/headless-scripting), [permissions](https://docs.x.ai/build/features/permissions), [MCP servers](https://docs.x.ai/build/features/mcp-servers), [authentication](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/02-authentication.md)

### Antigravity

Antigravity supports `agy -p`, JSON or streaming JSON, cached browser credentials, sandboxing, fine-grained permissions, and global/workspace MCP configuration. It has a critical unattended semantic: in headless mode a tool that would prompt can be soft-denied while the overall process continues and may exit successfully. Therefore success cannot mean `exit_code == 0`; the adapter must parse structured tool events and classify a run as `success_with_denials` or `permission_denied`. Whyline's existing generic Antigravity handling should be replaced before scheduling it. [Antigravity headless mode](https://antigravity.google/docs/cli/headless/), [permissions](https://antigravity.google/docs/permissions?tab=cli), [MCP](https://antigravity.google/docs/mcp?tab=cli), [login/install](https://antigravity.google/docs/cli/install)

### Spike acceptance matrix

Run the same conformance suite against the exact CLI versions whyline supports, both in an interactive shell and under a minimal launchd environment:

- successful no-op/read-only invocation and final-output extraction;
- missing, expired, and revoked subscription login with no TTY;
- quota/rate-limit response and any machine-readable retry time;
- denied file read, denied file write, denied shell command, and denied `git push`;
- symlink and `..` path escape attempts;
- one permitted and one denied MCP tool, including an OAuth-backed server;
- proof that unselected ambient MCP servers cannot be called;
- timeout and termination of child and grandchild processes;
- output truncation and malformed/partial JSON;
- version upgrade that changes flags or event schemas.

A provider becomes “scheduled-capable” only when all applicable tests pass. The UI may still offer a failed provider for manual runs with a clear warning; it must not quietly weaken policy to make the run work.

Record capabilities per tested CLI version, not merely per provider. The
matrix should distinguish `manual_read`, `scheduled_read`, `scheduled_mcp_read`,
and `reviewed_write`; passing one must not imply the others. A soft-denied tool
call followed by exit code zero is a required fixture for every adapter, not
only Antigravity, because `succeeded_with_denials` is a semantic result rather
than an OS process result.

## Scheduling on macOS

Install one user LaunchAgent at:

```text
~/Library/LaunchAgents/com.whyline.agents.scheduler.plist
```

It should use an absolute whyline executable path, a minimal explicit environment, `RunAtLoad`, and a short `StartInterval` such as 60–300 seconds. Each launch executes `whyline agents tick` and exits. A database lease prevents overlapping ticks. Per-agent locks default to no overlap; if a previous occurrence is still running, mark the next one skipped or coalesced rather than launching a duplicate.

Here `StartInterval` is deliberately only a heartbeat, not the source of
schedule truth. Its firings may be missed during sleep; the next firing after
wake, `RunAtLoad` after login, and an opportunistic tick when the console opens
all execute the same due-work transaction. That makes the design independent
of whether launchd itself coalesces a particular logical agent's calendar
events and avoids one plist per job.

Whyline—not launchd—must own the schedule calculation. `StartInterval` events are missed during sleep, while `StartCalendarInterval` jobs missed during sleep run on wake and multiple missed calendar intervals coalesce into one. Jobs missed while the Mac is powered off do not run merely because launchd exists. Apple's own scheduling guidance documents the wake behavior and the powered-off limitation. [Apple: Scheduling Timed Jobs](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/ScheduledJobs.html)

That leads to a simple, explicit catch-up policy:

- On wake, login, console launch, or scheduler tick, calculate all occurrences after the last acknowledged scheduled time.
- Coalesce them into at most one catch-up run per agent.
- Run that catch-up only inside a configurable freshness window; default to 24 hours for daily/weekday schedules and one interval for every-N-hours schedules.
- If it is stale, record `missed` without running.
- Advance from the intended scheduled instant, not from the late start, so an everyday 09:00 task remains anchored at 09:00.
- Store the IANA time zone and define daylight-saving behavior: one occurrence for an ambiguous repeated time, and run at the first valid local time after a nonexistent spring-forward time.

This same logic handles a powered-off Mac: after the next user login loads the LaunchAgent, whyline either performs one fresh catch-up or records the occurrence missed. A per-user LaunchAgent is available only in that user's login session; it is not a boot daemon.

### `pmset` and wake expectations

`pmset schedule`/`repeat` can request wake or power-on events, and changing power-management schedules requires root privileges. Repeating power events are a shared, limited system resource, so one repeating event per agent is the wrong architecture. [Apple: schedule startup, sleep, restart or shutdown](https://support.apple.com/en-gb/guide/mac-help/-mchl40376151/mac)

If wake support is added later, use a narrow root-owned helper installed by `whyline agents wake setup` after one administrator authorization. The helper should accept only a validated next-wake timestamp, label its event as whyline-owned, inspect existing events before changing anything, and program only the earliest upcoming one-time wake. Do not grant the whole whyline binary passwordless sudo and do not alter unrelated user/system power events. After every scheduler tick, reprogram the next event.

This remains best effort. Apple's documented closed-display mode requires external power together with an external display and input devices; power settings that prevent automatic sleep are also framed around power-adapter operation. From that, the defensible product contract is: lid open and logged in is supported; Apple's externally powered clamshell setup is supportable after testing; lid closed on battery is not guaranteed. [Apple: use a Mac laptop with the display closed](https://support.apple.com/en-ca/117373), [Apple: sleep and wake settings](https://support.apple.com/en-in/guide/mac-help/-mchle41a6ccd/mac)

When the Mac is physically off, there is no general promise of an on-time run. A `wakeorpoweron` request may power on supported hardware, but FileVault requires a user login before user data, Keychain credentials, and a user LaunchAgent are available. Whyline should report this honestly in schedule setup rather than presenting wake as reliability.

## Unattended safety model

Scheduled agents should start with a smaller capability set than manually run agents.

### Defaults and hard invariants

- New agents are on demand and read-only.
- The first scheduled release supports read-only runs only.
- No provider may push, force-push, publish, deploy, send messages, merge, or mutate a remote service unless a later capability explicitly models that action.
- No scheduled run commits. This also prevents the current relay chat behavior from committing unrelated dirty work.
- Shell access is absent by default. If enabled later, permit named read-only commands rather than arbitrary strings.
- Provider-generated processes have network access disabled except for the provider control channel and explicitly granted MCP connectivity. Clear interactive Git and SSH helpers such as `GIT_TERMINAL_PROMPT` and `SSH_AUTH_SOCK` from child environments where possible.
- Saved definitions cannot contain arbitrary provider CLI arguments. The adapter compiles a typed policy to known flags and config.

Network restriction needs an honest implementation gate: clearing credentials
blocks many pushes but is not a network sandbox, and a provider's own process
may spawn tools. Until a provider/OS combination can demonstrate process-level
egress control, describe the guarantee as “remote mutation blocked by layered
credentials, tool policy, and tests,” not “all network disabled.” If that is
insufficient for a selected tool, scheduled use of that tool is unsupported.

“Never push” must be enforced in layers: provider-native deny rules, no Git credential/SSH agent exposure, restricted network for generated commands, and conformance tests that attempt common and obfuscated push paths. A sentence in the prompt is not a security boundary.

### Writes, when they arrive

Do not let an unattended job edit the user's active checkout. Create a disposable Git worktree at the recorded base commit, run with scoped write access there, capture the resulting patch and untracked-file manifest, and leave the original repository untouched. The history screen can offer “Open diff” and an explicit user-driven apply flow. The first write-capable release should still forbid commits; commit creation can be a later, separately reviewed capability.

### Data and tools

Compile selected files/folders and MCP tools into a per-run capability manifest. Exact tool names are preferable to whole-server grants. Start scheduled MCP support with read-only tools. If a provider cannot prevent access to ambient global MCP servers, scheduled MCP is unsupported for that provider until the adapter can isolate its configuration.

Treat prompt text, repository files, tool output, and MCP resources as untrusted input. Do not expose credentials as prompt text or environment variables. Redact known secret patterns from logs, cap output, and record truncation. A run that encountered a denied action should say so even if the provider produced a plausible final answer.

## Authentication, limits, and failures

Every run begins with a cheap provider-specific preflight: binary/version check, subscription-login check, and capability/version check. Claude and Codex expose status commands today; Grok and Antigravity need a verified non-consuming status probe during the spike. Resolve the provider binary to an absolute path at activation time because a LaunchAgent does not inherit the user's interactive shell setup.

Classify results instead of reducing them to success/failure:

- `succeeded`;
- `succeeded_with_denials`;
- `authentication_required`;
- `quota_delayed`;
- `permission_denied`;
- `timed_out`;
- `provider_error`;
- `configuration_error`;
- `missed` or `skipped_overlap`.

On expired or revoked login, do not retry in a loop. Pause that activation immediately, send one notification, and show the exact interactive login command in the console. On quota exhaustion, do not treat a transient limit as permanent authentication failure: record the occurrence as delayed, use a provider-supplied retry/reset time when trustworthy, otherwise back off for hours rather than minutes, and suppress duplicate notifications. Auto-pause quota-limited agents only after a small consecutive-failure threshold or a known long reset window. Default provider concurrency to one because simultaneous jobs amplify subscription throttling.

The state transition should be explicit: `active -> auth_required` on a
definitive login failure; `active -> quota_delayed(until)` on a rate limit;
`quota_delayed -> active` after a successful preflight; and either attention
state requires an affirmative resume if policy or definition access changed.
This keeps Claude's useful circuit-breaker without turning a brief provider
throttle into needless manual repair.

Do not automatically fail over a saved agent to another vendor. Different models, tool semantics, sandboxes, and subscriptions make that a different job. A user may duplicate an agent with another runner or opt into an explicitly defined fallback policy in a later release.

Use the existing macOS notification mechanism for success, failure, authentication, and quota events. Notification failure must never change run status. If `osascript` notifications from a LaunchAgent prove inconsistent, replace them with a small signed notification helper later; this should not block the first version.

## TUI flows

The Agents screen should optimize for answering four questions: what exists, what will run next, what happened last, and what access will it have.

### Main screen

Use a list/detail layout. Each row shows name, runner, state, next run, and last result. The detail panel shows the instruction preview, definition scope and path, working directory, schedule/time zone, data sources, tool grants, and most recent run. Primary actions are:

- New;
- Edit;
- Run now;
- Pause/Resume;
- History;
- Delete/Deactivate.

“Delete” needs precise language. For a repository definition, deleting the definition is a Git-visible file change; deactivating only removes this Mac's schedule. Keep run history by default and offer a separate purge action.

### Creation wizard

Use short steps with a final security review:

1. **Basics** — name, Repository or Personal.
2. **Instructions** — inline prompt or prompt file.
3. **Runner** — provider and optional model, including login/capability status.
4. **Access** — files/folders, read/write mode, MCP servers and exact tools.
5. **Limits** — timeout, output cap, overlap policy.
6. **Schedule** — on demand, daily, weekdays, or every N hours; local time zone and catch-up explanation.
7. **Review** — exact runner, resolved paths, tools, network/write capability, next occurrence, and whether launchd is installed.

“Run now” shows the same compact review and works for a paused scheduled agent without resuming it. History opens a run list, then an output view with status, timestamps, definition hash, CLI version, structured denials, stdout/stderr, and diff. Add command parity such as `whyline agents list`, `show`, `new`, `run`, `pause`, `resume`, `history`, `delete`, `scheduler install`, `scheduler status`, and `tick`; the TUI should call the same application service as the CLI.

Surface `review_required` prominently when a repo definition no longer matches
the locally accepted hash. The review screen should diff capabilities rather
than raw TOML: “adds read access to `reports/`,” “enables MCP tool
`github.create_issue`,” or “changes weekdays 09:00 to every 2 hours.” Resume
must remain disabled until those changes are accepted or the activation is
reverted to its prior snapshot.

## Phased delivery

### Phase 0 — provider and launchd spike

Extract the shared execution interface and run the versioned conformance matrix. Validate minimal LaunchAgent environments, macOS Keychain access, absolute binary discovery, provider event parsing (including exit-zero denials), process-tree termination, capability-specific MCP isolation, and failure behavior with stdin closed. Claude and Codex are the likely first two adapters because whyline already manages them directly, but advancement is test-based rather than assumed.

### Phase 1 — smallest useful version

Ship Agents mode with saved on-demand, read-only jobs; Repository and Personal definitions; inert schedule suggestions; Claude/Codex or any adapters that passed the spike; selected local files/folders; run-now; history/output; timeout; deactivate/delete separation; and immutable local logs. No activated scheduling, MCP, writes, commits, or provider failover.

This version is useful immediately: recurring prompts become named, reviewable tools, and it validates the definition, permission, output, and history model without hiding macOS scheduling risk inside the first release.

### Phase 2 — scheduling

Add the SQLite activation registry, definition-hash acceptance and re-review, one per-user LaunchAgent, daily/weekday/every-N-hours schedules, pause/resume, occurrence deduplication, catch-up, overlap locks, login/quota classification, and success/failure notifications. The setup screen should explicitly state the awake/login requirements and provide scheduler diagnostics.

### Phase 3 — MCP and all providers

Add exact-tool MCP grants and promote Grok and Antigravity only after their adapters pass the same suite. Start with read-only MCP tools. Include an adapter capability table so the UI can disable unsupported combinations rather than relying on warnings.

### Phase 4 — reviewed write workflows

Add disposable worktrees, scoped filesystem writes, patch capture, and explicit user apply/reject. Preserve the invariant that unattended jobs do not commit or push.

### Phase 5 — optional power wake

Only after a hardware/OS test matrix, add the narrow admin-installed `pmset` helper and program the earliest next wake. Label it best effort, detect conflicts, and never claim support for closed-lid battery execution or guaranteed powered-off execution.

## Release gates

Before scheduling is called stable, automate tests for duplicate ticks, crashes between claim and completion, definition changes awaiting re-approval, DST transitions, sleep/wake catch-up, reboot/login catch-up, stale missed runs, overlapping long runs, missing binaries, CLI upgrades, expired logins, quota exhaustion, exit-zero tool denials, notification failure, output truncation, symlink escape, unselected MCP access, prompt-injection attempts to widen permissions, child-process cleanup, and attempted commits/pushes.

The strongest product promise is not “the job always runs at the exact time.” On a laptop, that promise is false. The right promise is: **when the Mac is able to run it, whyline runs at most one eligible occurrence with the permissions you approved, records exactly what happened, and never silently widens access or changes a remote system.**

## Antigravity

# Design & Architecture: "Agents" Mode for the Whyline Console

*Revised after reviewing Claude's and Codex's updated passes. This revision unifies our scheduling around a single ticking LaunchAgent backed by transactional SQLite leasing, replaces in-tree auto-commits with disposable worktree patch reviews, extracts a shared non-conversational execution service rather than reusing Chat's committing runner, introduces local definition-hash acceptance gates, and establishes rigorous capability-based CLI conformance testing.*

---

## 1. Executive Summary & Core Architectural Recommendations

The `whyline` console currently supports three operating modes:
- **Command**: Immediate, synchronous execution of `whyline` CLI commands in the repository.
- **Chat**: Conversational dialogue with a selected CLI agent (`claude`, `codex`, `agy`, or `grok`).
- **Relay**: Structured multi-phase autonomous pipeline (Implementer $\leftrightarrow$ Reviewer loop) executing against a `plan.md`.

**"Agents" Mode** establishes the fourth core pillar: **saved, reusable, scheduled background jobs**. An Agent in this mode is not an open-ended conversational session or a multi-agent relay handoff. It is an immutable, bounded, single-shot headless job specification:
1. A human-readable **name** and stable identifier.
2. A stored **prompt or instruction template** (with dynamic contextual variables).
3. A bound **CLI runner** (`claude`, `codex`, `antigravity`, or `grok`), executed strictly through existing local subscription logins and headless flags (zero API keys).
4. Configured **tools and data sources** (scoped MCP servers, file paths, and repository directories).
5. An execution **trigger**: On-demand (interactive "Run Now") or scheduled (daily at a local time, weekdays, every $N$ hours).

### Summary of Key Architectural Decisions

| Dimension | Recommendation | Why (Rationale) | Rejected Alternatives |
| :--- | :--- | :--- | :--- |
| **Data Model Storage** | **Three-Tier Hybrid (Repo Definition + Local Activation + User Logs)** | Agent definitions belong in `.whyline/agents/<slug>.toml` in git for team collaboration. Local activation and scheduling live in SQLite (`~/.whyline/agents/state.sqlite3`). Sensitive run logs live in user storage (`~/.whyline/agents/runs/`). | **Pure Per-User**: Disconnects jobs from repo git context and commits.<br>**Pure Per-Repo**: Leaks private transcripts into git; cannot discover daemons across repos without filesystem scans. |
| **Schedule Activation Gate** | **Local Definition-Hash Acceptance (`review_required`)** | A git checkout or `git pull` must never silently run background jobs or widen permissions on a machine. Any change to a repo definition flags `review_required` until approved locally. | **Automatic Repo Activation**: Security vulnerability; malicious repo updates could execute arbitrary code or exfiltrate files. |
| **macOS Scheduling** | **Single Ticking User LaunchAgent (`whyline agents tick`)** | One `com.whyline.agents.scheduler.plist` fires every 60–180s. Whyline itself computes due work, enforces transactional SQLite leases, and manages catch-up. | **N Per-Agent Plists**: Stampedes CPU/quotas on wake; no transactional locking; fragile launchctl management.<br>**`cron`**: Deprecated on macOS; skips sleep entirely. |
| **MacBook Sleep / Wake** | **Transactional Catch-up with Freshness Windows (No Forced Battery Wake)** | Apple Silicon PMU hardware physically cancels battery wakeups when the lid is closed to prevent bag fires. Jobs coalesce gracefully upon wake within a bounded freshness window. | **Forced `pmset` on Battery**: Fails silently under Apple SMC safety rules; creates fire/thermal hazard. |
| **Execution Sandbox & Writes** | **Disposable Git Worktree + Patch Review (NO Auto-Commits)** | Unattended runs execute in a temporary worktree (`git worktree add`). The run captures a patch (`changes.patch`) and manifest for explicit human apply/reject. Zero auto-commits. | **Active Working Tree Execution**: Overwrites uncommitted human work.<br>**Unattended Auto-Commit**: Pollutes git history without human review. |
| **Safety & Push Invariant** | **Four-Layer Push Denial & Environment Sanitization** | Hard-block `git push` via CLI deny rules, stripped credentials (`SSH_AUTH_SOCK`, `GIT_TERMINAL_PROMPT=0`), a pre-push hook, and conformance test verification. | **Prompt-Only Invariant**: Easily bypassed by prompt injection or model hallucination. |
| **Rate Limit / Auth Handling** | **Differentiated `auth_required` vs. `quota_delayed(until)`** | Halt execution immediately. On auth failure, pause activation and notify. On 429 quota exhaustion, record delay until provider reset timestamp and back off without human churn. | **Indefinite Retry Loops**: Burns battery, exhausts API quotas, and creates noisy failure alerts.<br>**Silent Model Failover**: Swapping models alters tool comprehension and execution semantics without consent. |
| **Execution Engine Reuse** | **Extract Shared `execute_once()` Execution Service** | Reuse `whyline_relay.agents` (process supervision, timeouts, heartbeats) and `whyline.account` (auth check). Do NOT reuse `whyline_relay.chat.run_turn()`. | **Direct Chat Reuse**: Chat's runner performs conversational prompt expansion, silent model failovers, and `commit_all()` git commits. |
| **Phased Delivery** | **Phase 0 Spike $\rightarrow$ Phase 1 On-Demand Read-Only $\rightarrow$ Phase 2 Scheduling** | Empirical CLI conformance spike must precede scheduling. Smallest useful version (Phase 1) delivers saved on-demand jobs with zero daemon or write risk. | **Monolithic Big Bang**: Debugging launchd, write sandboxing, and provider quirks concurrently causes brittle failures. |

---

## 2. Storage Strategy & Data Model

Definitions, machine activations, and run logs have fundamentally different lifecycles, security boundaries, and ownership semantics. They must not be collapsed into a single directory.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 THREE-TIER STORAGE ARCHITECTURE                        │
├────────────────────────────────┬─────────────────────────────┬────────────────────────┤
│ Layer                          │ Location                    │ Lifecycle & Security   │
├────────────────────────────────┼─────────────────────────────┼────────────────────────┤
│ 1. Repository Definitions      │ <repo>/.whyline/agents/     │ Committed to git.      │
│    (Shareable Intent)          │   └── <slug>.toml           │ Shareable, inert.      │
├────────────────────────────────┼─────────────────────────────┼────────────────────────┤
│ 2. Machine-Local Activation    │ ~/.whyline/agents/          │ Machine-local SQLite.  │
│    (Scheduler Authority)       │   └── state.sqlite3         │ Permissions: 0700/0600.│
├────────────────────────────────┼─────────────────────────────┼────────────────────────┤
│ 3. Run Artifacts & Audit Logs  │ ~/.whyline/agents/runs/     │ Machine-local storage. │
│    (Immutable Execution Trail) │   └── <run_id>/             │ Permissions: 0700/0600.│
└────────────────────────────────┴─────────────────────────────┴────────────────────────┘
```

### 1. Repository Definitions (`<repo>/.whyline/agents/<slug>.toml`)
Definitions represent reusable project templates. They are git-tracked and contain **no credentials, tokens, or absolute machine paths**. All paths are repository-relative.

```toml
# .whyline/agents/daily-audit.toml
schema_version = 1
id = "7f3b8a12-4c2e-4b6a-9f1e-0d8c7a2b3e4f"
name = "Daily Dependency & Security Audit"
slug = "daily-audit"
description = "Audits dependency security, runs linters, and drafts a whyline defect note"
runner = "codex"
model = "o3-mini"                # Optional; defaults to whyline's configured model
prompt_file = ".whyline/prompts/audit.md"  # Relative path or inline prompt
working_directory = "."
mode = "read-only"               # "read-only" | "reviewed-write"
timeout_seconds = 600
max_output_bytes = 2000000

[schedule_suggestion]
kind = "weekdays"                # "on-demand" | "daily" | "weekdays" | "every_n_hours"
time = "09:00"
time_zone = "Asia/Kolkata"
catch_up = "once_if_fresh"       # "once_if_fresh" | "skip"

[[sources]]
path = "src"
access = "read"

[[sources]]
path = "poetry.lock"
access = "read"

[[tools]]
server = "github"
names = ["list_issues", "get_issue"]
access = "read"

[safety]
disallow_git_push = true         # Immutable invariant
max_files_changed = 10           # Enforced in reviewed-write mode
max_diff_lines = 500
```

> [!IMPORTANT]
> **Schedule Suggestions Are Inert**: The `[schedule_suggestion]` block in a committed TOML file is purely advisory. Pulling or cloning a repository **never** activates background execution on this Mac.

### 2. Personal Definitions (`~/.whyline/agents/definitions/<id>.toml`)
For private instructions or cross-repository tasks, definitions can be stored in the user's home directory. The creation wizard explicitly prompts whether a new agent is **Repository** or **Personal**.

### 3. Machine-Local Activation & Scheduling (`~/.whyline/agents/state.sqlite3`)
The SQLite database is the authoritative scheduler state store (`0700` dir, `0600` file). It decouples git operations from local daemon execution and provides atomic, transactional leases:

```sql
CREATE TABLE activations (
    agent_id TEXT PRIMARY KEY,
    definition_path TEXT NOT NULL,
    repo_path TEXT,
    runner TEXT NOT NULL,
    status TEXT NOT NULL,        -- 'active', 'paused', 'review_required', 'auth_required', 'quota_delayed', 'error'
    accepted_definition_sha256 TEXT NOT NULL,
    schedule_kind TEXT NOT NULL, -- 'on-demand', 'daily', 'weekdays', 'every_n_hours'
    schedule_spec TEXT,          -- JSON: {"time": "09:00", "interval_hours": 4}
    time_zone TEXT NOT NULL,     -- IANA timezone string
    next_due_at TIMESTAMP,
    last_scheduled_at TIMESTAMP,
    last_run_id TEXT,
    retry_after TIMESTAMP,
    consecutive_failures INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE occurrences (
    agent_id TEXT NOT NULL,
    scheduled_for TIMESTAMP NOT NULL,
    claimed_at TIMESTAMP,
    run_id TEXT,
    status TEXT NOT NULL,        -- 'pending', 'claimed', 'completed', 'missed', 'skipped_overlap'
    PRIMARY KEY (agent_id, scheduled_for)
);
```

#### The Hash-Gated Activation Rule
Whenever `whyline agents tick` or the console loads an agent, it computes the SHA-256 hash of the definition on disk. If the hash differs from `accepted_definition_sha256`:
1. The agent's status transitions immediately to `review_required`.
2. Scheduled execution is halted.
3. The TUI and CLI display a security diff:
   > *"Agent 'daily-audit' definition modified in git (added source `docs/private/`, changed schedule to `every 1h`). Review and accept changes before execution can resume."*
4. Execution remains blocked until the user explicitly runs `whyline agents accept <slug>` or confirms in the TUI.

### 4. Run Artifacts & Immutable Audit Logs (`~/.whyline/agents/runs/<run_id>/`)
Execution artifacts are stored strictly outside the repository to prevent leaking private source excerpts, prompt texts, or MCP tool responses into git:
```
~/.whyline/agents/runs/run_20261004_090002_a1b2/
├── metadata.json          # Exit status, timing, runner, model, definition SHA, denials
├── stdout.log             # Raw captured runner stdout
├── stderr.log             # Raw captured runner stderr
├── events.jsonl           # Parsed tool calls, permissions, and streaming events
├── final.md               # Final synthesized model response
└── changes.patch          # Generated diff (in reviewed-write mode)
```

### 5. Repository Timeline Integration
To preserve whyline's shared project memory, successful or failed runs append a lightweight audit event to `.whyline/ledger.jsonl`:
```json
{"type": "AgentRunCompleted", "agent": "daily-audit", "runner": "codex", "status": "succeeded_with_denials", "duration_s": 42.1, "run_id": "run_20261004_090002_a1b2", "ts": "2026-10-04T09:00:44Z", "v": 1}
```
This allows `whyline timeline` to display agent runs alongside interactive sessions without creating git merge conflicts.

---

## 3. Autonomous macOS Scheduling: launchd, Sleep/Wake, pmset, and Power-Off

Running jobs on macOS while the console is closed requires navigating launchd mechanics, power states, and hardware constraints.

```
                                    macOS System Clock / Sleep / Wake
                                                   │
                                                   ▼
                               ┌───────────────────────────────────────┐
                               │  ~/Library/LaunchAgents/              │
                               │  com.whyline.agents.scheduler.plist   │
                               │  (Heartbeat Tick: Every 60-180s)      │
                               └───────────────────┬───────────────────┘
                                                   │
                                                   ▼
                               ┌───────────────────────────────────────┐
                               │       whyline agents tick             │
                               │  - Acquires SQLite Lease              │
                               │  - Computes Due Work & Freshness      │
                               │  - Evaluates Definition Hash          │
                               └───────────────────┬───────────────────┘
                                                   │
                         ┌─────────────────────────┴─────────────────────────┐
                         ▼                                                   ▼
               [ Occurrence Due & Fresh ]                           [ Stale / Off-Schedule ]
                         │                                                   │
           ┌─────────────┴─────────────┐                                     ▼
           ▼                           ▼                         Record Occurrence 'missed'
    [ Mac Awake / AC ]        [ Wake from Sleep ]                in SQLite Occurrences Table
           │                           │
           ▼                           ▼
    Execute Job via             Coalesce Missed Occurrences
    execute_once()              into Exactly ONE Run
```

### 1. The Single Ticking LaunchAgent Architecture
Instead of registering fragile, duplicate launchd plists for every agent, whyline installs **one single user LaunchAgent**:
```text
~/Library/LaunchAgents/com.whyline.agents.scheduler.plist
```
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.whyline.agents.scheduler</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/anish/.local/bin/whyline</string>
        <string>agents</string>
        <string>tick</string>
    </array>
    <key>StartInterval</key>
    <integer>120</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/anish/.whyline/agents/scheduler.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/anish/.whyline/agents/scheduler.err</string>
</dict>
</plist>
```

#### Why This Beats N Per-Agent Plists
1. **Sleep Coalescence Without Stampedes**: When a Mac wakes up after 8 hours of sleep, N separate plists using `StartCalendarInterval` would all fire simultaneously, stampeding CPU, memory, and LLM rate limits. A single ticking runner processes due jobs sequentially under strict concurrency limits.
2. **Transactional Deduplication**: SQLite claims due occurrences inside an immediate transaction:
   ```sql
   INSERT INTO occurrences (agent_id, scheduled_for, claimed_at, status)
   VALUES (?, ?, CURRENT_TIMESTAMP, 'claimed');
   ```
   If a crash or race occurs, the unique constraint on `(agent_id, scheduled_for)` prevents duplicate execution.
3. **Dynamic Schedules Without Plist Churn**: Changing an agent from "daily at 09:00" to "every 4 hours" requires only an SQLite update—zero `launchctl bootout` or disk plist rewrites.

### 2. Handling Sleep, Wake, and Missed Intervals
Apple's documented `launchd` behavior indicates:
- `StartInterval`: If the Mac is asleep during the timer interval, the firing is missed entirely due to Darwin kernel `kqueue` timer pauses.
- `StartCalendarInterval`: Fires on wake if missed during sleep, coalescing multiple missed intervals into one firing.

By setting `RunAtLoad = true` and ticking every 120 seconds, whyline guarantees that within 120 seconds of waking from sleep, `whyline agents tick` executes. Whyline—not launchd—calculates what is actually due:

#### The Freshness Window & Catch-up Policy
On every tick (and on wake/login), whyline compares the current time against the agent's scheduled intervals:
1. **Calculate Missed Occurrences**: All intervals between `last_scheduled_at` and `now`.
2. **Coalesce to One Run**: Multiple missed intervals coalesce into at most **one** catch-up execution.
3. **Freshness Window Check**:
   - For daily and weekday schedules, the freshness window is **24 hours**.
   - For every-$N$-hours schedules, the freshness window is **one interval duration** ($N$ hours).
   - If the missed occurrence falls outside the freshness window (e.g. laptop closed for a week), whyline marks the occurrence as `missed` in SQLite, logs a warning, and anchors the next run at the next scheduled calendar slot.
4. **Catch-up Policy**:
   - `catch_up = "once_if_fresh"`: Executes the single coalesced catch-up run (default for read-only agents).
   - `catch_up = "skip"`: Records occurrences as `missed` and waits for the next normal slot (recommended for any write-capable agent).

### 3. MacBook Sleep Realities: Lid Closed, Battery, and `pmset`
A critical architectural question is whether `pmset` can wake a closed-lid MacBook running on battery to execute an agent:

#### The Hardware Reality: Thermal PMU Safety
1. **Lid Closed on Battery**: Apple Silicon MacBooks (M1/M2/M3/M4) and Intel T2 MacBooks contain firmware safeguards in the Power Management Unit (PMU) and SMC. If the lid is closed and the laptop is disconnected from AC power, the hardware **physically suppresses full wakeups**. An RTC timer may trigger a brief 5-second `DarkWake`, but kernel power assertions immediately force the system back to sleep upon verifying `LidClosed && OnBattery`.
   - *Rationale*: Waking an AI agent to execute heavy compiler/LLM processes inside an insulated laptop bag poses severe thermal runaway and fire risks.
2. **Lid Closed on AC Power (Clamshell Mode)**: If connected to AC power and an external display (or headless display dongle), `pmset schedule wake` reliably wakes the machine.
3. **`pmset` Root Requirement**:
   `pmset schedule` and `pmset repeat` **require root (`sudo`)**:
   ```bash
   $ pmset schedule wake "10/05/2026 09:00:00"
   pmset: This operation must be run as root
   ```
   Furthermore, `pmset repeat wake` supports **only one single recurring wake event machine-wide**. Multiple agents cannot register independent wake events.

#### Recommendation on `pmset`:
- **Do not promise battery wake**: The console UI must state clearly:
  > *"Scheduled runs execute when your Mac is awake, or when connected to power in clamshell mode. If your Mac is asleep on battery, jobs coalesce and run immediately when you open your laptop."*
- **Optional Phase 5 Wake Helper**: Provide an optional, narrow root-owned helper (`whyline-wake-helper`) installed via a one-time admin setup (`whyline agents wake setup`). The helper:
  1. Inspects all active agents across repos in SQLite.
  2. Identifies the single earliest upcoming scheduled run.
  3. Invokes `/usr/bin/pmset schedule wake` for that single event.
  4. Reprograms the next wake event on every scheduler tick.
  5. Never grants blanket passwordless sudo to the whyline binary.

### 4. What Happens When the Mac Was Completely Powered Off?
1. **Cold Boot & FileVault**:
   - Modern macOS volumes are FileVault-encrypted.
   - User home directories (`/Users/anish/`) remain fully encrypted and unmounted until the human user enters their login password at the macOS login window.
   - User LaunchAgents (`gui/$UID`) do not exist prior to user authentication.
2. **Post-Boot Catch-up**:
   - Once the user logs in, `launchd` initializes and `RunAtLoad = true` triggers `whyline agents tick` immediately.
   - The scheduler checks missed intervals against the freshness window and either executes one catch-up run or logs stale intervals as `missed`.

---

## 4. CLI Engine Configuration & Conformance Spike

All four engines must execute headlessly **under their existing subscription logins, never API keys**.

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 WHYLINE AGENT RUNNER ADAPTER                                    │
└───────────────────────────────────────────────┬─────────────────────────────────────────────────┘
                                                │
                 ┌──────────────────────────────┼──────────────────────────────┬──────────────────┐
                 ▼                              ▼                              ▼                  ▼
          [ Claude Code ]                [ OpenAI Codex ]             [ Google Antigravity ]   [ xAI Grok ]
         (claude -p ...)               (codex exec ...)                 (agy -p ...)         (grok -p ...)
                 │                              │                              │                  │
   ┌─────────────┴─────────────┐  ┌─────────────┴─────────────┐  ┌─────────────┴─────────────┐    │
   │ --mcp-config <file>       │  │ -c mcp_servers.<name>     │  │ agy mcp add / enable      │    │ Native tools &
   │ --strict-mcp-config       │  │ ~/.codex/config.toml      │  │ ~/.gemini/antigravity-cli/│    │ --allow flags
   │ --settings <json>         │  │ -s workspace-write        │  │ --mode accept-edits       │    │ --output-format json
   │ --permission-mode         │  │ --add-dir <path>          │  │ Parse tool soft-denials   │    └──────────────────
   │   acceptEdits             │  └───────────────────────────┘  └───────────────────────────┘
   └───────────────────────────┘
```

### CLI Engine Headless Configuration Matrix

| CLI Engine | Headless Invocation Pattern | Subscription Auth Storage | Per-Run MCP Scoping | Permission & Tool Control |
| :--- | :--- | :--- | :--- | :--- |
| **`claude`** | `claude -p "<prompt>" --output-format json --permission-prompts none --settings <path>` | Claude Pro/Team OAuth via macOS Keychain / `~/.claude.json` | `--mcp-config <path>` & `--strict-mcp-config` | Deny rules: `Bash(git push:*)`, `Bash(rm -rf:*)` via generated settings JSON. |
| **`codex`** | `codex exec -s read-only --color never -C <cwd> --output-last-message <path>` | ChatGPT Plus/Pro OAuth via `~/.codex/auth.json` | `-c mcp_servers.<name>...` profile overrides | `-s read-only` or `-s workspace-write`; strict path containment. |
| **`antigravity` (`agy`)** | `agy -p "<prompt>" --output-format json --mode accept-edits` | Google Account OAuth in `~/.gemini/antigravity-cli/settings.json` | Workspace settings injection via `trustedWorkspaces` & `mcpServers` | Fine-grained `permissions.allow`; adapter parses event stream for soft denials. |
| **`grok`** | `grok -p "<prompt>" --output-format json --permission-mode acceptEdits` | xAI subscription OAuth in `~/.grok/` | `grok mcp` subcommands & config | Scoped `--allow` rules (e.g. `--allow "Bash(git status)"`); sandboxed execution. |

### The Critical Antigravity Headless Semantic: Exit-Zero Soft Denials
As the Antigravity architecture demonstrates, in headless execution (`agy -p --mode accept-edits`), when a tool call exceeds permitted rules, the engine does **not** necessarily abort with a non-zero exit code. Instead, the runtime records a tool permission refusal, provides the refusal notice to the model, and allows the model to produce a final conversational explanation, exiting with code 0.

Therefore, whyline's execution service **must not rely on `exit_code == 0` as proof of success**. The adapter must parse the structured JSON event stream. If any tool call was refused, the run is classified as `succeeded_with_denials` or `permission_denied`.

### The 10-Point Headless Conformance Spike
Before scheduling any runner, whyline runs an automated conformance test suite against that CLI version in both an interactive terminal and a minimal launchd subprocess environment:

```text
Spike Conformance Suite Matrix
├── 1. Non-Interactive Single-Shot: Send prompt with stdin </dev/null; verify process exits cleanly without hanging.
├── 2. Exit-Zero Tool Denial: Trigger a disallowed tool; verify adapter captures soft denial rather than reporting clean success.
├── 3. MCP Scoping & Isolation: Pass isolated MCP config; verify ambient unconfigured servers are inaccessible.
├── 4. Filesystem Sandboxing: Attempt write to /tmp/escape.txt; verify sandbox blocks path traversal and symlinks.
├── 5. Layered Push Denial: Attempt 'git push'; verify multi-layer defense intercepts command before network transmission.
├── 6. Non-Interactive Auth Failure: Corrupt token; verify CLI exits immediately with identifiable error without hanging on browser OAuth.
├── 7. Quota 429 Handling: Simulate rate-limit; verify adapter parses reset timestamp and classifies as quota_delayed.
├── 8. Minimal Environment / Absolute Paths: Run with sanitized PATH; verify binary and helper resolution succeeds.
├── 9. Process Tree Termination: Trigger timeout; verify SIGTERM/SIGKILL escalation terminates child and grandchild processes.
└── 10. Output Truncation & Framing: Generate 10MB output; verify stream framing and byte-capping survive without memory exhaustion.
```

#### Qualification Recommendation:
- **Phase 1 Launch**: Ship with `claude` and `codex`. Both are already proven in `whyline_relay` headless pipelines.
- **Phase 3 Promotion**: Promote `antigravity` and `grok` once their dedicated adapters pass all 10 conformance tests.

---

## 5. Unattended Safety Architecture

When background jobs execute while the user is away, safety guarantees must be absolute.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        UNATTENDED SAFETY ENVELOPE                      │
├────────────────────────────────────────────────────────────────────────┤
│ 1. Ephemeral Worktree Isolation  -> Never touch uncommitted human work │
│ 2. The Absolute NO COMMIT Rule   -> Produce reviewable patches only    │
│ 3. The Absolute NO PUSH Defense  -> 4-layer defense against remotes    │
│ 4. Change & Diff Caps            -> Bounded modification thresholds    │
│ 5. Isolated User Run Logs        -> Zero credential/transcript leakage │
│ 6. macOS Desktop Alerts          -> Immediate user notification        │
└────────────────────────────────────────────────────────────────────────┘
```

### 1. Ephemeral Worktree Isolation (Human Work Protection)
Unattended agents must **never** run in the user's active working tree:
```bash
# 1. Create temporary worktree from current HEAD at isolated location
git worktree add --detach .whyline/worktrees/<run_id> HEAD

# 2. Execute agent inside .whyline/worktrees/<run_id> with scoped permissions

# 3. Capture git diff and untracked file manifest to ~/.whyline/agents/runs/<run_id>/changes.patch

# 4. Remove worktree container
git worktree remove --force .whyline/worktrees/<run_id>
```
The active working directory is never touched. Uncommitted human edits remain completely safe from corruption or accidental staging.

### 2. The Absolute "NO COMMIT" Invariant in V1
Auto-committing unattended work directly into git history is an anti-pattern. A commit is a permanent project decision.

Instead, write-capable runs produce an **isolated patch bundle**:
- `changes.patch`: Standard unified diff.
- `manifest.json`: List of added, modified, or deleted files.
- The TUI provides an interactive **Diff Review** screen where the human user reviews the diff and explicitly clicks `[Apply Patch]` or `[Discard]`.

### 3. The Four-Layer "NO PUSH" Defense
Whyline guarantees that an unattended agent cannot push code to remote repositories through four redundant defensive layers:

```
┌────────────────────────────────────────────────────────────────────────┐
│ Layer 1: CLI Deny Rules        -> permissions.deny = ["Bash(git push*)"]
├────────────────────────────────────────────────────────────────────────┤
│ Layer 2: Sanitized Environment -> GIT_TERMINAL_PROMPT=0, GIT_ASKPASS=false,
│                                   unset SSH_AUTH_SOCK
├────────────────────────────────────────────────────────────────────────┤
│ Layer 3: Git Pre-Push Hook     -> Blocks push if WHYLINE_AGENT_RUN=1
├────────────────────────────────────────────────────────────────────────┤
│ Layer 4: Conformance Spike     -> Automated tests verify push attempts fail
└────────────────────────────────────────────────────────────────────────┘
```

### 4. Diff Thresholds & Circuit-Breaker Caps
If an agent modifies more than `max_files_changed` (default: 10) or generates more than `max_diff_lines` (default: 500), execution is aborted immediately, the worktree is rolled back, the run is flagged as `aborted_excessive_diff`, and a macOS alert is sent to the user.

### 5. Desktop Notifications
Whyline leverages `whyline_relay.notify.send()`:
- **Success**: Compact banner with duration and modified files summary.
- **Completed with Denials**: Warning banner alerting the user that tools were restricted.
- **Failure / Auth Expired / Quota**: High-priority alert indicating action is required.

---

## 6. Usage Limits, Quota Exhaustion & Expired Logins

During headless execution, cloud providers may reject requests due to rate limits or expired OAuth sessions.

### 1. State Machine Transitions

```
                    ┌─────────────────────────┐
                    │         Active          │
                    └────────────┬────────────┘
                                 │
                 ┌───────────────┼───────────────┐
                 ▼                               ▼
       [ Auth Token Expired ]             [ HTTP 429 Quota ]
                 │                               │
                 ▼                               ▼
    ┌─────────────────────────┐     ┌─────────────────────────┐
    │      auth_required      │     │  quota_delayed(until)   │
    │  - Pauses activation    │     │  - Records reset time   │
    │  - Alerts user once     │     │  - Resumes on next tick │
    │  - Requires human login │     │    after reset time     │
    └─────────────────────────┘     └─────────────────────────┘
```

1. **`auth_required`**: Triggered when a CLI returns token invalidation or OAuth expiration. The activation is paused immediately (`status = 'auth_required'`), a desktop notification is sent with the exact login command (e.g. `codex login`), and no further runs are attempted until the user logs in.
2. **`quota_delayed(until)`**: Triggered when hitting an hourly or weekly rate limit (HTTP 429). Whyline parses the provider's retry timestamp:
   - If a reset timestamp is returned, `retry_after` is set to that instant.
   - If no timestamp is provided, whyline applies exponential backoff (e.g. 2 hours $\rightarrow$ 6 hours).
   - Once the backoff period passes, the scheduler automatically retries on the next tick without requiring manual human resumption.
3. **Consecutive Failure Threshold**: If an agent hits 3 consecutive failures of any kind, its activation automatically pauses to prevent battery and log churn.

### 2. Provider Concurrency Limits
To prevent concurrent background agents from competing for rate limits, whyline enforces a **global concurrency limit of 1 active run per runner** (e.g., at most one `claude` and one `codex` run in flight simultaneously).

### 3. No Silent Runner Failovers
Whyline rejects silent automatic runner failover (e.g. falling back from Codex to Claude when rate-limited). Different models have divergent tool comprehension, prompt obedience, and context windows. Changing runners must be an explicit human configuration choice.

---

## 7. Execution Architecture: Reusing Whyline Foundations

Rather than duplicating process execution or reusing inappropriate conversational layers, Agents mode builds on a clean shared service boundary:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                               WHYLINE CODE REUSE MAP                                   │
├────────────────────────────┬─────────────────────────────┬─────────────────────────────┤
│ Module                     │ Existing Functionality      │ Architectural Action        │
├────────────────────────────┼─────────────────────────────┼─────────────────────────────┤
│ whyline_relay.agents       │ Subprocess supervisor,      │ REUSE DIRECTLY:             │
│                            │ timeouts, SIGTERM/SIGKILL,  │ Primary low-level execution │
│                            │ output teeing, heartbeats   │ engine for all agent runs.  │
├────────────────────────────┼─────────────────────────────┼─────────────────────────────┤
│ whyline.account            │ Subscription OAuth checks,  │ REUSE DIRECTLY:             │
│                            │ JWT decoding, tier status   │ Pre-flight auth verification│
├────────────────────────────┼─────────────────────────────┼─────────────────────────────┤
│ whyline.model              │ Model config & resolution   │ REUSE DIRECTLY              │
├────────────────────────────┼─────────────────────────────┼─────────────────────────────┤
│ whyline_relay.antigravity  │ Workspace trust management  │ REUSE DIRECTLY              │
├────────────────────────────┼─────────────────────────────┼─────────────────────────────┤
│ whyline_relay.notify       │ Native macOS osascript      │ REUSE DIRECTLY              │
├────────────────────────────┼─────────────────────────────┼─────────────────────────────┤
│ whyline.console.tui        │ Textual App, reactive loop, │ REUSE & EXTEND:             │
│                            │ mode switcher, modal dialogs│ Add '#mode-agents' container│
├────────────────────────────┼─────────────────────────────┼─────────────────────────────┤
│ whyline_relay.chat         │ run_turn(), REPL, prompt    │ DO NOT REUSE: Leaks chat    │
│                            │ expansion, backup failover  │ commits & history into runs │
├────────────────────────────┼─────────────────────────────┼─────────────────────────────┤
│ whyline run                │ Interactive terminal run    │ DO NOT REUSE: Designed for  │
│                            │                             │ interactive TTY handoff.    │
└────────────────────────────┴─────────────────────────────┴─────────────────────────────┘
```

### The New Shared Execution Primitive: `whyline.agents.execution.execute_once()`
Extract a provider-neutral single-shot execution service shared across manual runs, scheduled runs, and relay tasks:

```python
# Conceptual signature
def execute_once(
    request: AgentRunRequest,
    policy: SecurityPolicy,
    *,
    log_dir: Path,
    runner_fn = whyline_relay.agents.run,
) -> AgentRunResult:
    """Executes a single headless turn under strict sandbox constraints.
    - Sets up disposable worktree (if reviewed-write mode).
    - Injects scoped MCP configurations and tool allow/deny rules.
    - Sanitizes child environment (blocks git push & credential helpers).
    - Supervises process execution via whyline_relay.agents.run().
    - Parses structured events and tool denials (detects exit-zero refusals).
    - Captures stdout/stderr, events.jsonl, and changes.patch.
    - Returns structured AgentRunResult (never auto-commits).
    """
```

---

## 8. TUI Design & Console User Flows

### 1. Navigation & Header
The console mode bar in `whyline/console/tui.py` expands to four modes:
```
Mode: [ Command ] [ Chat ] [ Relay ] [ Agents (active) ]   runner: codex:o3-mini │ repo: TradingPlatform
```
Keyboard shortcut: `/route agents` or `F4`.

### 2. Agents Mode TUI Split-Pane Layout
The main view features a responsive two-column layout:

```
┌───────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ WHYLINE CONSOLE -- Agents Mode                                                                        │
├───────────────────────────────────────────────────────────────────┬───────────────────────────────────┤
│ SAVED AGENTS                                                      │ AGENT INSPECTOR: daily-audit      │
│                                                                   ├───────────────────────────────────┤
│ ● daily-audit         [codex]   09:00 Mon-Fri     Active          │ Description:                      │
│ ○ weekly-report       [claude]  Sun 18:00         Paused          │ Audits dependencies and linters.  │
│ ⚠ pr-digest           [agy]     Every 4h          Review Required │                                   │
│ ● test-healer         [codex]   On Demand         Ready           │ Runner: codex (o3-mini)           │
│                                                                   │ Schedule: Daily at 09:00 Mon-Fri  │
│                                                                   │ Scope: Read-Only (src/, locks)    │
│                                                                   │ Tools: github (read-only)         │
│                                                                   ├───────────────────────────────────┤
│                                                                   │ RECENT RUNS                       │
│                                                                   │ ───────────────────────────────── │
│                                                                   │ 2026-10-04 09:00  ✓ Success (42s) │
│                                                                   │ 2026-10-03 09:00  ✓ With Denials  │
│                                                                   │ 2026-10-02 09:00  ⚠ Quota Delayed │
├───────────────────────────────────────────────────────────────────┴───────────────────────────────────┤
│ [New Agent]  [Run Now]  [Pause/Resume]  [View Log]  [View Diff]  [Edit]  [Deactivate]  [Delete]       │
└───────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 3. Seven-Step Creation & Edit Wizard (`AgentCreateScreen`)
1. **Basics**: Name, slug, Repository vs. Personal storage.
2. **Instructions**: Inline prompt text or repository prompt file path (`.whyline/prompts/*.md`).
3. **Runner**: Select engine (`claude`, `codex`, `antigravity`, `grok`) annotated with live login/quota status.
4. **Data Sources & Scope**: Multi-select project folders and files; select `read-only` or `reviewed-write`.
5. **Tools & MCP**: Checkbox list of verified MCP servers and exact tool grants (e.g. `github.list_issues`).
6. **Schedule**: Choose On Demand, Daily at time, Weekdays at time, or Every $N$ hours; display local IANA timezone.
7. **Security & Permission Review**: Plain-language OAuth-style consent summary:
   > *"Codex will run read-only on `src/` and `poetry.lock`. Network is restricted to MCP server `github`. Git push is hard-blocked. Next run: Tomorrow at 09:00 IST."*

### 4. Interactive Modals
- **Diff & Patch Viewer (`AgentDiffScreen`)**: Displays syntax-highlighted `changes.patch` with `[Apply to Working Tree]`, `[Apply as Branch]`, and `[Discard]` actions.
- **Log Viewer (`AgentLogScreen`)**: Full-screen scrollable viewer showing raw stdout/stderr, execution metadata, and tool denial events.

### 5. CLI Command Parity
All console actions map 1:1 to CLI commands:
```bash
whyline agents list
whyline agents show <slug>
whyline agents run <slug>
whyline agents pause <slug>
whyline agents resume <slug>
whyline agents accept <slug>      # Accepts updated definition hash
whyline agents history <slug>
whyline agents diff <run-id>
whyline agents apply <run-id>
whyline agents tick               # Invoked by launchd
whyline agents scheduler status
```

---

## 9. Phased Implementation Plan

We recommend delivering Agents mode across five disciplined phases, strictly separating execution verification from scheduling risk, and scheduling risk from write blast-radius.

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    PHASED ROADMAP                                               │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│ PHASE 0: Headless Conformance & Sandboxing Spike                                                │
│          - 10-point test matrix across claude, codex, agy, grok                                 │
│          - Verify exit-zero tool denials, MCP isolation, auth failures, and push blocks         │
│          - Qualify claude + codex for initial release; define remediation path for agy/grok     │
│                                                                                                 │
│ PHASE 1: Smallest Useful First Version (On-Demand, Read-Only Saved Jobs)                        │
│          - TOML data model (.whyline/agents/*.toml) with inert schedule suggestions             │
│          - Console Agents mode TUI (split-pane list/detail, prompt preview, run history)        │
│          - "Run Now" execution via shared execute_once() primitive (read-only)                  │
│          - User run artifacts (~/.whyline/agents/runs/) & timeline ledger events                │
│                                                                                                 │
│ PHASE 2: Autonomous macOS Scheduling (Single LaunchAgent + SQLite)                              │
│          - Install single user LaunchAgent (~/Library/LaunchAgents/com.whyline.agents.scheduler)│
│          - SQLite state engine (~/.whyline/agents/state.sqlite3) with transactional leasing     │
│          - Sleep/wake coalescence, freshness windows, and definition-hash acceptance gates      │
│          - macOS desktop notifications, auth_required auto-pause, and quota_delayed backoff     │
│                                                                                                 │
│ PHASE 3: Scoped MCP & Engine Expansion                                                          │
│          - Exact-tool MCP grants and isolated configuration generation                          │
│          - Promote antigravity and grok adapters after passing spike checklist                  │
│                                                                                                 │
│ PHASE 4: Reviewed Writes via Disposable Worktrees                                               │
│          - Scoped ephemeral worktree execution (git worktree add)                               │
│          - Patch generation (changes.patch) and TUI Diff Review & Apply workflow                │
│          - Enforce change threshold caps (max_files_changed, max_diff_lines)                    │
│                                                                                                 │
│ PHASE 5: Optional Power Wake Helper                                                             │
│          - Narrow root-owned helper for pmset schedule wake on desktop/docked Macs              │
│          - Transparent UI diagnostics distinguishing AC clamshell from unsupported battery wake │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Phase 1: The Smallest Useful First Version (Saved On-Demand Jobs)
- **Why this is the right first milestone**: It delivers immediate, tangible value: developers can save complex prompts bound to specific CLIs and files, run them with one click ("Run Now"), and inspect past outputs. It carries **zero launchd/pmset risk** and **zero write-safety risk** because scheduling is not yet activated and execution is strictly read-only.
- **Deliverables**:
  1. TOML schema for `.whyline/agents/<slug>.toml`.
  2. Console Agents mode TUI with split-pane list/inspector.
  3. `execute_once()` service integrated with `whyline_relay.agents.run`.
  4. Run artifacts stored in `~/.whyline/agents/runs/<run_id>/`.
  5. Timeline integration appending `AgentRunCompleted` to `.whyline/ledger.jsonl`.
- **Exit Criteria**: A developer can open the console, create an agent named `pr-review`, click "Run Now", watch Codex execute read-only in the background, view the formatted output, and see the entry in `whyline timeline`.

---

## 10. Summary of Architectural Decisions (Whyline Record)

In accordance with whyline project guidelines, the core architectural decisions are recorded below:

1. **Adopt Three-Tier Storage (Repo Definitions + Local SQLite + User Run Logs)**
   - *Because*: Definitions are shareable project memory belonging in git; local schedule activation and leasing require ACID guarantees in a machine-local SQLite database; and run logs contain sensitive excerpts that must not leak into git.
   - *Rejected*: Storing run logs in gitignored repo folders (risks accidental git staging and IDE token leaks); Storing definitions exclusively in user home (breaks team sharing and git versioning).
2. **Require Local Hash Acceptance for Repo Definitions (`review_required`)**
   - *Because*: Pulling a git branch must never silently activate background jobs or widen execution permissions on a local machine without human consent.
   - *Rejected*: Automatic activation of repo definitions (creates severe security vulnerability).
3. **Use a Single Ticking LaunchAgent with SQLite Transactional Leasing**
   - *Because*: A single ticking job (`whyline agents tick`) prevents wake stampedes, enforces atomic concurrency limits, and handles dynamic schedules without plist churn.
   - *Rejected*: Individual launchd plists per agent (stampedes CPU/quotas on wake; lacks transactional deduplication; fragile launchctl management).
4. **Reject Forced `pmset` Battery Wake on Closed-Lid Laptops**
   - *Because*: Apple Silicon SMC hardware physically aborts battery wakeups when the lid is closed to prevent bag fires; forcing it is brittle and hazardous.
   - *Rejected*: Mandating sudo `pmset` for routine scheduling (fails silently on battery; violates least-privilege).
5. **Enforce Disposable Worktrees and Patch Reviews (Zero Auto-Commits)**
   - *Because*: Unattended background runs must never alter uncommitted human work, and commit creation is a permanent project choice that requires human review.
   - *Rejected*: Direct working tree execution (destroys dirty human edits); Unattended auto-commits (pollutes git history without human oversight).
6. **Extract Shared `execute_once()` Primitive Instead of Reusing Chat Runner**
   - *Because*: `whyline_relay.chat.run_turn()` performs conversational prompt expansion, silent multi-agent failovers, and auto-commits the repository on every turn.
   - *Rejected*: Direct invocation of `whyline_relay.chat.run_turn()` or interactive `whyline run`.
7. **Differentiate `auth_required` from `quota_delayed(until)`**
   - *Because*: Expired OAuth logins require human intervention and should pause immediately, while 429 quota exhaustion is transient and should back off automatically until the provider reset timestamp.
   - *Rejected*: Indefinite retry loops (wastes battery and quotas); Silent model failovers (alters prompt execution semantics without consent).
