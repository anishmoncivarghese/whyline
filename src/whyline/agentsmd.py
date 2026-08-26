"""The canonical shared instruction that asks agents to read and record reasoning.

Reading and recording both matter. The read instruction is best-effort: the
closed experiment measured only 43% unprompted compliance, so `whyline run`
remains the reliable way to inject context. The instruction still improves
directly opened sessions and now uses `sync` so one read includes the active
handoff, Git state, ownership, and relevant decisions.

The wording is not arbitrary. `docs/superpowers/specs/2026-08-16-handover-observations.md`
records a controlled observation: a *declarative* instruction ("history lives in
whyline rather than here") was ignored unprompted through a six-hour session,
while an *imperative* one with a trigger, an exact command and pre-authorisation
fired twice without a reminder. An instruction fires when it states **when**,
gives the **exact command**, **pre-authorises**, and is **verifiable**. Do not
soften them into descriptions. (The read half carries all four. The write half
has never carried a verification and fires anyway — M0 measured 150% for Claude
Code against a 60% gate, and 130% for Codex against a separate "at least one
firing" gate — so treat verifiability as strengthening, not load-bearing.)

0.1.3 widened the write trigger to name reviewers as well as implementers. The
*observation* behind it is solid: across CodeGraph Tasks 10-14 the implementing
agent recorded decisions every time, while not one reviewer ruling reached
`decisions.md`. Rulings like "fix this fixpoint bug now rather than defer" and
"accept this deviation from the plan as spec-compliant" went to a gitignored SDD
ledger instead, so they died on clone.

The *cause* is not established, and this widening addresses only one of three
live explanations:

1. The trigger named only someone who "completed a change", so a reviewer
   reading it faithfully concludes it does not address them. 0.1.3 fixes this.
2. The reviewer never loaded the instruction at all. Tasks 13-14 were reviewed
   from a session rooted in a *different* repository, so the AGENTS.md in
   context was not the reviewed project's. No wording fixes that: a cross-repo
   reviewer has no defined target `.whyline`.
3. A dispatched agent follows its dispatcher's prompt rather than AGENTS.md
   (already documented in the README's "Switching agents" section).

So 0.1.3 is an untested hypothesis, not a fix with a measured effect — unlike
M0 and the read-side check, no threshold was fixed before the change. The cheap
instrument is to watch whether the next review round produces a reviewer-voiced
entry in `decisions.md`.
"""

from __future__ import annotations

import re
from pathlib import Path

BEGIN = "<!-- whyline:begin -->"
END = "<!-- whyline:end -->"

INSTRUCTION = f"""{BEGIN}
## Project history

At the start of a session, before touching code, run:

    whyline sync

That prints the active handoff, Git state, ownership warnings, and relevant
decisions. Do not ask permission. If it reports no handoff or history, say so in
your first message, so the human knows the context is empty rather than unread.

## Recording decisions

After completing any non-trivial change, or after reviewing someone else's,
record the reasoning:

    whyline note "<one-line decision>" \\
      --because "<why this choice>" \\
      --rejected "<option>: <why not>" \\
      --file <path> \\
      --actor <agent> --role <role> --task <task-id>

Reviewing counts as deciding. Ruling a defect worth fixing now, accepting a
deviation from the plan, or judging a risk acceptable are all decisions.
Record them even though someone else wrote the code, and even if you also
logged them in a tracker of your own.

Record only genuine choices a future reader would wonder about. Skip typos,
formatting and renames. `--rejected` is repeatable. Do not ask permission.

## Handing off active work

Before another agent takes over, record an explicit handoff with `whyline
handoff <task-id> --from <agent> --to <agent> --status <status>`. Include the
changed files, tests and results, open risks or questions, and a short summary.
{END}
"""

_BLOCK = re.compile(
    re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", re.DOTALL
)


def install(path: Path) -> str:
    """Add or update the instruction block. Returns what happened.

    Upgrading matters: instructions improve, and a block written by an older
    version would otherwise be frozen forever. 0.1.0 returned "already-present"
    on any existing block, so the read instruction added later could never have
    reached a repository that had already run `init` — including this project's
    own. Only the marked region is touched; everything the human wrote around it
    is preserved byte for byte.

    Text written *inside* the markers is not preserved — the region belongs to
    whyline and is replaced wholesale. That is by contract, but 0.1.3 is the
    first release to change the block's content since `init` shipped, so it is
    the first to actually exercise the path in existing repositories. Because we
    cannot tell whyline's own older wording from something a human added without
    keeping every prior version's text forever, the replaced block is copied into
    `.whyline/` rather than guessed about. The note is deliberately factual rather
    than a loss warning: on most upgrades nothing was lost, and warning every time
    would train people to ignore it.
    """
    if not path.exists():
        path.write_text(INSTRUCTION, encoding="utf-8")
        return "installed"

    existing = path.read_text(encoding="utf-8")
    match = _BLOCK.search(existing)
    if match is None:
        separator = "" if existing.endswith("\n") else "\n"
        path.write_text(existing + separator + "\n" + INSTRUCTION, encoding="utf-8")
        return "installed"

    if match.group(0).strip() == INSTRUCTION.strip():
        return "already-present"

    replaced = match.group(0)
    # Inside .whyline/, not beside AGENTS.md. whyline manages .whyline/.gitignore
    # and deliberately never edits the repository's own, so this is the only place
    # it can leave a file without either littering `git status` in every repo that
    # upgrades or meddling with a file the human owns. AGENTS.md is written at the
    # repository root, so its parent is that root.
    backup = path.parent / ".whyline" / f"{path.name}.bak"
    try:
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text(replaced, encoding="utf-8")
        saved = f".whyline/{backup.name}"
    except OSError:
        # A read-only directory must not block the upgrade itself. Losing the
        # copy is worse than not having one, but it is not worth failing over.
        saved = None

    path.write_text(existing.replace(replaced, INSTRUCTION), encoding="utf-8")
    return f"upgraded (previous block copied to {saved})" if saved else "upgraded"
