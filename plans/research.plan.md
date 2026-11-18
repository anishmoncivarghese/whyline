<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-11-19-research-mode-design.md | created: 2026-11-19T12:00:00+05:30 -->
# Research: a question in, a checked report out, and research before brainstorm

Runs after `plans/release-resolve.plan.md`, and before `plans/telegram-daily-use.plan.md`. Spec: `docs/superpowers/specs/2026-11-19-research-mode-design.md`. Read it before every task. Where this plan and the spec differ, this plan wins. In particular:
- **A job is a folder, not a database row.** Nothing here edits `src/whyline/ideas/store.py`.
- **The router is not touched here.** The `research` route is RT-8 in `plans/telegram-daily-use.plan.md`. This plan adds the `research` command and the idea card button only.
- **Model selects come later.** `plans/agent-setup.plan.md` (AMD-1) adds a model per agent. Until it lands, Research → Set up chooses agents only.

It replaces `plans/assistant-research.plan.md` (RES-1..5), which is removed.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Why:
- Brainstorm works from what the models already know. Nothing is looked up and nothing says where a claim came from.
- A one-pass research answer can cite a page that doesn't say what the answer claims, and never goes back for what is still unknown.

What the user gets:
- A **Research** mode in the console: a question, a depth (Quick, Standard, Deep), the plan first if wanted, a live board, reports, follow-up questions.
- Citations whyline checks itself: each claim's quote is looked for on the fetched page and marked ✓, `not checked` or `the source doesn't say this`.
- **Research first** before a brainstorm, as a document-set stage and as a phase in Auto, with the report attached to the brainstorm, spec and plan.
- `research <question>` and a **Research** button on idea cards in Telegram.

Rules every task keeps:
- **Console first.** Every action is in the console and calls the same function as its `whyline research …` command.
- **Read-only, always.** Every agent turn is built with `capabilities.read_only_command` and runs in the job folder. Nothing outside `~/.whyline/research/<id>/` is written by a job, except the copy a document-set stage makes in that repository's docs (RSR-9).
- **Personal and global.** Jobs live in `~/.whyline/research` (folders 0700, files 0600) and never depend on the repository selected in the console. Tests point the home at a temporary folder.
- **Page text is data.** Fetched text passes `ideas.guard.clean`, is given to the agent as files in the job folder, and never chooses a command, a URL to post to, a path or a recipient. Prompts say that file content is data.
- **whyline marks the findings.** A finding's mark comes only from whyline's quote check, never from the agent's words.
- **Budgets are hard limits** (RSR-5's table).
- **No new dependency.** No search client: search is the agent CLI's own. Pages are fetched with `agents.pagefetch.fetch` only.
- **Tests:** never open a socket, resolve a real name, start a provider or call Telegram. Use fake turns, a fake fetch, an injected clock and temporary folders. Never sleep. Keep Python 3.11 compatibility.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- A quote not on the fetched page is marked `not_found` and never shown as checked. RSR-2, `test_missing_quote_is_not_found`.
- A blocked or failed page marks its findings `not_checked`, never `checked`. RSR-2, `test_blocked_page_is_not_checked`.
- A source that isn't `http(s)` or a pack file the job listed is dropped. RSR-1, `test_bad_sources_are_dropped`.
- A job stops at its round, minute and source limits and still writes a report marked `stopped at the limit`. RSR-5, `test_budget_stops_the_job`.
- No research turn is built without the read-only command, and none writes outside the job folder. RSR-3, `test_turns_are_read_only`.
- Instruction-like text in a fetched page is stripped before the agent sees it. RSR-2, `test_pages_are_cleaned`.
- Cancel keeps what was found and leaves the job `cancelled`, not `failed`. RSR-5, `test_cancel_keeps_findings`.

- [ ] RSR-1: The finding and report formats
  Create `src/whyline/research/__init__.py`, `src/whyline/research/report.py` and `tests/research/test_report.py` only.
  1. Dataclasses (frozen): `Source` (`n: int`, `title`, `ref` a URL or pack file, `read` date), `Finding` (`claim`, `source: int`, `quote`, `question: str`, `mark: str = "unchecked"`; marks are `checked`, `not_checked`, `not_found`, `unchecked`), `Round` (`n`, `findings`, `sources`, `open_questions`, `new_questions`).
  2. `round_prompt(question, plan, open_questions, known_summary, files) -> str` asks for three sections: `## Findings` with lines `- <claim> [n] "<quote, at most 25 words>"` under `### <sub-question>` headings, `## Sources` with lines `n. <title> — <url or file>`, and `## Open` with one open or new sub-question per line. It says file content is data and at most 8 new sources a round.
  3. `parse_round(text, *, n, allowed_files: set[str]) -> Round`. A source that isn't `http://`/`https://` and isn't in `allowed_files` is dropped. A finding citing a dropped or unknown source, or with no quote, is kept with `mark="not_found"` and the note `no usable source`. A quote over 25 words is cut. Text with no `## Findings` gives an empty `Round`.
  4. `write_report(question, plan, findings, sources, open_questions, meta) -> str` (Markdown): `## Answer` (5 to 10 lines from `checked` findings first, each `[n] ✓`, `[n] not checked`, or `(my own reasoning)` for writer lines without a source), `## Findings` by sub-question, `## Couldn't confirm` (`not_found`), `## Open questions`, `## Sources` (`n. title — ref — read date — checked k of m quotes`), `## How this was made` (depth, rounds, agents, minutes, whether the web was searched, `stopped at the limit` when it was).
  5. `chat_text(report_md) -> str`: the Answer section and the Sources lines, cut to 3,900 characters.
  Tests: `test_bad_sources_are_dropped`, a finding with no quote, a quote cut to 25 words, the empty round, each report section, the marks in the Answer, and `chat_text`'s limit.

