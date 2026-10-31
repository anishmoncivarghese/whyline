# Release: one button that ships a repository to the places the user picked

Date: 2026-10-31. Status: approved by the user in chat. Plans: `plans/release-1-core.plan.md` (REL-1..12) and `plans/release-2-targets.plan.md` (REL-13..19).

## Problem

When a plan finishes, the user pushes to GitHub, tags, creates a GitHub release and publishes to PyPI by hand, or asks an agent to. Whyline has no way to do this today. Agents are deliberately blocked from `git push`. A plan's release task (profile `release`, role `human`) just pauses with "Release done…" until the user types `done`. Setting up a new repository (creating it on GitHub, signing in, trusted publishing) is spread over several websites.

## What the user gets

- A **Release** button in Relay mode only. Its screen has two tabs: **Set up** and **Release**.
- **Set up** lists the targets, each with a checkbox, a status (✓ ready / ✗ with the reason) and a **Set up…** button that guides the one-time setup. An unticked target is never published to.
  - **GitHub**: push the branch, tag, GitHub release. Signs in through `gh` in the browser, and can create the GitHub repository and link it.
  - **PyPI**: trusted publishing through a GitHub workflow that runs on the tag.
  - **npm**: trusted publishing through a GitHub workflow that runs on the tag.
  - **Docker**: an image built and pushed by a GitHub workflow that runs on the tag. GitHub Container Registry needs no secret. Docker Hub is optional.
  - **Homebrew**: updates a formula in the user's tap repository.
  - **Custom**: any number of commands the user names (for example `make publish`), run after the tag.
  - GitHub is required by every other target, because they all start from the pushed tag. Ticking any other target ticks GitHub.
- **Release** runs a fixed list of steps. Before it starts, it shows a **Ready check** and the steps it will run.
- **Modes** (a setting, per repository):
  - **Ask** (default): you review the version and release notes, then confirm once before the first push.
  - **Step**: confirm before every step that pushes or publishes.
  - **Auto**: no confirmation once the Ready check passes. It still stops at the first failure.
- A separate setting, off by default: **Release when a plan completes**. It follows the mode, so in Ask mode it still asks.
- Progress in the console's busy line, the same way as the relay's:
  `release: v0.3.60 · step 6 of 11 (45%) · waiting for CI (5 of 7 checks) · 4m 10s`
  The % is completed steps out of the planned steps. The list is fixed before the run starts, so the % is accurate.
- **Resume** after a failure continues from the failed step. Every step first checks whether it's already done (the tag exists, the release exists, the version is on PyPI, and so on), so nothing is published twice.
- **When the relay pauses on a plan's release task**, the "Release done…" button offers **Run Release**. A successful release sends `done <task>` to the relay, exactly as typing it does today.
- **CLI**, for scripts: `whyline release check | run | status | resume | setup <target>`. It calls the same functions as the console (console first).

## Decisions

1. **Whyline runs the irreversible steps itself, as fixed commands, not an agent.** Pushes, tags and publishes cannot be undone. Fixed commands are predictable, can be resumed, and are what make the % possible. Rejected: letting the main or backup agent push, because agents are denied `git push` on purpose and their actions can't be checked step by step.
2. **Agents do the judgement work:**
   - draft the release notes from the commits since the last tag
   - draft a missing Dockerfile or Homebrew formula during setup
   - explain a failed step
   They use the relay's main agent and fall back to the backup chain. They write files in the working tree, and the user reviews them (Ask and Step modes) before anything is committed.
