# whyline — v1 Design

**Date:** 2026-08-09
**Status:** Approved for planning
**Supersedes:** the v1 scope in `AgentDock PRD v4_0.md` §8.1 and Phase 0/Phase 1 in `IMPLEMENTATION_PLAN.md`
**Retains:** the PRD's product thesis, vendor constraints, security model, and failure discipline

## 1. Decisions fixed

Six decisions were open in PRD §16 and `PRD_REVIEW.md`. All are now closed.

| Decision | Resolution |
|---|---|
| Product name | **whyline.** Free on PyPI, npm, `whyline.dev`, `whyline.sh`. `github.com/whyline` is a dormant squat (User, 0 public repos, created 2024-12-16); the repo lives under the owner's account, with `whyline-dev`, `getwhyline`, `whyline-cli` free as orgs. Unblocks the naming gate open since PRD v2.0 §3.4. |
| Licence | **Apache-2.0.** Patent grant matters in a vendor-adjacent position, and most employers permit Apache-2.0 while banning GPL — which reaches more of the intended audience. |
| Portfolio or business | **Neither, exactly: a free tool to help fellow developers.** No paid tier, no hosted sync, no team product, no monetisation, ever. |
| Second adapter | **Dissolved.** v1 wraps no vendor CLI, so there is no adapter layer to choose for. |
| Ledger committed by default | **`decisions.md` is committed; `ledger.jsonl` is gitignored.** Keeps the PRD's durability promise — delete whyline and the reasoning survives as plain Markdown — without committing raw prompt text. |
| Phase 1 continuation metric | See §10. The PRD's handoff-based gate no longer applies. |

Two further decisions taken in this design:

| Decision | Resolution |
|---|---|
| Capture mechanism | Three layers: git as the spine, a Claude Code hook for mechanical facts, and agent self-report via `AGENTS.md` for reasoning. |
| Process model | **Exec, never supervise.** No PTY, no output capture, no adapter conformance suite. |

## 2. What whyline is

A CLI that records why code exists and hands that record to whichever agent works next.

```
$ whyline explain src/cache/redis_layer.py:14
```

returns the agent, the instruction, the decision, the rejected alternatives, and the merge — or says honestly that it does not know.

Two payoffs from one mechanism, read at two time horizons:

- **Now:** `whyline brief` gives the next agent what the last one concluded, so switching between Claude Code, Codex and Gemini does not restart from zero.
- **Later:** `whyline explain` answers why a line exists, months after the session that produced it.

## 3. What changed from PRD v4.0, and why

| | PRD v4.0 | whyline v1 |
|---|---|---|
| v1 features | 4 (ledger, memory, handoff, two adapters) | 1 mechanism serving 2 payoffs |
| Commands | 8 | 7 |
| Launches agents | Yes, supervised via PTY | Yes, by `exec` — hands over the terminal |
| Vendor adapters | 2 required, conformance suite | None |
| Worktrees, roles | In scope | Cut |
| Storage | JSONL + SQLite index | JSONL only |
| Context injection | 2,000-token budget, ranking, `memory` command | Cut — the agent queries instead |
| Validation | 2-week study, 10 recruits, 3 conditions | 2–3 day cooperation test (§5) |

The reasoning behind the cuts:

**Adapters and PTY supervision existed to make handoff work without the agent's cooperation** — wrap the process, capture the stream, parse a summary out. That is the expensive half of the PRD build and a permanent maintenance liability (PRD §6.1: "every adapter is a standing maintenance liability"). This was confirmed in the field: between the PRD being written and this design, the Codex CLI was uninstalled from the development machine entirely and Claude Code drifted from 2.1.173 to 2.1.226.

All three target CLIs already read `AGENTS.md`. Asking the agent to record its own decisions obtains the same artefact for a fraction of the cost, and it is the *only* way to capture rejected alternatives, which no amount of output parsing can recover.

**Supervision was never required to launch an agent.** The PRD's cost came from capturing output. Handing the terminal over with `exec` costs about twenty lines and cannot break when a vendor changes its output format.

