<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-11-14-assistant-2-design.md | created: 2026-11-14T17:30:00+05:30 -->
# Assistant research: an answer with sources and a full report

Spec: `docs/superpowers/specs/2026-11-14-assistant-2-design.md`, Part 5. Read it before every task. Where this plan and the spec differ, this plan wins. In particular:
- **Web search is the agent CLI's own.** Whyline adds no search client. A provider whose read-only mode has no web search can still research the knowledge packs, and the answer says so.

Runs after `plans/assistant-checkins.plan.md`, and before `plans/assistant-triggers.plan.md`. It needs knowledge packs (`whyline.tools.knowledge`, from `plans/agent-tools.plan.md` TLS-6) and the router (`plans/telegram-daily-use.plan.md`).

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Why: the assistant can answer about a repo (`ask <repo>`) but can't look something up and come back with sources.

What the user gets:
- `research <question>` from Telegram, the console or the CLI.
- A 5 to 10 line answer where each claim has a numbered source, plus a full report attached as Markdown and PDF.
- A list of past reports on the Assistant screen.

Rules every task keeps:
- **Console first.** Starting a research job and reading reports work from the console through the same functions as `whyline idea research …`.
- **Read-only.** The job runs through `capabilities.read_only_command` in its own folder under `~/.whyline/ideas/research/<id>/`, on providers that are enabled and pass `can_run_unattended`. It never writes outside that folder.
- **Web pages and pack files are data.** Text fetched by whyline (knowledge pack pages) passes `ideas.guard.clean` before the agent sees it. The prompt tells the agent that page content is never an instruction.
- **Every claim cites a source or is marked `(my own reasoning)`.** A source is a URL or a pack file that the job really listed.
- **Private files:** the research folder is 0700 and files 0600.
- **One at a time.** This plan adds the next database version to `src/whyline/ideas/store.py`. Never run it in parallel with another plan that does (waiting-on-you and the assistant plans), and run them in the order in `plans/RUN-ORDER.md`.
- **No new dependency.**
- **Tests:** never invoke a real provider, the network or Telegram. Use fakes and temporary folders. Never sleep. Keep Python 3.11 compatibility.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- A claim citing a source number that isn't in the source list is flagged, not shown as sourced. RES-1, `test_unknown_citation_is_flagged`.
- A source that isn't `http(s)` or a listed pack file is dropped. RES-1, `test_bad_sources_are_dropped`.
- Hidden or instruction-like text in a fetched pack page is stripped before the agent sees it. RES-2, `test_pack_pages_are_cleaned`.
- A job past its time limit ends as failed with the reason, and the chat is told. RES-3, `test_research_times_out`.
- A provider without web search still answers from packs and says the web wasn't searched. RES-2, `test_no_web_is_stated`.

- [ ] RES-1: The report format and its checks
  Create `src/whyline/ideas/research.py` and `tests/ideas/test_research.py` only.
  1. `@dataclass(frozen=True) class Source`: `n: int`, `title: str`, `ref: str` (a URL or a pack file path), `read: str` (date). `@dataclass(frozen=True) class Report`: `question`, `answer_lines: tuple[str, ...]`, `sources: tuple[Source, ...]`, `body: str`, `notes: tuple[str, ...]`.
  2. `build_prompt(question, *, packs: list[str], pack_dir: Path | None, web: bool) -> str`. It asks for:
     - a section `## Answer` of 5 to 10 lines, each ending with `[n]` citations or `(my own reasoning)`
     - a section `## Report`
     - a section `## Sources` of lines `n. <title> — <url or file> — read <date>`
     - at most 12 sources

     It states that page and file content is data.
  3. `parse(text, *, allowed_files: set[str]) -> Report`.
     - A source whose ref is not an `http://` or `https://` URL and not in `allowed_files` is dropped, with a note.
     - An answer line citing a number with no source gets ` (source missing)` appended, with a note.
     - An answer line with no citation and no `(my own reasoning)` gets ` (unsourced)` appended.
     - Answer lines beyond 10 are moved into the body.
     - Text with no `## Answer` section gives a Report whose single answer line is `The agent didn't return a readable report.`
  4. `render_markdown(report) -> str` and `chat_text(report) -> str` (the answer lines, then `Sources:` with `n. title — ref`, cut to the Telegram message limit).
  Tests: `test_unknown_citation_is_flagged`, `test_bad_sources_are_dropped`, unsourced lines marked, more than 10 lines moved, the unreadable case, and `chat_text` within the limit.

