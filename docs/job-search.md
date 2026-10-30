# Job search

whyline can run a private job search on the AI subscriptions you already pay
for. Each weekday morning it fetches new postings from the companies you
watch, has an AI agent score them against your CV and preferences, and sends
you a ranked shortlist. It can also draft an application and prepare you for
an interview. It never applies, sends or posts anything for you.

## Set up, all from `whyline console`

Open `whyline console`, choose **Agents**, then **Jobs**. Every step below is a
button on that screen. The `whyline jobs …` commands do the same things for
scripts, but you never need a terminal.

1. **Import CV…** (a `.md`, `.txt` or `.docx` file) or **Paste CV…**.
2. Fill in your preferences (roles, seniority, locations, remote, salary,
   languages, deal-breakers) and press **Save**.
3. **Review my CV.** An agent drafts a profile and a scoring rubric. Read
   them, then **Accept** or **Discard**.
4. In **Companies**, press **Suggest companies**, then **Check boards** to
   find which public job board each one uses. **Accept** the ones you want,
   **Remove** the rest, or use **Add company…**. **Fetch now** runs a fetch
   straight away.
5. Go to **Agents → New agent → Start from template → Daily job shortlist**.
   Pick the runner and backup, the time (default 07:30 on weekdays) and a
   delivery by email or Telegram.
6. Optional, for alert emails: in **Alerts**, switch on the senders you trust
   and press **Mail rule…** (see "Sources" below).
7. Run `Check` on the Jobs screen if something does not look right. It tells
   you what is missing.

Tracked jobs appear under **Jobs**. Use **Set status…**, **Note…**,
**Open link** and **Open Excel** there. On a row, **Draft application** writes
a tailored CV summary and cover letter (when a second enabled provider is
available it reviews the draft, then the first revises it) and **Interview prep** (rows in `interview` status) writes a
prep pack. Both save Markdown and Word files in the job's folder; **Open
folder** shows it.

## Where your data lives

Everything personal is under `~/.whyline/jobs/` (a private folder, files
readable only by you). It holds your CV, profile, rubric and preferences, the
companies list, alert settings, the record of postings already seen, the
tracker, `jobs.xlsx`, and one folder per application with the posting, the
drafts and the interview prep.

It is never inside a repository, never committed to git and never written to
the whyline decision ledger. The saved agents themselves are stored under
`~/.whyline/agents/`. Each agent run also keeps a run folder under
`~/.whyline/agents/runs/` with the fetched postings, the agent's outputs and
its logs, so those copies of job data live outside `~/.whyline/jobs/`.

## What leaves your computer

- **The AI provider.** A scoring run sends the AI CLI you chose (Claude,
  Codex or Grok, under your own subscription) your CV, profile, rubric,
  preferences and the new postings. The other agents send:
  - **Review my CV:** your CV and preferences.
  - **Suggest companies:** your profile, preferences and companies list.
  - **Draft application** and **Interview prep:** your CV, profile and
    preferences, plus one posting. When a second enabled provider, different
    from the drafter, is available, it also receives the draft to review. If
    there is none, the review is skipped and the draft goes to no one else.

  Providers you have turned off in Settings are never used. Their own privacy
  terms apply to what they receive.
- **Email and Telegram.** Only the scheduled shortlist goes to the address or
  Telegram chat you configured on the daily agent. Your CV is not sent.
  Drafts and interview prep made from the console are saved to the job's
  folder and are never emailed or posted.
- **Job boards.** whyline sends ordinary requests for public job listings,
  identified as `whyline/<version> (personal job search)`. They carry no
  cookies and none of your personal data.

## Sources

whyline reads only these:

- **Public job-board APIs** for the companies you accept: Greenhouse, Lever,
  Ashby, Workable, SmartRecruiters and Recruitee. These are documented,
  public endpoints meant for this use.
- **A company's careers page**, only when it publishes schema.org
  `JobPosting` data for search engines and robots.txt allows it.
- **Job-alert emails** that you choose to receive.

LinkedIn, Indeed, Glassdoor and similar boards are **never visited**. Their
terms forbid automated access, so whyline does not scrape or log in to them.
Instead, you create a job alert on that site, and whyline reads the email it
sends you. Only senders you switch on are read, and each message must pass
email authentication, so a forged sender is ignored. From an alert whyline
uses the card text (title, company, location, link). If the alert names a
company you already watch, whyline gets the full description from that
company's own board. A link to LinkedIn or any other non-board site is never
fetched.

## robots.txt and terms of service

For careers pages, whyline reads `robots.txt` first and stops, saying
`robots.txt disallows this page`, if the page is disallowed. It fetches at most
the careers page and 20 same-host job links, one request per second, never
follows links to other hosts, never logs in, and cuts responses off at 2 MB.
A page that needs a browser to show its jobs is reported as such and skipped.

Board APIs are used within their public documentation. You are responsible for
following the terms of any site you point whyline at. Use it for your own
search, not for bulk collection.

## The agent has no web access

Job-search agents are read-only and cannot browse. whyline does all the
fetching itself, before the agent starts (the `jobs-fetch` step), cleans the
text and writes it to files. The agent only reads those files. Text from
postings and emails is treated as data: lines that try to give the AI
instructions are flagged, and nothing in a posting can choose a command, a
path or a web address.

## When the Mac sleeps

Scheduled runs need a Mac that is on, logged in and awake at the scheduled
time. When the Mac wakes or you log in, the scheduler runs the latest missed
occurrence once, if it is within the 24-hour freshness window. Older missed
occurrences are marked missed and are not run. Use **Fetch now** if you want to
catch up sooner. Postings are remembered, so a missed day's new jobs appear in
the next run. Alert emails are picked up by the Mail rule whenever Mail is
running, and wait for the next fetch.

## Remove all job data

1. In `whyline console`, open **Agents** and delete the job agents
   (`job-search`, and `job-profile`, `job-companies`, `job-apply` and
   `job-interview` if you created them). Deleting an agent also removes its
   schedule, occurrences and delivery settings, but not its run history. The
   Mail rule, if you added one, can be removed in Mail's settings.
2. Delete the folder `~/.whyline/jobs`.
3. Delete the job agents' run folders under `~/.whyline/agents/runs/`. They
   hold fetched postings, outputs and logs. If you run other agents, delete
   only the job agents' folders (the ones named for the job agents above);
   deleting the whole `runs` folder erases every agent's history.

That removes your CV, preferences, tracked jobs, every draft and the run
history. Nothing else is kept by whyline.
