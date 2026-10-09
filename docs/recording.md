# What whyline records

This is the detail behind the README. The landing page is the short version.

## Three layers

1. **git.** `explain` resolves a line to a commit with `git blame`. This works before whyline has recorded anything.
2. **A hook.** `whyline init` can install hooks that record sessions, instructions, and explicit file edits. Every hook path exits 0, so a hook failure cannot fail the vendor session. Claude Code's hook has been observed in real use. Codex's hook is written to `.codex/hooks.json` and does nothing until you approve it in Codex under `/hooks`. Antigravity's hook is written when `agy` is on `PATH` or the repository already has `.agents/`. Grok has no hook.
3. **The agent.** `init` adds an instruction asking the agent to log decisions and rejected alternatives. This is the only layer that captures why.

`whyline status` reports each vendor separately and says "configured but never observed" until a real event arrives. A JSON file on disk is not treated as a working hook.

Trust applies to events that have not happened yet. The Codex session you approve from has already passed its `SessionStart`, so restart Codex once afterwards if you want that event recorded. Later prompts, tool calls, and session end start recording immediately.

## Files

- `.whyline/decisions.md` — committed durable decisions: rationale, rejected options, actor, role, task, and affected files.
- `.whyline/active-handoff.json` — local current task, from/to agent, status, changed files, tests and results, risks and questions, and base and current commit.
- `.whyline/ownership.json` — local advisory task and file claims.
- `.whyline/ledger.jsonl` — local mechanical events and prompt text.

Only `decisions.md` is committed. The other three are gitignored. Stale ownership, a dirty tree, and raw prompts stay on the checkout that produced them. A fresh clone keeps the committed decisions, so `brief`, `status`, and `explain` still work. Those entries carry day precision, so they never justify high-confidence temporal attribution.

`sync` combines the active handoff, current git state, claims, and task- or file-relevant decisions into one nonce-fenced packet. The default budget is about 1,200 tokens. Raw prompt text is left out.

## Credentials

whyline has no API key of its own. `whyline run` replaces itself with the vendor CLI via `exec`, so the work runs on the subscription that CLI is already signed in to: Claude, ChatGPT for Codex, Grok, or Antigravity. You choose the agent and, with `whyline model set` or `/model` in the console, the model for this repository. The vendor CLI accepts or refuses that model.

`account status` shows the plan name for Claude and Codex when those logins are subscriptions. Grok and Antigravity are reported as installed or missing. A CLI signed in with its own API key still launches. whyline does not ask for that key, does not add permission-bypass flags, and does not forward or proxy a vendor token.

For Codex, `account detect` reads `~/.codex/auth.json` and decodes the plan name out of the local id token. For Claude it runs `claude auth status`. The stored result is the plan name (`~/.whyline/account.json` on the machine, `.whyline/account.json` in the repo, both gitignored). The raw token is not written back.

## What stays in your hands

You choose the role and the next agent. `claim` warns on overlap and does not lock a file. `run` hands the terminal over and does not capture or parse the vendor's output.

[whyline-relay](https://github.com/anishmoncivarghese/whyline-relay) is the optional program that does run a plan: it assigns the steps you wrote down and stops when the handoff record says a person is needed. `whyline init` asks before setting that up. The default answer is no.
