# Waiting on you: relay and release stops reach Telegram, with buttons

Status: draft for review, 2026-11-14. Builds on the personal assistant (ASST-1..23, done) and release CI recovery (RCR-1..7, done). Runs after `plans/quick-fixes.plan.md`.

## Problem

Whyline stops and waits for the user often, and the user only finds out by looking at the console. Between 2026-11-12 and 2026-11-13:

- v0.3.72's PyPI publish was cancelled because GitHub had no macOS runner. It sat until the user looked.
- v0.3.73 stopped at Check ready because `gh auth status` took longer than 30 seconds.
- A relay waited on a review and on a security Allow.

The Telegram bot already exists, with allowed chats, request cards, taps, confirmation codes and an audit table. It already answers `status`, `ask`, `do` and `stop`. But whyline itself sends only one unprompted message, `Released v<version> of <repo>`, at the end of a successful release (`release/plan.py`, the `after` step). Every stop is silent.

## What the user gets

A **Waiting on you** card in Telegram whenever a relay or release in one of the Inbox repos stops for the user, sent within a minute of the stop. The card names the repo, says what stopped and why, and has buttons. Each button calls the same function as its console button or CLI command, never anything new.

### Cards

1. **Release stopped.** The release state has `failed_id` set or ended `paused`, and nothing is running.
   - Text: `whyline v0.3.73 stopped at Check ready: GitHub didn't answer in time.` When `state.failure` holds a CI cause (RCR-1), its plain-words sentence is used: `GitHub couldn't find a macOS machine for test (macos-latest, 3.13). Your code is fine; rerun it.`
   - Buttons:
     - **Why**: the cause and its log excerpt, as with `whyline release why`.
     - **Rerun**: only for a CI cause, as with `whyline release rerun`. For a tests-failed cause it asks first, with the same question the console asks.
     - **Resume**: for every other cause, as with `whyline release resume`.
     - **Ask agent**: as with `whyline release ask`, read-only.
