# Self-improvement: scheduled self-checks that find, plan, fix and report, across chosen repos

Date: 2026-11-02. Status: draft for the user's review. Plan: `plans/self-improvement.plan.md` (IMP-1..). Needs `plans/sdlc-pipeline.plan.md` first, because Self-improvement writes its fix plans through that pipeline in Auto at size Small.

## Problem

Today whyline only does work when someone starts it. Tests can break on a new Python, a dependency or a flaky macOS runner. Small bugs and rough edges pile up in every repo. Nobody notices until the next feature runs into them. The user wants whyline to look after their repos on a schedule:

- check each repo
- find what is wrong
- write a plan to fix it, run the plan, and update the repo through GitHub
- tell the user what happened, by Telegram and/or email, with a report attached

It should work on whyline itself and on any repo the user has chosen and given permission to in whyline.

## What the user gets

1. **Everything lives in Settings.** The console's **Settings** opens with two tabs: **AI providers**, which is today's screen, and **Self-improvement**. Settings is reachable from every mode, Relay included. The Self-improvement tab has:
   - **Self-improvement loop: On / Off.** Off is the default. Off means nothing runs on a schedule. **Run now** still works.
   - **How often:** **Daily**, **Weekly** or **Monthly**.
     - **Weekly** picks one or more weekdays, for example Mon and Thu.
     - **Monthly** picks a day of the month, 1–28 or **Last day**.
     - Daily has a **Weekdays only** checkbox.
   - **Time:** HH:MM, local time, for example 02:00. Below it: `Next run: Tue 3 Nov, 02:00` and `The Mac must be awake at that time; a missed run is reported when it wakes.`
   - **Messages:** **Combined** (default) or **One per repo**, plus **Delivery…** for Telegram and/or email, attachment Word or Markdown, and **Send test**.
   - **Limits:** run limit (minutes), max agent starts per run, and the defaults for new repos (Fix from, Max fixes, Max minutes per repo, Max changed lines, CI wait).
   - **Repos:** a table of the repos it looks after. Each row shows:
     - the permission level
     - the last result, for example `✅ all checks pass` or `🔧 PR #212 waiting for you`
     - when it last ran

     Buttons: **Add repo…**, **Edit…** and **Remove**.
   - **Run now** (all repos or the selected one, with a Dry run checkbox), **History** and **Pause / Resume**.
   - **Save** and **Cancel**, like the providers tab. Nothing changes until Save.

   **Relay → Set up** also shows one line for the current repo: `Self-improvement: Open PRs · daily 02:00 · Change…`, or `Self-improvement: off for this repo · Turn on…`. **Change…** opens that repo's row in Settings → Self-improvement. There is one place to save, and two ways in.
2. **Add repo…** takes a folder and a level, then runs **Check** with a ✓ or ✗ per line and a fix button where one exists:
   - the folder is a git repo with a GitHub `origin`
   - `gh` is signed in and can push to it (only for levels that open PRs)
   - a test command is set (from the relay setup, or typed here)
   - the relay is set up **and committed** (`.whyline/relay/config.toml` tracked), and `doctor` passes. This applies to Plan and above, since the SDLC roles come from it.
   - the review agent has a verified read-only setting (all levels)
   - the agents it needs can run unattended

   Saving shows what this level allows, in plain lines, and the user accepts them. That is the permission, the same way an agent is accepted today.
3. **Permission levels**, per repo:

   | Level | Checks | Writes a fix plan | Fixes on a branch, opens a PR | Merges the PR |
   |---|---|---|---|---|
   | **Report only** | ✓ | | | |
   | **Plan** | ✓ | ✓ (sent in the report, not run) | | |
   | **Open PRs** (default) | ✓ | ✓ | ✓ | |
   | **Merge when green** | ✓ | ✓ | ✓ | ✓ once CI passes |

   A **Release** level is not in this plan. It comes after `plans/release-button.plan.md` ships (see Out of scope).
