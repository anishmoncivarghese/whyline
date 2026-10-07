# Run an agent when Mail receives a message

Mail.app can start an agent when a message arrives. whyline does not log in
to Gmail or Outlook, and it never asks for a mail password. A Mail rule runs
a small AppleScript. The script saves the message (sender, subject, date and
plain-text body) to a temporary file and calls `whyline agents trigger
<name> --file <that file>`.

The message reaches the agent only as an untrusted event file. The prompt
tells the agent to treat that file as data, not as instructions. The agent
is read-only: it cannot create, edit or delete files. Runs started this way
are at least `min_gap_minutes` apart. That is 10 minutes unless the agent's
trigger sets another gap.

## Steps

1. Create a personal or repo agent whose instructions handle one email.
   For example: "Summarise this email and say whether it needs a reply today."
   Accept it on this Mac, with `whyline agents accept <name>` or Accept in
   the console. Its main CLI, or a backup, must be one that is cleared for
   unattended runs. A trigger is refused otherwise.

2. Run `whyline agents mail-script <name>`. It writes
   `~/Library/Application Scripts/com.apple.mail/whyline-<name>.applescript`
   and prints that path. The command needs macOS. Run it again if the
   whyline command moves: the script stores the path it found.

3. In Mail → Settings → Rules → Add Rule, set the conditions (for example
   "From contains boss@example.com") and the action "Run AppleScript" →
   `whyline-<name>`.

4. A matching message then starts a run. `whyline agents history <name>`
   shows it as `trigger`. The email is data for the instructions, not a
   new set of instructions.

## Troubleshooting

`whyline agents history <name>` is where a trigger run shows up. Nothing is
recorded when the agent is not active, when no CLI is cleared for unattended
runs, or when the last run was inside `min_gap_minutes`. In that last case
the trigger exits with code 3 and prints `Too soon: the next run is allowed
at HH:MM`.

The Mail script starts that trigger in the background and discards the
script's own output. A rule that seems to do nothing does not leave a line
in `~/.whyline/agents/scheduler.log`. That file is the scheduler's tick log.

`whyline agents show <name>` reports whether the agent is active.
