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

## Discovered mid-design

While working out FC2's exact mechanics, a real pre-existing bug surfaced:
the mouse TUI's Model/Route/History/Help buttons (shipped in 0.3.11) call
`dispatch(session, "/model")` etc. directly, but `dispatch()` has no
concept of slash commands at all -- that handling has only ever existed
inline inside the keyboard REPL's own loop. Today, clicking these buttons
does not do what their label says: "command" mode would try to run
`whyline /model` as a literal subcommand, "chat" mode would send "/model"
as a literal prompt to an agent, "relay" mode hits "unknown relay
command." The shipped tests never caught this because they mocked
`dispatch` itself, proving only that the button *calls* it, never that
the result is meaningful. Typing a slash command into the TUI's own
prompt bar and clicking Send has the identical problem -- it is not
limited to the dedicated buttons. FC4 below fixes this as part of this
sub-project, since FC2's own route-button setup-handoff cannot work
correctly without it -- not scope creep, a genuine prerequisite.

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
- **FC4 -- Slash-command handling is extracted into one shared function
  both consoles call, fixing the bug above.** A new `handle_slash_command(
  session, text) -> SessionEvent | None` in `repl.py` covers `/help`,
  `/status`, `/handoff`, `/history`, `/route`, `/model` -- returning the
  event to render, or `None` if `text` isn't a recognized slash command at
  all (signaling "fall through to ordinary `dispatch()`"). `/exit` and
  `/stop` stay outside it, unchanged, since each means something
  genuinely different per console (`/exit` ends the keyboard loop, meaning
  nothing to the TUI, which has no such command; `/stop` is a real
  cancellation in the TUI but a fixed "nothing in flight" reply in the
  synchronous keyboard REPL -- see the console foundation's own UCF7). The
  keyboard REPL calls this function inline, before falling through to
  `dispatch()`, exactly reproducing its own current behavior (this must
  not change any existing keyboard-console test's outcome). The TUI's
  `_send()` calls it *synchronously on the main thread, before spawning
  any worker* (these are fast, local operations -- no background dispatch
  needed), and its Model/Route/History/Help buttons call it directly with
  their own fixed text, rather than routing through `dispatch()` at all.
  The relay-setup handoff (FC2) is signaled by a new `SessionEvent` kind,
  `"needs_setup"`, which `handle_slash_command` returns instead of
  performing the `exec` itself -- each caller decides how to actually hand
  off (inline for keyboard, deferred for the TUI), keeping the "differs by
  console flavor" mechanics exactly where FC2 already puts them.
  `adapters.relay_is_configured(root) -> bool` (checking for
  `.whyline/relay/config.toml`'s existence directly -- no need to import
  `whyline_relay` just to check a path) is what `/route relay` consults to
  decide whether to switch modes normally or return the `needs_setup`
  event. Matching today's entry menu exactly, no confirmation prompt is
  asked first -- the handoff is immediate.

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

repl.py:
  handle_slash_command(session, text) -> SessionEvent | None       (FC4)
    /help, /status, /handoff, /history  -> event to render
    /route <mode>
      "relay" and not adapters.relay_is_configured(root)
        -> SessionEvent(kind="needs_setup", text=...)
      else -> switches session.mode, event to render
    /model ... -> event to render (today's _handle_model logic, adapted)
    anything else -> None (caller falls through to dispatch())

  keyboard run() loop: handle_slash_command(...) first; if its event has
    kind == "needs_setup": exec_fn("whyline-relay", ["whyline-relay", "setup"])
    else: render the event (or fall through to dispatch() on None)     (FC2, inline)

  tui.py _send(): handle_slash_command(...) first, on the main thread,
    no worker; if kind == "needs_setup": self._exec_after = (...); self.exit()
    else: render directly (or spawn a worker for dispatch() on None)   (FC2, deferred)

  tui.py Model/Route/History/Help buttons call handle_slash_command directly
    with their own fixed text, never through dispatch()                (FC4)
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
- FC4: `handle_slash_command` unit-tested directly -- each of `/help`,
  `/status`, `/handoff`, `/history`, `/model` returns the right event;
  `/route <mode>` with config present switches modes; `/route relay` with
  no config present returns `kind == "needs_setup"` instead of switching;
  ordinary non-slash text returns `None`. Every existing keyboard-console
  test in `test_repl.py` must keep passing unmodified after `run()` is
  rewired to call this function (proving the extraction didn't change
  behavior, only its shape).
- FC2 (keyboard): a fake `exec_fn` captures the call when
  `handle_slash_command` returns `needs_setup` for `/route relay` with no
  config.toml present.
- FC2 (TUI): via Textual's `Pilot`, confirm choosing relay-with-no-config
  (via the Route button, and via typing `/route relay` into the prompt)
  sets the deferred-exec flag and calls `self.exit()`, and that the actual
  exec only happens in `launch()` after `app.run()` has returned -- never
  before. Also confirm the previously-broken case is now fixed: clicking
  Model (or History/Help) with a real config present renders the actual
  expected content, not just proof that some function got called.
- End-to-end (once built): a real scratch repo with neither extra
  installed still gets today's exact menu; installing `[console]` alone
  switches it to the keyboard REPL; installing `[ui]` switches it to the
  mouse TUI -- the same empirical bar every feature this session has been
  held to before shipping.
