# Relay guided flow v2: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This plan is run by whyline-relay with **antigravity implementing and claude reviewing**, one relay task per plan task. Tasks marked "(human)" are done by Claude or a person.

**Goal:** In Relay mode, "create a new plan" runs brainstorm → synthesis review → spec → plan, then the Roles step adds an automatic Committer and a Release role, and release tasks pause for the user to do and confirm.

**Architecture:** The engine (whyline-relay 0.2.31) gets:
- a `[roles] release` setting;
- a spec pipeline that shares the planner's machinery (a `_Kind` describing task id, files and prompts);
- `planner.draft(spec=...)` and `brainstorm.revise_synthesis`;
- the relay committing approved work in the older two-role format too;
- release pauses with `done`/`skip`.

The console (whyline 0.3.34) gets:
- staged outcomes in `plan_job` (synthesis, spec, plan);
- a brainstorm-first Plan form with a "Write a spec first" box;
- synthesis and spec review states in the main window;
- Committer and Release rows in the Roles step;
- a release state for `done`/`skip`.

**Tech Stack:** Python 3.11+, Textual 0.89.1, pytest + pytest-asyncio, `uv`, git.

**Spec:** `docs/superpowers/specs/2026-10-04-relay-guided-flow-v2-design.md`

## Global Constraints

- **Prerequisites:** whyline 0.3.33 (attachments) is released. Brainstorm and plan requests carry `attachments`, and `PlanRequest.refs` is already gone.
- whyline-relay is `~/whyline-relay` (Tasks 1–6); whyline is `~/agentdock` (Tasks 7–12).
- Relay roles while this plan runs: `implementer = "antigravity"`, `reviewer = "claude"`. Claude needs `.whyline/relay/claude-settings.json`; the relay creates it.
- Release values are `"human"` or an agent name. The default is `"human"`.
- Spec files are `docs/specs/<slug>.md`. The spec draft is `.whyline/relay/draft-spec.md`; its checkpoint is `.whyline/relay/spec-state.json`. The task id is `__spec__`.
- Commit message for the relay's own commit: `<type>: <summary> (<TASK-ID>)`.
  - `<type>` comes from the summary when it already starts with `feat|fix|docs|test|chore|refactor` followed by `:`.
  - Otherwise it's the task title's first word when that is one of `fix`, `docs`, `test`, `chore` or `refactor` (case-insensitive).
  - Otherwise `feat`.
  - The summary is the first sentence, at most 72 characters.
- The release pause reason starts with exactly `release task for you: <TASK-ID>`.
- Tests must not depend on installed agent CLIs, must not touch the real home folder, and must pass on Windows (paths compared via `Path`, shown via `.as_posix()`). Console layouts fit 80 columns.
- After each task: `whyline note "<decision>" --because "<why>" --file <path> --actor <agent> --role implementer --task FV2-<n>`.
- Never push, tag, bump versions or publish inside a task; Tasks 6 and 12 are releases (human).

## Review Focus

- **A repository whose `.whyline/relay/prompts/review.md` still says "commit".** The reviewer commits and the relay must not commit a second time; the task still ticks. Pinned in Task 4.
- **`[roles] release = "human"` in a config with a `[pipeline]` table.** "human" is not an agent and must not fail role validation. Pinned in Task 1.
- **A spec draft and a plan draft in progress at the same time.** Neither may overwrite the other's checkpoint or draft. Pinned in Task 2.
- **`whyline relay done RPF-9` when the pause is for RPF-17.** Refused, naming RPF-17. Pinned in Task 5.
- **Approving a spec, then the plan job failing.** The spec is already committed and stays; Plan → Resume continues the plan, not the spec. Pinned in Task 10.

---

# whyline-relay 0.2.31 (Tasks 1–6)

Before Task 1: `cd ~/whyline-relay && git switch main && git pull --ff-only && uv run pytest -q`. The suite should pass.

### Task 1: `[roles] release` in the config, and `setup.write_release`

**Files:** Modify `src/whyline_relay/config.py`, `src/whyline_relay/setup.py`. Test `tests/test_release_role.py` (create).

**Interfaces:** `Config.release_role: str = "human"`; `setup.write_release(root, value: str, *, commit=True) -> Path`.

- [ ] **Step 1: Failing tests**

```python
from pathlib import Path

import pytest

from whyline_relay import config, setup


def _write(root: Path, text: str) -> None:
    p = root / ".whyline/relay/config.toml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_default_release_role_is_human(tmp_path):
    assert config.load(tmp_path).release_role == "human"


@pytest.mark.parametrize("roles", [
    '[roles]\nimplementer = "codex"\nreviewer = "claude"\nrelease = "human"\n',
    '[roles]\nimplementer = "codex"\ntester = "claude"\nreviewer = "claude"\nrelease = "human"\n'
    '[pipeline]\ndefault_profile = "full"\n[pipeline.profiles]\nfull = ["draft", "review"]\n'
    '[pipeline.stages.draft]\nrole = "implementer"\nprompt = "implement"\n[pipeline.stages.draft.on]\n'
    'ready = "@next"\n[pipeline.stages.review]\nrole = "reviewer"\nprompt = "review"\n'
    '[pipeline.stages.review.on]\napproved = "@complete"\nrejected = "draft"\n',
])
def test_human_release_loads_in_both_formats(tmp_path, roles):
    _write(tmp_path, roles)
    assert config.load(tmp_path).release_role == "human"


def test_release_can_be_an_agent_but_not_nonsense(tmp_path):
    _write(tmp_path, '[roles]\nimplementer = "codex"\nreviewer = "claude"\nrelease = "grok"\n')
    assert config.load(tmp_path).release_role == "grok"
    _write(tmp_path, '[roles]\nimplementer = "codex"\nreviewer = "claude"\nrelease = "bob"\n')
    with pytest.raises(config.ConfigError, match="release"):
        config.load(tmp_path)


def test_write_release_keeps_everything_else(tmp_path):
    _write(tmp_path, 'max_rounds = 6\n[roles]\nimplementer = "codex"\nreviewer = "claude"\n')
    setup.write_release(tmp_path, "codex", commit=False)
    loaded = config.load(tmp_path)
    assert (loaded.release_role, loaded.max_rounds, loaded.roles.implementer) == ("codex", 6, "codex")
```

- [ ] **Step 2: Run and see them fail** (`uv run pytest tests/test_release_role.py -q`). Expected: `AttributeError: 'Config' object has no attribute 'release_role'`.

- [ ] **Step 3: Implement**

