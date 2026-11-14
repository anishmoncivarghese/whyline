<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-11-14-agent-builder-design.md | created: 2026-11-14T23:30:00+05:30 -->
# Agent draft: describe what you want and get an agent to review

Spec: `docs/superpowers/specs/2026-11-14-agent-builder-design.md`, Part 2. Read it before every task. Where this plan and the spec differ, this plan wins. In particular:
- **The `calls` field of a draft** is filled only once `plans/agent-calls.plan.md` has added it. Until then the drafter is not told about other agents, and a draft has none.

Runs after `plans/agent-profile.plan.md`, and before `plans/agent-calls.plan.md`.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Why: creating an agent means filling a long form and knowing which skills, tools and packs fit. Templates cover six fixed cases.

What the user gets:
- **New agent → Describe it**: type what you want, and the form opens filled in with a name, description, instructions, skills, tools, knowledge, schedule, delivery and starter prompts.
- A **What's missing** list, in plain words, when the description needs something the library doesn't have.
- **Change it**: a follow-up that redrafts and keeps the fields you edited by hand.
- `new agent <description>` from Telegram, and `whyline agents draft` from a terminal.

Rules every task keeps:
- **Console first.** Drafting works from New agent through the same functions as `whyline agents draft`.
- **A draft only uses what exists.** Every skill, tool, pack, CLI and delivery target in a draft is checked against the library by code. Anything else is removed and listed as missing. The drafter's output never adds a connector, a credential, a skill or a pack.
- **Safe defaults are applied by code, after the drafter:**
  - every tool that writes is `ask`
  - `every_minutes` below 15 is raised to 15, and `every_hours` below 1 to 1
  - delivery targets are only the user's own, from the deliveries already set up
- **Nothing is saved by drafting.** A draft is an unsaved `AgentDef` in the form. Saving is the user's Save, and running still needs Accept.
- **The description the user types is data** in the drafting prompt, inside a labelled block, cut to 2,000 characters. Library entries are data too.
- **The drafting turn is read-only**, through `capabilities.read_only_command`, on the assistant's main then backup agent, with a 90-second limit.
- **No new dependency.**
- **Tests:** never invoke a real provider or Telegram. Use temporary folders and a fake library. Keep Python 3.11 compatibility.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- A tool, skill, pack, CLI or delivery the library doesn't have never reaches the draft, and is listed as missing. DRF-2, `test_unknown_items_are_removed_and_listed`.
- A writing tool the drafter marked allowed comes out as ask. DRF-2, `test_writing_tools_are_ask_first`.
- Drafting writes no agent file. DRF-3, `test_drafting_saves_nothing`.
- A redraft keeps every field the user edited by hand. DRF-4, `test_redraft_keeps_hand_edits`.
- Text in the description that looks like an instruction to add a tool or a recipient changes nothing outside the validated draft. DRF-2, `test_description_cannot_widen_the_draft`.

- [ ] DRF-1: The library summary and the drafting prompt
  Create `src/whyline/agents/draft.py` and `tests/agents/test_draft.py` only.
  1. `@dataclass(frozen=True) class Library`: `skills` (ref, description), `tools` (`<server>.<tool>`, description, `writes: bool`), `packs` (name, description), `clis` (usable names), `deliveries` (labels), `templates` (names).
  2. `draft.library(repo_root) -> Library` from `tools.skills.find`, `tools.mcp_config.load` (enabled, tested servers only), `tools.knowledge.list_packs`, the enabled CLIs that pass `capabilities.can_run_unattended`, and the delivery targets set up in `agents.deliveries`. Each list is capped at 60 entries and each description at 160 characters.
  3. `draft.build_prompt(description, lib, *, base: dict | None = None, keep: tuple[str, ...] = ()) -> str`.
     - It asks for one fenced JSON block with: `name`, `description`, `instructions`, `skills`, `tools` (a map of tool to `allowed` or `ask`), `knowledge`, `trigger` (`kind` and its fields), `delivery`, `starters`, and `missing` (a list of plain sentences).
     - It states the rules: choose only from the lists, say what's missing instead of inventing it, write instructions as steps the agent follows, and keep the name short.
     - With `base`, it is a redraft: the earlier draft is given, and the fields in `keep` are marked `do not change`.
  4. `draft.parse(text) -> dict | None`: the last fenced JSON object, or None.
  Tests: the library caps, disabled or untested servers left out, the prompt holding the description inside a data block, the `keep` wording, and parse.

