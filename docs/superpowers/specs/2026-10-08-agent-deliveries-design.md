# Agent deliveries: email, Telegram and an after-run command

Date: 2026-10-08
Status: draft for review
Repo: whyline (the `whyline.agents` package, the console and the CLI). No
whyline-relay changes.
Builds on: `docs/superpowers/specs/2026-10-04-agents-mode-design.md`
(whyline 0.3.36–0.3.37.1). This spec replaces that spec's section 6 ("Email
via Mail.app — a recipe, not a feature"): delivery becomes a feature.

## Why

An agent's answer today goes to run history, a macOS notification and an
optional report folder. To get it anywhere else, the user wrote a separate
script that converts the report and drives Mail, plus a LaunchAgent to run
it (2026-10-08, the `govt-job-search` agent). The user wants this built in:
when creating an agent, choose where each run's result goes, and have it
arrive there automatically, including on scheduled runs while the console is
closed.

## What the user decided (2026-10-08)

- **Destinations in the first version:** email (through the Mail app) and
  Telegram. ntfy, WhatsApp, Slack and others are later; WhatsApp has no
  simple official route for a personal number.
- **Also an advanced hook:** a command run after each run, for anything the
  built-in destinations don't cover.
- **What is sent on success:** the report as an attachment, plus the
  report's opening lines in the message.
- **Attachment format:** Word (.docx). No PDF (macOS has no built-in PDF
  converter; it would need a browser engine). Markdown (.md) is the other
  choice and the fallback.
- **Conversion:** the `markdown` library (Markdown → HTML, with tables),
  then macOS `textutil` (HTML → .docx). `markdown` becomes a dependency.
- **On a failed run:** a short alert to the same destinations by default;
  per agent it can be set to stay silent.
- **Recipients:** one or more email addresses; one Telegram chat (a private
  chat with the bot or a group the bot is in).
- **Telegram set-up:** one bot per Mac, shared by every agent, set up once
  through a guided screen; the chat is found automatically.

## The honest promise

- Delivery runs on this Mac, after the run, by whyline itself. The agent
  stays read-only and never sees recipients or tokens.
- Nothing passes through a whyline-run server; there isn't one. Email goes
  through the user's Mail app; Telegram goes from this Mac to Telegram's Bot
  API. Telegram bot chats are not end-to-end encrypted.
- Email needs macOS and a configured Mail account. Word conversion needs
  macOS (`textutil`). Telegram works on every system; off macOS it attaches
  the Markdown file.
- A delivery that fails never changes the run's outcome and never loses the
  report.

## Design

### 1. Where delivery settings live: `~/.whyline/agents/deliveries.toml`

Per Mac, never in the agent's own file:

- a repo agent's file is committed, so recipients would leak into git
  (possibly a public repository);
- a command in a repo file would let `git pull` run someone else's command.

One table per agent, keyed by agent id:

```toml
["personal:govt-job-search"]
email = ["anish@example.com", "her@example.com"]
telegram_chat = -1001234567890        # numeric chat id; 0 or absent = none
telegram_label = "Family jobs (group)"
subject = "Daily government job vacancies"   # optional; empty = the agent's label
attach = "docx"                       # "docx" | "md"
on_failure = "alert"                  # "alert" | "silent"
command = ""                          # advanced; empty = none
```

The file is created `0600` (its folder is already `0700`). An agent with no
table has no deliveries, exactly as today. Deleting an agent removes its
table. A repo agent pulled onto another Mac starts with none.

Validation on save: `subject` is one line of at most 120 characters; each email address has one `@` and no spaces or commas;
`attach` and `on_failure` are one of their values; `telegram_chat` is an
integer that appears in this Mac's known chats (section 3).

### 2. After a run: `whyline.agents.deliver.after_run(defn, record)`

Called from `after.finish` for every run (scheduled, folder, trigger and Run
now), after the run record and report are written and independent of
whether a notification is shown.

1. Load the agent's delivery table. None: return.
2. **Succeeded** (`succeeded`, `succeeded_with_denials`): build the
   attachment (section 4) and the summary (section 5), then send to each
   configured destination: email, then Telegram, then the command.
3. **Any other outcome:** if `on_failure = "alert"`, send the alert text
   `"<agent label> <outcome>: <reason>"` (e.g. `govt-job-search timed_out:
   codex ran past 45 minutes`) to email and Telegram with no attachment, and
   run the command (it receives the outcome). `"silent"`: only the command
   runs.
   `skipped` and `missed` outcomes (no run happened) send nothing.
4. Record each result on the run (section 7).

Destinations are independent: one failing does not stop the others.

### 3. Telegram: `whyline.agents.telegram`

Uses the Bot API over HTTPS with the standard library (`urllib`), no new
dependency besides `markdown`.

