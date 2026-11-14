# Release hardening: checked release notes, earlier security checks, a way back, and a safer pipeline

Status: draft for review, 2026-11-15. Builds on Release (`whyline.release`, REL, RFB, RCR) and the security gate (`whyline.security`, SEC). Four parts, each its own small plan, in the order below. Runs after `plans/sdlc-done.plan.md`; Part 1 can run any time.

## Where whyline stands

- **Release** brings in main, checks ready, sets the version, writes notes, commits, runs the checks, pushes, waits for CI, tags, creates the GitHub release, publishes (PyPI, npm, Docker, Homebrew, custom), verifies and runs after-steps. It resumes, has step, ask and auto modes, and explains CI failures.
- **Release notes** are written by one read-only agent between `<notes>` markers (`release/notes.py`). An answer without the markers falls back to the raw commit list. The user confirms them.
- **The security gate** checks secrets (gitleaks rules, with an allowlist), dependency vulnerabilities (OSV over six lockfile types), package contents (wheel, sdist, npm package, Docker context), git history once, and offers a pre-commit hook and an agent-run audit.
- **The publish workflow** refuses a tag that disagrees with the version, checks the sdist for private paths, installs the wheel and each extra, and publishes with trusted publishing.

## Problems

1. **Release notes can carry the agent's own chatter.** Lines like "Here are the release notes I created, please review" got into the notes for 0.3.70, 0.3.71 and 0.3.72 and were removed by hand. The markers (RFB-8) cut text outside them, but nothing checks what is inside. And the fallback is the raw commit list: v0.3.73's notes list `chore: tick RCR-6 in the plan` and `setup: assign implementer/tester/reviewer roles`, which mean nothing to a user.
2. **Secrets are caught late.** `pre_commit` is off by default and the relay commits every task, so a key committed in task 3 is in history before the release scan sees it.
3. **The code is never read for flaws.** `audit` is off by default, and there is no fixed-rule scan for risky code.
4. **There is no way back from a bad release**, and no rehearsal before one.
5. **The pipeline trusts moving targets.** Actions are pinned by tag, test jobs have the default token permissions, nothing updates the actions, and the published files carry no proof of where they were built.
6. **Small gaps:** only tests gate a release (no lint or type check), dependency licences are not checked, and there is no `SECURITY.md` or `CHANGELOG.md`.

## Part 1: Release notes that are checked (plan `release-notes-review`)

- **A fixed check first, no model.** `notes.lint(text, commits) -> list[Problem]` flags a line that:
  - talks about the notes or to the reader of a chat: "here are", "I have", "I've", "let me know", "please review", "as requested", "hope this helps", "below are", a question, a sign-off
  - is first person ("I", "we'll", "my")
  - is wrapped in a code fence around the whole text, or repeats the `# v<version>` title
  - is process noise: `chore: tick …`, `setup: …`, `merge: …`, `plan: …`, `chore: release …`, `chore: record decisions`
  - contains a secret (`security.secrets.scan_text`), a home path (`/Users/…`, `/home/…`, `C:\Users\…`), or an email address that is not in the repository's own metadata

  Each problem has the line, the reason and whether the line can simply be removed.
- **A second agent reviews, and it is not the writer.** After the draft, a different enabled agent gets the commit subjects, the draft and the lint problems, and returns the notes between the same markers with: chatter and process lines removed, wording kept or tightened, nothing added.
  - **Nothing new.** Whyline compares the result with the draft: the reviewer may delete lines and reword them, but a bullet whose words overlap no draft line and no commit subject is removed and noted.
  - With only one enabled agent, the same agent reviews in a fresh turn, and the dialog says so.
