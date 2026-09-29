# Brainstorm: What other updates can be done in Whyline

## Codex

# Revised Codex view after the combined review

## Bottom line

The other passes changed my priorities. My independent pass leaned too far toward expanding the agent surface and too readily treated current vendor features as a reason to add more adapters. The combined evidence points somewhere more useful: Whyline should first make its existing handoff packet relevant, make its console cancellation real, survive restricted environments, and ensure its public claims match its code.

The next milestone should be **trustworthy context transfer**, not “support every agent.” A small internal agent registry and one explicit decision-supersession link are worthwhile foundations, but user-loaded plugins, model catalogs, MCP, automatic quota parsing, AST attribution, and worktree management should wait for evidence that the simpler mechanisms are insufficient.

## What the combined review establishes

Several findings are independently visible in the current tree or in this review session:

- `whyline sync` emitted 25 ownership claims before decisions, then omitted one of only three task-relevant decisions under its 1,200-token budget.
- The active FC-3 handoff recorded commit `eadabbc`, while the current checkout is at `0c0f26f`; the packet prints both values without interpreting the divergence.
- `handoff.create` replaces the active handoff but does not release the originating ownership claim, so completed task-only claims accumulate indefinitely.
- `account.save_global` writes directly to `~/.whyline/account.json`; a successful probe can become unusable when that location is unwritable.
- TUI Stop invalidates a result token and cancels a Textual worker, but its own code states that the underlying blocking operation continues.
- Agent facts are duplicated across runner, account, REPL/TUI, and brainstorm code.
- The README says Whyline does not orchestrate and never reads a vendor token, while the package now exposes Relay orchestration and Codex plan detection decodes the local ID-token payload.

These are not speculative feature requests. They are product-contract failures a user can encounter today.

## Priority 0: make current behavior dependable

### 1. Make `sync` spend its budget on the next decision

Relevant decisions are the scarce, durable information; old advisory claims are not. Change packet composition so it:

1. reserves space for the handoff, Git state, and the highest-ranked decisions;
2. shows ownership claims matching the active task, explicitly requested files, or dirty paths;
3. summarizes unrelated claims as a count instead of listing them;
4. preserves overlap warnings when the overlap touches the active scope;
5. says when the recorded handoff commit differs from HEAD, ideally with ahead/behind counts.

On handoff completion or transfer, release the handing-off actor’s matching task claim. Keep explicit `ownership release` for exceptional cases, and add a `status` warning for old unrelated claims rather than inventing a lock service or automatic time-based expiry.

Acceptance criterion: this repository’s current packet includes all three FC-3 decisions within the default budget and does not enumerate finished unrelated task-only claims.

### 2. Make account detection useful when global state is unwritable

Detection and persistence should have separate outcomes. `account detect` should still return and display fresh results if saving globally fails. Add an explicit repo-scoped mode and report where, if anywhere, the result was cached.

A conservative resolution order is:

1. explicit `WHYLINE_HOME` or platform state directory;
2. the existing global Whyline directory;
3. repo-local confirmation when the user requested it;
4. in-memory results for the current command.

Do not silently treat a write failure as “no agents available.” Do not scrape new vendors’ private auth files as the general solution; prefer documented status commands, and describe the existing Codex ID-token claim read honestly if it remains.

### 3. Make Stop terminate work, not only hide its result

A Stop button must stop the process consuming time and quota. Supervised console and Relay operations should run in a child process group with a cancellation handle. Stop should send a graceful termination, wait briefly, then escalate if necessary. It should preserve any already-written Relay state and still discard late UI events.

This does not require changing `whyline run`: its exec-and-get-out-of-the-way contract remains valuable. The supervision boundary belongs only to the console/brainstorm/Relay paths that already promise a Stop control.

### 4. Correct documentation against executable behavior

Reconcile the README and console design documents with the shipped product:

- distinguish the non-orchestrating decision-record core from the opt-in Relay surface that does orchestrate and assign roles;
- replace “never reads a vendor token” with the exact Codex behavior, or replace that behavior with a documented CLI status probe;
- report Codex hook capture from observed status rather than carrying a stale blanket claim;
- keep Windows labelled unverified until a real Windows run passes;
- reconcile the permanent plain-menu fallback, deferred attachments, and TUI copy behavior across the console specs;
- remove or revalidate claims about vendor products instead of encoding market conclusions in `runner.py` comments.

Documentation consistency deserves a release check because Whyline’s central promise is honest provenance.

## Priority 1: improve the read and record loop

### 5. Inject context where a documented session hook permits it

