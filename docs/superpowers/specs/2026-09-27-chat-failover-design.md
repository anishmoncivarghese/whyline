# Chat Automatic Failover Design

**Status:** Approved by user, section-by-section, 2026-09-27.

## Goal

`whyline chat` automatically retries a rate-limited or logged-out agent's
turn on a configured backup, once, and stays on that backup (sticky) until
you switch back — matching the automatic failover the implementer/reviewer
pipeline has had since 0.2.4, extended to chat's own addressing model
(default agent, or `/prefix`), where none of this exists today.

## Non-goals

- **A second fallback hop.** If the backup also fails, chat reports it and
  stops — never chases a backup-of-a-backup, matching the pipeline's own
  "one hop only" rule exactly.
- **Rewriting `chat.json`'s saved default.** The stated default is your
  preference; the active backup is a separate, temporary layer on top —
  same split the pipeline already has between `config.toml [roles]` and
  `active-roles.json`.
- **Content-based routing, or anything from the chat-repl spec's own
  non-goals.** This only changes what happens when the *currently addressed*
  agent (default or `/prefix`) is rate-limited or logged out.
- **Pipeline failover for custom `[pipeline]` roles.** A separate,
  subsequent piece of work (`[roles.backup]` is still explicitly forbidden
  together with `[pipeline]`; unchanged by this spec).

## Decisions

- **D1 — Reuse `failover.py`'s proven mechanism, with one concrete
  generalization.** `ActiveOverride`, `failover_reason` (rate-limit text
  marker, or a re-checked login-status command — never a guess from output),
  and `pause_message` are reused completely unchanged. `path()` gains an
  optional `filename: str = "active-roles.json"` parameter; `read_overrides`/
  `write_override`/`clear_overrides` gain an optional
  `storage_path: Path | None = None` parameter (computed via `path(root)`
  when omitted), so every existing pipeline call site is unaffected. A new,
  small `chat_path(root) -> Path` returns `path(root, "chat-active-agents.json")`.
  `effective_agent()` is *not* reused for chat — its fallback is
  `getattr(settings.roles, role)`, which has no meaning for a plain agent
  name — so chat gets its own new function instead (see below).
- **D2 — Separate storage file, `.whyline/relay/chat-active-agents.json`.**
  Deliberately not the pipeline's `active-roles.json`: a custom pipeline can
  name a role anything, including an agent's own name (`role = "claude"`),
  which would collide with chat's key ("the agent literally called claude")
  if they shared one file. Keyed by agent name, not role name.
- **D3 — New `[chat.backup]` config table, keyed by agent name.**
  ```toml
  [chat.backup]
  claude = "codex"
  codex  = "grok"
  ```
  Validated identically to `[roles.backup]`: the backup must be a built-in
  agent or a configured generic one, and cannot name the agent it backs up.
  Lives in `config.toml` (shared, committed policy), not `chat.json`
  (personal, gitignored) — matching the existing precedent that backups are
  configuration, not a personal preference.
- **D4 — Auto-retry the same message on the backup, immediately** (explicit
  user choice). On detecting a failover reason, chat writes the override,
  prints what happened, and re-runs the *exact same prompt* against the
  backup within the same turn — you get an answer without retyping anything.
- **D5 — Sticky, matching the pipeline** (explicit user choice). Once
  switched, every subsequent turn addressing that agent name (whether it's
  your saved default or an explicit `/prefix`) transparently resolves to the
  backup — persisted in `chat-active-agents.json`, surviving a REPL restart
  the same way `chat.json` already does — until `/reset-backup` clears it or
  you `/default` to something else entirely.
- **D6 — One hop only.** Failover is attempted only when running the
  *requested* (not-yet-overridden) agent. If a turn is already resolved to
  an active backup and that backup also fails, chat prints
  `failover.pause_message(...)` and stops for this turn — it never looks up
  a backup for the backup.
- **D7 — Uniform across default and `/prefix`.** The override is keyed by
  agent name, not "current default," so it applies consistently regardless
  of how you addressed that agent. There is no special-casing for "was this
  your default" — the same resolve-then-run step handles both.
- **D8 — New meta-commands.** `/backups` lists active overrides (agent,
  backup, reason, since) or reports none active, mirroring
  `whyline-relay roles status`. `/reset-backup [agent]` clears one override,
  or every override with no argument, mirroring `whyline-relay roles reset`.
- **D9 — Whichever agent actually answered is what's shown and logged.**
  `chat.py`'s existing `record["agent"]` (used for the printed `[agent] ...`
  line and the persisted chatlog entry) already reflects whichever name was
  actually run — the resolved (possibly backup) name, not the originally
  addressed one. No new field needed; this falls out of resolving the agent
  name before building the turn, not after.

## Architecture