**The context-injection machinery existed to push context into a launched agent.** Since the agent queries `whyline brief` itself, the token budget, relevance ranking, preview flow and `memory` command all leave v1 together.

**SQLite indexed 50,000 events.** A JSONL scan of that many events takes a few hundred milliseconds in Python, and a real repository will hold hundreds in its first months. The event format stays index-friendly so an index can be added later without migration.

## 4. Constraints retained from the PRD

These are not negotiable by scope.

- **No credential handling, ever** (PRD §6.1). whyline never reads, stores, forwards, refreshes or proxies a vendor token. Subscription access works because the vendor's own CLI does its own login; `run` passes the environment through to `exec` unchanged and inspects nothing.
- **Never spoof a vendor harness.**
- **Permission-bypass flags are never added by default** (PRD §12.1).
- **Contexts cannot be shared across vendors** (PRD §6.2). Switching agents is a relay carrying a written brief, never a continued conversation. Documentation must say this plainly rather than implying seamless switching.
- **Git is authoritative; the ledger is advisory** (PRD §9.4). whyline state never overrides repository state.
- **Injected content is fenced and labelled as untrusted** (PRD §12.1), since briefs derive from repository files and agent output.

## 5. M0 — the cooperation test (do this before writing anything else)

The entire design rests on one unproven assumption: **that agents reliably obey an `AGENTS.md` instruction to record their decisions.** If they do, both payoffs work cheaply. If they do not, both are hollow. This replaces the blocked Phase 0.

**Prerequisite — met 2026-08-09.** Claude Code 2.1.226 and Codex CLI 0.147.0 are installed, and `codex login status` reports "Logged in using ChatGPT", so subscription auth works without an API key. Gemini CLI 0.54.4 is installed but **unusable on a free personal account**: Google sign-in now fails with "This client is no longer supported for Gemini Code Assist for individuals", leaving only a paid API key or Vertex AI. Gemini is therefore excluded from v1; Claude Code and Codex are the two agents.

**Method**

1. Add the recording instruction to `AGENTS.md` in 2–3 active repositories (Mozhima, Duet, DocSift).
2. Install a ~10-line probe script that appends a timestamped line to a local log. No whyline code required.
3. Work normally for 2–3 days across Claude Code and Codex.
4. Count non-trivial changes from `git log` by hand, and compare against probe firings.

**Recorded per firing:** whether it fired unprompted, whether the note matched what actually changed, and whether rejected alternatives were included or only the decision.

**Thresholds, fixed before collection**

| Result | Decision |
|---|---|
| ≥60% on Claude Code and at least one firing on Codex | Build as designed |
| 30–60% | Build, but treat self-report as best-effort: `explain` leans on the hook, and `brief` warns when thin |
| <30% | Cooperation model fails. Fall back to hook-only mechanical provenance, drop `brief` and `run` |

**Threat to validity:** the operator knows the instruction exists and may unconsciously prompt for it. Record any firing that followed a reminder separately, and judge the threshold on unprompted firings only.

## 6. Architecture

### 6.1 Storage

```
.whyline/
  decisions.md    committed    append-only Markdown; the durable artefact
  ledger.jsonl    gitignored   append-only events; contains prompt text
```

`whyline init` writes the gitignore entries. `decisions.md` is readable and useful with whyline deleted, which is the point.

### 6.2 Event schema

One JSON object per line, `{"v": 1, "id": ..., "ts": ..., "type": ...}` plus type-specific fields. Appends are single atomic writes in `O_APPEND` mode.

| Type | Source | Fields |
|---|---|---|
| `SessionStarted` | hook | `session`, `agent`, `agent_version` |
| `Instruction` | hook | `session`, `text` — local only, never committed |
| `FileTouched` | hook | `session`, `path`, `tool` |
| `Note` | `whyline note` | `decision`, `because`, `alternatives[{option, why_not}]`, `files[]`, `session?` |
| `SessionEnded` | hook | `session`, `status` |