The 43% Claude read-side result shows that an instruction to run `sync` is not enough. The most direct experiment is to have Claude’s project `SessionStart` hook return the existing nonce-fenced sync packet on startup, resume, and compaction, while retaining the ledger event and the “never fail the session” contract.

This should be a bounded, measured change:

- verify the exact installed Claude hook contract before implementation;
- inject only on session-boundary events, not every prompt or tool call;
- record latency and token cost;
- compare read/use behavior before and after;
- make no equivalent claim for Codex or another agent until its own hook contract is verified.

MCP is not the default answer. Registering tools does not prove agents will call them, and it creates another installation and compatibility surface. Reconsider it only after an A/B test against session injection or for a vendor with no usable session-context hook.

### 6. Let reviewers target the repository they reviewed

Add `--repo <path>` to `note` and `handoff`. A reviewer operating from another checkout otherwise writes to the wrong repository or records nothing because that project’s instructions are absent.

This is small and directly testable: review a target checkout while the process CWD is elsewhere, then assert that only the target’s `.whyline/decisions.md` and handoff state changed.

### 7. Show related notes without overstating attribution

For a dirty line, `explain` correctly cannot claim commit-level provenance, but hiding all notes that name the file is too austere. Add a clearly separate “related, not attributed” block showing the count and latest file-level decisions. Use the same treatment when note timestamps cannot establish a blame-window link.

Confidence must remain `none` or `low`. Do not promote a file-level or symbol-name match to causal attribution.

### 8. Add minimal decision supersession

Keep `decisions.md` append-only, but allow a new note to carry `supersedes: <event-id>`. `brief` and `explain` should prefer the active note, mention the replaced ID, and retain the old entry for history.

Start with that single relation. A larger status/verification/audit system should follow only if real ledgers show recurring ambiguity that supersession does not solve.

## Priority 2: reduce maintenance cost without opening a plugin platform

### 9. Create one internal `AgentSpec`

Consolidate the existing built-ins into one source of truth containing:

- stable ID, label, binary, argv prefix, and model flag;
- login command and detection method;
- supported surfaces: run, chat, brainstorm, Relay;
- hook installer/capture confidence;
- whether “available” means authenticated or merely present on PATH.

Derive CLI choices, status rows, login hints, and brainstorm labels from it. Keep the registry package-internal first. Adding arbitrary TOML/Python adapters would introduce command-execution, credential, permission, and compatibility policy before the built-in contract is stable.

A new built-in agent should require one record plus adapter-specific tests, but “can invoke a binary” must not be called full support. Authentication truth, cancellation, instruction loading, headless behavior, and unattended permissions must all be explicit.

### 10. Add global model defaults, not a drifting model catalog

Repo-scoped choices are useful, but `/repo` makes users reselect routine defaults. Add a gitignored global default per agent, overridden by the repo file.

Keep model strings vendor-owned and unvalidated unless a CLI exposes a reliable machine-readable listing. Do not ship hand-maintained aliases or warnings that will drift. Named launch profiles may become useful later, but only after effort, provider, and permission settings have stable cross-agent meanings.

### 11. Tighten privacy controls around the local ledger

The ledger stores raw prompts indefinitely. Add a small, explicit privacy surface:

- `whyline privacy status` listing each operational file and what it contains;
- prompt capture modes such as `full`, `redacted`, and `off`;
- age-based prompt cleanup that preserves committed decisions and structural events;
- a sanitized diagnostics export that excludes prompt text, credentials, and home paths.

This is a better near-term investment than persisting full chat transcripts by default.

## Ideas to defer or reject for now

| Idea | Current judgment |
|---|---|
| User-defined agent/plugin registry | Defer until the internal `AgentSpec` survives another built-in and has a security policy. |
| Gemini/Cursor/Copilot/local-model expansion | Evaluate one at a time only after the registry and acceptance matrix exist; do not let vendor freshness drive the roadmap. |
| Parsing “session limit” strings and auto-writing handoffs | Reject in core: brittle vendor-output supervision. Surface typed Relay pauses where available. |
| MCP as the compliance fix | Defer pending measured advantage over session-boundary injection. Never claim near-100% compliance without data. |
| AST/symbol-level high-confidence `explain` | Reject for attribution: a stable name is not stable behavior. An optional symbol hint may be low/medium-confidence metadata. |
| Worktree-per-agent automation | Keep outside Whyline until advisory ownership proves insufficient; Git already owns this workflow. |
| SQLite, BM25, semantic search, MADR export | Defer: current Markdown scale is within budget and is already human-readable/exportable. |
| Attachments and structured streaming everywhere | Defer until cancellation and a stable supervised-event boundary exist. |

