# SDLC upgrade: a real git flow, a product owner, evidence, and a definition of done

Status: draft for review, 2026-11-14. Builds on the SDLC pipeline (`plans/done/sdlc-pipeline.plan.md`, done), the RAAID log (`plans/raaid-log.plan.md`, planned) and Release. Four parts, each its own small plan, in the order below. Runs after `plans/raaid-log.plan.md`.

## Where whyline stands

It already has:
- One product PRD, and per feature a spec or design, a plan with a test plan, and a build record, each with versions, approvals and an out-of-date flag (`whyline.sdlc.docset`, `product`, `record`).
- Requirements traced into the plan and test plan (`sdlc.trace.coverage`), and a drift check in the build record.
- Fresh-eyes reviews through five lenses (`sdlc.goldfish`, `sdlc/lenses/`).
- A relay with implementer, tester, reviewer and release roles on different agents.
- A pull request body and `open_pr` for a closed document set (`sdlc.close`).

## Problems

1. **Work doesn't start from the latest main.** A relay branches from whatever is checked out. It never fetches. "HEAD is behind origin/main" then appears at release time, and Bring in main has to fix it late.
2. **Nothing reaches main through a pull request.** `main` is not protected on GitHub and no pull request has ever been opened. Release pushes straight to `main`. `sdlc.close.open_pr` exists but is a button at the end of a document set, and hand-written plans never use it.
3. **Nobody owns "what next" or "is it accepted".** There is a PRD writer but no backlog, no priority, and no step where the user accepts the result against what was asked.
4. **The tester proves the suite passes, not that the requirement is met.** `trace.coverage` shows which requirement a test plan line covers, but nothing checks that each one has a named test that ran and passed, and nothing shows the feature working.
5. **"Done" is spread over many screens.** Documents, coverage, review findings, RAAID items and CI each live somewhere else.
6. **Nothing is learned between features** beyond `whyline note`.

## Part 1: Git flow (plan `sdlc-git-flow`)

Revised 2026-11-22 with the user's decisions: one pull request per plan, opened when the relay finishes; a **Who merges** setting; each plan in its own worktree; the release's version bump straight to `main` unless `main` is protected; and Park and Reopen (Part 1b).