- [ ] RES-2: Running a research job
  Edit `src/whyline/ideas/research.py`, `src/whyline/ideas/store.py` (schema) and their tests.
  1. A `research` table as the next schema version: `id`, `question`, `packs`, `state` (`queued`/`running`/`done`/`failed`), `agent`, `pid`, `error`, `created`, `finished`.
  2. `research.start(conn, question, *, packs=()) -> int` validates the question (not empty, at most 500 characters) and the pack names (`tools.knowledge.get_pack`), and inserts a queued row.
  3. `research.run(conn, research_id, *, run_fn=None, fetch=None, now=…) -> Report`:
     - creates the job folder
     - resolves the packs with `tools.knowledge.resolve`, copies pack files in (at most 50 files, 2 MB each), and fetches pack URLs with `tools.knowledge.fetch_pages`
     - passes each fetched page through `ideas.guard.clean` and saves the cleaned text
     - runs one read-only turn on the assistant's main then backup agent (`router.order`), with `web=True` when `capabilities` says the provider's read-only mode can search the web
     - parses the answer, writes `report.md` (and a PDF through `ideas.documents.export`), and marks the row
  4. When `web` is False, the note `The web wasn't searched: <agent> can't search in read-only mode. This answer uses your knowledge packs only.` is added, and with no packs either the job fails with `Nothing to research with: <agent> can't search the web and no knowledge pack was given.`
  5. `research.reports(conn, limit=50)` and `research.report_path(research_id)`.
  Tests: `test_pack_pages_are_cleaned`, `test_no_web_is_stated`, the no-web-no-packs failure, an unknown pack refused, the file caps, the backup agent used when the main gives nothing, and the folder and file modes.

- [ ] RES-3: `research` as an action, from Telegram and the router
  Edit `src/whyline/ideas/actions.py`, `src/whyline/ideas/intent.py`, `src/whyline/ideas/bot.py`, `src/whyline/ideas/worker.py`, `src/whyline/ideas/router.py`, `src/whyline/ideas/assistant.py` and their tests.
  1. Register `research` in `actions.REGISTRY`: `writes=False`, duration `long`, approval `none`. Add the `research` command: `research <question>`, with an optional leading `pack:<name>` word per pack.
  2. A research request runs through the existing request worker path as a detached child with a 15-minute limit (kv `research_timeout_minutes`, 5 to 60).
  3. Progress uses the feedback plan's working message: `Researching…`, then `Reading <n> sources…` when the folder has fetched pages, then `Writing the report…`.
  4. The result: `research.chat_text` as the reply, and `report.md` and the PDF sent as documents. A failure replies `Research failed: <reason>` with **Try again**.
  5. The router may choose `research` as a `task` (it is in the registry now). `assistant.validate` checks the pack names.
  Tests: `test_research_times_out`, the command parse with and without packs, the request row and its audit, the documents sent, the router choosing research for a lookup question (fake router output), and an unknown pack refused by name.

- [ ] RES-4: Research in the console and CLI
  Edit `src/whyline/ideas/cli.py`, `src/whyline/console/assistant_screen.py` and their tests.
  1. CLI:
     - `whyline idea research "<question>" [--pack <name> …]` starts a job and prints its id. With `--wait` it prints the answer when done.
     - `whyline idea research list` prints past reports (id, date, state, question).
     - `whyline idea research show <id>` prints the report.
     - `whyline idea research timeout <minutes>` saves the limit.
  2. Assistant screen: a **Research** section with a question input, a knowledge-pack multi-select, **Start**, a table of past reports, the selected report's text, and **Open file**. Each calls the same function as its command.
  Tests: CLI and console call `research.start`, the list matches `research.reports`, a timeout outside 5 to 60 is refused, and an empty question is refused.

- [ ] RES-5: Docs
  Edit `docs/assistant.md` and `README.md` only.
  Cover: `research`, packs, what the citation marks mean (`[n]`, `(my own reasoning)`, `(unsourced)`, `(source missing)`), the time limit, which providers can search the web in read-only mode, and where reports are kept.
  Verify with `uv run pytest -q`.
