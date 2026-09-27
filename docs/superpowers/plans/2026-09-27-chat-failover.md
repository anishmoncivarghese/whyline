# Chat Automatic Failover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `whyline chat` automatically retries a rate-limited or logged-out agent's turn on a configured backup, once, and stays on that backup (sticky) until reset — reusing the proven implementer/reviewer failover mechanism, generalized to chat's own by-name addressing.

**Architecture:** Generalize `failover.py`'s existing storage/read/write functions to take an explicit storage path (backward compatible — every existing pipeline call site is unaffected), add a chat-specific storage file and resolver function, add a `[chat.backup]` config table, and wire the resolve→run→detect→retry flow into `chat.py`'s `run_turn`, plus two new meta-commands in `repl()`.

**Tech Stack:** Python 3.11+, stdlib only (`datetime` for the override timestamp). No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-27-chat-failover-design.md`

## Global Constraints

- No new runtime dependency.
- Every existing pipeline-side call to `failover.path`/`read_overrides`/`write_override`/`clear_overrides` must keep working with no changes to those call sites — the new parameters are optional and default to today's behavior.
- Failover is one hop only: a turn already running on a backup that also fails is reported and stopped, never chased further.
- `chat.json`'s saved `default_agent` is never rewritten by failover — the active backup lives in a separate file.
- Every existing test must still pass after every task.

---

### Task 1: `failover.py` — a generalized, explicit storage path

**Files:**
- Modify: `src/whyline_relay/failover.py`
- Test: `tests/test_failover.py`

**Interfaces:**
- Produces: `failover.path(root, filename="active-roles.json") -> Path`. `failover.chat_path(root) -> Path` (returns `path(root, "chat-active-agents.json")`). `failover.read_overrides(root, storage_path=None) -> dict[str, ActiveOverride]`. `failover.write_override(root, role, override, storage_path=None) -> None`. `failover.clear_overrides(root, role=None, storage_path=None) -> int`. `failover.resolve_chat_agent(root, requested: str) -> str` (new — chat's own counterpart to `effective_agent`, with no `settings.roles` fallback). All four generalized functions behave exactly as before when `storage_path` (or `filename`, for `path`) is omitted.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_failover.py`:

```python
def test_chat_path_is_separate_from_the_pipeline_path(tmp_path):
    assert failover.chat_path(tmp_path) != failover.path(tmp_path)
    assert failover.chat_path(tmp_path).name == "chat-active-agents.json"


def test_writing_to_the_chat_path_does_not_touch_the_pipeline_file(tmp_path):
    failover.write_override(
        tmp_path, "claude",
        failover.ActiveOverride("codex", "claude", "rate-limit", "t"),
        storage_path=failover.chat_path(tmp_path),
    )
    assert failover.read_overrides(tmp_path) == {}
    assert failover.read_overrides(tmp_path, failover.chat_path(tmp_path)) == {
        "claude": failover.ActiveOverride("codex", "claude", "rate-limit", "t")
    }


def test_clear_overrides_respects_an_explicit_storage_path(tmp_path):
    chat_file = failover.chat_path(tmp_path)
    failover.write_override(
        tmp_path, "claude",
        failover.ActiveOverride("codex", "claude", "rate-limit", "t"),
        storage_path=chat_file,
    )
    failover.write_override(
        tmp_path, "implementer",
        failover.ActiveOverride("claude", "codex", "auth", "t"),
    )
    removed = failover.clear_overrides(tmp_path, storage_path=chat_file)
    assert removed == 1
    assert failover.read_overrides(tmp_path, chat_file) == {}
    assert "implementer" in failover.read_overrides(tmp_path)


def test_resolve_chat_agent_returns_the_requested_name_with_no_override(tmp_path):
    assert failover.resolve_chat_agent(tmp_path, "claude") == "claude"


def test_resolve_chat_agent_returns_the_backup_when_overridden(tmp_path):
    failover.write_override(
        tmp_path, "claude",
        failover.ActiveOverride("codex", "claude", "rate-limit", "t"),
        storage_path=failover.chat_path(tmp_path),
    )
    assert failover.resolve_chat_agent(tmp_path, "claude") == "codex"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_failover.py -k "chat_path or resolve_chat_agent or explicit_storage_path or does_not_touch" -v`
Expected: FAIL — `failover.chat_path`/`failover.resolve_chat_agent` do not exist, and `write_override`/`read_overrides`/`clear_overrides` do not accept `storage_path`.

- [ ] **Step 3: Implement**

In `src/whyline_relay/failover.py`, replace:

