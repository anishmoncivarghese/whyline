# Self-improvement: scheduled self-checks that find, plan, fix and report, across chosen repos

Date: 2026-11-02. Status: draft for the user's review. Plan: `plans/self-improvement.plan.md` (IMP-1..). Needs `plans/sdlc-pipeline.plan.md` first, because Self-improvement writes its fix plans through that pipeline in Auto at size Small.

## Problem

Today whyline only does work when someone starts it. Tests can break on a new Python, a dependency or a flaky macOS runner. Small bugs and rough edges pile up in every repo. Nobody notices until the next feature runs into them. The user wants whyline to look after their repos on a schedule:

- check each repo
- find what is wrong
- write a plan to fix it, run the plan, and update the repo through GitHub
- tell the user what happened, by Telegram and/or email, with a report attached

It should work on whyline itself and on any repo the user has chosen and given permission to in whyline.

Two rules from the user shape everything below:

- **Vulnerabilities.** Each run looks for newly published vulnerabilities that affect each repo's dependencies, and works out how to resolve each one.
- **Always human in the loop for GitHub.** Self-improvement pulls the latest code, works on it and makes the change locally, then tells the user what changed. It pushes to GitHub only after the user approves that change. Merging is always the user's call too. No level pushes or merges on its own.

## What the user gets

1. **Everything lives in Settings.** The console's **Settings** opens with two tabs: **AI providers**, which is today's screen, and **Self-improvement**. Settings is reachable from every mode, Relay included. The Self-improvement tab has:
   - **Self-improvement loop: On / Off.** Off is the default. Off means nothing runs on a schedule. **Run now** still works.
   - **How often:** **Daily**, **Weekly** or **Monthly**.
     - **Weekly** picks one or more weekdays, for example Mon and Thu.
     - **Monthly** picks a day of the month, 1–28 or **Last day**.
     - Daily has a **Weekdays only** checkbox.
   - **Time:** HH:MM, local time, for example 02:00. Below it: `Next run: Tue 3 Nov, 02:00` and `The Mac must be awake at that time; a missed run is reported when it wakes.`
   - **Messages:** **Combined** (default) or **One per repo**, plus **Delivery…** for Telegram and/or email, attachment Word or Markdown, and **Send test**.
   - **Limits:** run limit (minutes), max agent starts per run, and the defaults for new repos (Fix from, Max fixes, Max minutes per repo, Max changed lines).
   - **Repos:** a table of the repos it looks after. Each row shows:
     - the permission level
     - the last result, for example `✅ all checks pass` or `🔧 PR #212 waiting for you`
     - when it last ran

     Buttons: **Add repo…**, **Edit…** and **Remove**.
   - **Run now** (all repos or the selected one, with a Dry run checkbox), **History** and **Pause / Resume**.
   - **Save** and **Cancel**, like the providers tab. Nothing changes until Save.

   **Relay → Set up** also shows one line for the current repo: `Self-improvement: Fix and ask · daily 02:00 · Change…`, or `Self-improvement: off for this repo · Turn on…`. **Change…** opens that repo's row in Settings → Self-improvement. There is one place to save, and two ways in.
