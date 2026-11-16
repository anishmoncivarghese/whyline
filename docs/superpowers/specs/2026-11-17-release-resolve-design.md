# Resolve for Release: say what is wrong, offer the fix, and let the user say what they want

Status: draft for review, 2026-11-17. Builds on Release (`whyline.release`), the Ready check (`release/ready.py`), the stopped-release screen with Ask and Fix (`release/ci_failure.py`, RCR), Fix mode's snapshot, guard and undo (`console/fixmode.py`, FIX), and Resolve for a paused relay (`console/recovery.py`). One plan, `release-resolve`, to be written after this is approved.

## What happened on 2026-11-17

Releasing 0.3.75 from `relay/quick-fixes.plan`, the Release window showed `✗ HEAD is behind origin/main` with the advice `Pull or push so that main matches origin/main, then check again`, and Start was disabled.
- The advice was wrong for a release branch: the release's own first step, Bring in main, exists to fix exactly this. (RDF-1 corrects the check; it ships in 0.3.75.)
- Behind it was a real problem the window never showed: bringing in main would conflict in `plans/quick-fixes.plan.md`. The five conflicting lines differed only in `[x]` against `[ ]`.
- It took a trial merge and a hand merge in a terminal to get to Start.

A user without a terminal habit had no way forward from that window.

## Where whyline stands

