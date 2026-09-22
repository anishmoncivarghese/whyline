# whyline-relay: backup agents and quota/auth failover

Status: design, awaiting the owner's review. Written 2026-09-22.
Relates to: `2026-09-22-relay-agent-adapters-design.md` (piece 1, shipped as relay 0.2.2-0.2.3:
pluggable `implementer`/`reviewer` roles). That design's non-goals named three follow-on pieces —
pipeline stages, a planner stage, and quota-aware fallback between agents — each needing its own
design. **This document is the third one: quota- and auth-aware fallback.** It also records, in
section 8, the fuller roadmap the owner and reviewer worked out for the other two, so that context
isn't lost between design sessions.

## 1. Summary

Today, when an agent filling a role hits a usage limit, the relay pauses and asks a human to try
again later. The owner holds subscriptions to more than one agent (Claude, Codex, Antigravity) and
wants the relay to fall back to a second agent for that role automatically, so a run keeps going
instead of stopping. The same should happen if an agent stops being authenticated partway through
a run. Both are meant to be rare events made non-fatal, not a new way to route work by preference.

## 2. Goals and non-goals

Goals

- A role (`implementer` or `reviewer`) may name one backup agent.
- Two independent triggers switch a role to its backup automatically, within the same `start`
  invocation, with no pause: a detected usage/rate limit, and a detected loss of authentication.
- The switch is sticky: once active, the backup stays the role's effective agent — for the rest of
  that task, and every task after — until the owner changes it, deliberately or via a new command.
- Preflight checks a role's backup, not only its primary, so a backup that itself can't run is
  caught before it is needed.
- Every place that currently reads a role's configured agent reads its *effective* (possibly
  switched) agent instead, so safety checks (same-agent-both-roles, the from-actor check) stay
  honest after a switch.

Non-goals (this design)

- More than one backup per role, or a backup for a backup. With three agents today, a second hop
  would just be the third agent by name; add real chaining only if a fourth agent makes it useful.
- Automatically retrying the primary later. No agent measured so far reports when a quota resets,
  so guessing with a timer would as often retry too early as too late. The owner picks this back up
  by hand (`whyline-relay roles reset`, section 5.4).
- Falling back on anything except the two named triggers. A missing binary, a misconfigured
  command, or a repeated permission denial are configuration problems; silently switching agents
  over one would hide a bug instead of surfacing it. (This was asked and re-confirmed twice in the
  design session: once for triggers generally, once specifically for auth — the owner's answer both
  times was to keep the trigger list to exactly these two, and to prevent most auth failures ahead
  of time instead, which section 5.2 covers.)
- The bigger pieces from section 8 (more than two roles, a planner stage, subscription-aware setup,
  first-run interactive setup). This design assumes exactly today's two roles.

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | Sticky switch, no automatic reversion | No agent's output reliably says when a quota resets; guessing needs a timer that will be wrong in both directions |
| D2 | One backup per role, not a chain | Nothing today needs more than one hop; adds a config dimension for no present use |
| D3 | Switch and continue in the same run, never pause first | Matches the owner's goal directly ("so the activity continues"); a pause-then-resume step would be a needless extra one every single time a limit is hit |
| D4 | Exactly two triggers: rate limit and loss of auth | Both are transient conditions unrelated to whether the work itself is correct; anything else is a configuration bug that should surface, not be papered over |
| D5 | Auth loss is detected by re-running the adapter's own `login_argv`, not by scanning output text | `login_argv` is a real, structured signal the relay already has for two of three agents; guessing at how each tool phrases "you are no longer logged in" would be exactly the kind of fragile heuristic the project has avoided elsewhere |
| D6 | Preflight checks a configured backup's login too | Directly asked for: "before we start, check what subscriptions the user has ... so chances of an auth failure in between a task is less" |

## 4. Where this sits relative to today's code (measured 2026-09-22, relay 0.2.3)

| File | Today | What changes |
|---|---|---|
| `config.py` | `Config.agents: dict[str, list[str]]`; `Roles(implementer, reviewer)`; `Config.adapters` maps a generic agent's name to `"generic"` | New `Config.backups: dict[str, str]` (role name → backup agent name), parsed from `[roles.backup]`, validated the same way `[roles]` is: a backup must name a built-in or a configured generic agent |
| `agents.py` | `rate_limited(text) -> bool` scans for usage-limit phrases | Unchanged. Used as trigger 1, exactly as today |
| `adapters/base.py` | `Adapter.login_argv: tuple[str, ...] | None` already exists, used only by `preflight._logins` | Also read by the new failover check (trigger 2); no change to the `Adapter` shape itself |
| `loop.py` | `_run_task` reads `settings.roles.implementer` / `.reviewer` directly; `_hit_a_limit` is the only check run on `NO_HANDOFF` before pausing | Reads the role's *effective* agent via a new resolver; on `NO_HANDOFF`, checks rate-limit then auth-loss before falling through to today's pause |
| `running.py`, `preflight.py`, `cli.py` (dry-run, status) | Read `settings.roles.*`/`settings.agents[...]` directly in several places | Same resolver used everywhere; preflight also checks each role's backup |
| *(new)* `src/whyline_relay/failover.py` | — | The resolver, the switch logic, and reading/writing the override file |
| *(new)* `.whyline/relay/active-roles.json` | — | The persisted override; local-only, like `running.json`/`state.json` |