- **Then the fixed check again.** Whatever comes back is linted. Lines that still fail and can be removed are removed. If what is left is empty or still fails, whyline falls back.
- **A better fallback.** The commit list is grouped (New for `feat:`, Fixed for `fix:`, Docs for `docs:`, Other), with the prefix and the task id in brackets stripped, and process lines dropped. A release with only process commits says `Maintenance release.`
- **The confirm dialog shows the work:** `Written by claude, checked by codex. 3 lines removed.` with **See what was removed** (a before and after), **Edit**, **Use the commit list instead** and **Approve**. In auto mode the same line goes in the release log.
- **Settings**, in Release → Set up and `whyline release settings`: **Check release notes with a second agent** (on by default), and the reviewer agent (default: any enabled agent other than the writer).
- **The Telegram go-ahead** (`ideas/goahead.confirm_notes`) sends the checked notes with the same summary line.
- `whyline release notes --check <file>` lints a notes file and prints the problems, for a user who writes notes by hand.

## Part 2: Security earlier, and on the code (plan `security-earlier`)

- **The pre-commit hook is on for new set-ups**, and Release → Set up offers to turn it on where it is off. It runs the staged secret scan (`whyline security scan --staged --hook`), which takes well under a second.
- **The relay and the hook.** When a relay's commit is stopped by the hook, the console shows a pause with the finding (rule, file and line, never the value) and the choices **Allow this** (adds the allowlist entry and commits again), **Open the file** and **Ask an agent to remove it**. This needs no whyline-relay change: the relay already pauses when its commit fails, and the console's Resolve reads the hook's stop line.
- **A fixed-rule code check**, built in, for Python first: `shell=True` with a non-literal command, `eval`/`exec` on non-literals, `pickle.load(s)` and `yaml.load` without a safe loader, `verify=False`, `tempfile.mktemp`, weak hashes used for security (`md5`, `sha1` near "password", "token", "sign"), `assert` used for an access check, `0.0.0.0` binds, and SQL built with string formatting. It reads the syntax tree (`ast`), so comments and strings don't trigger it.
  - A new setting `code: block-high | warn | off` (default `warn`), beside secrets, dependencies and contents.
  - Findings can be allowed like any other, with a reason.
  - Bandit or Semgrep, when installed, are used as well, the way gitleaks is today.
- **The agent audit runs on what changed.** A new audit mode `changed` reviews only the files changed since the last release tag (at most 60 files, largest diffs first), with the same method files and report schema. The default becomes `warn` with scope `changed` for releases that change code. A full audit stays a button.
- **A licence check on dependencies.** Each dependency's licence is read from installed metadata (`importlib.metadata`) or the lockfile where it has it. A setting lists licences to flag (default: GPL, AGPL, SSPL and "unknown"), as `warn`. A new dependency since the last release is listed with its licence in the Ready check.

## Part 3: Rehearse, and a way back (plan `release-safety`)

- **Rehearse.** A button beside Release, and `whyline release run --rehearse`: it runs every step up to the first one that can't be undone, without changing the repository. It works in a temporary worktree: bring in main, bump, write and check the notes, run the checks and the security scan, build the packages and scan their contents. Then it shows what a real release would push, tag and publish: the version, the commit list, the notes, the files in each package and their sizes. Nothing is committed, pushed or tagged.
- **Release went wrong.** A button on a finished release in the Release screen, and `whyline release recover <version>`, with three guided actions:
  - **Warn users:** mark the GitHub release with a notice at the top of its notes (`gh release edit`) and, optionally, as a pre-release so it is no longer "latest".
  - **Yank from PyPI:** PyPI has no command for this, so whyline opens the version's manage page, says exactly what to click and what reason to type, and then checks the JSON API until the version shows as yanked. npm uses `npm deprecate` after a confirm. Docker and Homebrew show the steps.
  - **Ship a fix:** start a patch release from the previous good tag or from the current branch, with the bad version named in its notes.

  Nothing is deleted: no tag is removed and no history rewritten. Each action asks first and is recorded as a `whyline note`.
- **A release record.** Each finished release writes `docs/releases/v<version>.json`: the commit, who confirmed each step and when, the checks run and their results, the security scan summary, the package files with their sha256, and the workflow run. Rehearse and Recover read it.

## Part 4: A safer pipeline (plan `release-supply-chain`)

