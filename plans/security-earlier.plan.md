<!-- whyline-plan v1 | source: hand | drafted-by: claude | spec: docs/superpowers/specs/2026-11-15-release-hardening-design.md | created: 2026-11-15T14:30:00+05:30 -->
# Security earlier: the commit hook by default, a code check, a quicker audit and licences

Runs after `plans/sdlc-done.plan.md`, and before `plans/release-safety.plan.md`. Spec: `docs/superpowers/specs/2026-11-15-release-hardening-design.md`, Part 2. Read it before every task. Where this plan and the spec differ, this plan wins. In particular:
- **Bandit and Semgrep are not wired in here.** The built-in rules come first. Using those tools when installed is a follow-up.
- **The code check covers Python only.**

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

Why: `pre_commit` is off by default and the relay commits every task, so a secret committed mid-plan is in git history before the release scan sees it. The agent audit is off by default, and nothing looks at the code for risky patterns. A new dependency's licence is never shown.

What the user gets:
- The secret check runs on every commit for new set-ups, and Release → Set up offers it where it is off.
- When the hook stops a relay's commit, the console says what was found and offers to allow it, open the file, or ask an agent to remove it.
- A built-in check for risky Python patterns, as a warning by default.
- The agent audit on changed files only, as a warning by default.
- New dependencies listed with their licence, and flagged licences warned about.

Rules every task keeps:
- **Console first.** Every setting and action has a console counterpart saving through the same function as its CLI command.
- **Existing repositories keep their settings.** A repository whose config already has a `[security]` table is not changed by an upgrade. New defaults apply only to a config written for the first time.
- **Every finding can be allowed** with a reason, through the existing allowlist (`.whyline/security-allow.toml`), and every level can be set to `warn` or `off`.
- **No secret's value** in a finding, a log, a dialog or a prompt.
- **The hook stays fast:** the staged scan only, no network, no code check and no audit in the hook.
- **Code under test is data.** The code check parses files with `ast` and never imports or runs them.
- **No new dependency.**
- **Tests:** never invoke a real provider or the network. Use temporary repositories and fakes. Keep Python 3.11 compatibility.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Release scope:** no version bump, tag, push or publish.

**Review focus.** Each item is pinned by the test named in its task. This list, plus each task's own tests, is the complete bar for approval. A reviewer who finds a gap outside it records `whyline handoff <task> --issue "follow-up: <gap>"` and approves, and never rejects for it.
- An existing config's security settings are unchanged after upgrade. SEA-1, `test_existing_settings_are_kept`.
- A hook installed by something else is never overwritten. SEA-1, `test_foreign_hook_is_left_alone`.
- A risky pattern inside a comment or a string is not flagged, and a file that doesn't parse is reported, not crashed on. SEA-3, `test_code_check_reads_syntax_not_text`.
- The changed-files audit never sends more than 60 files, and never a file outside the repository. SEA-4, `test_changed_audit_is_bounded`.
- A dependency whose licence can't be read is `unknown`, never treated as fine. SEA-5, `test_unknown_licence_is_flagged`.

- [ ] SEA-1: The commit hook on by default, and offered in Set up
  Edit `src/whyline/security/settings.py`, `src/whyline/security/hook.py`, `src/whyline/release/config.py`, `src/whyline/console/release_screens.py`, `src/whyline/security/cli.py` and their tests only.
  1. When a release config is written for the first time for a repository (no `[security]` table yet), `pre_commit` is True and the hook is installed (`hook.set_installed`). A config that already has the table is read as it is.
  2. A hook that exists and isn't whyline's (`hook.foreign`) is never replaced. Set up then shows `Another pre-commit hook is installed. Add this line to it: whyline security scan --staged --hook` with **Copy**.
  3. Release → Set up shows, where the hook is off: `Secrets are only checked at release. Check every commit?` with **Turn on**. The Ready check lists it as a ready item that warns and never blocks.
  4. The hook script gains a second line so a missing `whyline` never blocks a commit: when the command is not found, it prints `whyline isn't on PATH; the secret check was skipped` and exits 0.
  Tests: `test_existing_settings_are_kept`, `test_foreign_hook_is_left_alone`, a first config turning it on, the Set up line and its button, the Ready item, and the hook script's missing-command line.

- [ ] SEA-2: When the hook stops a relay's commit
  Edit `src/whyline/console/recovery.py`, `src/whyline/security/hook.py`, `src/whyline/security/scan.py` and their tests only.
  1. `hook.STOP_LINE` stays the marker. `scan` writes the staged scan's findings (rule, file, line, fingerprint; no value) to `.git/whyline-security-last.json` when run with `--hook`.
  2. `recovery` gets a problem `hook-stopped`: detected when a paused relay's reason or log tail contains `hook.STOP_LINE`. Its summary is `The secret check stopped the commit: <rule> in <file>:<line>` (the first finding, and `and <n> more`).
  3. Its options:
     - **Allow this**: asks for a reason, adds the allowlist entries for the listed fingerprints, and resumes the relay
     - **Open the file**: opens it at the line in the Files pane
     - **Ask an agent to remove it**: the existing Ask agent option, with the finding (no value) as its context
     - **Cancel**
  4. Allow is refused for a rule the allowlist can't cover (a denied file such as `.env`), with the reason.
  Tests: detection from a pause reason and from a log tail, the summary with one and with several findings, Allow writing the entries with the reason and resuming, the refused case, and no value anywhere in the problem text.