## 5. Design

### 5.1 Configuration

```toml
[roles]
implementer = "codex"
reviewer    = "claude"

[roles.backup]
implementer = "antigravity"
# reviewer has no backup here — a rate limit or auth loss on claude pauses, exactly as today
```

A role absent from `[roles.backup]` behaves with zero change from relay 0.2.3. A backup name is
validated exactly like a role in `[roles]`: it must be a built-in agent (`codex`, `claude`) or a
name configured under `[agents.<name>]` with `adapter = "generic"`. There is no default backup for
any role.

### 5.2 Preflight: checking a backup before it's needed

`preflight._agents_in_use` today collects the agent behind each configured role. It gains the
agents behind each configured *backup* too, checked exactly the same way as a primary: on PATH,
and — for a built-in agent — logged in. A backup that fails either check is reported the same as a
primary failing would be, with a hint that names it as the backup for its role
(`"antigravity (backup for implementer) is not logged in"`). This is what answers the owner's ask
directly: run this before a plan starts, and login problems for every agent that could possibly run
— not just the ones about to run first — are visible up front, cutting the chance of hitting an
auth failure mid-task without eliminating it (a session can still lapse hours into a run).

### 5.3 Detecting the two triggers

Both checks run only when a turn ends in `NO_HANDOFF` — exactly where `_hit_a_limit` already runs
today. Order matters: cheapest and most specific check first.

```python
def failover_reason(adapter: Adapter, log_text: str) -> str | None:
    """'rate-limit', 'auth', or None. Never guesses: auth uses a real command, not text-sniffing."""
    if agents.rate_limited(log_text):
        return "rate-limit"
    if adapter.login_argv is not None and not _still_logged_in(adapter):
        return "auth"
    return None
```

`_still_logged_in` runs `adapter.login_argv` again (the same call `preflight._logins` makes) and
reads its exit code. A generic agent (`login_argv is None`) can never trigger the auth path — the
relay has no structured way to ask it, the same limitation `doctor` already states for it. Nothing
about `diagnose()` or the pause message for an *unrecognised* `NO_HANDOFF` changes: this check runs
before that path, not instead of it.

### 5.4 Switching, and where the switch lives

```python
@dataclass(frozen=True)
class ActiveOverride:
    agent: str
    backup_for: str
    reason: str          # "rate-limit" | "auth"
    since: str            # ISO timestamp

def effective_agent(root: Path, settings: Config, role: str) -> str:
    """The agent actually filling `role` right now: the configured one, or its active backup."""
    override = read_overrides(root).get(role)
    return override.agent if override is not None else getattr(settings.roles, role)
```

When `failover_reason` returns non-`None` for the role's *current effective* agent, and that agent
is not already the backup (so a backup that itself hits a limit falls through to the existing pause,
per the non-goals), the relay:

1. Writes `.whyline/relay/active-roles.json` with the new `ActiveOverride` for that role.
2. Prints a status line naming the switch and why (`"==> relay: implementer switched from codex to
   antigravity (codex hit a usage limit)"`), at the same visibility level as the existing turn
   progress lines.
3. Retries the **same round** with the new effective agent — a failover switch is not a review
   round; `max_rounds` is unaffected.

`active-roles.json` is added to `.git/info/exclude` alongside the existing relay runtime files, so
it never dirties the tree or rides into a commit. Every place in `loop.py`, `cli.py` (the dry-run
branch), `preflight.py` (the per-role summary lines), and `running.py` (the marker) that reads
`settings.roles.implementer` / `.reviewer` directly is changed to call `effective_agent` instead, so
the same-agent-both-roles warning, the from-actor mismatch check, and the printed progress verb all
reflect who is actually running, not just what was configured.

If the effective agent is already the backup and it also trips a trigger: no further fallback (D2).
The existing pause fires, with a message naming both agents and each one's reason
(`"antigravity (backup for implementer; codex was already out on a rate limit) also hit a rate
limit; try again when it resets"`).

