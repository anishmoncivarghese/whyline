# Does the decision layer actually work?

Moved here from the README so the landing page can stay short. The numbers below are the original measurement. They have not been re-run.

It was the design's one unproven assumption, so it was measured before the features depending on it were built. Over three days across two agents on a real project, 19 decisions were recorded across 14 commits — Claude Code 150% of its non-trivial changes against a 60% gate, Codex 130% against a separate "at least one firing" gate. Every one carried a rationale and a concrete rejected alternative. Codex was never reminded.

**That rate holds when an agent works directly, and not when it is dispatched.** A later orchestrated task in the same repository recorded nothing at all, because a dispatched agent follows its dispatcher's prompt rather than `AGENTS.md`. The figure above is a property of direct work. That is why the README recommends `whyline run` from your own shell, with each agent owning its session.

The read side was measured separately, because writing a record nobody consults is worthless. Claude Code ran `whyline brief` unprompted near the start of 3 of 7 sessions it owned — **43%**, below the 50% threshold fixed before collection. The result is **unreliable**: use `run` when the handoff must happen, and treat repository-instruction reads as a useful fallback. Codex was observed calling `brief` nine times, but no reliable Codex session denominator was available, so that count is not presented as a rate. Earlier 67% and 50% figures were superseded as the sample grew.

**Reviewers record less than implementers.** Across five tasks on one project, the agent implementing recorded every time, while not one ruling by the agent reviewing reached the record — those went to a tracker that was not committed, and died on clone. 0.1.3 widened the instruction to name reviewers explicitly. Whether that works is not yet measured, and at least two other causes are plausible, including that a reviewer working from a different repository never loads the project's `AGENTS.md` at all.

Full method and caveats: [`m0/RESULTS.md`](../m0/RESULTS.md).