3. **Publishing happens in GitHub workflows triggered by the tag** (PyPI, npm, Docker). This avoids storing publish tokens on the Mac, and it's how whyline itself already releases. Setup reuses an existing workflow that already publishes to that target instead of adding a second one. Homebrew and Custom run locally, because they need no registry token beyond `gh`'s sign-in.
4. **Configuration lives in `.whyline/release.toml`**, committed with the repository and holding no secrets. Run state lives in `.git/whyline-release/state.json`, inside `.git` so a relay's `git add -A` can never sweep it into a commit.
5. **Release and relay never run at the same time.** Release refuses to start while a relay runs, unless the relay is paused on a release task. Run and Resume in Relay mode are disabled while a release runs.
6. **Order:** everything that can be undone comes first; publishing comes last.
7. **The version is bumped in the files the project already uses:**
   - `pyproject.toml` `[project] version`, plus `__version__` if the package has one, plus `uv.lock` through `uv lock`
   - `package.json` `version`, plus the lockfile through `npm install --package-lock-only`
   - or files the user lists in config
   The choices are patch / minor / major / the version already in the files / custom.
8. **No new runtime dependency.** TOML is read with `tomllib` and written by a small writer for this file's fixed shape. All GitHub calls go through `gh` (`gh auth status`, `gh repo create`, `gh run list`, `gh release create`, `gh secret set`, `gh api`).

## Configuration (`.whyline/release.toml`)

```toml
[release]
mode = "ask"                 # ask | step | auto
branch = "main"              # where the release commit lands
start_after_plan = false
checks = ["uv run pytest -q"]          # run locally before any push
ci_ignore = ["test (windows-latest, 3.13)", "test (windows-latest, 3.11)"]  # CI jobs that do not gate
notes = "docs/releases/v{version}.md"  # "" = notes only in the GitHub release
version_files = []           # extra files holding the version, beyond the detected ones
after = ["uv tool upgrade whyline"]    # local commands after a successful release, failures only warn

[targets]
github = true
pypi = true
npm = false
docker = false
homebrew = false

[targets.docker]
registries = ["ghcr"]        # ghcr | dockerhub
image = ""                   # default: <owner>/<repo> lowercased

[targets.homebrew]
tap = ""                     # owner/homebrew-<name>
formula = ""                 # default: the project name

[[targets.custom]]
name = "docs"
run = "make publish-docs"
verify = ""                  # optional command whose exit 0 means published
```

Detection fills the defaults the first time: `pyproject.toml` → pypi, `package.json` without `"private": true` → npm, `Dockerfile` → docker. Detected targets are suggestions, shown ticked, and saved only on **Save**.

## Steps

The planned list is built from the config before the run starts. Each step has `id`, `title`, `irreversible: bool`, `done_check()`, `run()`.

1. `ready`: the Ready check (below). Never changes anything.
2. `version`: write the chosen version into the version files and update lockfiles.
3. `notes`: an agent drafts the notes, and in Ask and Step modes you edit or approve them.
4. `commit`: `chore: release v<version>`, adding only the version files, lockfiles, notes file and pending setup files.
5. `checks`: run each `checks` command; output goes to the transcript.
6. `push` (irreversible): fast-forward `origin/<branch>` to HEAD with `git push origin HEAD:<branch>`. If `origin/<branch>` isn't an ancestor of HEAD, stop and explain. If the push is rejected as protected, offer **Open PR** (`gh pr create`) and wait for it to merge.
7. `ci`: wait for the workflow runs on that commit, minus `ci_ignore`. Shows "n of m checks".
8. `tag` (irreversible): annotated `v<version>`, pushed.
9. `github_release` (irreversible): `gh release create v<version> --notes-file …`.
10. One wait step per workflow target (`pypi`, `npm`, `docker`): find the run the tag started, wait for it, and fail with its failed job's name and a link.
11. `homebrew` (irreversible): update the formula's `url` and `sha256` from the tag's source tarball, plus Python resources when the formula uses them, then commit and push to the tap.
12. One step per `custom` entry (irreversible).
13. `verify`:
    - PyPI JSON API lists the version
    - `npm view <name>@<version> version`
    - the registry manifest exists
    - the tap formula shows the version
    - custom `verify`
14. `after`: run the `after` commands, then send a Telegram message if the assistant bot is set up. Failures here only warn.

Step mode asks before every irreversible step. Ask mode asks once, before step 6. Auto asks nothing.

## Ready check

