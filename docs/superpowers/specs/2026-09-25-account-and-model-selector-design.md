# whyline: account detection and a model selector

Status: design, awaiting the owner's review. Written 2026-09-25.
Relates to: `2026-09-23-relay-n-roles-design.md`, whose section 2 (non-goals) and section 8 (roadmap)
named "subscription-aware setup" as a deferred piece — deferred specifically because "nothing here
checks whether an account can actually use a chosen model; that needs real measurement of what each
CLI can report about its own account, which hasn't been done." This design is that measurement, and
the two small features it makes possible.

## 1. Summary

Today, choosing a model for `codex`/`claude`/`antigravity` is either invisible (`whyline run` has no
model flag at all) or asked blind (whyline-relay's `init`/`roles set` ask "Model for codex (blank for
default):" with no idea what plan you're actually on). This design adds two small, independent
commands to `whyline` — `whyline account` (detects and confirms which subscription/plan each agent's
CLI is actually authenticated under, once per machine, confirmed once per repo) and `whyline model`
(a per-repo model selector, showing the detected plan as context) — and teaches `whyline run` to use
the selected model directly, plus teaches whyline-relay's own setup commands to read it as a default.

## 2. Goals and non-goals

Goals

- Detect, for real, which plan/tier `codex` and `claude` are authenticated under — not just whether
  they're logged in (which `adapters.py`'s existing `login_argv` checks already cover) — verified
  against the real CLIs, not assumed.
