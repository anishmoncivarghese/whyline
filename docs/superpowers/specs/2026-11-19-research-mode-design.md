# Research: a question in, a checked report out, and research before brainstorm

Date: 2026-11-19. Status: draft for review.
Plans: `plans/research.plan.md` (RSR-1..12). It replaces `plans/assistant-research.plan.md` (RES-1..5), and amends `plans/telegram-daily-use.plan.md` (RT-8) and `plans/job-search-5d-after-apply.plan.md` (JAA-8).

## Why

whyline can brainstorm, design, plan, build, test, review and release. What it can't do is go and find out. Today:

- **Brainstorm guesses.** Each model "researches on its own" from what it already knows. Nothing is looked up, and nothing says where a claim came from.
- **The planned research (RES-1..5) is one pass.** One read-only turn, a 5 to 10 line answer, sources the agent lists. Nothing checks that a source says what the answer claims, and nothing goes back for what is still unknown.
- **Telegram has to be told.** The router (RT-1..7) can choose `brainstorm` for a message, but not "find out first".

Google's Deep Research shows the shape that works: an optional plan you can edit, a background job that searches, reads, notices gaps and searches again, then a long cited report you can ask follow-up questions about. It only researches; it never builds.

whyline can do one thing better: **it checks the citations itself.** It fetches each cited page and looks for the quoted words. This is the same rule as the watch agents, where the model reads a number but whyline compares it.

## What the user gets