Every `Note` also appends a Markdown entry to `decisions.md`. Dropped from PRD §9.6: `TaskCreated`, `HandoffCreated`, `ReviewRequested`, `ReviewCompleted`, `MergeCompleted`.

### 6.3 The three capture layers

**Git is the spine.** `explain` resolves a line through `git blame -L n,n` to a commit SHA, author and date. This works on any repository with history before whyline has recorded anything.

**Hooks record mechanical facts.** Installed by `init` into project-level `.claude/settings.json`. Three hard constraints: the hook runs in the critical path of every tool call, so it must be fast; it must **never** fail the user's session — all errors swallowed, always exit 0; and it must be silent. Requires no discipline from the user.

Verified 2026-08-09: **all three target CLIs support hooks**, not just Claude Code. Gemini CLI ships `gemini hooks migrate`, which migrates hooks *from* Claude Code and so implies a compatible format; Codex exposes a hook trust system (`--dangerously-bypass-hook-trust`). The mechanical layer is therefore portable in principle, which reduces the design's dependence on the self-report cooperation assumption (§5). v1 implements and tests the Claude Code hook only; the others are follow-on work once the format differences are characterised.

**`init` must merge, never overwrite.** The development machine already has global Claude Code hooks configured (`PostToolUse`, `SessionStart`) from another tool. Clobbering a user's existing hook configuration is unacceptable: `init` reads the current config, appends whyline's entries alongside whatever is present, and refuses with a clear message rather than guessing if the file is unparseable.

**The agent records reasoning.** `init` offers to append an `AGENTS.md` instruction directing agents to call `whyline note` on non-obvious choices. This is the only layer that captures rejected alternatives, and the only one that depends on cooperation. It is also the manual fallback for the user.

### 6.4 Linking notes to commits

No git hook and no recorded SHAs. `explain` resolves lazily: `git blame` yields the commit and its timestamp; candidate `Note` events are those referencing the same path with a timestamp between that commit and the previous commit touching the path.

This is deliberately SHA-free at record time, so rebases, squashes and amends that rewrite history do not invalidate the ledger — a property a SHA-recording design would lose.

### 6.5 Commands

| Command | Purpose |
|---|---|
| `whyline init` | Scaffold `.whyline/`, write gitignore entries, offer to install the hook, offer to append the `AGENTS.md` instruction |
| `whyline note "<decision>" --because "<rationale>" --rejected "<option>: <why not>"` | Record a decision. `--rejected` is repeatable, once per alternative; the text is split on the first colon into `option` and `why_not` |
| `whyline brief` | Compose the handoff summary from recent notes; prints to stdout |
| `whyline run <agent> "<task>"` | `exec` claude/codex/gemini with the brief attached |
| `whyline explain <file>[:line]` | Why this code exists. `--json` |
| `whyline timeline [--file] [--since]` | Event history. `--json` |
| `whyline status` | Hook installed, event count, anything broken. `--json` |

`AGENTS.md` never rewritten without explicit confirmation (PRD §9.1). `brief` prints rather than persisting, so there is no stale file to trust.

### 6.6 `run` — exec, not supervise

`run` composes the brief, then replaces itself with the target CLI via `os.execvp`. The terminal belongs to the agent. Nothing is captured, parsed or stripped. Environment is passed through unmodified; no permission-bypass flags are added. If the binary is missing, it fails with a clear message and a non-zero exit.

## 7. `explain` must be honest

PRD §14 lists "`explain` overpromises certainty" as a live risk, and early on the ledger will be nearly empty. Confidence is therefore a first-class output.

| Evidence | Confidence | Output |
|---|---|---|
| Exactly one `Note` for the path inside the blamed commit's window | **High** | Full answer: instruction, decision, alternatives, rejections |
| Several candidate notes, ambiguous window, or the line was moved by a later commit | **Medium** | Full answer, naming the moving commit and advising verification |
| Only mechanical events for the path | **Low** | Who and when, stated plainly as having no recorded reasoning |
| Nothing beyond git | — | Report `git blame` and say no reasoning is recorded |

Never infer a rationale that was not recorded. A tool that confidently explains code it knows nothing about is worse than no tool.

