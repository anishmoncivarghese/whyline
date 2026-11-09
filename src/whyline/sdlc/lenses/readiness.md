# Lens: readiness

Ask whether an implementer could start now without making a design decision.

- Is every choice already made, with nothing left as "decide later" or "or similar"?
- For a plan, each task:
  - names its files and its tests;
  - has a `covers:` line;
  - is small: at most about 5 numbered steps and 4 source files;
  - if it is a guard or security task, has a closed Review focus list.

## Rules

- You are read-only. Do not edit, create or delete anything.
- You have not seen how this document was written. Judge only what is on the page.
- Report only problems. Do not praise or summarise.
- Write exactly one line per finding, in this form:
  `- [blocker|major|nit] <section> — <problem> — <suggested fix>`
- If you find nothing, write the single line `No findings.`
