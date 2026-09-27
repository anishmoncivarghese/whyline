# Account Capability Gating Design

**Status:** Approved by user, 2026-09-27. Queued to implement after the
backup-chain plan ships and piece A (relay's create-a-plan via brainstorming)
is done.

## Goal

Every place either package asks "which agent/model?" -- whyline's own
`whyline model` wizard, whyline-relay's chat setup wizard, its relay
role-selection wizard, and brainstorm's model-selection menu -- should only
ever offer agents the user actually has working access to, detected once and
re-checkable anytime, instead of unconditionally listing all four
(codex/claude/antigravity/grok) and letting an unavailable one fail later.

## Motivation

Prompted by a real, live confusion: running `whyline model`'s wizard, which
asks "Model for codex (blank to keep default):" for every one of the four
agents regardless of whether they're installed or subscribed, the user typed
"Grok" as an answer -- reading the prompt as "which agent should this role
use" rather than "which sub-model string within this specific CLI." Nothing
validates that string (a deliberate earlier decision, M4 in
`docs/superpowers/specs/2026-09-27-whyline-menu-relay-setup-design.md`), so
it was silently accepted and both codex's and claude's invocations broke.
Hiding agents the user doesn't have removes the whole category of "which of
these four do I even have" confusion this wizard invites today.

## Non-goals

- **Validating model *string* values** (e.g. rejecting "Grok" as a codex
  model name outright). M4 already deliberately chose not to do this, and
  nothing here revisits that decision -- this spec is about which *agents*
  are offered, not which model strings within a chosen agent are valid.
- **A real invocation test during detection.** Confirmed by the user:
  "on PATH" is enough for Antigravity/Grok, which have no reliable
  non-interactive login check today (preflight.py already documents this).
- **Changing whyline-relay's existing per-repo config-availability check**
  (`chat.resolve_command`, brainstorm's B6 `check_availability`). That
  answers a different question ("is this agent configured in *this repo's*
  config.toml") from the one this spec answers ("does the user have this
  agent at all, machine-wide") -- both checks stay, layered.
- **A shared Python dependency between whyline and whyline-relay.** They
  stay fully independent packages; whyline-relay reads whyline's account
  data as plain JSON, never imports whyline's code.

## Decisions

- **AC1 -- `account.py`'s per-agent record gains `available` and an optional
  manual override.** Each of the four agents' record becomes `{"plan":
  str | None, "available": bool, "reason": str | None, "manual": bool}`.
  `available` is computed by detection (a real plan detected, or PATH-found
  for Antigravity/Grok) unless `manual` is `True`, in which case the user's
  own explicit choice always wins -- covering both "hide this even though
  it's installed" (a false positive) and "trust this even though detection
  couldn't confirm it" (a false negative).
- **AC2 -- Detection extends to Antigravity and Grok.** `detect()` gains
  `detect_antigravity()`/`detect_grok()`, both PATH-only (`shutil.which`),
  returning `{"plan": None, "available": <bool>, "reason": None}` --
  never a login check, per the user's explicit choice. Every existing
  per-agent try/except-and-continue guarantee in `detect()` (one agent's
  detection failure never blocks another's) extends unchanged to these two.
- **AC3 -- Detection runs automatically the first time anything needs it,
  anywhere, not just from one hardcoded entry point.** Any command that
  calls `available_agents()` -- the bare `whyline` entry point (the
  Chat-or-Relay menu), `whyline model`, or anything added later -- checks
  `account.load_global() is None` first; if so, it runs the same detection
  `whyline account detect` already performs, prints a short one-line-per-
  agent summary, saves it globally, then continues. This is a check inside
  `available_agents()` itself (or immediately before every one of its
  callers -- decided at plan time by whichever reads more naturally), not a
  one-off hook bolted onto the entry menu alone: a user who runs `whyline
  model` directly, without ever running bare `whyline` first, still gets
  detection triggered automatically. It happens once, machine-wide -- every
  later invocation, anywhere, skips straight past it since global account
  data now exists. Explicit user choice: "both first ever run and I can
  call it anytime."
- **AC4 -- `whyline account status`, `enable`, `disable` are the callable-
  anytime surface.** `status` prints every agent's current availability,
  plan (if known), and whether it's manually overridden -- a read-only view,
  distinct from `detect` (which re-runs detection) or the existing bare
  `whyline account` (which does the repo-confirmation flow). `enable
  <agent>`/`disable <agent>` set `manual=True` with the given value,
  persisting across future `detect` runs until explicitly changed again.
  This is the "add or remove models" surface the user asked for.
- **AC5 -- `account.available_agents(root) -> set[str]`** is the one new
  helper every filtering call site uses, instead of each one hardcoding
  `("codex", "claude", "antigravity", "grok")` or re-deriving availability
  itself. It layers exactly like today's existing `load_repo`/`load_global`
  fallback: per-repo confirmation if present, else global data, else empty
  (nothing known yet -- callers treat this as "nothing available, tell the
  user to run detection").
- **AC6 -- whyline-relay reads `.whyline/account.json` directly, no import.**
  A new, small `capability.py` module (its own file, mirroring how
  `failover.py` is its own focused module rather than folded into
  `config.py`) reads that file, already written by whyline in the same
  repo's `.whyline/` directory, and returns the same shape
  `available_agents()` returns on the whyline side. If the file is absent
  or malformed, every consuming wizard falls back to exactly today's
  PATH-only behavior -- this integration is purely additive, never a hard
  requirement, so a whyline-relay-only repo that has never run any
  `whyline` command keeps working unchanged.
- **AC7 -- Three whyline-relay call sites consume AC6.** Chat's
  `run_setup_wizard`, `_agent_status_lines`, and `/agents`; the relay
  role-selection wizard (built in relay-setup-wizard, RSW); and brainstorm's
  numbered model-selection menu (`MODEL_OPTIONS`) -- each excludes an agent
  AC6 says is unavailable, rather than offering it and finding out later.
  Brainstorm's existing B6 (`check_availability`/"proceed without them?")
  is unchanged and still runs afterward, for the narrower, still-real case
  of an agent that's account-available but not configured in *this repo's*
  `config.toml`.

This spans two independent packages with no shared dependency between them
(AC6), so -- following this project's established pattern for cross-repo
work (whyline-entry-menu/relay-setup-wizard, chat-failover) -- it becomes
**two separate implementation plans at plan-writing time**, one per repo:
the whyline-side plan covers AC1-AC5, the whyline-relay-side plan covers
AC6-AC7 and depends on the whyline-side plan having shipped first (it reads
a file shape AC1 defines).

## Architecture

```
whyline (agentdock)                       whyline-relay
--------------------                      -------------
account.py
  detect() -> per-agent {plan, available, reason}
  (codex/claude: real plan check;
   antigravity/grok: PATH-only)
  available_agents(root) -> set[str]  ---> .whyline/account.json (same repo)
  enable(agent) / disable(agent)                |
  (manual override, persists across detect)     | read-only, plain JSON,
                                                 | no Python import
cli.py entry point                              v
  if load_global() is None:              a small helper (module TBD at plan
      auto-run detect(), print, save     time) reads the file, returns the
  -> Chat or relay? [chat]:              same {available: bool} shape, or
                                          falls back to PATH-only if absent
cmd_model wizard
  loops only over
  available_agents(root)                 chat.run_setup_wizard /
                                          _agent_status_lines / /agents
whyline account status/enable/disable    relay's role-selection wizard (RSW)
  (callable anytime)                     brainstorm's MODEL_OPTIONS menu
                                            each filters via the helper above
```

## Error handling

- One agent's detection failing (codex/claude's subprocess/JWT parsing, or
  antigravity/grok's PATH check somehow raising) never blocks the others --
  extends `detect()`'s existing per-agent try/except guarantee.
- No global account data yet, and even the automatic first-run detection
  fails outright: `available_agents()` returns an empty set; every consuming
  wizard tells the user to run `whyline account detect` manually rather than
  crashing or silently offering nothing with no explanation.
- `enable <agent>` for an agent that isn't actually installed: allowed --
  it's the user's own explicit choice (matching `model.py`'s existing
  "never validate, fail at invocation" philosophy, M4) -- but the CLI
  prints a one-line reminder that it'll fail at invocation time if genuinely
  missing.
- whyline-relay reads a missing or malformed `.whyline/account.json`: falls
  back to today's PATH-only behavior silently, the same permissive pattern
  `account.load_repo`/`load_global` already use for other malformed-JSON
  cases on the whyline side.

## Testing strategy

- `account.py`: `detect_antigravity`/`detect_grok` return `available=True`
  when found on PATH, `False` (not an error) when not; `available_agents()`
  correctly layers repo-confirmed vs. global vs. manual-override data;
  `enable`/`disable` persist and are not clobbered by a subsequent `detect`
  call; `detect` still refreshes every *non*-overridden agent's plan/PATH
  status.
- whyline's entry point: a cold machine (no `~/.whyline/account.json`)
  triggers detection automatically before the Chat/Relay prompt appears; a
  second run does not re-trigger it; `cmd_model`'s wizard only asks about
  available agents, and shows the right guidance when none are available.
- `whyline account status/enable/disable`: each does exactly what its
  decision says, independently testable without touching detection's own
  subprocess/PATH logic (inject a fake account.json).
- whyline-relay: a `.whyline/account.json` marking an agent unavailable
  removes it from chat's setup wizard, `_agent_status_lines`, `/agents`, the
  role wizard's offered choices, and brainstorm's numbered menu; an absent
  file leaves all four exactly as they behave today (PATH-only), proving
  the integration is additive, not a new hard dependency.
