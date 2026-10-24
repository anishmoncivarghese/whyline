# Console provider settings and non-blocking checks

Date: 2026-10-25
Status: agreed in conversation; ready to implement through Relay
Repo: Whyline (`agentdock`)

## Summary

Add a shared **Settings** button to the Whyline console. Its first section,
**AI subscriptions**, lets the user explicitly choose which of Claude, Codex,
Grok, and Antigravity Whyline may use.

That choice is machine-wide and authoritative. Chat, Relay Set up,
brainstorming, planning, backup chains, saved agents, and the idea inbox only
offer enabled providers. A disabled provider is not launched for account or
model discovery.

All provider checks follow one UI contract: the screen opens immediately,
cached information is shown first, and any live work happens in a background
worker with a visible `Checking…` state. Consistency means the same responsive
behaviour and status language for every provider; it does not mean inventing a
slow CLI command where a provider has no reliable one.

This also fixes the measured Relay Set up delay. The current screen calls
`agy models` synchronously from `compose()`. Three real calls took 5.543,
4.035, and 3.835 seconds. Local plan, configuration, and Git reads took only
milliseconds.

## Goals

- Put provider/subscription selection in the console, without requiring a
  terminal command.
- Distinguish what the user has enabled from what is installed and what
  Whyline can verify as ready.
- Never run a provider CLI merely because its binary exists.
- Open Settings, Relay Set up, and every other modal without waiting for an
  external command.
- Make every agent picker use the same enabled-provider source of truth.
- Preserve saved configuration and explain stale references instead of
  silently deleting or rewriting them.
- Keep the existing `whyline account` commands as scriptable counterparts to
  the console screen.

## Non-goals

- Buying, cancelling, or changing a provider subscription.
- Logging into a provider on the user's behalf.
- Claiming that Grok or Antigravity login can be verified when their CLIs do
  not expose a reliable non-interactive status command.
- Maintaining an authoritative online catalogue of every model sold by every
  provider.
- Per-repository provider enablement. The user's subscriptions belong to the
  machine account. Per-repository agent, model, role, and backup choices stay
  as they are.
- Automatically rewriting an existing relay config, saved agent, or inbox
  configuration when a provider is turned off.
- A version bump, release, tag, push, or PyPI publication in this plan.

## Terms

These words must not be collapsed into one boolean:

| Term | Meaning |
| --- | --- |
| Enabled | The user has selected this provider in Settings and permits Whyline to use it. |
| Installed | The provider's CLI executable is on `PATH`. This is a local lookup, not a login or network check. |
| Verified | Whyline has a reliable non-interactive account check and it passed. Claude and Codex can provide this signal. |
| Login unchecked | The CLI is installed, but the provider exposes no reliable non-interactive login check. This is the honest state for Grok and Antigravity. |
| Usable | Enabled and installed, and either verified or explicitly accepted as login-unchecked. This is what operational pickers use. |

The UI may say **AI subscriptions**, because that is the user's decision, but
the code should continue using `agent` or `provider`; it must not assume that
every usable account is billed the same way. Existing API-key status remains
truthfully labelled where detected.

## Decisions

### P1 — Settings is shared across all modes

Add `Settings` to the shared bottom controls, alongside Files, Awake, Help,
and Copy. It is visible in Chat, Relay, and Agents. It opens the same modal
from every mode and does not change the current mode.

### P2 — Enablement is explicit and machine-wide

Each provider record in `~/.whyline/account.json` gains an `enabled` boolean.
The global file is the authority for enablement. A repository's
`.whyline/account.json` may still supply its existing cached/confirmed account
details, but it must never override the global enabled choice.

New helpers make the distinction explicit:

```python
enabled_agents() -> set[str]
available_agents(root) -> set[str]  # compatibility name: enabled and usable
agent_status(root) -> dict[str, dict]
check_provider(agent) -> dict       # pure; never writes account.json
```

Every `agent_status` row includes `enabled`, `installed`, `available`, `label`,
and `hint`. `available` remains the effective operational value so existing
callers can migrate without two competing meanings.

`whyline account enable <agent>` and `disable <agent>` become the CLI
counterparts of the Settings checkboxes. Their user-visible wording changes
from “manually marked available” to “enabled/disabled in Whyline.”

`agent_status` uses the global record for enablement and the latest readiness
result. The old repo confirmation file remains readable for compatibility and
plan/tier context, but it no longer gates whether a provider can be used; a
machine-wide Settings choice must not be undone by a stale repo snapshot.

### P3 — Legacy data migrates without surprising the user

For a provider record without `enabled`, read `enabled` as its existing
`available` value. Do not rewrite the file merely by reading it. The first
Settings Save writes an explicit `enabled` value for all four providers.