- **Pin the actions.** `whyline release setup workflows --pin` rewrites each `uses: owner/action@vN` in the repository's workflows to the commit that tag points at now, with the tag kept as a comment. It shows the diff and asks. Release → Set up shows `3 actions are not pinned` with the same action.
- **Keep them current.** It offers a `.github/dependabot.yml` for `github-actions` (weekly), and for the package ecosystem the repository uses.
- **Least permission.** It adds `permissions: contents: read` at the top of workflows that have none, leaving jobs that set their own as they are.
- **Proof of origin.** The PyPI workflow template turns on attestations for the published files (trusted publishing already carries the identity), and attaches a build provenance attestation and an SBOM (CycloneDX, built from the lockfile whyline already reads) to the GitHub release. The verify step checks the attestation exists.
- **More than tests.** Release → Set up → Checks suggests commands from what the repository has: a linter and a type checker when their config is present (`ruff`, `mypy`, `pyright`, `eslint`, `tsc`), each added only when the user ticks it. A suggested check is run once first, and one that fails today is offered as `warn` so it doesn't block the next release.
- **Project files.** It offers a `SECURITY.md` (how to report a vulnerability, with the user's chosen contact) and builds `CHANGELOG.md` from the per-version notes, newest first, kept up to date by the release's commit step.

## Goals

- Release notes a user can read, with no agent chatter, without the user cleaning them.
- A secret or a risky line is caught when it is written, not at release.
- A bad release has a clear, safe way back, and a release can be rehearsed.
- The publish pipeline runs only code that was pinned, and the files it publishes can be traced to it.

## Non-goals

- Deleting or moving a published version or tag.
- Other hosts than GitHub, or other CI systems.
- A full static analyser: the built-in rules are a short, fixed list.
- Signing with the user's own keys.

## Anti-goals

- A reviewer agent that adds claims to the notes.
- A check that blocks a release with no way for the user to allow it or go on.
- A hook that slows every commit noticeably, or that the user can't turn off.
- Rewriting the user's workflows without showing the diff and asking.
- A finding, a log or a release record that contains a secret's value.

## How it fits the code today

- `release/notes.py`: `draft`, `extract`, `fallback`, `build_prompt`. Lint, review and the grouped fallback are added here. `release/plan.py` `default_ask_agent` runs the read-only turn; the reviewer uses the same call with another agent (`relaychat.agent_choice`).
- `release/cli.py` `_confirmers` and `console/release_screens.py`: the notes confirm.
- `security/settings.py` (`SecuritySettings`: secrets, dependencies, contents, pre_commit, audit), `security/scan.py` (`run`, `run_audit`, `_gate_audit`), `security/hook.py` (`install`, `set_installed`), `security/audit.py` and `audit_method/`, `security/findings.py`, `security/external.py` (optional tools), `security/lockfiles.py` and `deps.py`.
- New: `security/code.py` (the rules), `security/licences.py`.
- `console/recovery.py` (Resolve problems and options) for the hook stop during a relay.
- `release/engine.py` (steps, irreversible flags), `release/state.py`, `release/targets/*` (`verify`), `release/workflows.py` (templates), `release/setup_github.py`.
- New: `release/rehearse.py`, `release/recover.py`, `release/record.py`, `release/pins.py`.

## Calls I made (please check)

- **The notes reviewer may remove and reword, never add.** Whyline enforces it by comparing with the draft and the commits, not by trusting the reviewer.
- **The second-agent check is on by default.** It costs one short extra turn per release.
- **The code check starts as a warning**, so it doesn't block the first release after it lands. You can raise it to block-high.
- **The audit default becomes "warn, changed files only".** A full audit on every release would be slow and costly.
- **Yanking stays a guided manual step** on PyPI, because PyPI offers no command for it.
- **Pinning actions is offered, not automatic.** It changes your workflow files, so you see the diff first.
- **Order:** notes review first (it's the one that bit three releases), then security earlier, release safety, supply chain.