- [ ] DRF-2: Validating a draft
  Edit `src/whyline/agents/draft.py` and its tests only.
  1. `@dataclass(frozen=True) class Draft`: `defn: AgentDef`, `missing: tuple[str, ...]`, `drafted: tuple[str, ...]` (the field names the drafter filled), `notes: tuple[str, ...]` (what code changed, in plain words).
  2. `draft.validate(raw: dict, lib: Library, *, kind: str, repo_root) -> Draft`:
     - **name:** made to fit the agent name rule; when taken, a number is appended. An empty one becomes `new-agent`.
     - **description, starters:** cut to PRF-1's limits.
     - **instructions:** kept as text, cut to 8,000 characters. Empty instructions give a `missing` line.
     - **skills, tools, knowledge:** each entry not in `lib` is removed, and one `missing` sentence is added: `Needs <what>: add it in Agents → Tools → <tab>, then press Draft again.`
     - **tools:** a tool with `writes` is set to `ask`, with a note when the drafter had said allowed. An unknown permission becomes `ask`.
     - **trigger:** only the kinds `definitions.Trigger` has. Intervals are raised to the floors in the rules, with a note. An unreadable time becomes `manual` with a note.
     - **delivery:** kept only when its label is in `lib.deliveries`, else none, with a note.
     - **runner and backup:** the first usable CLI for this draft's tools (`runner.usable_clis`) and the next as backup. The drafter does not choose them.
     - `missing` sentences from the drafter are kept, each cut to 200 characters, at most 8.
  3. The result's `defn` passes `definitions` validation. When it can't be made to, `validate` raises `DraftError` with the reason.
  Tests: `test_unknown_items_are_removed_and_listed`, `test_writing_tools_are_ask_first`, `test_description_cannot_widen_the_draft` (a raw block naming a tool, a recipient and a credential that aren't in the library), the name fixes, the interval floors, a missing delivery, and the CLI choice for an agent with tools.

- [ ] DRF-3: Running a draft
  Edit `src/whyline/agents/draft.py`, `src/whyline/cli.py` (the `whyline agents` commands) and their tests only.
  1. `draft.create(description, *, kind, repo_root, run_fn=None, base: Draft | None = None, keep=()) -> Draft`: builds the library and prompt, runs one read-only turn on the assistant's main then backup agent (`ideas.assistant.selected`, 90 seconds), parses and validates. When no agent gives a readable block it raises `DraftError("Couldn't draft that: <reason>. Try again, or start from a template.")`. An empty description is refused.
  2. CLI: `whyline agents draft "<description>" [--repo]` prints the agent file `definitions.render` would write, then `What's missing:` and `Changed for safety:` when there are any. `--save` saves it through `service.save_new` (not accepted). `--json` prints the draft as JSON.
  Tests: `test_drafting_saves_nothing` (no file under the agents folders after `create` and after the CLI without `--save`), the backup agent used when the main gives nothing, the error text, `--save` writing an unaccepted agent, and an empty description.

- [ ] DRF-4: Describe it in New agent
  Edit `src/whyline/console/agents_screens.py` and its tests only.
  1. `AgentTemplateScreen` (the first step of New agent) gets **Describe it** above the templates and **Blank**: a text area with the hint `What should it do, when, and where should the answer go?`, an example line, and **Draft**.
  2. **Draft** runs `draft.create` off the UI thread, showing `Drafting…` with **Cancel**. On success it opens `NewAgentScreen` filled from the draft, with:
     - a top line `Drafted from your description. Check each section before saving.`
     - `drafted` beside each field in `Draft.drafted`, removed when the user edits that field
     - a **What's missing** box listing the sentences, each with a button to the Tools tab it names
     - a **Changed for safety** box listing the notes
  3. A **Change it** box under the form: a follow-up line and **Redraft**. It calls `draft.create` with the current form as `base` and the hand-edited field names as `keep`, and refills only the fields not in `keep`.
  4. A failed draft shows the error and leaves the user on the Describe it step with their text.
  5. Save, Review and Accept are unchanged.
  Tests: `test_redraft_keeps_hand_edits`, the form filled from a draft, the `drafted` marks cleared on edit, the missing box and its buttons, Cancel, and a failed draft keeping the text.

- [ ] DRF-5: `new agent` from Telegram
  Edit `src/whyline/ideas/actions.py`, `src/whyline/ideas/intent.py`, `src/whyline/ideas/bot.py`, `src/whyline/console/agents_screens.py` and their tests only.
  1. Register `draft_agent` (`writes=False`, duration `turn`, approval `none`) and the command `new agent <description>`.
  2. The reply is the draft as a summary: name, description, when it runs, where it delivers, its skills, tools (with `asks first` on those that do) and knowledge, then `What's missing` when there is any. Buttons: **Open in console** and **Discard**.
  3. A draft from Telegram is kept as a pending draft file under `~/.whyline/ideas/drafts/` (0600, at most 10, older ones removed), not as an agent. **Discard** removes it.
  4. The console's Agents list shows `1 draft from Telegram` with **Open**, which opens New agent filled from it. Saving or discarding there removes the pending draft.
  Tests: the summary text, the pending file written and capped at 10, Discard, the console opening it, and no agent file written from Telegram.

- [ ] DRF-6: Docs
  Edit `docs/agent-tools.md`, `README.md` and the console Help text for Agents only.
  Cover: Describe it with two example descriptions, What's missing and Changed for safety, Change it, `new agent` from Telegram, `whyline agents draft`, and that a drafted agent still needs Save and Accept.
  Verify with `uv run pytest -q`.
