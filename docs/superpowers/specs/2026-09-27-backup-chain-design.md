# Unified Backup Chain Design

**Status:** Approved by user, section-by-section, 2026-09-27.

## Goal

Replace every separate, one-hop backup mechanism in the project (the plain
2-role `[roles.backup]`, chat's `[chat.backup]`, and pipeline's total lack of
one) with a single configured chain of agents, shared by relay's plain
2-role mode, pipeline mode, chat, and brainstorming alike: when the active
agent hits a real limit or is unavailable, walk the chain in order, skipping
anything already tried, until one works or the chain runs out.

## Non-goals

- **Per-agent or per-role exclusions beyond simply omitting an agent from
  the chain.** The chain's own membership and order is the entire
  configuration surface; no separate "never use X as a backup for Y" list.
- **True concurrency or racing multiple chain candidates at once.** The
  chain is walked strictly in order, one candidate tried at a time, same as
  every other failover path already in this project.
- **A migration path or dual-mode support for `[roles.backup]`/
  `[chat.backup]`.** Both are removed outright; this is a clean cutover, not
  a deprecation window (see BC3).
- **Relay's "create a plan" via brainstorming** (piece A, explicitly
  deferred to its own design, sequenced after this one per the user's own
  choice).

## Decisions

- **BC1 — One global chain, shared everywhere.** A single new config table,
  `[backup] chain = ["claude", "codex", "grok", "antigravity"]` (order and
  membership entirely up to the user), used identically by the plain 2-role
  relay runner, the pipeline runner, chat, and brainstorming. Explicit user
  choice: setting a separate backup per role/agent/feature "becomes hectic"
  — one list, configured once, is easier to reason about and to maintain.