```python
def path(root: Path) -> Path:
    return config.relay_dir(root) / "active-roles.json"


def read_overrides(root: Path) -> dict[str, ActiveOverride]:
    try:
        raw = json.loads(path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    fields = ("agent", "backup_for", "reason", "since")
    result: dict[str, ActiveOverride] = {}
    for role, record in raw.items():
        if isinstance(record, dict) and all(
            isinstance(record.get(f), str) for f in fields
        ):
            result[role] = ActiveOverride(**{f: record[f] for f in fields})
    return result


def _write_all(root: Path, overrides: dict[str, ActiveOverride]) -> None:
    target = path(root)
    if not overrides:
        target.unlink(missing_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({r: asdict(o) for r, o in overrides.items()}, indent=2) + "\n",
        encoding="utf-8",
    )


def write_override(root: Path, role: str, override: ActiveOverride) -> None:
    overrides = read_overrides(root)
    overrides[role] = override
    _write_all(root, overrides)


def clear_overrides(root: Path, role: str | None = None) -> int:
    """Remove the override for `role`, or every override if `role` is None. Returns the count removed."""
    overrides = read_overrides(root)
    if role is None:
        removed = len(overrides)
        overrides = {}
    elif role in overrides:
        del overrides[role]
        removed = 1
    else:
        removed = 0
    _write_all(root, overrides)
    return removed
```

with:

```python
def path(root: Path, filename: str = "active-roles.json") -> Path:
    return config.relay_dir(root) / filename


def chat_path(root: Path) -> Path:
    """Chat's own override file -- separate from the pipeline's, since a
    custom pipeline can name a role after an agent (role = "claude"), which
    would collide with chat's key (the agent literally called claude) if
    they shared one file."""
    return path(root, "chat-active-agents.json")


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
    fields = ("agent", "backup_for", "reason", "since")
    result: dict[str, ActiveOverride] = {}
    for role, record in raw.items():
        if isinstance(record, dict) and all(
            isinstance(record.get(f), str) for f in fields
        ):
            result[role] = ActiveOverride(**{f: record[f] for f in fields})
    return result


def _write_all(
    root: Path,
    overrides: dict[str, ActiveOverride],
    storage_path: Path | None = None,
) -> None:
    target = storage_path if storage_path is not None else path(root)
    if not overrides:
        target.unlink(missing_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({r: asdict(o) for r, o in overrides.items()}, indent=2) + "\n",
        encoding="utf-8",
    )


def write_override(
    root: Path,
    role: str,
    override: ActiveOverride,
    storage_path: Path | None = None,
) -> None:
    overrides = read_overrides(root, storage_path)
    overrides[role] = override
    _write_all(root, overrides, storage_path)


def clear_overrides(
    root: Path, role: str | None = None, storage_path: Path | None = None
) -> int:
    """Remove the override for `role`, or every override if `role` is None. Returns the count removed."""
    overrides = read_overrides(root, storage_path)
    if role is None:
        removed = len(overrides)
        overrides = {}
    elif role in overrides:
        del overrides[role]
        removed = 1
    else:
        removed = 0
    _write_all(root, overrides, storage_path)
    return removed


def resolve_chat_agent(root: Path, requested: str) -> str:
    """The agent actually addressed right now for `requested`: its backup if
    switched, else `requested` unchanged. Chat's own counterpart to
    effective_agent() -- there is no settings.roles to fall back to here,
    since chat addresses agents by name directly, not by role."""
    override = read_overrides(root, chat_path(root)).get(requested)
    return override.agent if override is not None else requested
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_failover.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/failover.py tests/test_failover.py
git commit -m "feat: failover storage takes an explicit path, plus a chat resolver"
```

---

### Task 2: `config.py` — the `[chat.backup]` table

**Files:**
- Modify: `src/whyline_relay/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `Config.chat_backup: dict[str, str]` (default `{}`). Validated the same way `[roles.backup]` already is.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`:

