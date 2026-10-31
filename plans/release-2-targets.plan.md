<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-10-31-release-design.md | created: 2026-10-31T22:00:00+05:30 -->
# Release 2: PyPI, npm, Docker, Homebrew and custom targets

Spec: `docs/superpowers/specs/2026-10-31-release-design.md`. Read it before every task. Where a name in the repository has moved, follow the repository and keep the behaviour.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Starts after `plans/release-1-core.plan.md` is complete. It builds on REL-1 (config), REL-3 (`register_ready`), REL-4 (`Step`, engine), REL-5 (the CI polling helpers), REL-6 (`ask_agent`), REL-7 (`plan.build`) and REL-11 (the Set up tab).

What the user gets from this plan:
- Tick PyPI, npm, Docker, Homebrew or any custom command in **Set up**, finish that target's guided setup once, and every release then publishes there too. An unticked target is never touched.
- Each target's own Ready items, a wait step that follows its GitHub workflow, and a check that the version actually arrived.

Global constraints:
- Every constraint in `plans/release-1-core.plan.md` applies.
- Publish tokens for PyPI and npm are never stored anywhere: these use trusted publishing from GitHub Actions. Docker Hub's token is stored only as a GitHub repository secret, set with `gh secret set` with the value on stdin. It is never written to disk, a log, argv or the transcript.
- Workflow templates live as text in `src/whyline/release/templates/` and are written only when the user presses **Add workflow**. Each file Set up writes (workflow, Dockerfile) is recorded with `config.add_pending`, so the next release commit includes it (REL-5), never a separate commit mid-relay. Pin each action to its current major version. Before writing a template, the implementer checks the action's and registry's current docs, and records the source URL in a comment at the top of the template.
- Verify every task with `uv run pytest -q tests/release tests/console` and then `uv run pytest -q`. Change nothing outside the files a task names.

- [ ] REL-13: Target registry, workflow helpers and the plan hook
  Create `src/whyline/release/targets/__init__.py`, `src/whyline/release/workflows.py` and `tests/release/test_targets.py`; edit `src/whyline/release/plan.py` and `src/whyline/release/github.py` and their tests only.
  - A `Target` protocol: `key`, `title`, `ready_items(root, cfg, version, *, run, fetch) -> list[ReadyItem]`, `steps(root, cfg, version, *, run, fetch) -> list[Step]`, `verify(root, cfg, version, *, run, fetch) -> tuple[bool, str]`, and `setup_status(root, cfg, *, run) -> list[str]`. Plus `REGISTRY: dict[str, Target]` and `enabled(cfg) -> list[Target]` in this order: pypi, npm, docker, homebrew, custom.
  - `workflows.find_publishing(root, needle) -> Path | None`: the first `.github/workflows/*.yml` that contains `needle` and runs on tag pushes (`tags:` under `push:`). `workflows.write_template(root, name, text) -> Path` refuses to overwrite.
  - `workflows.wait_for_tag_run(root, tag, workflow_file, *, run, sleep, now, cancel_event, on_detail)` reuses REL-5's CI polling: `gh run list --workflow <file> --branch <tag> --json status,conclusion,url,databaseId`. It reports the run's status, fails with the failed job name (`gh run view <id> --json jobs`) and URL, and gives up after 45 minutes with a resumable failure.
  - `plan.build` inserts each enabled target's steps after `github_release`, then one `verify` step that calls every enabled target's `verify` and fails listing those that failed, then `after`. `ready.check` calls `ready_items` of enabled targets.
  - A Verify step has `done_check` false, so it always runs.
  Tests: order of enabled targets, finding a publishing workflow (and ignoring one that runs only on branches), no overwrite, the tag-run wait for pass/fail/timeout/cancel, `plan.build` with two fake targets, verify listing failures.

