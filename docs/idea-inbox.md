# Capture ideas from Telegram

Send an idea to a bot and whyline replies in that chat. whyline does not
log in to Telegram as you, and it never asks for your phone number. A chat
id is the number Telegram gives a conversation. It is not a phone number.

The inbox runs on this Mac, from the agents scheduler, while you are logged
in. `whyline idea service on` needs macOS. Telegram keeps undelivered
messages for about a day, so a Mac that was off catches up the next time
it is on and awake.

## A new bot

1. In Telegram, open @BotFather (https://t.me/BotFather), send /newbot,
   choose a name, and copy the token it gives you.

2. Run `whyline idea telegram setup`. Paste the token when asked. The
   paste is hidden. On a Mac the token is saved in the Keychain. Send the
   bot a direct message, allow that private chat, and turn the inbox on.
   The command lists private chats only. It does not offer a group.

   The console does the same setup. Open `whyline console`, choose
   Agents, then Inbox. Allow the private chat and turn the inbox on.
   That writes the same allowlist and starts the same service. A group
   is not on the list. Opening Inbox again leaves a chat that is already
   allowed, and an inbox that is already on, as they are.

3. Send the idea as a normal message. The bot replies with a card.

   Brainstorm opens a settings card (which agents, how many passes, who
   writes the final piece, the backup, and the timeout). Start brainstorm
   runs it. The synthesis comes back as Word and, when this Mac can make
   one, PDF. Edit changes those settings. Cancel on that card leaves the
   idea where it was.

   Quick score scores the idea with one agent and replies with the verdict.

   Cancel on the first card drops the idea.

   After a score, Full report sends the report, Refine asks what to add
   and scores again, Drop asks you to confirm before it drops the idea,
   and Excel sends the workbook.

   When a reply is ordinary language rather than a button, an assistant
   proposes a card. Confirm applies it. Edit asks you to change it.
   Cancel dismisses that proposal and leaves the idea alone.

## A bot you already use

Create a separate bot for whyline and run `whyline idea telegram setup`
with its token.

Reusing a bot is safe only when nothing else reads its messages. That
means no webhook, and no other program polling it. Telegram allows one
of those at a time. A webhook makes Telegram refuse polling, so whyline
sees no messages and doctor says so.

whyline holds one bot token per Mac. Saving a new token also moves
Agents mode's Telegram deliveries onto that bot. Chats found for the old
bot stay on the list, but the new bot can message only chats that have
talked to it.

## Stop

`whyline idea service off` stops the inbox. The scheduler keeps running
for other agents.

`whyline idea telegram deny <id>` stops the inbox reading that chat.
`<id>` is the number `whyline idea telegram setup` printed next to the
chat. It is not a phone number.

## More

[The assistant](assistant.md) covers verbs, approval, memory, reminders
and the morning brief.

## Troubleshooting

`whyline idea doctor` checks the bot token, the allowed chats, whether
the inbox is on, and whether the bot has a webhook. It does not read
messages, and it does not change the webhook.

`whyline idea service status` prints the last time a poll failed. A
conflict means another program is reading this bot's messages, or the
bot has a webhook. The next poll that reaches Telegram clears that line.
