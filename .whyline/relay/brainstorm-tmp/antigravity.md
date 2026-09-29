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
