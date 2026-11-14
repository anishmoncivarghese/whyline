<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-02T12:00:00+05:30 -->
# Self-improvement: scheduled self-checks that find, plan, fix and report, across chosen repos — 3: report, schedule, CLI, console and docs

Runs after `plans/self-improvement-2-fix.plan.md`, and before `plans/trading-desk.plan.md`. Split on 2026-11-15 from `self-improvement.plan.md` (37 tasks) into three plans, so each relay is short and ends with a release. This file builds: Parts 4 to 6 (IMP-24..37). Design: `docs/superpowers/specs/2026-11-02-self-improvement-design.md`. Read it before any task. Where this plan and the design differ, this plan wins. Where a name in the repository has moved, follow the repository and keep the design's behaviour.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

There is no publish task (removed 2026-11-11). When the relay finishes, press **Release**: it sets the version, writes the notes, runs the checks and the security scan, pushes, waits for CI, tags and publishes. This repository's relay has no `release` profile, so a publish task would only bump the version.

What the user gets:
- **Settings → Self-improvement** in the console holds all of it:
  - an **On / Off** switch for the loop
  - **Daily** (optionally weekdays only), **Weekly** on chosen days, or **Monthly** on a day or the last day, at a set time
  - messages and delivery
  - limits
  - the repos it looks after, each at a permission level: **Report only**, **Plan** or **Fix and ask** (default)

  **Relay → Set up** shows the current repo's line, with a link into that tab.
- On each scheduled run, one run goes through every repo, one at a time. For each repo it:
  1. pulls the latest default branch into its own clone, and checks it: tests, extra checks, CI on the default branch
  2. looks up newly published **vulnerabilities** in its dependencies (OSV.dev, plus Dependabot alerts when available)
  3. reviews it with a read-only agent, which says how to resolve each problem and each vulnerability
  4. writes a Small fix plan through the SDLC pipeline
  5. makes the fix locally with the relay
  6. runs a mechanical guard on the diff, then rechecks
  7. **tells the user what changed and waits.** Nothing is pushed until the user approves that exact change. Then it pushes a branch and opens a PR. Merging is also only on the user's approval.
- One combined Telegram and/or email message per run, sent even when all is well, with a Word report and the change's `.patch` attached. Approval cards: **Push and open PR** / **Discard**, and **Merge** / **Close** once CI is green. Immediate alerts for crashes, guard refusals, time limits, missed runs and new high or critical vulnerabilities.
- `whyline improve …` on the command line, calling the same functions.

Rules every task keeps:
- Console first: every console action saves through the same function the CLI calls.
- No new dependency. Word goes through `whyline.agents.docx`. Sending goes through `whyline.agents.deliver.send`. GitHub goes through the `gh` CLI, called with an injectable `run`.
- New non-widget code goes in `src/whyline/improve/`, with tests in `tests/improve/`. Console code goes in the files a task names, with tests in `tests/console/`.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- Tests never:
  - run a real agent, relay, `gh` or `git push` to a real remote
  - call Telegram, send mail or open a socket
  - contain "/Users/"

  Use fakes for `run`, the clock, the agent runner, the relay launcher and `deliver.send`. Real `git` is allowed only on temporary repos made inside the test.
- Self-improvement never writes to the user's own checkout or its `.git`, never pushes a default branch, and never force-pushes a branch it didn't create.
- **Human in the loop for GitHub:** no code path pushes, opens a PR or merges, except the approval functions in `improve/changes.py`. Each of those requires an approval naming the exact commit sha shown to the user. A test in IMP-23 checks this by searching the package for calls to `github.push`, `create_pr` and `merge`.
- Advisory text from OSV and Dependabot is untrusted data, the same as test output.
- No secret appears in a report, digest, log, PR body or alert. Redact through `improve.report.redact` (IMP-17).


**Reuse what exists now (decided 2026-11-15; this wins over the task text below).** This plan was written on 2026-11-02, before these existed:
- **IMP-25 and IMP-26, when messages go out:** digests, alerts and missed-run notices honour the active hours and the one-message-per-hour limit in `whyline.agents.quiet` (`plans/assistant-checkins.plan.md`, CKN-3). A held message goes out when the hours begin. Alerts for a new high or critical vulnerability are not held.
- **IMP-27, approval cards:** send the cards through the waiting-on-you card mechanism (`whyline.ideas.waiting`: one card per item, edited to done, `confirm.issue` codes), so an approval card that was handled in the console is marked done in Telegram. Keep the `improve_change` action and its always-tap policy as written.
- **IMP-28, `pause improvement` and `resume improvement`:** register them as commands in `ideas/intent.py`, so they never go through the router.
- **IMP-33 and IMP-24, the change summary:** when the repository's flow is Pull request, show the Done checklist (`whyline.sdlc.done.checklist`) in the review of a change and in the PR body.