- **A Ready item** is `key`, `ok`, `text` and one line of `fix` advice. Keys today: `git`, `gh`, `gh-auth`, `origin`, `clean`, `relay`, `synced`, `tag`, `security`, `security-history`, and each target's own (`pypi-workflow`, `pypi-name`, `pypi-version`, the npm, Docker and Homebrew ones). Only `security` has a button.
- **A stopped release** opens `ReleaseFailedScreen`. For a failed CI run it has Rerun failed jobs, Ask an agent, Open run, and after an answer, Fix with an agent (RCR). For every other stop it has only Resume release.
- **Bring in main** that hits a conflict runs `git merge --abort` and stops with `Merge main into <branch> yourself (or ask an agent)`.
- **Fix mode** can snapshot the repository, let an agent work under a guard (no change to HEAD's branch, refs, tags, remotes, config, hooks or ticked tasks), show what changed, and undo it.
- **`source.trial_merge`** lists the files that would conflict without touching anything.

## Problems

1. Advice is a sentence, not an action. The user has to translate it into git commands.
2. One line can't explain a problem with a cause behind it (behind main, because of a conflict, in one file, on five lines).
3. Outside a failed CI run, a stopped release offers no help at all.
4. There is nowhere to say "do it this way instead".

## Part 1: Resolve on every failed check

Each failed line in the Ready list gets **Resolve…**. With several failed, the first one's button is the default.

Resolve opens a window with three things, in this order:
- **What is wrong**, in plain words, with the facts whyline can read for itself (which files, how many commits, which version).
- **What you can do**: one to four buttons from a fixed list for that check. No model is used to produce them. The one whyline recommends is first.
- **Something else**: a box, `Say what you want to do`, which goes to an agent (Part 3).

Every button shows, before anything runs, exactly what it will do, as plain lines and the commands behind them, with **Do it** and **Cancel**. After it runs, the window shows the result, Check runs again by itself, and the line turns to ✓ or shows what is still wrong.

The fixed list:

| Check | What it tells you | Buttons |
|---|---|---|
| `clean` | the changed files, each with its state | **Commit them** (asks for a message), **Set them aside** (a named stash, and how to get them back), **Open** a file |
| `synced`, on the release branch | how many commits behind, or that the two have diverged | **Pull** (fast-forward only). Diverged: explanation, and the box |
| `synced`, on another branch | commits behind, and the result of a trial merge | No conflicts: **Bring in main now**. Conflicts: Part 2 |
| `tag`, `pypi-version`, `npm-version` taken | where the version already exists | **Use <next free version>** (changes the version in the Release window; changes nothing else) |
| `relay` running or paused | which plan and task | **Go to the relay**. For a pause, that relay's own Resolve |
| `gh-auth`, `origin`, target workflow or name missing | what is missing | **Open Set up** at that section |
| `git`, `gh` not installed | the install command | **Copy** |
| `security`, `security-history` | as today | **Security…** (the existing screen) |
| could not reach PyPI, npm or GitHub | the error | **Check again** |

A check with no row here gets the explanation and the box only.

## Part 2: A conflict, shown and settled in the window

When a trial merge finds conflicts, Resolve lists each conflicting file with:
- how many places conflict
- a one-line reading when whyline can tell without a model:
  - `only ticked and unticked tasks differ` (a plan file where each pair of sides is the same line apart from `[x]` and `[ ]`)
  - `both sides added the same lines`
  - `only the version number differs`
- a choice per file: **Keep this branch's lines**, **Keep main's lines**, **Ask an agent**, **Open both**

Rules:
- The choice applies to the conflicting places only. Everything that merges cleanly is merged as git would.
- For a plan file whose conflicts are only ticks, the default is to keep the ticked lines, whichever side they are on. A finished task is never unticked by a merge.
- Any other file has no default. The user picks.
- **Merge now** is enabled when every file has a choice. It makes one local merge commit whose message lists each file and the choice made. Nothing is pushed.
- If the merge does not come out exactly as previewed, it is aborted and nothing has changed.
- **Undo the merge** stays available in the window and in the Release window until the release starts or another commit is made.

The release's own Bring in main step uses the same view when it stops on a conflict, in place of today's "yourself (or ask an agent)".

## Part 3: Say what you want

The box sends the user's words to an agent together with the failed check, whyline's facts about it, and read-only access to the repository.

- **First, a proposal.** The agent answers with the cause as it sees it and numbered steps. Nothing has changed yet. The window shows it with **Do this**, **Change it** (back to the box with the proposal kept) and **Cancel**.
- **Then, the work, under Fix mode.** whyline takes a snapshot, the agent works under the guard, and the window shows the files changed and the commits made, with **Keep** and **Undo**.
- **The guard is not the user's to widen from the box.** Whatever is typed, the agent cannot push, move or delete a tag or branch, rewrite history, change git config or hooks, or untick a task. A request that needs one of these gets the answer `whyline won't do that from here` and the command to run by hand.
- **The agent and model** are the ones Release already uses for Ask an agent, with the same picker.

Files, logs and command output the agent reads are data. Only the text in the box is the user's instruction.

## Part 4: A stopped release

`ReleaseFailedScreen` gets **Resolve…** for stops that are not a failed CI run (those keep RCR's buttons):

| Stop | Buttons |
|---|---|
| Bring in main hit a conflict | Part 2 |
| A check command failed | the last 40 lines, **Run it again**, **Ask an agent** with the output |
| Push refused because the remote has new commits | **Bring them in** (trial merge first, then Part 2 if needed) |
| The tag or the GitHub release already exists | what it points at, **Resume from the next step** when it matches this release's commit; otherwise the explanation and the box |
| The publish workflow failed after uploading | what did get published, and that the release can be resumed from Verify |
| Anything else | the reason, and the box |

After a fix, **Resume release** is the default button.

## Part 5: Where else it shows

- **CLI**, through the same functions: `whyline release resolve` lists failed checks with their options; `whyline release resolve <check> --do <option>` prints what it will do and asks `[y/N]`; `--say "<text>"` is the box.
- **A record.** Each fix that ran is appended to `.git/whyline-release/resolve.log` (when, check, option or the typed text, commits made, kept or undone) and listed in the Release window under **What was resolved**. Fixes that changed the repository are also written as a `whyline note`.
- **Auto mode and the queue.** Resolve never runs by itself. A failed check stops the release as today, and the message says Resolve is waiting.

## Goals

- Every failed Ready line and every stopped release has a next action in the window.
- The 2026-11-17 case is three clicks: Resolve, Keep the ticks (already chosen), Merge now.
- The user sees the exact effect before anything changes, and can undo anything Resolve did locally.

## Non-goals

- Resolve cards in Telegram. `plans/telegram-daily-use.plan.md` (WAIT) sends a card when a release stops; adding the options to that card can follow.
- Resolving a paused relay. That Resolve exists and is unchanged.
- Fixing failed CI. RCR covers it.
- Editing a conflict line by line inside the console. Open both, or ask an agent.

## Anti-goals

- A fix that runs without being shown first.
- Discarding the user's uncommitted work. Nothing here resets, cleans or checks out over a changed file.
- Force-pushing, deleting a tag, a branch or a release, or rewriting history, by a button or through the box.
- A model deciding which side of a conflict wins without the user choosing "Ask an agent" for that file.

## Constraints

- Console first: every action above is in the Release window, with a CLI command over the same function.
- Outward commands go through the release's `run` with argv lists.
- No new dependency. Python 3.11 compatible. Tests use temporary repositories and fake agents, never a real remote or provider.

## Calls I made

- Fixed buttons come first and use no model; the agent is for everything else.
- Ticked tasks win a ticks-only conflict by default.
- Stash is offered for a dirty tree, under the words "Set them aside".
- Undo is a local reset to the snapshot, offered only until the release starts or a new commit is made.
- The typed box cannot loosen the guard.

## Questions

1. **When it runs.** My choice is straight after watch agents and before telegram-daily-use, since every plan ends in a release. Or should it go first, before agent-setup?
2. **Commit them.** For a dirty tree, should the commit go on the release branch as offered, or should Resolve only offer to set the files aside?
3. **Auto mode.** Should the two safest fixes (Bring in main with no conflicts, and ticks-only conflicts) be allowed to run by themselves in auto mode, or always wait for you?
