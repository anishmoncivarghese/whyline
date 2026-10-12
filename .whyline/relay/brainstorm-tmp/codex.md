# Whyline Remote Watch and Control for Mac and iPhone

## Recommendation

Build this as a **Whyline Control** system with three pieces:

1. a small always-on Whyline daemon on the Mac that observes relay, brainstorm, plan, agent, and terminal sessions;
2. a native SwiftUI companion app for macOS and iPhone showing the same runs, interventions, logs, and controls;
3. an optional, minimal cloud rendezvous service for device pairing, APNs notifications, and encrypted message relay when the devices are not on the same network.

Do not begin with generic Mac screen sharing or unrestricted shell access. The first release should expose structured Whyline actions: answer a question, approve or reject, resume, retry, stop after the current turn, interrupt now, switch to a backup agent, and launch another Whyline job in a new managed session. Add a real PTY terminal later as an elevated capability with stronger confirmation and an obvious audit trail.

This fits the product that already exists. Whyline already writes durable relay state, a live `running.json`, handoffs and questions, detached console logs, checkpoints, and a STOP file. The control system should normalize those into an event stream instead of scraping terminal pixels.

## Product experience

### Mac

The menu-bar app opens to a dashboard:

- **Needs you**: questions, approvals, permission failures, login failures, merge conflicts, dirty-tree blocks, exhausted agents, and timed-out turns.
- **Running**: each relay/brainstorm/plan/agent run with repository, stage, agent/model, elapsed time, last meaningful event, and progress.
- **Paused** and **Completed**: resumable work and recent history.
- **Sessions**: managed terminals, including which session is foregrounded in the Mac app.

A run detail page shows a compact timeline, live log tail, current task/stage, files changed, last handoff, and safe actions. “Open Terminal” reveals the corresponding managed session without changing its process.

### iPhone

The phone opens directly to **Needs you** when attention is required. A notification should say enough to decide whether it is urgent, for example:

> AgentDock · PLAN-4 needs a choice  
> Codex asks which migration strategy to use. Work has been paused for 3 min.

The intervention sheet includes:

- the exact question or blocker;
- recent context and the last relevant log lines, with secrets redacted;
- suggested choices when the agent supplied them;
- a free-text answer field;
- `Send answer & resume`, `Keep paused`, and `Stop`;
- the expected consequence of the selected action.

Running jobs use Live Activities only as a convenience for glanceable status; APNs notifications remain the attention mechanism. iOS suspends background apps and silent background notifications are throttled and not guaranteed, so a permanently connected phone client cannot be the correctness mechanism.

### Multiple terminals

“New session” should initially mean “start a new Whyline-managed job,” not “open an arbitrary shell.” The user chooses repository, mode (chat, brainstorm, plan, relay, or agent), agent/model, and task. The Mac daemon creates an isolated PTY-backed session and returns its output stream. The phone can switch among session tabs without changing which processes run.

Later, add **Advanced Terminal**:

- create a named shell session;
- stream a viewport and scrollback;
- send keystrokes, paste text, resize, interrupt, and detach;
- keep the process alive when the phone disconnects;
- show a persistent “Remote terminal active” indicator on the Mac;
- require recent biometric confirmation for dangerous commands or privilege escalation.

Managed sessions should use a PTY host owned by Whyline. Depending on Terminal.app or AppleScript would be fragile, hard to multiplex, and difficult to audit. Importing existing unmanaged Terminal tabs can be deferred; Whyline can offer “Adopt this directory into a new managed session” instead.

## Architecture

### Mac control daemon

Add a per-user launchd service, `whyline-control`, listening only on a Unix-domain socket by default. It owns:

- run discovery and reconciliation;
- normalized event production;
- command validation and execution;
- PTY session lifecycle;
- encrypted connection to paired devices;
- notification requests;
- audit history.

It watches known repositories and the existing `.whyline` records, but correctness should come from explicit events emitted by Whyline processes. Introduce a tiny local control protocol that every workflow can use:

```text
run.created
run.stage_changed
run.progress
run.log_appended
intervention.requested
intervention.resolved
run.paused
run.resumed
run.completed
run.failed
session.created
session.closed
```

Use a local SQLite database as the read model and outbox. Existing files remain authoritative during migration; the daemon reconciles them on startup. Each event carries `event_id`, `run_id`, repository identity, monotonic sequence, timestamp, kind, redacted payload, and source record version.

