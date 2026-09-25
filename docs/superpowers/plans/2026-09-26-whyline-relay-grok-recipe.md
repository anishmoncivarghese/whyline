# Grok Generic-Adapter Recipe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Document a real, empirically verified generic-adapter recipe for Grok (xAI's "Grok Build" CLI) in whyline-relay's README, mirroring the existing Antigravity section, and give `doctor` a Grok-specific warning when it's configured this way.

**Architecture:** No new Python module — this is a documentation-plus-one-small-preflight-branch piece, the same shape Antigravity's own generic recipe has. `bypass.py`'s binary-name-based guard already covers `grok` (shipped in a prior, independent fix); this plan only adds the `preflight.py` warning and the README content.

**Tech Stack:** Python 3.11+, stdlib only. No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-26-grok-generic-recipe-design.md`, sections 5.2-5.3. Phase 2 of that spec's two-repo build order; independent of phase 1 (`2026-09-26-whyline-grok-agent.md`, whyline's own `runner.py` changes) — either can ship first.

## Global Constraints

- No new runtime dependency.
- No new Python module — `adapters/grok.py` is explicitly out of scope (spec non-goals: the `model_flag`/`-p` ordering bug, no login-status check, generic denial text, no plan-tier field).
- `bypass.py`'s binary-name check already covers `grok` (a prior, independent fix) — nothing to change there.
- Every existing test must still pass after every task.

---

### Task 1: `preflight.py` — a Grok-specific generic-agent warning

**Files:**
- Modify: `src/whyline_relay/preflight.py`
- Test: `tests/test_preflight.py`

**Interfaces:**
- None new — `preflight.run`'s existing generic-agent warning check gains one more branch, alongside the existing Antigravity-specific one.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_preflight.py`:

```python
def test_grok_as_a_generic_agent_gets_a_specific_warning(ready_repo: Path, monkeypatch):
    target = ready_repo / ".whyline" / "relay" / "config.toml"
    target.write_text(
        '[roles]\nreviewer = "grok"\n'
        f'[agents.codex]\ncommand = ["{sys.executable}", "codex-role"]\n'
        '[agents.grok]\nadapter = "generic"\ncommand = ["grok", "-p"]\n'
    )
    monkeypatch.setattr(
        preflight.shutil,
        "which",
        lambda name: f"/bin/{name}" if name == "grok" else name,
    )
    checks = preflight.run(ready_repo, allow_dirty=True, runner=successful_runner())
    matches = [c for c in checks if "grok" in c.message and c.status == "warn"]
    assert len(matches) == 1
    # "login" alone isn't distinctive enough to prove this -- the old, generic
    # message ("...permissions, login or denials") already contains it. Check
    # for text unique to the new, grok-specific wording instead.
    assert "non-interactive" in matches[0].message


def test_a_non_grok_non_antigravity_generic_agent_keeps_the_original_message(
    ready_repo: Path, monkeypatch
):
    # Regression proof: adding grok's own branch must not change the message
    # any other generic agent (here, "aider") still gets.
    target = ready_repo / ".whyline" / "relay" / "config.toml"
    target.write_text(
        '[roles]\nreviewer = "aider"\n'
        f'[agents.codex]\ncommand = ["{sys.executable}", "codex-role"]\n'
        '[agents.aider]\nadapter = "generic"\ncommand = ["aider", "--message"]\n'
    )
    monkeypatch.setattr(
        preflight.shutil,
        "which",
        lambda name: f"/bin/{name}" if name == "aider" else name,
    )
    checks = preflight.run(ready_repo, allow_dirty=True, runner=successful_runner())
    matches = [c for c in checks if "aider is a generic agent" in c.message]
    assert matches == [
        preflight.Check(
            "warn",
            "aider is a generic agent: the relay does not manage its permissions, login or denials",
        )
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_preflight.py -k grok -v`
Expected: `-k grok` matches both new tests (the second one's name, `test_a_non_grok_non_antigravity_...`,
contains "grok" as a substring too) — 1 failed, 1 passed. `test_grok_as_a_generic_agent_gets_a_specific_warning`
FAILS: Grok currently falls into the generic `elif adapter.name == "generic":` branch, whose message
("grok is a generic agent: the relay does not manage its permissions, login or denials") does not
contain "non-interactive". `test_a_non_grok_non_antigravity_generic_agent_keeps_the_original_message`
PASSES already — it's a regression proof for behavior this task doesn't change.

- [ ] **Step 3: Implement**

In `src/whyline_relay/preflight.py`, change:

```python
        if adapter.name == "generic" and agent == "antigravity":
            checks.append(
                _result(
                    "warn",
                    "antigravity is a generic agent, and its headless permission "
                    "enforcement is known to be unreliable -- see README, 'Using "
                    "Antigravity today', and "
                    "github.com/google-antigravity/antigravity-cli#548. The relay "
                    "does not manage its permissions, login or denials",
                )
            )
        elif adapter.name == "generic":
```

