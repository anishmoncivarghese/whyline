# What else can be updated in Whyline — independent Codex pass

## Executive view

Whyline has moved beyond a decision-log CLI. At v0.3.18 it is also a multi-agent launcher, account/model selector, chat console, brainstorm surface, and front end for Whyline Relay. The local baseline is healthy (`498 passed, 1 skipped`), but this fast expansion has created three kinds of product debt:

1. Agent support is duplicated and hard-coded, so every new CLI will become increasingly expensive to add correctly.
2. Several high-value capabilities are now present in vendor CLIs but Whyline exposes only a model string and a final text response.
3. The core differentiator—the durable decision record—still has no first-class lifecycle for superseding, validating, or retiring old decisions.

My recommendation is to make the next milestone “open agent registry + trustworthy decision lifecycle,” not another isolated adapter. Gemini should be the first adapter built through that registry because the repository's current statement that Gemini CLI is dead is no longer true.

## Repository findings

- The four agents are repeated across `runner.py`, `account.py`, `cli.py`, `console/repl.py`, `console/tui.py`, and `console/adapters.py`. Adding one agent requires coordinated edits to launch commands, model flags, login commands, status labels, brainstorm choices, defaults, and tests.
- `whyline model set` accepts arbitrary strings. This is future-proof but offers no discovery, capability check, typo warning, provider selection, reasoning-effort setting, or distinction between interactive and unattended-safe models.
- `whyline account detect` writes `~/.whyline/account.json`. In a sandbox that can read the repository but cannot write the home directory, detection can succeed and still be discarded; callers then see no available agents. The transcript that prompted this brainstorm demonstrates the failure directly.
- `console/adapters.py` imports Whyline Relay internals and, for `start`/`resume`, redirects CLI output and classifies it with regular expressions such as `^Paused:` and `^Plan complete`. This is a version-coupling point despite the broad dependency range `whyline-relay>=0.2.1,<0.3`.
- The console stores a prompt history file, but its structured transcript is only in memory. The TUI shows a spinner and receives a final response; it does not consume the structured streaming output now offered by most agent CLIs.
- The decision log is append-only and readable, which is a good invariant, but its schema has no `supersedes`, `verified_at`, `status`, or stable subject anchor beyond file paths. A newer decision can contradict an older one and both remain equally eligible for `brief` and `explain`.
- Mechanical capture is implemented only for Claude and Codex. New launch adapters would otherwise appear fully supported while contributing no hook events.
- Raw prompt text is retained indefinitely in the gitignored ledger. Local-only is safer than hosted telemetry, but users still need retention, redaction, and deletion controls.
- Documentation can become stale independently of code. The README still excludes Gemini on a premise contradicted by current official documentation, while CI and packaging comments also retain assumptions from the older optional-extra layout.

## Highest-priority updates

### 1. Replace hard-coded agent maps with a capability registry

Create one `AgentSpec`/adapter contract as the source of truth. Suggested fields:

- stable key and display label
- executable and interactive prompt placement
- model, effort, working-directory, attachment, and resume arguments
- install, login, login-status, version, and model-list probes
- headless command builder and supported output formats
- permission/sandbox policy and whether unattended writes are safe
- instruction files read (`AGENTS.md`, `CLAUDE.md`, and vendor-specific files)
- hook support and mechanical-capture confidence
- availability meaning: installed, authenticated, subscribed, or manually enabled
- supported modes: `run`, console chat, brainstorm, relay role

All CLI choices, `/model`, `/login`, brainstorm UI, account detection, and documentation tables should derive from this registry. A capability must be allowed to be “unknown”; Whyline's strongest design habit is refusing to over-claim.

Keep built-ins in the package initially. Add user-defined adapters only after the contract is stable, with a declarative config for ordinary argv shapes and a Python entry point only for complex probes/parsers. Never let a third-party adapter silently inherit unattended-write permission.

### 2. Add Gemini CLI first, then Cursor and Copilot

The current README assertion that Gemini CLI is dead should be removed. Google's current CLI supports:

- interactive `gemini`
- headless `-p`/`--prompt`
- JSON and streaming JSON output
- `--model` and an `auto` model route
- Google-account authentication, including free individual accounts and paid Google AI subscriptions

