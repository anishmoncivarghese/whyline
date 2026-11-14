<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-11-15-release-hardening-design.md | created: 2026-11-15T15:30:00+05:30 -->
# Release supply chain: pinned actions, least permission, proof of origin, more checks and project files

Runs after `plans/release-safety.plan.md`, and before `plans/agent-profile.plan.md`. Spec: `docs/superpowers/specs/2026-11-15-release-hardening-design.md`, Part 4. Read it before every task. Where this plan and the spec differ, this plan wins. In particular:
- **The SBOM is built by whyline from the lockfile** it already reads, in CycloneDX JSON, with no external tool.
- **Attestations are turned on in the workflow template** whyline writes. An existing hand-edited workflow gets the change as a shown diff the user accepts, never silently.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Why: the workflows use actions by tag (`actions/checkout@v4`), which can be moved. Test jobs run with the default token permissions. Nothing keeps the actions current. The published files carry no proof of where they were built. Only tests gate a release, and the repository has no `SECURITY.md` or `CHANGELOG.md`.

What the user gets:
- Release → Set up shows what is unpinned or over-permissioned in the workflows, with a diff and one button to fix each.
- A Dependabot file offered for the actions and the package ecosystem.
- Published files with attestations, and an SBOM on the GitHub release.
- Lint and type checks suggested from what the repository already has.
- `SECURITY.md` offered, and `CHANGELOG.md` built from the release notes.