- **Token:** stored in the macOS Keychain as a generic password, service
  `whyline-telegram`, account `bot-token`, through the `security` command.
  Off macOS: a file `~/.whyline/agents/telegram-token` created `0600`, and
  the set-up screen says so. The token is never written to a log, run
  record or history, and is replaced with `•••` in any error text.
- **Check token:** `getMe` → the bot's username, or a clear error.
- **Find chats:** `getUpdates` → every private chat and group the bot has
  received a message in, as `(chat_id, label)`; labels are the person's
  name `(private)` or the group title `(group)`. Known chats are saved in
  `~/.whyline/agents/telegram-chats.toml` (`0600`).
- **Send:** `sendDocument` with the attachment and, as its caption, the
  subject line followed by the summary (at most 1,024 characters), or `sendMessage` for an alert. Plain
  text only: no `parse_mode`, so nothing in a report is read as formatting.
- **Errors:** 401 → "the bot token was rejected; run Telegram setup again";
  400/403 for the chat → "the bot can't reach <label>"; a network error or
  5xx → one retry after 30 seconds, then "no connection to Telegram".

### 4. The attachment: `whyline.agents.convert`

- `to_html(markdown_text) -> str`: `markdown.markdown(text,
  extensions=["tables"])` in a small HTML page with a stylesheet for
  readable tables (borders, top-aligned cells, small font).
- `to_docx(report_md: Path, out: Path) -> Path | None`: write the HTML next
  to `out`, run `textutil -convert docx <html> -output <out>`; return `None`
  when `textutil` is missing or fails.
- The attachment is written into the run folder
  (`~/.whyline/agents/runs/<run-id>/<agent>-<YYYY-MM-DD>.docx`), so a
  resend reuses it. With `attach = "md"` or when `to_docx` returns `None`,
  the report's Markdown is attached as `<agent>-<YYYY-MM-DD>.md`, and in the
  `None` case the message adds "(Word conversion isn't available on this
  computer, so the Markdown file is attached.)"

### 5. The summary

The report's text from the top down to (not including) its first Markdown
table or fenced block, trimmed to 1,000 characters at a line end, with a
final line `Full report attached.` An empty result uses the first 1,000
characters of the report. Used as the email body's opening and the Telegram
caption.

### 6. Email: `whyline.agents.mail_send`

Through Mail with `osascript`, as the tested script of 2026-10-08:
recipients, subject and attachment paths are passed as arguments (never
spliced into the script text), a new outgoing message is created with
`visible:false`, each attachment is added, then a 3-second delay and
`send`.

- Subject: `"<subject> — <YYYY-MM-DD>"`; alerts:
  `"<subject> failed — <YYYY-MM-DD>"`. `<subject>` is the agent's
  `subject` setting, or its label when that is empty. The date is the run's
  start date. Example: `Daily government job vacancies — 2026-10-09`.
- Body: the summary, then "Sent by whyline from <Mac name>."
- Errors are mapped to plain messages: macOS automation permission denied
  (error −1743) → "allow whyline to control Mail in System Settings →
  Privacy & Security → Automation"; no account → "Mail has no account set
  up"; anything else → the first line of the error.
- Not on macOS: "email needs the Mail app on macOS".

### 7. Recording results and resending

- `RunRecord` gains `deliveries: list[dict]`, each
  `{"to": "email" | "telegram" | "command", "ok": bool, "detail": str}`,
  saved into the run's metadata after delivery.
- `whyline agents history` and the console's Runs list append
  `delivered: email ✓ telegram ✓`, or the failure, e.g.
  `telegram ✗ the bot can't reach Family jobs (group)`. Alerts show as
  `alert: …`.
- Any failed delivery is also listed in the macOS notification for that run
  (when one is shown).
- **Resend:** `whyline agents resend <name> [--run <run-id>]` and a
  **Resend** button in the Runs view repeat delivery for that run with the
  agent's current settings and replace its `deliveries`.

### 8. The advanced command

- Run as `/bin/sh -c "<command>"` in the agent's folder, as the user, with
  a 2-minute timeout, standard input closed.
- Environment: `WHYLINE_AGENT` (name), `WHYLINE_AGENT_LABEL`,
  `WHYLINE_OUTCOME`, `WHYLINE_REASON`, `WHYLINE_RUN_ID`, `WHYLINE_REPORT`
  (path to the Markdown answer, empty on failure), `WHYLINE_ATTACHMENT`
  (the .docx or .md path, empty on failure), `WHYLINE_SUMMARY`.
- Its combined output is saved to the run folder as `command.log`. Exit 0 →
  ok; non-zero or timeout → `command failed (exit N): <last output line>`.