### 5.5 Inspecting and undoing a switch

Two new subcommands:

- **`whyline-relay roles status`** — one line per role: the configured agent, and, if different, the
  active one and why (`"implementer: codex, currently antigravity (rate-limit, since <time>)"`;
  a role with no override prints just its configured agent).
- **`whyline-relay roles reset [ROLE]`** — deletes the override for `ROLE`, or every override if none
  is given, reverting to the configured agent(s). Confirms what it removed; does nothing (with a
  clear message) if there was nothing to remove.

## 6. Build order and testing

One step, since the whole design is one small, self-contained addition to the existing loop:

1. `config.py` parses and validates `[roles.backup]`.
2. `failover.py`: `failover_reason`, `ActiveOverride`, read/write of `active-roles.json`,
   `effective_agent`.
3. `loop.py` reads roles through `effective_agent`; the switch-and-retry logic on `NO_HANDOFF`.
4. `preflight.py` checks backups; per-role summary lines show the effective agent.
5. `running.py`, `cli.py` dry-run: read through `effective_agent`.
6. A new `roles.py` (matching the pattern of `remove.py`, `preflight.py`: one small module per command group, wired into `cli.py`): `roles status` and `roles reset [ROLE]`, each taking `--repo REPO` like every existing command.

**Regression net:** all existing tests and the existing acceptance suite pass unchanged with no
`[roles.backup]` configured (the resolver's fallback path is exactly today's `settings.roles.*`
read). New tests, with fakes standing in for real agents exactly as the adapters work did: a
rate-limited primary switches and the task still completes in the same run; an agent whose
`login_argv` starts failing mid-plan switches; a backup that also fails falls through to today's
pause with both reasons named; `roles status`/`roles reset` round-trip; preflight fails on a backup
that isn't logged in or isn't on PATH, naming it as a backup.

## 7. Risks and open questions

- **`login_argv` re-checked on every `NO_HANDOFF`** adds one extra process launch (a fast, cheap
  status check) only on the failure path — never on a normal successful turn. Acceptable.
- **A backup and its primary sharing a login** (e.g., both are `claude` somehow, or a generic agent
  wrapping the same underlying account as a built-in one) would make the auth trigger fire, switch,
  and immediately fail again the same way. Not guarded against; the existing "no further fallback"
  behavior (5.4) means this degrades to a pause, not a loop, so it is a wasted switch rather than a
  hazard.
- **`active-roles.json` surviving a manual repo copy or `git clone`.** It is untracked by design
  (like `running.json`), so a fresh clone starts with no overrides, which is the same as today.
  Worth a one-line README callout when this ships.
- **Release**: relay 0.2.4. No whyline release is implied.

## 8. Roadmap beyond this design (recorded, not designed here)

The owner and reviewer worked out a fuller picture in this same design session, to be designed and
built one piece at a time, in this order:

- **A — N named roles in the state machine.** Today's router and config hard-code exactly two roles
  with fixed statuses. Planner, tester, documentation, and security-review roles all need this
  generalized first. Foundation for everything below.
- **D — Subscription-aware setup.** Probe which agents the owner is actually authenticated for
  before asking anything else, so a role can never be assigned to a tool the owner can't run.
- **C — First-run interactive setup.** `init` asks which agent fills which role, and its backup,
  once per repository, informed by D.
- **E — Planner role, with a review gate.** A rough idea becomes `plan.md`, reviewed by a different
  agent, with a human mode (an explicit yes/no) and an auto mode (proceeds after a bounded number of
  review rounds); a second, detailed breakdown pass follows approval.
- **F — Tester role.** Interleaved with the implementer, not concurrent with it: two independent
  turns from the same task text, not two processes touching the working tree at once. True
  concurrency (git worktrees per role, a merge step) was considered and set aside — nothing
  described so far needs literal simultaneity, only independent authorship of the tests versus the
  code.
- **G — Documentation and security-review roles.** Expected to be thin once A exists: the same role
  mechanism, differentiated mainly by prompt content.

## 9. Decision log (this design session, 2026-09-22)

| Question | Answer |
|---|---|
| Sticky switch, or auto-retry the primary later? | Sticky until changed by hand |
| One backup per role, or a chain? | One |
| Switch and continue, or pause once and require `resume`? | Switch and continue, same run |
| Trigger scope: rate limit only, or any failure? | Rate limit and auth loss only, not any failure |
| Should more roles than implementer/reviewer exist? | Yes, eventually (section 8); out of scope here |
| Is literal concurrency (tester "in parallel") required? | No — interleaved turns, independent authorship |
| Build order for the full roadmap | B (this design) → A → D → C → E, F, G |
