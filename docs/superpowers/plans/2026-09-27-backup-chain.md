# Unified Backup Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every separate, one-hop backup mechanism (`[roles.backup]`, `[chat.backup]`, and pipeline mode's total lack of one) with a single configured `[backup] chain = [...]`, shared by relay's plain 2-role mode, pipeline mode, chat, and brainstorming: on a real failure, walk the chain in order, skipping anything already tried, until one agent works or the chain runs out.

**Architecture:** One new resolver, `failover.next_backup(chain, tried, exclude=frozenset())`, used by four call sites that each already detect a failure today (the legacy 2-role runner's inline check, a brand-new equivalent branch in the pipeline runner, and chat's `run_turn`, which brainstorm inherits for free). Override storage stays exactly where it is (`active-roles.json`, `chat-active-agents.json`), gaining one new field, `tried`, on `ActiveOverride`. `[roles.backup]` and `[chat.backup]` are removed outright at config load, not kept alongside the new mechanism.

**Tech Stack:** Python 3.11+, stdlib only. No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-27-backup-chain-design.md`

## Global Constraints

- No new runtime dependency.
- `[roles.backup]` and `[chat.backup]` are removed, not deprecated: config load raises a clear `ConfigError` pointing at `[backup].chain` if either is still present anywhere in `config.toml`. There is no dual-mode support.
- The chain is walked in order, skipping every agent already tried in the current fallback sequence (and, for brainstorm only, any agent excluded because it's one of the session's other selected models); it never revisits an agent already tried, and never picks the agent that just failed.
- `active-roles.json` and `chat-active-agents.json` keep their existing file identity, location, and per-role/per-agent keying -- only `ActiveOverride` gains one new field, `tried: list[str] = []`, defaulting to `[]` when absent so an old file on disk still loads.
- Every existing test must still pass after every task, except the ones this plan explicitly rewrites because the config surface they exercised (`[roles.backup]`, `[chat.backup]`) no longer exists.
- Read every file this plan names fresh before editing it. Line numbers below are accurate as of this plan's writing (main branch, just after 0.2.19 plus the in-flight chat-brainstorm plan); by the time this runs, chat-brainstorm will have merged and shifted line numbers in `chat.py`. Match code by the surrounding context shown, not by line number alone.

**Note on this pairing:** Grok implements, Codex reviews and commits -- the pairing used for chat-failover (CF) and relay-setup-wizard (RSW), both of which completed cleanly with this pairing.

**Sequencing note:** this plan depends on nothing in the chat-brainstorm (CB) plan except that CB must have already merged to `main` and `brainstorm.py` must exist there, since Task 6 modifies it. Confirm `git log main` shows the CB plan's tasks ticked, and `src/whyline_relay/brainstorm.py` exists on `main`, before running `whyline-relay init`/`start` for this plan.

---

### Task 1: `config.py` -- one `[backup] chain`, old keys removed

**Files:**
- Modify: `src/whyline_relay/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Config.backup_chain: list[str]` (replaces `Config.backups: dict[str, str]` and `Config.chat_backup: dict[str, str]`, both removed). `[roles.backup]` and `[chat.backup]` anywhere in `config.toml` raise `ConfigError` naming `[backup].chain` as the replacement.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py` (it already imports `config` and has a `write()`
helper that writes `.whyline/relay/config.toml`):

```python
def test_backup_chain_defaults_to_empty(tmp_path):
    settings = config.load(tmp_path)
    assert settings.backup_chain == []


def test_backup_chain_parses_in_order(tmp_path):
    write(
        tmp_path,
        '[backup]\nchain = ["claude", "codex"]\n',
    )
    settings = config.load(tmp_path)
    assert settings.backup_chain == ["claude", "codex"]


def test_backup_chain_rejects_an_unknown_agent(tmp_path):
    write(tmp_path, '[backup]\nchain = ["not-a-real-agent"]\n')
    with pytest.raises(config.ConfigError, match="not-a-real-agent"):
        config.load(tmp_path)


def test_backup_chain_accepts_a_configured_generic_agent(tmp_path):
    write(
        tmp_path,
        '[backup]\nchain = ["grok"]\n'
        '[agents.grok]\nadapter = "generic"\ncommand = ["grok", "-p"]\n',
    )
    settings = config.load(tmp_path)
    assert settings.backup_chain == ["grok"]


def test_backup_chain_works_alongside_a_configured_pipeline(tmp_path):
    write(tmp_path, PIPELINE_TOML + '\n[backup]\nchain = ["grok"]\n'
          '[agents.grok]\nadapter = "generic"\ncommand = ["grok", "-p"]\n')
    settings = config.load(tmp_path)
    assert settings.backup_chain == ["grok"]
    assert settings.pipeline is not None


def test_roles_backup_is_rejected_with_a_pointer_to_the_new_key(tmp_path):
    write(tmp_path, '[roles]\nimplementer = "codex"\nreviewer = "claude"\n'
          '[roles.backup]\nimplementer = "claude"\n')
    with pytest.raises(config.ConfigError, match=r"\[backup\]\.chain"):
        config.load(tmp_path)


def test_roles_backup_is_rejected_together_with_a_pipeline_too(tmp_path):
    write(tmp_path, PIPELINE_TOML + '\n[roles.backup]\nimplementer = "claude"\n')
    with pytest.raises(config.ConfigError, match=r"\[backup\]\.chain"):
        config.load(tmp_path)


def test_chat_backup_is_rejected_with_a_pointer_to_the_new_key(tmp_path):
    write(tmp_path, '[chat.backup]\nclaude = "codex"\n')
    with pytest.raises(config.ConfigError, match=r"\[backup\]\.chain"):
        config.load(tmp_path)


def test_backup_chain_rejects_a_non_list(tmp_path):
    write(tmp_path, '[backup]\nchain = "claude"\n')
    with pytest.raises(config.ConfigError, match="chain"):
        config.load(tmp_path)
```

Note: `PIPELINE_TOML` is already defined at the top of `tests/test_config.py`;
reuse it, don't redefine it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_config.py -k backup -v`
Expected: FAIL (`AttributeError: 'Config' object has no attribute 'backup_chain'`
or similar -- the old tests referencing `[roles.backup]`/`[chat.backup]` as
*valid* config will also start failing once you make the change below, which
is expected and covered in Step 5).

- [ ] **Step 3: Remove the old backup config surfaces**

In `src/whyline_relay/config.py`, read the whole `load()` function first (it's
long). Then make these changes:

1. Right after `role_values = raw.get("roles") or {}` (near the top of the
   `raw_pipeline is not None` branch point), add a single check that applies
   to both pipeline and legacy mode:

   ```python
   role_values = raw.get("roles") or {}
   if "backup" in role_values:
       raise ConfigError(
           "[roles.backup] is no longer supported; configure a shared "
           "fallback chain under [backup].chain instead"
       )
   raw_pipeline = raw.get("pipeline")
   ```

2. In the pipeline branch, delete the now-redundant original check:

   ```python
   if "backup" in role_values:
       raise ConfigError(
           "[roles.backup] is not supported together with [pipeline]"
       )
   ```

   (Step 3.1 already covers this case, unconditionally.)

3. In the legacy (`else`) branch, remove `"backup"` from the allowed-keys
   list:

   ```python
   for key in role_values:
       if key not in ("implementer", "reviewer"):
           raise ConfigError(
               f"[roles] has an unknown key '{key}' (use implementer or reviewer)"
           )
   ```

   Then delete the entire `backup_values` block that follows it (the
   `backup_values = role_values.get("backup") or {}` line through the loop
   that validates it) -- it's dead code once `"backup"` can never reach here.

4. Replace the `chat_backup` parsing block:

   ```python
   raw_chat = raw.get("chat") or {}
   chat_backup_raw = raw_chat.get("backup") or {}
   chat_backup: dict[str, str] = {}
   for key, value in chat_backup_raw.items():
       ...
       chat_backup[key] = value
   ```

   with:

   ```python
   raw_chat = raw.get("chat") or {}
   if "backup" in raw_chat:
       raise ConfigError(
           "[chat.backup] is no longer supported; configure a shared "
           "fallback chain under [backup].chain instead"
       )
   ```

5. Add new `[backup]` table parsing right after that (still inside `load()`,
   before the `raw_planner` section):

   ```python
   raw_backup = raw.get("backup") or {}
   chain_raw = raw_backup.get("chain", [])
   if not isinstance(chain_raw, list):
       raise ConfigError("[backup] chain must be a list of agent names")
   backup_chain: list[str] = []
   for value in chain_raw:
       if not isinstance(value, str) or not value:
           raise ConfigError("[backup] chain entries must be non-empty strings")
       if value not in adapters.BUILTIN and value not in configured_adapters:
           builtins = ", ".join(sorted(adapters.BUILTIN))
           raise ConfigError(
               f"[backup] chain names {value!r}, which is not a built-in "
               f"agent ({builtins}) or a configured generic agent"
           )
       backup_chain.append(value)
   ```