```python
def test_no_chat_backup_table_means_no_chat_backups(tmp_path):
    write(tmp_path, "")
    assert config.load(tmp_path).chat_backup == {}


def test_a_chat_backup_is_parsed(tmp_path):
    write(tmp_path, '[chat.backup]\nclaude = "codex"\n')
    assert config.load(tmp_path).chat_backup == {"claude": "codex"}


def test_a_chat_backup_may_be_a_configured_generic_agent(tmp_path):
    write(
        tmp_path,
        '[chat.backup]\nclaude = "aider"\n[agents.aider]\n'
        'adapter = "generic"\ncommand = ["aider"]\n',
    )
    assert config.load(tmp_path).chat_backup == {"claude": "aider"}


def test_a_chat_backup_naming_itself_is_refused(tmp_path):
    write(tmp_path, '[chat.backup]\nclaude = "claude"\n')
    with pytest.raises(config.ConfigError, match="cannot be the same as its own agent"):
        config.load(tmp_path)


def test_a_chat_backup_naming_an_unknown_agent_is_refused(tmp_path):
    write(tmp_path, '[chat.backup]\nclaude = "gemini"\n')
    with pytest.raises(
        config.ConfigError,
        match="not a built-in agent .* or a configured generic agent",
    ):
        config.load(tmp_path)


def test_a_non_string_chat_backup_is_refused(tmp_path):
    write(tmp_path, "[chat.backup]\nclaude = 3\n")
    with pytest.raises(
        config.ConfigError, match="\\[chat.backup\\] claude must be a string"
    ):
        config.load(tmp_path)


def test_chat_backup_works_alongside_a_configured_pipeline(tmp_path):
    write(tmp_path, PIPELINE_TOML + '\n[chat.backup]\nclaude = "codex"\n')
    loaded = config.load(tmp_path)
    assert loaded.chat_backup == {"claude": "codex"}
    assert loaded.pipeline is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -k chat_backup -v`
Expected: FAIL — `Config` has no `chat_backup` attribute, and `[chat.backup]` is silently ignored (no validation exists yet).

- [ ] **Step 3: Implement**

In `src/whyline_relay/config.py`, add `chat_backup` to the `Config` dataclass. Change:

```python
@dataclass(frozen=True)
class Config:
    plan: str
    max_rounds: int
    timeout_minutes: int
    branch_prefix: str
    agents: dict[str, list[str]]
    status_map: dict[str, str]
    roles: Roles = field(default_factory=Roles)
    adapters: dict[str, str] = field(default_factory=dict)
    backups: dict[str, str] = field(default_factory=dict)
    pipeline: "pipeline_module.Pipeline | None" = None
    pipeline_fingerprint: str = ""
    planner: PlannerConfig = field(default_factory=PlannerConfig)
```

to:

```python
@dataclass(frozen=True)
class Config:
    plan: str
    max_rounds: int
    timeout_minutes: int
    branch_prefix: str
    agents: dict[str, list[str]]
    status_map: dict[str, str]
    roles: Roles = field(default_factory=Roles)
    adapters: dict[str, str] = field(default_factory=dict)
    backups: dict[str, str] = field(default_factory=dict)
    pipeline: "pipeline_module.Pipeline | None" = None
    pipeline_fingerprint: str = ""
    planner: PlannerConfig = field(default_factory=PlannerConfig)
    chat_backup: dict[str, str] = field(default_factory=dict)
```

In `load()`, find the section that parses `[roles.backup]` (it ends right before
`compiled_pipeline = None` in the non-pipeline branch, and the whole
`if raw_pipeline is not None: ... else: ...` block ends before
`raw_planner = raw.get("planner") or {}`). Add the new parsing block
immediately after that whole `if/else` block, before the `raw_planner` line:

```python
    raw_chat = raw.get("chat") or {}
    chat_backup_raw = raw_chat.get("backup") or {}
    chat_backup: dict[str, str] = {}
    for key, value in chat_backup_raw.items():
        if not isinstance(value, str):
            raise ConfigError(f"[chat.backup] {key} must be a string")
        if value == key:
            raise ConfigError(
                f"[chat.backup] {key} cannot be the same as its own agent"
            )
        if value not in adapters.BUILTIN and value not in configured_adapters:
            builtins = ", ".join(sorted(adapters.BUILTIN))
            raise ConfigError(
                f"[chat.backup] {key} names '{value}', which is not a built-in "
                f"agent ({builtins}) or a configured generic agent"
            )
        chat_backup[key] = value

    raw_planner = raw.get("planner") or {}
```

Finally, add `chat_backup=chat_backup` to the `Config(...)` constructor call
at the end of `load()`:

```python
    return Config(
        plan=raw.get("plan", DEFAULTS["plan"]),
        max_rounds=int(raw.get("max_rounds", DEFAULTS["max_rounds"])),
        timeout_minutes=int(raw.get("timeout_minutes", DEFAULTS["timeout_minutes"])),
        branch_prefix=raw.get("branch_prefix", DEFAULTS["branch_prefix"]),
        agents=agents,
        status_map=status_map,
        roles=roles_obj,
        adapters=configured_adapters,
        backups=dict(backup_values),
        pipeline=compiled_pipeline,
        pipeline_fingerprint=pipeline_fp,
        planner=planner_cfg,
        chat_backup=chat_backup,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/config.py tests/test_config.py
git commit -m "feat: a [chat.backup] table, independent of [pipeline]/[roles.backup]"
```