- It is only read from the per-Mac deliveries file, never from an agent's
  own file.

### 9. The console

**New/Edit agent form** gains a "Deliver to" section after Report:

- **Email to:** text field, comma-separated.
- **Subject:** text field, optional, placeholder "the agent's name"; the
  run date is added to it.
- **Telegram:** a Select of this Mac's known chats plus "None", and a
  **Set up Telegram…** button.
- **Attach as:** Word (.docx) / Markdown (.md).
- **If a run fails:** Send a short alert / Stay silent.
- **Advanced: after each run, run this command:** text field, with the
  hint "runs on this Mac only".
- **Send test:** sends `"Test from whyline: <agent label>"` with a small
  sample attachment to each chosen destination and shows each result.

Saving writes the agent file as today and the agent's table in
`deliveries.toml`. The Review text adds one sentence, e.g. "…and email to
anish@example.com, her@example.com and Telegram 'Family jobs (group)', with
a Word file attached. If a run fails, a short alert goes to the same
places."

**Telegram setup screen** (`TelegramSetupScreen`), four steps on one
screen: the BotFather instructions with an **Open BotFather** button
(`https://t.me/BotFather`); a password-style token field with **Check**
(shows "Connected to @<bot>" or the error); "Send any message to your bot,
or add it to a group" with a live list of found chats (polls `getUpdates`
every 3 seconds while open); **Send test message** to a chosen chat and
**Done**. Every button fits 80×24.

**Runs view:** delivery status per run, and **Resend** for the selected run.

### 10. The CLI

- `whyline agents telegram setup`: the same four steps, interactive (token
  read without echo).
- `whyline agents telegram chats`: list known chats.
- `whyline agents deliver <name>`: show the agent's delivery settings.
- `whyline agents deliver <name> [--email a@x,b@y] [--subject "<text>"]
  [--telegram "<label or chat id>"] [--attach docx|md] [--on-failure alert|silent]
  [--command "<cmd>"] [--clear]`: change them.
- `whyline agents deliver <name> --test`: send a test.
- `whyline agents resend <name> [--run <run-id>]`.

## Error handling

- Delivery never raises out of `after_run`: each destination's exception is
  caught and recorded as its `detail`.
- Missing or unreadable `deliveries.toml`: treated as no deliveries, and the
  console shows the reason once.
- A chat id in `deliveries.toml` that is no longer in the known chats: sent
  anyway; a Telegram error is recorded normally.
- Secrets in errors: the token is redacted from every message before it is
  recorded or shown.

## Testing

No test uses the network, Mail, the Keychain, `textutil` or a real
Telegram bot; all are stubbed. Tests pass on macOS, Linux and Windows,
point `HOME` at `tmp_path`, contain no `/Users/` paths, check permission
bits only when `os.name != "nt"`, and press buttons by widget.

- `convert`: a report with a 17-column table becomes HTML with a `<table>`;
  `to_docx` calls `textutil` with the right arguments and returns `None`
  when it fails.
- Summary: stops at the first table; trims at 1,000 characters on a line
  end; falls back for a report with no text before its table.
- `deliveries.toml`: round-trip, `0600`, validation errors, removal on
  delete.
- Telegram: `getMe` ok and 401; chat discovery from `getUpdates` for
  private and group chats; `sendDocument` caption limit and no
  `parse_mode`; 403 message; one retry on a network error; token redacted
  from errors; Keychain read/write through a stubbed `security`.
- Mail: arguments passed separately (an address with a quote in it stays
  one argument); error −1743 mapped to the Automation message; non-macOS
  message.
- `after_run`: success sends the attachment to both; a failure sends an
  alert (or nothing with `silent`); `skipped`/`missed` send nothing; one
  destination failing still runs the others; results land in
  `RunRecord.deliveries`; the run's outcome is unchanged.
- Command: environment variables, 2-minute timeout, `command.log`, exit
  status mapping.
- Resend: replaces `deliveries` for the chosen run.
- Console: the form's Deliver to section saves `deliveries.toml`; Review
  text; Send test results; Telegram setup screen with stubbed API (check,
  found chats, test message); Runs view status and Resend; 80×24 fit.
- CLI: `deliver`, `telegram setup`/`chats`, `--test`, `resend` parse and
  call the service.

**Live check before release (by a person, on macOS):** set up a real bot;
set `govt-job-search` to deliver to an email address and a Telegram chat;
Run now and confirm the Word report and summary arrive in both; set its
timeout to 1 minute, run again and confirm the short alert arrives in both;
restore the timeout.

## Releases

One release: whyline 0.3.38, adding the `markdown` dependency. Built as a
relay plan in `plans/` (Grok implements, Codex tests and reviews), then the
live check above, then the release by a person.