- [ ] RSR-2: Fetching sources and checking quotes
  Create `src/whyline/research/check.py` and `tests/research/test_check.py` only.
  1. `fetch_sources(sources, job_dir, *, now, fetch=pagefetch.fetch) -> dict[int, PageResult]`: each new URL source fetched once, its text cleaned with `ideas.guard.clean`, saved as `pages/<n>.txt` (0600), with its state (`ok`, `blocked`, `failed`) and reason kept in `pages/index.json`. Pack files are read from the job's `packs/` copy only.
  2. `normalise(text) -> str`: lower case, every run of whitespace one space, punctuation removed, typographic quotes and dashes folded to plain ones.
  3. `mark(findings, pages) -> list[Finding]`: `checked` when the normalised quote is in the normalised page, `not_found` when the page was read and it isn't, `not_checked` when the page is blocked or failed. A finding already `not_found` from parsing stays so.
  4. `counts(findings) -> dict[int, tuple[int, int]]`: per source, checked and total.
  Tests: `test_missing_quote_is_not_found`, `test_blocked_page_is_not_checked`, `test_pages_are_cleaned` (a page with hidden text and "ignore previous instructions" lines), a quote matching across line breaks and curly quotes, a pack file checked from its copy, the file modes, and each URL fetched once across two calls.