---

### Task 3: `chat.py` — the failover-aware turn pipeline

**Files:**
- Modify: `src/whyline_relay/chat.py`
- Test: `tests/test_chat_turn.py`

**Interfaces:**
- Consumes: `failover.resolve_chat_agent`, `failover.failover_reason`, `failover.write_override`, `failover.read_overrides`, `failover.chat_path`, `failover.ActiveOverride`, `failover.pause_message`, `failover.REASON_TEXT` (Task 1); `Config.chat_backup` (Task 2).
- Produces: `chat.run_turn(...)`'s returned record gains an optional `"failover_notice": str` key, present only when a switch happened or a backup also failed. `run_turn` gains a new `runner=subprocess.run` keyword parameter (threaded to `failover.failover_reason`'s own `runner`, so a test can substitute a fake one instead of ever invoking a real login-status subprocess). Every other part of `run_turn`'s signature and return value is unchanged.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_chat_turn.py`:

```python
def test_run_turn_switches_to_the_backup_and_retries_automatically(tmp_path: Path):
    _init_repo(tmp_path)
    relay = tmp_path / ".whyline" / "relay"
    relay.mkdir(parents=True, exist_ok=True)
    (relay / "config.toml").write_text('[chat.backup]\nclaude = "codex"\n')
    settings = config.load(tmp_path)

    calls = []

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult
        calls.append(command[0])
        if command[0] == "claude":
            return RunResult(1, "You have exceeded your usage limit. Try again later.")
        return RunResult(0, '{"type":"result","result":"pong from backup"}\n')

    # codex's own "pong from backup" response has no rate-limit marker, so
    # the post-retry failover_reason check falls through to a login-status
    # re-check -- fake the subprocess runner so this never shells out for
    # real. "still logged in" is returncode 0, matching still_logged_in()'s
    # own check.
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


def test_run_turn_reports_and_stops_when_the_backup_also_fails(tmp_path: Path):
    _init_repo(tmp_path)
    relay = tmp_path / ".whyline" / "relay"
    relay.mkdir(parents=True, exist_ok=True)
    (relay / "config.toml").write_text('[chat.backup]\nclaude = "codex"\n')
    settings = config.load(tmp_path)

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult
        return RunResult(1, "You have exceeded your usage limit. Try again later.")

    record = chat.run_turn(
        tmp_path, agent="claude", prompt="ping", settings=settings, run_fn=fake_run_fn
    )
    assert record["agent"] == "codex"
    assert "also" in record["failover_notice"]
    assert "hit a usage or rate limit" in record["failover_notice"]


def test_run_turn_uses_an_already_active_backup_silently(tmp_path: Path):
    _init_repo(tmp_path)
    relay = tmp_path / ".whyline" / "relay"
    relay.mkdir(parents=True, exist_ok=True)
    (relay / "config.toml").write_text('[chat.backup]\nclaude = "codex"\n')
    settings = config.load(tmp_path)
    from whyline_relay import failover

    failover.write_override(
        tmp_path, "claude",
        failover.ActiveOverride("codex", "claude", "rate-limit", "2026-01-01T00:00:00"),
        storage_path=failover.chat_path(tmp_path),
    )

    calls = []

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult
        calls.append(command[0])
        return RunResult(0, '{"type":"result","result":"pong"}\n')

    # codex's response has no rate-limit marker, so the already-on-a-backup
    # branch's failover_reason check falls through to a login-status
    # re-check -- fake the runner so this never shells out for real.
    fake_login_ok = lambda *a, **k: subprocess.CompletedProcess(a, 0, "", "")

    record = chat.run_turn(
        tmp_path, agent="claude", prompt="ping", settings=settings,
        run_fn=fake_run_fn, runner=fake_login_ok,
    )
    assert calls == ["codex"]
    assert record["agent"] == "codex"
    assert "failover_notice" not in record


def test_run_turn_with_no_backup_configured_behaves_exactly_as_before(tmp_path: Path):
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chat_turn.py -k "backup" -v`
Expected: FAIL — `run_turn` never checks `[chat.backup]` or retries; every new
test's `record["agent"]` comes back as the originally requested agent
(`"claude"`), never `"codex"`, and `"failover_notice"` never appears.

- [ ] **Step 3: Implement**

In `src/whyline_relay/chat.py`, add `subprocess` and `datetime`/`timezone` to
the stdlib imports and `failover` to the `whyline_relay` import line:

```python
import subprocess
from datetime import datetime, timezone
```