- **A Research mode** in the console beside Chat, Relay, Agents, Assistant and Workflows. Ask a question, pick Quick, Standard or Deep, optionally see the plan first, then watch it work. Reports are listed, can be opened, and can be asked follow-up questions.
- **Checked citations.** Every claim carries a source and a short quote. whyline marks each one: ✓ checked, `not checked` (the page couldn't be read), or `the source doesn't say this`.
- **Research before brainstorm.** A **Research first** box in the new-plan form, a Research stage in the document set, and a research phase in Auto. The report is attached to the brainstorm, spec and plan, so they can cite it.
- **Research from Telegram.** `research <question>`, a **Research** button on an idea's card, and a router that can choose research by itself, or ask "Research, brainstorm, or both?".
- **One engine** used by all of these, the job search company brief (JAA-8) and, later, saved agents.

## Goals

- Answers whose claims can be traced to a page that really says them.
- Research that keeps going until nothing new turns up or the budget runs out, and stops on its own.
- Brainstorms and specs that start from facts when the question needs facts.
- Asking is never more work than today: one button or one word.

## Non-goals

- A search engine or search API in whyline. Search is the agent CLI's own.
- Research that writes code, changes a repository, sends mail or publishes. It is read-only.
- The goal loop (research → build → release → measure → next). It is a later design, after this and self-improvement part 1.
- Charts in reports. Tables only.

## Anti-goals

- A report that looks sourced when its sources don't say it.
- Page text choosing a command, a file, a URL to post to, or a recipient.
- A research job that runs for hours or spends without a limit.
- Research that starts by itself on something private: automatic research is a setting, off until the user turns it on.

## How it works

### The engine: `whyline.research`

A new top-level package, not under `ideas`, because the console, Telegram, the SDLC runner, Auto and agents all use it. Jobs are personal: `~/.whyline/research/<id>/`, folder 0700, files 0600. A job is a folder with `job.json` (question, depth, packs, state, agents, rounds, times, error, and the inbox idea it belongs to, if any), the plan, each round's notes, fetched pages and the report. **There is no database table**, so this plan never collides with the plans that add schema versions to `ideas/store.py`.

A job runs in five steps:

1. **Plan.** One read-only turn turns the question into 3 to 8 sub-questions and the kinds of sources to look for. With **Show me the plan first**, the job waits in `plan_review`: the user edits the sub-questions (add, remove, reword) and presses **Start**. Without it the plan is used as written.
2. **Rounds.** Each round is one read-only turn with web search. It gets the plan, the open sub-questions, a summary of what earlier rounds found, and the pages read so far (as files). It returns findings as lines `- <claim> [n] "<quote of at most 25 words>"`, a source list, and the sub-questions still open, plus any new ones it found worth asking.
3. **Check.** After each round whyline fetches every new source URL with `agents.pagefetch.fetch` (private addresses refused, robot checks reported, 5-minute cache), cleans it with `ideas.guard.clean`, saves it in the job folder and looks for each quote in it. The comparison ignores case, spacing and punctuation. A finding is `checked`, `not_checked` (page blocked or failed, or a pack file outside the job), or `not_found`.
4. **Stop rule.** Another round runs only when there are open sub-questions, the last round added at least one checked finding, and the budget allows. Each depth has a budget:

   | Depth | Rounds at most | Minutes at most | Sources at most |
   |---|---|---|---|
   | Quick | 1 | 10 | 8 |
   | Standard | 3 | 30 | 20 |
   | Deep | 6 | 90 | 40 |

5. **Gap review and write.** A second agent (the backup, or the next enabled one) reads the findings and lists what is missing or one-sided. One more round runs for its points when the budget allows. Then the writer turn produces the report from checked findings first. Findings that are `not_found` are left out of the answer and listed under **Couldn't confirm**.

Every turn uses `capabilities.read_only_command`, runs in the job folder, and goes through main then backup like the brainstorm does. A usage limit moves to the backup. A turn that returns nothing readable moves on. Cancel stops the current turn and keeps what was found.

**Web search per agent.** Whether a CLI can search the web in its read-only mode is not assumed. `research.can_search(cli)` comes from a one-time probe (a tiny search turn whose answer must contain a URL) that the user runs from Research → Set up, saved in `~/.whyline/research/agents.json`. An agent that can't search still researches the knowledge packs, and the report says the web wasn't searched.

### The report

`report.md`, with a PDF through `ideas.documents.export`:

- **Answer**: 5 to 10 lines, each ending with `[n]` and its mark, or `(my own reasoning)`.
- **Findings** by sub-question.
- **Couldn't confirm**: claims whose quote wasn't found.
- **Open questions**: what the budget didn't reach.
- **Sources**: `n. <title> — <url or pack file> — read <date> — checked 3 of 4 quotes`.
- **How this was made**: depth, rounds, agents, minutes, whether the web was searched.

A **follow-up** is one read-only turn on the job folder (report, findings, pages) that answers a new question about it, citing the same sources. It is saved in the job as `followups.md`. A follow-up that needs new sources says so and offers **Research this**.

### Where it shows up

**Console: Research mode.** A sixth mode button. Left side: question, depth, knowledge packs, **Show me the plan first**, **Start**; then the live board (round 2 of 3, sources read, checked counts, the current sub-question) with **Cancel**. Right side: past reports, the selected report, a follow-up box, and **Open file**, **Use in brainstorm**, **Make a plan from this**. Set up holds the agents (main and backup, Model select per agent from AMD-1 when it has landed), the default depth, and **Check web search** for each agent.

**Brainstorm and planning.**
- The relay's new-plan form gets **Research first** beside **Brainstorm first**, with a depth select. It runs a research job on the topic and attaches the report.
- The document set gets a `research` stage before `brainstorm` (`sdlc.stages`). Its report is an attachment to every later stage, like the brainstorm is today.
- **Auto** gets a phase before the brainstorm when Research first is ticked. In Auto there is no plan review: the plan is used as written, at the chosen depth. A failed research phase pauses Auto with the reason, like the other phases. (Auto's existing `_research_phase` is the brainstorm. It keeps its name in the code; the new phase is `facts`, and the progress line says `Research`.)
- **Make a plan from this** opens the new-plan form with the report attached and Research first already done.

**Telegram.**
- `research <question>` (optional `quick`, `deep` and `pack:<name>` words) starts a job. The status message is edited as rounds finish. The end is the answer and sources as a message, with `report.md` and the PDF attached, and **Ask about it**, **Brainstorm with it**, **Again deeper**.
- An idea card gets **Research** next to **Brainstorm** (labels stay under 14 characters). A researched idea's brainstorm gets the report attached.
- **The router (RT-8, in the Telegram plan).** `research` becomes a route. On a `brainstorm` route the router also says `needs_facts: true|false`. A setting chooses what happens then: **Ask** (the default: buttons **Research**, **Brainstorm**, **Both**), **Both** (research Quick, then brainstorm with it), or **Brainstorm only**. A message that is a plain lookup goes to `research` Quick.
- **Automatic research** for questions is a separate switch, off by default. When off, a question the router can't answer from memory gets its answer with **Research this** under it.

**Agents and workflows.** `research.start` and `research.wait` are the API the job search brief (JAA-8) uses. A saved agent step and a workflow step are left for the agent-calls and workflows plans; they call the same two functions.

## Rules

- **Read-only, always.** No research turn gets write tools. The job folder is the only place anything is written.
- **Page text is data.** Cleaned with `ideas.guard.clean`, given to the agent as files, never put in instructions, never used to pick a command, URL to post to, path or recipient.
- **whyline checks; the model doesn't vouch for itself.** A finding's mark comes from whyline's comparison only.
- **Budgets are hard limits.** Rounds, minutes and sources stop the job; the report is written from what was found, marked `stopped at the limit`.
- **Personal and global.** Jobs live in `~/.whyline/research` and never depend on the repository selected in the console. A research stage in a repository copies the report into that repository's docs; the job itself stays personal.
- **Console first.** Every action has a console counterpart calling the same function as its CLI command.
- **No new dependency.**

## How it fits the code today

- `agents/pagefetch.py` (WCH-3) is the fetcher: private-address refusal, robot checks, cache. Research adds nothing to it.
- `tools/knowledge.resolve` and `fetch_pages` give pack files and pages.
- `ideas/guard.clean` cleans page text.
- `agents/capabilities.read_only_command` builds every turn. `whyline_relay.failover` detects usage limits, as the router does.
- `console/adapters.run_brainstorm(..., attachments=)` already takes attachments; the report is one.
- `sdlc/stages.STARTS` and `sdlc/runner._attachments` get the new stage.
- `console/auto_run.run` gets the `facts` phase; `console/plan_job.AutoRunRequest` gets `research_depth` (empty means no research).
- `ideas/brainstorm._report` already attaches the analysis report to a brainstorm; the research report is added the same way.
- `ideas/actions.REGISTRY` gets `research` (writes nothing, long).

## Changes to other plans

- **`assistant-research.plan.md` (RES-1..5) is removed.** Everything it promised is in RSR, with checking, rounds and the console on top. Its Telegram parts move into RSR-11 and RT-8.
- **`telegram-daily-use.plan.md`** gets RT-8 (the research route, `needs_facts`, the Ask/Both/Brainstorm only setting and the automatic research switch), and its line "`research` is not a route target yet" changes to name RT-8.
- **`job-search-5d-after-apply.plan.md` JAA-8** uses `whyline.research.start` and `wait` instead of `ideas.research`, at Quick depth.
- **`assistant-memory.plan.md` and `assistant-triggers.plan.md`** lose their "before/after assistant-research" lines.
- **Run order:** `research.plan.md` runs after `release-resolve.plan.md` and before `telegram-daily-use.plan.md` (group 1e), because the router's RT-8 needs it and nothing in it needs the router.

## Calls I made (please check)

- **Checked quotes are the core feature.** A claim's quote must be found on the fetched page. Pages behind logins or robot checks can't be checked, and say so. This means some true claims show as `not checked`.
- **Three depths with fixed budgets** (table above), Standard the default in the console and Quick in Telegram.
- **No database table.** A job is a folder with a JSON file, so this plan can run before the Telegram plan without a schema clash.
- **Web search is probed, not assumed**, per CLI, from Research → Set up.
- **The router asks by default** when a brainstorm needs facts. **Both** and **Brainstorm only** are settings. Automatic research for plain questions is off until turned on.
- **Auto never waits for a plan review.** If you tick Research first in Auto, the research plan is used as written.
- **The goal loop is a later design.** It needs this and the self-improvement checks first.
- **Agent and workflow steps are left to those plans.** They call `research.start` and `research.wait`.

## Left to the builder

- The exact prompt wording, inside the format the plan fixes.
- The progress board's layout, inside the fields the plan names.
- How quotes are normalised before comparison, inside "case, spacing and punctuation".