2. **Add repo…** takes a folder and a level, then runs **Check** with a ✓ or ✗ per line and a fix button where one exists:
   - the folder is a git repo with a GitHub `origin`
   - `gh` is signed in and can push to it (only for Fix and ask, checked so an approval can't fail later)
   - a test command is set (from the relay setup, or typed here)
   - the relay is set up **and committed** (`.whyline/relay/config.toml` tracked), and `doctor` passes. This applies to Plan and above, since the SDLC roles come from it.
   - the review agent has a verified read-only setting (all levels)
   - the agents it needs can run unattended

   Saving shows what this level allows, in plain lines, and the user accepts them. That is the permission, the same way an agent is accepted today.
3. **Permission levels**, per repo:

   | Level | Checks and vulnerabilities | Writes a fix plan | Makes the fix locally and asks you |
   |---|---|---|---|
   | **Report only** | ✓ | | |
   | **Plan** | ✓ | ✓ (sent in the report, not run) | |
   | **Fix and ask** (default) | ✓ | ✓ | ✓ |

   After a fix is made, nothing goes to GitHub until the user approves it (see **Approving a change** below). There is no level that pushes or merges by itself. A Release step is not in this plan.
4. **One schedule for all repos**, set in Settings: daily (optionally weekdays only), weekly on chosen days, or monthly on a day, at a time. It uses the existing agents heartbeat, so it needs no new launchd job. Turning the loop on also turns the agents heartbeat on when it is off, after saying so. One run covers every repo, **one repo at a time**, so a run can't use several agents' quotas at once.
5. **One combined message per run**, by Telegram, email or both. Delivery is set up the way it is for an agent. Example:

   ```
   whyline improve — Mon 2 Nov, 02:00 (ran 47 min)
   ✅ whyline-relay   all checks pass, nothing to do
   🔧 agentdock       2 fixes ready (+38 −12 in 3 files) → waiting for your OK to push
   🛡 agentdock       1 new vulnerability: urllib3 2.2.1, GHSA-xxxx (high), fixed in 2.2.2 → included in the fix
   ✋ whyline-docs    PR #41: CI green → waiting for you to merge
   📝 TradingPlatform tests fail on 3.11 → plan written (Plan level, not run)
   ⏭ cvfix           skipped: a relay is running there
   Full report attached.
   ```

   - **Attachments:**
     - **The report:** one Word file with a section per repo. It has the checks and their output tails, the vulnerabilities, the findings, the plan, what the fix changed (files, line counts, and a plain summary of each change), and the PR link once there is one. `.md` is the other choice, through the existing `attach` setting.
     - **The change:** a `<repo>-<date>.patch` file for each fix waiting for approval, so it can be read on a phone.
   - **Heartbeat:** the message is sent **every run, even when everything passes**, so a missing message means Self-improvement didn't run.
   - **Combined or one per repo:** combined is the default.
   - **Immediate alerts**, sent as they happen, outside the digest:
     - a repo's run crashed
     - the guard stopped a fix
     - a time limit was hit
     - a scheduled run was missed because the Mac was asleep or off. This is sent on the next heartbeat after it wakes.
     - a **new** high or critical vulnerability was found in a repo's dependencies
   - **Approval cards:** after the digest, each waiting decision gets its own assistant request card, through the assistant outbox:
     - a fix waiting to be pushed: **Push and open PR** / **Discard**
     - an open PR whose CI is green: **Merge #41** / **Close #41**
     - Each is a new `improve_change` action (push, discard, merge or close).
     - **Confirm:** a confirming tap is always needed, whatever the action's approval policy says.
     - **Expiry:** the code lasts until the next scheduled run, or 24 hours if there is no schedule. The next digest offers the card again.
     - **Telegram:** the card is sent when the assistant bot is bound to the same chat as the delivery.
     - **Email:** the card is sent through the assistant's existing `yes <code>` email replies, when assistant email is set up. Otherwise the digest says to approve in the console or with `whyline improve approve <repo>`.
6. **Approving a change.** A fix waiting for approval shows as **⏳ Waiting for you** on its repo's row in Settings → Self-improvement. **Review change…** shows:
   - the plain summary of each change, and the findings and vulnerabilities it resolves
   - the checks before and after
   - the guard result
   - the full diff, file by file

   Its buttons:
   - **Push and open PR**
   - **Ask for changes…:** typed feedback. The relay revises the fix on the same branch, then the checks, guard and recheck run again, and the user is told again. This uses the same flow as SDLC's Ask for changes.
   - **Discard**
   - **Open in console:** work on the clone by hand.

   **Push and open PR** does this, in order:
   1. Fetch `origin` again. If the default branch moved, rebase the branch on it, then rerun the checks and the guard. On a conflict or a failure, nothing is pushed, and the user is told why.
   2. Push the `improve/<date>` branch, never a default branch.
   3. Open the PR.

   A waiting change blocks new fixes for that repo, but checks and reviews still run, and each digest reminds the user with `waiting since <date>`. It never expires on its own. **Merge** appears once the PR's CI is green. The user can also merge on GitHub as usual.
7. **History** lists past runs. Each run opens its report, per-repo logs, the plan, the change, the PR, and **Resend**.
8. **A CLI for scripts**, saving through the same functions as the console:

   ```
   whyline improve status | run [--repo NAME] [--dry-run] | history | pause | resume
   whyline improve repos list | add PATH --level L | set NAME ... | remove NAME
   whyline improve on | off
   whyline improve schedule daily HH:MM [--weekdays] | weekly DAYS HH:MM | monthly DAY|last HH:MM
   whyline improve delivery ...
   whyline improve changes NAME | approve NAME | revise NAME "feedback" | discard NAME | merge NAME | vulns NAME
   ```

   `--dry-run` runs the checks and the review and writes the report, but never plans, fixes, pushes or sends.

## How one repo is handled in a run

Each step records its result. A step that fails stops that repo and the run moves on to the next repo.

1. **Skip checks.** Skip the repo, with the reason in the digest, when:
   - Self-improvement is paused, or the repo is paused
   - a relay is running in the repo's own checkout. The user is working there, and it would compete for agent quota.
   - **No new fix** while the repo has a change waiting for approval, an open Self-improvement PR, or a held fix. Checks, vulnerabilities and review still run and are reported, so the user still hears about new problems.
   - the default branch can't be fetched
2. **Workspace.** Self-improvement never touches the user's checkout or its `.git`.
   - **Clone:** it keeps its own **separate clone** per repo, `~/.whyline/improve/work/<repo-slug>`, cloned from `origin`, so no `improve/*` branch shows up in the user's repo.
   - **Reset:** each run fetches and resets the clone to `origin/<default branch>` and removes untracked files. It skips this when the repo has a **held fix** (step 7).
   - **Relay settings:** the relay's settings come from the repo's committed `.whyline/relay/`. Self-improvement never writes `.whyline/relay/config.toml`. It passes the plan and branch to `whyline-relay start --plan … --branch …`.
3. **Checks.** These are commands, not an agent. Each has a timeout, and its output is kept with only the tail in the report.
   - **Tests:** the repo's test command. A failing command is rerun once. If it passes on the rerun, it is recorded as **flaky** rather than failing.
   - **Extra checks** the user adds per repo, each with a name and a command. Examples: `uv run --python 3.11 pytest -q`, `ruff check`, `uv lock --check`, `pip-audit`. **Detect** offers likely ones from the files it finds: `pyproject.toml`, `package.json`, `ruff.toml`, `uv.lock`.
   - **CI on the default branch:** the latest run's result from `gh run list`, read-only.
   - **Vulnerabilities** in the repo's dependencies, looked up fresh each run:
     - **Dependencies:**
       - **Read from lock files:** `uv.lock`, `poetry.lock`, pinned `requirements*.txt`, `package-lock.json` and `pnpm-lock.yaml`.
       - **Direct or transitive:** each is marked by checking `pyproject.toml` or `package.json`.
     - **Sources:**
       - **OSV.dev** (`/v1/querybatch`), which covers the GitHub advisory database, PyPA and npm advisories. It is called over HTTPS with the standard library. No key is needed, and only package names and versions are sent.
       - The repo's open **Dependabot alerts** through `gh api`, when the repo has them enabled and the user can read them. Otherwise this source is skipped with a note.
     - **What is kept** for each vulnerability:
       - id and aliases (CVE)
       - summary
       - severity, from the CVSS score, or the database's severity when there is none
       - published date
       - the affected package, version and fixed versions
       - **new**: whether this run is the first to see it for this repo, tracked per repo
     - **Failure:** a source that can't be reached is reported as `vulnerability check unavailable: <reason>`. It never fails the repo.
4. **Review.** One read-only agent run, using the agents runner with `unattended=True`. It gets:
   - the check results
   - the commits since the last Self-improvement run, at most 30
   - the repo's own open whyline Idea Inbox items, read-only, if any
   - the vulnerabilities, with the advisory text marked as untrusted data

   For each vulnerability, the review says how to resolve it:
   - **upgrade** to the lowest fixed version that the repo's version constraints allow, or say which constraint has to change
   - with no fixed version, a **mitigation** in the code. It checks whether the repo uses the affected function or feature (with file:line evidence), so a vulnerability that can't be reached is reported as `not affected: <why>` rather than fixed.

   Each becomes a finding with `kind: "security"`. A vulnerability the review doesn't mention is added by whyline as a security finding, so none are dropped.

   It writes **findings**, each with id, severity (`high` / `medium` / `low`), title, evidence (a file:line or a check name), suggested fix and size (`small` / `too big`). Its output is parsed as JSON. If the JSON is bad, the whole text goes into the report and the repo stops at this step. Any failing check that the review misses is added by whyline as a `high` finding, so a red test is never dropped.
5. **Choose.**
   - **Take:** findings at or above the repo's **Fix from** severity (default `medium`), and only those of size `small`, up to **Max fixes per run** (default 3). Security findings come first, then the rest by severity.
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
     - lock files and dependency manifests, unless a taken finding is a security or dependency finding, and then only for the packages it names

     Changes under `docs/sdlc/improve-*` and `plans/improve-*` are always allowed.
   - is bigger than **Max changed lines** (default 400)
   - contains something that looks like a secret, using the same pattern set the release security gate will use. The first version uses a small built-in set.
9. **Recheck.** All the checks and the vulnerability lookup run again on the branch.
   - The tests must pass.
   - Every check that failed before must now pass, or be listed as not fixed.
   - Every vulnerability taken must be gone, or be listed as not fixed.

   If the tests fail, the change is not offered, and the digest says why.
10. **Tell the user and wait.** The change stays on `improve/<date>` in the clone, as **waiting for approval**:
    - A plain summary of each change is written: what changed, why, which finding or vulnerability it resolves, and files and lines.
    - It goes into the report, with the `.patch` attached and an approval card.
    - Nothing is pushed.

    What happens next is the user's decision: approve, ask for changes, or discard (see **Approving a change**).
11. **On approval.** It fetches, rebases if needed and rechecks, pushes the branch, and opens a PR titled `improve: <summary>`. The PR body lists:
    - the findings and vulnerabilities
    - the checks before and after
    - the guard result
    - the links to the documents

    From then on, the repo's row and each digest show the PR's CI state. **Merge** is offered only when CI is green, and runs only on the user's tap or click, using `gh pr merge --squash --delete-branch`.

## Safety rules

- **Nothing leaves this Mac without the user's approval.** A push, a PR and a merge each need an explicit approval of that change. An approval is a console button, a confirmed Telegram or email card, or `whyline improve approve`. An approval applies to the exact commit it was shown: if the branch changes afterwards, for example after a rebase or Ask for changes, the user approves again.
- Nothing is pushed to a default branch, ever. Every change goes through a branch, a PR and CI.
- A repo is looked after only when the user has added it and accepted its level on this Mac. The list and levels live in `~/.whyline/improve/repos.toml` (0600), never in the repo, for the same reason deliveries are per Mac. Raising a level asks for acceptance again.
- Limits stop a run that goes wrong quietly:
  - per-repo minutes and per-run minutes (default 240, after which remaining repos are skipped)
  - max fixes per run
  - max changed lines
  - one waiting change or open PR per repo
  - Self-improvement's own agent count per run (default 40 agent starts, review and relay together). It is separate from the workflows daily agent cap, which counts workflow steps only.
- **Pause Self-improvement** stops future runs at once and stops a running one at its next step. It is in the console, the CLI, and Telegram as `pause improvement` / `resume improvement`, which are assistant verbs.
- **Outside text is untrusted.** Test output, repo files and commit messages can contain text aimed at an agent. The review agent is read-only. Vulnerability advisories come from the internet and are treated the same way. The fix runs only through the relay's normal reviewer and tester. The guard checks the diff mechanically. A human approves every push and every merge, after seeing the diff.
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
- `github.py`: push, PR create, PR state, CI state, merge, Dependabot alerts (all through `gh`, with an injectable runner)
- `vulns.py`: reading lock files, OSV querybatch with an injectable HTTP call, Dependabot alerts, severity, and what's new since last run
- `changes.py`: waiting changes, the change summary and `.patch`, approve (fetch, rebase, recheck, push, PR), ask for changes, discard, merge
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
- **Human approval for every push and merge** is the user's rule. There is no auto-push or auto-merge level. The default level is **Fix and ask**.
- **OSV.dev for vulnerabilities**, plus Dependabot when available. It's my call: free, no key, and it covers PyPI and npm with fixed versions. Rejected: requiring `pip-audit` or `npm audit`. They are still available as extra checks, but they'd be a dependency per ecosystem.
- **Plans go through the SDLC pipeline at Small/Auto**, not a new planner. Self-improvement's fixes get the same reviewable documents as any other work.
- **Its own clone and an `improve/` branch.** It never touches the user's checkout or branches.
- **Rejected: one agent with full access doing everything.** It can't be limited or checked. The checks are commands, the review is read-only, the fix goes through the relay's reviewer and tester, and the guard is mechanical.
- **Rejected: running each repo in parallel.** It competes for agent quota and makes the digest wait on the slowest repo anyway.

## Calls made after the builder check

- **Approval cards.** A separate assistant card per decision (push, discard, merge, close), not buttons on the digest. Each one has a long expiry and always needs a confirming tap.
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
- **Vulnerabilities in the language runtime, OS packages or container images.** Dependencies in lock files only, for now.

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
  - nothing pushed at any level until approval
  - no second fix while one is waiting
  - an approval of an old commit refused
  - a new vulnerability alerted once, not on the next run
- An integration test with a real local git repo and a bare "origin" checks:
  - worktree reset
  - branch naming
  - nothing pushed before approval, then a push to the bare remote after approval (`gh` faked)
  - the user's checkout and its `.git` refs unchanged before and after
