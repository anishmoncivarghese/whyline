<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-10-31-release-design.md | created: 2026-10-31T23:00:00+05:30 -->
# Release 3: security checks before anything is published

Spec: `docs/superpowers/specs/2026-10-31-release-design.md` (Release). This plan adds security checks to it. Where this plan and the spec differ, this plan wins. Where a name in the repository has moved, follow the repository and keep the behaviour.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Starts after `plans/release-1-core.plan.md` is complete. It uses REL-1 (`release.toml`), REL-3 (`register_ready`), REL-8 (GitHub setup) and REL-11 (the Set up tab). It can run before or after `plans/release-2-targets.plan.md`. SEC-6's npm and Docker checks only matter once those targets exist, and they run whenever the project has a `package.json` or `Dockerfile`.

What the user gets:
- **Nothing to install.** Whyline has its own secret scanner, built on a bundled copy of gitleaks' MIT-licensed default rules. It checks dependencies through OSV.dev's free public API and inspects package contents itself. If `gitleaks`, `betterleaks` or `osv-scanner` is on PATH, whyline also runs them for wider coverage. Setup suggests `brew install gitleaks osv-scanner` but never requires it.
- **A release gate.** The Ready check gains a Security item. Before anything is pushed it scans:
  - the commits about to be pushed, for keys, tokens, private keys and `.env`-style files
  - the dependencies, for known vulnerabilities
  - the files each package will actually publish
- Each finding offers **Fix**, **Ignore once** or **Allow** (saved with a reason).
- **Settings → Release → Security.** Each check is On (block), Warn or Off. Secrets default to block. Dependencies default to blocking on high or critical and warning below that.
- **Scan history** runs once over the whole git history, for an existing repository about to go public.
- **Check every commit** (optional) installs a pre-commit hook, so a secret is stopped before it even reaches a local commit, the relay's included.
- **GitHub protection.** GitHub setup offers to turn on GitHub's own secret scanning, push protection and Dependabot alerts.
- **Deep audit** (off by default, on demand). Your main agent runs a multi-phase audit using a bundled copy of Cloudflare's MIT-licensed security-audit method. The Release gate can optionally block on *confirmed* high or critical findings.

Global constraints:
- New code lives in `src/whyline/security/` with tests in `tests/security/`. No new runtime dependency.
- A found secret is never printed, logged, stored or sent in full anywhere. That includes the transcript, the CLI, JSON output, allowlists, agent prompts and Telegram. Show only `first4…last2 (N chars)`. Allowlist entries store a fingerprint: sha256 of rule id, path and secret, first 16 hex characters.
- The dependency check sends only public package names, versions and ecosystems to `https://api.osv.dev`. A package not from the public registry (local path, git, workspace, a private index URL) is never sent and is listed as "not checked (private source)".
- Every subprocess goes through an injected `run`, and every HTTP call through an injected `fetch`. No test reaches the network, and no test needs gitleaks or osv-scanner installed.
- Scanning stays fast: the release gate covers only `origin/<branch>..HEAD` plus the package contents, and must finish in under 20 s on this repository. History scanning is separate and shows progress.
- Console first: every CLI command has a console counterpart calling the same function.
- Verify every task with `uv run pytest -q tests/security tests/release tests/console` and then `uv run pytest -q`. Change nothing outside the files a task names.

- [ ] SEC-1: Findings, settings and the allowlist
  Create `src/whyline/security/__init__.py`, `src/whyline/security/findings.py`, `src/whyline/security/settings.py` and `tests/security/test_settings.py`; edit `src/whyline/release/config.py` and its test only.
  - `Finding(kind, rule, title, severity, path, line, commit, preview, fingerprint, fix_hint, source)`:
    - `kind` is secret / dependency / contents / audit
    - `severity` is critical / high / medium / low / unknown
    - `source` is builtin / gitleaks / betterleaks / osv-scanner / audit
    - `preview` follows the masking rule
  - `[security]` in `release.toml`:
    - `secrets = "block"`, `dependencies = "block-high"` (block / block-high / warn / off), `contents = "block"`
    - `history_scanned = ""` (date of the last full scan)
    - `pre_commit = false`
    - `audit = "off"` (off / warn / block-confirmed)
    REL-1's `load`/`save` read and write it, and unknown values are a `ConfigError`.
  - Allowlist in `.whyline/security-allow.toml`, committed: entries `{fingerprint, rule, path, reason, added}`. `allow(root, finding, reason)` refuses an empty reason. `is_allowed(root, finding)`. `ignore_once(state_dir, finding)` lasts only for the current release run, under `.git/whyline-release/`.
  - `decide(findings, settings) -> Decision(blocking, warnings, allowed)`.
  Tests: masking for short and long values, fingerprint stability, settings round-trip and errors, allow needs a reason, decide per setting (block-high lets medium through as a warning).