In `config.load`:
- Change `role_values = raw.get("roles") or {}` to `role_values = dict(raw.get("roles") or {})`.
- Directly after that, add:

```python
    release_role = role_values.pop("release", "human")
    if not isinstance(release_role, str) or not release_role:
        raise ConfigError('[roles] release must be "human" or an agent name')
```

- After `configured_adapters` is complete (after the recipes loop), validate it:

```python
    if release_role != "human" and release_role not in adapters.BUILTIN \
            and release_role not in configured_adapters:
        raise ConfigError(f'[roles] release must be "human" or a known agent, not {release_role!r}')
```

- Add `release_role: str = "human"` as the **last** field of `Config`, and pass `release_role=release_role` in the `return Config(...)`.

In `setup.py`:

```python
def write_release(root: Path, value: str, *, commit: bool = True) -> Path:
    """Who does the plan's release tasks: "human" (the default) or an agent."""
    return _write_config(
        root, lambda text: _set_keys(text, "roles", {"release": value}),
        f"setup: release tasks by {value}", commit,
    )
```

`write_roles` keeps an existing `release` key in both branches. In the pipeline branch, `_set_keys` only touches implementer, tester and reviewer. In the template branch, `[roles]` is rebuilt, so before replacing it, read `old.get("roles", {}).get("release")` and, when present, call `content = _set_keys(content, "roles", {"release": that})` after the template is assembled. Add a test: `write_roles` on a config with `release = "codex"` keeps it.

- [ ] **Step 4: Run** `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: release role in the relay config (FV2-1)`.

### Task 2: The spec pipeline (shared planner machinery)

**Files:** Modify `src/whyline_relay/planner.py`, `src/whyline_relay/state.py`, `src/whyline_relay/prompts.py`, `src/whyline_relay/gitcheck.py`. Create `src/whyline_relay/specs.py`. Test `tests/test_specs.py`.

**Interfaces:**
- `planner._Kind(task_id, draft_name, state_name, draft_prompt, review_prompt)`, with `PLAN_KIND` and `SPEC_KIND`.
- `state.save_plan`, `load_plan` and `clear_plan` gain `name: str = "plan-state.json"`.
- `specs.SpecQuestions = planner.PlanQuestions`, the same class, so the console catches one type.
- `specs.draft(root, settings, request, *, attachments=(), print_fn=None) -> Path`, plus `revise`, `resume_draft`, `answer`, `discard`, `pending_description`, `draft_path(root)`, and `approve(root, draft_path, *, name, replace=False) -> Path`.

