# What other updates can be done in Whyline — independent research

Grounded in the current source under `src/whyline/` (5.3k lines across `cli.py`,
`decisions.py`, `resolve.py`, `brief.py`, `sync.py`, `ownership.py`, `gitq.py`,
`account.py`, `model.py`, `hooks.py`, plus the console/TUI/relay layer) and the
README's stated design constraints (no orchestration, no credential handling,
advisory-only ownership). Ideas below are things I'd actually build next, not a
wishlist — each is tied to a concrete gap in the code as it exists today.

## 1. Give `explain` a deterministic link instead of a timestamp-window guess

`resolve.py` reaches HIGH confidence only by matching a note's timestamp against
a git-blame commit's epoch window (`explain()` in `resolve.py:70-225`) — a
genuinely clever heuristic, but still a heuristic: two decisions recorded close
together, or a note written slightly before/after the commit that landed it, can
land on MEDIUM or the wrong entry. `note` and `handoff` already know which files
are affected; they don't know which commit. Adding an optional `--commit <sha>`
to `whyline note` (defaulting to `HEAD` when the tree is clean at note time, and
back-fillable by a lightweight `git commit` post-hook that stamps the most recent
untied note) would let `explain` match on exact SHA first and only fall back to
the epoch-window logic when no commit was recorded. This turns the tool's most
distinctive feature — "why does this line exist" — from probabilistic into exact
for every decision recorded going forward, while keeping the existing heuristic
as the fallback for older history.

## 2. Decisions have no supersede/retract relationship

`decisions.md` is append-only by design (`decisions.py:1-5`), which is right for
auditability, but there's no way to mark a later decision as replacing an earlier
one on the same file. Today, if an agent reverses an earlier call, `brief` and
`explain` will happily surface both the original and the reversal with no
ordering signal beyond timestamp — a future reader (human or agent) has to infer
which one is "live." A `--supersedes <event-id>` flag on `note`, rendered as a
new `**Supersedes:**` field parsed the same way `**Files:**` is (`decisions.py:
92-116`), would let `brief`/`explain` either suppress the superseded entry or
label it clearly. Small addition, closes a real correctness gap in the
committed record.

## 3. Ownership claims never go stale

`ownership.claim()` stamps `claimed_at` (`ownership.py:59`) but nothing ever
reads it back — `conflicts()` only checks for shared files or a shared task
(`ownership.py:18-38`), forever, regardless of age. In practice a claim from
three weeks ago that an agent simply forgot to `release` will keep surfacing as
a live conflict in `claim`, `sync`, and `status` indefinitely, training users to
ignore the warning. Since ownership is explicitly advisory and local
(`.whyline/ownership.json` is gitignored per the README), the fix is cheap: have
`conflicts()` (or its callers) flag claims older than some threshold (e.g. 48h)
as "stale" rather than "active," and let `whyline release --stale` clear all of
them in one shot. This keeps the "advisory, never blocking" philosophy intact
while making the warning meaningful again.

## 4. `explain` and `brief` break silently across renames

`resolve._mentions()` matches a note's recorded path against `rel_path` with
plain equality (`resolve.py:64-67`), and `blame_line()` in `gitq.py:58-85` blames
one literal path with no `--follow`. Meanwhile `commits_touching()` *does* use
`--follow` specifically because "history stops at the most recent rename"
(`gitq.py:90-92`) — the code already knows renames matter for git history, but
that awareness doesn't extend to matching decisions against a renamed file. A
decision recorded against `src/cache.py` becomes invisible to `explain` the
moment that file is renamed to `src/caching/store.py`, even though git itself
can still trace the line's ancestry. Worth resolving the note's recorded path
through the same rename chain `commits_touching` already walks, so old decisions
keep attaching to a file that moved.

## 5. No way to query the decision log