- [ ] SEC-2: Bundled secret rules and the Go-to-Python regex translator
  Create `src/whyline/security/rules/gitleaks.toml`, `src/whyline/security/rules/LICENSE-gitleaks`, `src/whyline/security/rules/VERSION`, `src/whyline/security/rules.py`, `scripts/update_secret_rules.py` and `tests/security/test_rules.py` only. Make sure the package data ships the `rules/` files (check `pyproject.toml`'s build config, and add the include there only if needed).
  - Copy gitleaks' `config/gitleaks.toml` from its latest release tag, with its MIT licence text. `VERSION` holds the tag and the date. `scripts/update_secret_rules.py --ref <tag>` refreshes all three. It's a developer-only script, never run by whyline.
  - `load_rules() -> RuleSet`. Each rule carries id, description, regex, secret_group, entropy, keywords (lowercased), path regex and its allowlists (regexes, stopwords, paths, `regexTarget`), plus the global allowlist.
  - `translate(go_regex) -> str`:
    - `\z` becomes `\Z`
    - a `(?i)` (or other inline flag group) that isn't at the very start becomes a scoped group `(?i:…)` covering the rest of its enclosing group, with parentheses and character classes tracked properly
    - possessive and atomic forms Python lacks are left to fail
    In today's file, 25 of 222 regexes don't compile in Python as written (22 mid-pattern flags, 3 `\z`).
  - Rules that still fail to compile are skipped, and their ids are listed in `RuleSet.skipped`.
  Tests:
  - the bundled file loads, and at least 98% of its rules compile after translation
  - `translate` on `abc(?i)def`, `x(?:a(?i)b)c`, `foo\z`, and a `(?i)` inside a character class (left alone)
  - every skipped id is reported
  - for 10 named rules (AWS access key, GitHub PAT, GitHub fine-grained PAT, Slack bot token, Stripe secret key, OpenAI key, Anthropic key, Google API key, a private key block, a generic API key), a synthetic sample matches and a near-miss doesn't. Build the samples in the test from pieces, so the test file itself never contains a matching literal: GitHub push protection and this plan's own scanner would flag it.

- [ ] SEC-3: The built-in secret scanner
  Create `src/whyline/security/secrets.py` and `tests/security/test_secrets.py` only.
  - `scan_text(text, path, rules) -> list[Finding]`:
    - skip paths in the global allowlist
    - per rule, check keywords before running the regex (case-insensitive)
    - take `secretGroup` (or the whole match)
    - apply the rule's entropy threshold (Shannon entropy) and allowlists
    - mask the preview
  - `DENY_NAMES`: `.env`, `.env.*` (but not `.env.example`/`.env.sample`), `*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa`, `id_ed25519`, `.npmrc` containing `_authToken`, `.pypirc` with a password, `credentials.toml`, `.whyline/relay/logs/`. Each produces a `contents`-kind finding even when nothing inside matches.
  - Scopes:
    - `scan_range(root, rev_range, *, run)`: added lines only, from `git log -p --no-color --unified=0 <range>`, with commit and line numbers
    - `scan_staged(root, *, run)`: `git diff --cached -U0`
    - `scan_paths(root, paths)`: whole files, skipping binaries (a NUL byte in the first 8 KB) and files over 2 MB
    - `scan_history(root, *, run, on_progress, cancel_event)`: `git log -p --all` streamed, with progress as commits done of `git rev-list --all --count`
  - Findings are de-duplicated by fingerprint, keeping the earliest commit.
  Tests (temp git repos, secrets built from pieces):
  - a key added in the range is found with its commit and line
  - a key removed later is still found by history and not by the range
  - the staged scope
  - a keyword miss skips the regex (spy)
  - low entropy is ignored
  - allowlisted paths are skipped
  - each DENY_NAMES case, including `.env.example` passing
  - no finding, repr or exception message contains the full secret (assert across all outputs)

- [ ] SEC-4: Read dependency lockfiles
  Create `src/whyline/security/lockfiles.py`, fixtures under `tests/security/fixtures/` and `tests/security/test_lockfiles.py` only.
  - `Dependency(name, version, ecosystem, source_file, public: bool)`. `read_all(root) -> list[Dependency]` finds and parses:
    - `uv.lock`: `[[package]]` with `source.registry` on pypi.org counts as public; editable, virtual, path, git and other registries are private. The root project itself is skipped.
    - `poetry.lock`
    - `requirements*.txt`: only `name==version` pins; other lines are listed as "unpinned, not checked"
    - `package-lock.json` v2 and v3: `packages` entries under `node_modules/`, public when `resolved` is on registry.npmjs.org; `link: true` and `file:` are private
    - `pnpm-lock.yaml` and `yarn.lock`: names and versions with a small line parser, and no YAML dependency
  - Ecosystem names are OSV's (`PyPI`, `npm`). PyPI names are normalised as PEP 503 does.
  Tests: one fixture per format, with private and public entries, the root skipped, and unpinned requirements reported.

- [ ] SEC-5: Check dependencies against OSV.dev
  Create `src/whyline/security/deps.py` and `tests/security/test_deps.py` only.
  - `check(deps, *, fetch, cache_dir, now) -> DepReport(findings, not_checked, error)`.
    - POST `https://api.osv.dev/v1/querybatch` with only public deps, in chunks of 500, with a 20 s timeout per call. Then GET `https://api.osv.dev/v1/vulns/<id>` for each new id.
    - Each vuln is cached for 24 hours in `~/.whyline/security/osv-cache/`.
  - Severity:
    - use `database_specific.severity` when present (GHSA's CRITICAL/HIGH/MODERATE/LOW, with MODERATE as medium)
    - otherwise the CVSS v3 base score from `severity[].score`, computed from the vector with a small built-in calculator: 9.0+ critical, 7.0+ high, 4.0+ medium, else low
    - otherwise unknown
  - `fix_hint`: "upgrade <name> to <first fixed version>" from `affected[].ranges[].events[].fixed` for the matching package, or "no fixed version yet".
  - A network failure returns `error="could not reach OSV.dev"` and no findings. The gate treats that as a warning, never as passing silently.
  Tests (fake fetch): a vulnerable and a clean package, chunking at 500, the cache hit, each severity source including a CVSS vector, fix hints, a private dep never in any request body, the network error.

- [ ] SEC-6: Check what each package actually publishes
  Create `src/whyline/security/contents.py` and `tests/security/test_contents.py` only.
  - Python (`pyproject.toml` with `[project]`): run `uv build --out-dir <tmp under .git/whyline-release/build>`, list the wheel (zipfile) and sdist (tarfile) members, and run `scan_text` over each text member, plus DENY_NAMES on member names.
  - npm (`package.json`, not private): run `npm pack --dry-run --json`, then scan the listed files from the working tree.
  - Docker (`Dockerfile`): compute the build context as the files `git ls-files --cached --others --exclude-standard` lists, minus `.dockerignore` patterns (a small matcher with `*`, `**`, `!` and leading `/`), then scan those. Warn when there is no `.dockerignore`.
  - `check(root, *, run) -> list[Finding]` returns `contents` findings with `path` as `<artifact>:<member>`. A build failure is one finding, "could not build <kind>: <last line>", at warn level.
  Tests: a wheel fixture containing a `.env`, a sdist with a key in a text file, npm pack JSON listing a `.npmrc`, `.dockerignore` matching (negation included), and the build-failure finding.

- [ ] SEC-7: Use gitleaks, betterleaks or osv-scanner when installed
  Create `src/whyline/security/external.py` and `tests/security/test_external.py` only.
  - `available(which=shutil.which) -> dict[str, str]` (tool → path).
  - Run the tool with JSON output to a temp file, never to stdout in the transcript:
    - secrets: `gitleaks git --log-opts "<range>" --report-format json --report-path <tmp> --redact`, and `dir` mode for paths. betterleaks takes the same flags: check its README at implementation time and adapt in this one function if not.
    - deps: `osv-scanner scan source -r . --format json`
  - Convert the results to `Finding`s. Use `source` = the tool name and the same masked preview: the `--redact` output has no secret, so the preview is `(redacted by <tool>)`.
  - `merge(builtin, external)`: de-duplicate by `(path, line, rule family)`, and prefer the external finding's rule name.
  - A tool that crashes or times out (60 s) becomes a warning, and the built-in results stand.
  Tests: parsing recorded JSON samples for each tool (fixtures written in the test, secrets built from pieces), merge de-duplication, a tool crash, `--redact` always passed.

- [ ] SEC-8: `whyline security` CLI and the Release gate
  Create `src/whyline/security/scan.py`, `src/whyline/security/cli.py` and `tests/security/test_cli.py`; edit `src/whyline/cli.py` only to register it the way `_add_workflows`/`cmd_workflows` do; edit `src/whyline/release/ready.py` and its test only to register the item.
  - `scan.run(root, scope, settings, *, run, fetch, which, on_progress, cancel_event) -> ScanReport`. Scope is `release` (`origin/<branch>..HEAD` plus contents plus deps), `staged`, `history` or `all`. It combines SEC-3 to SEC-7, filters through the allowlist and ignore-once, and calls `decide`. On a completed history scan it saves `history_scanned`.
  - CLI:
    - `whyline security scan [--staged|--history|--all] [--json]`: findings grouped by kind, then a summary. Exits 1 when anything blocks.
    - `whyline security allow <fingerprint> --reason TEXT`
    - `whyline security status`: settings, tools found, rules version, last history scan
  - Release: `register_ready("security", …)`. The Ready item is ✓ with "no findings" or "N warnings", ✗ with "N blocking findings (secrets: a, dependencies: b, contents: c)", or ✗ "security scan failed: <reason>". The fix text is "Open Security to review". When `history_scanned` is empty and the repository has never been pushed (no `origin/<branch>`), a second item suggests **Scan history** (✗ only when secrets is "block").
  Tests: each scope's combination (fakes), the exit codes, allow from the CLI, `--json` contains no secret, the Ready item in each state, the history suggestion only before the first push.

- [ ] SEC-9: Security in the console
  Create `src/whyline/console/security_screens.py` and `tests/console/test_security_screens.py`; edit `src/whyline/console/release_screens.py` and its test only.
  - `SecurityScreen(ModalScreen)` opens from **Security…** on the Release tab, from the Ready item's fix, and from a Security section in the Set up tab.
    - It shows findings grouped by kind: severity badge, title, `path:line`, commit short sha, masked preview and fix hint.
    - Per finding: **Fix** opens the file at the line in the console's editor (for a secret, the hint also says "rotate this key; deleting it doesn't remove it from history once pushed"). **Ignore once**. **Allow…** asks for a reason.
    - **Scan again**, **Scan history** (a worker, with progress `commits n of m` and **Stop**), and **Copy report**, which has masked values only.
  - The Set up tab's Security section has:
    - three selects (secrets, dependencies, contents) with block/warn/off, and block-high for dependencies
    - **Check every commit** (SEC-10) and Deep audit (SEC-12)
    - tools found, with the `brew install gitleaks osv-scanner` hint and **Copy** when missing
    - the rules version and date
    Everything saves through `config.save`.
  Tests: grouping and badges, Allow needs a reason and writes through `allow`, Ignore once, history scan progress and Stop, Copy report contains no full secret, the settings round-trip.

- [ ] SEC-10: Check every commit (optional pre-commit hook)
  Create `src/whyline/security/hook.py` and `tests/security/test_hook.py`; edit `src/whyline/security/cli.py`, `src/whyline/console/security_screens.py` and their tests only.
  - `install(root)` writes `.git/hooks/pre-commit` running `whyline security scan --staged --hook`. If a hook already exists and isn't whyline's, it is kept: `install` refuses and tells the user to add the line themselves (shown with **Copy**). `uninstall(root)` removes only whyline's hook. `installed(root)`.
  - `--hook` mode prints only blocking secret findings (masked) and the line `Commit stopped by whyline security. Review: whyline security scan --staged`. It exits 1 on a block and 0 otherwise. It skips the dependency and contents checks, so it stays under 2 s. With `secrets = "off"`, it exits 0 at once.
  - When it blocks a relay commit, the relay's commit fails, and with whyline-relay RLY-10 the relay pauses with the task kept. The pause message includes the hook's output, so Resolve shows it.
  - The CLI gets `whyline security hook install|uninstall|status`. The Security section's **Check every commit** switch calls the same functions.
  Tests: install, uninstall, an existing foreign hook kept, `--hook` blocking on a staged secret and passing on a clean change (a temp repo with a real commit through the installed hook), the hook output is masked, the off setting.

- [ ] SEC-11: GitHub's own protection
  Edit `src/whyline/release/setup_github.py`, `src/whyline/console/release_screens.py` and their tests only.
  - `protection_status(owner_repo, *, run)` reads `gh api repos/<o>/<r> --jq .security_and_analysis` and `gh api repos/<o>/<r>/vulnerability-alerts` (204 on, 404 off). It returns secret scanning, push protection and Dependabot alerts as on/off/unavailable.
  - `enable_protection(owner_repo, which, *, run)`:
    - `gh api -X PATCH repos/<o>/<r> -f security_and_analysis[secret_scanning][status]=enabled`, and the same for `secret_scanning_push_protection`
    - `gh api -X PUT repos/<o>/<r>/vulnerability-alerts`
    Check GitHub's REST docs at implementation time and match field names there. A 403 or 422 (for example a private repository without the needed plan) becomes "not available for this repository: <message>", never a crash.
  - The GitHub Set up panel shows the three with **Turn on** buttons, and says that GitHub's push protection is a second net, not a replacement for the local scan.
  Tests: each status, the enable argv, the unavailable message on 403/422.

- [ ] SEC-12: Deep audit run by the main agent
  Create `src/whyline/security/audit.py`, `src/whyline/security/audit_method/` (the method files and `LICENSE-cloudflare`) and `tests/security/test_audit.py` only.
  - Bundle Cloudflare's security-audit-skill method (MIT) from its latest tag, keeping the licence and a `VERSION` file:
    - the phase instructions
    - the attack-class playbooks relevant to this kind of project (LLM, prompt injection and agent tooling; supply chain and release; HTTP and auth; resource exhaustion; data isolation; desktop IPC)
    - the findings JSON schema
  - `run(root, *, agent, ask_agent, out_dir=None, cancel_event, on_progress) -> AuditReport`:
    - output goes to `~/.whyline/security/audits/<repo-name>/run-<N>/`, never inside the repository
    - the prompt gives the method, the repository path and the output directory, and says not to run the project's code (no sandbox is provided, so unverifiable leads stay `needs_validation`), not to modify the repository, and to write `findings.json` against the schema
    - it uses the relay's main agent with no timeout cap beyond the user's setting, falling back to the backup chain only on a limit or auth failure
  - The `findings.json` is validated against the schema with a small built-in validator for the schema's subset. Invalid output is kept, and the report says "the agent's output didn't match the schema", with the first errors.
  - Findings become `Finding(kind="audit", …)` keeping the verdict: confirmed, needs_validation or rejected. Rejected findings are only counted.
  Tests (fake agent writing fixture files): the output dir outside the repo, the prompt's must-not lines, a valid file to findings with verdicts, invalid JSON and schema errors reported, run numbering, cancel.

- [ ] SEC-13: Deep audit in the console and the Release gate
  Edit `src/whyline/console/security_screens.py`, `src/whyline/security/scan.py`, `src/whyline/security/cli.py` and their tests only.
  - The Security screen gets an **Audit** tab. **Run deep audit** shows that it uses your main agent, may take a long time and many tokens, and that a single run finds only part of what repeated runs do. It then runs in a worker with elapsed time and **Stop**.
  - Findings are listed by verdict and severity, with **Open report** for the run folder's `REPORT.md`. Past runs are listed.
  - `whyline security audit [--agent NAME]` calls the same function.
  - The Release gate with `audit = "warn"` shows confirmed findings from the latest audit as warnings. With `block-confirmed`, confirmed high or critical ones block. `needs_validation` never blocks. With no audit run yet, `block-confirmed` gives a ✗ "run a deep audit first".
  Tests: the tab lists runs and verdicts, Stop, each gate setting, and needs_validation never blocking.

- [ ] SEC-14: Docs
  Create `docs/security.md`; edit `docs/release.md` and `README.md` only.
  - What each check looks at, what leaves the Mac (only public package names and versions, to OSV.dev), the settings and their defaults, Allow versus Ignore once, and Scan history with why a pushed key must be rotated.
  - Check every commit, GitHub protection, the deep audit's cost and limits, and the optional tools.
  - Credits: gitleaks rules (MIT) and Cloudflare's security-audit method (MIT), with links and the bundled versions.