## Part 4: Report, digest and schedule

- [ ] IMP-24: Report and PR body
  Edit `src/whyline/improve/report.py` and its tests only. Every text passes through `redact`.
  1. `repo_section(result) -> str` is Markdown:
     - status line and level
     - a table of checks before (and after, when rechecked) with ✓/✗/flaky
     - **Vulnerabilities:** a table of id, package, version → fixed, severity, new, and the resolution, or `not affected: <why>`
     - findings taken and reported
     - the plan's path and its tasks
     - the fix state, the guard result, the change summary (IMP-20) when waiting, and the PR link once approved
     - a tail of each failing check in a fenced block
  2. `digest_lines(run) -> list[str]`: one line per repo, as in the design's example, with ✅ 🔧 🛡 ✋ ⏳ 📝 ⏭ ⚠️ ⛔.
     - **🛡** a new vulnerability: `N new vulnerabilities: <pkg> <ver>, <id> (<severity>), fixed in <v> → included in the fix | reported`
     - **🔧** a new waiting change: `N fixes ready (+A −D in F files) → waiting for your OK to push`
     - **⏳** an older waiting change: `change waiting for your OK since <date>`
     - **✋** an open PR: `PR #N: CI <green|red|running> → waiting for you to merge` (green), or `… CI red → see PR` (red)
  3. `digest_text(run)` is a header with the date, time and duration, then the lines, then `Full report attached.`
  4. `write_report(run) -> (md_path, docx_path)` uses `whyline.agents.docx.write`.
  5. `pr_body(result) -> str` covers the findings, the checks before and after, the guard result, and links to `docs/sdlc/improve-<date>/`.
  Tests: digest text exactly for the design's example, the vulnerability table, redaction applied, the docx written, and the PR body has no secrets.

- [ ] IMP-25: Sending the digest and alerts
  Create `src/whyline/improve/notify.py` and its tests. Edit `src/whyline/agents/deliver.py` and its tests only to accept a list of attachments.
  1. The delivery is `deliveries.get("improve")`.
  2. `send_digest(run, *, send)`:
     - **combined:** one `deliver.send(delivery, subject, digest_text, attachments)`. The attachments are the report (docx or md, from `delivery.attach`) and each new waiting change's `.patch`. If `deliver.send` takes one attachment today, extend it to a list here and keep the single-file form working.
     - **per-repo:** one send per repo, each with its own section as the attachment
     - It is sent on every run that isn't a dry run, including one where all repos are skipped or all pass. That is the heartbeat.
  3. `alert(text, *, send)` sends one short message with no attachment, when `delivery.on_failure == "alert"`. The runner calls it for:
     - a repo crash
     - a guard refusal
     - the time or agent limit
     - a missed run (IMP-26)
     - a new high or critical vulnerability, once per vulnerability per repo
  4. No delivery set → nothing is sent, and the run's `run.json` says `not delivered: no delivery set`.
  5. Send errors are recorded in `run.json` and never raised.
  Tests: combined with a patch attached, per-repo, the heartbeat on all-pass, alert on/off, no delivery, and a send error recorded.

- [ ] IMP-26: Schedule through the heartbeat, and missed runs
  Edit `src/whyline/agents/tick.py`, create `src/whyline/improve/tick.py`, and their tests only.
  1. `agents/tick.run_tick` calls `_run_improve(now)` beside `_run_workflows`. A failure there is logged and never stops the tick.
  2. `improve/tick.run(now, *, spawn)`:
     - It uses `improve.schedule.due_times` on `settings.schedule`, from the later of the last claimed due time and the moment the loop was last turned on.
     - It claims each due time once in `home()/state.sqlite` (UNIQUE due_at).
     - It spawns `whyline improve run --scheduled` detached through `agents.tick.detached`.
  3. A due time older than `schedule.freshness` is recorded as missed, and `notify.alert` sends "Self-improvement missed its <time> run (this Mac was asleep or off). Next run: <time>." once per missed time.
  4. `enabled=False` or paused → nothing is spawned and nothing is counted as missed. Turning the loop on doesn't count past due times as missed.
  Tests: due → spawned once across two ticks, missed → one alert, off, paused, turned on just after a due time (no missed alert), weekly and monthly due times, and a tick failure contained.