- **BC2 — Walk the whole chain, not one hop.** On a failure, skip every
  agent already tried in the current fallback sequence (see BC5) and take
  the next untried chain entry; if that one also fails, keep going; only
  pause once the chain is exhausted. Explicit user choice ("so it test and
  move to that model"), replacing every existing one-hop-only failover path
  in the project.
- **BC3 — `[roles.backup]` and `[chat.backup]` are removed, not kept
  alongside the chain.** Config loading raises a clear `ConfigError` if
  either key is still present, pointing at `[backup].chain` as the
  replacement. Both were narrower, one-hop mechanisms; keeping them next to
  a chain that already generalizes both would mean two backup systems to
  reason about, undermining the entire point of unifying them. This project
  has no external users to migrate — a clean cutover is safe.
- **BC4 — Brainstorm gets chain failover for free through `run_turn`, no
  brainstorm-specific failover code.** Per the chat-brainstorm design's own
  B1 ("reuse `run_turn` for every phase, unchanged"), making `run_turn`'s
  existing internal chat-failover path chain-aware (BC2) automatically
  gives every brainstorm phase real multi-model failover with no new
  failover logic in `chat.py`'s brainstorm code itself. The only
  brainstorm-specific change: a phase's section heading and pass-0 temp
  filename use the agent that *actually* executed the turn (from
  `run_turn`'s own return record), not the originally-requested one — so a
  substituted model's contribution is never mislabeled as having come from
  the model that actually hit its limit. Chain candidates for a brainstorm
  model's slot additionally exclude every *other* model already selected
  for that session, to avoid two slots colliding on the same section
  heading or temp file.
- **BC5 — Override storage reuses today's files, plus one new field.**
  `ActiveOverride` gains `tried: list[str] = []` — every agent already
  attempted and exhausted in the current fallback sequence for that
  role/chat-slot. `active-roles.json` (2-role and pipeline) and
  `chat-active-agents.json` (chat/brainstorm) keep their existing identity,
  location, and keying; a file written before this change simply loads with
  `tried=[]`, which at worst means one redundant retry of the already-known-
  bad primary before the chain continues — harmless, no migration needed.
- **BC6 — Each role/chat-slot walks its own chain independently.** A
  pipeline's `tester` role hopping to `codex` has no effect on the
  `reviewer` role's own state, even if `reviewer`'s primary agent is also
  `codex` — the same underlying agent can serve two roles/slots at once
  with no conflict, since each keeps its own `tried` set and its own
  override entry, keyed exactly as today (role name for relay, requested
  agent name for chat/brainstorm).
- **BC7 — Pipeline gains a real failover branch, mirroring the legacy
  runner's existing one.** `_run_configured_task` currently has none at
  all (relying on `[roles.backup]` being forbidden alongside `[pipeline]`
  at config load, which BC3 removes as a concept entirely). This adds a
  branch structured like the legacy `_run_task`'s existing inline
  check-and-switch logic: on `NO_HANDOFF`, call the existing
  `failover_reason` unchanged, and instead of looking up one fixed backup,
  walk the chain (BC2) for that role.
- **BC8 — Chain exhaustion pauses with its own distinct message.** Today's
  "no backup configured" pause text is reused when the chain is empty or
  absent; a new, distinct message ("every backup in the chain is
  unavailable: claude, codex, grok all failed") is shown when the chain
  itself ran out, so the two situations are never confused when reading a
  pause.

## Architecture

One shared resolver, used by all three call sites:

```
failover.next_backup(chain: list[str], tried: set[str], exclude: set[str] = frozenset()) -> str | None
```

Returns the first entry in `chain` that is in neither `tried` nor `exclude`,
or `None` if none remain. `tried` always includes the agent that just
failed (added by the caller before calling this), so the resolver can never
return the agent that just failed — no separate self-reference check is
needed. `exclude` is used only by brainstorm, passed the session's other
selected models (BC4); every other caller passes an empty set.

**Call sites:**

- **Legacy 2-role runner (`_run_task`)** — today's existing inline
  `failover_reason` → `settings.backups.get(role)` → single switch becomes:
  `failover_reason` unchanged → `next_backup(chain, tried=override.tried | {current_agent})` → write the new `ActiveOverride` (with `tried` extended) or pause with BC8's message if `None`.
- **Pipeline runner (`_run_configured_task`)** — the new branch from BC7,
  structured identically, keyed by `stage.role` instead of the fixed
  `implementer`/`reviewer` names. A new `pipeline_effective_agent(root,
  settings, role) -> str` resolves a pipeline role's current agent the way
  `effective_agent` already does for the fixed 2-role case, but falls back
  to `pipe.roles[role].agent` instead of `getattr(settings.roles, role)`
  (which would raise on a pipeline-only role name like `"tester"`) — this
  is the only genuinely new resolver the chain design needs; everything
  else reuses `next_backup` and the existing override storage.
- **Chat (`resolve_chat_agent`)** — unchanged trigger conditions (a turn's
  `ok` is `False` or `rate_limited` per BC's existing chat-failover checks),
  now walking the chain instead of a single per-agent `[chat.backup]`
  entry; storage stays `chat-active-agents.json`, keyed by requested agent.
- **Brainstorm** — no new call site; inherits chat's behavior via `run_turn`
  per BC4. The brainstorm orchestration code's only change is reading which
  agent actually ran from `run_turn`'s return record for headings/filenames,
  and passing `exclude={other selected models}` down so `run_turn`'s
  internal chain walk skips them for that call.

**Config:**

```toml
[backup]
chain = ["claude", "codex", "grok", "antigravity"]
```

Optional; absent or empty means no backup anywhere, identical to today's
behavior with no backup configured at all. Each entry validated exactly as
every other agent reference already is (built-in or configured generic
agent). `[roles.backup]` or `[chat.backup]` still present anywhere in
config raises `ConfigError` naming `[backup].chain` as the replacement.

## Error handling

- Invalid agent name inside `chain`: rejected at config load, same
  validation path as any other agent field.
- Empty or absent `chain`: valid, means no backup anywhere — unchanged from
  today's no-backup default.
- `[roles.backup]` or `[chat.backup]` still present: `ConfigError` at load,
  naming `[backup].chain` as where it moved.
- Chain exhausted for a role/chat-slot: pauses with BC8's distinct message;
  the override is left in place (not cleared) so `roles status`/`/backups`
  can show which agents were tried.
- Brainstorm collision (every remaining chain candidate is excluded because
  it's another selected model): that model's slot keeps its previous
  section content for this phase — the *existing* B7 graceful-degradation
  behavior, unchanged, not a new error path.
- A chain member not installed or not logged in: `doctor` is extended to
  check every agent named in the chain (not just the active roles' primary
  agents), surfaced up front; if one becomes unavailable between `doctor`
  runs, the ordinary `failover_reason` check treats it as a failure like
  any other, and the chain walk continues past it.

## Testing strategy

- Config: `[backup].chain` parses into an ordered list; empty/absent is
  valid and means no backup; an invalid agent name is rejected;
  `[roles.backup]` or `[chat.backup]` present anywhere raises `ConfigError`
  naming the replacement.
- `next_backup`: returns the first untried, non-excluded chain entry;
  returns `None` when every entry is tried or excluded; never returns an
  agent present in `tried` (covers the self-reference case with no
  dedicated check).
- Legacy 2-role runner: a `NO_HANDOFF` walks two or more hops down the
  chain across repeated simulated failures within one run, pausing with
  BC8's message only once the chain is truly exhausted.
- Pipeline runner: the new failover branch in `_run_configured_task`
  triggers on `NO_HANDOFF` exactly like the legacy runner; two different
  roles independently walk the chain without affecting each other's
  `tried` state, including the case where they land on the same backup
  agent simultaneously.
- Chat: `resolve_chat_agent` walks the chain across repeated failures in
  one session; state is sticky across turns via `chat-active-agents.json`;
  `/backups` output reflects the current agent and its `tried` history.
- Brainstorm: a model whose `run_turn` call fails over mid-phase gets its
  section/temp-file named for the agent that actually ran, not the one
  requested; a chain candidate that's one of the session's other selected
  models is skipped; a brainstorm model's slot with every remaining
  candidate excluded keeps its previous section content rather than
  erroring.
- `doctor`: flags a chain member that isn't installed or isn't logged in,
  in addition to today's existing implementer/reviewer checks.
- End-to-end (once built): a real scratch-repo pipeline run where the
  implementer's stage and its first chain backup both simulate
  `NO_HANDOFF`, confirming the run walks two hops to the third configured
  agent and completes successfully.