- [ ] **Step 1: Failing tests** (reuse `tests/test_planner.py`'s `repo`, `settings_with_planner` and `_scripted_run`, as `tests/test_planner_questions.py` does):

```python
import pytest

from whyline_relay import loop, planner, specs, state
from tests.test_planner import _scripted_run, repo, settings_with_planner  # noqa: F401


def test_spec_draft_review_then_approve_commits_only_the_spec(repo, monkeypatch):
    import subprocess

    settings = settings_with_planner(repo)
    monkeypatch.setattr(loop.agents, "run", _scripted_run(["claude:ready", "claude:approved"]))
    path = specs.draft(repo, settings, "Build the thing")
    assert path == repo / ".whyline/relay/draft-spec.md"
    path.write_text("# Spec\n\n## Why\nBecause.\n")
    target = specs.approve(repo, path, name="The Thing")
    assert target == repo / "docs/specs/the-thing.md"
    shown = subprocess.run(["git", "show", "--name-only", "--format=", "HEAD"], cwd=repo,
                           capture_output=True, text=True).stdout.split()
    assert shown == ["docs/specs/the-thing.md"]
    assert state.load_plan(repo, name="spec-state.json") is None


def test_spec_and_plan_checkpoints_do_not_collide(repo, monkeypatch):
    settings = settings_with_planner(repo)
    monkeypatch.setattr(loop.agents, "run", _scripted_run(["codex:blocked#Q?", "codex:blocked#P?"]))
    with pytest.raises(specs.SpecQuestions):
        specs.draft(repo, settings, "spec request")
    with pytest.raises(planner.PlanQuestions):
        planner.draft(repo, settings, "plan request")
    assert specs.pending_description(repo) == "spec request"
    assert planner.pending_description(repo) == "plan request"


def test_spec_answer_reruns_the_asking_stage(repo, monkeypatch):
    settings = settings_with_planner(repo)
    prompts = []
    scripted = _scripted_run(["codex:blocked#Which DB?", "claude:ready", "claude:approved"])

    def run(command, prompt, **kw):
        prompts.append(prompt)
        return scripted(command, prompt, **kw)

    monkeypatch.setattr(loop.agents, "run", run)
    with pytest.raises(specs.SpecQuestions):
        specs.draft(repo, settings, "x")
    specs.answer(repo, settings, "sqlite")
    assert "You asked:\n1. Which DB?\nThe human answered:\nsqlite" in prompts[1]


def test_spec_prompts_exist():
    from whyline_relay import prompts as p
    assert "## Why" in p.SPEC_DRAFT and "## Testing" in p.SPEC_DRAFT
    assert "placeholder" in p.SPEC_REVIEW
```

The fake agent derives the task id from `## Task (\S+)` in the prompt. Both kinds render `## Task {task_id}`, so the spec turns hand off for `__spec__`. Check that the spec prompts keep that header.

- [ ] **Step 2: Run and see them fail.**

- [ ] **Step 3: Implement**

`state.py`: give `plan_path(root, name="plan-state.json")`, `save_plan(root, value, name="plan-state.json")`, `load_plan(root, name="plan-state.json")` and `clear_plan(root, name="plan-state.json")` the extra parameter, used for the file name. Existing callers are unchanged.

`planner.py`:

```python
@dataclass(frozen=True)
class _Kind:
    task_id: str
    draft_name: str
    state_name: str
    draft_prompt: str
    review_prompt: str


PLAN_KIND = _Kind(PLAN_TASK_ID, "draft-plan.md", "plan-state.json", "plan-draft", "plan-review")
SPEC_KIND = _Kind("__spec__", "draft-spec.md", "spec-state.json", "spec-draft", "spec-review")
```

Thread a keyword-only `kind: _Kind = PLAN_KIND` through:
- `draft_path(root, kind=PLAN_KIND)` → `config.relay_dir(root) / kind.draft_name`;
- `_pipeline_for(settings, kind)`, using `kind.draft_prompt` and `kind.review_prompt`;
- `_task_for(description, kind)`;
- `_checkpoint(..., kind)`, which saves with `name=kind.state_name` and `draft_path=str(draft_path(root, kind))`;
- `_run_pipeline(..., kind=PLAN_KIND)`;
- `draft`, `revise`, `resume_draft`, `answer`, `discard` and `pending_description`, each with `kind=PLAN_KIND`.

Every `state.load_plan(root)` and `clear_plan(root)` inside these functions uses `name=kind.state_name`, and the `record.task == PLAN_TASK_ID` checks use `kind.task_id`. Nothing changes for existing plan callers.

`specs.py`:

```python
"""Specs: drafted and reviewed by the planner's machinery (spec section 3),
with their own task id, draft file and checkpoint, so a spec and a plan can
be in progress at once."""
from __future__ import annotations

import subprocess
from pathlib import Path

from whyline_relay import config, gitcheck, planner, state

SpecQuestions = planner.PlanQuestions
KIND = planner.SPEC_KIND


def draft_path(root: Path) -> Path:
    return planner.draft_path(root, KIND)


def draft(root, settings, request: str, *, attachments=(), print_fn=None, runner=subprocess.run) -> Path:
    return planner.draft(root, settings, request, attachments=attachments,
                         print_fn=print_fn, runner=runner, kind=KIND)


def revise(root, settings, feedback, *, print_fn=None, runner=subprocess.run) -> Path:
    return planner.revise(root, settings, feedback, print_fn=print_fn, runner=runner, kind=KIND)


def resume_draft(root, settings, *, print_fn=None, runner=subprocess.run) -> Path:
    return planner.resume_draft(root, settings, print_fn=print_fn, runner=runner, kind=KIND)


def answer(root, settings, answers, *, print_fn=None, runner=subprocess.run) -> Path:
    return planner.answer(root, settings, answers, print_fn=print_fn, runner=runner, kind=KIND)


def discard(root) -> str:
    return planner.discard(root, kind=KIND)


def pending_description(root):
    return planner.pending_description(root, kind=KIND)


def _slug(text: str) -> str:
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].rstrip("-")
    return slug or "spec"


def approve(root: Path, draft: Path, *, name: str, replace: bool = False) -> Path:
    text = draft.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError("the spec draft is empty")
    target = root / "docs" / "specs" / f"{_slug(name)}.md"
    if target.exists() and not replace:
        raise planner.PlanExists(f"{target} already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    gitcheck.commit_paths(root, [target], f"docs: add spec {_slug(name)}")
    state.clear_plan(root, name=KIND.state_name)
    return target
```

Check `planner.discard`'s current body: it clears `plan-state.json` and removes the draft. Make it use `kind` for both.

`prompts.py`: add `SPEC_DRAFT` and `SPEC_REVIEW`, shaped like `PLAN_DRAFT` and `PLAN_REVIEW`: `{sync_packet}`, a role line, `## Task {task_id}`, `{task_text}`, `{review_feedback}`, the rules, `## How to finish`. Register them in `TEMPLATES` as `"spec-draft"` and `"spec-review"`.
- **SPEC_DRAFT's rules:** write `.whyline/relay/draft-spec.md` with these sections: `# <title>`, `## Why`, `## Decisions`, `## Design` (numbered `###` sections), `## Error handling`, `## Testing`, `## Releases`. Base it on the brainstorm document or the description named in the task, and on any attachments listed. Recommend rather than list options. Use the same "put the choices in the question" sentence as `PLAN_DRAFT`. No placeholder text.
- **SPEC_REVIEW's rules:** check that every section exists, nothing contradicts anything else, there is no placeholder text ("TBD", "TODO", "fill in"), and it is specific enough to plan from. Don't judge whether it is the right product. The outcome names match the stage transitions (`approved`, `revise`, `blocked`).

`gitcheck.RELAY_IGNORE`: add `".whyline/relay/draft-spec.md"` and `".whyline/relay/spec-state.json*"`.

- [ ] **Step 4: Run** `uv run pytest -q`, including the existing planner tests, unchanged.
- [ ] **Step 5: Commit** `feat: spec pipeline sharing the planner's machinery (FV2-2)`.

### Task 3: Plan from a spec, release marking, and `revise_synthesis`

**Files:** Modify `src/whyline_relay/planner.py`, `src/whyline_relay/prompts.py`, `src/whyline_relay/brainstorm.py`. Test `tests/test_plan_from_spec.py`.

**Interfaces:**
- `planner.draft(..., spec: Path | None = None)`: the description becomes `"Write the plan from this spec: <repo-relative path>. Read it in full first.\n\n" + description`.
- The `PLAN_DRAFT` and `PLAN_REVIEW` release rule.
- `brainstorm.final_synthesis(root, topic) -> str`.
- `brainstorm.revise_synthesis(root, settings, agent, models, topic, feedback, *, timeout_seconds=None, attachments=(), run_fn=None, runner=None) -> dict` (a `run_turn` record).

- [ ] **Step 1: Failing tests**

```python
from whyline_relay import brainstorm, loop, planner, prompts
from tests.test_planner import _scripted_run, repo, settings_with_planner  # noqa: F401


def test_plan_from_a_spec_names_it_first(repo, monkeypatch):
    spec = repo / "docs/specs/thing.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# Thing\n")
    seen = []
    scripted = _scripted_run(["claude:ready", "claude:approved"])
    monkeypatch.setattr(loop.agents, "run", lambda c, p, **k: seen.append(p) or scripted(c, p, **k))
    planner.draft(repo, settings_with_planner(repo), "the thing", spec=spec)
    assert "Write the plan from this spec: docs/specs/thing.md. Read it in full first." in seen[0]


def test_plan_prompts_mark_release_tasks():
    assert "relay-profile: release" in prompts.PLAN_DRAFT
    assert "relay-profile: release" in prompts.PLAN_REVIEW


def test_final_synthesis_and_revise(repo, monkeypatch):
    doc = brainstorm.shared_path(repo, "topic")
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("# Brainstorm: topic\n\n## Final Synthesis\n\nUse SQLite.\n\n## Claude\n\nx\n")
    assert brainstorm.final_synthesis(repo, "topic") == "Use SQLite."
    sent = []
    monkeypatch.setattr(brainstorm.chat, "run_turn",
                        lambda root, **kw: sent.append(kw) or {"ok": True, "agent": kw["agent"], "response": "done"})
    brainstorm.revise_synthesis(repo, settings_with_planner(repo), "claude", [("claude", "Claude")],
                                "topic", "Prefer Postgres")
    assert sent[0]["agent"] == "claude" and "Prefer Postgres" in sent[0]["prompt"]
    assert "## Final Synthesis" in sent[0]["prompt"]
```

- [ ] **Step 2: Run, see them fail.**

- [ ] **Step 3: Implement**

`planner.draft` gains `spec: Path | None = None`. When it's given, prepend the line above to `description`, computing the path with `spec.resolve().relative_to(root.resolve()).as_posix()` (fall back to `str(spec)` outside the repo).

`PLAN_DRAFT` and `PLAN_REVIEW`: add, above `## How to finish`:

```
A task that releases, publishes, tags or deploys must include the line
`relay-profile: release` in its detail, so the relay hands it to whoever does
releases.
```

(`PLAN_REVIEW` words it as a check: "Send back a draft whose release, publish, tag or deploy tasks lack `relay-profile: release`.")

`brainstorm.py`:

```python
def final_synthesis(root: Path, topic: str) -> str:
    text = shared_path(root, topic).read_text(encoding="utf-8")
    start = text.find("## Final Synthesis")
    if start == -1:
        return ""
    body = text[start + len("## Final Synthesis"):]
    end = body.find("\n## ")
    return (body if end == -1 else body[:end]).strip()


REVISE_SYNTHESIS_PROMPT = (
    "Read {shared_path} in full. Rewrite only its \"## Final Synthesis\" section, "
    "applying this feedback from the human: {feedback}\n\nKeep every model's own "
    "section unchanged. Keep the section first, right after the title."
)


def revise_synthesis(root, settings, agent, models, topic, feedback, *, timeout_seconds=None,
                     attachments=(), run_fn=None, runner=None) -> dict:
    kwargs = {k: v for k, v in (("run_fn", run_fn), ("runner", runner)) if v is not None}
    return chat.run_turn(
        root, agent=agent,
        prompt=REVISE_SYNTHESIS_PROMPT.format(shared_path=shared_path(root, topic), feedback=feedback),
        settings=settings,
        commit_message=f'brainstorm: {agent} revises the synthesis on "{topic}"',
        commit_paths=owned_paths(root, topic, models),
        timeout_seconds=timeout_seconds, attachments=attachments, **kwargs,
    )
```

- [ ] **Step 4: Run** `uv run pytest -q`.
- [ ] **Step 5: Commit** `feat: plans from specs, release marking, synthesis revision (FV2-3)`.

### Task 4: The relay commits approved work in the two-role format too

**Files:** Modify `src/whyline_relay/loop.py` (`_run_task`'s approval and `_commit_and_approve`), `src/whyline_relay/prompts.py` (`REVIEW`), `tests/golden/prompt_review_*.txt`. Test `tests/test_auto_commit.py`.

**Interfaces:** `loop.commit_message(task, summary) -> str`. In the two-role format, an approval with no reviewer commit is committed by the relay. An approval where the reviewer already committed (an older `review.md`) is accepted as-is.

- [ ] **Step 1: Failing tests**

```python
from whyline_relay import loop, plan


def _task(text="T-1: Add the parser"):
    return plan.Task(task_id="T-1", text=text, checked=False, line_index=0)


def test_commit_message_rules():
    assert loop.commit_message(_task(), "Adds the parser. Also tests.") == "feat: Adds the parser (T-1)"
    assert loop.commit_message(_task("T-1: Fix the crash"), "Guard the None.") == "fix: Guard the None (T-1)"
    assert loop.commit_message(_task(), "docs: explain flags") == "docs: explain flags (T-1)"
    assert len(loop.commit_message(_task(), "x" * 200)) <= len("feat: ") + 72 + len(" (T-1)")
    assert loop.commit_message(_task(), "") == "chore: T-1 needed no changes (T-1)"
```

Then two loop tests in the style of `tests/test_loop_single.py`, which drive a two-role run with the fake agents:
1. A reviewer that approves **without** committing: the relay makes the commit (its message ends with `(T-1)`), the task ticks, and only the task's files are in that commit.
2. A reviewer that approves **after committing** itself (the fake agent's `commit:` spec): exactly one commit names `T-1`, and no second commit is made.

Copy the existing two-role fixture and fake-agent setup from `test_loop_single.py`; the fake agent's `"commit:to:status"` form makes the commit.

- [ ] **Step 2: Run, see them fail.**

- [ ] **Step 3: Implement**

```python
_TYPES = ("feat", "fix", "docs", "test", "chore", "refactor")
_TYPE_PREFIX = re.compile(r"^(feat|fix|docs|test|chore|refactor)(\([^)]*\))?:\s*", re.I)


def commit_message(task: plan.Task, summary: str) -> str:
    summary = (summary or "").strip()
    if not summary:
        return f"chore: {task.task_id} needed no changes ({task.task_id})"
    match = _TYPE_PREFIX.match(summary)
    if match:
        kind, summary = match.group(1).lower(), summary[match.end():]
    else:
        title = task.text.split(":", 1)[-1].strip().split(" ", 1)[0].lower()
        kind = title if title in _TYPES[1:] else "feat"
    first = re.split(r"(?<=[.!?])\s", summary, maxsplit=1)[0].rstrip(".")
    return f"{kind}: {first[:72]} ({task.task_id})"
```

`_commit_and_approve` uses `commit_message(task, summary)` in place of `f"{body} ({task.task_id})"`, and keeps its HEAD check.

In `_run_task` (the two-role driver), where an approved review currently returns `_approved(root, task, base_commit, round_, target)`:

```python
            if gitcheck.commit_verified(root, base_commit, task.task_id):
                return _approved(root, task, base_commit, round_, target)  # an older review.md committed
            return _commit_and_approve(root, task, base_commit, round_, target, record.summary)
```

Read the code around the existing `_approved` call (near line 400) and put this at that exact point. `_commit_and_approve`'s "HEAD moved" check needs `base_commit == HEAD`, which holds when the reviewer didn't commit.

`REVIEW` prompt: change the role line to "You are the reviewer for this task.". Replace the Approve block with:

```
Approve: do not commit -- whyline commits the approved work itself. Hand off:

    whyline handoff {task_id} --from {reviewer} --to {reviewer} --status approved \\
      --summary "<what changed, as a one-line commit summary>"
```

Update `tests/golden/prompt_review_0.2.1.txt` (or whichever golden pins `REVIEW`) to the new text, and keep its filename. If a test also checks `init`'s written `review.md`, update that expectation too.

- [ ] **Step 4: Run** `uv run pytest -q`.
- [ ] **Step 5: Commit** `feat: the relay commits approved work in every config format (FV2-4)`.

### Task 5: Release pauses, `done` and `skip`, and the release-agent check

**Files:** Modify `src/whyline_relay/loop.py` (`_run_plan`), `src/whyline_relay/cli.py` (`done`, `skip`, `resume` message), `src/whyline_relay/preflight.py`. Test `tests/test_release_tasks.py`.

**Interfaces:** `loop.RELEASE_PREFIX = "release task for you: "`; `loop.mark_done(root, task_id) -> None`; `loop.mark_skipped(root, task_id) -> None`. CLI: `whyline relay done <ID>` and `whyline relay skip <ID>` (both then resume the run); `whyline relay resume` on a release pause prints the hint and exits 1. Preflight: `warn` for a release agent whose sandbox likely blocks network access or tags.

- [ ] **Step 1: Failing tests**

```python
import pytest

from whyline_relay import cli, loop, plan, state


PLAN = "- [ ] T-1: build\n  do it\n- [ ] T-2: release 1.0\n  relay-profile: release\n  Bump the version.\n  Tag v1.0 and push.\n- [ ] T-3: after\n  x\n"


def test_a_release_task_pauses_for_the_human_without_a_pipeline_profile(two_role_repo, monkeypatch):
    # two_role_repo: a git repo with this PLAN, config implementer/reviewer, T-1 already ticked
    root = two_role_repo(PLAN.replace("- [ ] T-1", "- [x] T-1"))
    with pytest.raises(loop.Paused) as paused:
        loop.run_plan(root, loop.config.load(root), root / "plan.md", branch="relay/plan", echo=False)
    assert paused.value.reason.startswith("release task for you: T-2")
    assert state.load(root).task_id == "T-2"


def test_done_ticks_commits_and_moves_on(two_role_repo):
    root = two_role_repo(PLAN.replace("- [ ] T-1", "- [x] T-1"))
    with pytest.raises(loop.Paused):
        loop.run_plan(root, loop.config.load(root), root / "plan.md", branch="relay/plan", echo=False)
    loop.mark_done(root, "T-2")
    tasks = plan.parse((root / "plan.md").read_text())
    assert plan.find(tasks, "T-2").checked and state.load(root) is None


def test_done_for_the_wrong_task_is_refused(two_role_repo):
    root = two_role_repo(PLAN.replace("- [ ] T-1", "- [x] T-1"))
    with pytest.raises(loop.Paused):
        loop.run_plan(root, loop.config.load(root), root / "plan.md", branch="relay/plan", echo=False)
    with pytest.raises(ValueError, match="T-2"):
        loop.mark_done(root, "T-3")


def test_skip_leaves_it_unticked(two_role_repo):
    root = two_role_repo(PLAN.replace("- [ ] T-1", "- [x] T-1"))
    with pytest.raises(loop.Paused):
        loop.run_plan(root, loop.config.load(root), root / "plan.md", branch="relay/plan", echo=False)
    loop.mark_skipped(root, "T-2")
    assert not plan.find(plan.parse((root / "plan.md").read_text()), "T-2").checked
```

Write the `two_role_repo` fixture in `tests/conftest.py`. It's a factory: a git repo, the given `plan.md` committed, `.whyline/relay/config.toml` with `[roles] implementer = "codex" reviewer = "claude"` and `release` unset (so "human"), on branch `relay/plan`. Use the setup steps from `tests/test_cli_commands.py::test_resume_reuses_the_saved_base_commit`.

Skipped tasks must stay skipped on later runs. Record each `mark_skipped` id in `.whyline/relay/skipped-tasks.json` (git-ignored via `RELAY_IGNORE`), and have `_run_plan` pass over unticked tasks listed there. Test that too: after skip, `run_plan` goes on to T-3 (stub the agents as in the loop tests).

Add a CLI test: `cli.main(["resume", "--repo", str(root)])` on a release pause returns 1 and prints `whyline relay done T-2`.

- [ ] **Step 2: Run, see them fail.**

- [ ] **Step 3: Implement**

In `_run_plan`, right after choosing `task` and before `run_task`:

```python
        if task.profile == "release" and settings.release_role == "human":
            checklist = "\n".join(l.strip() for l in task.text.splitlines()[1:]
                                  if l.strip() and not l.strip().startswith("relay-profile:"))
            reason = f"{RELEASE_PREFIX}{task.task_id}\n{checklist}"
            _save_pause(root, plan_path, branch, task, gitcheck.head_commit(root),
                        reason, None, only, {"round": 1, "last": None})
            raise Paused(reason)
        if task.profile == "release":  # an agent does releases
            settings = _with_release_implementer(settings, settings.release_role)
            task = dataclasses.replace(task, profile=None)
```

`_with_release_implementer` returns a copy of `settings` with the implementer role's agent replaced:
- in the two-role format, `dataclasses.replace(settings, roles=Roles(release_agent, settings.roles.reviewer))`;
- in the pipeline format, a copy of `settings.pipeline` whose `roles["implementer"]` is `dataclasses.replace(role, agent=release_agent)`.

Setting `profile=None` keeps the task off a pipeline profile named `release`, so it uses the default profile. This deviates on purpose from the spec's "no tester stage": the agent-run release keeps the tester, which is simpler and only adds a check.

```python
def _paused_release(root: Path, task_id: str) -> state.RelayState:
    saved = state.load(root)
    if saved is None or not saved.paused_reason.startswith(RELEASE_PREFIX):
        raise ValueError("the relay is not paused on a release task")
    if saved.task_id != task_id:
        raise ValueError(f"the relay is paused on release task {saved.task_id}, not {task_id}")
    return saved


def mark_done(root: Path, task_id: str) -> None:
    saved = _paused_release(root, task_id)
    plan_path = Path(saved.plan)
    current = plan_path.read_text(encoding="utf-8")
    if plan.find(plan.parse(current), task_id) is None:
        raise ValueError(f"{task_id} is no longer in {plan_path.name}")
    plan_path.write_text(plan.tick(current, task_id), encoding="utf-8")
    gitcheck.commit_paths(root, [plan_path], f"chore: release task {task_id} done by hand")
    state.clear(root)


def mark_skipped(root: Path, task_id: str) -> None:
    _paused_release(root, task_id)
    skipped = config.relay_dir(root) / "skipped-tasks.json"
    ids = json.loads(skipped.read_text()) if skipped.exists() else []
    if task_id not in ids:
        ids.append(task_id)
    skipped.write_text(json.dumps(ids))
    state.clear(root)
```

In `_run_plan`, choose the next unchecked task that isn't listed in `skipped-tasks.json`. Add a `plan.next_unchecked(tasks, skip=ids)` parameter, or filter before calling it.

CLI:
- `done` and `skip` take `task_id`, call `mark_done` or `mark_skipped`, print `Marked <ID> done.` (or `Skipped <ID>.`), then run the same code path as `start` with the saved plan and branch, in the same process, so progress streams on.
- In `cmd_resume`, when the saved reason starts with `RELEASE_PREFIX`, print `This is a release task for you: do its steps, then run: whyline relay done <ID> (or: whyline relay skip <ID>)` and return 1.

Preflight: in the role checks, when `settings.release_role` is an agent, add one check:
- `warn` with "release tasks by codex: its workspace-write sandbox blocks network access and tag writes; release tasks will likely fail" when the agent is codex and its command contains `workspace-write`;
- otherwise `warn` with "release tasks by <agent>: can't verify that it can push and tag; the first release task will show".

There's no network call in preflight.

- [ ] **Step 4: Run** `uv run pytest -q`.
- [ ] **Step 5: Commit** `feat: release tasks pause for the human; done and skip (FV2-5)`.

### Task 6: Release whyline-relay 0.2.31 (human)

Same steps as earlier relay releases: bump to `0.2.31` in `pyproject.toml` and `src/whyline_relay/__init__.py`, `uv lock`, write `docs/releases/v0.2.31.md` (spec pipeline, plans from specs, release marking, the relay commits approved work in every format, release tasks pause for you with `done`/`skip`, synthesis revision), run the suite with and without agent CLIs on PATH, push `main`, tag `v0.2.31`, watch the release workflow, and confirm PyPI.

---

# whyline 0.3.34 (Tasks 7–12)

Before Task 7 (human): `cd ~/agentdock && git switch main && git pull --ff-only`. Bump both `whyline-relay>=0.2.30,<0.3` → `>=0.2.31,<0.3`, run `uv lock --refresh --upgrade-package whyline-relay && uv sync`, run the tests with and without agent CLIs on PATH, and commit `chore: require whyline-relay 0.2.31`.

### Task 7: `relay_ops` for specs, synthesis and release tasks

**Files:** Modify `src/whyline/console/relay_ops.py`. Test `tests/console/test_relay_ops.py`.

**Interfaces** (all in `relay_ops`):
- `draft_spec(root, request, attachments, *, progress) -> Draft` (`source="spec"`);
- `revise_spec(root, draft, feedback, *, progress) -> Draft`, `resume_spec(root, *, progress) -> Draft`, `answer_spec(root, answers, *, progress) -> Draft`, `discard_spec(root)`, `pending_spec(root) -> str | None`;
- `approve_spec(root, draft, name, *, replace=False) -> Path`;
- `spec_questions_error()`, which is `PlanQuestions`, the same class;
- `final_synthesis(root, topic) -> str`;
- `revise_synthesis(root, topic, agent, agents, feedback, *, progress, timeout_minutes=None, attachments=()) -> None`;
- `draft_plan(root, description, attachments, *, progress, spec: Path | None = None) -> Draft`;
- `release_task(root) -> tuple[str, list[str]] | None`: the paused release task's id and checklist;
- `save_release(root, value)`;
- `release_role(root) -> str`.
- `list_plans`' `PlanInfo` gains `spec: str = ""`, read from the marker's `spec:` field. `with_marker(..., spec="")` writes it.

- [ ] **Step 1: Failing tests** for each wrapper, in the existing style of `test_relay_ops.py` (a real git repo and a fake relay run). The main ones:

```python
def test_approve_spec_writes_docs_specs(repo):
    d = relay_ops.Draft(path=repo / "d.md", text="# S\n", drafted_by="codex", source="spec")
    d.path.write_text("# S\n")
    assert relay_ops.approve_spec(repo, d, "My Spec") == repo / "docs/specs/my-spec.md"


def test_marker_records_the_spec(repo):
    text = relay_ops.with_marker("- [ ] T-1: x\n", source="draft", drafted_by="codex",
                                 spec="docs/specs/s.md")
    assert "| spec: docs/specs/s.md |" in text.splitlines()[0]
    path = repo / "plans" / "p.plan.md"
    path.parent.mkdir()
    path.write_text(text)
    assert relay_ops.list_plans(repo)[0].spec == "docs/specs/s.md"


def test_release_task_reads_the_pause(repo):
    from whyline_relay import state
    state.save(repo, state.RelayState(
        plan=str(repo / "plan.md"), branch="b", task_id="T-2", round=1, base_commit="",
        paused_reason="release task for you: T-2\nBump the version.\nTag v1.0 and push.", log_path=""))
    assert relay_ops.release_task(repo) == ("T-2", ["Bump the version.", "Tag v1.0 and push."])
```

- [ ] **Step 2–5:** Implement each as a thin call into `whyline_relay.specs`, `brainstorm` and `setup` (lazy imports, as in the rest of `relay_ops`). Run `uv run pytest -q`, then commit `feat: relay_ops for specs, synthesis and release tasks (FV2-7)`.

The marker line's field order is `source | drafted-by | spec | created`, with `spec` present only when set. `_marker_fields` already parses any `key: value` field.

### Task 8: `plan_job` stages: synthesis, spec, plan

**Files:** Modify `src/whyline/console/plan_job.py`. Test `tests/console/test_plan_job.py`.

**Interfaces:**
- `Outcome` gains `stage: str = "plan"` (`"synthesis" | "spec" | "plan"`), `text: str = ""` (for synthesis), `topic: str = ""` and `writer: str = ""`.
- `PlanRequest` gains `spec_first: bool = True`.
- `run_request(root, request, progress) -> Outcome`:
  - `"brainstorm"` runs the brainstorm, then returns `Outcome("draft", stage="synthesis", text=final_synthesis, topic=..., writer=final_agent)`. If the synthesis has `## Open questions` items, it returns `kind="questions", stage="synthesis"`.
  - `"existing"` (a saved brainstorm document) returns the same synthesis outcome, without running anything.
  - `"draft"` with `spec_first` runs `draft_spec(description)` and returns stage `spec`; without it, as today (stage `plan`).
  - `"resume"` resumes a pending spec first, if there is one, otherwise the plan.
- `run_synthesis_change(root, request, outcome, feedback, progress) -> Outcome` (stage `synthesis`).
- `run_spec_from_synthesis(root, request, outcome, progress) -> Outcome` (stage `spec`): the request text is `f"Write the spec from the brainstorm in {doc} (its Final Synthesis is the agreed direction)."`.
- `run_plan_from_spec(root, request, spec_path, progress) -> Outcome` (stage `plan`).
- `run_revision` and `run_answer` dispatch on `outcome.stage` (spec → `revise_spec`/`answer_spec`; plan → as today).
- `summary(draft, name)` is unchanged for plans. `spec_summary(draft, name) -> str` gives the title, section headings and line count, then `Type "approve" to save it as docs/specs/<slug>.md and write the plan, or say what to change.` `synthesis_text(outcome) -> str` gives the first 40 lines plus `… (View full for the rest)` and `Type "approve" to write the spec from this, or say what to change.`

- [ ] **Step 1: Failing tests**, one per path above, in the style of the existing `test_plan_job.py`, with `relay_ops` and `adapters.run_brainstorm` stubbed. For example:

```python
def test_a_brainstorm_returns_its_synthesis_for_review(tmp_path, monkeypatch):
    from whyline.console import adapters
    monkeypatch.setattr(adapters, "run_brainstorm", lambda root, **k: tui_event("output", "ok"))
    monkeypatch.setattr(relay_ops, "final_synthesis", lambda root, topic: "Use SQLite.")
    req = plan_job.PlanRequest("brainstorm", "p", brainstorm={"topic": "t", "agents": ["claude"],
        "passes": 1, "final_agent": "claude", "timeout_minutes": 15, "attachments": []})
    out = plan_job.run_request(tmp_path, req, lambda l: None)
    assert (out.kind, out.stage, out.text, out.writer) == ("draft", "synthesis", "Use SQLite.", "claude")


def test_an_unticked_spec_box_plans_directly(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(relay_ops, "save_planner", lambda *a: None)
    monkeypatch.setattr(relay_ops, "draft_plan", lambda root, d, a, progress, spec=None: called.append("plan") or _draft(tmp_path))
    monkeypatch.setattr(relay_ops, "draft_spec", lambda *a, **k: called.append("spec"))
    plan_job.run_request(tmp_path, plan_job.PlanRequest("draft", "p", description="x", spec_first=False,
                         drafter="codex", reviewer="claude"), lambda l: None)
    assert called == ["plan"]
```

(`tui_event` is `whyline.console.session.SessionEvent`; import it as such.)

- [ ] **Step 2–5:** Implement, run `uv run pytest -q`, and commit `feat: plan job stages for synthesis, spec and plan (FV2-8)`.

### Task 9: The brainstorm-first Plan form, and `start` with no plan

**Files:** Modify `src/whyline/console/relay_screens.py` (`RelayPlanScreen`), `src/whyline/console/tui.py` (`_launch_relay`). Test `tests/console/test_relay_plan_screen.py`, `tests/console/test_tui_relay_run.py`.

- [ ] **Step 1: Failing tests:**
  - The Source select's first option, and its default value, is `brainstorm`. Its labels are "Brainstorm it" / "I'll describe it" / "I have a plan already".
  - The description group has `#rp-spec-first` (a Checkbox, ticked by default), and the request carries `spec_first`.
  - The brainstorm group shows the Drafter and Reviewer dropdowns too (`#rp-drafter`, `#rp-reviewer` move out of the draft group into a shared row shown for both brainstorm and describe). The request carries them.
  - Typing `start` (no `--plan`) in Relay mode opens `RunChoiceScreen` (or the Plan form when there are no plans), and `start --plan x` still launches directly.

- [ ] **Step 2–5:** Implement:
  - Reorder `_SOURCES` to `[("Brainstorm it", "brainstorm"), ("I'll describe it", "draft"), ("I have a plan already", "paste")]`, with default `"brainstorm"`.
  - Move the Drafter/Reviewer row out of the draft group, and show it for brainstorm and draft.
  - Add the checkbox.
  - In `_launch_relay`, when `args == ["start"]`, call `self._run_flow_start()` and return.

  Run `uv run pytest -q`, then commit `feat: brainstorm-first plan form; start asks first (FV2-9)`.

### Task 10: Synthesis and spec review in the main window

**Files:** Modify `src/whyline/console/tui.py`. Test `tests/console/test_plan_in_main_window.py`.

**Interfaces:**
- The plan state values stay `"working"`, `"review"` and `"answering"`. `self._plan_outcome.stage` says what is being reviewed.
- The sub-title suffix is `· synthesis review`, `· spec review` or `· plan review`.
- Placeholders: synthesis "Type "approve" to write the spec, or say what to change"; spec "Type "approve" to save the spec and write the plan, or say what to change".
- The `#plan-view` button is labelled **View full**, **View spec** or **View draft** by stage.

- [ ] **Step 1: Failing tests** (stub `plan_job`):

```python
async def test_synthesis_approve_starts_the_spec_job(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_job, "run_request", lambda root, req, p: plan_job.Outcome(
        "draft", stage="synthesis", text="Use SQLite.", topic="t", writer="claude"))
    started = []
    monkeypatch.setattr(plan_job, "run_spec_from_synthesis",
                        lambda root, req, out, p: started.append(out.topic) or plan_job.Outcome(
                            "draft", _draft(tmp_path, "# Spec\n## Why\n"), stage="spec"))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: app._plan_state == "review", "synthesis review")
        assert "synthesis review" in app.sub_title
        assert any("Use SQLite." in l for l in _lines(app))
        await _type(app, pilot, "approve")
        await _wait_for(pilot, lambda: started == ["t"], "spec job")
        await _wait_for(pilot, lambda: "spec review" in app.sub_title, "spec review")


async def test_spec_approve_commits_then_plans_from_it(tmp_path, monkeypatch):
    spec_draft = _draft(tmp_path, "# Spec\n")
    monkeypatch.setattr(plan_job, "run_request", lambda root, req, p: plan_job.Outcome("draft", spec_draft, stage="spec"))
    monkeypatch.setattr(relay_ops, "approve_spec", lambda root, d, name, replace=False: root / "docs/specs/my-plan.md")
    planned = []
    monkeypatch.setattr(plan_job, "run_plan_from_spec",
                        lambda root, req, spec, p: planned.append(spec) or plan_job.Outcome("draft", _draft(tmp_path)))
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: "spec review" in app.sub_title, "spec review")
        await _type(app, pilot, "approve")
        await _wait_for(pilot, lambda: "plan review" in app.sub_title, "plan review")
    assert planned == [tmp_path / "docs/specs/my-plan.md"]
    assert any("Saved docs/specs/my-plan.md" in l for l in _lines(app))


async def test_plan_failure_after_spec_approval_keeps_the_spec(tmp_path, monkeypatch):
    spec_draft = _draft(tmp_path, "# Spec\n")
    monkeypatch.setattr(plan_job, "run_request", lambda root, req, p: plan_job.Outcome("draft", spec_draft, stage="spec"))
    monkeypatch.setattr(relay_ops, "approve_spec", lambda root, d, name, replace=False: root / "docs/specs/my-plan.md")

    def boom(root, req, spec, p):
        raise RuntimeError("codex timed out")

    monkeypatch.setattr(plan_job, "run_plan_from_spec", boom)
    app = tui.WhylineConsoleApp(root=tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        app._start_plan_job(REQUEST)
        await _wait_for(pilot, lambda: "spec review" in app.sub_title, "spec review")
        await _type(app, pilot, "approve")
        await _wait_for(pilot, lambda: any("codex timed out" in l for l in _lines(app)), "failure")
        failure = next(l for l in _lines(app) if "codex timed out" in l)
    assert "docs/specs/my-plan.md is saved" in failure and "Resume draft" in failure
```

- [ ] **Step 2–5:** Implement in `_plan_done`, `_plan_reply` and `_approve_plan`, branching on `self._plan_outcome.stage`:
  - **synthesis + approve** → `_run_plan(lambda p: plan_job.run_spec_from_synthesis(root, request, outcome, p))`.
  - **spec + approve** → `relay_ops.approve_spec(...)` (with the existing replace confirmation), render `Saved docs/specs/<slug>.md and committed it. Writing the plan from it…`, then `_run_plan(lambda p: plan_job.run_plan_from_spec(root, request, spec_path, p))`. Keep `self._approved_spec = spec_path`, so `_plan_failed` can say "<spec> is saved; open Plan → Resume draft to continue the plan".
  - **plan + approve** → as today. Pass `spec=` through to `with_marker` via `approve_plan(..., spec=...)` (extend `approve_plan` with `spec: str = ""`).
  - Change requests and answers go to `plan_job.run_synthesis_change` / `run_revision` / `run_answer`.
  - **View** opens `PlanDraftScreen` with the synthesis text, the spec text or the plan text.

  Run `uv run pytest -q`, then commit `feat: synthesis and spec review in the main window (FV2-10)`.

### Task 11: Committer and Release in the Roles step; the release state

**Files:** Modify `src/whyline/console/relay_screens.py` (`RelaySetupScreen`), `src/whyline/console/tui.py`, `src/whyline/console/relay_ops.py` (`save_roles` keeps release; `role_meaning` gains release). Test `tests/console/test_relay_setup_screen.py`, `tests/console/test_run_flow.py`, `tests/console/test_release_state.py` (create).

- [ ] **Step 1: Failing tests:**
  - Set up shows `Static("Committer: whyline (automatic)", id="rs-committer")` and `Select` `#rs-release` with "you" (value `human`) and every relay agent, prefilled from `relay_ops.release_role(root)`. Check saves it with `relay_ops.save_release(root, value)`, after `save_roles`.
  - The summary line ends with `· Release: you` (or the agent), and `role_meaning` gives `"codex writes the code → claude runs the tests → claude reviews; whyline commits; you do the release steps."`.
  - **The release state:** when the relay process finishes with a pause whose text starts with `release task for you: T-2` (stub `RelayProcess` as in `test_tui_relay_run.py`), the transcript shows `⏸ T-2 is a release task for you:`, the numbered checklist, and `Type "done" when finished, or "skip".`. The sub-title says `· release`. The Resume button label is `Release done…`. Typing `done` launches the relay with `["done", "T-2"]`, and typing `skip` with `["skip", "T-2"]`.

- [ ] **Step 2–5:** Implement:
  - `RelaySetupScreen` adds the two rows inside `#rs-roles`. The summary row shows them read-only.
  - In `tui._relay_finished`, when the pause text starts with `"release task for you: "`, set `self._release_task = relay_ops.release_task(root)`, render the checklist, set a `"release"` sub-state (reuse `_plan_state`-style handling: in `_send`, when `self._release_task` is set and the text is `done` or `skip`, call `_launch_relay([text, task_id])` and clear it), and update the Resume label.
  - `_sync_relay_buttons` labels Resume `Release done…` while `self._release_task` is set. Pressing it behaves like typing `done`.

  Run `uv run pytest -q`, then commit `feat: committer and release roles; release tasks in the console (FV2-11)`.

### Task 12: Release whyline 0.3.34 (human)

Same as earlier console releases: bump to `0.3.34`, write `docs/releases/v0.3.34.md` (brainstorm-first plans, synthesis review, specs, plans from specs, the relay commits for you, release tasks pause with a checklist, `start` asks first; needs whyline-relay 0.2.31), test with and without agent CLIs, push, tag `v0.3.34`, watch every OS, confirm PyPI, and run `uv tool upgrade whyline`.

**Check by hand before tagging:** in a scratch repo, Run → Create → describe a tiny change with "Write a spec first" ticked → approve the spec → approve the plan → Roles show Committer and Release: you → Start. Add a `relay-profile: release` task to the plan, so the run pauses there with the checklist; then type `done` and see it finish.

---

## Running this plan with the relay

Before each part, set the roles in that repo's `.whyline/relay/config.toml`, `[roles]`, to `implementer = "antigravity"` and `reviewer = "claude"`, and commit the change. Then:

- **whyline-relay** (Tasks 1–5): `.whyline/relay/fv2-relay.md` with FV2-1 to FV2-5, each "Implement 'Task N' from `.whyline/relay/fv2/implementation-plan.md`" (copy this plan and the spec into `.whyline/relay/fv2/`). Run `start --plan .whyline/relay/fv2-relay.md`.
- **whyline** (Tasks 7–11): `.whyline/relay/fv2-console.md` with FV2-7 to FV2-11, pointing at `docs/superpowers/plans/2026-10-04-relay-guided-flow-v2.md`.

Every relay task repeats: tests first; no dependence on installed agent CLIs or the real home folder; Windows-safe paths; never push, tag or publish.

From Task 4 on, the relay commits for the reviewer. While Task 4 itself runs, Claude follows the repo's existing `review.md`, which says to commit, and that's still accepted.