- [ ] IMP-27: Approval cards by Telegram and email
  Edit `src/whyline/ideas/actions.py`, `src/whyline/ideas/worker.py`, `src/whyline/improve/notify.py` and their tests only.
  1. Register the action `improve_change` in `actions.REGISTRY`:
     - payload `{"repo": name, "op": "push"|"discard"|"merge"|"close", "sha": head_sha, "number": N}`
     - its policy always needs a confirming tap or `yes <code>` reply, and the console can't set it to none (the editor shows it fixed)
  2. The worker handler calls `changes.approve(name, sha, by=<channel>)`, `discard`, `merge` or `close`, and replies with the result. For example:
     - "PR #212 opened: <url>"
     - "This change was updated after you saw it. Review it again."
     - "CI is not green yet (running)."
  3. After the digest, `notify.offer_cards(run)` offers one request per decision:
     - a new or still-waiting change: **Push and open PR** / **Discard**, with the summary's first 10 lines in the card
     - an open PR with green CI: **Merge #N** / **Close #N**
     - **Telegram:** through `bot.offer_request` when the assistant bot is bound to the delivery's chat
     - **Email:** through `email_in.offer_request` when assistant email is set up
     - **Neither:** the digest ends with `Approve in the console (Settings → Self-improvement) or run: whyline improve approve <repo>`
     - The confirm TTL runs until the next scheduled run, or 24 hours.
  Tests:
  - registry entry and fixed policy
  - the handler for each op with fake `changes`, including a stale sha
  - cards for a matching chat only
  - an email card
  - the fallback line
  - the TTL

- [ ] IMP-28: `pause improvement` and `resume improvement` from Telegram and email
  Edit `src/whyline/ideas/actions.py`, `src/whyline/ideas/worker.py`, `src/whyline/ideas/intent.py` and their tests only.
  1. Add the verbs `pause improvement` and `resume improvement`, which run at once. Both call `improve.service.pause/resume` (IMP-29).
  2. The reply is "Self-improvement paused. A running check stops at its next step." or "Self-improvement resumed. Next run: <time>."
  Tests: both verbs, by Telegram and email intent, and the reply text.

## Part 5: Service, CLI and console