## Recommended sequence

1. Rebudget `sync`, filter claims, release completed claims, and explain handoff/HEAD divergence.
2. Separate account detection from global persistence failure.
3. Implement real child-process cancellation for supervised surfaces.
4. Correct README/spec claims and add consistency checks.
5. Add `note --repo`, `handoff --repo`, and unattributed related notes in `explain`.
6. Run the bounded Claude SessionStart injection experiment.
7. Consolidate built-in agent metadata into `AgentSpec`.
8. Add `supersedes`, global model defaults, and ledger privacy controls.

That sequence strengthens Whyline’s core claim—reliable, honest cross-agent context—before expanding the number of agents or the amount of automation it owns.

## Antigravity

# Revised Antigravity view after combined review pass 1

## 1. Bottom line & revised perspective

Reviewing the independent findings from Codex and Grok against the live state of the repository has fundamentally reshaped my priorities. In Pass 0, my analysis over-indexed on expanding Whyline's footprint: introducing a generalized MCP server (`whyline mcp`), building an open user-facing plugin registry (`agents.toml`), scraping vendor CLI outputs for rate limits, and implementing AST/symbol-level blame tracing.

The combined evidence demonstrates that **Whyline's core value is trustworthy, bounded, zero-lock-in context transfer**. Adding speculative integration layers or secondary protocols before stabilizing current contracts weakens that value. Live verification on this checkout confirms the core issues:
- `whyline sync` burned its 1,200-token budget enumerating 25 stale, completed task claims, omitting a critical active decision for task FC-3.
- `account detect` crashes with an unhandled `PermissionError` in sandboxed agent environments where `~/.whyline/` is read-only.
- The TUI `Stop` button cancels the Textual worker and invalidates UI tokens, but leaves the underlying blocking agent process running in the background, consuming quota and compute.
- Core public documentation (README, console design specs) has drifted from actual code behavior regarding orchestration, Codex auth token reads, and platform support.

The revised roadmap prioritizes **core provenance integrity, sandbox resilience, genuine cancellation, and verified session hooks** over unvetted agent expansion.

## 2. What the combined review establishes

Cross-referencing the three independent passes and our live session context reveals several undeniable conclusions:

1. **Context budget starvation in `sync`:** `whyline sync` spent token budget printing 25 advisory ownership claims from long-completed tasks (WEM, ACG, UCF, RLV, MTU, WFX, FC) while omitting a relevant FC-3 decision. Handoff creation replaces the active handoff file but never releases the creator's task claim, leading to permanent claim accumulation.
2. **SessionStart hook beats MCP for compliance:** Claude Code's project `SessionStart` hook (`hookSpecificOutput.additionalContext`) natively injects context on startup, resume, and compact without model compliance risk or per-turn token re-billing. MCP adds another protocol surface that models must be prompted to call.
3. **Sandbox filesystem fragility:** `account.save_global()` writes unconditionally to `~/.whyline/account.json`. In sandboxed agent environments (Codex, Antigravity subagents, containerized CI), this throws an unhandled `PermissionError` and breaks `whyline account detect`.
4. **Supervised operations lack real cancellation:** In `tui.py`, `_stop()` invalidates a dispatch token and calls `worker.cancel()`, but Textual workers cannot interrupt blocking Python calls. Background agent processes continue running and burning quota.
5. **Exec-not-supervise remains non-negotiable:** Regex parsing of vendor CLI output for rate-limit strings (`"You've hit your session limit"`) is fragile across CLI releases and violates Whyline's boundary. Cancellation and Relay structured pauses solve the actual user pain.
6. **Duplicated agent metadata:** Agent tuples are copy-pasted across 7+ modules (`runner.py`, `account.py`, `cli.py`, `tui.py`, etc.). A single internal `AgentSpec` registry is needed before any external extensibility is considered.
7. **Attribution truth over speculative matching:** Symbol/AST matching cannot be claimed as high confidence because symbols retain names across semantic rewrites. Instead, `whyline explain` simply needs an unattributed "Related decisions on this file" block when lines are dirty or uncommitted.
8. **Documentation drift:** The README states Whyline "never orchestrates" and "never reads vendor tokens", but `whyline relay` orchestrates and `account.detect_codex` decodes the local `id_token` payload.

## 3. Priority 0: make current behavior dependable

