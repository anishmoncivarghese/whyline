# Making Whyline known

Independent pass, 2026-10-10. Audience for this note: the maintainer. Karma on hand: Hacker News 3, Reddit 8.

The goal worth pursuing is that a developer who already runs two coding-agent CLIs on one repository can find Whyline, install it, and trust it. "Everyone knows the name" is a different goal, and this product is a poor fit for it. The category of agent memory and agent orchestration is crowded. GitHub's daily trending conversation in late September 2026 was already full of those tools. Whyline's own README says the tool does not orchestrate, does not assign roles, and does not supervise. Public copy should sound like that README.

## What is actually true, and therefore safe to say

The public project is real and installable.

- Repository: <https://github.com/anishmoncivarghese/whyline> (on the order of 515 commits; Apache-2.0).
- Package: `whyline` 0.3.37.1 on PyPI, uploaded 2026-10-08. `pip install whyline` resolves. The README's install line is `uv tool install whyline`. Both are valid because the package publishes a `whyline` console script. `uvx` is the wrong default: it does not leave a durable binary for hooks.
- The demo that survives a skeptical reader is `whyline explain path:line`, which prints the decision, the reason, the rejected alternative, and a confidence line. The second demo is an explicit handoff: `whyline run` attaches history, because an agent remembering to read is unreliable.
- The published measurement in `m0/RESULTS.md` and the README is small and already caveated. Write side: 19 decisions across 14 commits, one repository, one operator, three days (2026-08-14 to 2026-08-17); every decision had a because and a rejected alternative; Codex was not reminded. Read side: Claude Code called `whyline brief` near the start of 3 of 7 sessions it owned, 43 percent, below a threshold of 50 percent that was fixed before collection. Codex reads were observed without a session denominator, so they are not a rate. A dispatched agent recorded nothing, because it follows the dispatcher prompt rather than `AGENTS.md`. Reviewer-voiced decisions were a known gap; the README says the later wording change is not cleanly measured.
- `phase0/STATUS.md`, updated 2026-08-09, still lists recruitment and ten measured sessions as unfinished. The recruitment message in `phase0/recruitment-message.md` is already written and is privacy-safe. If sessions happened after that status file, use them. The file as it stands does not show an external user.

Three facts will be weaponised if the launch copy is sloppy, so they belong in the first comment of any thread.

1. The 43 percent figure has a denominator of seven sessions and one operator. The honest use of it is "we set a bar, missed it, and routed handoff through `whyline run`." A graphic that drops the denominator becomes the story, and the story becomes a correction.
2. Codex mechanical hooks are unverified. The README says `init` writes `.codex/hooks.json` and that no Codex hook event has been observed. Codex did record decisions through the instruction file. Those are different claims. The first commenter who runs `whyline status` will see the difference.
3. The name is already taken in two ways that this audience knows. Amy Ko and Brad Myers's Whyline (CHI 2004, CMU) is a debugger for "why did" and "why didn't" questions about program output; the Java archive is still public at `amyjko/whyline`. Separately, npm has had `@malindar/whyline` since May 2026 ("Git remembers what changed. Whyline remembers why.") and `@sal-sovereign-ai-labs/whyline` since September 2026. The PyPI name `whyline` is this project. The bare word is not. Every public page needs one disambiguation sentence: a git-committed decision log and handoff for coding-agent CLIs, unrelated to the 2004 debugger and unrelated to the npm packages.

Windows is unverified. The relay spends the user's subscription quota and is off unless asked. Shipping several releases a day (0.3.30 through 0.3.37.1 between 4 and 8 October 2026) means a launch week needs a pinned version. A reader who installs "latest" during a thread and hits a same-day break will say so in the thread.

## The karma constraint, as the sites actually enforce it

Karma 3 and karma 8 are a constraint on two broadcast forums. They are not a constraint on distribution.

### Hacker News

Primary pages, read 2026-10-10:

- Guidelines: <https://news.ycombinator.com/newsguidelines.html>
- Show HN: <https://news.ycombinator.com/showhn.html>
- The restriction notice: <https://news.ycombinator.com/showlim>

`showlim` says Show HN is temporarily restricted because of a massive influx, mostly from people who are not yet familiar with the site, and that the way through is to become a contributor and then post an occasional Show HN. There is no published number. Daniel Gackle has described it as not a checklist. An account at karma 3 has almost no history, so a Show HN submission is likely to be refused with some variant of "temporarily restricting Show HN" or "your account isn't able to submit this site." Public threads through spring and summer 2026 show that emailing `hn@ycombinator.com` to be let through sometimes gets a reply and sometimes sits. One moderator comment said a genuine self-made project can be mailed in. That is a moderation mailbox, not a promotion channel.

