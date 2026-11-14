# Plan queue: run several plans one after another, releasing as it goes

Status: draft for review, 2026-11-14. Builds on the relay, the Release button (REL, RFB, RCR) and Auto run. Runs after `plans/telegram-daily-use.plan.md`. It uses Rehearse and the release record from `plans/release-safety.plan.md` when they are installed, and works without them.

## Problem

Whyline can take one idea from brainstorm to a released version without the user (Auto run, then `Release when a plan completes` with the release mode `auto`). It cannot go on to the next plan. Today, between two plans, the user has to:

- notice that the relay finished
- press Release, or wait for it to start, and answer its confirms
- wait for CI and the publish
- pick the next plan in Set up and start the relay

`plans/RUN-ORDER.md` lists 31 plans. Each hand-over waits for the user to be at the Mac, often for hours.

## What the user gets

A **Queue**: the user ticks one or more plans, puts them in order, says where the releases go, and presses Start. Whyline runs each plan's relay, releases where asked, brings in main, and starts the next plan. It asks nothing along the way unless the user chose to be asked before publishing. When something is wrong it holds and says why.

### Setting up a queue

In the console, **Queue** opens from the Relay screen and from the command list. It shows every unfinished plan in `plans/`:

- a checkbox to include the plan
- its position, with **Move up** and **Move down**. The starting order is the order of `plans/RUN-ORDER.md` when that file exists, else each plan's `Runs after` line, else by name.
- **After this plan**: `Release` or `Carry on`. `Carry on` starts the next plan on top of this one's work without releasing. The last plan in the queue is always `Release`.
- **Version**: `patch` (default) or `minor`, used when this plan releases.
- **Ask me before publishing**: a per-plan override, see below.

Above the list, one setting for the whole queue:

- **Publish by itself**: releases run with no question.
- **Ask me before publishing**: each release waits for one go-ahead.

A plan's own **Ask me** box turns the question on for that plan inside a `Publish by itself` queue. It cannot turn the question off inside an `Ask me` queue.

Warnings shown before Start, none of which block it:

- a ticked plan's `Runs after` plan is neither finished nor earlier in the queue
- a ticked plan has no tasks left
- the repository's release config has no publish target, so `Release` will only push and tag
- the commit hook or the security check is off

Start is refused, with the reason, when a relay or a release is running in this checkout, when the checkout has uncommitted changes, or when the release's Ready check fails for a reason that would stop the first release (not signed in to GitHub, no remote).

### What the queue does for each plan

1. **Bring in main.** Fetch `origin/<release branch>`. When it has commits this checkout doesn't, merge them, the same way the release's Bring in main step does. This is how plans and fixes pushed to main while the queue runs reach it. A conflict holds the queue.
2. **Check the plan.** The plan file exists after the merge, parses, and has unticked tasks. A plan with none left is marked done and skipped.
3. **Run the relay** on that plan, as Set up's Start does: same preflight, same roles, backups and timeout from `config.toml`. The relay's own recovery (backup agents, automatic Resolve) runs as it does today. The queue adds none of its own.
4. **When the relay ends:**
   - every task ticked: go on
   - anything else (paused, round cap, no agent available, crashed): hold
5. **Release, when this plan is marked Release:**
   - `Publish by itself`: run the release in mode `auto`.
   - `Ask me`: run the Ready check (and Rehearse, when installed), then wait for the go-ahead. After it, run the release in mode `auto`. One go-ahead covers the whole release.
   - The release is the existing one, unchanged: bring in main, notes, checks, security scan, push, CI, tag, publish, verify, after steps.
   - A release that stops for any reason holds the queue.