```python
from whyline_relay import adapters, agents, chatlog, config, failover, gitcheck, init, invocation
```

`subprocess` is needed only for `run_turn`'s new `runner=subprocess.run`
default -- the same threading pattern `loop.py` already uses so a test can
substitute a fake runner instead of ever invoking a real login-status
subprocess (`codex login status`, `claude auth status`).

Replace the whole `run_turn` function:

```python
def run_turn(
    root: Path,
    *,
    agent: str,
    prompt: str,
    settings: "config.Config | None" = None,
    run_fn=None,
) -> dict:
    settings = settings if settings is not None else config.load(root)
    run_fn = run_fn if run_fn is not None else agents.run
    command = resolve_command(settings, agent)
    adapter = config.adapter_for(settings, agent)
    if _ensure_permission_files(root, agent):
        # Committed on its own, before the turn -- so the turn's own
        # diff-stat/files_changed reflects only what the agent did, not
        # one-time setup init would normally have already done.
        gitcheck.commit_all(root, f"chat: generate {agent}'s permission settings")
    full_prompt = _build_prompt(root, prompt)
    turn_command = list(command)
    output_file: Path | None = None
    if adapter.uses_output_file:
        handle = tempfile.NamedTemporaryFile(
            prefix="whyline-relay-chat-", suffix=".txt", delete=False
        )
        output_file = Path(handle.name)
        handle.close()
        turn_command += ["-o", str(output_file)]
    log_path = config.relay_dir(root) / "logs" / "chat-last-turn.log"
    result = run_fn(
        turn_command,
        full_prompt,
        cwd=root,
        log_path=log_path,
        timeout_seconds=CHAT_TIMEOUT_SECONDS,
        capture=True,
        echo=True,
        agent_name=agent,
    )
    if adapter.uses_output_file:
        raw = output_file.read_text(encoding="utf-8") if output_file.exists() else ""
    else:
        raw = result.output or ""
    response = adapter.extract_response(raw)
    ok = result.exit_code == 0
    rate_limited = agents.rate_limited(raw)
    # commit_all stages everything and no-ops (returns False) when the tree
    # is already clean -- safe to call unconditionally rather than checking
    # is_dirty first, and it's the only reliable way to see a brand-new
    # untracked file in the resulting stat (git diff on the working tree
    # never shows untracked files; the committed diff always does).
    committed = gitcheck.commit_all(root, f"chat: {agent} turn")
    diff_stat = gitcheck.commit_stat(root) if committed else ""
    files_changed = max(len(diff_stat.splitlines()) - 1, 0) if diff_stat else 0
    # append generates the timestamp and returns the record it persisted.
    # rate_limited and diff_stat are return-only, so they are added after
    # the write and never become part of the chatlog line.
    record = chatlog.append(
        root, agent=agent, prompt=prompt, response=response,
        files_changed=files_changed, ok=ok,
    )
    record["rate_limited"] = rate_limited
    if committed:
        record["diff_stat"] = diff_stat
    return record
```

with:

