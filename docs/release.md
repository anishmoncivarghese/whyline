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

Only GitHub runs in this version. The other targets can be ticked and saved,
but their **Set up…** buttons say they come with release part 2.

## Setting up each target

- **GitHub**: needs `git`, the `gh` tool, an `origin` remote on GitHub and a
  signed-in `gh`. **Set up…** next to GitHub shows what is missing and offers
  Sign in, Create repository (private or public) or Ask agent. Without `gh`
  it shows `brew install gh` with a Copy button.
- **PyPI, npm, Docker, Homebrew, Custom**: tick the box and save. Their
  options (`docker_options`, `homebrew_options`, custom `run`/`verify`) live in
  `.whyline/release.toml`.
- **Branch**, **Checks** (one command per line, run before the push), **CI jobs
  to ignore**, **Notes path** (default `docs/releases/v{version}.md`) and
  **After-commands** are on the same Set up tab. Save asks before you close
  with unsaved changes.

With no file yet, Set up shows what detection suggests; it is only kept when
you press **Save**.

## Running a release

Open **Release**, pick the next version (patch, minor, major or custom), press
**Check**, then **Start**. Check lists each item with ✓ or ✗ and what to do
about a ✗; Start stays off until every item is ✓.

### Modes

- **ask** (default): asks before each irreversible step (the push, the tag, the
  GitHub release) and shows the release notes for you to use, edit or stop.
- **step**: asks before every step.
- **auto**: asks nothing. Only use it after Check is all ✓.

### Resume

A failed or stopped release keeps its place in `.git/whyline-release/`.
When a step fails, the popup offers **Resume release** (continue after you fix
the cause) and, when a pull request is the way forward, **Open PR**. Resume
skips every step already done. Choosing **Edit** on the notes stops the
release; Resume continues with the edited file.

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

## What is never stored

whyline stores no passwords, tokens or API keys for releases. `release.toml`
holds choices only (targets, mode, branch, checks, paths). Sign-in is left to
`gh` and each registry's own tool, which keep their credentials where they
always did. The saved release state holds the version, step ids, which steps
are done, the mode and the failure reason, and nothing else. Messages that
could contain a Telegram token are masked before they are shown.