4. **One schedule for all repos**, set in Settings: daily (optionally weekdays only), weekly on chosen days, or monthly on a day, at a time. It uses the existing agents heartbeat, so it needs no new launchd job. Turning the loop on also turns the agents heartbeat on when it is off, after saying so. One run covers every repo, **one repo at a time**, so a run can't use several agents' quotas at once.
5. **One combined message per run**, by Telegram, email or both. Delivery is set up the way it is for an agent. Example:

   ```
   whyline improve — Mon 2 Nov, 02:00 (ran 47 min)
   ✅ whyline-relay   all checks pass, nothing to do
   🔧 agentdock       2 findings → PR #212 opened, CI green, waiting for you
   📝 TradingPlatform tests fail on 3.11 → plan written (Plan level, not run)
   ⏭ cvfix           skipped: a relay is running there
   Full report attached.
   ```

   - **Attachment:** one Word file with a section per repo: checks and their output tails, findings, the plan, what the fix changed, and the PR link. `.md` is the other choice, through the existing `attach` setting.
   - **Heartbeat:** the message is sent **every run, even when everything passes**, so a missing message means Self-improvement didn't run.
   - **Combined or one per repo:** combined is the default.
   - **Immediate alerts**, sent as they happen, outside the digest:
     - a repo's run crashed
     - the guard stopped a fix
     - a time limit was hit
     - a scheduled run was missed because the Mac was asleep or off. This is sent on the next heartbeat after it wakes.
   - **Telegram buttons:** for each PR waiting at **Open PRs**, a separate card follows the digest, with **Merge #212** and **Close #212**. It is an assistant request card, sent through the assistant outbox:
     - **Action:** a new `improve_pr` action (merge or close)
     - **Expiry:** its confirm code lasts until the next scheduled run, or 24 hours if Self-improvement has no schedule
     - **Confirm:** a confirming tap is required whatever the action's approval policy says
     - **When not sent:** only when the Idea Inbox bot is set up and bound to the same chat as the Self-improvement delivery. Otherwise there is no card, and the digest has the link only.

     Email gets the PR link only.
6. **History** lists past runs. Each run opens its report, per-repo logs, the plan, the PR, and **Resend**.
7. **A CLI for scripts**, saving through the same functions as the console:

   ```
   whyline improve status | run [--repo NAME] [--dry-run] | history | pause | resume
   whyline improve repos list | add PATH --level L | set NAME ... | remove NAME
   whyline improve on | off
   whyline improve schedule daily HH:MM [--weekdays] | weekly DAYS HH:MM | monthly DAY|last HH:MM
   whyline improve delivery ...
   ```

   `--dry-run` runs the checks and the review and writes the report, but never plans, fixes, pushes or sends.

## How one repo is handled in a run

Each step records its result. A step that fails stops that repo and the run moves on to the next repo.

1. **Skip checks.** Skip the repo, with the reason in the digest, when:
   - Self-improvement is paused, or the repo is paused
   - a relay is running in the repo's own checkout. The user is working there, and it would compete for agent quota.
   - the previous Self-improvement PR for this repo is still open. Self-improvement never piles up PRs, and the digest repeats the open PR.
   - the default branch can't be fetched
2. **Workspace.** Self-improvement never touches the user's checkout or its `.git`.
   - **Clone:** it keeps its own **separate clone** per repo, `~/.whyline/improve/work/<repo-slug>`, cloned from `origin`, so no `improve/*` branch shows up in the user's repo.
   - **Reset:** each run fetches and resets the clone to `origin/<default branch>` and removes untracked files. It skips this when the repo has a **held fix** (step 7).
   - **Relay settings:** the relay's settings come from the repo's committed `.whyline/relay/`. Self-improvement never writes `.whyline/relay/config.toml`. It passes the plan and branch to `whyline-relay start --plan … --branch …`.
3. **Checks.** These are commands, not an agent. Each has a timeout, and its output is kept with only the tail in the report.
   - **Tests:** the repo's test command. A failing command is rerun once. If it passes on the rerun, it is recorded as **flaky** rather than failing.
   - **Extra checks** the user adds per repo, each with a name and a command. Examples: `uv run --python 3.11 pytest -q`, `ruff check`, `uv lock --check`, `pip-audit`. **Detect** offers likely ones from the files it finds: `pyproject.toml`, `package.json`, `ruff.toml`, `uv.lock`.
   - **CI on the default branch:** the latest run's result from `gh run list`, read-only.
4. **Review.** One read-only agent run, using the agents runner with `unattended=True`. It gets:
   - the check results
   - the commits since the last Self-improvement run, at most 30
   - the repo's own open whyline Idea Inbox items, read-only, if any

   It writes **findings**, each with id, severity (`high` / `medium` / `low`), title, evidence (a file:line or a check name), suggested fix and size (`small` / `too big`). Its output is parsed as JSON. If the JSON is bad, the whole text goes into the report and the repo stops at this step. Any failing check that the review misses is added by whyline as a `high` finding, so a red test is never dropped.
5. **Choose.**
   - **Take:** findings at or above the repo's **Fix from** severity (default `medium`), and only those of size `small`, up to **Max fixes per run** (default 3), highest severity first.
   - **Report only:** findings marked `too big`. They are listed with a note to plan them as features.
   - **Level stop:** at **Report only**, the repo stops here.
6. **Plan.**
   - The taken findings become one description, sent to the SDLC pipeline: size **Small**, mode **Auto**, roles from the repo's relay setup, and **build off**. The pipeline writes the short spec and the plan with its test plan in the clone on branch `improve/<yyyy-mm-dd>`.
     - **Build off** is a new option on the SDLC Auto entry point, added by this plan. It writes the documents and returns without preflight, without `select_plan` and without starting the relay.
   - At **Plan** level, the plan goes into the report and the repo stops here. The branch stays in the clone, is not pushed, and is replaced next run.