```python
def _execute_agent_call(
    root: Path, agent: str, prompt: str, full_prompt: str,
    settings: "config.Config", run_fn,
) -> dict:
    """Runs one attempt against `agent`. No chatlog write, no failover
    logic -- run_turn decides, after seeing the result, whether this was
    the whole story or whether a backup needs a turn too."""
    command = resolve_command(settings, agent)
    adapter = config.adapter_for(settings, agent)
    if _ensure_permission_files(root, agent):
        gitcheck.commit_all(root, f"chat: generate {agent}'s permission settings")
    turn_command = list(command)
    output_file: Path | None = None
    if adapter.uses_output_file:
        handle = tempfile.NamedTemporaryFile(
            prefix="whyline-relay-chat-", suffix=".txt", delete=False
        )
        output_file = Path(handle.name)
        handle.close()
        turn_command += ["-o", str(output_file)]
    log_path = config.relay_dir(root) / "logs" / "chat-last-turn.log"
    result = run_fn(
        turn_command,
        full_prompt,
        cwd=root,
        log_path=log_path,
        timeout_seconds=CHAT_TIMEOUT_SECONDS,
        capture=True,
        echo=True,
        agent_name=agent,
    )
    if adapter.uses_output_file:
        raw = output_file.read_text(encoding="utf-8") if output_file.exists() else ""
    else:
        raw = result.output or ""
    response = adapter.extract_response(raw)
    ok = result.exit_code == 0
    committed = gitcheck.commit_all(root, f"chat: {agent} turn")
    diff_stat = gitcheck.commit_stat(root) if committed else ""
    files_changed = max(len(diff_stat.splitlines()) - 1, 0) if diff_stat else 0
    return {
        "raw": raw,
        "response": response,
        "ok": ok,
        "adapter": adapter,
        "command": turn_command,
        "committed": committed,
        "diff_stat": diff_stat,
        "files_changed": files_changed,
    }


def run_turn(
    root: Path,
    *,
    agent: str,
    prompt: str,
    settings: "config.Config | None" = None,
    run_fn=None,
    runner=subprocess.run,
) -> dict:
    settings = settings if settings is not None else config.load(root)
    run_fn = run_fn if run_fn is not None else agents.run
    requested = agent
    resolved = failover.resolve_chat_agent(root, requested)
    full_prompt = _build_prompt(root, prompt)

    attempt = _execute_agent_call(root, resolved, prompt, full_prompt, settings, run_fn)
    final_agent = resolved
    failover_notice: str | None = None

    if resolved == requested:
        # Check `chat_backup` *before* calling failover_reason: that call can
        # run a real login-status subprocess (via runner), and there is no
        # point spending it -- or risking a real, unmocked subprocess call in
        # a test that never configured [chat.backup] -- when there is no
        # backup to switch to anyway. This also means every pre-existing
        # chat test, none of which configure [chat.backup], never reaches
        # failover_reason at all: zero behavior change for them.
        backup = settings.chat_backup.get(requested)
        if backup:
            reason = failover.failover_reason(
                attempt["adapter"], attempt["raw"], attempt["command"], runner=runner
            )
            if reason:
                verb, _ = failover.REASON_TEXT[reason]
                failover_notice = f"{requested} {verb}; trying its backup, {backup}..."
                failover.write_override(
                    root,
                    requested,
                    failover.ActiveOverride(
                        agent=backup,
                        backup_for=requested,
                        reason=reason,
                        since=datetime.now(timezone.utc).isoformat(),
                    ),
                    storage_path=failover.chat_path(root),
                )
                attempt = _execute_agent_call(
                    root, backup, prompt, full_prompt, settings, run_fn
                )
                final_agent = backup
                reason2 = failover.failover_reason(
                    attempt["adapter"], attempt["raw"], attempt["command"],
                    runner=runner,
                )
                if reason2:
                    override = failover.read_overrides(
                        root, failover.chat_path(root)
                    ).get(requested)
                    failover_notice = failover.pause_message(
                        backup, requested, reason2, override
                    )
    else:
        # Already on an active backup (someone configured [chat.backup] for
        # `requested` at some point, and it already switched) -- detect a
        # further failure but never chase a third agent (one hop only).
        reason = failover.failover_reason(
            attempt["adapter"], attempt["raw"], attempt["command"], runner=runner
        )
        if reason:
            override = failover.read_overrides(root, failover.chat_path(root)).get(
                requested
            )
            failover_notice = failover.pause_message(
                resolved, requested, reason, override
            )

    rate_limited = agents.rate_limited(attempt["raw"])
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_chat_turn.py -v`
Expected: PASS, all of them — including every pre-existing test in this
file (`test_run_turn_generates_claude_settings_when_init_never_ran`,
`test_run_turn_never_overwrites_a_customized_claude_settings_file`, etc.),
none of which configure `[chat.backup]`, so `resolved == requested` always
and `_execute_agent_call` runs exactly once, matching the old inlined
behavior byte for byte.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/chat.py tests/test_chat_turn.py
git commit -m "feat: chat auto-retries a rate-limited or logged-out agent on its backup"
```

---

### Task 4: `chat.py` — `/backups` and `/reset-backup`

**Files:**
- Modify: `src/whyline_relay/chat.py`
- Test: `tests/test_chat_repl.py`

**Interfaces:**
- Consumes: `failover.read_overrides`, `failover.clear_overrides`, `failover.chat_path` (Task 1); `run_turn`'s `runner` parameter and `"failover_notice"` key (Task 3).
- Produces: `/backups` and `/reset-backup [agent]` recognized by `repl()`. `repl()` also prints `record["failover_notice"]` when present, and gains a `runner=None` keyword parameter threaded to `run_turn` (only when set, so `run_turn`'s own real default is preserved otherwise).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_chat_repl.py`:

