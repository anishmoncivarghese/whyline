# Relay chat

Ask a question about a running relay and get an answer from a read-only agent.

## What it answers

The **Chat** tab (in Relay, next to All files) and `whyline ask` answer
questions such as "What's it doing?", "Why did it stop?", "Plan progress" and
"What's changed?". The agent sees a snapshot of the relay's state: the plan,
the latest handoffs, recent decisions and the changed files. Paths written as
`path:line` in an answer open the file in the console.

## Read-only, and it never disturbs the relay

Chat never stops, steers or slows the relay. The answering agent runs in a
read-only mode, cannot edit files, and works from a snapshot instead of the
relay's own state files. Its Stop button cancels only the question you asked.

## Quota

The answering agent uses your subscription like any other turn. Chat prefers an
agent that is not working on the relay. If none is spare, the reviewer answers
and the tab says "shares quota with the relay"; your questions then count
against the same limits as the relay's work.

## History

Each repository and relay run has one JSONL file under
`~/.whyline/relay-chat/<repo>/<run>.jsonl`. Clearing a conversation renames the
file aside; it is not deleted. Settings are in
`~/.whyline/relay-chat/settings.toml`.

## Settings

In the console, open **Settings → Relay chat** and press Save:

- **Agent**: Automatic, or one installed agent with a read-only mode.
- **Time limit**: minutes per answer; 0 means no limit.
- **Snapshot size**: how many characters of relay state the agent sees.

## From a terminal

```
whyline ask "why did it stop?"
whyline ask --history
whyline ask --clear
whyline ask --set-agent claude --set-timeout 300 --set-snapshot-chars 40000
```

`--set-timeout` takes seconds; the console shows the same value in minutes.

## Changing agents while a relay runs

While a relay runs, **Agents for this run** (in Relay) changes who does the
work without stopping it. Press Save and only what you changed is applied; if
one change is refused, the message shows and the others still apply. Tick
**Keep for future runs** to also write the change to the relay's
`config.toml`; otherwise it lasts for this run.

| Change | Applies |
|--------|---------|
| A role's agent (implementer, tester, reviewer) | From the next turn |
| A role's or backup's model | From the next turn that agent takes |
| Timeout (minutes, `0` for none) | From the next turn |
| Round cap (1 to 99) | From the next check; a cap below the current round is refused |
| Backups: order, and which are used | The next time a backup is needed |

Every model dropdown has **Default** (the CLI decides), the models whyline
knows for that agent, and **Other…** for a typed id. **Refresh models**
refreshes the lists without losing your selection. A backup that also holds a
role shows that role's model and `same as its role`. The plan itself stays as
it is while the relay runs. Relay **Set up** offers the same model lists,
including a model for each backup.