- **Start from the latest main.** Starting a relay (console **Run**, `whyline relay start`, Auto, and an idea's `do`) first fetches `origin/<default branch>`.
  - When the checkout is on the default branch and behind, it fast-forwards and then branches.
  - When it can't fast-forward (local commits not on origin, or a dirty tree), it stops and says which, with the choices **Push them first**, **Branch from origin/main anyway** and **Cancel**.
  - Offline, it says `Couldn't reach GitHub; starting from your local main` and goes on.
- **Deliver as**, per repository, in Relay → Set up and `whyline relay settings deliver`: **Pull request** or **Straight to main** (today's behaviour).
  - Pull request is offered only when the project is on GitHub: an `origin` remote on github.com whose default branch exists there. Otherwise Set up shows it unavailable with the reason `Not on GitHub yet; publish it first`.
  - Until the user picks, the default is Pull request for a project on GitHub and Straight to main otherwise. Straight to main takes exactly today's steps.
- **Who merges**, a global setting in Settings and `whyline settings who-merges you|auto`: **You** (the default) or **Automatic**. Relay → Set up can change it for one run.
  - **You:** a pull request waits, however green, until the user presses **Merge**. Nothing reaches `main` without that click, in every Release and Auto mode.
  - **Automatic:** whyline merges once the pull request's checks pass, then says it did (console and Telegram).
- **Each plan in its own worktree.** With Pull request, starting a plan makes a git worktree on a new branch `relay/<plan>` from the fresh `origin/<default>`, at `~/.whyline/worktrees/<project>/relay-<plan>` (the existing `whyline.worktrees` layout), outside the project so tests and scans never walk into it. The console moves to the worktree for the run (as picking a repository does) and shows `Plan worktree: <plan>` with **Back to <project>**. The project's own folder stays on the default branch.
- **One pull request per plan, when the relay finishes.** When the last task is approved, whyline pushes the branch and opens the pull request, or updates the one that exists.
  - The body holds the plan's name and its ticked tasks, links to the document set when there is one, and later the acceptance table (Part 2), the evidence (Part 3) and the checklist (Part 4).
  - The console shows the pull request with its checks. RCR's Why, Rerun and Ask an agent work on a failed check.
  - **Merge** is enabled once the checks pass. It merges with a merge commit, deletes the branch on GitHub, fast-forwards the project folder's default branch, removes the worktree, deletes the local branch with `git branch -d`, and moves the console back to the project.
- **Release from main.** With Pull request, Release runs from the project folder on the default branch; Bring in main isn't needed.
  - The version bump is a release commit whyline makes itself. It goes **straight to `main`**, as today.
  - When `main` is protected on GitHub, Release instead pushes `release/v<version>`, opens a small pull request, waits for its checks, and merges it under Who merges. The tag is made on the merged commit.
- **Protect main.** Release → Set up gets **Protect main on GitHub**: no direct pushes, the CI checks required. It is offered only with Pull request, it asks first, and it can be undone from the same place.
- **Plan-only commits.** A commit that touches only `plans/` and `docs/` may still go straight to `main` while `main` is unprotected. Publishing them through a pull request is a follow-up.
- **Old branches.** After a release, merged local `relay/*` branches and leftover worktrees whose branch is merged are offered for cleanup.

## Part 1b: Projects, Park and Reopen (plan `sdlc-git-flow`)

- **Projects list.** A global list at `~/.whyline/projects.json`: each project's folder, GitHub address, default branch, last release, and whether it is parked. A project is added when the console opens it. Console: **Projects**, reached from the repository picker. CLI: `whyline project list`.
- **Park.** Frees a finished project's folder from the laptop. It first checks, and refuses with the list, when any of these hold:
  - a commit on any local branch that isn't on GitHub
  - a stash
  - a changed or untracked file git doesn't ignore
  - a plan worktree still present
  - a relay or a release running or paused
  - an open pull request from a plan (named, so the user can merge or close it first)

  Then it saves whyline's local-only files (the ignored files under `.whyline/`, such as relay logs, pauses, chat and issues) compressed to `~/.whyline/parked/<repo-key>.tar.gz`, moves the folder to the Trash (macOS; elsewhere it deletes after the user types the project's name), and marks the project parked. It always asks first, in every mode.
- **Reopen.** Clones the project from GitHub to its old folder (or one the user picks), restores the saved local files, runs `uv sync` when the project has a `uv.lock`, marks it not parked, and opens it in the console.

## Part 2: Product owner and acceptance (plan `sdlc-product-owner`)

- **Acceptance criteria in the PRD and spec.** Each requirement (`R1`, `R2`… as `sdlc.trace.requirements` reads them today) gets one or more acceptance criteria: `R1.A1: Given … when … then …`. The templates gain the section and the writer prompt asks for them. A spec with a requirement that has no criterion can't be approved; the reason is shown.
- **A backlog.** `docs/product/backlog.md`, kept by whyline: one row per candidate feature with a title, a one-line outcome, a priority (Now, Next, Later), a size, and its source (an idea from the Idea Inbox, a RAAID action, a PRD gap, or typed). Ideas marked planned and RAAID actions can be sent to it with one action.
- **A product owner agent.** A read-only role (default: the PRD writer) with two jobs:
  - **Groom:** propose an order for the Now and Next rows with a one-line reason each. The user accepts or reorders. Nothing moves without the user.
  - **Accept:** after the build, check each acceptance criterion against the evidence and say met, not met or can't tell, with the reason.
- **Acceptance is the user's.** The build ends at an **Accept** step: the table of criteria with the product owner agent's reading and the evidence, and **Accept**, **Accept with follow-ups** (each becomes a RAAID action and a backlog row) or **Send back** (names the criteria, and the relay reopens those tasks). The acceptance is recorded as a `whyline note` and in the build record.
- **Console:** a **Backlog** entry in Docs (list, add, priority, **Groom**, **Plan this**, which opens the Plan form filled in). CLI: `whyline docs backlog list|add|set|groom`, `whyline docs accept <slug>`.

## Part 3: Tests that trace, and evidence (plan `sdlc-evidence`)

- **Every criterion names its test.** The test plan maps each acceptance criterion to at least one check: an automated test by its id (`tests/x/test_y.py::test_name`) or a manual check with steps. `trace.coverage` gains criteria: covered, uncovered, and covered only by a manual check.
- **The tester works from that list.** The tester's prompt gets the criteria for this task and their tests. Its handoff records, per criterion, the test id and whether it passed. A named test that doesn't exist or didn't run is a failure, not a pass.
- **Results are read, not claimed.** After the tester's run, whyline runs the named tests itself (`uv run pytest <ids> --junitxml`, or the repository's own test command from Release → Set up) and reads the result file. The table shows whyline's result. A mismatch with the tester's claim is flagged and raises a RAAID issue.
- **A demo step.** For a feature with a user-visible change, the plan may name a demo: a command to run and what to capture.
  - CLI output is captured as text.
  - A console (Textual) screen is captured as an SVG screenshot through the app's own test pilot.
  - A web page is captured through the agent's browser tool when it has one.
  - The capture is saved under `docs/sdlc/<slug>/evidence/` and linked from the build record and the pull request.
  - A demo is optional. With none, the evidence is the test results.
- **Manual checks** are listed for the user in the Accept step with **Passed** and **Failed** per check.

## Part 4: Definition of done, estimates and retrospective (plan `sdlc-done`)

- **One checklist per feature**, in Docs, in the pull request and in `whyline docs done <slug>`:
  - documents approved and not out of date
  - every acceptance criterion covered and passing (or accepted with a follow-up)
  - review findings closed or accepted
  - RAAID: no open blocker issue or high risk for this feature (shown, with a link; it warns and never blocks)
  - CI green
  - accepted by the user
  - build record written

  Each line shows done, not done or not applicable with the reason. Release shows the checklist before the first irreversible step. A line that is not done warns; only the user decides to go on.
