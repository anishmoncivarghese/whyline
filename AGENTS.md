<!-- whyline:begin -->
## Recording decisions

After completing any non-trivial change, record the reasoning:

    whyline note "<one-line decision>" \
      --because "<why this choice>" \
      --rejected "<option>: <why not>" \
      --file <path>

Record only genuine choices a future reader would wonder about. Skip typos,
formatting and renames. `--rejected` is repeatable. Do not ask permission.
Store shared project instructions here, but record evolving decision history
through whyline rather than appending it to AGENTS.md.
<!-- whyline:end -->