### Commands, not remote file mutation

Phone actions become typed command envelopes:

```json
{
  "command_id": "uuid",
  "run_id": "uuid",
  "kind": "answer_and_resume",
  "expected_revision": 18,
  "payload": {"answer": "Use SQLite for v1"},
  "created_at": "...",
  "expires_at": "..."
}
```

The Mac validates the device, signature, capability, run state, revision, and expiry. It then calls Whyline's normal domain operation—the same implementation used by the local UI—rather than editing `state.json`, touching STOP, or writing feedback directly. Commands are idempotent by `command_id`; stale commands return the current state instead of being applied twice.

This requires extracting a small control/service layer from CLI and TUI presentation. CLI, Mac app, and remote commands should all call operations such as `status`, `answer_intervention`, `resume`, `request_stop`, `interrupt`, `retry`, and `start_job`.

### Connectivity

Use two transports behind one protocol:

- **Local-first:** Bonjour discovery plus TLS for Mac and iPhone on the same network.
- **Away from home:** a device-initiated outbound WebSocket from the Mac to a rendezvous service. This works behind NAT without opening an inbound Mac port. The service stores only bounded encrypted envelopes and device presence.

Pair with a QR code displayed by the Mac. The QR contains a one-time pairing nonce and Mac public-key fingerprint. Both devices generate keys locally; after the iPhone confirms the matching code, they exchange signed device certificates. Application payloads are end-to-end encrypted so the rendezvous service cannot read terminal output, answers, or commands.

For a developer preview, Tailscale Serve is a good optional transport because it restricts the local service to the user's tailnet and applies tailnet access controls. Do not use Tailscale Funnel for the default: Funnel is public internet exposure and lacks Serve's identity headers. Tailscale should remain an adapter, not a prerequisite for the consumer product.

### Notifications

The Mac sends a minimal notification request to the cloud service, which sends APNs. Keep sensitive question text out of APNs payloads by default; the notification can say “Whyline needs your input” and the app fetches the encrypted intervention after opening. Allow richer previews as an opt-in.

Notification policy needs deduplication and escalation:

- notify once when an intervention is created;
- update or clear it when resolved elsewhere;
- optionally remind after a user-selected interval;
- never alert for ordinary log lines;
- collapse repeated failures under one run/intervention identifier.

## A first-class intervention model

Today a pause reason is mostly text. Remote control needs a durable structured record:

```text
Intervention
  id, run_id, kind, state, revision
  title, explanation, questions[]
  allowed_actions[]
  context_refs[]
  requested_by, requested_at, deadline
  resolution, resolved_by_device, resolved_at
```

Useful `kind` values are `question`, `approval`, `permission_denied`, `auth_required`, `dirty_worktree`, `conflict`, `agent_unavailable`, `timeout`, and `manual_pause`. An intervention is resolved exactly once. If the local Mac and phone respond simultaneously, optimistic concurrency accepts one and explains the conflict to the other.

Agents should not receive raw remote keystrokes as their answer. Whyline records the human response, actor/device, and timestamp, then builds the same feedback prompt the local workflow would have produced. This preserves checkpoints and gives future readers an auditable decision.

## Security model

Remote terminal control is equivalent to remote code execution under the user's account, so it must be designed as a security boundary.

- Pair devices explicitly; support device naming, revocation, and “revoke all.”
- Store private keys and refresh credentials in Keychain/Secure Enclave where available.
- Require Face ID/Touch ID to reveal sensitive output, answer high-impact approvals, start Advanced Terminal, or elevate a session.
- Give each device capabilities: `observe`, `intervene`, `operate_runs`, and separately `terminal`.
- Bind every command to a run/session and an expected state revision.
- Redact known tokens and secret patterns before data leaves the Mac; default log retention and remote scrollback should be bounded.
- Never transmit environment variables wholesale. Terminal creation starts from a controlled environment and working directory.
- Reject remote commands when the repository path is outside approved roots.
- Audit pairing, commands, responses, terminal creation, privilege changes, and device revocation in an append-only local log.
- Provide an immediate Mac kill switch that disables remote commands and closes network sessions without killing local work.
- Do not expose arbitrary file browsing in v1; only artifacts explicitly associated with a run.