- [ ] IMP-29: Service
  Create `src/whyline/improve/service.py` and its tests. It is the one API the console and CLI share:
  - `rows()` → `Row(name, level, last_result, last_run_at, held, waiting, pr, new_vulns, paused)`
  - `add_repo(path, level, **fields)`, `update_repo(name, **fields)`, `accept(name)`, `remove_repo(name)` (which also removes its clone and held record)
  - `check_repo(path_or_name, level) -> list[CheckLine(ok, text, fix)]`:
    - git repo with GitHub origin
    - `gh` can push (fix level, so an approval can't fail later)
    - test command set
    - relay set up and committed, and doctor passes (plan level and above)
    - the review agent can run read-only and unattended (`agents.capabilities`)
  - `detect(path)`
  - `settings()`, `save_settings(...)`
  - `set_enabled(on) -> str`. Turning the loop on when the agents heartbeat (`agents.launchd.status`) is off turns it on through `agents.launchd.turn_on` and returns a line saying so.
  - `set_schedule(schedule)`, `next_run()`
  - `pause()`, `resume()`
  - `run_now(only=None, dry_run=False)` starts the run detached and returns the run id
  - `history(n)`, `run_detail(run_id)`, `resend(run_id)`
  - `discard_held(name)`
  - `changes(name) -> Waiting | None`, `diff(name) -> str`
  - `approve(name, sha, by)`, `revise(name, feedback)`, `discard(name)`, `merge(name)`, `close(name)`, all through `improve.changes`
  - `vulns(name) -> list[Vuln]`, from the last run

  Tests: each through fakes, and check lines for each level.

- [ ] IMP-30: CLI
  Create `src/whyline/improve/cli.py`, edit `src/whyline/cli.py`, and add tests.
  Subcommands:
  - `whyline improve status | run [--repo NAME] [--dry-run] [--scheduled] | history [-n N] | show RUN | resend RUN | pause | resume`
  - `whyline improve repos list | add PATH --level L [--test CMD] [--check NAME=CMD]... | set NAME [...] | accept NAME | check NAME | remove NAME`
  - `whyline improve changes NAME` prints the summary and the diff. `approve NAME` shows the summary and the sha, asks "Push and open a PR? [y/N]", and passes that sha. `--yes` is allowed only together with `--sha SHA`.
  - `whyline improve revise NAME "feedback" | discard NAME | merge NAME | close NAME | vulns NAME`
  - `whyline improve on | off`
  - `whyline improve schedule daily HH:MM [--weekdays] | weekly mon,thu HH:MM | monthly 1-28|last HH:MM`
  - `whyline improve settings [--digest combined|per-repo] [--run-minutes N] [--max-agent-starts N]`
  - `whyline improve delivery` opens the same editor flow as `whyline agents delivery` for the id `improve`

  Rules:
  - `add` prints the level's lines and asks to accept, unless `--yes` is given.
  - Every subcommand calls `service`.
  - `run --scheduled` runs in the foreground; the tick uses it.

  Tests: parsing, the accept prompt, `--yes`, and each subcommand calling the service.

- [ ] IMP-31: A Self-improvement tab in Settings
  Edit `src/whyline/console/settings_screen.py`, create `src/whyline/console/improve_screens.py`, edit `src/whyline/console/tui.py` where it opens Settings, and add tests in `tests/console/`.
  1. **Tabs:** the Settings modal gets two tabs, **AI providers** (today's content, unchanged in behaviour) and **Self-improvement**. `ProviderSettingsScreen` keeps its constructor. The new tab's widgets come from `improve_screens.SelfImprovementPane`, which takes injected service callables, so the module still doesn't import the main app. Settings opens from every mode, as today.
  2. **The tab's top section:**
     - **Self-improvement loop** switch (Off by default)
     - **How often:** Daily / Weekly / Monthly
     - **Daily:** a **Weekdays only** checkbox
     - **Weekly:** seven day checkboxes
     - **Monthly:** a Select of 1–28 and **Last day**
     - **Time:** HH:MM
     - **Messages:** Combined / One per repo
     - **Limits:** Run limit (minutes) and Max agent starts
     - **Defaults for new repos:** Fix from, Max fixes, Max minutes per repo, Max changed lines

     Only the fields for the chosen frequency show.
  3. **Live lines:** under Time, `Next run: <describe>, <date time>` updates as fields change (from `schedule.next_due`), and so does `The Mac must be awake at that time; a missed run is reported when it wakes.` With the loop Off, the line is `Off: nothing runs on a schedule.`
  4. **Save:** Save / Cancel is shared with the providers tab, and both tabs' staged changes save together. Self-improvement saves through `service.set_enabled`, `service.set_schedule` and `service.save_settings`. A bad value shows the `ScheduleError` text beside the field and saves nothing. Turning the heartbeat on shows `service.set_enabled`'s line.
  Tests:
  - both tabs present, with providers behaviour unchanged (the existing tests pass)
  - frequency switching shows the right fields
  - the next-run line for each frequency
  - Save calling the service with the staged values
  - Cancel writing nothing
  - a bad time blocks Save
  - the tab reachable at 80x24 and 120x40

- [ ] IMP-32: Repos in the Self-improvement tab
  Edit `src/whyline/console/improve_screens.py` and its tests only.
  1. **Repo table:** a **Repos** table of `service.rows()`:
     - columns Repo, Level, Last result, Last run
     - ⏸ for a paused repo, ✋ for a held fix, ⏳ **Waiting for you** for a change waiting for approval, 🛡 N for new vulnerabilities, and `PR #N · CI …` for an open PR
     - buttons **Add repo…**, **Edit…** and **Remove**
  2. **Add repo…** asks for a folder (the existing folder picker) and a level. It then shows **Check** lines from `service.check_repo`, each with ✓/✗ and a fix button where one exists:
     - **Set up relay** opens the existing relay Set up for that folder
     - **Sign in to gh** shows the command
  3. **Edit…** shows:
     - level, test command, extra checks (add/remove, and **Detect** which fills suggestions to tick)
     - Fix from, Max fixes, Max minutes, Max changed lines (prefilled from the defaults)
     - Never touch (one per line)
     - Paused
     - **Discard held fix**, only when one is held
  4. **Saving a repo** shows the level's lines from `allows` with **Accept and save** / **Cancel**, and saves through `service.add_repo` / `update_repo` + `accept`. **Remove** asks to confirm.
  5. `open_repo(name)` opens the tab with that repo's editor, for IMP-35.
  Tests: check lines, Detect adding ticked checks, accept needed after a level change, cancel writing nothing, remove confirm, and `open_repo`.

- [ ] IMP-33: Review change, and vulnerabilities, in the console
  Edit `src/whyline/console/improve_screens.py` and its tests only.
  1. A ⏳ row has **Review change…**, which opens `ReviewChangeScreen`:
     - the summary, the findings and vulnerabilities it resolves, the checks before and after, and the guard result
     - the diff, file by file, in the existing diff view
     - buttons **Push and open PR**, **Ask for changes…** (a text box), **Discard** (confirm) and **Open in console**
  2. **Push and open PR** calls `service.approve(name, sha_shown, "console")` with the sha the screen loaded, and shows the result. On `needs approval again`, the screen reloads with the new summary.
  3. **Open in console** opens the clone folder as the console's repo, the same way choosing a repo does today.
  4. A row with an open green PR has **Merge** and **Close**, each with a confirm.
  5. A 🛡 row has **Vulnerabilities…**, a table of id, package, version → fixed, severity, new, and the resolution, with **Open advisory** links.
  Tests: the screen shows summary and diff, approve passes the loaded sha, the stale-sha message reloads, ask for changes calls revise, discard confirm, merge only on green, and the vulnerability table.

- [ ] IMP-34: Run now, Pause, Delivery and History in the tab
  Edit `src/whyline/console/improve_screens.py` and its tests only.
  1. **Run now** asks "All repos, or <selected repo>?" with a Dry run checkbox, then calls `service.run_now`. **Pause / Resume** toggles through `service.pause` / `resume`. Both act at once and don't wait for Save; the tab says so.
  2. **Delivery…** opens the existing agent delivery editor for the id `improve`, including **Send test**.
  3. **History** lists runs from `service.history`: Started, Duration, and one short result per repo. Opening a run shows the report Markdown in the existing Markdown viewer, with these buttons, each hidden when there's nothing to open:
     - **Open Word report**
     - **Open PR** and **Open change** (the `.patch`)
     - **Open log** per repo
     - **Resend**
  Tests: run now args, the pause toggle, the delivery editor opened with id `improve`, history rows, and resend.

- [ ] IMP-35: The Self-improvement line in Relay → Set up
  Edit the Relay Set up screen in `src/whyline/console/relay_screens.py` (or where `relay-setup` opens it) and its tests only.
  1. Add one line for the current repo:
     - `Self-improvement: <Level> · <describe(schedule)>` (plus `· change waiting for you` when one is) with **Change…** when the repo is in the list
     - `Self-improvement: off for this repo · Turn on…` when it isn't
     - `(loop is off)` added when the loop is off
  2. **Change…** opens Settings on the Self-improvement tab at `open_repo(name)`. **Turn on…** opens **Add repo…** with this folder filled in. Nothing is saved from Set up itself.
  Tests: each text, and both buttons opening the right place.

## Part 6: Prove, document, publish

- [ ] IMP-36: End-to-end test on real git
  Create `tests/improve/test_end_to_end.py` only.
  1. **Setup:** a temporary "user" repo with a bare origin, one failing test, and relay files committed.
  2. **Fakes:**
     - OSV returns one high vulnerability for a pinned dependency, fixed in the next version
     - `gh` returns WRITE permission and records `pr create`
     - the review agent returns one finding
     - the SDLC stub writes a one-task plan
     - the relay stub fixes the test and commits
  3. **Asserts:**
     - after the run, the change is waiting, the bare origin has no `improve/*` branch, and the digest is sent once with a docx and a `.patch`
     - the user repo's files and refs are unchanged
     - `service.approve` with the shown sha pushes `improve/<date>` to the bare origin and creates the PR (fake `gh`), with the expected PR body
     - a second run reviews but makes no new fix: "PR #1 is open"

- [ ] IMP-37: Documentation
  Edit `README.md` and create `docs/self-improvement.md` only.
  Explain in user terms:
  - what Self-improvement does, with the levels table
  - adding a repo
  - schedule and delivery (Telegram and email), and the heartbeat
  - the vulnerability check: what is sent to OSV.dev (names and versions only) and how resolutions are chosen
  - approving changes: nothing is pushed or merged without your approval, how to approve from the console, Telegram, email or the CLI, and Ask for changes
  - the safety rules (never the default branch, the guard, limits, pause)
  - held fixes
  - that the Mac must be awake
  - the CLI

  Use one screenshot placeholder per screen as `<!-- screenshot: … -->`.