- **Estimate and actual.** The plan stage records an estimate per task (S, M, L) and the product owner's size for the feature. The build record adds the actuals: rounds per task, wall time, agent time and tokens where the CLI reports them. The Stages line shows the estimate. The retrospective compares them.
- **A retrospective.** After acceptance, one read-only turn reads the build record, the review rounds, the pauses and the RAAID items, and writes `retro.md`: what went well, what cost rounds, and at most 3 proposed rules. Each proposed rule is a card: **Add to the plan rules** (appended to the repository's `docs/product/plan-rules.md`, which every new plan's writer prompt includes), **Make it a RAAID action**, or **Skip**. Nothing is added without the user.
- **Roles on one screen.** The Stages line and the Plan form name every role in order: Product owner → Writer → Reviewer → Architect (Large) → Test planner → Implementer → Tester → Code reviewer → Release → Product owner (accept). The same agent may not both write and review a document, and may not both implement and code-review a task; the form says so when the choices break that.

## Goals

- Work starts from the latest `main` and returns to it through a checked pull request.
- Every requirement has a criterion, every criterion a test, and every test a result whyline read itself.
- One place says whether a feature is done, and the user makes the final call.

## Non-goals

- A hosted service, several human users, or permissions between people.
- Story points, sprints or velocity charts.
- Replacing GitHub's review with whyline's, or other hosts than GitHub.
- An agent that accepts without the user, or merges without the user unless the user set Who merges to Automatic.

## Anti-goals

- A checklist or a RAAID item that blocks a release without the user being able to go on.
- A tester's "passed" trusted without whyline reading the result.
- Protecting `main` without asking, or in a way that locks the user out of their own repository.
- Process that makes a one-line fix need a PRD. Small stays small: a short spec, one criterion, its test.

## How it fits the code today

- **Relay start:** the console's start path (`console/relay_ops.py`, `console/auto_run.py`), the relay's own preflight (`whyline_relay.preflight`, `gitcheck`) and `ideas/run.py`. The fetch-and-fast-forward check is a whyline function called before each of them, so no whyline-relay release is needed.
- **Release:** `release/plan.py` and `release/github.py` build the steps (`push`, `ci`, `tag`, `github_release`). Only when `main` is protected does the release swap `push` for push-branch plus open-PR, point `ci` at the pull request's checks (`release/workflows.py`, `ci_failure.py`), and add `merge` before `tag`. `release/source.py`'s Bring in main stays for Straight to main.
- **Plan worktrees:** whyline-relay keeps every file under the folder it starts in and only switches branch when it isn't already on it (`gitcheck.ensure_branch`), so a relay started in a worktree on `relay/<plan>` needs no whyline-relay change. The console moves there with `console/repl.switch_repo`, the same call the repository picker makes. `whyline.gitdir` (0.3.79) already lets Release work from a worktree.
- **Relay finished:** `WhylineConsoleApp._relay_finished` in `console/tui.py` is where the pull request is opened.
- **Pull request body:** `sdlc.close.pr_body` and `open_pr` are reused and extended, and work without a document set.
- **Criteria and coverage:** `sdlc/trace.py` (`requirements`, `plan_covers`, `test_covers`, `coverage`), the templates in `sdlc/templates/`, and the approval check in `sdlc/review.py`.
- **Tester evidence:** the relay's handoff record, `whyline_relay.testplan` scenarios, and `sdlc/record.py`'s `trace_table`.
- **Backlog and acceptance:** new modules under `whyline/sdlc/`, the Docs screen (`console/docs_screen.py`) and `sdlc/cli.py`.
- **RAAID:** `whyline.raaid` once built. The checklist reads it; follow-ups and retro actions add to it through `raaid add`.

## Calls I made (please check)

- **Pull request is the default for projects on GitHub** (the user's decision, 2026-11-22); Straight to main for the rest. Protecting `main` stays opt-in.
- **Worktrees live under `~/.whyline/worktrees/`**, not inside the project, so pytest, security scans and file watchers never walk into a second copy of the code.
- **The console moves into the worktree for the run** rather than learning a second root: 244 places read `session.root`, and moving is what the repository picker already does.
- **Who merges Automatic needs only passing checks.** The relay's reviewer has already approved every task before the pull request opens.
- **Park moves the folder to the Trash on macOS** rather than deleting it, so a mistake can be undone.
- **Merge commits, not squash**, so the relay's per-task commits and their `whyline note` history stay readable.
- **GitHub review is not required** by default: there is one person. CI is the gate.
- **The checklist warns and never blocks**, matching the RAAID plan's rule.
- **Whyline reruns the named tests itself.** It costs a second test run per task, and removes trust in the tester's word.
- **The product owner is an agent that proposes; acceptance is always yours.**
- **Order:** git flow first (it fixes a problem that bites every release), then product owner, evidence, done.