to:

```python
        if adapter.name == "generic" and agent == "antigravity":
            checks.append(
                _result(
                    "warn",
                    "antigravity is a generic agent, and its headless permission "
                    "enforcement is known to be unreliable -- see README, 'Using "
                    "Antigravity today', and "
                    "github.com/google-antigravity/antigravity-cli#548. The relay "
                    "does not manage its permissions, login or denials",
                )
            )
        elif adapter.name == "generic" and agent == "grok":
            checks.append(
                _result(
                    "warn",
                    "grok is a generic agent, and it has no non-interactive "
                    "login-status check or specific denial detail -- see README, "
                    "'Using Grok today'. The relay does not manage its "
                    "permissions, login or denials",
                )
            )
        elif adapter.name == "generic":
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_preflight.py -v`
Expected: PASS, all of them — including the existing `test_antigravity_as_a_generic_agent_gets_a_specific_warning` and `test_generic_agent_is_checked_and_warned_without_login` (using "aider"), both unaffected since Grok gets its own, separate `elif` branch.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/whyline_relay/preflight.py tests/test_preflight.py
git commit -m "feat: doctor gives grok a specific, actionable generic-agent warning"
```

---

### Task 2: README — document the verified Grok recipe

**Files:**
- Modify: `README.md`

**Interfaces:**
- None — documentation only.

- [ ] **Step 1: Update the README**

Find the existing "Using Antigravity (`agy`) today, via the generic adapter" section and add a new,
parallel section immediately after it (before "## Backup agents"):

````markdown
### Using Grok (`grok`, "Grok Build") today, via the generic adapter

xAI's Grok Build CLI (`grok`) has genuinely better headless-mode fundamentals than Antigravity did when it was added — real per-invocation `--allow`/`--deny` permission flags, not one file global to the machine — verified directly: a full realistic implement turn (editing a file, *creating* a new one, running a verification command, recording a real `whyline note`, committing) and a full realistic reviewer turn (reading a diff, summarizing it accurately) both completed correctly with the recipe below, and an explicit `--deny` rule correctly beat a broader `--allow` for the same command, even with a project's own `.claude/settings.local.json` separately allowing it. It is still not a built-in, on purpose: `grok login` only ever starts a live device-code OAuth flow (there is no read-only status check `doctor` could run), and a denied action only reports `stopReason: "cancelled"`, never which command or file it needed — the same two gaps that keep Antigravity a generic agent too. Configure it like this:

```toml
[roles]
implementer = "codex"   # or reviewer; either role works
reviewer    = "grok"

[agents.grok]
adapter = "generic"
command = [
  "grok", "--output-format", "json", "--permission-mode", "dontAsk",
  "--deny", "Bash(git push:*)", "--deny", "Bash(rm -rf:*)",
  "--allow", "Edit", "--allow", "Bash(git add:*)", "--allow", "Bash(git commit:*)",
  "--allow", "Bash(git diff:*)", "--allow", "Bash(git status:*)", "--allow", "Bash(git log:*)",
  "--allow", "Bash(whyline:*)", "--allow", "Bash(python3:*)",
  "-p"
]
```

**`-p` must be the last item in the command**, for the same reason as Antigravity's own recipe: the relay always appends the prompt as the command's final argument, and `grok -p` greedily consumes whatever token comes right after it.

**`Edit` alone covers creating new files, not just editing existing ones** — verified directly, so there is no need to also grant a separate `Write` rule for ordinary implementation work.

**Swap `Bash(python3:*)` for your own stack's test command** (`Bash(npm test:*)`, etc.) — this is a hand-written recipe, not a stack-aware built-in adapter; adjust the allow-list for your project yourself.

**A generic agent can't take a configured `model` at all** — put a model flag directly in `command` yourself if you want one pinned, the same rule every generic agent already follows.

**Not yet tested: a logged-out or first-run session might hang** rather than failing promptly, since there is no login-status check to catch this ahead of time and the relay's own subprocess call inherits stdin. Left as a known, unverified risk rather than assumed safe.
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document a verified generic-adapter recipe for grok"
```

## Not in this plan

- **A managed `adapters/grok.py`** — explicitly out of scope (spec non-goals): the `model_flag`/`-p`
  ordering incompatibility needs its own architectural fix first, and there is no login-status check
  or specific denial detail to build `Manages(True, True, True)`-level guarantees on.
- **Failover/backup-agent support for Grok** — requires the login check above.
- **A Grok-specific rate-limit marker** — explicitly deferred per all three consultants: do not add
  one without a captured real 429 response body.
- **whyline's own `runner.py` support for Grok** — a separate plan,
  `2026-09-26-whyline-grok-agent.md`, independent of this one shipping first.
