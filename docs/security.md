# Security

Whyline checks a release for leaked secrets, vulnerable dependencies and
unwanted files before anything is pushed. **Nothing needs installing**: the
scanner is built in. Everything here is also in `whyline console`
(**Release → Security…** and **Release → Set up → Security**); the CLI is for
scripts.

## What each check looks at

| Check | Looks at | Setting |
| --- | --- | --- |
| **Secrets** | The lines added by the commits about to be pushed (`origin/<branch>..HEAD`): API keys, tokens, private keys. Also `.env`-style files. | `secrets` |
| **Dependencies** | Pinned versions in `uv.lock`, `poetry.lock`, `requirements*.txt`, `package-lock.json`, `pnpm-lock.yaml` and `yarn.lock`, checked against known vulnerabilities. Unpinned requirements are listed as "not checked". | `dependencies` |
| **Package contents** | The files each package would really publish: the wheel and sdist from `uv build`, `npm pack --dry-run`, and the Docker build context (a missing `.dockerignore` is a warning). Secrets inside them and files such as `.env`, `*.pem`, `*.key`, `id_rsa`, `.npmrc` with a token and `credentials.toml` are flagged. | `contents` |

The release scan covers only the unpushed commits plus the package contents,
so it stays quick. A secret found anywhere is shown masked as
`first2****last2` (just `****` when the value is 8 characters or fewer); the full value is never printed, logged, stored,
copied or sent to an agent. Allowlist entries hold a fingerprint (a truncated
hash), not the secret.

## What leaves your Mac