- [ ] SEA-3: A built-in code check
  Create `src/whyline/security/code.py` and `tests/security/test_code.py`. Edit `src/whyline/security/settings.py`, `src/whyline/security/scan.py`, `src/whyline/security/findings.py` and their tests.
  1. `code.check(root, files: list[str] | None = None, *, skip_paths=…) -> list[Finding]` parses each tracked `.py` file with `ast` (all tracked files when `files` is None; tests under `tests/` and paths in `skip_paths` are skipped). Rules, each with an id, a severity and a one-line fix:
     - `shell-true` (high): `subprocess.*` or `os.system`/`os.popen` with `shell=True` or a string command that isn't a literal
     - `eval-exec` (high): `eval` or `exec` on anything but a literal
     - `unsafe-load` (high): `pickle.load(s)`, `marshal.load(s)` on non-literals, `yaml.load` without a `Loader` that is a safe loader
     - `no-verify` (high): `verify=False` in a call, or `ssl._create_unverified_context`
     - `sql-format` (medium): `.execute(` whose first argument is an f-string, a `%` format or a `+` concatenation with a non-literal
     - `weak-hash` (medium): `hashlib.md5`/`sha1` in a function or assignment whose name contains `password`, `token`, `secret` or `sign`
     - `mktemp` (medium): `tempfile.mktemp`
     - `bind-all` (low): a string literal `0.0.0.0` passed as a host or bind argument
     - `assert-auth` (low): an `assert` whose test names `user`, `admin`, `auth` or `permission`
  2. A file that doesn't parse gives one low finding `unparsed` with the syntax error's line, and the check goes on. A file over 1 MB is skipped with a note.
  3. A line ending `# whyline: allow <rule-id> <reason>` is not reported.
  4. `SecuritySettings.code: str = "warn"` with the choices `block-high`, `warn`, `off`. `scan.run` runs the check for the release scope (files changed since the last tag, or all when there is no tag) and gates on it like the others. Findings use a fingerprint of rule, file and the normalised source line, so they survive line-number changes and can be allowed in the allowlist.
  Tests: `test_code_check_reads_syntax_not_text` (each pattern inside a comment, a docstring and a string is not flagged; a syntax error gives `unparsed`), each rule firing and its safe twin not firing, the inline allow, the allowlist, the three levels in the gate, and tests and skip paths left out.

- [ ] SEA-4: The audit on changed files
  Edit `src/whyline/security/audit.py`, `src/whyline/security/scan.py`, `src/whyline/security/settings.py`, `src/whyline/security/cli.py`, `src/whyline/console/security_screens.py` and their tests only.
  1. `SecuritySettings.audit_scope: str = "changed"` (`changed` or `full`). For a config written for the first time, `audit` is `warn`. An existing config keeps its value.
  2. `audit.changed_files(root, since_ref, *, run) -> list[str]`: tracked files changed since the ref, existing, inside the repository, not in `skip_paths`, text files only, ordered by the size of their diff, at most 60. With no ref (first release), the scope falls back to `full`.
  3. `audit.build_prompt` takes the list and tells the agent to review those files and what they call, using the same method files and report schema. The run record stores the scope and the file list.
  4. With `changed` and no changed code files, the audit is skipped with `No code changed since <ref>`.
  5. Console: the Security screen's audit section gets **Scope** (Changed files / Everything) and **Audit everything now**. CLI: `whyline security audit [--full]`, and `whyline security settings audit-scope changed|full`.
  Tests: `test_changed_audit_is_bounded` (200 changed files give 60; a symlink pointing outside and a deleted file are left out), the ordering, the first-release fallback, the skip line, the settings round trip, and console and CLI calling one function.

- [ ] SEA-5: Licences of dependencies
  Create `src/whyline/security/licences.py` and `tests/security/test_licences.py`. Edit `src/whyline/security/settings.py`, `src/whyline/security/scan.py`, `src/whyline/release/ready.py`, `src/whyline/console/security_screens.py`, `src/whyline/security/cli.py` and their tests.
  1. `licences.read(root, deps: list[Dependency], *, metadata=…) -> dict[str, str]` (package → licence): for PyPI packages from installed metadata in the project's environment (`License-Expression`, else `License`, else the `License ::` classifiers), for npm from `package-lock.json`'s `license` fields. Anything unreadable is `unknown`. Values are normalised to short ids (`MIT`, `Apache-2.0`, `GPL-3.0`…) for the common spellings.
  2. `SecuritySettings.licences: str = "warn"` (`warn` or `off`) and `flag_licences: tuple[str, ...]` (default `GPL`, `AGPL`, `LGPL`, `SSPL`, `unknown`; a prefix match).
  3. `licences.new_since(root, ref, *, run) -> list[Dependency]`: dependencies in the lockfile now that were not in it at the ref.
  4. The scan adds a finding per flagged licence (severity low, never blocking). The Ready check lists `New dependencies since <tag>: <name> (<licence>), …` as an informational item.
  5. Console: the Security screen lists dependencies with a flagged licence and the setting. CLI: `whyline security licences [--all]`.
  Tests: `test_unknown_licence_is_flagged`, each metadata source, the normalised spellings, the prefix match, new dependencies since a ref, and the Ready item.

- [ ] SEA-6: Docs
  Edit `docs/security.md` (or the page that documents the security check), `docs/release.md` and `README.md` only.
  Cover: the commit hook and how to turn it off, what happens when it stops a relay, the code check's rules and the inline allow, the audit scope, the licence check, and that existing repositories keep their settings.
  Verify with `uv run pytest -q`.