2. **Release needs a go-ahead.** This only happens for a release resumed from Telegram. When it reaches an irreversible step (push, tag, GitHub release, publish) that ask/step mode would confirm, or the notes approval, it sends:
   - Text: `whyline v0.3.73 is ready to push to origin/main. 4 commits.` For notes: `Release notes for v0.3.73`, followed by the notes as a message (or a file when they're too long for one message).
   - Buttons: **Go on**, which asks `Push v0.3.73 to origin/main? This can't be undone.` with **Yes, push**, and **Stop**.
   - It waits up to 30 minutes. With no answer, the release stops `paused`, exactly as a declined confirm does today, and the card says so.
3. **Relay stopped for you.** The relay in a repo is not live and its state has a `paused_reason`, or it ended with unticked tasks. This covers a pause, the round cap, all agents unavailable, a review that needs a human, and a crash.
   - Text: `agentdock relay paused at RFB-8: <pause line>`, using `whyline_relay.status.pause_line`.
   - Buttons:
     - **Why**: the pause line plus the last 20 log lines.
     - **Resume**: the existing resume path, `whyline.ideas.watch.resume_relay` / `console.recovery`.
     - **Ask**: the read-only relay chat, `whyline.relaychat.ask`. The next free-text message is taken as the question, the same way **Refine** works today.
4. **Relay finished.** All tasks are ticked and nothing is live. `agentdock relay finished release-ci-recovery: 7 tasks.` No buttons. This is information only, and it can be switched off on its own.
5. **Security finding during a release.** Text: rule, file and line, with no value from the file. One line: `Allow or fix it in the console.` No Allow button.

### When the stop clears

When the user acts in the console instead, or the stop clears for any other reason, the open card is edited to `Done in the console ✓` (or `Resumed ✓`) and its buttons are removed. Tapping an old card answers `This card is out of date.`, as today.

### Settings, console first

- **Assistant screen.** A **Waiting on you** section: one checkbox per card kind (all on except **Relay finished**, which is on too), and a list of open cards. The list is the same function the CLI uses.
- **CLI.** `whyline idea waiting` lists open cards. `whyline idea waiting set <kind> on|off` changes a setting through the same save function as the console.
- **Doctor.** `whyline idea doctor` reports whether waiting cards are on and when the last one was sent.

## Goals

- A stop costs the user a glance at the phone, not a walk to the Mac.
- Every button does exactly what the console button does.
- Nothing irreversible happens from the phone without two taps, the second naming what will happen.

## Non-goals

- Starting a new release, or a new relay, from a waiting card. `do <task>` already exists for relays.
- Allowing a security finding from the phone.
- WhatsApp, voice notes, an evening digest, and email reply drafts. Each is a later design.
- Repos outside the Inbox repo list (`whyline.ideas.setup.list_repos`).

## Anti-goals

- A secret, a diff, or a whole log in a Telegram message.
- A typed message acting without a tap. `resume`, typed, is answered with the card, not run.
- Two copies of the same card, or a card that keeps reappearing after it was handled.
- The phone and the console both running the same release or relay.

## How it fits the code today

- **Polling and taps:** `whyline.ideas.worker` runs under launchd. It polls Telegram (`telegram_in.poll_once`) and runs `watch.tick`, which already reads `whyline_relay.state.load(root)` and `whyline_relay.running.live(root)`, but only for relays started from ideas.
  - New: a `waiting.scan(conn, repos, …)` on the same tick, for every Inbox repo. It reads the relay state, relay liveness, the release state (`whyline.release.state.load`) and the release's running pid.
  - It produces `Waiting` items keyed by `(repo, kind, identity)`. The identity is, for example, the release version plus `failed_id` plus `reason`, or the relay task id plus `paused_at`.
- **Cards and taps:** `ideas/bot.py` (outbox, cards, buttons, `CALLBACK_DATA_LIMIT` 64), `ideas/confirm.py` (random, bound, short-lived codes), `ideas/requests.py` (the audit table) and `ideas/actions.py` (the registry and policy).
  - New actions: `release_why`, `release_rerun`, `release_resume`, `release_ask`, `release_go`, `relay_why`, `relay_resume`, `relay_ask`.
  - `*_why` and `*_ask` are read-only (`none`).
  - `*_rerun`, `*_resume` and `release_go` write, so their policy is `tap`. `release_go` for a push or publish needs the second confirm tap.
- **Release:** `release/cli.py` already has `resume`, `why`, `rerun` and `ask`. `engine._drive` calls `confirm(step)` before irreversible steps.
  - A Telegram-started resume runs the release as a detached `whyline release resume` process, like the bot starts relays today.
  - Its `confirm` and `confirm_notes` are a Telegram confirmer. The confirmer sends card 2 and waits on the request row.
  - The confirmer is chosen by a new `--confirm-via telegram` option on `whyline release resume` and `rerun`. It is hidden from help and used only by the worker.
- **Relay:** resume through `watch.resume_relay` / `console.recovery.apply`. Ask through `relaychat.ask.ask(repo, question)`.
- **Redaction:**
  - All card text and excerpts pass through the security scanner (`security.secrets.scan_text`), and every match is replaced with `•••`.
  - Excerpts are capped at 20 lines.
  - The bot token is already redacted by `telegram.redact`.
- **One runner at a time:** before acting, a tap checks `State.running` with a live pid, and `running.live(root)` for relays. When something is already running, it answers `Already running (started in the console).` and does nothing.

## Calls I made (please check)

- **Go-ahead cards only for releases resumed from Telegram.** A release started in the console keeps confirming in the console. Bridging a waiting console dialog to the phone is a later step.
- **Relay finished is on by default.** It is the card you'd most want after a long run. It can be turned off.
- **The confirm wait is 30 minutes,** then the release pauses. The same card's **Resume** starts it again.
- **The worker's tick is the only sender.** The relay and the release don't message Telegram themselves, apart from the existing `Released v…` line. One place decides, so cards are never sent twice.
- **No Allow from the phone.** Allowing a possible secret should happen where the file can be read.