### 1. Fix `sync` token budgeting and release completed claims
- **Rebalance budget:** Reserve token budget for active handoff status, Git state, and relevant decisions first. Filter claims so only those matching the active task or dirty paths are enumerated; summarize the rest as a count (e.g. `"22 completed/unrelated claims omitted"`).
- **Auto-release on handoff:** When `whyline handoff` completes, automatically release the actor's task-level ownership claim. Keep explicit `whyline ownership release` for manual cleanup, and add a warning in `whyline status` when old claims accumulate.
- **Handoff vs. HEAD divergence:** When the recorded handoff commit differs from Git HEAD (e.g. handoff at `eadabbc` vs. HEAD at `f6d83af`), explicitly print the commit divergence (ahead/behind counts) rather than silently printing two differing hashes.

### 2. Graceful sandbox degradation for account detection
- **Orderly persistence fallback:** Wrap `account.save_global()` in `try/except OSError`. If `~/.whyline/` is unwritable, fall back in order:
  1. Explicit path in `WHYLINE_HOME`
  2. Global default `~/.whyline/account.json`
  3. Local checkout `.whyline/account.json` (emitting a short notice to stderr)
  4. In-memory cache for the lifetime of the command
- **Safe detection flags:** Add `--local` and `--dry-run` to `whyline account detect`. A failure to write the global cache must never crash the command or falsely report that no agents are available.

### 3. Real process group termination for console Stop
- **Process group isolation:** Supervised console chat and Relay worker tasks must run in an isolated child process group (`os.setpgrp` / `preexec_fn=os.setsid`).
- **Escalating signal cancellation:** When the user clicks Stop or issues cancellation, Whyline must send `SIGTERM` to the process group, wait briefly (500ms), and escalate to `SIGKILL` if processes remain alive.
- **State preservation:** Preserve on-disk Relay state up to the cancellation point while discarding late UI events. Core `whyline run` retains its exec-and-exit contract.

### 4. Reconcile public documentation with executable reality
- **Orchestration honesty:** Update the README to clearly distinguish the un-orchestrated core decision-record from opt-in `whyline relay` orchestration.
- **Token reading disclosure:** Replace "never reads a vendor token" with an accurate description: Whyline decodes the local cached Codex `id_token` payload to inspect plan type and discards it without storing credentials; Claude uses CLI status.
- **Windows verification:** Keep Windows marked as unverified in the README and package classifiers until end-to-end Windows CI runs pass green.
- **Console specifications:** Reconcile console design docs to reflect that the plain CLI menu is the permanent zero-dependency fallback, and attachments are deferred.

## 4. Priority 1: improve the read and record loop

### 5. Claude SessionStart hook context injection
- **Bounded hook injection:** In `hook_entry.py`, on Claude's `SessionStart` event (`startup`, `resume`, `compact`), print the nonce-fenced `sync` packet via `hookSpecificOutput.additionalContext`.
- **Fail-safe contract:** Keep hook execution on `exit 0` always. If sync generation fails, log the ledger event and exit cleanly without breaking the user's session.
- **Measurement:** Measure read compliance and token consumption empirically. Leave the `AGENTS.md` instruction intact as defense-in-depth and for other agents. Defer MCP until hook injection is proven insufficient.

### 6. Cross-repository reviewer flags (`--repo <path>`)
- Add `--repo <path>` to `whyline note` and `whyline handoff`.
- Reviewers frequently operate from an external checkout or parent directory. Without `--repo`, notes are either written to the wrong repository or fail because `AGENTS.md` is missing from the reviewer's current directory.

### 7. Unattributed related decisions in `whyline explain`
- When inspecting an uncommitted/dirty line or a commit where notes postdate the commit window, `whyline explain` currently suppresses all discovered notes.
- Instead, render a clearly separated block:
  ```text
  Not attributed: Line is uncommitted (no git blame provenance)
  Recent decisions on this file:
    - [2026-09-28] "Approve the TUI shared-handler cutover..." (FC-3)
    - [2026-09-28] "Update legacy TUI button mock tests..." (FC-3)
  ```
- Keep confidence strictly at `none` or `low`. Do not promote these notes into causal Decision/Because/Rejected fields.

### 8. Minimal decision supersession (`supersedes: <event-id>`)
- Add an optional `--supersedes <event-id>` flag to `whyline note`, recorded as an explicit line in `decisions.md`.
- Keep the log append-only. When multiple notes match a blame window, `explain` prioritizes the active decision and notes that earlier event IDs were superseded, eliminating historical confusion without deleting history.

## 5. Priority 2: maintainability and ergonomics