7. **Fix.**
   - The relay runs that plan in the worktree on the same branch, unattended:
     - **Time:** a limit of **Max minutes per repo** (default 90).
     - **Rounds:** the repo's round cap.
     - **Releases:** no release tasks, because Self-improvement plans never contain one.
   - **When it pauses:** `whyline-relay start` exits with code 2 on a pause and 0 when it is done. A pause for any reason ends the fix, and the digest gives the reason.
   - **Held fix:** after a pause, the clone and its relay state are kept as a **held fix**. The user opens the clone in the console and resumes, or presses **Discard held fix** in Self-improvement. While a fix is held, later runs still check, review and report that repo, but don't reset its clone or start another fix.
   - **Firm time limit:** at **Max minutes per repo**, Self-improvement runs `whyline-relay stop`, waits 2 minutes, then kills the relay's process group. The repo becomes a held fix.
   - **Build record:** when the relay finishes, Self-improvement runs the SDLC build-record stage itself, headless, before the guard, so the PR carries it.
8. **Guard.** Before anything is pushed, whyline checks the branch's diff against the default branch. It refuses, and sends an immediate alert, when the diff:
   - deletes a test, or adds a skip/xfail/`only`, or lowers a coverage or test threshold
   - changes a file on the repo's **Never touch** list. The defaults are:
     - `.github/workflows/**`
     - `.whyline/**`, except `.whyline/decisions.md`
     - release and publishing settings
     - lock files, unless a finding is about dependencies

     Changes under `docs/sdlc/improve-*` and `plans/improve-*` are always allowed.
   - is bigger than **Max changed lines** (default 400)
   - contains something that looks like a secret, using the same pattern set the release security gate will use. The first version uses a small built-in set.
9. **Recheck.** All the checks run again on the branch. The tests must pass, and every check that failed before must now pass or be listed as not fixed. If the tests fail, nothing is pushed and the digest says why.
10. **PR.** At **Open PRs** and above:
    - **Push:** the branch is pushed. It is never the default branch, and never forced over a branch Self-improvement didn't create.
    - **Open:** `gh pr create` opens a PR titled `improve: <summary>`. Its body lists the findings, the checks before and after, the guard result and links to the documents.
11. **Merge.** At **Merge when green**:
    - **Wait:** Self-improvement waits up to **CI wait** (default 30 minutes) for the PR's checks.
    - **All green:** it merges with `gh pr merge --squash --delete-branch`.
    - **Otherwise:** it leaves the PR open and says so. The next run won't add another PR, and tries the merge again.

## Safety rules

- Nothing is pushed to a default branch, ever. Every change goes through a branch, a PR and CI.
- A repo is looked after only when the user has added it and accepted its level on this Mac. The list and levels live in `~/.whyline/improve/repos.toml` (0600), never in the repo, for the same reason deliveries are per Mac. Raising a level asks for acceptance again.
- Limits stop a run that goes wrong quietly:
  - per-repo minutes and per-run minutes (default 240, after which remaining repos are skipped)
  - max fixes per run
  - max changed lines
  - one open PR per repo
  - Self-improvement's own agent count per run (default 40 agent starts, review and relay together). It is separate from the workflows daily agent cap, which counts workflow steps only.
- **Pause Self-improvement** stops future runs at once and stops a running one at its next step. It is in the console, the CLI, and Telegram as `pause improvement` / `resume improvement`, which are assistant verbs.
- **Outside text is untrusted.** Test output, repo files and commit messages can contain text aimed at an agent. The review agent is read-only. The fix runs only through the relay's normal reviewer and tester. The guard checks the diff mechanically. At **Open PRs**, a human still merges. The design accepts that a hostile repo could steer a fix within those bounds. That is why the default level is **Open PRs**, not **Merge when green**.
- Secrets never go out. Report text is redacted for the Telegram token and stored credentials before it is written or sent. Output tails are capped at 60 lines per check.
- One Self-improvement run at a time, under `~/.whyline/improve/run.lock`. A heartbeat that finds it held does nothing.

## Where things live

- `~/.whyline/improve/repos.toml`: repos, levels, checks, limits and the accepted-capabilities hash
- `~/.whyline/improve/settings.toml`: on/off, schedule, digest mode, global limits, paused
- `~/.whyline/improve/runs/<run-id>/`:
  - `run.json`: per-repo step results
  - `report.md` and `report.docx`
  - `<repo-slug>/` with each check's log, `findings.json` and the relay log
