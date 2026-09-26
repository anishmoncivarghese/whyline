# Terminal Chat Orchestrator Design

**Status:** Approved by user, section-by-section, 2026-09-26.

## Goal

Typing `whyline` with no arguments starts an interactive REPL where free text
goes to a default agent (the "orchestrator"), `/claude`/`/codex`/`/agy`/`/grok`
sends one message to a specific agent directly, and every agent shares one
conversation history — including across a full agentic turn (file edits,
commands, commits), not just Q&A.

## Non-goals

- **Content-based auto-routing.** The default agent is a fixed choice you set,
  not something that inspects your text and guesses. (Decision D3.)
- **A new, separate permission model for chat.** Chat reuses whatever
  permission floor whyline-relay's adapters/config already define for that
  agent in that repo — never a softer or harder set invented just for this
  feature. (Decision D5.)
- **Summarized shared memory.** History fed into each new turn's prompt is the
  verbatim, capped tail of the transcript — no compression/summarization pass.
  (Decision D4.)
- **A third shared-core package.** This is built inside whyline-relay, reusing
  its existing `adapters`/`agents.py`, not split into a new dependency both
  projects import. (Decision D2.)

## Decisions

- **D1 — Scope:** Chat supports full agentic turns (edits, commands, commits),
  not just Q&A. This is what makes shared permission-floor reuse from
  whyline-relay's adapters necessary in the first place.
- **D2 — Package home:** The REPL (`chat` command) lives in **whyline-relay**,
  directly reusing `adapters/` (claude.py, codex.py, generic.py, bypass.py)
  and `agents.py`'s subprocess supervisor. whyline itself stays a thin
  launcher: bare `whyline` execs into `whyline-relay chat` if whyline-relay is
  installed, else falls through to its normal help. No permission/bypass
  logic is duplicated into whyline.
- **D3 — Orchestrator routing:** A fixed default agent, chosen once during
  first-launch setup and changeable later via `/default <agent>`. No
  content-based routing.