Only the dependency check uses the network. It sends **public package names,
versions and ecosystem** (for example `requests 2.31.0 PyPI`) to
[OSV.dev](https://osv.dev) (`api.osv.dev`), and nothing else: no code, no
paths, no secrets. A package that does not come from the public registry
(local path, git, workspace, private index) is never sent and is listed as
"NAME: private package, not checked". Answers are cached for 24 hours in
the repository, under `.git/whyline-release/osv-cache/`. If OSV.dev cannot be
reached, the result depends on the dependencies setting: with `block` or
`block-high` (the default) the scan fails and Ready shows
"✗ security scan failed: could not reach OSV.dev"; with `warn` it is a note
("could not reach OSV.dev"). It never passes silently.

The secret and contents checks run entirely on your machine.

## Settings and defaults

In **Release → Set up → Security**, or the `[security]` table of
`.whyline/release.toml`:

| Setting | Values | Default |
| --- | --- | --- |
| `secrets` | `block`, `warn`, `off` | `block` |
| `dependencies` | `block`, `block-high`, `warn`, `off` | `block-high` (blocks high and critical, warns on the rest) |
| `contents` | `block`, `warn`, `off` | `block` |
| `pre_commit` | `true`, `false` | `false` (Check every commit) |
| `audit` | `off`, `warn`, `block-confirmed` | `off` |
| `history_scanned` | date, set by Scan history | empty |

The Release **Ready** check gains a Security item: ✓ with "no findings" or
"N warnings", or ✗ with the number of blocking findings by kind.

## Allow versus Ignore once

Each finding offers **Fix**, **Ignore once** and **Allow…**.

- **Fix** opens the file at the line. For a secret it also tells you to rotate
  the key.
- **Ignore once** applies to the current release run only (kept under
  `.git/whyline-release/`). The next release flags it again.
- **Allow…** asks for a reason (required) and saves the finding's fingerprint
  in `.whyline/security-allow.toml`, which you commit. It is skipped from then
  on, for everyone. Use it for test fixtures and known false positives, not to
  silence a real key. CLI: `whyline security allow <fingerprint> --reason TEXT`.

## Scan history

**Scan history** (`whyline security scan --history`) reads every commit ever
made, including secrets that were later deleted. Run it once on an existing
repository before making it public. It shows progress (`commits n of m`) and
has **Stop**; the date of a completed run is saved as `history_scanned`. Before
a repository's first push, the Ready check suggests it.

**A key found in history, or already pushed, must be rotated.** Deleting it in
a new commit does not remove it: it stays in every earlier commit and every
clone, and anyone who fetched it keeps a copy. Revoke the key at its provider
and create a new one first; rewriting history is optional and only tidies up.

## Check every commit

Optional. **Check every commit** (`whyline security hook install`) writes a
`pre-commit` hook that scans the staged changes for blocking secrets, so a
key is stopped before it reaches even a local commit, the relay's included.
It skips dependencies and contents so it stays fast, and prints only masked
values. A hook that is not whyline's is never overwritten: whyline shows the
line to add yourself, with **Copy**. `whyline security hook uninstall` removes
only its own hook. When the hook stops a relay commit, the relay pauses with
the task kept and the hook's output in the pause message. A secrets setting of
`off` makes the hook exit at once.

## GitHub protection

In **Release → Set up → GitHub**, whyline shows whether GitHub's own **secret
scanning**, **push protection** and **Dependabot alerts** are on, and offers
**Turn on** for each. Some are unavailable for private repositories without
the right plan; you then see "not available for this repository" and nothing
breaks. GitHub's push protection is a second net, not a replacement for the
local scan, which runs before anything is pushed.

## Deep audit

Off by default and on demand: **Security… → Audit → Run deep audit**, or
`whyline security audit [--agent NAME]`. Your **main agent** reads the
repository using a multi-phase method (reconnaissance, hunting, validation,
reporting) with playbooks for AI and agent tooling, supply chain, web and
auth, resource exhaustion, data isolation and desktop IPC.

- **Cost.** It can take a long time and **many tokens** from your plan, and
  has no timeout beyond your own setting. It falls back to your backup agents
  only on a limit or sign-in failure.
- **Limits.** One run finds only part of what repeated runs would. The agent is
  told not to run the project's code or change the repository, and there is no
  sandbox, so leads it cannot verify stay `needs_validation`. Treat results as
  leads to review, not a clean bill of health.
- **Output.** Reports go to `~/.whyline/security/audits/<repo-name>/run-<N>/`
  (`findings.json`, `REPORT.md`), never into the repository. Output that does
  not match the schema is kept, and the report shows the first errors.
- **Gate.** With `audit = "warn"`, confirmed findings from the latest run show
  as warnings. With `block-confirmed`, confirmed high or critical findings
  block; with no run yet it asks you to run one first. `needs_validation`
  never blocks, and rejected findings are only counted.

## Optional tools

If `gitleaks`, `betterleaks` or `osv-scanner` is on your PATH, whyline also
runs it, with redacted output, for wider coverage, and merges duplicates with
the built-in results. A tool that crashes or takes over 60 seconds becomes a
warning and the built-in results stand. Setup suggests
`brew install gitleaks osv-scanner` but never requires it.

## Command reference

```text
whyline security scan [--staged | --history | --all] [--json]
whyline security allow <fingerprint> --reason TEXT
whyline security status
whyline security hook install | uninstall | status
whyline security audit [--agent NAME]
```

`scan` exits 1 when anything blocks.

## Credits

- **Secret rules**: [gitleaks](https://github.com/gitleaks/gitleaks) default
  rules (`config/gitleaks.toml`), MIT licence, bundled at **v8.30.1**
  (2026-03-21). The licence text ships in
  `src/whyline/security/rules/LICENSE-gitleaks`.
- **Deep audit method**: Cloudflare's
  [security-audit-skill](https://github.com/cloudflare/security-audit-skill),
  MIT licence, bundled at commit **c1c8a8c** (`main`, 2026-09-14; the
  repository has no tags or releases). The licence ships in
  `src/whyline/security/audit_method/LICENSE-cloudflare`.
- **Vulnerability data**: [OSV.dev](https://osv.dev).