6. **Install check.** After a release to a package registry, install the published version into a temporary environment and run one command that proves it starts (for a Python package with a console script, `<script> --version`; the command can be set in the queue's settings). Today's Verify step only waits for the version to appear on the registry. A version that doesn't install or start holds the queue before the next plan builds on it. The temporary environment is removed afterwards.
7. **After a release:** check that the checkout holds everything on `origin/<release branch>`. The next plan's relay branch starts from there. The queue does not switch to the release branch itself, because it may be checked out in another worktree.
8. **Next plan.**

A plan marked `Carry on` skips steps 5 to 7. Its work is released with the next plan that releases, in one version.

### The go-ahead

With `Ask me`, when a plan is ready to release the queue shows, in the console and (when `waiting-on-you` is installed) as a Telegram card:

- `agentdock: quick-fixes is ready to release as v0.3.75. 16 tasks, 41 commits. Checks passed.`
- the Rehearse result's `would` lines, when Rehearse is installed
- **Publish**, which asks once more: `Release v0.3.75 to PyPI? This can't be undone.` with **Yes, publish**
- **Hold**

It waits with no time limit. It sends one reminder after 6 hours. Nothing else in the queue runs while it waits.

### Holding

A hold stops the queue where it is. It never skips to the next plan, and it never retries by itself beyond what the relay and the release already retry. The queue holds when:

- bringing in main conflicts
- a plan file is missing or doesn't parse
- the relay ends with tasks left
- the release stops at any step: Ready, checks, a blocking security finding, CI, tag, publish, verify, an after step
- the published version fails the install check
- the Mac's low-battery safeguard paused the relay
- the user pressed **Hold**

A held queue shows what held it, in the words the relay or the release already uses, and offers:

- **Resume queue**: after the user fixed the cause with the existing tools (Resolve, Resume release, Rerun). It picks up at the step that held, and checks first that the cause is gone: the relay is not paused, the release is not stopped.
- **Skip this plan**: only before the plan's relay has made a commit. After that it is refused, because later plans may build on it.
- **Stop queue**: ends the queue and leaves the checkout as it is.

When `waiting-on-you` is installed, a hold sends its card (relay stopped, release stopped) with one extra line: `The queue is holding: 3 plans are waiting behind this.` and, once the cause is fixed from Telegram, **Resume queue**.

### While it runs

The Queue screen lists the plans with one state each: `waiting`, `running · TLS-14, 9 of 16 tasks`, `releasing · Wait for CI`, `waiting for you`, `held`, `done · v0.3.75`, `done · carried on`, `skipped`. The console title shows `queue 2 of 5`.

While a queue runs the user can:

- add a plan, remove a waiting plan, and reorder waiting plans
- change `Release` / `Carry on`, the version and **Ask me** on waiting plans
- change the queue's publish setting, which applies from the next release
- **Hold after this plan**: finish the running plan (and its release, if marked), then hold

They cannot change the running plan's row.

When the queue ends it sends one summary: `Queue finished: 5 plans, 3 releases (v0.3.75, v0.3.76, v0.3.77), 9h 12m.`

## How it works

### One runner, a fresh process for each stage

`whyline queue run` is a small loop, started detached by the console's Start (and by `whyline queue start`), so the queue goes on when the console is closed. It holds a lock with its pid, like the release does.

The loop does no work itself. For each stage it starts a new `whyline` process and waits for it:

- `whyline queue stage bring-in`
- the relay, through the same launch function Set up uses (`ideas.run.launch`, so keep-awake applies)
- `whyline queue stage release`

This matters for a repository whose tool is the one running the queue, as with whyline's own. When the release's `after` commands upgrade the installed tool (for whyline, `uv --no-cache tool upgrade whyline`), the next stage is a new process, so it runs the new version. The queue does not add that command itself: the Queue screen shows the release's current `after` commands and says `Nothing upgrades the installed tool after a release` when the list is empty, with a link to Release → Set up.

The console's `Release when a plan completes` setting stays as it is for a relay started by hand. While a queue's lock is held, the console does not start that release: the queue's own release stage does, so a release is never started twice. The loop is kept small and its state file is versioned, so an old loop can drive new stages.

### State

`.git/whyline-queue/queue.json`, written atomically:

- `schema`, `started`, `publish` (`auto` or `ask`), `hold_after_current`
- `items`: `plan` (path), `after` (`release` or `carry-on`), `bump`, `ask`, `state`, `version`, `started`, `finished`, `hold_reason`
- `stage` of the running item, and the runner's `pid`

`.git/whyline-queue/queue.log` gets one line per stage start, end, hold and resume. Nothing in either file holds a secret; hold reasons pass the existing redaction.

The queue is per checkout. Two queues in two checkouts of one repository are refused, as two releases are.

### What it reuses, and what it must not duplicate

| Need | Existing function |
|---|---|
| list plans and their progress | `console.relay_ops.list_plans`, `whyline_relay.plan.parse` |
| choose the plan | `relay_ops.select_plan` |
| preflight | `relay_ops.run_checks` |
| start the relay | `ideas.run.launch` / the console's `_launch_relay` argv |
| is a relay live, is it paused | `whyline_relay.running.live`, `relay_ops.paused_run` |
| merge main in | `release.source.bring_in_main` (its merge part, split out) |
| run a release | `release.engine.run(mode="auto")` with the plan from `release.plan` |
| is a release stopped | `release.state.load` |
| Telegram cards | `waiting-on-you` (WAIT-1..7) |
| Rehearse | `release.rehearse.run` (SAF-2), when present |
| is the version on the registry | the target's `verify` (unchanged) |

The queue adds a new `confirmed_by` value, `queue`, to the release record (SAF-1) when that is installed.

### Console first

Every queue action is in the console's Queue screen and calls the same function as its CLI command:

- `whyline queue list`
- `whyline queue add <plan> [--after release|carry-on] [--bump patch|minor] [--ask]`
- `whyline queue remove <plan>`, `whyline queue move <plan> <position>`
- `whyline queue start [--publish auto|ask]`
- `whyline queue status`
- `whyline queue hold`, `whyline queue resume`, `whyline queue skip`, `whyline queue stop`
- `whyline queue go-ahead` (asks `[y/N]`)

## Safety rules

- **"Publish by itself" removes the question, not the checks.** The queue never passes a flag that skips a release step, a check, the security scan or Verify. There is no such option.
- **The first time, the user says so twice.** Starting a queue with `Publish by itself` asks once: `This queue will publish 3 releases without asking. Each one can't be undone.` with **Start** and **Ask me before each instead**.
- **A go-ahead is for one version.** It names the version and the commit. If the commit changed before the release starts (main moved, a hold was resumed), the go-ahead is asked again.
- **Telegram taps follow the existing rules:** allowed chats only, a current nonce, and the second confirm for anything that can't be undone. No message text chooses a plan, a version or a command.
- **The queue never forces.** No force push, no deleted tag, no skipped hook, no merge strategy that discards a side.
- **The queue never edits a plan**, a spec or code. Only the relay writes code; only the release bumps the version.
- **Agents get no extra permission.** The relay runs with the roles and permissions it has today.
- **A hold is quiet.** Nothing runs in a held queue, so a held queue overnight costs nothing.

## Not in this design

- Two plans running at the same time.
- One queue across several repositories.
- Resolving a merge conflict or a failed test by itself. The relay's and the release's existing Ask agent and Fix stay where they are, started by the user.
- Skipping a failed plan and going on.
- Choosing the plans by itself. The user ticks them.
- A schedule ("start the queue at 22:00"). The scheduler can call `whyline queue start` later if wanted.

## Decisions made here, for review

These are my calls, not things the user asked for in these words:

- A plan can be `Carry on`, so several plans ship in one release.
- The go-ahead waits with no time limit, with one reminder after 6 hours.
- Skip is refused once the plan's relay has committed.
- The queue does not check out the release branch; it only checks nothing on it is missing.
- The queue is built after `waiting-on-you`, and uses Rehearse only when it is there.
- A new install check after each release, because today's Verify only waits for the version to appear.
- Each stage is a fresh process, so a queue in whyline's own repository uses each new version as soon as it is installed.

## Open risks

- **A bad release with no one watching.** The install check catches a version that doesn't install or start. It doesn't catch a feature that is wrong. `release-safety`'s Release went wrong is the recovery path. The user should use `Ask me` until a few unattended queues have gone well.
- **Quota.** A long queue can use up every agent. The relay already pauses with "no agent available"; the queue then holds until the user resumes.
- **A long hold on a branch.** Main may move a lot while a queue is held. Resume brings main in again first, and a conflict then needs the user.