### 9. Unified internal `AgentSpec` registry
- Consolidate agent metadata currently scattered across `runner.py`, `account.py`, `cli.py`, and `tui.py` into a single internal dataclass:
  - Agent identifier, display label, binary, argv prefix, model flag
  - Login command and detection mechanism (CLI status vs. token decode vs. PATH-only)
  - Supported execution surfaces (interactive run, chat, brainstorm, Relay)
  - Hook installer contract
- **Antigravity parity:**
  - Standardize `agy` invocation (`["agy", "-i"]`, `--model`).
  - Keep detection PATH-only until `agy` provides a non-interactive status command; do not scrape `~/.gemini/`.
  - Add Antigravity workspace rules installation (`.gemini/rules/whyline.md`) to `whyline init`.
  - Add headless relay support flags for Antigravity in `whyline relay`.

### 10. Global model defaults without catalog drift
- Support `~/.whyline/model.json` to provide user-level default models per agent, overridable by repo-local `.whyline/model.json`.
- Do not maintain a hardcoded model catalog or dynamic CLI queries (`agy models`). Keep model strings vendor-owned; invalid names fail fast at the vendor CLI boundary.

### 11. Local ledger privacy controls
- Add `whyline privacy status` detailing stored ledger files.
- Provide options to scrub prompt text in `.whyline/events.jsonl` while preserving structured decisions, handoffs, and audit hashes.

## 6. Ideas to defer or reject for now

| Proposal | Current judgment | Rationale |
|---|---|---|
| **Whyline MCP Server** | **Defer** | Adds protocol complexity without guaranteeing compliance. Claude `SessionStart` hook injection provides deterministic context delivery at session boundaries. |
| **Parsing vendor output for session limits** | **Reject** | Violates `exec-not-supervise`. Fragile across vendor CLI versions. Rely on process-group cancellation and structured Relay pause states. |
| **User-defined plugin registry (`agents.toml`)** | **Defer** | Premature before the internal `AgentSpec` is hardened. Introduces security, PTY, and auth liabilities. |
| **AST / Symbol-level blame attribution** | **Reject** | High confidence requires git blame window alignment. Symbols retain names across semantic rewrites. Unattributed file notes solve the dirty-line blind spot. |
| **In-Whyline Git worktree management** | **Reject** | Worktrees are Git's responsibility. Whyline provides advisory ownership warnings, not repository orchestration. |
| **SQLite / BM25 / Semantic decision search** | **Defer** | Current Markdown parsing takes ~159ms for 50,000 events. Committed Markdown is durable, portable, and human-readable. |
| **Scraping private vendor auth files (`~/.gemini/`)** | **Reject** | Rely on documented CLI status probes. The Codex ID-token read is an exception to narrow, not a pattern to copy. |

## 7. Recommended implementation sequence

1. **Rebalance `sync` budget:** Filter claims to active task/dirty scope, release claims on handoff, and report handoff/HEAD divergence.
2. **Harden sandbox account detection:** Implement fallback cascade for `account.save_global()`.
3. **Implement process group termination:** Give console `Stop` real `SIGTERM`/`SIGKILL` handles.
4. **Correct public documentation:** Align README, specs, and classifiers with shipped code behavior.
5. **Implement Claude SessionStart hook injection:** Automatically provide sync packet on startup, resume, and compact.
6. **Add cross-repo support:** Introduce `--repo <path>` on `note` and `handoff`.
7. **Surface unattributed notes in `explain`:** Display recent file notes when lines are uncommitted or dirty.
8. **Consolidate `AgentSpec` & add supersession:** Unify internal agent metadata and add `--supersedes <event-id>`.
9. **Add global model defaults & privacy controls:** Support `~/.whyline/model.json` and ledger sanitization.

## Grok

# What else Whyline should change