```python
def test_repl_backups_command_reports_none_active(tmp_path: Path):
    root = _repo(tmp_path)
    chat.save_default_agent(root, "claude")
    lines = iter(["/backups", "/exit"])
    printed = []
    chat.repl(
        root,
        input_fn=lambda prompt="": next(lines),
        print_fn=lambda *a, **k: printed.append(" ".join(str(x) for x in a)),
        run_fn=_fake_run_fn,
        which=lambda name: "/bin/x",
    )
    assert any("no active" in line.lower() for line in printed)


def test_repl_backups_command_lists_an_active_override(tmp_path: Path):
    from whyline_relay import failover

    root = _repo(tmp_path)
    chat.save_default_agent(root, "claude")
    failover.write_override(
        root, "claude",
        failover.ActiveOverride("codex", "claude", "rate-limit", "2026-01-01T00:00:00"),
        storage_path=failover.chat_path(root),
    )
    lines = iter(["/backups", "/exit"])
    printed = []
    chat.repl(
        root,
        input_fn=lambda prompt="": next(lines),
        print_fn=lambda *a, **k: printed.append(" ".join(str(x) for x in a)),
        run_fn=_fake_run_fn,
        which=lambda name: "/bin/x",
    )
    assert any("claude" in line and "codex" in line for line in printed)


def test_repl_reset_backup_clears_one_agent(tmp_path: Path):
    from whyline_relay import failover

    root = _repo(tmp_path)
    chat.save_default_agent(root, "claude")
    failover.write_override(
        root, "claude",
        failover.ActiveOverride("codex", "claude", "rate-limit", "t"),
        storage_path=failover.chat_path(root),
    )
    lines = iter(["/reset-backup claude", "/backups", "/exit"])
    printed = []
    chat.repl(
        root,
        input_fn=lambda prompt="": next(lines),
        print_fn=lambda *a, **k: printed.append(" ".join(str(x) for x in a)),
        run_fn=_fake_run_fn,
        which=lambda name: "/bin/x",
    )
    assert failover.read_overrides(root, failover.chat_path(root)) == {}
    assert any("no active" in line.lower() for line in printed)


def test_repl_reset_backup_with_no_argument_clears_all(tmp_path: Path):
    from whyline_relay import failover

    root = _repo(tmp_path)
    chat.save_default_agent(root, "claude")
    failover.write_override(
        root, "claude",
        failover.ActiveOverride("codex", "claude", "rate-limit", "t"),
        storage_path=failover.chat_path(root),
    )
    failover.write_override(
        root, "codex",
        failover.ActiveOverride("grok", "codex", "auth", "t"),
        storage_path=failover.chat_path(root),
    )
    lines = iter(["/reset-backup", "/exit"])
    chat.repl(
        root,
        input_fn=lambda prompt="": next(lines),
        print_fn=lambda *a, **k: None,
        run_fn=_fake_run_fn,
        which=lambda name: "/bin/x",
    )
    assert failover.read_overrides(root, failover.chat_path(root)) == {}


def test_repl_prints_the_failover_notice_when_present(tmp_path: Path):
    import subprocess

    root = _repo(tmp_path)
    chat.save_default_agent(root, "claude")
    relay = root / ".whyline" / "relay"
    relay.mkdir(parents=True, exist_ok=True)
    (relay / "config.toml").write_text('[chat.backup]\nclaude = "codex"\n')

    def fake_run_fn(command, prompt, **kwargs):
        from whyline_relay.agents import RunResult
        if command[0] == "claude":
            return RunResult(1, "You have exceeded your usage limit. Try again later.")
        return RunResult(0, '{"type":"result","result":"pong"}\n')

    # codex's "pong" response has no rate-limit marker, so the post-retry
    # failover_reason check falls through to a login-status re-check -- fake
    # the subprocess runner so this never shells out for real.
    fake_login_ok = lambda *a, **k: subprocess.CompletedProcess(a, 0, "", "")

    lines = iter(["hello", "/exit"])
    printed = []
    chat.repl(
        root,
        input_fn=lambda prompt="": next(lines),
        print_fn=lambda *a, **k: printed.append(" ".join(str(x) for x in a)),
        run_fn=fake_run_fn,
        which=lambda name: "/bin/x",
        runner=fake_login_ok,
    )
    assert any("trying its backup" in line for line in printed)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chat_repl.py -k "backup" -v`
Expected: FAIL — `/backups` and `/reset-backup` are rejected as unknown
commands, and `repl()` never prints a `failover_notice`.

- [ ] **Step 3: Implement**

In `src/whyline_relay/chat.py`, add `failover` to the imports if Task 3
hasn't already (it has — this is the same import line).

Update `SLASH_COMMANDS`. Change:

```python
SLASH_COMMANDS = ("/default", "/agents", "/history", "/clear", "/exit")
```

to:

```python
SLASH_COMMANDS = (
    "/default", "/agents", "/history", "/clear", "/exit",
    "/backups", "/reset-backup",
)
```