- **D4 — Shared memory depth and persistence:** Full transcript, capped to a
  token budget per turn (same capping pattern as `whyline`'s `sync.compose`),
  persisted per-repo in `.whyline/relay/chat-history.jsonl` (JSONL, one record
  per turn), surviving REPL restarts.
- **D5 — Permission floor:** claude/codex always run with their existing
  managed defaults from `adapters/claude.py`/`codex.py` (safe even with no
  relay config in the repo). agy/grok (generic) are only usable in chat if the
  repo's `.whyline/relay/config.toml` already configures a command for them,
  per the existing README recipes — otherwise they're refused in chat with a
  pointer to `doctor` and the README, not given a separate weaker fallback.
- **D6 — Auto-commit:** Every agentic turn that leaves the working tree dirty
  is auto-committed (`git add -A && git commit`), mirroring whyline-relay's
  existing task-per-commit model. There is no separate human review step
  before the commit — the printed post-turn diff-stat is the review, after
  the fact. (Explicit user choice: relay's implementer/reviewer pairing does
  not exist for a live chat turn, and the alternative — leaving changes
  uncommitted — was rejected in favor of matching relay's existing pattern.)
- **D6a — Gitignore.** `.whyline/relay/.gitignore` already exists and lists
  the relay's own local, ephemeral state (`logs/`, `state.json`, `STOP`,
  `running.json`) — deliberately not `config.toml`, which is shared team
  config. `chat.json` (a personal default-agent preference) and
  `chat-history.jsonl` (personal conversation content, potentially including
  sensitive prompts) belong in that same local-only category. `init.py`'s
  existing gitignore-writing list gains `chat.json\nchat-history.jsonl\n`.
- **D7 — Setup wizard scope:** First launch detects which of claude/codex/
  agy/grok are actually installed (`shutil.which`), lets you pick a default
  from those, and saves the choice. It does not run whyline's own `account
  detect`/`model set` flows inline — those remain separate, existing commands
  chat doesn't duplicate or require.
- **D8 — Response extraction is real, not just log-teeing.** whyline-relay's
  existing `agents.run()` deliberately never parses output to decide
  anything — routing comes from `whyline handoff` records, and output is only
  teed to a log for a human watching a relay run. Chat's entire purpose is
  different: the captured response *is* the payload. `agents.run()` gains a
  `capture: bool` option to also buffer stdout; each `Adapter` gains two new
  fields: `extract_response: Callable[[str], str]`, parallel to the existing
  `diagnose` field, and `uses_output_file: bool` (true only for codex).
  - **claude:** `uses_output_file = False`. Its existing `--output-format
    json` default command already produces a JSON object whose `result`
    field is the exact final text (verified directly: `claude -p "reply with
    exactly the word: pong" --output-format json` returns
    `..."result":"pong"...`). No command change needed; `extract_response`
    parses captured stdout directly.
  - **codex:** `uses_output_file = True`. `-o <tempfile>`
    (`--output-last-message`, a real `codex exec` flag whose whole purpose is
    writing just the agent's final message to a file) needs a fresh path
    every turn, so it cannot live in the static `default_command` tuple the
    way claude's flags do. Instead, `chat.py`'s turn pipeline checks
    `adapter.uses_output_file` before running: if true, it creates a
    `tempfile.NamedTemporaryFile` path, appends `"-o"`, `str(path)` to the
    resolved command for this turn only, runs it, then reads that file's
    text (`""` if missing/empty) and passes that — not the captured stdout —
    to `extract_response`. Codex's own `extract_response` is then trivial:
    strip whitespace from what it's given; the file already contains only
    the final message, no envelope to parse.
  - **generic (agy/grok):** the two don't share a field name — verified
    directly: `grok --output-format json --permission-mode dontAsk -p "reply
    with exactly the word: pong"` returns `..."text":"pong"...`; `agy
    --output-format json --mode accept-edits --add-dir . --new-project -p
    "reply with exactly the word: pong"` returns
    `..."response":"pong\n"...`. Neither matches claude's `"result"`. Since
    "generic" is one shared `Adapter` object covering any binary a user
    configures, its `extract_response` tries a priority-ordered list of known
    field names against the parsed last JSON line —
    `("result", "response", "text", "message")` — and returns the first one
    present as a string. Covers both verified agents today and leaves room
    for a future generic tool using a common convention.
  - **Fallback, all adapters:** if extraction fails (malformed/unexpected
    output, or codex's temp file missing/empty), fall back to the existing
    `last_line_detail` heuristic every adapter's `diagnose` already uses,
    clearly labeled `(raw output, no structured result found)`.
- **D8a — `agents.run()`'s `echo` flag must split in two.** Today `echo`
  couples two things under one switch: printing the heartbeat ("... claude
  still running (30s)") and echoing every raw stdout line to the terminal
  live. Chat wants the first (so a slow turn still shows it's alive) but not
  the second (raw JSON/tool-call chatter dumped mid-chat would be confusing —
  the whole point of `extract_response` is to show one clean final answer
  instead). `agents.run()` gains the `capture: bool` parameter above; when
  true, it buffers every line into a string instead of writing it to
  `sys.stdout`, while the existing heartbeat behavior (still gated on `echo`)
  is unaffected. Relay's existing task-loop callers pass `capture=False`
  (today's behavior, unchanged); `chat.py` passes `capture=True, echo=True`
  (heartbeat on, raw echo off).
  `agents.run()`'s return type changes from a bare `int` exit code to a
  `RunResult(exit_code: int, output: str | None)` namedtuple — `output` is
  `None` when `capture=False`, the buffered text when `capture=True`. The
  one existing caller (`loop.py:145`) already discards the return value
  entirely (routing comes from `whyline handoff` records, per the module's
  own docstring) — confirmed by reading it, not assumed — so this is a safe,
  uncontested signature change.

## Architecture

```
whyline (no args)
  └─ execs into ──▶ whyline-relay chat
                       │
                       ├─ chat.py         (REPL loop, routing, turn pipeline)
                       ├─ chatlog.py      (append/load/cap chat-history.jsonl)
                       ├─ adapters/*.py   (+extract_response field; unchanged permissions/commands)
                       └─ agents.py       (+capture option; unchanged process/timeout/signal handling)
```

- **`whyline`'s delegation** (in `src/whyline/cli.py` or `main()`, whichever
  currently handles no-args invocation): `shutil.which("whyline-relay")` →
  found: `os.execvp("whyline-relay", ["whyline-relay", "chat"])`. Not found:
  fall through to existing help/usage output. Mirrors the same
  `which`/`execvp` pattern `runner.py` already uses and already tests via
  monkeypatching — no new pattern introduced.

- **`.whyline/relay/chat.json`** (new, per-repo): `{"default_agent": "claude"}`.
  Presence of this file is what distinguishes "first launch" (run the setup
  wizard) from a normal `chat` start.

- **`.whyline/relay/chat-history.jsonl`** (new, per-repo, append-only): one
  JSON object per line — `{"agent": str, "prompt": str, "response": str,
  "timestamp": ISO8601, "files_changed": int, "ok": bool}`. `ok: false` marks
  a turn whose agent reported failure/denial (drives the `⚠` prefix on its
  diff-stat line and excludes nothing from history — a failed turn's context
  still matters to later turns).

## Command / UX shape

```
$ whyline
[first launch only]
Detected: claude, codex, agy. Not found: grok.
Pick your default agent [claude]:
Saved. Starting chat --

> what does the auth middleware do?
[claude] The middleware in src/auth/...

> /codex refactor validate_token to raise instead of returning None
[codex] Done -- validate_token now raises AuthError...
  3 files changed, committed as a1b2c3d

> /grok is that safe given the callers in payments/?
[grok] Given the shared history above, yes -- the two callers already...

> /agy summarize what we just did
agy is not configured for chat in this repo -- see `whyline-relay doctor`
and README, "Using Antigravity today", to add it to .whyline/relay/config.toml.

> /notacommand
Unknown command: /notacommand. Try /claude, /codex, /agy, /grok, /default,
/agents, /history, /clear, /exit.

> /exit
```

- `/claude`, `/codex`, `/agy`, `/grok` — one-shot: send this message to that
  agent, default agent for the session unchanged.
- `/default <agent>` — change the default for the rest of the session and
  persist it to `chat.json`.
- `/agents` — list installed (`which`) vs. configured-for-edits (has a
  managed default or a `config.toml` entry) vs. neither.
- `/history` — replay the saved transcript for this repo.
- `/clear` — wipe `chat-history.jsonl`, with a y/n confirmation first
  (destructive, matches the project's standing "confirm before irreversible
  actions" rule).
- `/exit` or Ctrl+D — quit.
- An unrecognized `/word` is an error, re-prompted immediately — it is never
  sent to the default agent as literal text. A typo must not silently burn a
  turn (and its cost) on the wrong agent.

## Turn execution pipeline

1. **Resolve the agent** — `/prefix` if given, else `chat.json`'s
   `default_agent`.
2. **Build the prompt** — `chatlog.recent(root, token_budget)` returns the
   capped tail of `chat-history.jsonl`, formatted as plain text, prepended to
   the new input. Oldest turns drop first once the budget is exceeded — no
   summarization.
3. **Resolve the command:**
   - claude/codex: `adapters.get(name).default_command` — always available.
   - agy/grok (generic): only if `.whyline/relay/config.toml` already has an
     `[agents.<name>]` entry; otherwise refused (see UX example above).
4. **Run it** — `agents.run(command, prompt, cwd=root, capture=True,
   timeout_seconds=CHAT_TIMEOUT_SECONDS)`. Same process-group, heartbeat,
   timeout, and Ctrl+C handling the relay's task loop already relies on. A
   new, chat-specific constant, deliberately much shorter than the relay's
   task default (`timeout_minutes: 30` in `config.py`, meant for unattended
   background work) — a human is waiting live at the prompt here.
   `CHAT_TIMEOUT_SECONDS = 300` (5 minutes): long enough for a real edit
   turn (the empirical Grok/Antigravity turns this session ran well under
   that), short enough that a stuck turn doesn't strand the human. Not
   user-configurable in v1 — YAGNI until someone hits it.
5. **Extract the response** — `adapter.extract_response(text)`, where `text`
   is the codex temp-file's contents if `adapter.uses_output_file`, else the
   run's captured stdout (see Decision D8).
6. **Show it, log it, commit it** — print the response. Append the turn
   record to `chat-history.jsonl`. Capture `git diff --stat` *before*
   committing (so there's something to show), then call
   `gitcheck.commit_all(root, "chat: <agent> turn")` — already exists, used
   by the relay's own task loop: stages everything, commits, returns
   `False`/no-op when nothing was staged. Print the captured diff-stat only
   when `commit_all` returned `True`. Prefix that line with `⚠` if the turn's
   `ok` is `false`.

## Error handling

- **`AgentMissing`** — printed inline; turn not logged; REPL continues.
- **`AgentTimeout`** — printed inline; turn not logged; no commit.
- **Rate-limited** (`agents.rate_limited()`, already exists) — printed with a
  suggestion to `/default` another agent or wait; not a hard crash.
- **Extraction failure** — falls back to `last_line_detail`, clearly labeled.
- **Reported failure/denial but files still changed** — still auto-committed
  (Decision D6); diff-stat line prefixed `⚠`.

## Testing strategy

- `chatlog.py`: pure-function tests (empty/single/over-budget/corrupted-line
  history), no subprocesses.
- Per-adapter `extract_response`: one real-sample fixture test plus one
  malformed-input fallback test, per adapter (claude, codex, generic).
- `chat.py` turn pipeline: `agents.run` monkeypatched (never a real
  subprocess in tests, matching the existing codebase-wide pattern) —
  default routing, `/prefix` routing, unknown-command re-prompt without
  burning a turn, generic agent refused when unconfigured, auto-commit only
  when dirty, `⚠` marker on reported failure.
- First-launch wizard: `shutil.which` monkeypatched across installed-agent
  subsets; refuses with zero agents found; persists the chosen default.
- `whyline`'s exec-delegation: `shutil.which`/`os.execvp` monkeypatched
  exactly like `runner.py`'s existing tests — present → execs with the right
  argv; absent → falls through to help, no crash.
- End-to-end (once built): a scratch-repo smoke test with a real installed
  agent — multi-turn session, a `/prefix` switch, history surviving a REPL
  restart, an agentic turn actually committing — the same empirical bar every
  feature this session was held to before shipping.