Structured operations should be allowed while the phone is locked only through carefully scoped notification actions, if at all. Free-text answers and terminal input should require opening the authenticated app.

## Reliability and state rules

- The Mac is authoritative for execution state. The phone is a replicated view and command issuer.
- Work continues if the cloud service or phone is offline unless it has reached an intervention.
- Commands queue briefly when the Mac is offline, display “Pending,” expire safely, and can be cancelled before delivery.
- Every stream reconnect sends the last acknowledged sequence; gaps are filled from SQLite.
- PTY sessions persist independently of the network connection and have bounded, disk-backed scrollback.
- After daemon restart, reconcile live PIDs, `running.json`, checkpoint files, handoffs, logs, and STOP state before accepting commands.
- A run has one control lease for mutating operations, preserving the relay's existing single-run-per-repository invariant. Separate sessions may work in different repositories/worktrees; two mutating sessions in one worktree should be blocked.
- “Interrupt now” and “stop after turn” remain distinct everywhere in the UI.

## Delivery plan

### Phase 0 — Instrument and model

- Inventory every current pause and question path across relay, brainstorm, planner, auto mode, and scheduled agents.
- Define `Run`, `Event`, `Intervention`, `Command`, and `Session` schemas with versioning.
- Extract presentation-independent local operations from CLI/TUI code.
- Emit structured events alongside current files and prove startup reconciliation.
- Add redaction tests and a threat model before networking.

Exit criterion: a local diagnostic client can list every run and correctly answer or resume every supported intervention without scraping screen text.

### Phase 1 — Mac status companion

- Ship the launchd daemon and menu-bar SwiftUI app.
- Show running/paused/completed jobs, progress, last event, log tail, and interventions.
- Support local answer/resume/stop/interrupt/retry and deep-link to the console.

Exit criterion: the Mac app can replace the current need to find the original terminal for all structured Whyline controls.

### Phase 2 — Paired iPhone on local network

- Add QR pairing, device keys, Bonjour discovery, TLS, event sync, and capability management.
- Implement Needs You, run details, log tail, answer/resume/stop/retry, and device revocation.
- Test reconnects, duplicate commands, stale state, simultaneous Mac/phone actions, and daemon restarts.

Exit criterion: the phone controls a Mac on the same network without any cloud account and without exposing a listening service beyond paired devices.

### Phase 3 — Anywhere access and APNs

- Add the outbound Mac connection, encrypted relay, presence, encrypted command queue, and APNs.
- Add notification preferences, deduplication, expiry, offline indicators, and delivery receipts.
- Run an external security review and abuse testing before enabling remote mutation by default.

Exit criterion: a user away from the Mac receives an intervention, answers it, sees the relay resume, and can revoke the phone from the Mac.

### Phase 4 — Managed jobs and terminal tabs

- Create new Whyline jobs remotely using typed launch forms.
- Add PTY-backed session tabs, persistent scrollback, resize, interrupt, detach, and session switching.
- Gate Advanced Terminal behind a separate permission and biometric confirmation.
- Consider read-only artifact previews and approved uploads only after terminal security is stable.

Exit criterion: the user can start and switch among multiple safe managed sessions from iPhone, and an explicitly enabled terminal session survives disconnection without losing output or accepting duplicate input.

## Scope to defer

- controlling arbitrary pre-existing Terminal/iTerm tabs;
- full Mac desktop remote control;
- multi-user team collaboration and shared approvals;
- editing arbitrary repository files on iPhone;
- cloud execution of agents;
- exposing a public unauthenticated HTTP endpoint;
- making the cloud copy authoritative;
- Windows and Android clients until the protocol and intervention UX are proven.

## Success measures

- median time from intervention creation to phone notification;
- percentage of interventions resolved without returning to the Mac;
- false or duplicate notification rate;
- command success, expiry, and conflict rates;
- reconnect and state-reconciliation correctness;
- number of runs stranded because the UI lacked an actionable structured intervention;
- zero commands accepted from revoked devices, zero secrets observed in APNs payloads, and zero cross-repository command application in security tests.

The most valuable first milestone is not “a terminal on the phone.” It is “Whyline tells me exactly why work stopped and lets me safely resolve it from anywhere.” Once that control contract is reliable and auditable, multiple remotely operated terminal sessions become a contained extension instead of the foundation of the system.