```
run_turn(root, agent=requested, prompt, ...)
  │
  ├─ resolved = failover.resolve_chat_agent(root, requested)
  │     (chat-active-agents.json lookup; requested unchanged if no override)
  │
  ├─ command = resolve_command(settings, resolved)
  ├─ adapter = config.adapter_for(settings, resolved)
  ├─ ... run the turn as today, using `resolved` throughout ...
  │
  └─ if resolved == requested (no override was active):
         reason = failover.failover_reason(adapter, raw, command)
         if reason and settings.chat_backup.get(requested):
             backup = settings.chat_backup[requested]
             failover.write_override(
                 root,
                 requested,
                 ActiveOverride(
                     agent=backup, backup_for=requested, reason=reason, since=now,
                 ),
                 storage_path=failover.chat_path(root),
             )
             print(f"{requested} {verb}; trying its backup, {backup}...")
             # re-run the exact same turn, once, with backup as `resolved`
             # -- if this second attempt also shows a failover_reason,
             # print pause_message and stop (no further hop; already on
             # a backup, so no [chat.backup] lookup happens on this pass)
     else:
         # already on a backup -- detect failure but never chase further
         reason = failover.failover_reason(adapter, raw, command)
         if reason:
             print(failover.pause_message(resolved, requested, reason, override))
```

`failover.resolve_chat_agent(root, requested: str) -> str` is a new function,
not a reuse of `effective_agent()` (see D1): it reads
`read_overrides(root, storage_path=chat_path(root))` and returns the
override's agent if `requested` has one, else `requested` unchanged.

`chat.repl()` gains two branches in its command-recognition list (alongside
`/default`, `/agents`, `/history`, `/clear`, `/exit`): `/backups` and
`/reset-backup [agent]`.

## Configuration

```toml
[chat.backup]
claude = "codex"
codex  = "grok"
# agy/grok have no backup here -- a rate limit or auth loss on them just
# reports and stops, exactly like today
```

`config.Config` gains `chat_backup: dict[str, str]` (default `{}`), parsed
and validated in `config.load()` the same way `[roles.backup]` already is —
independently of the existing `[pipeline]` vs. `[roles.backup]` mutual
exclusion, since chat is a third, separate context from both the legacy
2-role shape and a custom pipeline.

## Detection, switch, and retry

1. Resolve the requested agent name (default, or `/prefix`) through
   `failover.resolve_chat_agent(root, requested)`.
2. Run the turn exactly as today, using the resolved name throughout
   (command, adapter, logging, display).
3. After the turn completes, call the existing
   `failover.failover_reason(adapter, raw, command)` — unchanged rate-limit
   text-marker-or-login-recheck logic.
4. If a reason is found **and** the resolved name equals the requested name
   (i.e. this wasn't already a backup) **and** `[chat.backup]` names a
   backup for it: write the override, print what happened, and re-run the
   identical turn once against the backup. If that second attempt also
   shows a failover reason, print `pause_message` and stop — no further hop.
5. If the resolved name already differs from the requested name (an
   override was already active) and this run also shows a failover reason:
   print `pause_message` and stop immediately — never look up a further
   backup.
6. If no backup is configured for a failing agent: unchanged from today —
   print the existing rate-limited message, no auto-switch.

## Error handling and edge cases

- Generic agents (agy/grok) have no login-status command, so only the
  rate-limit text marker can trigger their failover — identical restriction
  to the existing pipeline behavior.
- The "sticky" default is a layered override, never a rewrite of
  `chat.json`'s own `default_agent` field — see D2/D5.
- Whichever agent actually produced the response is what's printed and
  logged (D9) — no separate "requested vs. actual" bookkeeping needed
  anywhere else in the turn record.

## Testing strategy

- `failover.py`: `path()`'s new `filename` parameter and `chat_path()` tested
  against a real tmp dir; `read_overrides`/`write_override`/`clear_overrides`
  called with an explicit `storage_path` proven independent of the
  pipeline's own `active-roles.json` (writing one never touches the other);
  `resolve_chat_agent` — no override → requested unchanged; override present
  → the override's agent.
- `chat.py`'s `run_turn`: no backup configured → unchanged (existing tests
  still pass verbatim); backup configured and a rate-limit/auth reason is
  detected → auto-retries on the backup, response/log reflect the backup's
  name, override persisted; backup also fails → `pause_message`-shaped
  output, no further hop, override still names the *original* failing
  agent; an already-overridden agent → resolved silently, no redundant
  login-status re-check performed twice in the same call.
- `chat.py`'s `repl()`: `/backups` lists active overrides or reports none;
  `/reset-backup <agent>` clears one, `/reset-backup` with no argument
  clears all — confirmed via a follow-up `/backups` showing empty.
- `config.py`: `[chat.backup]` accepts a valid backup; rejects an unknown
  agent name, self-reference, and a backup that isn't built-in or
  configured-generic — mirroring `[roles.backup]`'s existing test shapes.
- End-to-end (once built): a real scratch-repo session forcing a
  rate-limit-shaped response from a scripted stand-in for the primary,
  confirming the real retry, the real backup's real answer, and the
  override file's real content.