6. In the `Config` dataclass definition, replace:

   ```python
   backups: dict[str, str] = field(default_factory=dict)
   ```

   and

   ```python
   chat_backup: dict[str, str] = field(default_factory=dict)
   ```

   with a single new field in the same position as the first:

   ```python
   backup_chain: list[str] = field(default_factory=list)
   ```

7. In the final `return Config(...)` call, remove the `backups=dict(backup_values),`
   and `chat_backup=chat_backup,` lines, and add `backup_chain=backup_chain,`
   in their place.

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `uv run pytest tests/test_config.py -k backup -v`
Expected: PASS

- [ ] **Step 5: Fix every existing test that used the removed config surfaces**

Run the whole suite to find them:

Run: `uv run pytest -q`
Expected: failures in `tests/test_config.py` (any test that configured
`[roles.backup]` or `[chat.backup]` as *valid* input, or that constructs a
`config.Config(...)` directly passing `backups=` or `chat_backup=`),
`tests/test_loop_failover.py`, `tests/test_chat_turn.py`, and
`tests/test_preflight.py`. Fix each one now, by name:

- `tests/test_config.py`: search for `roles.backup` and `chat.backup` in
  existing (not the ones you just added) tests. Any test asserting these
  *work* as config (not the two new tests from Step 1 asserting they're
  rejected) must be deleted or rewritten to use `[backup] chain = [...]`
  instead, with updated assertions against `settings.backup_chain`.
- `tests/test_loop_failover.py`: fix it completely now, in this task --
  don't leave it half-updated for Task 3.
  1. `settings_with_backup(root, implementer_command, backup_agent,
     backup_command, backups)`'s last parameter is currently a dict,
     `backups`, passed as `backups=backups` to `config.Config(...)`. Rename
     it to `chain: list[str]` and pass `backup_chain=chain` instead.
  2. Every one of its 5 call sites currently passes `{"implementer":
     "aider"}` as that last argument. Change all 5 to pass `["aider"]`
     instead (a single-entry chain reproduces the exact same one-hop
     behavior these tests already check -- no other change needed in any
     of these 5 tests).
  3. Delete `test_the_backup_also_failing_pauses_and_names_both` entirely.
     Its assertions (`"backup for implementer" in reason` and `"codex was
     already out" in reason`) describe the old single-backup
     `pause_message` wording for "the one configured backup also failed" --
     under the chain design that situation now produces the new "every
     backup in the chain is unavailable" message instead (Task 3 adds
     `test_chain_exhaustion_pauses_with_a_distinct_message`, which
     supersedes this test's coverage under the new wording). Note the
     deletion and its reason via `whyline note`.
  4. `test_dry_run_shows_the_effective_backup_agent` writes
     `'[roles.backup]\nimplementer = "claude"\n'` directly into
     `config.toml`, which now raises `ConfigError` at load. Change that
     line to `'[backup]\nchain = ["claude"]\n'` -- the test's assertion
     doesn't depend on the chain being consulted at all (it writes an
     `ActiveOverride` straight to disk and checks that `--dry-run` reports
     the effective agent from that override), so any validly-parsing config
     works; this keeps the fixture realistic.
- `tests/test_chat_turn.py`: delete
  `test_run_turn_switches_to_the_backup_and_retries_automatically`,
  `test_run_turn_reports_and_stops_when_the_backup_also_fails`,
  `test_run_turn_uses_an_already_active_backup_silently`, and
  `test_run_turn_with_no_backup_configured_behaves_exactly_as_before` for
  now -- Task 5 re-adds equivalent tests against `[backup].chain`. Note in
  your `whyline note` that Task 5 restores this coverage in the new shape.
- `tests/test_preflight.py`: delete
  `test_missing_backup_program_names_its_role`,
  `test_failed_backup_login_names_its_role`, and
  `test_the_summary_line_labels_a_backup_as_a_backup_not_a_primary` for
  now -- Task 7 re-adds equivalent tests against `[backup].chain`. Note the
  same way.

Run: `uv run pytest -q`
Expected: PASS (some tests deleted, as itemized above; everything remaining
green)

- [ ] **Step 6: Commit**

```bash
git add tests/test_config.py tests/test_loop_failover.py tests/test_chat_turn.py tests/test_preflight.py src/whyline_relay/config.py
git commit -m "feat: replace [roles.backup]/[chat.backup] with a single [backup] chain"
```

---

### Task 2: `failover.py` -- `ActiveOverride.tried` and `next_backup()`

**Files:**
- Modify: `src/whyline_relay/failover.py`
- Test: `tests/test_failover.py`

**Interfaces:**
- Consumes: nothing new from Task 1 directly (this task's own tests construct
  `ActiveOverride` and lists by hand), but the field this task adds is what
  Tasks 3-6 all read and write.
- Produces: `ActiveOverride.tried: list[str] = field(default_factory=list)`
  (a new field, positioned last so every existing positional call like
  `ActiveOverride("antigravity", "codex", "rate-limit", "2026-01-01T00:00:00")`
  keeps working unchanged). `next_backup(chain: list[str], tried: set[str],
  exclude: frozenset[str] = frozenset()) -> str | None` -- the first entry in
  `chain` not in `tried` or `exclude`, or `None` if none remain.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_failover.py`:

```python
def test_active_override_tried_defaults_to_empty_list():
    override = failover.ActiveOverride("antigravity", "codex", "rate-limit", "t")
    assert override.tried == []


def test_active_override_tried_can_be_set():
    override = failover.ActiveOverride(
        "grok", "codex", "rate-limit", "t", tried=["codex", "claude"]
    )
    assert override.tried == ["codex", "claude"]


