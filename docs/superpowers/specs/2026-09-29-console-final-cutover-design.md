# Console Final Cutover Design

**Status:** Approved by user, section-by-section, 2026-09-29.

## Goal

Sub-project #6, the last item on the console roadmap: bare `whyline`
launches the richest console available (mouse TUI, then keyboard console,
then today's plain text menu) instead of always showing the plain
Chat/Relay text prompts -- with the console's own relay mode able to hand
off into `whyline-relay setup` when nothing is configured yet, matching
the parity the plain entry menu already has today.

## Context

Sub-projects #1-5 are all shipped (console foundation, relay lifecycle
views -- #2's model palette turned out already covered by #1 -- the mouse
TUI, and Windows/packaging readiness). This was explicitly deferred until
all of those existed, since there was nothing to cut over to before now.

## Non-goals

- **Removing the plain text entry menu's code.** Per the user's own
  choice, it stays permanently as the zero-extras fallback -- "deprecated"
  means it is no longer the first choice when something better is
  installed, not scheduled for deletion.
- **A console-native relay setup wizard.** The multi-turn interactive
  Q&A (plan source, roles, backup chain) stays exactly as it is today, in
  `whyline-relay setup` -- the console hands off to it via `exec`, per the
  user's own choice, rather than rebuilding it inside the console's
  single-shot event model.
- **Attachments.** Still deferred indefinitely, unrelated to this
  sub-project.

## Decisions

- **FC1 -- `run_entry_menu` gains a priority check before its existing
  logic, purely additive.** Before the "Chat or relay?" prompt: if
  `paths.find_repo_root()` finds a repo (a non-fatal check -- `whyline`
  outside a repo must still fall through gracefully, not hard-exit the
  way `_require_repo()` would) and `tui.TUI_AVAILABLE`, launch the mouse
  TUI; else if `editor.AVAILABLE`, launch the keyboard console; else fall
  through to today's exact text-menu logic, completely unchanged. No
  existing behavior changes for anyone without `[console]`/`[ui]`
  installed, or running outside a repo.
- **FC2 -- Relay setup handoff differs by console flavor, for a real
  architectural reason.** When `/route relay` is chosen and no
  `.whyline/relay/config.toml` exists, both console flavors exec into
  `whyline-relay setup`, matching today's entry menu exactly -- but:
  - **Keyboard REPL**: execs inline, immediately, the same way
    `run_entry_menu` already does today -- no special terminal state to
    unwind.
  - **Mouse TUI**: cannot exec mid-render, since Textual owns the
    terminal's alternate-screen/raw-mode state and `os.execvp` while
    that's active would leave the terminal broken. The app sets a
    deferred-exec flag and calls `self.exit()`; the actual `exec` happens
    in `launch()`, strictly *after* `app.run()` returns and the terminal
    is already restored to normal.
- **FC3 -- The old entry menu is untouched and permanent.** No removal,
  no deprecation warning printed, no behavior change to it at all -- FC1
  simply routes around it when something better is available.

## Architecture

```
run_entry_menu()
  │
  root = paths.find_repo_root()          (non-fatal, FC1)
  if root and tui.TUI_AVAILABLE:
      tui.launch(root); return True
  if root and editor.AVAILABLE:
      repl.run(root); return True
  │
  (unchanged from today, exactly as-is)
  choice = "Chat or relay?" ...

repl.py / tui.py, /route relay with no config.toml present:
  keyboard: exec_fn("whyline-relay", ["whyline-relay", "setup"])   -- inline (FC2)
  TUI:      self._exec_after = ["whyline-relay", "setup"]; self.exit()
            launch()'s own code, after app.run() returns:
              if app._exec_after: exec_fn(*app._exec_after)         (FC2)
```

## Error handling

- No repo root found for bare `whyline`: falls straight through to
  today's existing fallback logic, which has no repo requirement of its
  own -- behavior outside a repo is unchanged.
- The TUI's deferred exec never fires unless the user actually confirms
  the relay-setup handoff -- declining or cancelling leaves the console
  running, same as today's entry menu leaves the shell alone if declined.
- `textual`/`prompt_toolkit` installed but broken in some other way (import
  succeeds, something else fails at launch): surfaces as a normal
  exception, never silently swallowed into a masked fallback.

## Testing strategy

- FC1: with a fake `find_repo_root` and `TUI_AVAILABLE`/`editor.AVAILABLE`
  toggled in every combination, confirm exactly the right one launches;
  every existing `test_cli_chat_delegation.py` test must keep passing
  unmodified (proving the fallback path is untouched).
- FC2 (keyboard): a fake `exec_fn` captures the call when `/route relay`
  is chosen with no config.toml present.
- FC2 (TUI): via Textual's `Pilot`, confirm choosing relay-with-no-config
  sets the deferred-exec flag and calls `self.exit()`, and that the actual
  exec only happens in `launch()` after `app.run()` has returned -- never
  before.
- End-to-end (once built): a real scratch repo with neither extra
  installed still gets today's exact menu; installing `[console]` alone
  switches it to the keyboard REPL; installing `[ui]` switches it to the
  mouse TUI -- the same empirical bar every feature this session has been
  held to before shipping.