Each item is ✓ or ✗ with a one-line fix:
- `git` and `gh` are installed
- `gh` is signed in
- `origin` points at GitHub
- the working tree is clean
- no relay is running (one paused on a release task is fine)
- HEAD is on or ahead of `origin/<branch>`
- the tag `v<version>` doesn't exist locally or on the remote
- each ticked target's own check:
  - PyPI: the workflow exists and the version isn't on PyPI
  - npm: the workflow exists and the version isn't on npm
  - Docker: a Dockerfile and the workflow exist
  - Homebrew: the tap exists and you can push to it
  - Custom: the command's first word is on PATH

The check runs in a thread worker and takes at most 30 s. A network failure marks only that item ✗ ("could not reach PyPI").

## Set up, per target

- **GitHub:**
  - If `gh` is missing, show `brew install gh` with a Copy button.
  - **Sign in** runs `gh auth login --web --git-protocol https --hostname github.com`, with a newline on stdin. It shows the one-time code and opens the browser, and the status refreshes when it exits.
  - With no `origin`, **Create repository** asks for the name (default: the folder name), private or public (default private) and an optional description, then runs `gh repo create <name> --private|--public --source . --remote origin`. Nothing is pushed until a release.
  - Whyline never asks for or stores a GitHub token.
- **PyPI:**
  - Reuse a workflow under `.github/workflows/` that already runs `pypa/gh-action-pypi-publish` on a tag. Otherwise **Add workflow** writes `.github/workflows/release-pypi.yml` from a template (build with `uv build`, publish with trusted publishing, environment `pypi`).
  - It then shows the exact values for the trusted publisher form on pypi.org (owner, repository, workflow file name, environment), with a pending publisher for a project that isn't on PyPI yet, plus an **Open pypi.org** button.
  - Every file Set up writes (workflow, Dockerfile) is recorded as pending in `.git/whyline-release/pending.json`. The Ready check's clean-tree item ignores pending files, and the release commit includes them, never a separate commit mid-relay.
- **npm:** the same flow with `release-npm.yml`: `npm publish --provenance --access public`, `id-token: write`, and trusted publishing configured on npmjs.com. For a package that isn't on npm yet, the guide says whether npm allows a trusted publisher before the first publish. The implementer checks npm's current docs and writes that into the guide text. If npm doesn't allow it, the guide tells the user to run `npm login` and `npm publish` once by hand.
- **Docker:**
  - With no `Dockerfile`, **Draft with agent** asks the main agent to write one for this project, and you review it.
  - **Add workflow** writes `release-docker.yml` (`docker/build-push-action`, tags `v<version>` and `latest`, GHCR through `GITHUB_TOKEN`).
  - For Docker Hub, the user types a username and an access token into a masked field. Whyline stores them as repository secrets with `gh secret set DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN`, sending the value on stdin, and never writes them to disk or the transcript.
- **Homebrew:**
  - Tap name defaults to `<owner>/homebrew-tap`. **Create tap** makes the repository with `gh repo create`.
  - With no formula, **Draft with agent** writes one from the project, using a Python virtualenv formula for Python projects. You review it, and it's pushed to the tap. Later releases only update `url`, `sha256` and resources.
- **Custom:** add, edit or remove entries with a name, a command and an optional verify command.

Every **Set up…** screen also has **Ask agent**. It sends the target's status and the error, if any, to the main agent through the chat path (`adapters.run_chat_turn`) and shows the answer. The agent explains; it does not run setup commands.

## Out of scope

- crates.io, the VS Code Marketplace, the App Store, Snap and Chocolatey. A Custom entry covers them for now. Go modules need nothing beyond the GitHub tag.
- Signing and notarising macOS binaries.
- Release branches and backports, and more than one package per repository.
- Changing whyline-relay. The release task keeps role `human`, and the console handles the pause.

## Testing

Every subprocess (`git`, `gh`, `uv`, `npm`, `brew`, network) goes through an injected `run`. Every network check goes through an injected `fetch`. Tests use temporary git repositories with a bare repository as `origin`, and never reach GitHub or a registry.
