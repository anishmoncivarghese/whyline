# The assistant

The assistant answers messages from your allowed Telegram chats and email
senders. Set up the inbox first: see [Capture ideas from Telegram](idea-inbox.md).
Console steps come first below. The command line is for scripts and comes second.

Run `whyline console`, choose Agents, then Assistant. The screen has Actions,
Reminders, Memory, Morning brief, History, and a Check button.

## Verbs

Send a verb as the first word of a message. Anything else is an idea and is
captured.

| Verb | Example | What it does |
| --- | --- | --- |
| `idea` | `idea an app for swaps` | Captures an idea. |
| `brainstorm` | `brainstorm 3` | Runs a brainstorm on idea 3. |
| `status` | `status` | Shows what is running and what is paused. |
| `run` | `run morning-brief` | Runs a saved agent now. |
| `ask` | `ask agentdock where is retry handled` | Asks about an allowed repository. |
| `summarise` | `summarise` (reply to a message) | Summarises that message. |
| `remind` | `remind in 2h call Sam` | Sets a reminder. Also `remind 17:30 ...` and `remind tomorrow 9:00 ...`. |
| `remember` | `remember my gym days are Tue and Thu` | Saves a fact to memory. |
| `forget` | `forget 2` | Forgets memory line 2. |
| `do` | `do agentdock fix the typo in README` | Starts a relay task. |
| `stop` | `stop 12` | Stops a running job. |

Five more verbs are fixed. They are always on, and `/help` lists them:

| Verb | Example | What it does |
| --- | --- | --- |
| `list` | `/list` | Lists your ideas. |
| `excel` | `/excel` | Sends the ideas as a spreadsheet. |
| `plan` | `/plan 3` | Shows or builds the plan for idea 3. |
| `drop` | `/drop 3` | Drops idea 3. |
| `help` | `/help` | Lists every enabled verb with an example, plus the settings template. |

Unlike the verbs in the first table, these five cannot be switched off and
cannot be given an approval. They do not appear in Actions.

Command line: `whyline idea actions list` shows every configurable verb, whether
it is on, and its approval.

## Approval

- `do` and `stop` change things, so they always need a tap on Confirm. This
  cannot be turned off.
- `brainstorm` needs a tap by default and cannot go lower.
- The rest need no tap by default. Each can be switched off.

Console: in Assistant, Actions, change the On box or the Approval choice and
press Save. A refused change stays open with the reason. Command line:
`whyline idea actions set remind --off`, or `--approval tap`.

## Email provider check

Email is accepted only from allowed senders whose mail passes your provider's
authentication check. whyline needs to know which provider's check to trust.

Console: Agents, Inbox, Email provider check. Type `mx.google.com` for Gmail,
`icloud.com` for iCloud or `mx.microsoft.com` for Microsoft, or the id from
a message's `Authentication-Results` header. Command line:
`whyline idea email authserv mx.google.com`.

Until it is set, email is ignored and Check warns.

## The Mail rule

Mail.app hands each message to whyline through a rule.

1. Console: Agents, Inbox, Install Mail rule. Command line:
   `whyline idea email mail-script`.
2. Open Mail, then Settings, then Rules, then Add Rule.
3. Set the conditions, for example From is an address you allowed.
4. Set the action to Run AppleScript and choose `whyline-idea.applescript`.
5. Save the rule. Allow the addresses with `whyline idea email allow you@example.com`
   or in Inbox.

Check reports `mail rule script` as missing until step 1 is done.

## Memory

Memory is a short list of facts the assistant sees in each turn. Send
`remember ...` or `forget 2`. Console: Assistant, Memory, where you can Add,
Edit, Forget and Clear all. Command line: `whyline idea memory show`, `add`,
`forget <n>` and `clear`.

## Reminders

Send `remind in 30m stretch`. whyline sends the reminder to the same Telegram
chat when it is due. Console: Assistant, Reminders, type the time and text,
then Add; each row has a Cancel button. Command line:
`whyline idea remind list` and `whyline idea remind cancel <id>`.

A reminder more than two hours late, because the Mac was asleep, is sent
with a note saying so.

## The morning brief

Each weekday at the time you choose, an agent called `morning-brief` reads
today's calendar, unread and flagged mail, and due reminders, writes the
brief, and sends it to your Telegram chat. It also offers up to five
suggested reminders as Confirm/Cancel cards. Nothing is created until you
tap Confirm.

Console: Assistant, Morning brief.

1. Press "Grant Calendar access and preview" and answer the macOS prompt.
2. Pick the calendars to include.
3. Press "Grant Mail and Reminders access and preview", answer the prompts,
   and tick the mailboxes to read. No mailbox is read until you tick one. Mail
   must be running; whyline never launches it.
4. Choose the time, the provider that writes the brief, an optional backup, and
   the Telegram chat, then press Create morning brief. Read the warning first.
5. Press Check. It reports Calendar, Mail and Reminders access, whether Mail is
   running, whether the agent exists and is accepted, the last brief's
   outcome, and the next run.

Command line: `whyline idea brief calendar --preview`, `brief mail --preview`,
`brief tasks --preview`, then
`whyline idea brief setup --at 07:00 --runner claude --chat <id>`, and
`whyline idea doctor` for the checks.

### If the Mac sleeps at the brief time

A sleeping Mac cannot run the brief. Check shows a hint. Either set a
scheduled wake in System Settings, Battery (or Energy), Schedule, or run this
yourself, a few minutes before the brief time:

    sudo pmset repeat wakeorpoweron MTWRF 06:55:00

This is your choice. whyline never runs it.

## Limits

- The Mac must be on and awake. A brief or reminder due while it sleeps runs
  when it wakes, or is skipped if it is too old.
- Telegram keeps undelivered messages for about 24 hours. Messages you sent
  while the Mac was off for longer than that are lost.
- The provider you choose (Claude, Codex, Gemini and so on) has its own terms
  of use. Check that unattended, scheduled use is allowed on your plan.
- The brief sends your calendar, email excerpts, reminders and memory to that
  provider, and the result goes through Telegram. Do not put anything in memory
  you would not send to both.
- The assistant never sends email or messages to other people, and never
  creates, accepts or edits calendar events. Suggested reminders are only
  whyline reminders.