An old `manual` record is interpreted the same way: its existing `available`
value becomes its initial enabled choice. A later live check determines
readiness; the user's enabled choice survives that check.

This preserves the set of providers an existing installation currently
offers. A fresh installation with no account file opens Settings once before
an agent-dependent action; the screen may suggest installed providers but
nothing is enabled until the user saves the selection. Cancelling leaves the
file absent and the requested action does not continue.

`ensure_detected()` must therefore stop launching every installed provider on
a fresh machine. With no explicit enabled set it returns without provider
subprocesses; Settings is the onboarding path.

### P4 — Disabled means no provider subprocess

Whyline may use `shutil.which` to label whether a CLI is installed; this is a
local PATH lookup. It must not start `claude`, `codex`, `grok`, or `agy` for a
disabled provider.

Automatic refresh checks enabled providers only:

- Claude: `claude auth status`, in a worker.
- Codex: read and decode its local auth file, in the same worker contract even
  though it is normally fast.
- Grok: PATH-only; label `Installed · login not automatically verified`.
- Antigravity: PATH-only; label `Installed · login not automatically verified`.

The explicit CLI command `whyline account detect` follows the same enabled-only
rule. Settings offers **Check selected**. There is no automatic “check all”
that ignores the user's choices.

`check_provider(agent)` is a pure read/probe operation. It returns a result to
the screen but never writes the global file. The CLI detect command explicitly
persists its results; Settings persists completed results only as part of Save,
which keeps Cancel transactional.

### P5 — Screens paint before checks start

No Textual `compose()`, constructor, event handler, or `on_mount()` path may
wait for a provider subprocess. The sequence is:

1. Push and paint the modal from saved/local data.
2. Show `Checking…` only for enabled providers that need live work.
3. Run checks in Textual thread workers.
4. Return results through `call_from_thread` and update only a still-mounted,
   still-current screen token.
5. If the screen closes, late results may update the cache but must not touch
   disposed widgets.

There is no fixed sleep in production or tests.

### P6 — Model discovery uses the same responsive contract

Claude, Codex, and Grok currently have short built-in model lists. Returning
those is immediate. Antigravity obtains its changing list from `agy models`.
All four go through one model-options interface, but only a provider with a
dynamic catalogue launches an external command.

Relay Set up must not call `model_options_for_agent()` in a way that launches
a subprocess from `compose()`. It renders enabled provider rows immediately:

- a static/cached catalogue renders the dropdown immediately;
- an uncached dynamic catalogue renders the saved/manual value and
  `Checking models…`;
- the worker replaces that row's options when the result arrives;
- failure leaves the saved/manual input usable and shows
  `Could not refresh models; using the saved/default value.`

Successful dynamic results are cached for the console session. Failure and an
empty result are negatively cached for 60 seconds so reopening Set up does not
relaunch a known failing command. After the negative TTL, a later open may
retry. Tests inject the clock and runner; they do not wait 60 seconds.

Disabled providers have no row and therefore no account or model check.

### P7 — One provider policy for every surface

All new choices come from the same account helpers. The required behaviour is:

| Surface | Behaviour |
| --- | --- |
| Chat context bar | Show enabled providers. An enabled but unusable provider may remain visible with `!` and its actionable reason. Disabled providers are absent. |
| Model command/button | List enabled providers only. |
| Brainstorm and Plan brainstorm fields | Render enabled providers only; an enabled but currently unusable provider is disabled with its reason. Final writer and test-planner selects use the same set. |
| Relay Set up roles, release, and backup chain | Offer enabled, usable relay agents only. A saved role that is now disabled is reported as stale and Check cannot pass until the user chooses an enabled provider. |
| Relay preflight and Auto | A configured disabled provider is unavailable and produces an actionable FAIL that points to Settings. |
| New saved agent | Main CLI and backup choices contain enabled providers that satisfy the existing unattended-safety rule. |
| Existing saved agent | List/history remain visible. Edit shows a now-disabled saved runner as a retained, unavailable value so opening and cancelling cannot corrupt it. Run is refused with an instruction to enable the provider or edit the agent. |
| Idea Inbox | New score/brainstorm, assistant, and backup choices contain enabled providers that satisfy the existing unattended-safety rule. Saved disabled names remain visible as blocked configuration until changed. |
| Email/Telegram/background execution | A disabled provider is rejected at execution/preflight time even if stale saved data or an incoming setting names it. UI filtering is not the security boundary. |

Turning a provider off never silently edits a repository config or deletes a
saved agent. Turning it back on makes those saved references eligible again.

### P8 — No-provider state is valid and actionable

Saving with all providers off is allowed. It must not fall back silently to
Claude. Agent-dependent actions show:

`No AI subscriptions are enabled. Open Settings and choose the providers Whyline may use.`