- [ ] REL-14: PyPI target
  Create `src/whyline/release/targets/pypi.py`, `src/whyline/release/templates/release-pypi.yml` and `tests/release/test_target_pypi.py`; edit `src/whyline/console/release_screens.py` and its test only.
  - The template runs on push of tags `v*`, uses environment `pypi` and `permissions: id-token: write, contents: read`, and does checkout, `astral-sh/setup-uv`, `uv build`, then `pypa/gh-action-pypi-publish`.
  - The workflow file is the existing publishing one (`find_publishing(root, "pypa/gh-action-pypi-publish")`) or `release-pypi.yml`.
  - Ready items:
    - the workflow exists
    - the project name is in `pyproject.toml`
    - `https://pypi.org/pypi/<name>/<version>/json` is 404, meaning the version isn't published yet. A network error gives "could not reach PyPI".
  - Steps: `pypi` waits for the tag run of the workflow. Its `done_check` is that the version JSON returns 200.
  - Verify: the version JSON returns 200, retried for up to 5 minutes (injected sleep), because PyPI's index lags.
  - `setup_status` lines:
    - whether the workflow exists, with its path
    - whether the project exists on PyPI
    - the values for pypi.org's trusted publisher form: owner, repository, workflow file name, environment `pypi`, and for a new project "use Add a pending publisher"
  - Console: the PyPI **Set up…** panel shows those lines, with **Add workflow** (shown when none exists), **Open pypi.org** (opens `https://pypi.org/manage/account/publishing/` with `open`) and **Ask agent**.
  Tests: ready on 404/200/network error, reuse of an existing publishing workflow, template written once, verify retry, the panel's buttons and lines.

- [ ] REL-15: npm target
  Create `src/whyline/release/targets/npm.py`, `src/whyline/release/templates/release-npm.yml` and `tests/release/test_target_npm.py`; edit `src/whyline/console/release_screens.py` and its test only.
  - The template runs on tag `v*` with `permissions: id-token: write, contents: read`. It uses `actions/setup-node` with `registry-url: https://registry.npmjs.org`, a current Node LTS, an npm new enough for trusted publishing (upgrade npm in the job when needed), `npm ci`, then `npm publish --provenance --access public`. Before writing it, check npm's trusted-publishing docs and match them.
  - The workflow file is found by `find_publishing(root, "npm publish")`, or `release-npm.yml`.
  - Ready items: the workflow exists, `package.json` has a name and isn't private, and the version isn't on npm (`https://registry.npmjs.org/<name>/<version>` returns 404; scoped names URL-encoded).
  - Steps: `npm` waits for the tag run. Its `done_check` is that the registry URL returns 200.
  - Verify: the same URL returns 200, retried for up to 5 minutes.
  - `setup_status` lines:
    - whether the workflow exists
    - whether the package exists on npm
    - the values for npmjs.com's trusted publisher form (owner, repository, workflow file name)
    - for a package that isn't published yet, the first-publish rule from npm's docs as found during this task. If npm needs a first manual publish: "Run `npm login` and `npm publish` once in a terminal; later releases publish automatically."
  - Console: the npm panel, with **Add workflow**, **Open npmjs.com** and **Ask agent**.
  Tests: as for PyPI, plus a scoped package name and a private package refused in ready.