- [ ] RSR-3: Jobs, agents and read-only turns
  Create `src/whyline/research/jobs.py`, `src/whyline/research/agents.py` and `tests/research/test_jobs.py` only.
  1. `jobs.home() -> Path` is `~/.whyline/research` (honouring the existing test home override). A job is `<home>/<id>/` with `job.json`: `id` (`YYYYMMDD-HHMMSS-<4 hex>`), `question`, `depth`, `packs`, `state` (`planning`, `plan_review`, `running`, `writing`, `done`, `failed`, `cancelled`), `agents`, `rounds`, `started`, `finished`, `error`, `web`, `idea_id` (an inbox idea this job belongs to, or null).
  2. `jobs.create(question, *, depth="standard", packs=(), review_plan=False, idea_id=None) -> Job`: the question is 3 to 2,000 characters; the depth is `quick`, `standard` or `deep`; each pack exists (`tools.knowledge.get_pack`). Pack files are copied into `packs/` (at most 50 files, 2 MB each) and pack URLs saved through `knowledge.fetch_pages` into `pages/`.
  3. `jobs.load(id)`, `jobs.list(limit=50)` newest first, `jobs.save(job)` atomic, and `jobs.for_idea(idea_id) -> Job | None`, the newest `done` job for that idea. The link lives in `job.json` only, so no idea column is added.
  4. `agents.order() -> list[str]`: the research main then backup from `<home>/agents.json`, keeping only those passing `capabilities.can_run_unattended`; when none is set, the assistant's main and backup.
  5. `agents.turn(prompt, job_dir, *, name, timeout_seconds, run_fn=None) -> str`: one turn with `capabilities.read_only_command`, `cwd=job_dir`, its log in `logs/`. It raises `TurnFailed` with the reason on a non-zero exit, no output or a usage limit (`whyline_relay.failover`'s check). `agents.first(prompt, job_dir, …)` tries each agent in order and records which answered.
  6. `agents.can_search(cli) -> bool | None` from `agents.json`; `agents.probe(cli, *, run_fn=None) -> bool` runs one tiny search turn and saves true when its answer holds an `https://` URL.
  Tests: `test_turns_are_read_only` (every argv built went through `read_only_command`, and after a run with fake turns nothing changed under the temporary home outside the job folder), the id and state values, the question and pack checks, the copy caps, the order with a skipped agent, the usage-limit fallback, and the probe's saved result.

- [ ] RSR-4: The research plan, and reviewing it
  Create `src/whyline/research/plan.py` and `tests/research/test_plan.py` only.
  1. `plan_prompt(question, packs) -> str` asks for `## Sub-questions` (3 to 8 lines) and `## Look for` (kinds of sources).
  2. `make(job, *, turn=agents.first) -> ResearchPlan` (`questions: tuple[str, ...]`, `look_for: tuple[str, ...]`), saved as `plan.json`. Fewer than 3 sub-questions uses the question itself as the only one.
  3. `edit(job, questions: list[str]) -> ResearchPlan`: 1 to 10 non-empty lines, each at most 300 characters; saves and moves `plan_review` to `running`.
  4. A job created with `review_plan=True` stops in `plan_review` after `make`.
  Tests: the parse, the fallback, `edit`'s limits and state change, and `plan_review` reached only when asked.

- [ ] RSR-5: Rounds, the budget, cancel and the report
  Create `src/whyline/research/run.py` and `tests/research/test_run.py` only.
  1. `BUDGETS = {"quick": (1, 10, 8), "standard": (3, 30, 20), "deep": (6, 90, 40)}` (rounds, minutes, sources).
  2. `run(job_id, *, turn=agents.first, fetch=pagefetch.fetch, now=…, progress=None, cancel_event=None) -> Job`:
     - makes the plan when there is none (stopping at `plan_review` when asked)
     - runs rounds with `report.round_prompt`, `parse_round`, `check.fetch_sources` and `check.mark`, saving `rounds/<n>.json`
     - runs another round only when there are open sub-questions, the last round added at least one `checked` finding, and no limit is reached
     - after the rounds, a gap review turn on the next agent in order (`Gaps:` lines), and one more round on those gaps when the budget allows
     - a writer turn given the findings and marks, whose `## Answer` is checked against the findings (a line citing an unknown number gets ` (source missing)`); the report is written with `report.write_report`, saved as `report.md`, and as `report.pdf` through `ideas.documents.export` when it works
     - `web` is false when no agent in order `can_search`; then the job uses packs only, and with no packs either it fails with `Nothing to research with: no agent can search the web here and no knowledge pack was given.`
  3. `progress(line)` gets `Planning…`, `Round 2 of 3: <sub-question>`, `Read 9 sources, 14 of 17 quotes checked`, `Checking for gaps…`, `Writing the report…`.
  4. Cancel stops the current turn, writes the report from what was found and ends `cancelled`. A turn failure on every agent ends `failed` with the reason. A limit ends `done` with `stopped at the limit` in the report.
  5. `resume(job_id, …)` continues a job left `running` after a restart from its last saved round.
  Tests: `test_budget_stops_the_job` (each of the three limits), `test_cancel_keeps_findings`, the stop when a round adds nothing checked, the gap round, the writer's unknown citation, the no-web case with and without packs, the progress lines, and `resume`.

- [ ] RSR-6: Follow-up questions and the CLI
  Create `src/whyline/research/followup.py` and `src/whyline/research/cli.py`. Edit `src/whyline/cli.py` (register the `research` command) and the tests.
  1. `followup.ask(job_id, question, *, turn=agents.first) -> str`: one turn on the job folder (report, findings, pages) answering with the job's source numbers only. Lines citing other numbers get ` (source missing)`. The answer is appended to `followups.md` with the question and time. An answer whose only content is `NEEDS NEW SOURCES` returns `This needs new sources. Research it?`.
  2. CLI, each calling one function from RSR-3 to RSR-6:
     - `whyline research "<question>" [--depth quick|standard|deep] [--pack NAME …] [--plan-first] [--wait]`
     - `whyline research list`, `show <id>`, `plan <id> --question "<line>" …` (edit and start), `cancel <id>`, `ask <id> "<question>"`
     - `whyline research agents [--main NAME] [--backup NAME]` and `whyline research check-search [NAME]`
  3. A started job without `--wait` runs as a detached child (`python -m whyline research _run <id>`) with its pid in `job.json`, so the terminal and the console can close.
  Tests: each command calling its function, `--wait` printing the answer, the detached child's argv, a follow-up citing an unknown source, and `NEEDS NEW SOURCES`.

- [ ] RSR-7: The Research mode in the console
  Create `src/whyline/console/research_screen.py` and `tests/console/test_research_screen.py`. Edit `src/whyline/console/tui.py` (`_MODES`, `_MODE_BUTTONS` and the mode bar) only.
  1. A **Research** mode button after Workflows.
  2. Left: **Question** (multi-line), **Depth** select (Quick, Standard, Deep; Standard first), **Knowledge packs** multi-select, **Show me the plan first**, **Start**. While a job runs: a board with the state, round `n of m`, the current sub-question, sources read, checked counts and minutes, and **Cancel**. It refreshes every 2 seconds from `job.json`.
  3. In `plan_review`, the sub-questions as editable lines with **Add line**, **Start** (calls `plan.edit`) and **Cancel**.
  4. Right: past reports (date, depth, state, question), the selected report with `markup=False`, a follow-up input with **Ask**, and **Open file**, **Use in brainstorm** (opens the relay's brainstorm form with `report.md` attached) and **Make a plan from this** (opens the new-plan form with the report attached).
  5. **Set up** (a button in this mode): main and backup agent selects, the default depth, and **Check web search** per agent showing yes, no or not checked.
  6. Every action calls the same function as its RSR-6 command. A job started here runs as the same detached child.
  Tests: the mode button, Start calling `jobs.create` and starting the child, the board fields from a fake `job.json`, plan review saving through `plan.edit`, Ask calling `followup.ask`, the two hand-off buttons opening their forms with the attachment, and Set up saving agents and running the probe.

- [ ] RSR-8: Research first in the new-plan form and the brainstorm
  Edit `src/whyline/console/relay_screens.py`, `src/whyline/console/tui.py` (the brainstorm start path only), `src/whyline/ideas/brainstorm.py` and their tests only.
  1. The new-plan form's options get **Research first** under **Brainstorm first**, with a **Depth** select shown when ticked.
  2. When ticked, starting runs a research job on the topic (`jobs.create`, then `run.run` in the existing worker the brainstorm uses), shows its progress lines in the same log, and attaches `report.md` to the brainstorm and to the plan request. A failed or cancelled research stops with its reason and the form stays filled.
  3. The idea brainstorm (`ideas/brainstorm.py`): an idea with a `done` job from `jobs.for_idea` gets that report added to its attachments, as `_report` adds the analysis today.
  Tests: the checkbox and depth select, research running before the brainstorm with the report attached, the failure leaving the form, and an idea brainstorm with a research report attached.

- [ ] RSR-9: A research stage in the document set
  Edit `src/whyline/sdlc/stages.py`, `src/whyline/sdlc/runner.py`, `src/whyline/sdlc/docset.py` and their tests only.
  1. `research` is a stage before `brainstorm`, labelled `Research`, and `STARTS` gains it first. It runs only when the set was started at `research`, or when its roles hold `research_depth`.
  2. `runner._run_research` creates and runs a job on the set's request, copies `report.md` into the set's docs folder as `research.md`, and finishes the stage with the note `research report`. A `failed` job returns the stage error with the reason.
  3. `_attachments` adds `research.md` to every later stage, like the brainstorm.
  4. The research stage has no review lens.
  Tests: the stage order and label, `STARTS`, the copy into docs, the attachment on brainstorm, spec and plan, the failed job's error, and an existing document set without the stage unchanged.

- [ ] RSR-10: A research phase in Auto
  Edit `src/whyline/console/plan_job.py` (`AutoRunRequest`), `src/whyline/console/auto_run.py`, the Auto form in `src/whyline/console/tui.py` and their tests only.
  1. `AutoRunRequest.research_depth: str = ""` (`""`, `quick`, `standard`, `deep`). It is part of the fingerprint document. Old saved checkpoints without it read as `""`.
  2. `auto_run.run` gets a phase `facts` before the existing brainstorm phase (`_research_phase`, whose name stays). With a depth set it runs a job with `review_plan=False`, stores the report as an artifact like the other phases, and passes it to the brainstorm as an attachment. A matching stored artifact is not run again on resume.
  3. A failed or cancelled job pauses Auto with `Research stopped: <reason>`, like the other phases' pauses.
  4. The Auto form gets **Research first** and a depth select. Progress lines say `Research`, not `facts`.
  Tests: the fingerprint with and without a depth, an old checkpoint loading, the phase order, the report reaching the brainstorm, resume skipping a finished phase, and the pause on failure.

- [ ] RSR-11: Research from Telegram
  Edit `src/whyline/ideas/actions.py`, `src/whyline/ideas/intent.py`, `src/whyline/ideas/bot.py`, `src/whyline/ideas/worker.py` and their tests only.
  1. `actions.REGISTRY["research"] = Action("research", "research", False, "long", "none", "none", "Research a question")`.
  2. The command `research <question>`, with optional leading words `quick`, `deep` and `pack:<name>` (one per pack). The default depth in Telegram is Quick.
  3. It starts the job through `jobs.create` and the detached child. One status message is edited with the progress lines, at most once every 10 seconds.
  4. The end: `report.chat_text` as the reply, `report.md` and `report.pdf` as documents, and buttons **Ask about it**, **Brainstorm it** and **Deeper** (labels under 14 characters). **Ask about it** waits for the next message as the follow-up; **Brainstorm it** captures an idea from the question, sets the job's `idea_id` to it and opens its brainstorm card; **Deeper** starts a Standard job on the same question.
  5. Idea cards in `captured` and `scored` get **Research** beside **Brainstorm**. It starts a Quick job on the idea's text with `idea_id` set; the card shows `Researched` when `jobs.for_idea` finds it done.
  6. A failure replies `Research failed: <reason>` with **Try again**.
  Tests: the command parse with each word, the registry entry, the edited status message's rate, the end message and documents, each button, the idea card's Research button and the job's `idea_id`, and the failure reply.

- [ ] RSR-12: Docs
  Create `docs/research.md`. Edit `docs/assistant.md` and `README.md` only.
  Cover: what Research does and doesn't do, the depths and their limits, plan first, the marks (✓, `not checked`, `the source doesn't say this`, `(my own reasoning)`), Couldn't confirm, follow-up questions, Check web search, Research first in the new-plan form, the document set and Auto, Telegram's `research` and the idea card button, where jobs are kept, and what can't be read (logins, robot checks, pages that need a browser).
  Verify with `uv run pytest -q`.