Independent pass. Read the current tree (`src/whyline`, README, the 0.1.3–0.3.18 instruction and console history, Claude Code's hook docs) and the `whyline sync` packet this session actually printed. No other model's notes.

Whyline's hard parts already work: committed `decisions.md`, nonce-fenced `sync`, exec-not-supervise `run`, honest confidence on `explain`, hooks that cannot fail a session. The updates below are the places that packet, the renderer, and the README currently lose information or say something the code no longer matches. They are ordered by how often a session hits them.

## 1. Sync spends its budget on finished claims

`whyline sync` on this checkout (active task FC-3, git `ed815049`, working tree clean) printed:

- 25 ownership claims, almost all task-only, for work that is already done (WEM, ACG, UCF, RLV, MTU, WFX, FC).
- One overlap warning, because UCF-1 is still claimed by both grok and antigravity.
- Then: "Omitted: 1 relevant decision due to the token budget" — 2 of 3 decisions for FC-3, out of 193 recorded.

`sync.compose` renders every claim before it decides which decisions fit in the 1,200-token budget (`src/whyline/sync.py`). Compact mode exists, but only after the non-compact render is already over budget, and even then it keeps five claims. Decisions are the section that gets shortened.

Claims never leave on their own. `handoff.create` replaces `active-handoff.json` and does not call `ownership.release`. `release` is a separate command agents do not run when they finish. Nothing expires `claimed_at`. Ownership is advisory and checkout-local, so keeping every historical claim in the hot file does not preserve history that matters — `decisions.md` does that. It only crowds the next agent.

The handoff record is also frozen at write time. FC-3's handoff `current` is `eadabbc`; git HEAD is `ed815049`. Both numbers are printed, and nothing says they differ.

Do this:

- In the default packet, list claims that match the active task or the dirty paths. Replace the rest with a count ("22 other claims, none on this task").
- Select decisions first. A claim for a finished task must not be the reason a relevant decision is omitted.
- When `handoff` is recorded for a task, release that actor's claim for it. Keep `release` for the explicit case.
- Add one line when handoff `current` is not HEAD: how many commits behind, not a second place the reader has to diff by eye.
- `whyline status` should say when the claim file is mostly stale, so a human can clear it. A checkout-local `release` of claims whose task is not the active handoff is safe; do not invent a lock manager.

## 2. Put sync in the session the hook already has

The read side was measured at 43% (Claude Code ran `brief` unprompted in 3 of 7 owned sessions, under the precommitted 50% bar). `m0/RESULTS.md` and `agentsmd.py` still say so, and the installed instruction still asks the agent to remember `whyline sync` before touching code. That wording is already imperative, exact, and pre-authorised. The miss is that it depends on the model complying.

`hook_entry.main` on `SessionStart` only appends a ledger event and prints nothing (`src/whyline/hook_entry.py`). Claude Code's current hook contract does the injection itself: a project `SessionStart` hook may print `hookSpecificOutput.additionalContext`, and Claude Code inserts it before the first prompt. The same event fires on resume and on compact, which is when a context window is rebuilt. Plain stdout is also treated as session context. Project settings (what `whyline init` already writes to `.claude/settings.json`) are the path that works; plugin-shipped SessionStart hooks have dropped `additionalContext` (anthropics/claude-code#16538), so do not move this into a plugin.

Shape:

- On Claude `SessionStart` only, print the existing fenced `sync` packet as `additionalContext`, and still append the ledger event.
- Keep every path on exit 0. If sync fails, print nothing and record the session anyway.
- Match `startup`, `resume`, and `compact`. Do not also inject on `PostToolUse` or every `UserPromptSubmit`; that re-bills the same packet on every tool call and puts the hook on the latency path it was written to stay off.
- Leave the AGENTS.md instruction in place. Injection covers Claude sessions that were opened directly. `whyline run` stays the path that attaches context for the other agents.

Do not claim the same stdout contract for Codex until it is checked against Codex's hook docs. `init` can keep installing the Codex recording hook. Codex read behaviour was never given a session denominator; this change does not invent one.

An MCP server (`whyline_sync`, `whyline_note`, …) is a second product. Agents call MCP tools only after someone configures the server, which is the same compliance problem as remembering a CLI. Revisit MCP only if a vendor documents that its tools are invoked more reliably than a SessionStart hook and that vendor is one Whyline already launches.

## 3. `explain` hides the notes it already found while the line is dirty

`resolve.explain` loads every note that names the file. For an uncommitted line it returns confidence `none` and reason "line is uncommitted, so it has no recorded provenance yet", with those notes still on the object. `render._attributed_notes` then drops them, on purpose: printing them under "Confidence: None" would say the line's reason is known and unknown at once (`src/whyline/render.py`).

That guard is right. The result is wrong for the moment explain is needed. Mid-task, the line is dirty, the decision was recorded minutes ago, and the command shows neither the decision nor a pointer to it.

Print a separate block that cannot be read as attribution:

```
Not attributed    line is uncommitted, so no decision is tied to it
On this file      4 decisions name src/whyline/console/tui.py
                  latest: "Approve the TUI shared-handler cutover …"
```

Same treatment when every note postdates the blamed commit, or when timestamps are unreadable. Confidence stays `none` or `low`. Do not promote those notes into the Decision/Because/Rejected fields.

Do not build AST or symbol identity for this. Blame-plus-time-window is the mechanism that stays honest across rebases, and HIGH is defined as one note inside one commit window. A symbol index would report HIGH across a reformat that kept the name and changed the behavior. If a note needs a stable handle, add an optional symbol string to `whyline note` and let `explain` say "a decision names this symbol" at MEDIUM at most.

`decisions.md` is 193 entries and the large-ledger budget is already met (~159 ms at 50,000 events, which is why there is no SQLite). A `whyline search` that scans the markdown is enough when someone asks. BM25, a documentation-site export, and MADR generation are not; the committed markdown is already the record a human can read with Whyline uninstalled.

## 4. Reviewers still have no target repository

`agentsmd.py` records three explanations for "implementers write decisions, reviewers do not." The 0.1.3 wording change addresses only the first, and the file says that change is an untested hypothesis. The second is structural: Tasks 13–14 were reviewed from a session rooted in a different repository, so the `AGENTS.md` in context was not the reviewed project's, and `whyline note` writes wherever `find_repo_root()` walks up from the cwd.

Add `whyline note --repo <path>` and the same flag on `handoff`, requiring a git checkout that has been initialised. Point the reviewer sentence in the instruction at that flag: a ruling made while sitting in another checkout is still recorded in the reviewed project's `decisions.md`. Then look at whether reviewer-voiced entries actually appear. Do not describe 0.1.3 as having closed the gap.

## 5. One agent table

The set {claude, codex, antigravity, grok} is copied across `runner.AGENTS`, `runner.MODEL_FLAG`, `account.AGENT_ORDER`, `account.BINARIES`, `account.LOGIN_COMMANDS`, `account._LOGIN_CHECKED`, `cli._print_account`, and `console.adapters.BRAINSTORM_LABELS`. Antigravity's argv is `["agy", "-i"]`; Grok's is `["grok"]`; both model flags are `--model`. Detection for the last two is PATH-only, by an explicit comment in `account.py`: available means installed, not signed in. `init` installs hooks only for Claude and Codex.

Fold those into one record: id, binary, argv prefix, model flag, login argv or "no login subcommand", detection kind, hook installer or none. A fifth agent should be a row and a test, not a sweep of the package.

Stop there. Do not add a user plugin file, and do not take on Aider, OpenCode, Goose, Copilot CLI, Ollama, or vLLM.

- `run` execs the vendor CLI so the subscription the user already has does the auth. A local model server is a new credential and billing story.
- `runner.py` refuses to supervise a PTY or parse vendor output, because that is what broke when a format changed. Most of those tools need one or the other.
- whyline-relay already has a generic adapter for a deliberate headless one-shot. Core Whyline does not need a second one.

Antigravity stays PATH-only until `agy` has a non-interactive status command comparable to `claude auth status`. Do not read `~/.gemini/` to guess. If Antigravity or Grok grow a documented project hook or rules file that accepts extra context, add that installer to the same table. Do not invent a rules path and hope the CLI loads it.

Model names stay unvalidated. `model.py` states that on purpose: a bad name fails when the vendor CLI starts, which is the failure the user can see. A picker that shells out to `agy models` or maintains an alias list (`sonnet`, `opus`) will drift, and a soft warning trains people to ignore it.

## 6. Stop has to stop the process that spends the quota

`tui._stop` bumps a dispatch token and calls `worker.cancel()`. Its own comment says the worker still runs to completion; Python cannot interrupt it; the console only drops the result when it returns. Relay start/resume goes through `run_relay_oneshot`, which calls `relay_cli.main` in-process. Stop on a relay run therefore hides the output and leaves the agents running.

Run chat turns and relay start/resume in a child process group, and have Stop send SIGTERM to that group (SIGKILL if it is still alive after a short grace). Discarding a late result is fine as a second step. It is not a substitute for killing the child.

Do not scan agent stderr for "session limit" or "resets at 4:30". That is vendor-output parsing, which this codebase has already rejected, and the strings will change. Relay already pauses on structured reasons and can fail over. Surface that pause in the console; do not add a parallel quota watcher or a `paused-session-limit` handoff status.

## 7. Make the public claims match the code

This project shipped 0.1.4 because the PyPI page overstated a measured rate. The same standard applies to the sentences below.

**Orchestration.** "What whyline does not do" still says Whyline does not orchestrate and does not assign roles. The same README documents `whyline relay` and the setup wizard, which run a plan and assign implementer, tester, and reviewer. Split the sentence: the decision record does not orchestrate; `whyline relay` does, and only when the user sets it up.

**Codex hooks.** The README still says no Codex hook event has been observed, so mechanical capture is untested. Re-check `whyline status` on a repo that has actually used Codex since that sentence was written, and replace it with what status reports. Leave it if it is still true.

**Windows.** `state.file_lock` is now `O_CREAT|O_EXCL` and the comment says POSIX and Windows. The README still says Windows is not verified. Classifiers list MacOS and POSIX Linux only. There is a 2026-09-29 Windows-fix plan in `docs/superpowers/plans/`. Update the README and the classifiers after a Windows run is green. Until then the README is the honest line and the lock comment is ahead of the evidence.

**Tokens.** The README says Whyline never reads a vendor token. `account.detect_claude` matches that: it runs `claude auth status` and keeps `subscriptionType`. `account.detect_codex` opens `~/.codex/auth.json` and base64-decodes the `id_token` payload to read `chatgpt_plan_type`. The token is not stored. It is read. Prefer a Codex CLI status command if one prints the plan. If the file read stays, say so in the README in one sentence: the Codex plan is derived from the local auth file's id-token claims, and the token is discarded. `detect_antigravity` / `detect_grok` should keep saying "installed", not "signed in".

**Console docs disagree with each other.** `docs/superpowers/specs/2026-09-28-whyline-unified-console-design.md` says the plain entry menu goes away at cutover, and its acceptance list still includes attachments. The final-cutover plan keeps the plain menu as the permanent zero-dependency fallback, and the foundation spec defers attachments indefinitely. `tui.py` also notes that RichLog in the pinned Textual has no text selection; copy is OSC 52. Reconcile those docs so the next implementation pass does not delete the fallback or start attachments to satisfy a stale acceptance line.

**Model layer.** Account data has a machine file and a repo file. Model choice is repo-only (`paths.model_path`). `/repo` switches checkouts and the model choice does not come along. A gitignored `~/.whyline/model.json` default, overridden by the repo file, matches account. No validation, as above.

## 8. A superseded decision should say so

`explain` already has the honest fallback: several notes in one commit window become MEDIUM ("the link is ambiguous"), and a later commit that moved the line becomes MEDIUM ("verify it still applies"). That second case is a feature when the old reasoning might still be true. It is noise when a later note replaced an earlier one and both name the same file.

Keep the log append-only. Add an optional `supersedes <event-id>` on `whyline note`, rendered as its own line in `decisions.md` so it is readable with no tool. When both notes fall in the window, `explain` shows the later one and one line that the earlier id was superseded. It does not delete the earlier entry, and it does not raise confidence above what the window earned.

## What not to build

| Idea | Why not |
|---|---|
| MCP server as the way to close the 43% gap | Claude's SessionStart hook already injects context for sessions `init` configures. MCP adds a server the agent must be taught to call. |
| Parsing vendor limit errors and auto-writing a handoff | Breaks the exec-not-supervise rule. Relay already pauses on its own structured reasons. |
| Plugin registry of arbitrary CLIs and local model servers | New auth and a PTY. The generic adapter belongs to whyline-relay, for a one-shot the user asked for. |
| Symbol/AST `explain` at HIGH confidence | A stable name is not a stable behavior. Blame window stays the definition of HIGH. |
| Worktree-per-agent inside Whyline | Ownership is a warning. Isolation is a workflow the user runs with git, not a second git Whyline operates. |
| SQLite, BM25, MADR export | The ledger budget is met. The markdown is the export. |
| Hard-coded model pickers | Spec M4: invalid names fail at the vendor CLI. |
| Scraping `~/.gemini/` or any other auth file for a new agent | Claude's status command is the pattern. Codex's id-token read is the exception to narrow, not the template to copy. |

## Order

1. Sync: claims filtered, decisions preferred, handoff-behind-HEAD called out, handoff releases the claim.
2. Claude SessionStart injects the fenced sync packet, including resume and compact.
3. `explain` shows file-level notes as unattributed when the line is dirty.
4. `note`/`handoff --repo` for a reviewer sitting in another checkout.
5. README and classifiers corrected against the code, including the Codex token sentence, after checking Codex hook status and Windows CI rather than ahead of them.
6. Console Stop signals the child process group.
7. One agent record. Supersedes field after that.

Items 1–4 are whyline itself and do not depend on whyline-relay. Item 6 does, because relay start is in-process today. Item 7 is maintenance so the next agent is not a fifth copy of the same tuple.