Where practical, the empty screen includes an **Open Settings** button. It
must not start a provider or mutate configuration.

### P9 — Settings Save and Cancel are transactional

The modal initially reads cached status and current enablement. Checkbox
changes are staged. **Save** writes all four `enabled` values in one atomic
replacement of the global account file, preserving unrelated plan/auth fields
and merging the latest completed staged check results. **Cancel** writes
nothing.

After Save, the main console refreshes the agent menu, backup menu, and current
status without restarting. If the saved default agent is disabled, the current
session chooses the first usable enabled provider and reports the change. It
does not rewrite the repository default until the user presses the existing
Save button.

Settings Save is disabled while a write is in progress, but account checks may
continue in the background. A write error stays on the modal and leaves the
old file intact.

## Settings screen

The initial modal is deliberately small:

```text
Settings

AI subscriptions
Choose only the subscriptions Whyline may use.

[x] Claude        Max · Ready
[x] Codex         ChatGPT Plus · Ready
[ ] Grok          Not used by Whyline
[ ] Antigravity   Not used by Whyline

Disabled providers are not checked or shown in agent choices.

[Check selected]  [Save]  [Cancel]
```

At 80x24 the body scrolls while the title, error/status line, and buttons stay
reachable. Provider names and status messages are plain text (`markup=False`)
because CLI errors may contain brackets.

Checking a currently disabled provider changes its staged status to
`Not checked yet`. The screen may start its check after the checkbox event or
when **Check selected** is pressed, but must not save the choice until Save.
Unchecking a provider immediately changes its staged status to
`Not used by Whyline` and prevents any not-yet-started check for it.

## Storage and compatibility

Example global record after Save:

```json
{
  "claude": {
    "enabled": true,
    "available": true,
    "plan": "max",
    "detected_at": "2026-10-25T02:00:00+05:30"
  },
  "codex": {
    "enabled": true,
    "available": true,
    "auth_mode": "chatgpt",
    "plan": "plus",
    "detected_at": "2026-10-25T02:00:00+05:30"
  },
  "grok": {
    "enabled": false,
    "available": true,
    "plan": null
  },
  "antigravity": {
    "enabled": false,
    "available": true,
    "plan": null
  }
}
```

`available` in storage is the last detection result. Effective availability is
never that field alone; it is `enabled and detected-ready`. Disabled records
may retain their last result so re-enabling can show useful cached context
before the fresh check completes.

Readers tolerate missing, malformed, and unknown fields exactly as today.
Writers use a temporary sibling plus `Path.replace()` so interruption cannot
leave half-written JSON. No token or credential is added to either account
file.

## Error handling

- One provider check failing does not stop other checks.
- Timeout or malformed output becomes a one-line provider status with a Retry
  path; it never closes Settings or Set up.
- A Settings write failure leaves the modal open and the old file unchanged.
- A saved default, role, backup, inbox choice, or saved agent naming a disabled
  provider is never silently dropped on read.
- No provider selected is an explicit state, not a reason to re-enable Claude.
- A late worker result is ignored by a newer refresh token.
- Model-list text and provider stderr are untrusted display data and are never
  interpreted as Textual markup.

## Acceptance criteria

1. With Antigravity enabled and a fake `agy models` blocked for five seconds,
   clicking Relay **Set up** displays the modal and `Checking models…` before
   the fake command is released.
2. With Antigravity disabled, opening Settings, Set up, Brainstorm, Plan, New
   Agent, and Inbox never calls `agy`.
3. With Grok disabled, it is absent from every new-choice surface named in P7.
4. An enabled but missing Claude CLI is visible in Settings as `Not installed`
   and is not usable in operational selectors.
5. Grok and Antigravity never claim verified login; their installed state says
   login is not automatically verified.
6. Settings Cancel makes no file change. Save writes all four choices and the
   open console refreshes immediately.
7. A legacy account file with no `enabled` fields initially offers the same
   providers it offered before this change.
8. All providers off produces the P8 message and never silently launches
   Claude.
9. A stale saved relay role or saved agent remains inspectable but cannot run
   until it is changed or re-enabled.
10. A failed/empty Antigravity model query is not repeated during the 60-second
    negative-cache window.
11. Settings and Set up fit at 80x24 and 120x40.
12. `uv run pytest -q` passes with no network, real provider invocation, fixed
    sleep, or real home-directory writes in tests.

## Build boundary

This is a Whyline application change. No whyline-relay package edit is
required: Whyline already owns the console, global account data, and the
wrappers around relay configuration. Relay preflight behaviour is adapted from
Whyline's account status passed into its existing checks.

If implementation discovers that whyline-relay itself independently enumerates
providers in a user-facing path that this console cannot filter, stop that
task and record the exact path; do not silently expand this plan into a second
repository or release.