- Detect once per machine (an account's plan doesn't vary per repo), cache it in a new
  `~/.whyline/account.json` (whyline's first-ever global, cross-repo file), and confirm it once per
  repo in `.whyline/account.json`.
- A standalone, explicit `whyline model` command lets you pick a model per agent per repo, showing
  the detected plan as informational context — never filtering or blocking a choice.
- `whyline run` becomes model-aware for the first time, using whatever `whyline model` selected.
- whyline-relay's `init` wizard and `roles set` read the same per-repo model file as an additional
  default source, without ever writing to it themselves.
- Both new commands behave exactly like `whyline init` already does: explicit, human-run, never
  auto-triggered mid-flow by `whyline run` or anything else. Neither existing on a repo changes any
  existing command's behavior at all.

Non-goals

- **Filtering or validating model choices against what a plan actually permits.** Explicitly
  rejected during design in favor of YAGNI: no tier-to-model table to build and keep current as
  providers change their lineups. A wrong choice fails at the CLI's own invocation time, same as
  today.
- **Detecting Antigravity's subscription/tier.** No verified mechanism exists for it (unlike Codex's
  decodable JWT and Claude's `auth status` field, both confirmed for real during this design).
  `whyline model` still lets you set Antigravity's model; it just never shows tier context for it.
- **Managing OAuth refresh, multi-account switching, or re-authenticating on the user's behalf.**
  This reads whatever the underlying CLI's own auth state currently is; if it's stale, using that
  CLI once (letting it refresh itself) and re-running `whyline account detect` is the fix, not
  something this feature manages.
- **Any new dependency.** `whyline` and `whyline-relay` both keep `dependencies = []`; every
  mechanism here (JSON parsing, JWT payload decoding) uses only the standard library.

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| M1 | "Subscription" means the account's plan/tier (Claude Pro/Max/Team, ChatGPT Plus/Pro/Team) — not just binary login status, which `adapters.py`'s `login_argv` already checks | The deeper, genuinely unmeasured gap the roadmap named; a binary check would just be UX polish on an existing mechanism |
| M2 | Both CLIs' plan detection is real and verified, not assumed: `claude auth status`'s JSON output has a `subscriptionType` field directly; Codex has no equivalent command, but `~/.codex/auth.json`'s `tokens.id_token` JWT, decoded, carries `chatgpt_plan_type` under its `https://api.openai.com/auth` claim | Confirmed against live output on 2026-09-25, not guessed. Codex's path is real but reads an internal, undocumented file — a real fragility risk (5, Risks), accepted because no public alternative exists |
| M3 | Detect once per machine (`~/.whyline/account.json`, whyline's first global file), confirm once per repo (`.whyline/account.json`) | An account's plan doesn't vary per repo; re-running full detection in every repo would repeat identical work and risk drifting out of sync with itself |
| M4 | The detected plan is shown as context only, never filters or blocks a model choice | Owner's explicit choice — no tier→model table to build and keep updated as provider lineups change |
| M5 | Two separate commands (`whyline account`, `whyline model`), not one combined wizard and not folded into `whyline init` | Detection is rare and machine-wide; model choice is something you'd plausibly change per task. Folding into `init` (a conventionally one-time command) would fight the explicit "where we can change it" requirement |
| M6 | `whyline run` gains model support via a new `MODEL_FLAG` mapping; whyline-relay's `init`/`roles set` read `.whyline/model.json` as an additional default, but never write to it | whyline-relay never imports whyline as a library (it already only shells out to the `whyline` CLI) and both keep zero runtime dependencies, so file-based, single-writer integration is the only option that doesn't add a dependency or risk two tools racing to write the same file |
| M7 | Detection failure for one agent (not installed, not logged in, unparseable output) records `"plan": "unknown"` with a reason and continues with the other agent — never a hard failure | Matches this project's established "degrade gracefully, never block on a partial signal" convention (e.g. `preflight.py`'s own checks each report independently) |
| M8 | Corrupt or malformed `account.json`/`model.json` is treated as absent, exactly like `whyline-relay`'s `state.py` already treats a corrupt `state.json` | Consistency with an established, already-proven convention, not a new one |
| M9 | Both per-repo files (`.whyline/account.json`, `.whyline/model.json`) are gitignored, added to the existing `.whyline/.gitignore` (which already gitignores `ledger.jsonl` for the same reason: it holds information that shouldn't leave the machine via git) | `account.json` holds someone's personal plan/billing tier — committing it would expose that to every repo collaborator. `model.json` follows for consistency, and because different teammates may have access to different models; each person keeps their own choice, the same way `~/.whyline/account.json` (global) is never committed at all |

## 4. Where this sits relative to today's code (measured, whyline 0.3.1 / whyline-relay 0.2.13)

| File | Today | What changes |
|---|---|---|
| `whyline/src/whyline/paths.py` | Only ever resolves repo-relative paths (`.whyline/...`); no global/home-directory concept exists anywhere in whyline | Gains `global_whyline_dir() -> Path` (`~/.whyline/`) and `account_path`/`global_account_path`/`model_path` helpers, alongside the existing repo-scoped ones |
| `whyline/src/whyline/cli.py` (`_merge_gitignore`, called from `init`) | Writes `.whyline/.gitignore` with `ledger.jsonl`, `index.db`, `!decisions.md`, `*.bak`, `active-handoff.json`, `ownership.json`, `readside.log`, `*.lock` | Gains two more lines, `account.json` and `model.json` (M9) — both new per-repo files are personal/machine-specific, never committed |
| `whyline/src/whyline/cli.py` | `_add_init`, `_add_status`, etc. — one `_add_<command>` function per subcommand | Gains `_add_account` and `_add_model`, wired the same way |
| `whyline/src/whyline/account.py` | Does not exist | New module: `detect_codex()`, `detect_claude()`, `detect() -> dict`, `save_global`/`load_global`, `confirm_for_repo`/`load_repo` — the detection and file-handling logic, with no CLI parsing in it (kept out of `cli.py`, matching how `runner.py`/`hooks.py` etc. already separate logic from argument parsing) |
| `whyline/src/whyline/model.py` | Does not exist | New module: `ModelChoice` (per-agent dict), `load`/`save` for `.whyline/model.json`, an interactive `choose()` used by the `model` command |
| `whyline/src/whyline/runner.py` | `AGENTS = {"claude": [...], "codex": [...], "antigravity": [...]}`; `build_argv(agent, task, brief_text)` takes no `root` and does no filesystem I/O; `launch(agent, task, brief_text, which=None, exec_fn=None)` resolves `which`/`exec_fn` explicitly at call time rather than as captured defaults, specifically for testability (its own docstring: a real incident on 2026-08-17 where a captured default silently bypassed a test's monkeypatch and spent real vendor quota) | Gains `MODEL_FLAG = {"claude": "--model", "codex": "--model", "antigravity": "--model"}` (all three confirmed for real against `--help` output). `build_argv` gains one new parameter, `model: str \| None = None`, appended via `MODEL_FLAG` when given — stays pure, no I/O added to it, matching why `which`/`exec_fn` are resolved outside `launch` rather than defaulted inside it. `launch` gains the same `model` parameter, passed straight through. Resolving *which* model to pass is `cmd_run`'s job (below), not `runner.py`'s |
| `whyline/src/whyline/cli.py` (`cmd_run`) | Resolves `root = _require_repo()`, then calls `runner.launch(args.agent, args.task, brief_text)` — `root` is never passed to `launch` today | Reads `model_module.load(root).get(args.agent)` right after resolving `root`, and passes it as `runner.launch(args.agent, args.task, brief_text, model=model)` |
| `whyline-relay/src/whyline_relay/init.py` | `_ask_model(confirm, agent)` always prompts blind, defaulting to blank | Reads whyline's `.whyline/model.json` (if present) first and offers it as the bracketed default, the same `[default]` convention `_ask_agent` already uses |
| `whyline-relay/src/whyline_relay/roles.py` | `set_role`'s interactive model prompt (`confirm(f"Model for {agent} (blank for default): ")`) always blank | Same pre-fill treatment as `init.py`'s `_ask_model` |

## 5. Design

### 5.1 Detection (`whyline account`)

```python
# account.py
def detect_codex(auth_path: Path = Path.home() / ".codex" / "auth.json") -> dict:
    """Never raises for a missing/malformed file or an unexpected shape -- always
    returns a dict with at least {"plan": "unknown", "reason": "..."} on failure."""

def detect_claude(runner=subprocess.run) -> dict:
    """Runs `claude auth status`, parses its JSON. Same failure contract as detect_codex."""

def detect() -> dict:
    """{"codex": detect_codex(), "claude": detect_claude()}"""
```

`detect_codex` reads `auth_mode` first: if it isn't `"chatgpt"` (e.g. an API key), returns
`{"auth_mode": <value>, "plan": None}` — not an error, just "no subscription tier applies here."
When it is `"chatgpt"`, decodes `tokens.id_token`'s middle (payload) segment as base64 JSON and reads
`.["https://api.openai.com/auth"].chatgpt_plan_type`. The raw token itself is never written to
`account.json`, logged, or returned from `detect_codex` — only the derived plan string and
`auth_mode`. `detect_claude` mirrors this: if `apiProvider` isn't `"firstParty"`, `plan` is `None`.

`~/.whyline/account.json`:
```json
{
  "codex": {"auth_mode": "chatgpt", "plan": "plus", "detected_at": "2026-09-25T14:00:00+05:30"},
  "claude": {"auth_method": "claude.ai", "plan": "pro", "detected_at": "2026-09-25T14:00:00+05:30"}
}
```

`whyline account detect` always re-runs detection fresh and overwrites this file — there is no
staleness timer, since the underlying CLIs' own auth files are the actual source of truth and this
is just a cache of what they most recently reported.

`.whyline/account.json` (per repo) has the same per-agent shape, plus `"confirmed": true|false` at
the top level. `whyline account status`, run in a repo with no repo file yet, prints the global
detection and asks "Use this for this repo? [Y/n]"; either answer writes the repo file (so the
prompt doesn't repeat), with `confirmed` reflecting the answer. `whyline account status` in a repo
that already has a file just prints it, no prompt.

### 5.2 Model selection (`whyline model`)

`.whyline/model.json`:
```json
{"codex": "gpt-5-codex", "claude": "opus", "antigravity": null}
```

`whyline model` (no args) iterates `("codex", "claude", "antigravity")`, and for each one: prints the
agent name plus its detected plan from `.whyline/account.json` if present and non-null (nothing
printed for Antigravity, or for an agent whose `plan` is `None`), prints its current setting from an
existing `.whyline/model.json` if any, and asks `Model for {agent} (blank to keep default): `. A
blank answer leaves that key absent/`null` — matching `roles set`'s own blank-means-default
convention exactly. `whyline model set <agent> <model>` does the same for one agent, non-interactively.
`whyline model status` just prints the current file's contents (or "nothing set" if absent).

No value is validated against any list of real model names (M4) — whatever string is given is
written as-is.

### 5.3 `whyline run` becomes model-aware

`build_argv`/`launch` stay pure and gain an explicit `model` parameter each — no internal filesystem
access, consistent with why this file already resolves `which`/`exec_fn` outside `launch` rather than
inside it:

```python
MODEL_FLAG = {"claude": "--model", "codex": "--model", "antigravity": "--model"}

def build_argv(agent: str, task: str, brief_text: str, model: str | None = None) -> list[str]:
    if agent not in AGENTS:
        known = ", ".join(sorted(AGENTS))
        raise UnknownAgent(f"Unknown agent {agent!r}. Known agents: {known}")
    command = list(AGENTS[agent])
    if model:
        command += [MODEL_FLAG[agent], model]
    prompt = f"{brief_text}\n\n{task}" if brief_text else task
    return [*command, prompt]


def launch(
    agent: str, task: str, brief_text: str, which=None, exec_fn=None, model: str | None = None,
) -> int:
    argv = build_argv(agent, task, brief_text, model=model)
    ...  # unchanged below this line
```

`cmd_run` is the one place that resolves *which* model to use, right after it already resolves `root`:

```python
def cmd_run(args: argparse.Namespace) -> int:
    from whyline import gitq, model as model_module, paths, sync

    root = _require_repo()
    ...
    model = model_module.load(root).get(args.agent)
    try:
        runner.launch(args.agent, args.task, brief_text, model=model)
    ...
```

If `.whyline/model.json` doesn't exist, or has no entry for `agent`, `model_module.load(root).get(...)`
returns `None`, and behavior is byte-for-byte identical to today — this is purely additive.

### 5.4 whyline-relay integration (read-only)

In `init.py`'s `_ask_model` and `roles.py`'s `set_role`, before prompting, both check for
`.whyline/model.json` in the repo root (a plain file read, no import of whyline as a library — matches
how `whylinecmd.py` already only ever shells out to `whyline`, never imports it). If a value exists for
that agent, the prompt becomes `Model for {agent} [{preset}] (blank to accept, or type another): `,
the same bracketed-default shape `_ask_agent` already uses; a blank answer takes the preset instead of
staying unset. If the file is absent, malformed, or has no entry for that agent, the prompt is
unchanged from today (blank default, nothing preset). whyline-relay never writes to this file — `whyline
model` is its only writer, so there is exactly one place that can change it.

### 5.5 CLI surface

- `whyline account status` — show cached global + repo state (prompts to confirm on first repo use).
- `whyline account detect` — force fresh detection, overwrite `~/.whyline/account.json`.
- `whyline model` — interactive selector, all three agents.
- `whyline model set <agent> <model>` — non-interactive, one agent.
- `whyline model status` — print current repo selections.

### 5.6 Error handling and edge cases

- A CLI not installed, not logged in, or its output in an unexpected shape → that agent's entry is
  `{"plan": "unknown", "reason": "<one line>"}`; the other agent's detection still runs and its own
  result is unaffected (M7).
- Corrupt/malformed `account.json` or `model.json` (hand-edited badly) → treated as absent, exactly
  like whyline-relay's `state.py` already treats a corrupt `state.json` (M8) — never a crash, on
  either side of the integration.
- An agent name in `.whyline/model.json` whyline-relay doesn't itself know about (a future agent
  whyline supports before whyline-relay's `adapters.BUILTIN` catches up) → whyline-relay silently
  ignores that key; it only ever reads keys matching its own known agent names.
- `whyline model` run in a repo with no `.whyline/account.json` yet → still works, just shows no tier
  context line for any agent (not an error, not a block).
- API-key-mode auth (Codex `auth_mode` not `"chatgpt"`, or Claude `apiProvider` not `"firstParty"`) →
  `plan: null`, reported plainly as "no subscription tier (using an API key)" wherever shown, never
  treated as a detection failure.

## 6. Build order

One coherent design, but **two separate implementation plans**, because it spans two separate git
repositories — unlike the planner piece (entirely inside whyline-relay), this design's own build
order forces the split: each repo needs its own `whyline-relay` sandbox and its own release cycle,
the same way whyline's own Antigravity support (0.3.1) and whyline-relay's pieces have always shipped
as fully separate runs throughout this project's history.

1. **whyline: `whyline account` + `whyline model` + `whyline run`'s model support (5.1-5.3).** Fully
   self-contained; ships as its own whyline release. Regression net: `runner.py`'s existing
   `build_argv` tests, run with no `.whyline/model.json` present, must keep passing unedited.
2. **whyline-relay: the read-only integration (5.4).** Depends on 1 being released first, since it
   reads the exact `.whyline/model.json` shape phase 1 defines. Regression net: `init`/`roles set`'s
   existing interactive-prompt tests, run with no `.whyline/model.json` present in their test repos,
   must keep passing unedited — proving the new behavior is additive, never a change to today's
   default (blank) prompt.

## 7. Risks and open questions

- **Codex's plan-tier detection depends on an undocumented internal file format** (`~/.codex/auth.json`'s
  JWT claim shape). If a future Codex release changes this shape, `detect_codex` must degrade to
  `{"plan": "unknown", "reason": "..."}`, not crash — this needs a real test asserting exactly that
  for a JSON blob shaped like today's, but missing the expected claim.
- **No staleness signal exists for Claude's side** — `claude auth status` always reflects the live,
  current state (it's not a cache), so this risk is Codex-specific: if Codex's own local auth file is
  stale (its refresh_token flow hasn't run recently), `whyline account detect` faithfully reports
  whatever Codex itself currently believes, which could be out of date. Documented as a known
  limitation (5.1), not solved here.
- **Antigravity's own subscription/tier model is entirely unmeasured** — explicitly out of scope
  (non-goals), but worth a future spike if Antigravity ever exposes an equivalent to Claude's `auth
  status` or Codex's JWT claim.

## 8. Roadmap update

This completes the N-roles design's "subscription-aware setup," the roadmap's last piece with no
prior design work at all. Unlike the planner (which reused this project's existing `pipeline.py`
engine), this piece is almost entirely new surface in `whyline` itself, with a small, deliberately
narrow read-only touchpoint on whyline-relay's side.

## 9. Decision log (this design session, 2026-09-25)

| Question | Answer |
|---|---|
| What does "subscription" mean? | The account's plan/tier, not just binary login (owner's choice) |
| Is plan-tier detection actually possible? | Yes, verified for real: Claude's `auth status` has a direct `subscriptionType` field; Codex's requires decoding its own JWT, which does carry `chatgpt_plan_type` |
| Which tool hosts this? | `whyline` itself, not whyline-relay and not a new separate tool (owner's choice) |
| Global vs. repo scope? | Detect once per machine, confirm once per repo (owner's choice) |
| Does the detected tier filter model choices? | No — shown as context only, never blocks or filters (owner's choice) |
| Does the model selector affect `whyline run`, whyline-relay, or both? | Both (owner's choice) |
| Command structure? | Two focused commands (`whyline account`, `whyline model`), not one combined wizard, not folded into `init` (owner's choice) |
| Are the new per-repo files committed to git or gitignored? | Both gitignored (owner's choice) — `account.json` is personal plan/billing info, `model.json` follows for consistency and because access varies per teammate |