- [ ] REL-16: Docker target
  Create `src/whyline/release/targets/docker.py`, `src/whyline/release/templates/release-docker.yml` and `tests/release/test_target_docker.py`; edit `src/whyline/console/release_screens.py` and its test only.
  - The template runs on tag `v*` with `permissions: contents: read, packages: write`. It uses `docker/setup-buildx-action`, `docker/login-action` (GHCR through `GITHUB_TOKEN`; Docker Hub through `secrets.DOCKERHUB_USERNAME`/`DOCKERHUB_TOKEN`, written only when `dockerhub` is in `registries`), `docker/metadata-action` (tags `v<version>`, `<version>` and `latest`) and `docker/build-push-action` with `push: true`. The image name comes from config (default `<owner>/<repo>`, lowercased).
  - Ready items:
    - a `Dockerfile` exists
    - the workflow exists
    - for Docker Hub, both secrets are present (`gh secret list --json name`)
  - Steps: `docker` waits for the tag run.
  - Verify: `docker manifest inspect <ref>:<version>` when `docker` is installed. Otherwise the tag run's success counts, with a note.
  - `store_dockerhub_secrets(root, username, token, *, run)` runs `gh secret set DOCKERHUB_USERNAME` and `gh secret set DOCKERHUB_TOKEN` with the values on stdin only.
  - `draft_dockerfile(root, *, ask_agent) -> str` asks the main agent for a Dockerfile for this project (language, entry point and lockfile from the tree listing and the manifest files), saying it must be small and non-root.
  - Console: the Docker panel shows status, registry checkboxes (GHCR/Docker Hub), image name and **Add workflow**.
    - **Draft Dockerfile** puts the draft in a read-only view with **Save as Dockerfile** and **Discard**.
    - The Docker Hub username field and a masked token field (`Input(password=True)`) go with **Store as GitHub secrets**, which clears the field after storing and never logs it.
    - **Ask agent**.
  Tests:
  - the template with and without Docker Hub
  - the ready items
  - the secrets go on stdin and never in argv (assert the sentinel isn't in any recorded argv or transcript event)
  - the draft goes through `ask_agent` and is never written without Save
  - verify with and without docker

- [ ] REL-17: Homebrew target
  Create `src/whyline/release/targets/homebrew.py` and `tests/release/test_target_homebrew.py`; edit `src/whyline/console/release_screens.py` and its test only.
  - The tap defaults to `<owner>/homebrew-tap` and the formula to the project name. `create_tap(owner, name, *, run)` runs `gh repo create <owner>/homebrew-<name> --public` (taps must be public for `brew tap` without credentials, so say so in the panel).
  - The tap is worked in a scratch clone: `gh repo clone <tap> <tmp>` under `.git/whyline-release/tap`, refreshed with `git pull` on reuse.
  - Ready items: the tap repository exists (`gh repo view`), `Formula/<formula>.rb` exists in it, and you can push (`gh api repos/<tap> --jq .permissions.push`).
  - Step `homebrew` (irreversible):
    1. Download `https://github.com/<owner>/<repo>/archive/refs/tags/v<version>.tar.gz` through `fetch` and compute its sha256.
    2. Replace the formula's `url` and `sha256` lines (only those lines).
    3. When the formula contains `resource "` blocks and `brew` is installed, run `brew update-python-resources <path>`. When `brew` is missing, keep the old resources and add a warning to the step detail.
    4. Commit `<formula> <version>` and push.
    Its `done_check` is that the tap's formula already has the new url.
  - Verify: the tap's formula on the remote (`gh api repos/<tap>/contents/Formula/<formula>.rb`) contains the version's URL.
  - `draft_formula(root, *, ask_agent)`: the agent writes a first formula (a `Language::Python::Virtualenv` formula for a Python project, with the test block running `<cli> --version`). You review it in the panel, and **Push to tap** commits it.
  - Console: the Homebrew panel shows tap and formula fields, **Create tap**, **Draft formula**, **Push to tap**, the `brew tap <owner>/<name>` / `brew install <formula>` lines users will run, with **Copy**, and **Ask agent**.
  Tests: the sha256 from a fixture tarball, only the url and sha256 lines change, resources updated when brew exists and a warning when it doesn't, `done_check`, verify, create_tap argv, the draft is reviewed before push.

- [ ] REL-18: Custom targets
  Create `src/whyline/release/targets/custom.py` and `tests/release/test_target_custom.py`; edit `src/whyline/console/release_screens.py` and its test only.
  - Ready item per entry: the first word of `run` (after `shlex.split`) is on PATH, or is a path that exists.
  - One irreversible step per entry, `custom:<name>`, running `run` with `shell=True` in root, with `WHYLINE_RELEASE_VERSION=<version>` and `WHYLINE_RELEASE_TAG=v<version>` in the environment. Lines stream to detail, and a failure shows the last 20 lines. Its `done_check` runs `verify` when set (exit 0 = done), otherwise false.
  - Verify: each entry's `verify` exits 0. Entries without one count as verified, with "no verify command" in the detail.
  - Console: the Custom panel lists entries with **Add**, **Edit** and **Remove** (name, command, optional verify command), and saves through `config.save`.
  Tests: ready on a missing command, the env vars reach the command, `verify` as `done_check`, the editor round-trips through `config.save`, a duplicate name is refused.

- [ ] REL-19: End-to-end check and docs
  Create `tests/release/test_end_to_end.py`; edit `docs/release.md` and `README.md` only.
  - An end-to-end test: a temp repository with a bare origin, every target enabled through fakes for `gh`, `fetch`, `brew` and `docker`, and auto mode. It runs `plan.build` and the engine to completion. Then:
    - a second run is refused as already released (tag exists)
    - a run failed at the PyPI wait resumes and finishes without repeating the tag or the GitHub release (assert the fake `gh` saw `release create` once)
    - an unticked target's steps never appear and none of its commands run
  - `docs/release.md`: a section per target (what it publishes, the one-time setup, where tokens live or why there are none, how to verify by hand), plus a troubleshooting list built from each step's failure messages.