There's `whyline timeline` (mechanical ledger events) and `whyline brief`
(relevance-ranked, token-budgeted, meant for agent context), but nothing meant
for a human to just ask "what has codex decided in the last week" or "show me
every decision that touched `src/cli.py`." `decisions.parse_entries()` already
returns structured dicts with actor/role/task/files/because/alternatives
(`decisions.py:92-141`) — the parsing exists, there's just no CLI surface over
it besides the token-capped brief. A `whyline log [--actor] [--file] [--task]
[--since] [--grep]` command, printing full entries with no budget trimming,
would make the committed record actually browsable instead of only
machine-consumable.

## 6. Codex mechanical capture is still an unverified assumption

The README says plainly: hooks are "Verified against Claude Code only... no
Codex hook event has been observed yet" and `whyline status` reports Codex as
"configured but never observed" until one organically arrives. That's an honest
status quo, but it means the tool's second-most-important pillar (mechanical
capture, layer 2 of 3 in the README's own model) is running on faith for half
its supported agents. A `whyline doctor --fire-test-event` that synthesizes one
hook payload through the real `hook_entry.py` path and confirms it lands in the
ledger would convert "never observed" into a real pass/fail check that runs at
`init` time, instead of waiting on an agent to happen to fire one.

## 7. No Gemini support in account/model detection

`account.py` detects Claude, Codex, Antigravity, and Grok (`detect_codex`,
`detect_claude`, `detect_antigravity`, `detect_grok`); `detect_antigravity` and
`detect_grok` are already PATH-only "installed, not subscribed" checks
(`account.py:97-113`) precisely because those CLIs have no reliable
non-interactive login check. Gemini CLI is in the same boat and is a real
competitor in this exact niche (coding agent with a CLI). Adding
`detect_gemini` on the same PATH-only pattern, plus a `model.py` entry, is a
same-shape addition, not new design — and the console's brainstorm/relay
feature already treats "some models available, others greyed out with a
reason" as a first-class UI state, so a new agent slots in without touching the
console layer at all.

## 8. `decisions.md` has no rotation story for long-lived repos

Every read path (`brief.compose`, `resolve.explain`, the new `log` idea above)
parses the *entire* `decisions.md` on every call — fine at the 19-decisions/
3-days scale the design was measured at, but the file is committed and
append-only forever. A repository that lives for two years will eventually be
parsing thousands of entries on every `sync` call just to rank and discard most
of them. Worth deciding now, while the format is still young: either an index
(`.whyline/decisions.idx.json`, rebuildable, gitignored, mapping id → byte
offset) to avoid re-parsing on every read, or an explicit `whyline archive
--before <date>` that moves old entries to `decisions-YYYY.md` while `explain`
and `brief` search all archive files but the hot path only touches the current
one. Either is a straightforward addition on top of the existing parser; doing
nothing means a silent performance cliff a few years out.

## 9. `whyline explain` has no batch/diff mode

`explain` takes exactly one `path:line` (`cli.py:358-384`, `_split_target`).
The natural companion to `sync` — which already computes `gitq.changed_paths()`
for the working tree (`gitq.py:131-160`) — would be `whyline explain --diff`,
explaining every changed line across the dirty tree in one pass, reusing the
same per-line `blame_line` + note-window logic already in `resolve.py`. That's
the moment a reviewer actually wants "why do these lines exist" — right before
committing or reviewing a diff — not one line at a time.

## Lower-priority / smaller polish

- `ownership.conflicts()` only detects *exact* file-string overlap
  (`ownership.py:24-26`); if a claim is ever extended to accept directories or
  globs, this needs prefix-aware matching or it will silently miss real
  conflicts.
- `note`'s `--rejected "option: why not"` parsing (`events.parse_rejected`,
  `events.py:31-39`) splits on the first `:`, so an option string containing a
  colon (e.g. `"use redis:6379 as cache: too much ops overhead"`) parses wrong
  with no error. Worth a `--rejected-option`/`--rejected-reason` pair as an
  alternative to the single delimited string, or at minimum a warning when the
  option side itself contains a colon.
