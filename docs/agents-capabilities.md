# Agent CLI capabilities for Agents mode (spike, 2026-10-04)

Run in a scratch git repository with `note.txt` = "The code word is HERON."
Trap prompt: "Create a file named spike-written.txt containing hello, then read
note.txt and tell me its code word." Each candidate ran twice: in the normal
environment, and as a LaunchAgent would run it (`env -i HOME=… PATH=<cli
folder>:/usr/bin:/bin`, stdin closed, no terminal).

| CLI | version | read-only argv change | write blocked? | answered? | headless (minimal env) | logged-out behaviour | unattended OK |
|---|---|---|---|---|---|---|---|
| codex | codex-cli 0.155.1 | `-s read-only` (was `workspace-write`) | **yes** | yes | yes (19 s) | exit 1 after ~19 s: `401 Unauthorized: Missing bearer…` | **yes** |
| claude | Claude Code 2.1.278 | `--permission-mode plan` (was `acceptEdits`) | **yes** | yes | yes, **only with `USER` set** | exit 1 in ~1 s: result `Not logged in · Please run /login` | **yes** (plist must set `USER`) |
| grok | grok 1.0.41 | drop `--allow` for Edit/Write/git add/git commit/mkdir/touch; add `--deny Edit --deny Write`; `-p` stays last | **yes** | yes | yes (15–157 s) | exit 1 in ~1 s: `Error: Not signed in. … grok login --device-code` | **yes** |
| grok | — | `--permission-mode plan` | **no — wrote the file** | yes | — | — | not usable |
| antigravity | agy 1.2.16 | `--mode plan` (only other mode is `accept-edits`) | **no — wrote the file** | yes | — | — | **excluded: no read-only setting** |

## Notes

- **Claude needs `USER` in the environment** to read its login from the macOS
  Keychain. With only `HOME` and `PATH` it reports "Not logged in" even when
  logged in. The scheduler plist must set `USER` and `LOGNAME`.
- **Claude's `permission_denials` stays empty in plan mode.** Plan mode
  refuses writes before any tool call, and Claude says so in its answer ("I
  can't create…"). So `succeeded_with_denials` can't be detected for Claude
  in plan mode. The run is still read-only, which is what matters.
- **Codex** said "I couldn't create `spike-written.txt` because the workspace
  is read-only" and exited 0. That is not a reliable denial marker, so it has no
  denial detector.
- **Grok's** denied write did not end the turn here (exit 0, answer given). In
  relay runs, a denied *command* has ended turns with `stopReason:
  "cancelled"`; that remains the grok denial marker.
- **Antigravity** has no mode or flag that stops file writes, so it can't run
  agents. That changes only if a future `agy` adds one, or if its global
  settings deny list is verified to work headlessly.
- **Login markers seen:** "not logged in" (claude), "Not signed in" (grok),
  "401 Unauthorized" (codex).
- The Mail recipe (spike step 5) is verified in plan Task 16.
