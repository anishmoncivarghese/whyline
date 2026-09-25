# Grok (`grok`, "Grok Build") as a documented generic recipe

Status: design, awaiting the owner's review. Written 2026-09-26.
Relates to: `2026-09-25-account-and-model-selector-design.md` (whyline's `runner.AGENTS`/`MODEL_FLAG`,
extended here the same way Antigravity was), and whyline-relay's existing "Using Antigravity today,
via the generic adapter" README section, whose exact shape this document mirrors.

**This design was informed by three independent consultations**, run for real: Grok itself (asked to
design its own adapter, mirroring how Antigravity was originally consulted), Codex (`codex exec -s
read-only`), and Antigravity (`agy --mode plan`) — the latter two each shown Grok's own proposal and
the owner's empirical findings, and asked to review it from the perspective of an agent that already
has a real, managed adapter here. All three independently converged on the same core recommendation.

## 1. Summary

Grok (xAI's official CLI, "Grok Build") has genuinely better headless-mode fundamentals than
Antigravity had when it was added — real per-invocation `--allow`/`--deny` permission flags, not a
single machine-global settings file — but a full multi-round consultation and extensive empirical
verification converged on the same conclusion all three consultants reached independently: **add it
as a documented generic-adapter recipe, the same shape Antigravity already has, not a managed
built-in adapter.** This design also adds `grok` to whyline's own `runner.AGENTS` for interactive
`whyline run grok` use, which is unaffected by any of the generic-adapter concerns below (a human is
present the whole time).

## 2. Goals and non-goals

Goals

- `whyline run grok "<task>"` works, using the same interactive-hand-to-a-human model `claude`/
  `codex`/`antigravity` already use.
- `whyline model set grok <model>` / `whyline model` work for Grok, using the account/model-selector
  feature already shipped (0.3.2).
- whyline-relay documents a real, empirically verified generic-adapter recipe for Grok, in the same
  place and shape as the existing Antigravity section.
- `doctor` gives a Grok-specific warning when it's configured generic, naming its own specific gaps
  (not a copy of Antigravity's wording, since the specifics differ).
- The pre-existing bypass-guard gap this investigation surfaced (a generic agent's own known bypass
  flag was never checked at all) is fixed — **already committed to `main`**, independent of the rest
  of this design (`bypass.py` now checks `agy` and `grok` by binary name; not yet its own tagged
  release as of this writing, still sitting on top of 0.2.14).

Non-goals

- **A managed `adapters/grok.py` built-in adapter.** All three consultations agreed this is premature.
  The blocking reasons, in order of how fundamental they are:
  1. **The `model_flag`/`-p` ordering incompatibility** (found independently by Codex and Antigravity):
     `config.py` appends a configured `model_flag` to the *end* of the stored command, but Grok's own
     headless invocation needs `-p` to remain the token immediately before the prompt. A managed
     adapter's `model_flag` support would silently produce `grok ... -p --model NAME <prompt>`, which
     is broken — `-p` would swallow `"--model"` as the prompt text. Not a problem for the generic
     recipe (a generic agent never gets `model_flag` support at all — same existing rule as any other
     generic tool).
  2. **No safe, read-only login-status check exists.** `grok login` unconditionally starts a live
     device-code OAuth flow — there is no equivalent to `codex login status` / `claude auth status`.
  3. **Denial detail stays generic** (`stopReason: "cancelled"`, no command or path named) — the exact
     same gap that kept Antigravity generic.
  4. **No parseable subscription/plan-tier field** exists for the account/model-selector feature.
- **Failover/backup-agent support for Grok.** Requires the login check above; explicitly deferred.
- **Guessing a rate-limit marker for Grok.** All three consultants agreed: do not add one without a
  captured real 429 response body. The existing `RATE_LIMIT_MARKERS` full-stdout substring scan was
  also flagged as a latent false-positive risk (a JSON echo of plan text containing a marker phrase)
  — worth its own, separate look, not part of this design.
- **Verifying the logged-out / first-run headless hang risk.** Deliberately not forced during this
  investigation, to avoid disrupting the owner's real, authenticated session. Documented as a known,
  unverified risk in the README recipe rather than silently ignored.

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| G1 | Grok gets a documented **generic-adapter recipe**, not a managed built-in — identical shape to Antigravity's existing section | Independent 3-way consultation agreement (Grok, Codex, Antigravity), on grounds that don't disappear with more argv-flag testing: the `model_flag` ordering bug is architectural, the login-check gap is a real CLI limitation, not a config problem |
| G2 | `whyline run grok` is added regardless, fully independent of the generic-adapter concerns | A human is present and approves in real time for `whyline run`; none of the headless-mode gaps (login check, denial detail, permission scoping) apply to an interactive session |
| G3 | The recipe uses `--permission-mode dontAsk` plus explicit `--allow`/`--deny` rules, `-p` last, `--output-format json` | Empirically verified: this exact shape completed a full realistic implement turn (edit including creating a new file, verify, `whyline note`, commit) and a full realistic reviewer turn (read a diff, summarize accurately), with deny correctly beating allow even adversarially |
| G4 | The recipe explicitly documents that `Edit` alone covers file creation, not just editing existing files | Verified directly — a first assumption (mirroring Grok's and Codex's own shared worry) that a separate `Write` rule would be needed was wrong; worth stating plainly so a reader doesn't over-grant permissions defensively |
| G5 | The recipe documents that a project's own `.claude/settings.local.json` does not widen the effective policy | Verified adversarially: a local settings file explicitly allowing `git push` did not override the recipe's own `--deny "Bash(git push:*)"` — this was a real, unresolved risk before testing, not an assumption |
| G6 | `doctor` gets a Grok-specific warning branch, distinct from Antigravity's | The specifics genuinely differ (no equivalent to issue #548, different missing capabilities) — copying Antigravity's exact wording would misrepresent what's actually known about Grok |
| G7 | The bypass-guard fix (checking a generic agent's binary name, not only its registered `adapter_name`) lands independent of and before the rest of this design | A genuine, pre-existing gap unrelated to whether Grok specifically gets added — found while reviewing Grok's proposal, but the exposure already existed for Antigravity. Already committed to `main` as its own bounded fix, not gated on this spec's approval; will go out in whichever release picks it up next |

## 4. Where this sits relative to today's code (measured, whyline 0.3.2 / whyline-relay 0.2.14+)

| File | Today | What changes |
|---|---|---|
| `whyline/src/whyline/runner.py` | `AGENTS = {"claude": [...], "codex": [...], "antigravity": ["agy", "-i"]}`; `MODEL_FLAG` has entries for all three | Gains `"grok": ["grok"]` in `AGENTS` (bare invocation — confirmed `grok "<prompt>"` starts an interactive session directly, simpler than Antigravity's `-i` requirement) and `"grok": "--model"` in `MODEL_FLAG` (confirmed via `-m, --model <MODEL>` in `--help`) |
| `whyline-relay/README.md` | Has "Using Antigravity today, via the generic adapter" (added when Antigravity was integrated) | Gains a parallel "Using Grok today, via the generic adapter" section, with the verified recipe (G3-G5) |
| `whyline-relay/src/whyline_relay/preflight.py` | Has an Antigravity-specific generic-agent warning (already existed before this design; unrelated to the bypass-guard fix, G7, which touched `bypass.py` only) | Gains a third branch, `elif adapter.name == "generic" and agent == "grok":`, with Grok-specific wording |
| `whyline-relay/src/whyline_relay/adapters/bypass.py` | **Already fixed, committed to `main`** (on top of 0.2.14, not yet its own release): checks a generic agent's binary name against `SIMPLE_BINARY_FLAGS`/`MODE_BINARY_FLAGS`, currently covering `agy` and `grok` | No further change needed here — `grok`'s entry (`--permission-mode bypassPermissions`) was added proactively during that fix |
| `whyline-relay/src/whyline_relay/adapters/*` (a real `grok.py`) | Does not exist | **Not created** (non-goals) |

## 5. Design

### 5.1 whyline: `runner.py`

```python
AGENTS = {
    "claude": ["claude"],
    "codex": ["codex"],
    "antigravity": ["agy", "-i"],
    "grok": ["grok"],
}

MODEL_FLAG = {"claude": "--model", "codex": "--model", "antigravity": "--model", "grok": "--model"}
```

`build_argv("grok", task, brief_text, model=...)` produces `["grok", "--model", "<model>", "<brief>\n\n<task>"]` when a model is set, or `["grok", "<brief>\n\n<task>"]` otherwise — the same shape as every other agent, verified safe for this bare-positional-prompt invocation (unlike the generic recipe's `-p`, there is no greedy-consumption risk here, since `grok`'s interactive mode takes the prompt as a plain trailing positional argument, exactly like `claude`/`codex`).

### 5.2 whyline-relay: the README recipe

```toml
[roles]
implementer = "codex"   # or reviewer; either role works
reviewer    = "grok"

[agents.grok]
adapter = "generic"
command = [
  "grok", "--output-format", "json", "--permission-mode", "dontAsk",
  "--deny", "Bash(git push:*)", "--deny", "Bash(rm -rf:*)",
  "--allow", "Edit", "--allow", "Bash(git add:*)", "--allow", "Bash(git commit:*)",
  "--allow", "Bash(git diff:*)", "--allow", "Bash(git status:*)", "--allow", "Bash(git log:*)",
  "--allow", "Bash(whyline:*)", "--allow", "Bash(python3:*)",
  "-p"
]
```

Prose accompanying the recipe, matching Antigravity's section's density and tone:

- **`-p` must be the last item in the command** — the relay always appends the prompt as the command's final argument; `grok -p` greedily consumes whatever token comes right after it, so `-p` anywhere earlier makes it swallow the next flag instead of the real prompt.
- **`Edit` alone covers creating new files, not just editing existing ones** — verified directly; a separate `Write` rule is not needed for ordinary implementation work.
- **Swap `Bash(python3:*)` for your own stack's test command** (`Bash(npm test:*)`, etc.) — this is a hand-written recipe, not a stack-aware managed adapter; adjust it for your project.
- **A generic agent can't take a configured `model` at all** — put a model flag directly in `command` yourself if you want one pinned (existing, already-documented rule, unchanged).
- **Verified: a project's own `.claude/settings.local.json` does not widen this policy** — even a local settings file explicitly allowing `git push` did not override this recipe's `--deny` rule in testing.
- **Known, unverified risk**: a logged-out or first-run session might hang waiting for a device-code or workspace-trust prompt rather than failing promptly, since there is no login-status check to catch this ahead of time (`agents.run` inherits stdin; the process would sit until `timeout_minutes`, default 30). Not yet tested, to avoid disrupting a real authenticated session — noted here rather than silently assumed safe.
- **Denials are generic**: `stopReason: "cancelled"`, no command or file named — same limitation as Antigravity's "a RunCommand call was denied."

### 5.3 whyline-relay: `preflight.py`

```python
elif adapter.name == "generic" and agent == "grok":
    checks.append(
        _result(
            "warn",
            "grok is a generic agent, and it has no non-interactive login-status "
            "check or specific denial detail -- see README, 'Using Grok today'. "
            "The relay does not manage its permissions, login or denials",
        )
    )
```

Placed as a third branch alongside the existing `agent == "antigravity"` branch and the generic `else`, in the same `if adapter.name == "generic":` block `preflight.py` already has.

## 6. Build order

One phase per repo, same split as the account/model-selector design and for the same reason (two
separate git repositories, two separate `whyline-relay` sandboxes needed):

1. **whyline: `runner.py`'s `AGENTS`/`MODEL_FLAG` additions (5.1).** Fully self-contained.
2. **whyline-relay: the README recipe (5.2) and `preflight.py` warning (5.3).** Independent of phase 1
   in terms of code (no shared file), but documented together since they're one coherent piece of
   work; either could ship first without breaking the other.

## 7. Risks and open questions

- **The logged-out/first-run hang risk remains genuinely unverified.** This is stated plainly in the
  README rather than resolved, matching this project's own standard of not asserting safety that
  wasn't actually measured.
- **The `RATE_LIMIT_MARKERS` full-stdout-scan false-positive risk**, flagged by Grok during
  consultation, applies to every generic JSON-output agent (Antigravity and Grok both), not just this
  one — worth a dedicated look later, explicitly out of scope here.
- **If Grok's CLI later adds a real login-status check or more specific denial output**, this design's
  non-goals should be revisited — the `model_flag`/`-p` ordering bug would still need its own fix
  first (a small, generalizable `Adapter` shape change: a way to insert a model flag before a
  trailing prompt-flag, not just append it to the whole command's end) before managed-adapter status
  would make sense.

## 8. Decision log (this design session, 2026-09-25–26)

| Question | Answer |
|---|---|
| Managed adapter or generic recipe? | Generic recipe — independent 3-way consultation agreement |
| Should Grok participate in its own design consultation? | Yes — mirrored the original Antigravity consultation methodology |
| Should Codex/Antigravity review Grok's own proposal, or get an identical from-scratch brief? | Review Grok's proposal specifically (owner's choice) |
| Does `Edit` alone create new files? | Yes — verified directly, resolving a concern all three consultants shared |
| Does a project's `.claude/settings.local.json` widen Grok's effective permissions? | No — verified adversarially |
| Is the `model_flag`/`-p` bug a blocker for the generic recipe? | No — a generic agent never gets `model_flag` support at all; only relevant for a future managed adapter |
| Should the bypass-guard gap be fixed now or bundled into this spec? | Fixed immediately, independent of this spec's approval (owner's explicit request) |