`repl()` also needs to accept and thread through the same `runner` parameter
`run_turn` gained in Task 3, so a test can substitute a fake one. Change
`repl()`'s signature:

```python
def repl(
    root: Path,
    *,
    input_fn=None,
    print_fn=None,
    run_fn=None,
    which=None,
    setup_answers=None,
) -> None:
```

to:

```python
def repl(
    root: Path,
    *,
    input_fn=None,
    print_fn=None,
    run_fn=None,
    which=None,
    setup_answers=None,
    runner=None,
) -> None:
```

and its existing call to `run_turn` (inside the main loop, in the `try:`
block):

```python
            record = run_turn(
                root, agent=agent, prompt=prompt, settings=settings, run_fn=run_fn
            )
```

to:

```python
            record = run_turn(
                root, agent=agent, prompt=prompt, settings=settings, run_fn=run_fn,
                **({"runner": runner} if runner is not None else {}),
            )
```

(`run_turn`'s own default, `subprocess.run`, already covers the real case —
`repl()`'s own default stays `None` so a caller who doesn't pass one gets
`run_turn`'s real default rather than `repl()` silently re-binding
`subprocess.run` a second time.)

Add two new branches in `repl()`, right after the existing `/clear` branch
and before the `/default` branch:

```python
        if line == "/backups":
            overrides = failover.read_overrides(root, failover.chat_path(root))
            if not overrides:
                print_fn("No active backups.")
            for agent_name, override in overrides.items():
                print_fn(
                    f"{agent_name} -> {override.agent} "
                    f"({override.reason}, since {override.since})"
                )
            continue
        if line.startswith("/reset-backup"):
            parts = line.split(maxsplit=1)
            target = parts[1].strip() if len(parts) == 2 else None
            removed = failover.clear_overrides(
                root, role=target, storage_path=failover.chat_path(root)
            )
            print_fn(f"Cleared {removed} backup override(s).")
            continue
```

Finally, update the turn-result printing at the end of the loop to show
`failover_notice` when present. Change:

```python
        print_fn(f"[{record['agent']}] {record['response']}")
        if record["rate_limited"]:
            print_fn(
                f"{record['agent']} looks rate-limited -- "
                "/default another agent, or wait."
            )
        if record.get("diff_stat"):
            prefix = "" if record["ok"] else "⚠ "
            print_fn(f"{prefix}{record['diff_stat'].strip()}")
```

to:

```python
        if record.get("failover_notice"):
            print_fn(record["failover_notice"])
        print_fn(f"[{record['agent']}] {record['response']}")
        if record["rate_limited"]:
            print_fn(
                f"{record['agent']} looks rate-limited -- "
                "/default another agent, or wait."
            )
        if record.get("diff_stat"):
            prefix = "" if record["ok"] else "⚠ "
            print_fn(f"{prefix}{record['diff_stat'].strip()}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_chat_repl.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/chat.py tests/test_chat_repl.py
git commit -m "feat: /backups and /reset-backup, and show failover notices"
```

---

### Task 5: README — document chat's automatic backup

**Files:**
- Modify: `README.md`

**Interfaces:**
- None — documentation only.

- [ ] **Step 1: Update the README**

Find the "## Chat: talk to any configured agent from one terminal" section
(added for the chat REPL itself) and add a new paragraph immediately before
its worked example (the ` ```  $ whyline-relay chat ... ``` ` block):

````markdown
**Automatic backup, the same idea the implementer/reviewer pipeline has had
since 0.2.4:**

```toml
[chat.backup]
claude = "codex"
codex  = "grok"
# agy/grok have no backup here -- a rate limit or auth loss on them just
# reports and stops, exactly like today
```

When the agent you're addressing (default or `/prefix`) hits a detected
usage limit or stops being authenticated, chat writes an override, tells you
what happened, and immediately re-runs your exact message on the backup --
no retyping. The switch is sticky: every later turn addressing that same
agent name resolves straight to the backup, silently, until you
`/reset-backup [agent]` or `/default` to something else. `/backups` shows
what's currently active. One hop only -- if the backup also fails, chat
reports it and stops, the same "no further fallback" rule the pipeline's own
backup already follows.
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document chat's automatic backup"
```

## Not in this plan

- **Automatic backup for a custom `[pipeline]`'s roles** -- a separate,
  subsequent plan; `[roles.backup]` remains forbidden together with
  `[pipeline]`, unchanged by this plan.
- **The pipeline setup wizard** -- a separate, subsequent plan, built after
  this and the pipeline-failover piece so it can ask about backups from the
  start.