Rules that matter for this launch:

- Using the site primarily for promotion is against the guidelines. Occasional posts of one's own work are allowed.
- "Don't post generated text or AI-edited text. HN is for conversation between humans." The same page bans automated posting. A model-written Show HN, including a light edit of one, is a rule break. The posts in this plan have to be written by the maintainer, in the maintainer's sentences.
- Soliciting votes or comments is banned, and the penalty people report attaches to the submission and the domain. Friends told to star, upvote, or "go comment" are the pattern the software looks for.
- Deleting and reposting is banned. A story that received significant attention is a duplicate for about a year. A story that received none can be tried again in small number, later, with a real reason.
- Show HN is for something people can run. Blog posts, signup pages, and newsletters are ordinary submissions, not Show HN. A major version bump is generally not a Show HN.
- The second-chance pool is moderators and reviewers pulling overlooked stories back. It is not an application. Public discussion of the pool treats "please second-chance my post" as the wrong email. Email `hn@ycombinator.com` when a post was killed by mistake.

A secondary write-up of an open Show HN dataset (about 208,000 posts) put the median post at 2 points, one of them the author's, and about 4 percent of posts above 30. Treat that as orientation, not as an official statistic. A quiet Show HN is the common outcome. It is not evidence the project failed, and it is not a reason to repost the next morning.

### Reddit

Reddit has no single karma gate. Each subreddit's AutoModerator is its own law, often unpublished. Guides in 2026 commonly tell founders to reach on the order of 200 comment karma before promotional posts, because many large subs filter new or low-karma accounts silently. Karma 8 will fail a lot of those filters. A burst of generic answers in unrelated subs is the pattern called karma farming, and it draws bans.

Subreddit rules, from public rule text reviewed by third parties in May–July 2026. Re-read the live rules the day of posting. They move.

- r/programming (millions of members) forbids product promotion and "I made this" demos. A technical write-up of something difficult or educational is allowed. A GitHub link with a feature list is not. This is the only large programming sub that fits, and only for the measurement essay.
- r/SideProject allows sharing your own work, usually with disclosure in the title or first line. It is a reasonable place for a feedback post. It is a weak place to become known. Launch posts are the default content there, so a bare link sinks.
- The sitewide culture people cite is roughly 90 percent ordinary participation and 10 percent mention of one's own work. Cross-posting the same text the same day is the spam shape.

Answer people who describe the blank-second-agent problem. Mention the tool in a reply when it is the direct answer, with a disclosure. Build karma as a side effect of that. There is no honest weekend sprint from 8 to "safe."

### Lobsters

<https://lobste.rs/about>, read 2026-10-10. Invite-only. New accounts are green for 70 days and cannot submit a domain the site has not seen, with GitHub among the domains that already exist. Self-promotion should stay under about a quarter of one's stories and comments. The `show` tag is one of the tags new users cannot use. This is a month-two channel at the earliest, after an invite, and only once ordinary comments outnumber the Whyline post.

## Where attention can come from without karma

Ranked by fit to a local Python CLI whose user already has Claude Code and Codex installed.

1. **Inside the tools.** In 2026, Claude Code and Codex discover utilities through plugins, skills, and curated lists. `hesreallyhim/awesome-claude-code` (the list people treat as the curated one) takes recommendations through its web issue form, not a pull request, asks for human submitters, wants the resource older than 14 days with commits after the first day, and wants a one-line description with no pitch and no emoji. This repository qualifies on age. A one-line entry plus a small skill that tells the agent the exact `whyline note` / `whyline sync` commands is how the target user meets the tool while already working. The skill text has to repeat the README's honesty: reads are best-effort, `whyline run` is the reliable handoff. A plugin that pretends the 43 percent problem is solved will be caught.

2. **A human-written measurement essay, submitted as a normal story.** The interesting claim is the negative result and the product change it caused. Write side cleared a precommitted bar. Read side missed a precommitted bar. The tool therefore pushes context with `whyline run` instead of hoping `AGENTS.md` is read. That is a curiosity post. It can go to Hacker News as an ordinary link once the account can submit links, and to r/programming as a write-up if the live rules still allow that. The tool link sits at the bottom, once. Show HN of the repository comes later, and only if `showlim` lets the account through.

3. **Replies to the pain, in public.** Search for people describing a second agent starting blank, or a reviewer losing the reason a change was made. Answer the specific case. One terminal recording is enough. A launch-day mention blast is the thing to skip.

