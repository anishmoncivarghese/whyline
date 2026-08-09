# Source-session truth

The prior agent decided on parse-then-swap: build a temporary dictionary, validate uppercase/underscore keys and duplicates, then assign the complete dictionary under the existing lock. Split with `partition("=")` or `split("=", 1)` so values retain equals signs. Empty lines are ignored; malformed lines and empty keys fail without mutation.

Critical miss: mutating `_values` while parsing, which violates rollback and atomic visibility.