Rules every task keeps:
- **Console first.** Every action is in Release → Set up through the same functions as `whyline release setup …`.
- **Nothing in the user's repository is rewritten without a shown diff and a yes.** This holds in every mode, and for whyline's own repository too.
- **Workflow files are edited as text, line by line.** Comments, order and formatting outside the changed lines are kept byte for byte. No YAML library rewrites a file.
- **Network calls go through the release's `run`** (`gh api`) with its timeouts and retries. Offline, a status says `couldn't check` and nothing is changed.
- **No new dependency.**
- **Tests:** never call a real `gh` or the network. Use fixture workflow files and fakes. Keep Python 3.11 compatibility.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- Pinning changes only the `uses:` lines it names, and every other byte of the file is unchanged. SUP-1, `test_pin_touches_only_uses_lines`.
- A tag that can't be resolved is left as it is and reported, never guessed. SUP-1, `test_unresolved_tag_is_left`.
- No file is written before the user accepted its diff. SUP-2, `test_nothing_written_before_yes`.
- A suggested check that fails today is added as a warning, not a blocker. SUP-4, `test_failing_suggestion_is_warn`.
- The SBOM lists every dependency in the lockfile once, with its version. SUP-3, `test_sbom_matches_lockfile`.

- [ ] SUP-1: Find and pin unpinned actions
  Create `src/whyline/release/pins.py` and `tests/release/test_pins.py` only.
  1. `pins.scan(root) -> list[Use]` over `.github/workflows/*.yml` and `*.yaml`: each `uses: owner/repo[/path]@ref` line with its file, line number, action, ref and whether the ref is a full 40-character commit sha. Local actions (`./…`) and Docker references (`docker://…`) are listed as not applicable.
  2. `pins.resolve(action, ref, *, run) -> str | None`: the commit sha the tag or branch points at, from `gh api repos/<owner>/<repo>/commits/<ref> --jq .sha`. None on any failure.
  3. `pins.plan(root, *, run) -> list[Change]`: for each unpinned use, the new line `uses: owner/repo@<sha> # <ref>`, keeping the line's indentation, its `- ` prefix and any trailing comment's text after the ref.
  4. `pins.diff(root, changes) -> str` (a unified diff) and `pins.apply(root, changes)`, which rewrites only those lines and checks afterwards that every other line is unchanged, restoring the file if not.
  Tests: `test_pin_touches_only_uses_lines` (a fixture with comments, anchors, odd spacing and CRLF line ends), `test_unresolved_tag_is_left`, an already pinned line left alone, local and Docker uses skipped, a `uses:` inside a string or comment not touched, and the restore on a mismatch.

- [ ] SUP-2: Permissions, Dependabot, and Set up
  Edit `src/whyline/release/pins.py`, `src/whyline/release/workflows.py`, `src/whyline/release/cli.py`, `src/whyline/console/release_screens.py` and their tests only.
  1. `pins.permissions(root) -> list[Finding]`: workflows with no top-level `permissions:` key. `pins.add_permissions(root, file) -> Change` inserts `permissions:\n  contents: read\n` before the top-level `jobs:` line. A workflow whose jobs all set their own `permissions` is reported as fine.
  2. `workflows.dependabot_text(root) -> str`: a `.github/dependabot.yml` with `github-actions` weekly, plus `pip` or `uv` when there is a `pyproject.toml`, and `npm` when there is a `package.json`. When the file exists, only the missing ecosystems are offered, as an appended block.
  3. Release → Set up gets a **Workflows** section with one line per finding and a button: `3 actions are not pinned` → **Pin…**, `ci.yml has no permissions set` → **Set read-only…**, `No Dependabot file` → **Add…**. Each opens the diff with **Apply** and **Cancel**. After Apply the line turns to done. The changes are left uncommitted for the user to review, with the line `Changed .github/…; commit it with your next change.`
  4. CLI: `whyline release setup workflows` prints the findings. `--pin`, `--permissions` and `--dependabot` each print the diff and ask `[y/N]` (`--yes` to skip the question).
  5. The Ready check lists unpinned actions as an item that warns and never blocks.
  Tests: `test_nothing_written_before_yes` (console and CLI, for all three), the permissions insert position, a workflow with per-job permissions reported fine, an existing Dependabot file extended not replaced, and the Ready item.

- [ ] SUP-3: Attestations and an SBOM
  Create `src/whyline/release/sbom.py` and `tests/release/test_sbom.py`. Edit `src/whyline/release/templates/` (the PyPI workflow template), `src/whyline/release/targets/pypi.py`, `src/whyline/release/workflows.py` and their tests.
  1. `sbom.build(root, name, version) -> dict`: CycloneDX 1.5 JSON with the project as the top component and one component per dependency from `security.lockfiles.read_all` (name, version, purl `pkg:pypi/<name>@<version>` or `pkg:npm/…`), each once. `sbom.write(root, name, version, out_dir) -> Path` writes `<name>-<version>.cdx.json`.
  2. The PyPI workflow template:
     - publishes with attestations on (`uv publish --trusted-publishing always` with the attestations flag the installed uv supports; when it has none, the `pypa/gh-action-pypi-publish` step with `attestations: true`, pinned by sha)
     - adds `attestations: write` to the publish job's permissions and an `actions/attest-build-provenance` step (pinned by sha) for `dist/*`
     - runs `whyline release sbom --out dist-sbom/` and attaches the file to the GitHub release
  3. For a repository whose workflow differs from the old template, Set up shows `Your publish workflow doesn't attest its files` with **Show the change**, a diff of the three additions against the user's file, applied only on yes. When the additions can't be placed safely (the publish job isn't found), it shows the lines to add by hand.
  4. The PyPI target's `verify` adds a check that the version's files have attestations (`https://pypi.org/integrity/<name>/<version>/<file>/provenance` answers 200), reported as a warning when missing, never as a failed release.
  5. CLI: `whyline release sbom [--out DIR]`.
  Tests: `test_sbom_matches_lockfile`, the purl forms, a project with no lockfile giving the top component only, the template's three additions, the diff against a customised workflow, the unplaceable case, and verify's warning.

- [ ] SUP-4: Suggest lint and type checks
  Edit `src/whyline/release/config.py`, `src/whyline/release/ready.py`, `src/whyline/release/cli.py`, `src/whyline/console/release_screens.py` and their tests only.
  1. `ready.suggest_checks(root) -> list[Suggestion]` (`name`, `command`, `why`), from files present:
     - `ruff` when `pyproject.toml` has `[tool.ruff]` or a `ruff.toml` exists: `uv run ruff check .`
     - `mypy` when `[tool.mypy]` or `mypy.ini` exists: `uv run mypy .`
     - `pyright` when `pyrightconfig.json` exists: `uv run pyright`
     - `eslint` when an eslint config exists: `npx eslint .`
     - `tsc` when `tsconfig.json` exists: `npx tsc --noEmit`
     A suggestion already in `cfg.checks` is left out. Nothing is suggested for a tool with no config: whyline does not introduce a linter.
  2. `ReleaseConfig.warn_checks: tuple[str, ...] = ()`: checks that run and report but never stop a release. The checks step runs them after `checks` and lists failures as warnings in the release log and the record.
  3. Set up → Checks lists the suggestions, each with **Try it** (runs it once and shows the last 20 lines) and **Add**. A suggestion whose try failed is added to `warn_checks` with the line `It fails today, so it's added as a warning. Move it to Checks once it passes.` One that passed is added to `checks`.
  4. CLI: `whyline release settings checks suggest`, and `whyline release settings checks add "<command>" [--warn]`.
  Tests: `test_failing_suggestion_is_warn`, each detection, a tool with no config not suggested, a warn check's failure not stopping the release, and round trip of `warn_checks`.

- [ ] SUP-5: SECURITY.md and CHANGELOG.md
  Create `src/whyline/release/projectfiles.py` and `tests/release/test_projectfiles.py`. Edit `src/whyline/release/plan.py` (the commit step), `src/whyline/release/config.py`, `src/whyline/release/cli.py`, `src/whyline/console/release_screens.py` and their tests.
  1. `projectfiles.security_text(contact: str, *, private_reporting: bool) -> str`: a short `SECURITY.md` with supported versions (`the latest release`), how to report (GitHub's private vulnerability reporting when on, else the contact), and what to expect. The contact is the user's choice, typed in the dialog. It is never taken from git config without being shown.
  2. `projectfiles.changelog(root, cfg) -> str`: `# Changelog`, then each version's notes file under `## v<version> — <date of its tag>`, newest first, with each file's own `# v<version>` title removed. Versions with no notes file are listed with `No notes.`
  3. `ReleaseConfig.changelog: bool = False`. When on, the release's commit step rewrites `CHANGELOG.md` with the new version included, in the same commit as the version bump. A `CHANGELOG.md` that whyline didn't write (no marker comment on its first line) is never overwritten: Set up says so and offers `CHANGELOG.whyline.md` instead.
  4. Set up shows `No SECURITY.md` → **Add…** (contact box, the text, **Create**), and `No changelog` → **Build from release notes…** (the text, **Create and keep it updated**). CLI: `whyline release setup security-md --contact "<text>"` and `whyline release setup changelog`, each printing the text and asking.
  Tests: the changelog order and the removed titles, a version with no notes, the marker and a foreign file left alone, the commit step including the file when on and not when off, and nothing written before yes.

- [ ] SUP-6: Docs
  Edit `docs/release.md`, `docs/security.md` (or the page that documents the security check) and `README.md` only.
  Cover: why actions are pinned and how to update a pin, the permissions change, Dependabot, attestations and how a user can check them, the SBOM, suggested checks and warning checks, `SECURITY.md` and the generated changelog.
  Verify with `uv run pytest -q`.