Official references: [Gemini authentication](https://geminicli.com/docs/get-started/authentication/), [headless mode](https://geminicli.com/docs/cli/headless/), [model selection](https://geminicli.com/docs/cli/model/), and [plans](https://geminicli.com/plans/).

Recommended adapter order:

| Candidate | Why it fits | Main validation needed |
|---|---|---|
| Gemini CLI | Official CLI, subscription/free-account login, model flag, structured headless output | Permission behavior, login-status probe, hook/instruction behavior, quota failure signatures |
| Cursor Agent | Interactive and headless modes, `--model`, JSON streams, browser login/status, resume, and `AGENTS.md` support | Whether subscription login is valid for all headless use and safe unattended permission defaults |
| GitHub Copilot CLI | Available across Copilot plans, interactive and `-p` modes, `--model`, JSONL, attachments, and `AGENTS.md` support | Organization policy restrictions, tool approval policy, credit-limit reporting |
| Kiro CLI | Interactive/headless modes, model listing, resume, effort levels, structured streams | Headless mode currently requires an API key, which conflicts with Whyline's “subscriptions already paid for” positioning |

Official references: [Cursor CLI parameters](https://docs.cursor.com/en/cli/reference/parameters), [Cursor authentication](https://docs.cursor.com/en/cli/reference/authentication), [Copilot CLI quickstart](https://docs.github.com/en/copilot/get-started/cli-quickstart), [Copilot programmatic reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-programmatic-reference), and [Kiro CLI commands](https://kiro.dev/docs/cli/reference/cli-commands/).

Aider, OpenCode, and direct Ollama/provider wrappers should remain generic/community adapters at first. They can be useful, but they change Whyline's credential and billing story because they are not simply handing control to the user's official subscription CLI. Local models are better introduced through a vendor-supported route first—for example, Codex's current `--oss` with Ollama or LM Studio—using a launch profile rather than pretending the provider is just another model string.

### 3. Upgrade model selection into launch profiles

The user-visible object is no longer only a model. It is a launch profile:

```text
agent + model + provider + effort + permission mode + context/attachment support
```

Add commands such as:

- `whyline model list <agent>`: query the installed CLI when it exposes a model list; show “not discoverable” otherwise.
- `whyline profile set deep --agent codex --model ... --effort high`
- `whyline profile set local --agent codex --provider ollama --model ...`
- `/profile deep` in the console.

Validation should be advisory unless the vendor offers a reliable discovery command. Distinguish “verified available,” “vendor accepts arbitrary ID,” and “unverified string.” Cache discovery with the CLI version and a refresh command so new models are not blocked by Whyline releases.

Do not add opaque automatic routing first. Start with named profiles and explicit rules such as “brainstorm uses `fast`; final synthesis uses `deep`.” If automatic recommendations are later added, print the reason and require confirmation for any transition into unattended execution.

### 4. Make account detection work in restricted environments

Add a standard state-directory resolution order, for example:

1. `WHYLINE_HOME`
2. XDG/platform application-state directory
3. `~/.whyline`

If the chosen global location is unwritable, keep the fresh result in memory for the current command and optionally save a repo-local confirmation; do not convert a successful probe into “no agents available.” The status surface should separate `probe`, `cache`, and `repo confirmation` so users can see exactly which step failed.

Also prefer vendor-supported status commands over reading private auth formats. The current Codex plan detection decodes an undocumented JWT from `~/.codex/auth.json`, even though current Codex exposes `codex login status`. The CLI may not reveal the plan tier, so use it for authentication truth and treat tier as optional enrichment rather than making availability depend on a private claim.

### 5. Give decisions an explicit lifecycle

Preserve the append-only Markdown artifact, but add links between records:

- `whyline note ... --supersedes <event-id>`
- `whyline verify <event-id> --file ...`
- statuses such as active, superseded, invalidated, and needs-review
- an optional stable subject anchor: symbol name plus a content fingerprint, not only a mutable line number or a rebase-sensitive commit SHA

`brief` should show active decisions by default and include a compact “superseded history exists” notice. `explain` should prefer an active verified decision and state when the relevant code changed after verification. A new `whyline audit` could report contradictory active decisions, missing files, decisions attached to code that has materially changed, unresolved merge markers, and records with unreadable metadata.

This is more central to Whyline's identity than another console button. It turns a growing archive into maintained institutional memory.

### 6. Define a stable Whyline–Relay protocol

Move console integration away from importing private relay modules and parsing rendered text. Whyline Relay should expose a small supported API returning typed events such as:

```text
started, progress, handoff, paused(kind, reason, recovery), completed, failed
```

Add protocol-version/capability negotiation and show both package versions in `doctor`. Pin or test against the oldest and newest supported relay versions. This will also make streaming, cancellation, and better TUI rendering possible without depending on phrases in console output.

### 7. Stream progress and make cancellation real

Claude, Codex, Grok, Gemini, Cursor, Copilot, and Kiro now expose structured or streaming headless forms. Introduce a provider-neutral event stream for console/brainstorm/relay use:

- text delta
- thinking/progress status
- tool requested/started/finished
- usage/quota metadata when provided
- final response
- typed failure

Keep `whyline run` as the existing unsupervised `exec` path; streaming belongs only to surfaces that already supervise a child process. Stop should terminate the process group, wait briefly, escalate if necessary, and preserve resumable relay state. This addresses the current gap where cancelling a UI worker can suppress a late result without necessarily stopping the underlying vendor work.

### 8. Treat quota/session limits as routing state

The initiating transcript shows the actual user problem: one model hits a session limit and the user must manually understand what happened next. Persist a local cooldown record when a CLI reports a reset time, display it in `/model`, and offer a one-turn or session-level fallback. Never infer billing or quota from weak text if structured data is available.

Suggested behavior:

- “Claude unavailable until 16:30; continue with Codex for this turn?”
- remember the cooldown, not the credential or full response
- clear it on `/model refresh` or after expiry
- show why an agent was skipped during brainstorm
- estimate how many models/passes a brainstorm will invoke before starting

### 9. Finish attachments as a capability-aware feature

Attachments were intentionally deferred, but current CLIs increasingly support images and file inputs. Add a manifest with path, media type, size, digest, source, and whether it may be copied outside the repository. Map it per adapter instead of embedding paths in prose.

The UI should disable unsupported attachment types for the selected profile, redact secret-like files by default, enforce size/count limits, and record only metadata—not attachment contents—in operational history. Text files/directories can be passed as explicit scoped context; image support should be declared per agent/model.

## Additional worthwhile updates

### Privacy and maintenance

- Add `whyline privacy status` showing exactly which files contain prompts, account metadata, model choices, and decisions.
- Add configurable prompt capture (`full`, `redacted`, `off`) and retention, plus `whyline gc`/`whyline purge-prompts`.
- Add a sanitized diagnostics bundle that excludes prompt text, tokens, home paths, and credentials by construction.
- Add a semantic merge helper for `.whyline/decisions.md`; detecting conflict markers is good, but resolving append-only concurrent entries should be easy and deterministic.

### Portability and UX

- Generate Bash/Zsh/Fish/PowerShell completions from the argparse command tree.
- Add end-to-end PTY/TUI smoke tests, especially on Windows. Unit tests on `windows-latest` are valuable but do not verify terminal interaction, mouse behavior, process groups, or vendor CLI launching.
- Persist structured console transcripts per repository with an explicit privacy toggle; current `/history` is session-memory only even though prompt recall uses a file.
- Add `whyline context export/import` for a sanitized, user-approved handoff bundle across clones or machines. Keep operational state gitignored by default.
- Generate the README agent/capability matrix from the registry, and add a release test that fails when documented built-ins differ from registered built-ins.

### Measurement and quality

- Repeat the read-side and reviewer-recording experiments on more than one project/operator. The current 43% automatic read rate is explicitly unreliable evidence for instruction-only handoff.
- Add property/fuzz tests around Markdown parsing, hostile fence content, malformed hook payloads, paths, and relay event decoding—the data crosses a prompt-injection boundary.
- Add an opt-in local effectiveness report: handoffs completed, decisions read, decisions superseded, conflicts found, and fallback frequency. Keep it local and source-free to preserve the no-telemetry promise.

## Suggested sequence

1. Correct the Gemini documentation and run a bounded Gemini adapter spike.
2. Introduce the capability registry and migrate the existing four agents without changing behavior.
3. Fix state-directory/cache fallback and separate authentication truth from plan-tier enrichment.
4. Add Gemini through the registry; then evaluate Cursor and Copilot with the same acceptance matrix.
5. Add decision supersession/verification plus `whyline audit`.
6. Establish the typed Relay protocol and version diagnostics.
7. Build streaming/cancellation and quota cooldowns on that protocol.
8. Add launch profiles, attachments, privacy controls, and sanitized context export.

## Acceptance bar for any new agent

A new agent should not be called “supported” until Whyline has verified:

- interactive launch with an initial prompt
- model selection behavior and argument ordering
- login detection without reading or exposing credentials
- console/headless response parsing and exit codes
- rate-limit, auth failure, timeout, cancellation, and empty-response behavior
- instruction-file loading and decision-record compliance
- safe unattended permissions, or an explicit prohibition on relay roles
- Windows/macOS/Linux availability claims that match actual tests
- brainstorm fallback and final-writer behavior
- documentation generated from the same registered capability data

This bar prevents “can invoke the binary” from being mistaken for end-to-end Whyline support.