def test_read_overrides_defaults_tried_when_absent_from_disk(tmp_path):
    target = failover.path(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_text(
        '{"implementer": {"agent": "claude", "backup_for": "codex", '
        '"reason": "rate-limit", "since": "t"}}'
    )
    overrides = failover.read_overrides(tmp_path)
    assert overrides["implementer"].tried == []


def test_read_overrides_round_trips_tried(tmp_path):
    failover.write_override(
        tmp_path, "implementer",
        failover.ActiveOverride("grok", "codex", "rate-limit", "t", tried=["codex"]),
    )
    overrides = failover.read_overrides(tmp_path)
    assert overrides["implementer"].tried == ["codex"]


def test_next_backup_returns_the_first_untried_entry():
    assert failover.next_backup(["claude", "codex", "grok"], tried=set()) == "claude"


def test_next_backup_skips_already_tried_entries():
    result = failover.next_backup(
        ["claude", "codex", "grok"], tried={"claude", "codex"}
    )
    assert result == "grok"


def test_next_backup_returns_none_when_the_chain_is_exhausted():
    result = failover.next_backup(
        ["claude", "codex"], tried={"claude", "codex"}
    )
    assert result is None


def test_next_backup_returns_none_for_an_empty_chain():
    assert failover.next_backup([], tried=set()) is None


def test_next_backup_skips_excluded_entries_too():
    result = failover.next_backup(
        ["claude", "codex", "grok"], tried=set(), exclude={"claude"}
    )
    assert result == "codex"


def test_next_backup_never_returns_the_agent_that_just_failed():
    # The caller is required to have added the failed agent to `tried`
    # before calling; this test documents that contract holds even when
    # the failed agent is the chain's only entry.
    result = failover.next_backup(["claude"], tried={"claude"})
    assert result is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_failover.py -k "tried or next_backup" -v`
Expected: FAIL (`TypeError: __init__() got an unexpected keyword argument
'tried'` / `AttributeError: module 'failover' has no attribute 'next_backup'`)

- [ ] **Step 3: Implement**

In `src/whyline_relay/failover.py`:

1. Add `from typing import Iterable` to the existing imports (or use
   `list[str] | set[str]` directly -- keep the signature exactly as `set[str]`
   for `tried`, since every caller already deals in sets or can call `set(...)`
   cheaply).

2. Change the `ActiveOverride` dataclass:

   ```python
   @dataclass(frozen=True)
   class ActiveOverride:
       agent: str
       backup_for: str
       reason: str  # "rate-limit" | "auth"
       since: str  # ISO timestamp
       tried: list[str] = field(default_factory=list)
   ```

   (add `field` to the `from dataclasses import asdict, dataclass` line ->
   `from dataclasses import asdict, dataclass, field`)

3. Update `read_overrides` to accept a record with or without `"tried"`:

   ```python
   def read_overrides(
       root: Path, storage_path: Path | None = None
   ) -> dict[str, ActiveOverride]:
       target = storage_path if storage_path is not None else path(root)
       try:
           raw = json.loads(target.read_text(encoding="utf-8"))
       except (OSError, json.JSONDecodeError):
           return {}
       if not isinstance(raw, dict):
           return {}
       required = ("agent", "backup_for", "reason", "since")
       result: dict[str, ActiveOverride] = {}
       for role, record in raw.items():
           if not isinstance(record, dict) or not all(
               isinstance(record.get(f), str) for f in required
           ):
               continue
           tried = record.get("tried")
           if not isinstance(tried, list) or not all(isinstance(t, str) for t in tried):
               tried = []
           result[role] = ActiveOverride(
               **{f: record[f] for f in required}, tried=list(tried)
           )
       return result
   ```

4. Add `next_backup` near the bottom of the module, right after
   `rate_limited`:

   ```python
   def next_backup(
       chain: list[str], tried: set[str], exclude: frozenset[str] = frozenset()
   ) -> str | None:
       """The first chain entry not already tried or excluded, or None if the
       chain is exhausted. Callers add the just-failed agent to `tried` before
       calling, so this never returns the agent that just failed."""
       for candidate in chain:
           if candidate not in tried and candidate not in exclude:
               return candidate
       return None
   ```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_failover.py -v`
Expected: PASS (every test in the file, including the ones already there)

- [ ] **Step 5: Commit**

```bash
git add src/whyline_relay/failover.py tests/test_failover.py
git commit -m "feat: add ActiveOverride.tried and failover.next_backup"
```

---

### Task 3: Legacy 2-role runner walks the chain

**Files:**
- Modify: `src/whyline_relay/loop.py` (the `_run_task` function; also fix the
  `settings_with_backup` helper's callers in `tests/test_loop_failover.py`
  left pending from Task 1, Step 5)
- Test: `tests/test_loop_failover.py`

**Interfaces:**
- Consumes: `failover.next_backup` and `ActiveOverride.tried` from Task 2;
  `settings.backup_chain` from Task 1.
- Produces: `_run_task` now walks the whole configured chain on a
  `NO_HANDOFF`, instead of switching to one fixed `settings.backups.get(role)`
  and stopping there.

- [ ] **Step 1: Write the failing tests**

First finish the `settings_with_backup` helper update left pending from Task
1 (change its last parameter from `backups: dict` to `chain: list[str]`, and
have it pass `backup_chain=chain` to `config.Config(...)`), then fix every
existing call site in `tests/test_loop_failover.py` that passed a `backups=`
dict (e.g. `{"implementer": "aider"}`) to instead pass `chain=["aider"]` (a
single-entry chain reproduces the exact same one-hop behavior those existing
tests check).

Then add these new tests to the same file (they need a second, distinct fake
agent script beyond `FAKE`/the rate-limited one already at the top of the
file -- reuse the existing `RATE_LIMITED` fake-script text for as many
positions in the chain as needed, since every entry in this test's chain
should behave identically: rate-limited until the last one):

```python
def test_a_chain_of_two_backups_walks_past_the_first_when_it_also_fails(
    repo, tmp_path
):
    limited = tmp_path / "limited.py"
    limited.write_text(RATE_LIMITED)
    also_limited = tmp_path / "also_limited.py"
    also_limited.write_text(RATE_LIMITED)
    base = config.load(repo)
    settings = config.Config(
        plan=base.plan,
        max_rounds=base.max_rounds,
        timeout_minutes=base.timeout_minutes,
        branch_prefix=base.branch_prefix,
        agents={
            "codex": [sys.executable, str(limited)],
            "claude": [
                sys.executable, FAKE, str(repo), "claude", "claude",
                "approved", "yes",
            ],
            "aider": [sys.executable, str(also_limited)],
            "cline": [
                sys.executable, FAKE, str(repo), "cline", "claude",
                "ready-for-review", "no",
            ],
        },
        status_map=base.status_map,
        adapters={"aider": "generic", "cline": "generic"},
        backup_chain=["aider", "cline"],
    )
    base_commit = loop.gitcheck.head_commit(repo)
    outcome = loop.run_task(repo, settings, TASK, base_commit=base_commit, echo=False)
    assert outcome.committed
    overrides = failover.read_overrides(repo)
    assert overrides["implementer"].agent == "cline"
    assert overrides["implementer"].tried == ["codex", "aider"]


def test_chain_exhaustion_pauses_with_a_distinct_message(repo, tmp_path):
    limited = tmp_path / "limited.py"
    limited.write_text(RATE_LIMITED)
    also_limited = tmp_path / "also_limited.py"
    also_limited.write_text(RATE_LIMITED)
    base = config.load(repo)
    settings = config.Config(
        plan=base.plan,
        max_rounds=base.max_rounds,
        timeout_minutes=base.timeout_minutes,
        branch_prefix=base.branch_prefix,
        agents={
            "codex": [sys.executable, str(limited)],
            "claude": [
                sys.executable, FAKE, str(repo), "claude", "claude",
                "approved", "yes",
            ],
            "aider": [sys.executable, str(also_limited)],
        },
        status_map=base.status_map,
        adapters={"aider": "generic"},
        backup_chain=["aider"],
    )
    base_commit = loop.gitcheck.head_commit(repo)
    with pytest.raises(loop.Paused) as excinfo:
        loop.run_task(repo, settings, TASK, base_commit=base_commit, echo=False)
    assert "every backup in the chain is unavailable" in str(excinfo.value)
    assert "codex" in str(excinfo.value)
    assert "aider" in str(excinfo.value)


def test_no_chain_configured_pauses_exactly_as_before(repo, tmp_path):
    limited = tmp_path / "limited.py"
    limited.write_text(RATE_LIMITED)
    base = config.load(repo)
    settings = config.Config(
        plan=base.plan,
        max_rounds=base.max_rounds,
        timeout_minutes=base.timeout_minutes,
        branch_prefix=base.branch_prefix,
        agents={
            "codex": [sys.executable, str(limited)],
            "claude": [
                sys.executable, FAKE, str(repo), "claude", "claude",
                "approved", "yes",
            ],
        },
        status_map=base.status_map,
    )
    base_commit = loop.gitcheck.head_commit(repo)
    with pytest.raises(loop.Paused) as excinfo:
        loop.run_task(repo, settings, TASK, base_commit=base_commit, echo=False)
    assert "hit a usage or rate limit" in str(excinfo.value)
    assert "every backup in the chain is unavailable" not in str(excinfo.value)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_loop_failover.py -v`
Expected: FAIL on the three new tests (`AttributeError:` or a `Paused` message
that doesn't yet distinguish chain exhaustion from no-chain-configured; the
walk logic doesn't exist yet so it stops after one hop).

- [ ] **Step 3: Implement**

In `src/whyline_relay/loop.py`, find the `NO_HANDOFF` branch inside
`_run_task` (currently around line 321-359):

```python
        if move == routing.NO_HANDOFF:
            try:
                text = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            adapter = config.adapter_for(settings, agent)
            reason = failover.failover_reason(
                adapter, text, settings.agents[agent], runner=runner
            )
            if reason is not None:
                backup = settings.backups.get(role)
                if backup is not None and backup != agent:
                    verb, _ = failover.REASON_TEXT[reason]
                    failover.write_override(
                        root,
                        role,
                        failover.ActiveOverride(
                            agent=backup,
                            backup_for=agent,
                            reason=reason,
                            since=datetime.now().astimezone().isoformat(),
                        ),
                    )
                    if echo:
                        agents.print_status(
                            f"==> relay: {role} switched from {agent} to {backup} "
                            f"({agent} {verb})"
                        )
                    continue
                existing = failover.read_overrides(root).get(role)
                raise Paused(
                    failover.pause_message(agent, role, reason, existing), target
                )
            raise Paused(
                f"{agent} exited without handing off"
                f"{_no_handoff_detail(target, adapter, settings.agents[agent])}; "
                "nothing was routed",
                target,
            )
```

Replace the `if reason is not None:` block's body with a chain walk:

```python
            if reason is not None:
                existing = failover.read_overrides(root).get(role)
                already_tried = set(existing.tried) if existing is not None else set()
                already_tried.add(agent)
                backup = failover.next_backup(settings.backup_chain, already_tried)
                if backup is not None:
                    verb, _ = failover.REASON_TEXT[reason]
                    failover.write_override(
                        root,
                        role,
                        failover.ActiveOverride(
                            agent=backup,
                            backup_for=agent,
                            reason=reason,
                            since=datetime.now().astimezone().isoformat(),
                            tried=sorted(already_tried),
                        ),
                    )
                    if echo:
                        agents.print_status(
                            f"==> relay: {role} switched from {agent} to {backup} "
                            f"({agent} {verb})"
                        )
                    continue
                if not settings.backup_chain:
                    raise Paused(
                        failover.pause_message(agent, role, reason, existing), target
                    )
                raise Paused(
                    f"every backup in the chain is unavailable for {role} "
                    f"({', '.join(sorted(already_tried))} all failed)",
                    target,
                )
```

Note the distinction: an empty `settings.backup_chain` reuses today's exact
`pause_message` wording (Global Constraint: chain absent behaves exactly as
before); a non-empty chain that's been fully walked gets the new, distinct
"every backup in the chain is unavailable" message.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_loop_failover.py -v`
Expected: PASS (all tests in the file, including the three new ones and the
pre-existing ones now using `chain=[...]`)

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/loop.py tests/test_loop_failover.py
git commit -m "feat: the legacy 2-role runner walks the whole backup chain"
```

---

### Task 4: Pipeline runner gets real failover

**Files:**
- Modify: `src/whyline_relay/failover.py` (add `pipeline_effective_agent`)
- Modify: `src/whyline_relay/loop.py` (`_run_configured_task`)
- Test: `tests/test_failover.py`, `tests/test_loop_pipeline.py` (create
  `tests/test_loop_pipeline_failover.py` if `test_loop_pipeline.py` doesn't
  already have a natural home for failover-specific tests -- check first)

**Interfaces:**
- Consumes: `failover.next_backup`, `ActiveOverride.tried` (Task 2),
  `settings.backup_chain` (Task 1).
- Produces: `failover.pipeline_effective_agent(root: Path, settings:
  config.Config, role: str) -> str` -- the pipeline role's current agent
  (its backup if switched, else `pipe.roles[role].agent`). `_run_configured_task`
  now has a real `NO_HANDOFF` failover branch, walking the chain exactly like
  Task 3's legacy runner, keyed by `stage.role`.

- [ ] **Step 1: Write the failing test for `pipeline_effective_agent`**

Check first whether `tests/test_loop_pipeline.py` exists and what it covers
(`ls tests/ | grep pipeline`); read it before adding to it, so your new tests
match its existing fixture style (it almost certainly already builds a
`pipeline_module.Pipeline` and a pipeline-shaped `config.Config` by hand for
its own tests -- reuse that pattern rather than inventing a new one).

Add to `tests/test_failover.py`:

```python
def test_pipeline_effective_agent_with_no_override(tmp_path):
    from whyline_relay import pipeline as pipeline_module
    from whyline_relay.config import Config

    pipe = pipeline_module.Pipeline(
        roles={"tester": pipeline_module.Role(name="tester", agent="claude")},
        stages={},
        profiles={},
        default_profile="default",
    )
    settings = Config(
        plan="p", max_rounds=3, timeout_minutes=30, branch_prefix="r/",
        agents={}, status_map={}, pipeline=pipe,
    )
    assert failover.pipeline_effective_agent(tmp_path, settings, "tester") == "claude"


def test_pipeline_effective_agent_with_an_override(tmp_path):
    from whyline_relay import pipeline as pipeline_module
    from whyline_relay.config import Config

    pipe = pipeline_module.Pipeline(
        roles={"tester": pipeline_module.Role(name="tester", agent="claude")},
        stages={},
        profiles={},
        default_profile="default",
    )
    settings = Config(
        plan="p", max_rounds=3, timeout_minutes=30, branch_prefix="r/",
        agents={}, status_map={}, pipeline=pipe,
    )
    failover.write_override(
        tmp_path, "tester",
        failover.ActiveOverride("grok", "claude", "rate-limit", "t"),
    )
    assert failover.pipeline_effective_agent(tmp_path, settings, "tester") == "grok"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_failover.py -k pipeline_effective_agent -v`
Expected: FAIL (`AttributeError: module 'failover' has no attribute
'pipeline_effective_agent'`)

- [ ] **Step 3: Implement `pipeline_effective_agent`**

In `src/whyline_relay/failover.py`, add this right after `effective_agent`:

```python
def pipeline_effective_agent(root: Path, settings: config.Config, role: str) -> str:
    """The agent actually filling a configured pipeline's `role` right now:
    its backup if switched, else the pipeline's own configured agent for it.
    A pipeline role name (e.g. "tester") is not a field on Roles, so this
    cannot reuse effective_agent()'s getattr(settings.roles, role) fallback."""
    override = read_overrides(root).get(role)
    if override is not None:
        return override.agent
    return settings.pipeline.roles[role].agent
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_failover.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing tests for the pipeline runner's failover branch**

Read `tests/test_loop_pipeline.py` in full now (if it exists) to match its
fixtures exactly -- in particular how it builds a `pipeline_module.Pipeline`
with real stages/profiles/transitions, and how it fakes an agent's handoff
(it's almost certainly the same `fake_role_agent.py` script used in
`tests/test_loop_failover.py`, referenced the same way). Using that same
style, add a test (in `tests/test_loop_pipeline.py`, or a new
`tests/test_loop_pipeline_failover.py` if the existing file has no natural
place for a failover-specific fixture) equivalent in shape to Task 3's
`test_a_chain_of_two_backups_walks_past_the_first_when_it_also_fails`, but
built as a one-stage pipeline (a single stage whose role is, say, `"solo"`,
transitioning straight to `"@complete"` on a `"done"` outcome) where the
stage's configured agent is rate-limited and the chain has one working
backup:

```python
def test_a_pipeline_stage_switches_to_the_chain_backup_on_no_handoff(
    repo, tmp_path
):
    from whyline_relay import pipeline as pipeline_module

    limited = tmp_path / "limited.py"
    limited.write_text(RATE_LIMITED)
    pipe = pipeline_module.Pipeline(
        roles={"solo": pipeline_module.Role(name="solo", agent="codex")},
        stages={
            "work": pipeline_module.Stage(
                id="work", role="solo", prompt="implement",
                transitions={"done": "@complete"},
            )
        },
        profiles={"default": pipeline_module.Profile(name="default", stages=("work",))},
        default_profile="default",
    )
    base = config.load(repo)
    settings = config.Config(
        plan=base.plan, max_rounds=base.max_rounds,
        timeout_minutes=base.timeout_minutes, branch_prefix=base.branch_prefix,
        agents={
            "codex": [sys.executable, str(limited)],
            "aider": [
                sys.executable, FAKE, str(repo), "aider", "aider",
                "done", "no",
            ],
        },
        status_map=base.status_map,
        adapters={"aider": "generic"},
        backup_chain=["aider"],
        pipeline=pipe,
        pipeline_fingerprint="test",
    )
    base_commit = loop.gitcheck.head_commit(repo)
    outcome = loop.run_task(repo, settings, TASK, base_commit=base_commit, echo=False)
    assert outcome.committed
    overrides = failover.read_overrides(repo)
    assert overrides["solo"].agent == "aider"
    assert overrides["solo"].tried == ["codex"]
```

Check `fake_role_agent.py`'s argument order against `tests/test_loop_failover.py`'s
existing calls before trusting the argument list above verbatim -- it takes
`(repo, from_actor, to_actor, status, block)`-shaped positional arguments in
that file's usage; match it exactly, since a mismatch here silently produces
a handoff the pipeline's `transitions` table won't recognize (an "unknown"
outcome, not a passing test).

Also go back to `tests/test_failover.py` and add one more unit-level test
next to the two `pipeline_effective_agent` tests from Step 1 above, proving
two roles' overrides are independent of each other even when they resolve to
the same backup agent (a full end-to-end pipeline run isn't needed for this
-- `pipeline_effective_agent` reads `active-roles.json` directly, so writing
to it for two roles and checking each resolves independently is the right
level for this check, and avoids needing a second stage's fake agent output
to correctly address a first stage's switched-to agent, which is fiddly to
get right and not what this particular property is about):

```python
def test_two_pipeline_roles_have_independent_overrides_even_on_the_same_backup(
    tmp_path,
):
    from whyline_relay import pipeline as pipeline_module
    from whyline_relay.config import Config

    pipe = pipeline_module.Pipeline(
        roles={
            "drafter": pipeline_module.Role(name="drafter", agent="codex"),
            "checker": pipeline_module.Role(name="checker", agent="claude"),
        },
        stages={},
        profiles={},
        default_profile="default",
    )
    settings = Config(
        plan="p", max_rounds=3, timeout_minutes=30, branch_prefix="r/",
        agents={}, status_map={}, pipeline=pipe,
    )
    failover.write_override(
        tmp_path, "drafter",
        failover.ActiveOverride("aider", "codex", "rate-limit", "t", tried=["codex"]),
    )
    failover.write_override(
        tmp_path, "checker",
        failover.ActiveOverride("aider", "claude", "rate-limit", "t", tried=["claude"]),
    )
    assert failover.pipeline_effective_agent(tmp_path, settings, "drafter") == "aider"
    assert failover.pipeline_effective_agent(tmp_path, settings, "checker") == "aider"
    overrides = failover.read_overrides(tmp_path)
    assert overrides["drafter"].tried == ["codex"]
    assert overrides["checker"].tried == ["claude"]
```

This particular test exercises `pipeline_effective_agent`, already implemented
back in Step 3 -- run it now and confirm it already passes (`uv run pytest
tests/test_failover.py -k independent_overrides -v`), rather than expecting it
to fail; it's added here, alongside the pipeline-runner test, only because it
belongs conceptually with this task's other multi-role coverage, not because
it's untested code.

- [ ] **Step 6: Run the pipeline-runner test to verify it fails**

Run: `uv run pytest tests/test_loop_pipeline.py -k chain_backup -v`
(or the new file's equivalent path)
Expected: FAIL -- `_run_configured_task` currently always raises `Paused` on
any `NO_HANDOFF`, per its own docstring.

- [ ] **Step 7: Implement the pipeline runner's failover branch**

In `src/whyline_relay/loop.py`, inside `_run_configured_task`:

1. Change the `effective_agents` line (currently, near the top of the
   function):

   ```python
   effective_agents = {name: role.agent for name, role in pipe.roles.items()}
   ```

   to build it from `pipeline_effective_agent` instead, and move it inside
   the `while True:` loop (recomputed every iteration, since a failover
   switch changes it mid-run -- exactly like `_run_task` recomputes
   `implementer`/`reviewer` at the top of its own loop):

   Remove the old line entirely from its current position, and at the very
   top of the `while True:` loop body, add:

   ```python
   while True:
       effective_agents = {
           name: failover.pipeline_effective_agent(root, settings, name)
           for name in pipe.roles
       }
       stage = pipe.stages[current_stage_id]
       agent = effective_agents[stage.role]
   ```

   (this replaces the existing `stage = pipe.stages[current_stage_id]` /
   `agent = pipe.roles[stage.role].agent` lines with the versions above --
   `agent` now comes from `effective_agents`, which is override-aware).

2. `effective_agents` is used two more times below in the same function
   (once passed to `pipeline.decide(...)`, once passed to
   `prompts.stage_footer(...)`) -- both already reference the local variable
   by name, so no further change is needed there; they now pick up the
   override-aware version automatically.

3. Update the two lines just above the loop that compute
   `implementer_agent`/`reviewer_agent` (used only for prompt-template
   `{implementer}`/`{reviewer}` placeholders) to also be override-aware,
   since a stale value here would show the wrong name in a rendered prompt
   even though the actual invocation already switched:

   ```python
   implementer_agent = (
       failover.pipeline_effective_agent(root, settings, "implementer")
       if "implementer" in pipe.roles else ""
   )
   reviewer_agent = (
       failover.pipeline_effective_agent(root, settings, "reviewer")
       if "reviewer" in pipe.roles else ""
   )
   ```

   Leave these computed once before the loop, same as today -- they're
   template-display values, not the routing-critical `effective_agents` dict,
   and Task 4's own tests don't exercise this display path, so no test
   changes are needed for this specific edit; it's a correctness fix that
   rides along with the rest of this task.

4. Now replace the `NO_HANDOFF` branch itself. Find:

   ```python
        if decision.kind == "no-handoff":
            try:
                text = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            adapter = config.adapter_for(settings, agent)
            reason = failover.failover_reason(
                adapter, text, settings.agents[agent], runner=runner
            )
            if reason is not None:
                existing = failover.read_overrides(root).get(stage.role)
                raise Paused(
                    failover.pause_message(agent, stage.role, reason, existing), target
                )
            raise Paused(
                f"{agent} exited without handing off"
                f"{_no_handoff_detail(target, adapter, settings.agents[agent])}; "
                "nothing was routed",
                target,
            )
   ```

   Replace the `if reason is not None:` block's body with the same chain-walk
   shape Task 3 added to `_run_task`, keyed by `stage.role`:

   ```python
            if reason is not None:
                existing = failover.read_overrides(root).get(stage.role)
                already_tried = set(existing.tried) if existing is not None else set()
                already_tried.add(agent)
                backup = failover.next_backup(settings.backup_chain, already_tried)
                if backup is not None:
                    verb, _ = failover.REASON_TEXT[reason]
                    failover.write_override(
                        root,
                        stage.role,
                        failover.ActiveOverride(
                            agent=backup,
                            backup_for=agent,
                            reason=reason,
                            since=datetime.now().astimezone().isoformat(),
                            tried=sorted(already_tried),
                        ),
                    )
                    if echo:
                        agents.print_status(
                            f"==> relay: {stage.role} switched from {agent} to "
                            f"{backup} ({agent} {verb})"
                        )
                    continue
                if not settings.backup_chain:
                    raise Paused(
                        failover.pause_message(agent, stage.role, reason, existing),
                        target,
                    )
                raise Paused(
                    f"every backup in the chain is unavailable for {stage.role} "
                    f"({', '.join(sorted(already_tried))} all failed)",
                    target,
                )
   ```

   `continue` re-enters the `while True:` loop, which recomputes
   `effective_agents` and `agent` at the top (per Step 7.1) before running
   the stage again -- this time with the backup.

5. Update `_run_configured_task`'s docstring: remove the sentence
   `"[roles.backup] is refused together with [pipeline] at config load (see
   config.py), so there is no failover branch here: a no-handoff always
   pauses -- there is never a backup to switch to."` and replace it with:
   `"On a no-handoff, walks settings.backup_chain for stage.role exactly like
   _run_task's own legacy failover branch, via failover.next_backup."`

- [ ] **Step 8: Run the test to verify it passes**

Run: `uv run pytest tests/test_loop_pipeline.py -v` (or wherever you placed
the new test)
Expected: PASS

- [ ] **Step 9: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add src/whyline_relay/failover.py src/whyline_relay/loop.py tests/test_failover.py tests/test_loop_pipeline.py
git commit -m "feat: the pipeline runner walks the backup chain too"
```

(adjust the `git add` paths if you created a new test file instead of adding
to `tests/test_loop_pipeline.py`)

---

### Task 5: Chat's `run_turn` walks the chain

**Files:**
- Modify: `src/whyline_relay/chat.py`
- Test: `tests/test_chat_turn.py`

**Interfaces:**
- Consumes: `failover.next_backup`, `ActiveOverride.tried` (Task 2),
  `settings.backup_chain` (Task 1).
- Produces: `run_turn(..., exclude: frozenset[str] = frozenset())` -- a new,
  optional parameter (default empty, so every existing caller is unaffected)
  that Task 6 (brainstorm) will use to keep a chain substitution from
  colliding with another model already selected in the same session.
  `run_turn`'s returned record's `"agent"` key is unchanged in meaning (the
  agent that actually executed, whether primary or a chain substitute) --
  Task 6 depends on this already being true.

- [ ] **Step 1: Write the failing tests**

In `tests/test_chat_turn.py`, replace the four tests deleted in Task 1 Step 5
(`test_run_turn_switches_to_the_backup_and_retries_automatically`,
`test_run_turn_reports_and_stops_when_the_backup_also_fails`,
`test_run_turn_uses_an_already_active_backup_silently`,
`test_run_turn_with_no_backup_configured_behaves_exactly_as_before`) with:

```python
def test_run_turn_switches_to_the_backup_and_retries_automatically(tmp_path: Path):
    _init_repo(tmp_path)
    relay = tmp_path / ".whyline" / "relay"
    relay.mkdir(parents=True, exist_ok=True)
    (relay / "config.toml").write_text('[backup]\nchain = ["codex"]\n')
    settings = config.load(tmp_path)
    calls = []

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult
        calls.append(command[0])
        if command[0] == "claude":
            return RunResult(1, "You have exceeded your usage limit. Try again later.")
        text = "pong from backup\n"
        _deliver(command, text)
        return RunResult(0, text)

    fake_login_ok = lambda *a, **k: subprocess.CompletedProcess(a, 0, "", "")
    record = chat.run_turn(
        tmp_path, agent="claude", prompt="ping", settings=settings,
        run_fn=fake_run_fn, runner=fake_login_ok,
    )
    assert calls == ["claude", "codex"]
    assert record["agent"] == "codex"
    assert record["response"] == "pong from backup"
    assert "claude hit a usage or rate limit" in record["failover_notice"]
    from whyline_relay import failover
    override = failover.read_overrides(tmp_path, failover.chat_path(tmp_path))
    assert override["claude"].agent == "codex"
    assert override["claude"].reason == "rate-limit"
    assert override["claude"].tried == ["claude"]


def test_run_turn_walks_past_a_backup_that_also_fails(tmp_path: Path):
    _init_repo(tmp_path)
    relay = tmp_path / ".whyline" / "relay"
    relay.mkdir(parents=True, exist_ok=True)
    (relay / "config.toml").write_text(
        '[backup]\nchain = ["codex", "aider"]\n'
        '[agents.aider]\nadapter = "generic"\ncommand = ["aider"]\n'
    )
    settings = config.load(tmp_path)
    calls = []

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult
        calls.append(command[0])
        if command[0] in ("claude", "codex"):
            return RunResult(1, "You have exceeded your usage limit. Try again later.")
        text = "pong from aider\n"
        _deliver(command, text)
        return RunResult(0, text)

    fake_login_ok = lambda *a, **k: subprocess.CompletedProcess(a, 0, "", "")
    record = chat.run_turn(
        tmp_path, agent="claude", prompt="ping", settings=settings,
        run_fn=fake_run_fn, runner=fake_login_ok,
    )
    assert calls == ["claude", "codex", "aider"]
    assert record["agent"] == "aider"
    from whyline_relay import failover
    override = failover.read_overrides(tmp_path, failover.chat_path(tmp_path))
    assert override["claude"].agent == "aider"
    assert override["claude"].tried == ["claude", "codex"]


def test_run_turn_reports_and_stops_when_the_chain_is_exhausted(tmp_path: Path):
    _init_repo(tmp_path)
    relay = tmp_path / ".whyline" / "relay"
    relay.mkdir(parents=True, exist_ok=True)
    (relay / "config.toml").write_text('[backup]\nchain = ["codex"]\n')
    settings = config.load(tmp_path)

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult
        text = "You have exceeded your usage limit. Try again later."
        _deliver(command, text)
        return RunResult(1, text)

    record = chat.run_turn(
        tmp_path, agent="claude", prompt="ping", settings=settings, run_fn=fake_run_fn
    )
    assert record["agent"] == "codex"
    assert "also" in record["failover_notice"]
    assert "hit a usage or rate limit" in record["failover_notice"]


def test_run_turn_uses_an_already_active_backup_and_keeps_walking_if_it_fails(
    tmp_path: Path
):
    _init_repo(tmp_path)
    relay = tmp_path / ".whyline" / "relay"
    relay.mkdir(parents=True, exist_ok=True)
    (relay / "config.toml").write_text(
        '[backup]\nchain = ["codex", "aider"]\n'
        '[agents.aider]\nadapter = "generic"\ncommand = ["aider"]\n'
    )
    settings = config.load(tmp_path)
    from whyline_relay import failover
    failover.write_override(
        tmp_path, "claude",
        failover.ActiveOverride(
            "codex", "claude", "rate-limit", "2026-01-01T00:00:00", tried=["claude"]
        ),
        storage_path=failover.chat_path(tmp_path),
    )
    calls = []

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult
        calls.append(command[0])
        if command[0] == "codex":
            return RunResult(1, "You have exceeded your usage limit. Try again later.")
        text = "pong from aider\n"
        _deliver(command, text)
        return RunResult(0, text)

    fake_login_ok = lambda *a, **k: subprocess.CompletedProcess(a, 0, "", "")
    record = chat.run_turn(
        tmp_path, agent="claude", prompt="ping", settings=settings,
        run_fn=fake_run_fn, runner=fake_login_ok,
    )
    assert calls == ["codex", "aider"]
    assert record["agent"] == "aider"
    override = failover.read_overrides(tmp_path, failover.chat_path(tmp_path))
    assert override["claude"].tried == ["claude", "codex"]


def test_run_turn_with_no_chain_configured_behaves_exactly_as_before(tmp_path: Path):
    _init_repo(tmp_path)
    settings = config.load(tmp_path)

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult
        return RunResult(1, "You have exceeded your usage limit. Try again later.")

    record = chat.run_turn(
        tmp_path, agent="claude", prompt="ping", settings=settings, run_fn=fake_run_fn
    )
    assert record["agent"] == "claude"
    assert record["rate_limited"] is True
    assert "failover_notice" not in record


def test_run_turn_exclude_skips_a_chain_candidate(tmp_path: Path):
    _init_repo(tmp_path)
    relay = tmp_path / ".whyline" / "relay"
    relay.mkdir(parents=True, exist_ok=True)
    (relay / "config.toml").write_text(
        '[backup]\nchain = ["codex", "aider"]\n'
        '[agents.aider]\nadapter = "generic"\ncommand = ["aider"]\n'
    )
    settings = config.load(tmp_path)
    calls = []

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult
        calls.append(command[0])
        if command[0] == "claude":
            return RunResult(1, "You have exceeded your usage limit. Try again later.")
        text = "pong from aider\n"
        _deliver(command, text)
        return RunResult(0, text)

    fake_login_ok = lambda *a, **k: subprocess.CompletedProcess(a, 0, "", "")
    record = chat.run_turn(
        tmp_path, agent="claude", prompt="ping", settings=settings,
        run_fn=fake_run_fn, runner=fake_login_ok, exclude=frozenset({"codex"}),
    )
    assert calls == ["claude", "aider"]
    assert record["agent"] == "aider"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_chat_turn.py -v`
Expected: FAIL on every test added in Step 1 (the old single-hop
`chat_backup` logic doesn't understand `[backup] chain` or `exclude` at all).

- [ ] **Step 3: Implement**

In `src/whyline_relay/chat.py`, replace the whole body of `run_turn` (from
`settings = settings if settings is not None else config.load(root)` through
the `record = chatlog.append(...)` call) with:

```python
def run_turn(
    root: Path,
    *,
    agent: str,
    prompt: str,
    settings: "config.Config | None" = None,
    run_fn=None,
    runner=subprocess.run,
    commit_message: str | None = None,
    exclude: frozenset[str] = frozenset(),
) -> dict:
    settings = settings if settings is not None else config.load(root)
    run_fn = run_fn if run_fn is not None else agents.run
    requested = agent
    resolved = failover.resolve_chat_agent(root, requested)
    full_prompt = _build_prompt(root, prompt)
    attempt = _execute_agent_call(
        root, resolved, prompt, full_prompt, settings, run_fn,
        commit_message=commit_message,
    )
    final_agent = resolved
    failover_notice: str | None = None
    current = resolved
    existing = failover.read_overrides(root, failover.chat_path(root)).get(requested)
    tried = set(existing.tried) if existing is not None else set()
    tried.add(resolved)

    while settings.backup_chain:
        reason = failover.failover_reason(
            attempt["adapter"], attempt["raw"], attempt["command"], runner=runner
        )
        if reason is None:
            break
        backup = failover.next_backup(settings.backup_chain, tried, exclude)
        if backup is None:
            override = failover.read_overrides(root, failover.chat_path(root)).get(
                requested
            )
            failover_notice = failover.pause_message(current, requested, reason, override)
            break
        verb, _ = failover.REASON_TEXT[reason]
        failover_notice = f"{current} {verb}; trying its backup, {backup}..."
        failover.write_override(
            root,
            requested,
            failover.ActiveOverride(
                agent=backup,
                backup_for=requested,
                reason=reason,
                since=datetime.now(timezone.utc).isoformat(),
                tried=sorted(tried),
            ),
            storage_path=failover.chat_path(root),
        )
        attempt = _execute_agent_call(
            root, backup, prompt, full_prompt, settings, run_fn,
            commit_message=commit_message,
        )
        final_agent = backup
        current = backup
        tried.add(backup)

    rate_limited = failover.rate_limited(
        attempt["adapter"], attempt["raw"], attempt["command"]
    )
    record = chatlog.append(
        root, agent=final_agent, prompt=prompt, response=attempt["response"],
        files_changed=attempt["files_changed"], ok=attempt["ok"],
    )
    record["rate_limited"] = rate_limited
    if attempt["committed"]:
        record["diff_stat"] = attempt["diff_stat"]
    if failover_notice:
        record["failover_notice"] = failover_notice
    return record
```

Two behavioral notes worth understanding before you move on (both already
covered by the tests above, but explaining them here so you know they're
intentional, not bugs):

- When `resolved != requested` (an override was already active coming in),
  the loop's first `failover_reason` check runs against the *already-resolved*
  agent's first attempt, exactly like the old "already on an active backup"
  branch did -- there's no separate code path for it anymore, the `while`
  loop naturally covers both "just discovered the primary is down" and
  "already on a backup and it just failed too," since `tried` is seeded from
  the existing override's own `tried` list plus `resolved` itself.
- `settings.backup_chain` being empty short-circuits the `while` immediately
  (matching the `if settings.backup_chain:` -- actually written as `while
  settings.backup_chain:` above, which re-checks every iteration but is
  always the same falsy list, so it simply never enters when empty) --
  zero behavior change for a repo with no `[backup]` configured, matching
  `test_run_turn_with_no_chain_configured_behaves_exactly_as_before`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_chat_turn.py -v`
Expected: PASS

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/chat.py tests/test_chat_turn.py
git commit -m "feat: chat's run_turn walks the whole backup chain"
```

---

### Task 6: Brainstorm relabels a chain substitution and excludes its own models

**Files:**
- Modify: `src/whyline_relay/brainstorm.py`
- Test: `tests/test_brainstorm_passes.py` if it exists (created during the
  chat-brainstorm plan), or whichever brainstorm test file(s) exist on `main`
  by the time you run this -- list `tests/` and read whichever file(s) cover
  `brainstorm.py` before writing anything, since this plan was written before
  chat-brainstorm (CB) finished and its test file layout may not match this
  description exactly.

**Interfaces:**
- Consumes: `run_turn(..., exclude=...)` from Task 5; `run_turn`'s returned
  record's `"agent"` key (Task 5's docstring note: already the actually-
  executed agent, unchanged by this plan).
- Produces: every place in `brainstorm.py` that calls `chat.run_turn` for a
  specific model now captures the returned record, passes `exclude` (the
  set of every *other* selected model's agent key for that session), and
  uses `record["agent"]` -- not the originally-requested `agent_key` -- to
  decide which label a phase's contribution is attributed under.

- [ ] **Step 1: Read `brainstorm.py` fresh, in full**

This plan was written while chat-brainstorm (CB) was still mid-flight; by the
time you run this task, `brainstorm.py` will have review-pass and
final-synthesis code (CB-4/CB-5/CB-6) that did not exist when this plan's
tasks were drafted. Read the whole file now. You are looking for every call
to `chat.run_turn(...)` -- there will be at least three groups: pass-0
research (`run_pass_zero`, already shown below as it existed when this plan
was written, for orientation only -- do not assume it's unchanged), combined
review passes, and final synthesis. Every one of them needs the same two
changes: pass `exclude=`, and use the returned record's `"agent"` for
whichever heading/label that call's output gets attributed under.

For orientation, `run_pass_zero` looked like this when this plan was
written:

```python
def run_pass_zero(
    root: Path,
    models: list[tuple[str, str]],
    topic: str,
    *,
    settings: "config.Config",
    run_fn=None,
    runner=None,
    print_fn=None,
) -> None:
    print_fn = print_fn if print_fn is not None else print
    for agent_key, label in models:
        prompt = (
            f'Research "{topic}" independently. Write your findings to '
            f"{temp_path(root, agent_key)} as plain markdown. This is your "
            "own independent pass -- you haven't seen, and shouldn't need, "
            "any other model's perspective yet."
        )
        kwargs = {"run_fn": run_fn} if run_fn is not None else {}
        if runner is not None:
            kwargs["runner"] = runner
        try:
            chat.run_turn(
                root,
                agent=agent_key,
                prompt=prompt,
                settings=settings,
                commit_message=(
                    f'brainstorm: {agent_key} independent research on "{topic}"'
                ),
                **kwargs,
            )
        except (agents.AgentMissing, agents.AgentTimeout, chat.AgentUnavailable) as error:
            print_fn(f"{label} could not research this pass: {error}")
```

and `merge_pass_zero` used each model's own requested `label` unconditionally
for its section heading -- this is exactly the gap this task closes.

- [ ] **Step 2: Write the failing tests**

The core behavior to test, regardless of how CB shaped the surrounding code
by the time you get here: a model whose `chat.run_turn` call returns a
record whose `"agent"` differs from the agent that was requested must have
its contribution attributed to the *returned* agent's label, and the
`exclude` set passed to that call must contain every other selected model's
agent key.

Add tests along these lines (adapt names/signatures to whatever
`run_pass_zero`/`merge_pass_zero` or their CB-4/CB-5/CB-6-added siblings
actually look like once you've read the real file in Step 1 -- the shape
below is illustrative of the *behavior*, not a literal diff to paste,
since the exact function signatures may have grown parameters this plan's
author could not have known about):

```python
def test_run_pass_zero_excludes_other_selected_models(tmp_path, monkeypatch):
    settings = config.load(tmp_path)
    _init_a_real_repo(tmp_path)  # match whatever helper the real test file uses
    models = [("claude", "Claude"), ("codex", "Codex")]
    captured_excludes = []

    def fake_run_turn(root, *, agent, prompt, settings, exclude=frozenset(), **kwargs):
        captured_excludes.append((agent, exclude))
        return {"agent": agent, "response": "ok", "rate_limited": False, "ok": True}

    monkeypatch.setattr(brainstorm.chat, "run_turn", fake_run_turn)
    brainstorm.run_pass_zero(tmp_path, models, "topic", settings=settings)
    excludes_by_agent = dict(captured_excludes)
    assert excludes_by_agent["claude"] == frozenset({"codex"})
    assert excludes_by_agent["codex"] == frozenset({"claude"})


def test_merge_pass_zero_labels_a_substituted_agent_by_who_actually_ran(
    tmp_path, monkeypatch
):
    settings = config.load(tmp_path)
    _init_a_real_repo(tmp_path)
    models = [("claude", "Claude"), ("codex", "Codex")]

    def fake_run_turn(root, *, agent, prompt, settings, exclude=frozenset(), **kwargs):
        # claude's slot is actually served by codex (a chain substitution)
        actual = "codex" if agent == "claude" else agent
        brainstorm.temp_path(root, agent).parent.mkdir(parents=True, exist_ok=True)
        brainstorm.temp_path(root, agent).write_text(f"findings from {actual}")
        return {"agent": actual, "response": "ok", "rate_limited": False, "ok": True}

    monkeypatch.setattr(brainstorm.chat, "run_turn", fake_run_turn)
    brainstorm.run_pass_zero(tmp_path, models, "topic", settings=settings)
    brainstorm.merge_pass_zero(tmp_path, models, "topic")
    shared = brainstorm.shared_path(tmp_path, "topic").read_text(encoding="utf-8")
    assert "## Codex" in shared
    # claude's own slot was actually served by codex, so it must not also
    # appear mislabeled as "## Claude"
    assert shared.count("## Codex") == 2  # codex's own slot, plus claude's substituted one
```

Write a real `_init_a_real_repo` helper (or reuse whatever the actual test
file already has) that creates a git repo the way every other test file in
this project does (see `_init_repo` in `tests/test_chat_turn.py` for the
pattern), since `merge_pass_zero` calls `gitcheck.commit_all`.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_brainstorm_passes.py -k "exclude or substitut" -v`
(adjust the file name/path to wherever you placed these)
Expected: FAIL (`TypeError: run_pass_zero() got an unexpected keyword
argument` or the merge producing the wrong heading, depending on which
change you're testing).

- [ ] **Step 4: Implement**

For every `chat.run_turn(...)` call site found in Step 1:

1. Compute the exclude set as every *other* selected model's agent key:
   `exclude = frozenset(key for key, _ in models if key != agent_key)`.
2. Pass it: `chat.run_turn(root, agent=agent_key, ..., exclude=exclude, **kwargs)`.
3. Capture the return value (`record = chat.run_turn(...)`, not a bare call
   with the result discarded).
4. Use `record["agent"]` (falling back to `agent_key` only if the call
   raised one of the already-handled exceptions and no record exists) as the
   key into `MODEL_OPTIONS` to find the actually-serving agent's display
   label, and use that label for whatever heading/section that phase writes.
   Concretely, for `merge_pass_zero`'s current per-model loop (`for agent_key,
   label in models:`), change it to look up the actual label after calling
   `run_pass_zero` -- which means `run_pass_zero` must now return a mapping
   `{requested_agent_key: actual_agent_key}` instead of `None`, and
   `merge_pass_zero` must accept that mapping and use
   `dict(MODEL_OPTIONS_BY_KEY).get(actual, label)` (build a
   `{key: label}` lookup from `MODEL_OPTIONS`, e.g. `{key: label for _,
   key, label in MODEL_OPTIONS}`) in place of the requested model's own
   `label` when they differ. Apply the same "return and use the actual
   agent" pattern to whichever review-pass and final-synthesis functions
   Step 1 found, adjusted to how each one attributes its section (a review
   pass writes under `"## {agent_label}"` per the spec's `REVIEW_PROMPT` --
   that heading must also use the actually-executed agent's label, not the
   requested one).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_brainstorm_passes.py -v` (or wherever you
placed them)
Expected: PASS

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/whyline_relay/brainstorm.py tests/test_brainstorm_passes.py
git commit -m "feat: brainstorm relabels a chain-substituted model and excludes its own selections"
```

---

### Task 7: `doctor` checks the chain; `roles status` shows `tried`

**Files:**
- Modify: `src/whyline_relay/preflight.py`
- Modify: `src/whyline_relay/roles.py`
- Test: `tests/test_preflight.py`, `tests/test_roles.py`

**Interfaces:**
- Consumes: `settings.backup_chain` (Task 1), `ActiveOverride.tried`
  (Task 2).
- Produces: `doctor` now checks every agent named in `settings.backup_chain`
  is on PATH and logged in, for both legacy and pipeline mode alike.
  `roles.status()`'s output line for an overridden role now also shows which
  agents were already tried, when there are any beyond the current one.

- [ ] **Step 1: Write the failing tests**

First finish the two `tests/test_preflight.py` tests left pending from Task
1, Step 5 (`test_missing_backup_program_names_its_role`,
`test_failed_backup_login_names_its_role`,
`test_the_summary_line_labels_a_backup_as_a_backup_not_a_primary`), rewriting
each to configure `[backup] chain = [...]` instead of `[roles.backup]`, with
the same assertions (a chain entry's program-missing/login-failure message
should still say `"(backup for <role>)"`, and the summary line should still
say `"<role> backup: <agent>"` rather than mislabeling it a primary).
Read each test's current body (before you deleted it in Task 1) via `git
log -p -- tests/test_preflight.py` or by checking Task 1's own diff, since
this task restores equivalent coverage in the new config shape rather than
inventing new assertions from scratch.

Then add a new test confirming a pipeline (not just legacy mode) also gets
its chain checked -- something legacy-mode-only never needed since
`[roles.backup]` was forbidden with `[pipeline]` before this plan (BC3
removes that restriction along with the old key entirely):

```python
def test_a_pipeline_configured_backup_chain_is_also_checked(
    ready_repo: Path, monkeypatch
):
    from whyline_relay import config as config_module

    (ready_repo / ".whyline" / "relay" / "config.toml").write_text(
        '[roles]\nimplementer = "codex"\nreviewer = "claude"\n'
        '[pipeline]\ndefault_profile = "default"\n'
        '[pipeline.profiles]\ndefault = ["implement"]\n'
        '[pipeline.stages.implement]\nrole = "implementer"\nprompt = "implement"\n'
        '[pipeline.stages.implement.on]\ndone = "@complete"\n'
        '[backup]\nchain = ["aider"]\n'
        '[agents.aider]\nadapter = "generic"\ncommand = ["aider"]\n'
    )
    checks = preflight.run(ready_repo, runner=lambda *a, **k: subprocess.CompletedProcess(a, 1))
    messages = [c.message for c in checks]
    assert any("aider" in m and "not on PATH" in m for m in messages), messages
```

Check `ready_repo`'s fixture definition at the top of `tests/test_preflight.py`
first (it almost certainly sets up PATH so `codex`/`claude` resolve but
nothing else does) to make sure `aider` really is missing from PATH in that
fixture, matching the assertion above.

Add to `tests/test_roles.py`:

```python
def test_status_shows_tried_history_when_present(tmp_path):
    from whyline_relay import config, failover, roles

    settings = config.load(tmp_path)
    failover.write_override(
        tmp_path, "implementer",
        failover.ActiveOverride(
            "grok", "codex", "rate-limit", "2026-01-01T00:00:00",
            tried=["codex", "claude"],
        ),
    )
    output = roles.status(tmp_path, settings)
    assert "tried: codex, claude" in output


def test_status_omits_tried_when_there_is_only_the_current_backup(tmp_path):
    from whyline_relay import config, failover, roles

    settings = config.load(tmp_path)
    failover.write_override(
        tmp_path, "implementer",
        failover.ActiveOverride("grok", "codex", "rate-limit", "2026-01-01T00:00:00"),
    )
    output = roles.status(tmp_path, settings)
    assert "tried:" not in output
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_preflight.py tests/test_roles.py -k "chain or tried" -v`
Expected: FAIL (`_agents_in_use` doesn't look at `backup_chain` yet;
`roles.status` doesn't mention `tried` at all)

- [ ] **Step 3: Implement the `doctor` change**

In `src/whyline_relay/preflight.py`, replace `_agents_in_use`:

```python
def _agents_in_use(
    settings: config.Config,
) -> dict[str, tuple[list[str], str | None]]:
    agents: dict[str, tuple[list[str], str | None]] = {}
    if settings.pipeline is not None:
        for role in settings.pipeline.roles.values():
            if role.agent not in agents:
                agents[role.agent] = (settings.agents[role.agent], None)
    else:
        for role in ("implementer", "reviewer"):
            name = getattr(settings.roles, role)
            if name not in agents:
                agents[name] = (settings.agents[name], None)
    for name in settings.backup_chain:
        if name not in agents:
            agents[name] = (settings.agents[name], "the chain")
    return agents
```

Note the message shape changes slightly from before: it used to say
`"backup for implementer"` (naming a specific role, since `[roles.backup]`
was keyed by role); a shared chain has no single role to name, so it now
says `"backup for the chain"`. Update the two f-strings in `_programs` and
`_logins` that build these messages (`f"{program} (backup for {backup_for})
is not on PATH"` and the login equivalent) -- no change needed to those
f-strings themselves, since `backup_for` is now the string `"the chain"`
rather than a role name, and the sentence still reads correctly
("aider (backup for the chain) is not on PATH"). Update your Step 1 test
rewrites' assertions to match this exact wording (`"backup for the chain"`,
not `"backup for implementer"`).

Also check `_role_checks`' own use of `backup_for` (the loop building the
`"ok"` summary line, `f"{backup_for} backup"` if `backup_for is not None`
else the primary/role name) -- it reads the same tuple, so it also now says
`"the chain backup"` instead of `"implementer backup"`. Update the third
restored test's assertion (`test_the_summary_line_labels_a_backup_as_a_backup_not_a_primary`)
to match: `assert any(msg.startswith("the chain backup: ") for msg in
messages)`.