## 8. Failure behaviour

| Situation | Behaviour |
|---|---|
| No `.whyline/` | Instruct the user to run `init`; exit 3 |
| Hook not installed | `status` flags it; `explain` still works off git and `decisions.md` |
| Torn final line from a crash mid-append | Skip it, warn once, continue |
| Untracked file, line past EOF, uncommitted line | Degrade to file-level and say so |
| `git` missing or not a repository | Clear message, no traceback |
| Target CLI missing in `run` | Clear message, non-zero exit, brief still printed |
| Two processes appending at once | Safe: `O_APPEND` single-write appends |

Exit codes: `0` success · `1` runtime error · `2` usage error · `3` not initialised.

## 9. Non-functional requirements

- Cold start under 200 ms for `status`, `explain`, `timeline`, `brief` (PRD §12.2).
- No network calls, no telemetry, all state local.
- macOS and Linux; Windows via WSL.
- Python 3.11+, standard library plus Rich; shipped via `uv`/`uvx`, never "pip install and hope".
- Test-driven. Phase 0's three synthetic fixtures (`cache_ttl`, `webhook_dedupe`, `config_reload`) are reused as `explain` test repositories, since they are already git repositories with known history.

## 10. Success metrics

Replacing the PRD's handoff-based gate.

- **Primary:** the owner runs `explain` unprompted at least weekly for four consecutive weeks on a real repository.
- **Secondary:** on three or more occasions, `explain` surfaced reasoning that had genuinely been forgotten.
- **Switching:** `brief` or `run` used at least twice weekly when moving between agents.
- **Falsifier:** if after four weeks fewer than ten notes exist, the capture layer has failed. Stop rather than polish — PRD §14: "If `explain` is not used weekly, the feature has failed regardless of ledger completeness."

## 11. Explicitly out of scope

Listed to prevent the scope re-inflation PRD §8.2 records happening once already. Each needs written evidence of demand plus a plan revision to re-enter.

PTY supervision and output capture · adapter conformance suite · worktree isolation and parallel collision detection · SQLite index · context-budget injection and the `memory` command · roles · review workflow · `merge` · cost tracking · session resume · TUI · knowledge graph · plugin SDK · compare mode.

Permanently out, per §1: hosted sync, team features, enterprise features, any paid tier.

## 12. Open questions

- Does Codex honour `AGENTS.md` as reliably as Claude Code? Answered by M0.
- Do the Codex and Gemini hook formats differ enough from Claude Code's to matter? Deferred until after v1; `gemini hooks migrate` suggests they are close.
- Should `run` support Gemini at all, given its free tier is closed? Currently excluded.
- Rename the working directory from `agentdock` to `whyline`? Cosmetic; deferred to the owner.
- Trademark search on "whyline" not performed. Low exposure for a free non-commercial tool, non-zero. Note: "Whyline" was a 2008 CMU research debugger answering "why did this happen?" — same field, long dormant, no commercial conflict.
- PyPI/npm availability was checked via registry 404s, which is a strong signal but not authoritative; PyPI also rejects names too similar to existing ones. Confirm by registering early.

## 13. Requirements trace against PRD v4.0

| PRD area | Disposition |
|---|---|
| F1 project memory | Partial — `decisions.md` retained; injection machinery cut (§3) |
| F2 structured handoff | Delivered by a different mechanism — `brief` via self-report, not session scraping |
| F3 provenance ledger | Delivered — the core of v1 |
| F4 isolation and failure | Failure model retained (§8); worktree isolation cut |
| F5 roles | Cut |
| F6 event ledger | Delivered, reduced to five event types (§6.2) |
| F0 adapters | Cut entirely; replaced by `exec` (§6.6) |
| Eight CLI commands | Seven, with `run` redefined and `memory`/`merge` removed |
| §6.1 vendor constraints | Fully retained (§4) |
| §12.1 security | Retained; redaction hook unnecessary since `ledger.jsonl` is not committed |
| §12.2 performance | Retained, minus the 50,000-event index target |