4. **Newsletters that accept a tool or a link by email, after the essay exists so an editor can see a discussion.**
   - Console.dev: `hello@console.dev`. They review developer tools and say they do not do sponsored reviews. They want something a person can try. Pitch the essay and the install line.
   - PyCoder's Weekly: Python CLI, project-link submission. Expect a listing at most.
   - Changelog News has a submit form and has historically turned away tutorials and commercial product posts. The essay is the closer fit. A directory roundup dated 2026-10-07 reported the newest issue it could see was from April 2026, so confirm the publication is actually shipping the week you write.

5. **Terminal Trove** (<https://terminaltrove.com/submit/>). Criteria include an image preview (PNG, GIF, or MP4) and per-platform install commands, and the form asks that the tool exist in the package repositories you name. macOS and Linux are the honest platforms. A 20-second recording of `explain` and a handoff is the asset. Homebrew can be one of the install lines once a formula exists. The directory is a catalogue, not a launch.

6. **Five external users, then a second essay.** The phase0 screener already describes the person: an agent CLI at least three days a week, two or more coding-agent products recently, synthetic or their own non-confidential repo. Five people who keep a `decisions.md` for two weeks are the proof a podcast or a follow-up post needs. The Changelog guest/topic form (`changelog.com/request`) is the right podcast pitch, and only after one of those people will be named or quoted. Ten formal sessions remain the research plan in `phase0/STATUS.md`. Five public users are the distribution plan. They are allowed to be a subset.

7. **Homebrew, pipx, and a pinned release.** Add `pipx install whyline` beside the uv line before any post. Many readers will not install uv to try a CLI. A Homebrew formula is a trust signal and a Terminal Trove checkbox. Cut it against one chosen version during launch week, then bump on purpose. Daily 0.3.x publishes and a formula fight each other.

Lower priority, in this order: DevHunt (a dev-tool launch board; fine as a listing, weak as a plan), a personal post on DEV or a similar blog under the maintainer's name, Lobsters after an invite and a comment history. Product Hunt reaches a broader audience and converts poorly for a terminal tool; a listing months later is optional. AlternativeTo fits products that replace a named product. Whyline does not. Paid slots on TLDR and similar newsletters are a later decision, after a stranger has kept the tool. Coordinated star pushes, "share with your network" posts, and outreach to aggregators that scrape GitHub trending are omitted on purpose. Trending is a consequence of a real thread. Language-specific trending pages have included repositories with only a handful of new stars on quiet days, so there is no star count to buy, and a count you organise is the HN penalty case.

## Ninety days

Assume the week of 2026-10-13 as week 1. Slip the public posts if the external users or the pinned release slip. Do not slip them in order to "catch a news cycle."

### Weeks 1–2. Become postable, and make the trial short

No post whose subject is Whyline.

- Freeze a release. Smoke `pipx install whyline` and `uv tool install whyline` on a clean machine. `whyline init` in a fresh git repo, then `whyline explain` on a line that has a recorded decision.
- Put three things on the README's first screen: the Ko / npm disambiguation sentence, the pipx line, and a still or GIF of `explain`. State macOS and Linux. State that Codex decision logging was observed and Codex hook events were not.
- Publish a tiny demo repository a stranger can clone and run `whyline explain` in, with a committed `decisions.md` and no agent login required. Show HN's guideline is that people should be able to try the thing without a signup. An agent subscription is a signup-shaped barrier. `explain` on a fixture avoids it.
- Send the existing recruitment message to developers who already use two agent CLIs. Target five conversations, not a public call for users.
- Hacker News, four days a week: comments on threads about git history, ADRs, measurement, or coding agents, where you have a concrete thing to add. No link. No "I built." Stop any day the only reason to comment is the karma number.
- Reddit: read the live rules of two subs, then do the same kind of commenting. A Claude-or-Codex community and one programming community is enough. Leave if the rules restrict new accounts.

Exit test: the account can submit an ordinary link, or you know from a real attempt that it cannot. You also have the demo repo and the GIF.

### Week 3. The essay

Write it yourself. Outline, so the post is yours:

- What you believed an instruction file would do.
- The bar you wrote down before collecting (60 percent write-side on Claude, at least one Codex firing, 50 percent unprompted reads).
- What happened, with the denominators and the single-operator limit in the same paragraph as the percentages.
- The dispatched-agent miss, in a sentence.
- What you changed: `whyline run` carries the packet; instruction-file reads stay a fallback.
- One link to the repository and the install line, after the result.

Submit the essay URL to Hacker News as a normal story, title close to the essay's own title, no "you won't believe," no number stuffed in for effect. The guidelines ask submitters to crop gratuitous numbers. If the account cannot submit, mail `hn@ycombinator.com` a short note that the account appears restricted, with the URL, and ask what they want you to do. Then wait.

The next day, post a different wording in the one Reddit community whose rules allow a technical write-up. First line: you built the tool the essay measures. Stay for the afternoon. Fold corrections into the README. Do not post the essay anywhere else that day.

### Weeks 4–5. Only the thread

Answer comments. Change the README where a comment found a real hole, especially the Codex hook sentence and the sample-size sentence. Collect the five users if they have not started. Do not submit the repository as Show HN in these two weeks. Do not delete the essay submission if it sits at the bottom of `/newest`.

### Week 6. Show HN, if the account is allowed to

Title shape: `Show HN: Whyline – why a line of code exists, for the next coding agent`.

The first comment, written by hand before you submit, covers: `pipx` and `uv` install, `whyline init`, the demo repo, what the tool refuses to do, the 3-of-7 read result, the 2004 Whyline disambiguation, and the Codex hook status. Submit on a weekday morning US time, and keep the afternoon clear. That timing is custom, not a rule.

If the post sits at one or two points, leave it. That is the ordinary result. A later submission has to be a different artifact, such as the external-user essay, and only after a long gap.

The same week, if the GIF and the pinned install lines exist: Terminal Trove, the awesome-claude-code issue form, Console.dev, PyCoder's Weekly. Each gets its own short note. None of them get the Show HN thread as a voting link.

### Weeks 7–8. In-tool install path

Ship the small skill or plugin if it is not already in the README's init path. The distribution win is `claude plugin` / a marketplace line / a skill file a person can copy, pointing at the same `whyline` binary. Keep the surface area to note, sync, explain, and handoff. Leave the console, the scheduler, and the relay out of the first screen of that listing. They are real; they are how a newcomer files Whyline under "another orchestrator."

Reply on X or whatever network you actually use, only under posts that describe this problem. If you have no audience there, this item is replies, not a launch thread.

### Weeks 9–12. The second story, or silence

Write again only if at least a few people who are not you have a `decisions.md` with rejected alternatives in it. The post is what they recorded and whether reviewer notes showed up. That is the piece that can be remembered. Pitch Changelog with that piece.

If the external use did not happen, do not invent a second launch. Keep commenting, ship the reviewer-recording gap or the Codex hook verification, and put the Homebrew formula up when you are willing to maintain the bump.

## Copy rules for every channel

- Disambiguate the name in the first screen.
- Give the denominator beside 43 percent.
- Say `whyline run` is the reliable handoff.
- Say Codex hooks are unverified until a `status` line shows otherwise.
- Install lines are `pipx install whyline` and `uv tool install whyline`, then `whyline init`.
- The maintainer's own sentences. A model may outline. A model does not draft the text that gets pasted onto Hacker News.
- One channel per day when the post is about your own work.

## How to tell whether it worked

There is no telemetry, on purpose. Public traces are the metric.

- Day 30: five repositories you do not own contain a Whyline `decisions.md`, or five people have told you they ran `init` and kept it. Issues or pull requests from strangers count. Stars do not, by themselves.
- Day 90: one of these happened: an HN thread with a technical disagreement in it, a newsletter mention, or a stranger's public write-up. A Show HN at 2 points plus a Console.dev listing is a success. A star spike with no external `decisions.md` is not.
- PyPI download charts are a weak check on top of those, because CI and mirrors inflate them.

## Sources

- Whyline README, `m0/RESULTS.md`, `phase0/STATUS.md`, `phase0/recruitment-message.md`, `pyproject.toml` (this repository, version 0.3.37.1).
- PyPI project page for `whyline` 0.3.37.1, uploaded 2026-10-08: <https://pypi.org/project/whyline/>
- Hacker News guidelines, Show HN guidelines, and `showlim`, read 2026-10-10.
- Lobsters about page, read 2026-10-10: <https://lobste.rs/about>
- `hesreallyhim/awesome-claude-code` contributing rules: age, human submission, issue form, one-line description.
- Terminal Trove submit form: <https://terminaltrove.com/submit/>
- Console.dev accepts tool suggestions at `hello@console.dev` and does not sell reviews (directory roundups, 2026).
- r/programming's public rule against product and "I made this" posts, and the exception for technical write-ups, as quoted by rule trackers from the subreddit's rules in May–July 2026. Confirm on the subreddit before posting.
- Amy Ko, "The Whyline," CHI 2004 / CMU, and the public Java archive `amyjko/whyline`.
- npm packages using the same name: `@malindar/whyline` (May 2026), `@sal-sovereign-ai-labs/whyline` (September 2026).
- Show HN median and the "about 4 percent above 30 points" figure: secondary summary of an open dataset of Show HN posts, not an HN official statistic.
