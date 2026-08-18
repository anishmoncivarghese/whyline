<!-- whyline:begin -->
## Project history

At the start of a session, before touching code, run:

    whyline brief

That prints what previous agents decided and rejected on this project.
Do not ask permission. If it reports nothing recorded, say so in your first
message, so the human knows the history is empty rather than merely unread.

## Recording decisions

After completing any non-trivial change, or after reviewing someone else's,
record the reasoning:

    whyline note "<one-line decision>" \
      --because "<why this choice>" \
      --rejected "<option>: <why not>" \
      --file <path>

Reviewing counts as deciding. Ruling a defect worth fixing now, accepting a
deviation from the plan, or judging a risk acceptable are all decisions.
Record them even though someone else wrote the code, and even if you also
logged them in a tracker of your own.

Record only genuine choices a future reader would wonder about. Skip typos,
formatting and renames. `--rejected` is repeatable. Do not ask permission.
<!-- whyline:end -->

## Project instructions

Keep shared project instructions in this file. Record decision history with
`whyline note`, not by appending to this file — the earlier declarative form of
this line was measured being ignored, so it is stated here as a direction rather
than as a description.