- [ ] **Step 4: Implement the `roles.status` change**

In `src/whyline_relay/roles.py`, in `status()`:

```python
def status(root: Path, settings: config.Config) -> str:
    lines = []
    overrides = failover.read_overrides(root)
    for role, configured in current_roles(settings).items():
        override = overrides.get(role)
        if override is None:
            lines.append(f"{role}: {configured}")
        else:
            verb, _ = failover.REASON_TEXT[override.reason]
            line = (
                f"{role}: {configured}, currently {override.agent} "
                f"({override.reason}: {configured} {verb}, since {override.since})"
            )
            if override.tried and override.tried != [override.backup_for]:
                already = [a for a in override.tried if a != override.agent]
                if already:
                    line += f", tried: {', '.join(already)}"
            lines.append(line)
    return "\n".join(lines)
```

The `override.tried != [override.backup_for]` / `already` filtering exists so
a plain one-hop switch (where `tried` is just `[backup_for]`, i.e. the
original agent, which is already shown as `configured` earlier in the same
line) doesn't redundantly print `"tried: codex"` right after already saying
`"codex, currently grok"` -- `tried` is only interesting to show once it
holds *more* than the one obvious hop.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_preflight.py tests/test_roles.py -v`
Expected: PASS

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/whyline_relay/preflight.py src/whyline_relay/roles.py tests/test_preflight.py tests/test_roles.py
git commit -m "feat: doctor checks the backup chain; roles status shows tried history"
```

---

## Final check

After Task 7's commit, run the whole suite one more time (`uv run pytest -q`)
and confirm there is no remaining reference to `settings.backups`,
`settings.chat_backup`, `[roles.backup]`, or `[chat.backup]` anywhere in
`src/` (a plain `git grep -n "chat_backup\|\.backups\b\|roles\.backup\|chat\.backup"
-- src/` should return nothing). If it finds anything, that's a task this
plan missed -- fix it before considering the plan complete, and record why
via `whyline note`.