- `~/.whyline/improve/work/<repo-slug>/`: the separate clone
- Delivery is a `deliveries.toml` entry under the id `improve`, edited with the existing delivery screen.
- Inside the repo, only on the PR branch: the SDLC document set, at `docs/sdlc/improve-<date>/`, and the plan, at `plans/improve-<date>.plan.md`.

## Code layout

New package `src/whyline/improve/`:

- `settings.py`: repos and settings, load/save/validate, level capabilities text and hash
- `schedule.py`: Daily / Weekly / Monthly at a time, due times, next run, missed runs
- `checks.py`: running commands with timeouts, flaky rerun, CI status, Detect
- `workspace.py`: clone create/reset, held fixes, skip checks
- `review.py`: the review prompt, the agent run, findings parsing and the merge with failing checks
- `fix.py`: the SDLC Small/Auto plan, the relay run with limits, pause handling
- `guard.py`: diff rules
- `github.py`: push, PR create, PR state, CI wait, merge (all through `gh`, with an injectable runner)
- `report.py`: the per-repo section, the digest text, `report.md` → `.docx` through `whyline.agents.docx`
- `notify.py`: the digest and immediate alerts through `whyline.agents.deliver.send`, and the Telegram buttons through the assistant's request cards
- `runner.py`: one run over all repos, the lock, the limits, pause
- `service.py`: the one API the console and CLI share
- `cli.py`: `whyline improve ...`

Console: `src/whyline/console/improve_screens.py` (the Settings tab, the repo editor, History), a tab added to `settings_screen.py`, and the line in Relay → Set up.

Heartbeat: `agents/tick.py` gets `_run_improve(now)` beside `_run_workflows`. It claims the scheduled occurrence once and starts the run detached.

## Decisions

- **Name "Self-improvement"**, the user's words. Code uses `improve` (`whyline improve`, `src/whyline/improve/`, branches `improve/<date>`).
- **All settings in Settings → Self-improvement**, the user's request, with an On/Off switch and Daily / Weekly / Monthly at a time. Relay → Set up links to it for the current repo, rather than having a second editor. My call: a tab in the existing Settings modal, not a new console mode. That keeps the top bar as it is.
- **One schedule and one combined digest for all repos**, the user's preference. Per repo is a setting.
- **Word attachment by default.** whyline already makes `.docx`, and it opens on a phone.
- **Default level Open PRs**: it updates through GitHub, and a human merges.
- **Plans go through the SDLC pipeline at Small/Auto**, not a new planner. Self-improvement's fixes get the same reviewable documents as any other work.
- **Its own clone and an `improve/` branch.** It never touches the user's checkout or branches.
- **Rejected: one agent with full access doing everything.** It can't be limited or checked. The checks are commands, the review is read-only, the fix goes through the relay's reviewer and tester, and the guard is mechanical.
- **Rejected: running each repo in parallel.** It competes for agent quota and makes the digest wait on the slowest repo anyway.

## Calls made after the builder check

- **Telegram buttons.** A separate assistant card, not buttons on the digest. It has a long expiry and always needs a confirming tap, and it is sent only when the assistant bot is bound to the same chat.
- **SDLC Auto.** It gets a **build off** option. Self-improvement runs the relay itself, with its own limits, and never writes the relay config.
- **A separate clone.** Self-improvement uses a clone, not a `git worktree` of the user's repo, so the user's repo and `.git` are never changed.
- **A firm time limit.** It runs `whyline-relay stop`, then kills the process group after 2 minutes.
- **A held fix** blocks the next fix for that repo, the same way an open PR does, so paused relay state isn't wiped.
- **The build record** is run by Self-improvement after the relay finishes.
- **Self-improvement's agent count** is its own limit, not the workflows cap.

## Out of scope

- **The Release level.** It comes after `release-button` ships, as a follow-up plan that calls the release engine when the merged PR is releasable.
- **Running on another machine or in the cloud.** Self-improvement runs on this Mac only, so the Mac must be awake at the scheduled time. Missed runs are reported, see above.
- **Repos on hosts other than GitHub.**
- **Fixing findings marked "too big".** They are reported, so the user can plan them as features.

## Testing

- Every step has unit tests with fake `run` / `gh` / agent / relay / clock. No test opens a socket, calls Telegram, sends mail or runs a real agent.
- Guard tests cover each rule:
  - a deleted test
  - an added `pytest.mark.skip`
  - a Never touch path
  - an oversize diff
  - a fake secret
- A run test uses three fake repos (pass / fix / skipped). It checks:
  - the combined digest text exactly
  - the heartbeat on an all-pass run
  - an alert on a guard refusal
  - nothing pushed at Plan level
  - no second PR while one is open
- An integration test with a real local git repo and a bare "origin" checks:
  - worktree reset
  - branch naming
  - push to the bare remote (`gh` faked)
  - the user's checkout and its `.git` refs unchanged before and after
