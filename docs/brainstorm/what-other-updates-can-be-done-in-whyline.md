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

# Independent Research & Brainstorm: Recommended Updates for Whyline
**Contributor:** Antigravity (Google DeepMind Agent)  
**Date:** 2026-09-29  
**Status:** Independent Pass (Pass Zero — Multi-Model Brainstorm)  
**Target:** Whyline Architecture & Roadmap

---

## 1. Executive Summary & Antigravity Perspective

Whyline solves one of the most critical friction points in contemporary AI-assisted software engineering: **preventing multi-agent amnesia without introducing bloated orchestration or vendor lock-in**. By keeping a durable, git-blamed decision log (`decisions.md`) and a lightweight, token-bounded active handoff packet (`whyline sync`), Whyline allows developers to pair different AI coding agents (Claude Code, Codex, Antigravity, Grok) on their existing subscriptions with zero credential forwarding and zero per-token markup.

Recent releases (0.3.16 through 0.3.18) made significant strides by bundling the TUI/console, introducing multi-agent brainstorming (`/brainstorm`), adding repository switching (`/repo`), and establishing basic account/model detection.

However, real-world development sessions reveal several key friction points:
1. **Sandbox & Permission Fragility:** Commands like `whyline account detect` fail hard when run inside sandboxed agent environments (e.g. Codex, Antigravity, Docker, restricted subagents) because they insist on writing to `~/.whyline/account.json`.
2. **Quota / Session-Limit Abruptness:** When an agent hits an hourly or 5-hour session limit (e.g., Anthropic's *"You've hit your session limit · resets 4:30pm"* or OpenAI's usage caps), the developer or relay hits a brick wall. Whyline does not currently detect, track, or smoothly hand off across session resets.
3. **Static Agent Architecture:** Adding new models or agent backends (Cursor CLI, Aider, OpenCode/Goose, local Ollama/vLLM endpoints) requires manual code changes across hardcoded dictionaries in `runner.py`, `account.py`, and `cli.py`.
4. **The 43% Compliance Barrier:** Historical measurements showed unprompted CLI `whyline brief` compliance was only 43%, and reviewer decision capture lagged significantly behind implementers.
5. **Console & TUI Ergonomics:** Command mode vs. Chat mode confusion, lack of command autocompletion, and missing global configuration defaults.

This document presents an independent, exhaustive blueprint of updates for Whyline across six functional pillars:
- **Pillar 1:** Critical Reliability & Sandbox Resilience
- **Pillar 2:** Session-Limit & Quota-Aware Auto-Handoff
- **Pillar 3:** Pluggable Agent & Model Architecture ("Adding More Models")
- **Pillar 4:** First-Class Antigravity Parity & Agent Customizations
- **Pillar 5:** Closing the Compliance Gap via MCP & Proactive Extraction
- **Pillar 6:** Next-Gen Decision Intelligence (`whyline explain` 2.0 & ADRs)

---

## 2. Pillar 1: Critical Reliability & Sandbox Resilience

### 1.1 Graceful Sandbox Degradation for Account Detection
* **The Problem:** In sandboxed agent environments (Codex, Antigravity subagents, containerized CI), writing to paths outside the repository root (specifically `~/.whyline/account.json` via `save_global`) triggers an unhandled `OSError` (`PermissionError`). This completely breaks `whyline account detect`, causing the agent to abort with an error directing the user to run it in a normal terminal.
* **Proposed Update:**
  1. **Safe Fallback in `account.save_global()`:** Wrap the write operation in a try/except for `OSError`. If `~/.whyline` is unwritable, fall back automatically to the repo-local `.whyline/account.json` and output an informational warning to `stderr`:
     ```text
     warning: ~/.whyline/account.json is read-only (sandbox detected); cached account status locally in .whyline/account.json.
     ```
  2. **Explicit Flags:** Add `--repo-only` / `--local` and `--dry-run` to `whyline account detect` so agents running in automated pipelines or sandbox tiers can safely refresh status without attempting global filesystem writes.
  3. **In-Memory Cache Fallback:** If even the repo-local file is somehow constrained, return the detected dictionary in-memory so the current command execution never crashes.

### 1.2 Defensive File Locking Across Platforms
* Build upon the recent Windows file lock refactor (`state.py`) by adding lock timeouts and stale PID detection. If a prior agent crashed mid-write leaving `.lock` files behind, provide an automatic recovery mechanism after a 10-second threshold without requiring manual user intervention.

---

## 3. Pillar 2: Session-Limit & Quota-Aware Smart Handoff

In modern AI agent usage, **session limits and rate limits are the #1 cause of workflow interruption**. When an agent runs out of quota, the user must manually notice the error, open another terminal, summarize the state, and restart with a different agent. Whyline is uniquely positioned to solve this.

### 2.1 Quota & Session-Limit Pattern Recognition
Vendors emit distinct, predictable strings when session limits or rate limits are reached:
* **Claude Code:** `"You've hit your session limit · resets <time>"`, `"Usage limit reached"`, `"429 Too Many Requests"`
* **Codex:** `"Rate limit exceeded"`, `"You have reached your current usage limit"`, `"quota exceeded"`
* **Antigravity:** `"RESOURCE_EXHAUSTED"`, `"Quota exceeded for quota metric"`, `"rate limit reached"`
* **Grok:** `"Rate limit hit"`, `"Credits exhausted"`

### 2.2 Automated "Limit Handoff" Protocol
When `whyline run <agent>` or the console chat adapter detects a session limit:
1. **Automatic Handoff Snapshot:** Whyline immediately captures the uncommitted working tree diff, the last prompt, and the failure message into an active handoff:
   ```bash
   whyline handoff <task-id> \
     --from claude --to codex \
     --status paused-session-limit \
     --summary "Claude hit session limit (resets 4:30pm). Handoff to continue implementation." \
     --risk "Context window transition mid-task"
   ```
2. **Quota Cooldown State Tracker (`.whyline/quota-status.json`):**
   Record the cooldown timestamp (e.g. `{"claude": {"limited_until": "2026-09-29T16:30:00+05:30"}}`).
   - In `/model` and `agent_status()`, display: `claude ✗ rate-limited (resets in 42m)`.
   - Prevent the console or relay from dispatching to an agent currently under active quota restriction.
3. **One-Click Failover Prompt:**
   In console or terminal:
   ```text
   ⚠ Claude reached its session limit (resets 4:30pm).
   Available agents ready:
     [1] Antigravity (gemini-2.5-pro)
     [2] Codex (o3-mini)
   Switch to Antigravity and continue task? [Y/n]:
   ```

---

## 4. Pillar 3: Pluggable Agent & Model Architecture

The user specifically asked: *"In brainstorming, how can I add more models?"*  
Currently, models and agents are constrained by two bottlenecks:
1. Agent CLIs are hardcoded in `runner.py`'s `AGENTS` and `MODEL_FLAG`.
2. Model selections in `whyline model set <agent> <model>` accept arbitrary strings with zero discovery, validation, or autocompletion.

### 4.1 Declarative Agent Registry (`agents.toml`)
Instead of hardcoding agents in Python source code, introduce an extensible registry. Whyline ships built-in defaults but allows user/repo overrides in `.whyline/agents.toml` or `~/.whyline/agents.toml`:

```toml
[agents.claude]
binary = "claude"
model_flag = "--model"
login_command = ["claude", "auth", "login"]
auth_type = "cli"
prompt_mode = "arg"

[agents.antigravity]
binary = "agy"
args = ["-i"]
model_flag = "--model"
auth_type = "path_or_config"
prompt_mode = "arg"

[agents.cursor]
binary = "cursor"
args = ["agent"]
model_flag = "--model"
prompt_mode = "arg"

[agents.aider]
binary = "aider"
model_flag = "--model"
prompt_mode = "arg"

[agents.local_ollama]
binary = "llm"
args = ["-m"]
model_flag = "-m"
prompt_mode = "arg"
```

This transforms Whyline from a 4-agent fixed launcher into a universal AI coding harness supporting **Cursor CLI, Aider, OpenCode/Goose, GitHub Copilot CLI, and local Ollama/vLLM runners**.

### 4.2 Dynamic Model Discovery & Soft-Validation Catalog
To replace blind string entry with an intuitive experience:
1. **Provider Querying / Listing:**
   - **Antigravity:** Invoke `agy models` (or read cached models) to enumerate available models (`gemini-2.5-pro`, `gemini-2.5-flash`, etc.).
   - **Claude:** Catalog canonical aliases (`opus`, `sonnet`, `haiku`, `claude-3-7-sonnet`, `claude-3-5-sonnet-latest`).
   - **Codex:** Catalog common models (`o3-mini`, `o1`, `gpt-4o`, `gpt-4.5-preview`).
   - **Grok:** Catalog `grok-2`, `grok-beta`, `grok-code`.
2. **Interactive Selection in TUI & CLI:**
   - In the TUI `/model` modal and CLI `whyline model`: Provide an interactive searchable picker of known models plus a `[Custom...]` option.
   - Soft-Validation: If a user specifies an unrecognized model string, display a gentle warning rather than an error:
     ```text
     Note: 'gpt-4-turbo' is not in Codex's known alias list. Using as typed.
     ```
3. **Global Defaults (`/default` & `~/.whyline/model.json`):**
   - Allow setting global fallback models per agent so users do not have to re-run `whyline model set` in every new Git repository clone.

---

## 5. Pillar 4: First-Class Antigravity Parity

As Google's Antigravity (`agy`), the agent has unique strengths: multi-turn reasoning, native skill loading, subagent delegation, and deep IDE workspace integration. Currently in Whyline, Antigravity has several rough edges that should be polished:

1. **Non-Interactive Auth Detection for Antigravity:**
   - Currently, `account.py` marks Antigravity as `"installed (login not checked)"` because `agy` lacks a simple auth status subcommand.
   - *Fix:* Inspect `~/.gemini/` configuration, environment credentials (`GEMINI_API_KEY` / Google Cloud ADC), or run a lightweight validation probe to report real authentication state.
2. **Antigravity Rule & Hook Installation:**
   - When running `whyline init`, Whyline installs `.claude/settings.json` and `.codex/hooks.json`, but does not configure Antigravity workspace rules.
   - *Fix:* Have `whyline init` populate `.gemini/rules/whyline.md` or Antigravity workspace instructions with the canonical `whyline sync` and `whyline note` directives.
3. **First-Class Relay Integration:**
   - The README currently notes: *"Antigravity is safe for whyline run, but not currently safe for unattended whyline-relay role without the generic-adapter recipe"*.
   - *Fix:* Bring native headless execution flags for `agy` into `whyline-relay` so Antigravity can act as a first-class Implementer, Tester, or Reviewer alongside Claude and Codex.

---

## 6. Pillar 5: Closing the 43% Compliance Gap via MCP & Proactive Extraction

The 43% read-side compliance rate observed during initial benchmarking is the single greatest bottleneck in manual multi-agent handoffs. An instruction in `AGENTS.md` is often skipped when an agent receives a direct user prompt.

### 6.1 Native Model Context Protocol (MCP) Server (`whyline mcp`)
The industry has converged on the **Model Context Protocol (MCP)**. Claude Code, Antigravity, Cursor, Windsurf, Zed, and Claude Desktop all natively support MCP servers.

By implementing `whyline mcp` (a lightweight stdlib JSON-RPC server):
* Tools exposed:
  - `whyline_sync(task_id, files)`: Injects handoff and active decisions directly into agent context.
  - `whyline_note(decision, because, rejected, files)`: First-class structured tool for recording decisions.
  - `whyline_explain(target)`: Directly inspects why a line/file was created.
  - `whyline_handoff(...)`: Formats and records handoffs.
* **Why this is revolutionary:** When Whyline tools are exposed as native agent tool declarations, agent compliance jumps from **43% to ~100%**, because models are trained to proactively invoke relevant registered tools.

### 6.2 Proactive Decision Extraction & Drafting
Even when an agent forgets to run `whyline note`:
* **Diff Analysis on Commit:** A Git `post-commit` or hook script compares modified files against recent notes.
* If a 50+ line diff introduces new architecture without a matching decision, Whyline prompts:
  ```text
  Whyline Notice: Significant changes detected in src/auth/jwt.py.
  Suggested note:
    whyline note "Implement JWT RS256 token verification" \
      --because "Decouple auth service from database lookups" \
      --rejected "symmetric HS256: secret sharing risk" \
      --file src/auth/jwt.py
  Record this decision? [Y/n/edit]:
  ```

---

## 7. Pillar 6: Next-Gen Decision Intelligence (`whyline explain` 2.0)

`whyline explain` is Whyline's signature feature: bridging `git blame` to developer rationale. Several enhancements can expand its depth:

### 7.1 AST & Symbol-Aware Explanation
* **The Problem:** Lines move. Code formatters (Black, Prettier, Ruff) rewrite lines, causing `git blame` on a line to point to a formatting commit rather than the architectural change.
* **Solution:** Support symbol-level explanation:
  ```bash
  whyline explain src/auth/session.py:SessionManager.validate_token
  ```
  Use `git log -L :<funcname>:<file>` or AST parsing to track the semantic lifetime of the function, ensuring decisions stick to the code even across reformatting.

### 7.2 Decision Search & Semantic Querying
* As projects grow, `decisions.md` accumulates hundreds of entries.
* Add `whyline search <query>` (e.g. `whyline search "cache TTL"` or `whyline query "why did we reject SQLite?"`).
* Implement via fast in-memory BM25 or keyword matching over parsed `decisions.md` blocks.

### 7.3 Architectural Decision Record (ADR) Export
* Add `whyline export --format adr --output docs/adr/` to export Whyline decisions into industry-standard MADR (Markdown Architectural Decision Records) or static HTML documentation for engineering team onboarding and compliance reviews.

### 7.4 Worktree Isolation for Multi-Agent Concurrency
* Running two agents in parallel in the same Git working tree leads to file conflicts and dirty state contamination.
* Provide `whyline worktree create <agent>` to automatically spin up temporary Git worktrees (`.whyline/worktrees/<agent>`), allowing concurrent agent tasks without risk of collision.

---

## 8. Console & TUI UX Enhancements

Based on real console feedback in 0.3.18:
1. **Unified Smart Input Bar & Route Suggestion:**
   - If a user types natural language (e.g. *"let's brainstorm caching options"*) while in **Command mode**, do not return an ugly `argparse` error. Instead, auto-detect conversational intent and show:
     ```text
     › "let's..." looks like a chat message. Press Tab to switch to Chat mode, or type /help.
     ```
2. **Slash Command Auto-Suggest:**
   - In Textual TUI and prompt_toolkit REPL, trigger a floating completion popup when `/` is typed, showing descriptions and syntax for `/model`, `/repo`, `/brainstorm`, `/handoff`, etc.
3. **Diff Previews in Transcript:**
   - Render syntax-highlighted diffs inside the TUI log when agents touch files or when viewing `/handoff`.

---

## 9. Phased Implementation Roadmap

| Phase | Title | Scope & Key Deliverables |
|---|---|---|
| **Phase 1** | **Sandbox & Quota Resilience** | Fallback for `account.save_global` on read-only `~/.whyline`; rate-limit string detection; automated limit-handoff. |
| **Phase 2** | **Pluggable Agent Registry** | Extract `AGENTS` and `MODEL_FLAG` to extensible `agents.toml`; dynamic model listing (`agy models`, Claude aliases); `/default` global models. |
| **Phase 3** | **Antigravity Parity & Workspace Rules** | Antigravity auth detection; `whyline init` support for `.gemini/rules/`; first-class headless relay support. |
| **Phase 4** | **Whyline MCP Server** | Implement `whyline mcp` stdlib JSON-RPC server exposing `sync`, `note`, `explain`, and `handoff` tools. |
| **Phase 5** | **Decision Intelligence 2.0** | AST/Symbol-level `explain`; `whyline search` keyword retrieval; ADR export generator. |
| **Phase 6** | **Console Autocompletion & Worktree Isolation** | TUI slash-command autocomplete; smart mode routing; isolated Git worktrees per agent. |

---

## 10. Conclusion

Whyline has already proven its core premise: cross-agent coordination without shared memory or credential theft is both possible and practical. By addressing sandbox constraints, automating session-limit handoffs, generalizing the model/agent registry, and bridging to modern agent protocols via MCP, Whyline will transition from a helpful CLI utility to the foundational control plane for multi-agent software engineering.

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
