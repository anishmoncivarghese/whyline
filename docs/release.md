# Release

The **Release** button (Relay mode) publishes a version for you: it checks the
repository is ready, bumps the version, writes release notes, commits, pushes,
waits for CI, tags, and creates the GitHub release. Everything is also in
`whyline console`; nothing needs a terminal.

## Targets

Targets are what a release publishes to. Tick them in **Release → Set up**; the
choice is saved in `.whyline/release.toml`.

| Target | What it does |
| --- | --- |
| GitHub | Pushes the branch, waits for CI, tags `vX.Y.Z` and creates the GitHub release with your notes. Always on: every other target publishes through it. |
| PyPI | Publishes the Python package. |
| npm | Publishes the npm package. |
| Docker | Pushes the image to the registries you list (default `ghcr`). |
| Homebrew | Updates the formula in your tap. |
| Custom | Runs your own command, then an optional verify command. |

Every target publishes after the GitHub release exists, in the order PyPI,
npm, Docker, Homebrew, Custom, then one **Verify the release** step checks them
all. A target you leave unticked adds no steps and runs no commands.

## Setting up each target

Each target's **Set up…** button shows what is missing and offers the fix.
whyline keeps only your choices in `.whyline/release.toml`; see
[What is never stored](#what-is-never-stored).

### GitHub

- **Publishes:** pushes the branch, waits for CI, tags `vX.Y.Z` and creates the
  GitHub release with your notes.
- **One-time setup:** needs `git`, the `gh` tool, an `origin` remote on GitHub
  and a signed-in `gh`. **Set up…** offers Sign in, Create repository (private
  or public) or Ask agent. Without `gh` it shows `brew install gh` with a Copy
  button.
- **Tokens:** none held by whyline. `gh auth login` keeps its own token.
- **Check by hand:** `git ls-remote --tags origin vX.Y.Z` and
  `gh release view vX.Y.Z`.

### PyPI

- **Publishes:** adds `release-pypi.yml` (or uses an existing workflow that
  runs on tags and uses `pypa/gh-action-pypi-publish`). The tag push starts it,
  the step waits for that run, then Verify waits up to 5 minutes for the
  version to appear on pypi.org.
- **One-time setup:** **Add workflow**, commit it, then on pypi.org open
  *Publishing* and add a trusted publisher with the Owner, Repository,
  Workflow file name and Environment (`pypi`) that Set up shows. A brand new
  project uses *Add a pending publisher*.
- **Tokens:** none. Trusted publishing swaps GitHub's short-lived identity for
  a PyPI upload token inside the run.
- **Check by hand:** open `https://pypi.org/project/<name>/<version>/`, or
  `curl -s -o /dev/null -w '%{http_code}' https://pypi.org/pypi/<name>/<version>/json`
  prints 200.

### npm

- **Publishes:** adds `release-npm.yml` (or uses an existing tag workflow with
  `npm publish`), waits for its run, then Verify waits up to 5 minutes for the
  version on the registry.
- **One-time setup:** the package must exist once. Run `npm login` and
  `npm publish` in a terminal the first time; then on npmjs.com add a trusted
  publisher with the Owner, Repository and Workflow file name Set up shows.
  `"private": true` in `package.json` blocks the release.
- **Tokens:** none. The workflow uses trusted publishing (npm 11.5.1 or newer)
  with provenance.
- **Check by hand:** `npm view <name>@<version> version`.

### Docker

- **Publishes:** adds `release-docker.yml` (or uses an existing tag workflow
  with `docker/build-push-action`) that pushes the image to each registry you
  list, `ghcr` by default. Verify runs `docker manifest inspect` when docker is
  installed; without docker the tag run's success is the check.
- **One-time setup:** a `Dockerfile` in the repository (**Draft Dockerfile**
  asks the agent and shows it before anything is written) and the workflow.
  The image defaults to `<owner>/<repo>` in lowercase.
- **Tokens:** GHCR uses the run's own `GITHUB_TOKEN`. Docker Hub needs the
  GitHub secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`; **Store as GitHub
  secrets** sends them to `gh secret set` on stdin, so they never appear in a
  command line, and whyline keeps no copy.
- **Check by hand:** `docker manifest inspect ghcr.io/<owner>/<repo>:<version>`.

### Homebrew

- **Publishes:** bumps `Formula/<name>.rb` in your tap to the new tag's source
  tarball (url and sha256) in a scratch clone under
  `.git/whyline-release/tap`, runs `brew update-python-resources` when the
  formula has resource blocks and `brew` is installed, then commits and pushes.
- **One-time setup:** a **public** tap repository named
  `<owner>/homebrew-<name>` (default `homebrew-tap`; **Create tap** makes it)
  and a first formula (**Draft formula** asks the agent and shows it before it
  is pushed). Users install with `brew tap <owner>/<name>` and
  `brew install <formula>`.
- **Tokens:** none. The push uses the account `gh` is signed in with, which
  must be able to push to the tap.
- **Check by hand:** open `Formula/<name>.rb` in the tap and look for
  `.../archive/refs/tags/vX.Y.Z.tar.gz`; or `brew update && brew info <formula>`.

### Custom

- **Publishes:** whatever you write under `[[targets.custom]]` in
  `release.toml` (`name`, `run`, optional `verify`). Each entry is an
  irreversible step with `WHYLINE_RELEASE_VERSION` and `WHYLINE_RELEASE_TAG` in
  its environment. A `verify` command that exits 0 before the run means it
  already happened (the step is skipped); after the run it means it worked.
- **One-time setup:** the program named first in `run` must be on `PATH` (or at
  the path given); Ready checks that.
- **Tokens:** yours to manage. Keep them in the tool's own store or the
  environment, not in `release.toml`.
- **Check by hand:** run the `verify` command in the repository with the two
  variables set.

### Release options

**Branch**, **Checks** (one command per line, run before the push), **CI jobs
to ignore**, **Notes path** (default `docs/releases/v{version}.md`) and
**After-commands** are on the same Set up tab. Save asks before you close
with unsaved changes.

**CI jobs to ignore** takes one name per line: either a job's name as GitHub
shows it, such as `test (windows-latest, 3.13)`, or a whole workflow's name,
such as `nightly`. Wait for CI leaves those out. A workflow run that failed
only because of an ignored job counts as passed, and the release does not wait
for an ignored job that is still running. Any other failed job stops the
release and is named, as `CI failed: ci / test (ubuntu-latest, 3.13)`. With no file yet, Set up shows what detection suggests;
it is only kept when you press **Save**.

### Target status

Each ticked target's row in Set up shows its last check: `✓ Ready · checked
<date>` or `✗ <first failing item>`, saved per repository. A target never
checked says `Not checked yet`; an unticked target shows no status and takes
one line. Opening Set up re-checks the ticked targets in the background and
updates the rows as results arrive.

## Running a release

Open **Release**, pick the next version (patch, minor, major or custom), press
**Check**, then **Start**. Check lists each item with ✓ or ✗ and what to do
about a ✗; Start stays off until every item is ✓.

### An unreleased current version

When tag `v<version>` exists neither locally nor on origin, the current
version has never been released (a plan may have set it). The screen then opens
with `Current version: 0.3.69 (not released yet)` and defaults to
`current → 0.3.69 (not released yet)`, listed first, so the version is not
skipped. Once it is tagged the default is `patch`. `whyline release run` with
no `--bump` or `--version` uses the unreleased current version and prints which
it chose.

### Releasing right after a relay

A relay works on its own branch. Press **Release** there when it finishes: the
screen shows `Releasing <branch> · <n> commits · main has <m> commits this
branch doesn't`, then publishes to `main` as usual. `whyline release` prints the
same line.

The first step, **Bring in main**, makes sure checks run on what will land:

1. It stops with `A relay is running here; release when it finishes` while a
   relay is running in the checkout, and with `Commit or stash these first:
   <files>` if the tree has changes. Nothing is changed in either case.
2. It fetches, and when `main` is ahead merges it into the branch
   (`merge: bring main into <branch> for v<version>`).
3. It moves each finished plan (every task ticked) and its `.tests.md` into
   `plans/done/` and commits `chore: move finished plans to plans/done`. A plan
   with an unticked task stays where it is.

In ask mode it asks first and shows the line above plus `Moves to plans/done:
<names>`. The step is skipped on the release branch itself, when `main` has
nothing new and no plan is finished, and on resume once done.

**Conflicts.** If the merge conflicts, whyline runs `git merge --abort`, leaving
a clean tree, and stops with `Merge main into <branch> yourself (or ask an
agent), then resume the release. Conflicts: <files>`. Merge by hand, then
**Resume release**.

**The setting.** **Bring in main before releasing** in Release settings (default
on; `bring_in_main` in `release.toml`) turns the step off. For one CLI run use
`whyline release run --no-bring-in`.

**The other main checkout.** After the push, if another checkout of `main`
exists (a separate worktree) and has no changes, it is fast-forwarded and the
release reports `Updated <path> to v<version>`. With changes it is left alone:
`Your <branch> checkout at <path> has changes; update it with git pull`. A
failure there is only a warning, never a failed release.

### Modes

- **ask** (default): asks before each irreversible step (the push, the tag, the
  GitHub release) and shows the release notes for you to use, edit or stop.
- **step**: asks before every step.
- **auto**: asks nothing. Only use it after Check is all ✓.

### Release notes

The notes step asks an agent to draft `docs/releases/v<version>.md` (the
**Notes path** setting) from the commit subjects since the last tag, matching
the style of the previous release's notes. The agent runs once, read-only, in an
empty temporary folder, so it cannot edit your files or make a commit. It is
told to put the notes between a line `<notes>` and a line `</notes>`, and only
that part is kept (the last pair, if there are several). If the agent fails,
or its answer has no usable pair, the notes are the plain commit list and the
release log says `The agent's notes were not usable; using the commit list`.

In ask mode you check the notes before they are used. In the console the
notes appear in a scrollable box with **Use these notes**, **Edit** (opens the
file in your editor, then shows it again) and **Stop**. On the command line
`whyline release run` prints the first 40 lines and asks
`Use these notes? [y/N/e]`; `e` opens `$VISUAL` or `$EDITOR`, then asks again.
`--yes` skips the question.

If you choose a bump while `docs/releases/v<current>.md` exists and
`v<current>` was never released, Release asks `v<current> has notes and was
never released. Release v<current> instead?` before it starts; the default is
Yes.

### Security checks

Before anything is pushed, Ready gains a **Security** item: it scans the
commits about to be pushed for secrets, checks dependencies against OSV.dev and
inspects the files each package would publish. Secrets and package contents
block by default; dependencies block on high or critical. Open **Security…**
to Fix, Ignore once or Allow a finding. Settings, what leaves your Mac, Scan
history, Check every commit, GitHub protection and the optional deep audit are
in [docs/security.md](security.md).

## When CI fails

When CI (or a PyPI, npm or Docker publish run) fails, the failure screen says
why in plain words, then the workflow and attempt, the failing test names or the
last lines of the log, and a link to the run.

| Cause | What it means | What to do |
| --- | --- | --- |
| `no-runner` | GitHub never started the job (no step ran, or the annotation says the job was not acquired by a runner or capacity ran out). Your code is fine. | Rerun failed jobs. |
| `timeout` | The job ran past its time limit and was stopped. | Rerun; if it keeps happening, look at the slow step. |
| `tests` | A test step failed. The test names (`FAILED …`) are listed. | Fix the code. Rerunning won't help a real failure. |
| `publish` | A publish or upload step failed after the tests passed. | Check the publish settings, such as the trusted publisher. |
| `other` | Anything else, or GitHub could not be asked for details. | Open the run, or Ask an agent. |

### Rerun failed jobs

**Rerun failed jobs** runs `gh run rerun <run> --failed` and resumes the
release at the step that failed. The wait picks up the new attempt of the same
run, so the release carries on to PyPI by itself. It is the primary button for
`no-runner` and `timeout`. For `tests` it first asks `Tests failed. Rerunning
won't fix a real failure. Rerun anyway?`. With nothing stopped, or no saved
failure, it says `Nothing to rerun`. **Open run** opens the run in your browser.

### Ask an agent and Fix with an agent

**Ask an agent** has a read-only agent explain the failure: it gets the failure
text, up to 200 lines of the failed job's log, the commits since the last tag
and `git diff --stat`, and runs in an empty temporary folder, so it cannot edit
files or commit. The answer is shown and added to the release log. When the
agent says code must change, **Fix with an agent** appears. It opens a Fix
session with the failure and the answer as context, at your Fix level, so each
change waits for your approval and nothing is pushed. When it ends, the screen
says `Start a new release when the fix is in; v<version> is already tagged.`

### When GitHub has no runner

**When GitHub has no runner** in Release → Set up (`release.on_no_runner`):

- **ask** (default): show the failure screen.
- **rerun once**: rerun automatically, once per run, and log `GitHub had no
  runner for <job>; rerunning once`. A second `no-runner` failure on the same
  run shows the screen. Tests and every other cause are never rerun
  automatically.
- **off**: show the screen and don't make Rerun the primary button.

### Slow GitHub replies

While waiting for CI or a tag workflow, a `gh` timeout, an OS error or a failed
`gh run list` is retried at the normal poll interval, with `GitHub is slow to
answer (2 of 5)` as the detail. A good reply resets the count; five in a row
stop the step with `GitHub didn't answer 5 times in a row; check your
connection and resume`.

### From a terminal

- `whyline release why` prints the failure of the stopped release (or `The
  release isn't stopped`).
- `whyline release rerun [--yes]` reruns the failed jobs and resumes. It asks
  `Tests failed. Rerunning won't fix a real failure. Rerun anyway? [y/N]` for
  cause `tests` only.
- `whyline release ask` prints the agent's answer.
- `whyline release settings [--on-no-runner ask|"rerun once"|off]` sets the
  no-runner behaviour; with no option it prints the Release settings.

## Resume

A failed or stopped release keeps its place in `.git/whyline-release/`.
When a step fails, the popup offers **Resume release** (continue after you fix
the cause) and, when a pull request is the way forward, **Open PR**. Resume
skips every step already done. Choosing **Stop** on the notes stops the
release; Resume continues with the notes file as it is on disk (including any
edits you made with **Edit**).

## From a plan

- **A release task in a plan.** When Relay pauses on one, the **Release
  done…** button offers **Run Release**, **Mark released** and **Skip**. Run
  Release opens the same screen with the task's checklist above the steps.
  When the release finishes, the console sends `done <task>` for you, exactly
  as if you had typed it. A failed or stopped release leaves the relay paused,
  so you can Resume the release or answer the task yourself.
- **After a plan.** Tick **Release when a plan completes**
  (`start_after_plan = true`). When the relay finishes with every plan task
  ticked, the console opens Release with Check already run. In ask and step
  mode it then waits for you. In auto mode it starts only when every item is ✓.

## Troubleshooting

Each message below is what the release shows. Fix the cause, then press
**Resume release**; steps already done are skipped, so a tag or GitHub release
is never made twice.

**Before anything is pushed**

- **Not ready: …** Each item names its fix. The tag item, `Tag vX.Y.Z exists
  locally` or `on origin`, means that version was already released: pick
  another.
- **Check failed: `<command>`** One of your Checks exited non-zero; the last
  lines of its output follow. Fix it and resume.
- **You stopped at the release notes** Edit the file if you like, then resume.
- **A release is already running.** Another run holds the lock. Wait for it, or
  if its process is gone, resume.
- **The stopped release is for X, not Y.** Resume the version it was started
  for, or finish or discard that release first.

**Push, CI, tag and GitHub release**

- **origin/main has commits this branch doesn't; merge them first.** Pull,
  merge, then resume.
- **main is protected; open a pull request instead.** Use **Open PR**, merge
  it, then resume.
- **git push failed**, **git tag failed**, **git push of vX.Y.Z failed**,
  **gh release create failed** Git or `gh` printed the reason after the colon;
  usually sign-in (`gh auth login`) or network.
- **CI failed: `<workflow>` / `<job>` `<url>`** Open the link, fix the
  failure, push the fix as a new commit if needed, then resume. To stop a job
  that is known to fail from blocking releases, add its name (the part after
  the `/`) to **CI jobs to ignore**.
- **CI is still running after 60 minutes.** Resume to keep waiting.

**PyPI, npm and Docker**

- **No PyPI / npm / Docker publishing workflow; set up … and add one.** Use
  **Add workflow** in the target's Set up. A workflow must run on `push` of
  `tags` and contain the publish action to be found.
- **`<workflow>.yml` failed in job `<job>` `<url>`** Open the run. For PyPI and
  npm the usual cause is a missing or mismatched trusted publisher (Owner,
  Repository, Workflow file name, Environment); fix it on the registry's site
  and re-run the job from GitHub, then resume.
- **`<workflow>.yml` is still running after 45 minutes.** Resume to keep
  waiting.
- **`<name> <version>` is already on PyPI / npm.** Pick another version. A
  version can never be published twice.
- **Missing GitHub secrets: DOCKERHUB_USERNAME, DOCKERHUB_TOKEN** Choose
  **Store as GitHub secrets** in Docker's Set up.
- **No Dockerfile** Choose **Draft Dockerfile** in Docker's Set up.

**Homebrew**

- **Tap `<repo>` not found** / **Formula/`<name>`.rb is not in the tap** /
  **You cannot push to `<repo>`** Use **Create tap** and **Draft formula**, or
  sign in to `gh` with an account that owns the tap.
- **Could not download `<url>`** GitHub had not made the tag's tarball yet, or
  the network dropped. Resume.
- **Could not clone `<repo>`** or **git pull in the tap clone failed** Check
  `gh` sign-in and that the tap is reachable; the scratch clone is reset on the
  next run.
- **brew update-python-resources failed** Run it on the formula by hand. Without
  `brew` the release goes on and warns that resource blocks were not updated.

**Custom**

- **`<command>` was not found for `<name>`** Install it, or fix `run`.
- **`<name>` exited with N** The last lines of its output follow. The step is
  irreversible, so check what it did before you resume; add a `verify` command
  so a resume skips it once it has worked.

**After the release**

- **Verify failed for …** Each failing target is named. `is not on PyPI / npm
  after 5 minutes` can be the registry lagging: check by hand (see each target
  above) and resume to verify again. `the tap's formula does not point at vX`
  means the push did not land. `verify command failed` is your custom check.
- **Warning: after command failed / could not send the Telegram message.** The
  release is done; these only warn.

## What is never stored

whyline stores no passwords, tokens or API keys for releases. `release.toml`
holds choices only (targets, mode, branch, checks, paths). Sign-in is left to
`gh` and each registry's own tool, which keep their credentials where they
always did. The saved release state holds the version, step ids, which steps
are done, the mode and the failure reason, and nothing else. Messages that
could contain a Telegram token are masked before they are shown.
