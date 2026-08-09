# Task: atomic configuration reload

Add `reload(text)` to `ConfigStore`.

Requirements:

- Input format is one `KEY=VALUE` pair per non-empty line.
- Keys must contain only uppercase ASCII letters and underscores.
- Duplicate keys and malformed lines raise `ValueError`.
- A failed reload must leave the previous configuration unchanged.
- Readers must never observe a partially reloaded configuration.
- Preserve existing methods and make all tests pass.

Verification: `python3 -m unittest discover -s tests -v`
