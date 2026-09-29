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
