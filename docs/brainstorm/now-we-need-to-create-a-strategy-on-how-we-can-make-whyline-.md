# Brainstorm: Now we need to create a strategy on how we can make whyline famous so that everyone nows about it, what are the possible ways to do it, i have low reddit and hacker news karma 8 and 3 respectively. You need to create a proper plan how we can di it

## Codex

# Make Whyline known by proving one narrow habit

Revised combined-review pass, 10 October 2026.

## The strategy in one paragraph

Do not optimize for “everyone knows Whyline.” First make Whyline the tool that developers who switch between Claude Code and Codex associate with one problem:

> **The next coding agent should not start blind.**

The immediate promise is a clean cross-agent handoff. The durable differentiation is more specific:

> **Git records what changed. Whyline records the decision, rejected alternatives, tests, and risks behind it—and can explain why a line exists later.**

That pairing is stronger than either story alone. “Shared agent memory” is understandable but crowded. “Git blame 2.0” is distinctive but does not by itself create frequent use. Lead with the painful switch; prove the product with git-native decision provenance.

Low Hacker News karma (3) and Reddit karma (8) change the sequence, not the ambition. Build proof through five external users, an instantly runnable demo, an honest measurement essay, in-tool discovery, and editor submissions before attempting a broad community launch.

## What changed after reviewing the other proposals

The strongest shared ideas are:

- a 20–45 second real terminal demo and cloneable demo repository;
- a human-written technical essay about the failed passive-read assumption;
- positioning around both cross-agent handoff and line-level decision history;
- a pinned, stable release with simple install commands;
- direct recruitment of a small number of people who already use two agent CLIs;
- staggered launches, followed by replies and product fixes;
- success measured by outside repositories retaining Whyline, not stars.

Several attractive tactics should be rejected:

- **No 72-hour karma sprint.** Karma gates are subreddit-specific and HN publishes no threshold. Useful participation over several weeks is credible; activity optimized for points is visible as farming.
- **No proxy Show HN from a high-karma account.** The maker should own the submission and conversation. Another person may independently share a tool they genuinely use, but that is not a launch tactic to arrange.
- **No coordinated same-day HN, Reddit, and X push.** It overloads a solo maintainer, resembles promotion, prevents one channel’s feedback from improving the next, and invites prohibited vote coordination.
- **No GitHub Trending target or claimed star threshold.** The algorithm is not a controllable acquisition channel. Trending is a possible consequence of genuine attention, not a plan.
- **No prewritten AI copy pasted into HN.** HN explicitly asks for human conversation and bars generated or AI-edited text. This document may guide the maintainer’s thinking; the maintainer must write the submitted title, comment, and replies.
- **No influencer name list as the core strategy.** Unsolicited mass tagging is low-trust. Send a specific artifact only when it directly matches a creator’s demonstrated interest.
- **No VS Code extension, orchestration feature, or broad platform expansion before retention.** Those are new products, not distribution for the existing wedge.
- **No ambitious vanity forecasts.** Targets such as 5,000 stars or 25,000 monthly downloads hide whether anyone used a second handoff.

## The audience and category

### Beachhead

Target solo developers and small teams who:

- use Claude Code and Codex on the same long-lived repository;
- switch agents for implementation, review, quota, or context-window reasons;
- already use Git and terminal tools;
- value local files, auditability, and no additional API bill;
- have felt an agent undo or rediscover a decision.

Defer developers who use one agent for disposable tasks, enterprises asking for Slack/Jira ingestion, and people seeking an autonomous multi-agent swarm.

### Category language

Use one consistent qualifier everywhere:

> **Whyline for coding agents — git-native decision handoffs for Claude Code and Codex.**

This reduces confusion with the 2004 Whyline debugger, other projects and npm packages using the name, and generic “agent memory” products. Add a short disambiguation sentence on the README, site, PyPI page, demo repository, and launch posts.

### Message ladder

1. **Pain:** “Switch coding agents without the next one starting blind.”
2. **Mechanism:** structured decisions, rejected alternatives, tests, and risks in Git-committed Markdown.
3. **Magic moment:** run `whyline explain path:line` and see why that code exists.
4. **Trust:** local-only, Apache-2.0, no account, telemetry, API keys, or per-token markup.
5. **Honesty:** agents must record meaningful decisions; passive instruction-file reads are not reliable enough to be the handoff path.

Do not open with the console, scheduler, chat, brainstorm, model selection, or relay feature list. They make the product look like another broad orchestration platform.

## Claims that must remain precise

The current measurement is interesting because it changed the product, not because it proves a universal law.

Public wording should say:

- Claude Code ran the expected read near the start in **3 of 7 owned sessions (43%)**;
- this was one repository, one operator, and a small sample;
- the precommitted read bar was 50%, so passive reads missed it;
- the product response was to carry context through `whyline run`, while instruction-file reads remain best effort;
- Codex decision logging was observed, but Codex hook events were not verified;
- a dispatched agent missed the recording behavior, another limitation worth naming.

Never publish a “43%” graphic without the 3-of-7 denominator and single-operator caveat. Never describe the measurement as a Claude-versus-Codex benchmark. The good story is: **we tested an assumption, it failed its own bar, and we changed the workflow.**

Before promotion, freeze one release for launch week. Daily patch releases weaken trust and complicate Homebrew or reproducibility. State macOS and Linux support; do not imply Windows support until it has been tested.

## The minimum launch package

Build these assets once and reuse them in channel-native forms.

### 1. A 20–45 second silent terminal demo

Show one continuous workflow:

1. Agent A records a non-obvious decision and rejected alternative.
2. A handoff records changed files, tests, and an open risk.
3. Agent B starts with the handoff rather than a repeated briefing.
4. `whyline explain path:line` retrieves the reason later.

Use captions and real output. Avoid slides and a broad feature tour.

### 2. A no-login demo repository

A stranger should be able to clone it and run `whyline explain` against a committed decision record without having Claude Code or Codex credentials. The repository should also show the exact commands for a full handoff when the user is ready.

### 3. Two durable install paths

Verify on clean macOS and Linux environments:

- `pipx install whyline`
- `uv tool install whyline`

Then run `whyline init`, record one decision, sync, hand off, and explain a line. Add Homebrew later if a maintainer is willing to update it deliberately; it is helpful packaging hygiene, not a launch blocker.

### 4. A conversion-ready repository

The first screen needs:

- qualified name and one-sentence promise;
- terminal demo;
- three-step quick start with expected output;
- supported platforms;
- a link to the demo repository;
- honest limitation and Codex-hook status;
- comparison with a manual HANDOFF.md, git messages/ADRs, transcripts, and generic memory;
- one obvious place for help and feedback.

### 5. A reproducible evidence package

Publish the task, starting commit, success criteria, prompts, raw outputs, and scoring rubric. A useful future experiment compares repeated briefing time, missed constraints, and recall of rejected alternatives with and without a structured handoff. Do not claim token savings until those are actually measured.

## Low-karma plan

### Hacker News

For three to four weeks, contribute only where there is firsthand value to add: Git history, ADRs, local developer tools, agent context, or measurement methodology. Ten thoughtful comments are more useful than a numeric karma goal. Do not mention Whyline in unrelated threads.

Use a two-step publishing sequence:

1. **Ordinary story first:** a human-written essay about the passive-read measurement and the design change it caused.
2. **Show HN later:** the runnable repository, only after the account is permitted and the demo package is ready.

If the account cannot submit because of the current Show HN restriction, email `hn@ycombinator.com` once with the facts and ask what the moderators recommend. Do not treat the mailbox as a route to the front page, request the second-chance pool, delete and repost, or solicit votes and comments.

For Show HN, the maintainer should be available for several hours and answer technical objections directly. A quiet submission is normal; leave it in place.

### Reddit

There is no site-wide safe karma number. Pick two communities the maintainer would read even without a product: one Claude/Codex community and one programming or CLI community. Read their live rules on posting day.

For several weeks:

- answer specific questions about handoffs, context loss, Git provenance, hooks, and local-first workflows;
- link Whyline only when it directly answers the question, disclose authorship immediately, and do not repeat the link across threads;
- use a permitted self-promotion or project megathread where available;
- ask moderators once before a standalone post when rules are unclear.

The first standalone post should be a technical write-up or measurement discussion, not a bare GitHub link or feature list. Put “I built the tool discussed here” in the first line. Space communities by several days and let each discussion improve the next post. If AutoModerator removes a post, contact moderators once; do not keep reposting.

### Channels with no karma dependency

Prioritize these before or alongside community launches:

1. **Five design partners:** personalized outreach to people who publicly described switching between agents. Offer installation help and ask to observe behavior, not for praise.
2. **GitHub and PyPI:** the permanent conversion surfaces.
3. **In-tool discovery:** a small Claude/Codex skill or plugin focused only on note, sync, handoff, and explain; submit to relevant curated lists through their actual contribution route.
4. **Newsletters/directories:** Console.dev, PyCoder’s Weekly, Changelog News, Terminal Trove, and one carefully chosen awesome list after the demo and stable release exist.
5. **Short video:** one two-minute walkthrough and three embeddable clips.
6. **Owned technical writing:** publish on an indexable site, then syndicate selectively with canonical links if supported.
7. **Product Hunt:** optional after external proof. It is not where a terminal tool should discover product-market fit.

## The 90-day operating plan

### Weeks 1–2: make the trial undeniable

- Freeze and smoke-test a launch release on macOS and Linux.
- Add pipx and uv install paths, the qualified name, and precise limitations.
- Record the terminal demo and publish the no-login demo repository.
- Establish current baselines: GitHub stars/forks, PyPI downloads, known outside users, issues, and mentions.
- Send five to ten personalized design-partner invitations using the existing privacy-safe recruitment note.
- Begin genuine HN and Reddit participation with no promotional objective.

**Gate:** five outside people complete a useful first handoff. If clean installs repeatedly fail, fix activation before producing launch content.

### Week 3: publish the negative-result essay

The maintainer writes the essay in their own language:

- the belief that repository instructions would be read;
- the thresholds fixed before collection;
- the 3-of-7 result and limitations;
- the dispatched-agent miss;
- the product change to deterministic handoff delivery;
- one repository link and install command at the end.

Submit it as an ordinary HN story if allowed. The next day, adapt it for one rules-compatible Reddit community with disclosure. Stay present, collect objections, and correct the docs.

### Weeks 4–5: turn criticism into proof

- Respond to every substantive question.
- Fix the three most common install or comprehension failures.
- Complete onboarding with the design partners.
- Collect permissioned workflow stories, screenshots, and exact user language.
- Run a reproducible before/after handoff experiment.

**Gate:** at least five outside users perform a second useful handoff within 14 days. If they do not, pause broad promotion and investigate retention.

### Week 6: launch the runnable product

If the HN account is eligible, publish a human-written Show HN linking directly to the runnable project. Ask one narrow question: what critical state is missing from decision, rejected alternative, tests, and open risk?

During the same week—but not as a coordinated voting burst—submit the stable artifact to relevant directories and editors. Space each outreach and tailor it. A sample sequence is Show HN on one day, Terminal Trove two days later, then Console.dev and PyCoder’s Weekly after the thread has produced useful corrections.

### Weeks 7–8: move discovery inside the workflow

Ship or simplify the integration that lets a user install a small Whyline skill/plugin from the agent environment. Its first screen should expose only four verbs: note, sync, handoff, explain.

Publish one external-user workflow, hold one office hour or live demo, and open two genuinely bounded contribution issues.

### Weeks 9–12: earn the second story

Publish again only if outside usage produced something worth learning:

- what five users recorded;
- whether rejected alternatives prevented rework;
- where reviewer decisions disappeared;
- what the before/after experiment showed;
- which limitations remained.

That evidence is the Changelog or podcast pitch. If retained use did not happen, do not manufacture another launch. Improve the product and continue problem-led participation.

## Weekly founder cadence

Reserve roughly six distribution hours:

- 90 minutes for support and thoughtful community replies;
- 90 minutes for one user interview or onboarding;
- two hours for the experiment, article, demo, or case study;
- one hour for non-promotional community participation;
- 30 minutes for one editor or partner pitch;
- 30 minutes to review evidence and choose the next experiment.

This cadence is sustainable and gives a solo maintainer time to fix what distribution reveals.

## Metrics and decision rules

The north-star metric is:

> **Confirmed retained repositories: outside repositories whose users voluntarily report at least two useful Whyline-assisted handoffs within 30 days.**

Whyline promises no telemetry, so use voluntary check-ins, GitHub discussions/issues, permissioned case studies, and noisy aggregate PyPI data. Do not weaken the privacy promise to make the dashboard prettier.

Ninety-day targets:

| Outcome | Target |
| --- | ---: |
| Outside users completing a first useful handoff | 20 |
| Outside users completing a second handoff within 14 days | at least 10 |
| Public external workflow stories or unsolicited mentions | 5 |
| Reproducible experiment with raw artifacts | 1 |
| Useful external issues or pull requests | 5 |
| Earned editor/newsletter/community discussions | 2 |

Decision rules:

- Visits but no installs: simplify positioning and the first-screen quick start.
- Installs but no first handoff: fix setup and demo friction.
- First handoff but no second use: stop promotion and interview users.
- Stars without confirmed use: downgrade the channel.
- Repeated confusion with orchestration or generic memory: narrow the copy.
- Repeated comparison with a plain handoff file: demonstrate the schema, rejected alternatives, lifecycle, and line-level explain instead of adding adjectives.

## The next ten working days

1. Choose and smoke-test one release.
2. Add pipx beside uv and verify both from clean environments.
3. Add the qualified name and precise claim caveats to the first screen.
4. Record the terminal demo.
5. Publish the no-login demo repository.
6. Contact five design partners.
7. Start helpful HN and Reddit participation without links.
8. Outline—but do not AI-draft—the measurement essay.
9. Record baseline metrics and a manual cohort sheet.
10. Do not announce a public launch date until five external users have completed a first handoff.

## Bottom line

Whyline should not attempt to become famous by looking bigger than it is. It should become memorable by owning a precise sentence: **the next coding agent should not start blind.** Its proof is not “memory”; it is a Git-committed record of decisions and rejected alternatives, plus an explanation of why a line exists.

The reliable growth loop is:

> useful handoff → retained outside repository → measurable story → credible technical discussion → more qualified users

The low-karma accounts only delay two broadcast posts. They do not block user recruitment, product proof, in-tool discovery, GitHub conversion, videos, directories, or editors. Earn the right to launch by making five strangers miss Whyline when it is absent; then give communities evidence worth discussing.

## Antigravity

# Making Whyline Famous: The Independent Growth Blueprint & Tactical Playbook

## 1. Executive Summary & The Reality of Developer Virality

"Fame" in open-source developer tooling is not a marketing problem; it is a **distribution engineering** problem. Open-source tools do not become industry staples because of ad budgets or generic social media posts. They become famous when they satisfy three precise criteria:

1. **A Razor-Sharp Wedge that Explains Itself in 5 Seconds:** Not "an AI agent coordination platform" (a noisy category with widespread developer fatigue), but:
   > *"Git blame tells you WHO and WHEN. Whyline tells you WHY and WHAT WAS REJECTED."*
   > and
   > *"Run Claude Code and Codex on the same project without either one starting blind — using the subscriptions you already pay for."*
2. **An Unforgivingly Empirical Narrative:** Developers, particularly on Hacker News, Reddit, and technical Twitter, are immune to hype. They are intensely receptive to empirical benchmarks, failure post-mortems, and transparent limitations. Whyline possesses a rare unfair advantage: **real empirical data** (`m0/RESULTS.md` showing Claude Code reads instructions only 43% of the time, while deterministic relay handoffs guarantee context transfer).
3. **An Algorithmic Velocity Engine:** Hitting GitHub Trending (Python and Overall) creates an automated snowball. When a repository gains 75–150 stars in a 24-hour window, algorithmic aggregators, bot accounts, Chinese developer digests (HelloGitHub, 阮一峰 Weekly), and tech newsletters pick it up automatically, transforming local traction into global visibility.

### The Immediate Constraint: Low Karma (HN: 3, Reddit: 8)
A naive launch right now—posting a direct link to GitHub on Hacker News or Reddit with low-karma accounts—**will fail within 15 minutes**. 
- On Hacker News (karma 3), link submissions from new/low-karma accounts trigger automated anti-spam and flame filters, dropping the post into `/newest` oblivion or marking it `[dead]`.
- On Reddit (karma 8), AutoModerator rules across `r/programming`, `r/Python`, `r/ClaudeAI`, and `r/LocalLLaMA` silently remove posts from accounts under minimum thresholds (typically 10–50 karma and 14–30 days account age) or enforce strict 9:1 self-promotion ratios.

This strategy blueprint solves the low-karma obstacle, establishes a non-promotional technical launch posture, and details a comprehensive 90-day execution roadmap to turn Whyline into the standard decision-provenance layer for multi-agent software engineering.

---

## 2. Overcoming the Low Karma Bottleneck

Trying to brute-force low karma via spamming or upvote rings is fatal (HN and Reddit algorithms detect coordinated voting instantly and issue shadowbans or domain blacklists). Instead, we apply a four-pronged bypass and bootstrap strategy.

```
                  ┌───────────────────────────────────────────────┐
                  │       LOW-KARMA BOOTSTRAP STRATEGY             │
                  └──────────────────────┬────────────────────────┘
                                         │
         ┌───────────────────────────────┼──────────────────────────────┐
         ▼                               ▼                              ▼
┌──────────────────┐           ┌──────────────────┐           ┌──────────────────┐
│ 72-Hour Organic  │           │  Research Post   │           │   Proxy Launch   │
│ Karma Sprint     │           │  (Not Link Post) │           │  & Elder Support │
│ (Reddit 8 -> 100)│           │  (Bypasses Spam) │           │  (HN / Influencer│
└──────────────────┘           └──────────────────┘           └──────────────────┘
```

### 2.1 The 72-Hour Reddit Karma Sprint (Legitimate & Safe)
To post without triggering AutoModerator, the account needs ~50–100 comment karma and a verified organic footprint.
- **Do NOT post in karma-farming subreddits** (e.g., `r/FreeKarma4U`). Most major tech subreddits automatically ban any account with post history in karma farms.
- **The High-Signal Comment Method:** 
  1. Go to `r/ClaudeAI`, `r/OpenAI`, `r/ChatGPTCoding`, and `r/Python`.
  2. Filter by `Top -> Past 24 Hours` or `New`.
  3. Find developers struggling with agent context loss, multi-agent errors, or Claude Code vs. Codex comparisons.
  4. Write three genuinely detailed, helpful technical answers per day explaining how context isolation works, how subshells execute, or how to structure prompt instructions.
  5. *Do not link to Whyline in these initial comments.* Establish pure credibility.
  6. In 48–72 hours, 3–5 high-quality comments routinely generate 50–150 karma.

### 2.2 The "Text Post / Research" Wedge (Never Submit a Bare Link)
- On Reddit, link posts (`[Title](github.com/...)`) scream self-promotion and trigger spam filters.
- **Text self-posts** receive the opposite treatment: they bypass link-based spam triggers and invite discussion. 
- Format: *"We measured how often Claude Code and Codex actually read repository instructions (Results inside + open source tool)"*.
- Place the GitHub link at the bottom as reference material, not the focal point.

### 2.3 Hacker News: The "Show HN" Playbook for Low Karma
Hacker News treats "Show HN" differently from normal link submissions, but a 3-karma account is still vulnerable to algorithmic suppression.
1. **Title strictness:** Must strictly follow the format: `Show HN: Whyline – Git-native decision provenance for AI coding agents` (or `Show HN: Whyline – Pass tasks between Claude Code and Codex without losing context`). No hype, no emojis, no superlatives ("blazing fast", "ultimate", "revolutionary").
2. **The "Dang Email" Protocol (HN's Official Safety Valve):**
   - Hacker News moderator Daniel Gackle (`dang`) actively monitors `hn@ycombinator.com`.
   - If an earnest, high-effort, open-source technical project gets caught in the spam filter or drops with 1 upvote despite positive merit, email `hn@ycombinator.com`:
     > *Subject: Show HN: Whyline*
     > *Hi Dan, I posted a Show HN for Whyline (a local-only, open-source git provenance tool for multi-agent workflows). Because my account is relatively new, I believe it may have slipped past the new queue without visibility. If you find the project interesting and in line with HN guidelines, I'd appreciate consideration for the second-chance pool. Thank you for keeping HN high-signal.*
   - Dang regularly reviews these and places quality projects on the front page via the second-chance pool.
3. **The Proxy Launch Option:**
   - Partner with an existing, reputable HN user (karma > 500) who has tested Whyline to submit the initial link.
   - You (as author) immediately post the first comment detailing the architecture, the motivation, the 43% read-rate benchmark, and the technical trade-offs.

---

## 3. Core Positioning: The 4 Viral Narratives

To make Whyline famous, we must frame it around problems developers already complain about daily. Nobody wakes up wanting another AI orchestration tool. Developers *are* complaining about:
1. AI agents undoing previous work or hallucinating why code was written.
2. Context window amnesia when switching between Claude Code and Codex.
3. Crazy API billing bills when using heavy agent wrappers.
4. `git blame` being useless when an AI generated 400 lines in one commit.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                            WHYLINE POSITIONING MATRIX                        │
├──────────────────┬─────────────────────────────┬─────────────────────────────┤
│ Target Audience  │ The Visceral Frustration    │ Whyline's Viral Answer      │
├──────────────────┼─────────────────────────────┼─────────────────────────────┤
│ Senior Eng /     │ "AI code churn is insane;   │ "Git blame tells who;       │
│ Tech Leads       │ nobody knows why lines exist│ Whyline explain tells why   │
│                  │ or what was rejected."      │ and what was rejected."     │
├──────────────────┼─────────────────────────────┼─────────────────────────────┤
│ Multi-Agent      │ "Claude Code is great at X, │ "Dual-agent relay on your   │
│ Power Users      │ Codex at Y, but switching   │ existing subscriptions. Zero│
│                  │ between them loses context."│ API markup, zero lock-in."  │
├──────────────────┼─────────────────────────────┼─────────────────────────────┤
│ Open Source /    │ "Tired of VC-backed cloud   │ "Local-only, Apache-2.0,    │
│ Pragmatic Devs   │ wrappers collecting data &  │ markdown committed to Git,  │
│                  │ charging tokens."           │ zero telemetry."            │
├──────────────────┼─────────────────────────────┼─────────────────────────────┤
│ AI Researchers / │ "Prompt memory doesn't work │ "We measured it: unprompted │
│ Tool Builders    │ reliably across sessions."  │ read is only 43%. You need  │
│                  │                             │ deterministic CLI relays."  │
└──────────────────┴─────────────────────────────┴─────────────────────────────┘
```

### Narrative 1: "Git Blame 2.0"
- **The Hook:** *"Git blame answers WHO broke the build and WHEN. Whyline answers WHY they chose that approach and WHAT alternatives they rejected."*
- **Why it resonates:** Every software engineer has stared at a commit message saying `fix: update cache logic` and wondered: *"Did they consider bounded eviction? Why did they avoid LRU?"* Whyline makes architectural decisions and rejected trade-offs first-class citizens in the Git history.

### Narrative 2: "The Claude-to-Codex Relay"
- **The Hook:** *"You already pay for Claude Pro and ChatGPT Plus / Codex. Why are you re-explaining your codebase every time you switch between them?"*
- **Why it resonates:** Claude Code and Codex have distinct strengths (Claude excels at architectural planning and test drafting; Codex excels at targeted edits and fast execution). Switching between them currently requires manual copy-pasting or starting from scratch. Whyline connects them natively.

### Narrative 3: "The 43% Empirical Finding"
- **The Hook:** *"We tested whether AI coding agents actually read instructions in AGENTS.md. The result: only 43% of the time unprompted."*
- **Why it resonates:** Debunks the myth that passive context files (`AGENTS.md`, `.cursorrules`) are sufficient for complex multi-agent handoffs. Introduces Whyline's deterministic `whyline run` and `whyline sync` as the necessary engineering solution.

### Narrative 4: "Zero Billing Markup / Sovereign AI"
- **The Hook:** *"No API keys. No per-token tax. No cloud relay. Just vendor CLIs executed locally."*
- **Why it resonates:** Devs are burned out by wrappers that charge a 20% margin on top of OpenAI/Anthropic APIs or require enterprise SSO.

---

## 4. Visual Assets & Launch Prerequisite Checklist

Before starting any outreach, the repository and visual assets must be optimized for immediate conversion. A developer who lands on GitHub should understand the tool and star the repo within 10 seconds.

### 4.1 The 20-Second Terminal GIF / Video (The "Aha!" Moment)
A recording (using `vhs` by Charm or `asciinema`) displaying a crisp, three-act terminal workflow:
1. **Act 1 (0:00 - 0:07):** Claude Code implements a feature and runs `whyline note "Pin better-sqlite3 to ^13.0.0" --because "..." --rejected "^11.0.0: node-gyp source build error"`.
2. **Act 2 (0:07 - 0:13):** Tab 2 opens Codex: `whyline run codex "review and test"` — Codex instantly picks up the exact decision and rejected options without any user prompt.
3. **Act 3 (0:13 - 0:20):** Developer runs:
   ```bash
   $ whyline explain package.json:14
   Decision   Pin better-sqlite3 to ^13.0.0
   Because    prebuilt binaries needed
   Rejected   ^11.0.0 (requires node-gyp build)
   Confidence High
   ```
This 20-second demo visualizes the abstract concept into concrete developer magic.

### 4.2 The "Clone & Try in 60 Seconds" Sandbox
Provide a 1-line interactive demo command in the README:
```bash
git clone https://github.com/anishmoncivarghese/whyline-demo && cd whyline-demo && whyline explain src/cache.py:24
```
Allowing a developer to run `whyline explain` on an existing, pre-populated decision history without setting up agents proves the value immediately.

### 4.3 Package Distribution Expansion: Homebrew Tap
While `uv tool install whyline` is standard for Python engineers, macOS developers overwhelmingly expect:
```bash
brew install anishmoncivarghese/tap/whyline
```
Having a Homebrew formula eliminates installation hesitation for developers who do not use `uv` or Python daily.

---

## 5. Channel-by-Channel Execution Playbook

```
                         ┌────────────────────────────────────────┐
                         │      MULTI-VECTOR DISTRIBUTION MAP     │
                         └───────────────────┬────────────────────┘
                                             │
      ┌──────────────────┬───────────────────┼───────────────────┬──────────────────┐
      ▼                  ▼                   ▼                   ▼                  ▼
┌───────────┐      ┌───────────┐       ┌───────────┐       ┌───────────┐      ┌───────────┐
│ Hacker    │      │  Reddit   │       │ Tech X /  │       │ Developer │      │ GitHub    │
│ News      │      │ Subreddits│       │ Twitter   │       │Newsletter │      │ Trending  │
│ (Show HN) │      │ (Text)    │       │ (Threads) │       │ (Sponsorship│    │ Engine    │
└───────────┘      └───────────┘       └───────────┘       └───────────┘      └───────────┘
```

### 5.1 Hacker News: The Master "Show HN" Post
**Submission Timing:** Tuesday or Wednesday, 07:00 AM – 08:30 AM US Eastern Time (peak front-page voting window).

**Submission Title:**
> `Show HN: Whyline – Git-native decision provenance and handoffs for coding agents`

**First Comment (The Founder Statement):**
> *Hey HN,*
>
> *I built Whyline because I got tired of switching between Claude Code and Codex and watching the second agent start blind every single time.*
>
> *Claude is great at architectural planning and writing tests; Codex is great at fast, targeted diffs. But in practice, combining them is painful: the second agent has no idea what the first one decided, what it tried, or what it deliberately ruled out. You end up copy-pasting context, or the second agent reverts a trade-off the first one carefully verified.*
>
> *Whyline fixes this with three core principles:*
>
> 1. *It records DECISIONS and REJECTED ALTERNATIVES, not entire conversation transcripts. When an agent finishes, it writes why it chose X and why it rejected Y.*
> 2. *It is git-native: decisions live in `.whyline/decisions.md` committed directly to your repository. Six months from now, running `whyline explain <file>:<line>` uses `git blame` + decision matching to explain WHY that line exists.*
> 3. *Zero extra API billing: it launches vendor CLIs via `exec` on the subscriptions you already pay for. No per-token markup, no telemetry, no cloud accounts.*
>
> *One thing we measured that surprised us: over 14 commits across both agents, Claude and Codex reliably recorded decisions (130-150% of non-trivial changes). But Claude Code only read passive repository instructions (`AGENTS.md`) unprompted 43% of the time. Passive context files aren't enough; you need a deterministic handoff relay (`whyline run / sync`).*
>
> *Code is Apache-2.0, Python 3.11+ stdlib core: [link]*
> *I'd love feedback on how you currently manage multi-agent context and decision tracking.*

**Managing the Comments:**
- Respond to every technical comment within 10 minutes.
- When someone asks: *"Why not just use git commit messages?"*
  - Answer: *"Commit messages describe what changed and why that change happened at a commit level. But they rarely capture granular rejected alternatives for individual architectural choices, and agents don't reliably parse git logs for rejected options when starting a task. Whyline structures this specifically for agent ingestion (under a 1,200 token budget) and enables `whyline explain file:line` mapping."*

---

### 5.2 Reddit: Targeted Subreddit Text Posts
Do not post in all subreddits on the same day. Stagger across 10 days.

#### Subreddit 1: `r/ClaudeAI`
- **Angle:** Claude Code power users who also use ChatGPT/Codex.
- **Title:** *How we solved context loss when handing off tasks between Claude Code and other agents*
- **Focus:** Show how Claude Code's terminal hooks record decisions automatically, and how `whyline handoff` passes state to other tools.

#### Subreddit 2: `r/Python`
- **Angle:** Engineering, stdlib purity, and TUI implementation.
- **Title:** *Built a zero-dependency (core) Git decision provenance tool using Python 3.11, prompt_toolkit & Textual*
- **Focus:** Highlight that the decision engine and git-blame parser use **only Python stdlib**, while the full-screen console uses Textual. Python developers appreciate clean architecture with minimal dependencies.

#### Subreddit 3: `r/commandline` & `r/cli`
- **Angle:** UNIX philosophy, CLI tooling, TUI design.
- **Title:** *whyline: a full-screen TUI and Git relay for managing developer decisions and AI handoffs*
- **Focus:** Showcase the terminal workflow, the Textual console, and `whyline explain`.

#### Subreddit 4: `r/LocalLLaMA` & `r/ChatGPTCoding`
- **Angle:** Multi-agent memory limitations and empirical failure rates.
- **Title:** *We measured how often AI coding agents actually read project context files (Only 43%). Here is the data and how we fixed it.*
- **Focus:** Deep technical discussion on prompt-injection limits vs deterministic CLI relays.

---

### 5.3 Tech X / Twitter & Developer Influencer Seeding
Twitter is the primary real-time channel for AI coding discourse. The strategy here is **"Content-First Seeding"**: do not ask influencers to promote Whyline; give them interesting data and tools that fit their existing narratives.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        X / TWITTER TARGET TARGETS                      │
├──────────────────────┬─────────────────────────┬───────────────────────┤
│ Influencer / Creator │ Why They Care           │ Specific Approach     │
├──────────────────────┼─────────────────────────┼───────────────────────┤
│ Simon Willison       │ Obsessed with CLI tools,│ Tag him on the 43%    │
│ (@simonw)            │ sqlite, local LLMs, and │ AGENTS.md benchmark   │
│                      │ transparent tooling.    │ and git-native storage│
├──────────────────────┼─────────────────────────┼───────────────────────┤
│ Swyx / Latent Space  │ Tracks the AI Engineer  │ Pitch the concept of  │
│ (@swyx)              │ stack, agent workflows, │ "Decision Provenance  │
│                      │ and context relays.     │ vs Vector Memory"     │
├──────────────────────┼─────────────────────────┼───────────────────────┤
│ ThePrimeagen /       │ Love roasting bad AI    │ Show `whyline explain`│
│ Fireship             │ tools; praise practical │ as "Git blame that    │
│                      │ terminal-first utilities│ actually explains why │
│                      │                         │ your junior AI broke  │
│                      │                         │ production"           │
├──────────────────────┼─────────────────────────┼───────────────────────┤
│ Anton                │ Building local-first,   │ Showcase dual-agent   │
│ (@abacaj)            │ agentic developer flows.│ Claude Code + Codex   │
│                      │                         │ coordination.         │
└──────────────────────┴─────────────────────────┴───────────────────────┘
```

#### The Viral Twitter Thread Template:
- **Tweet 1 (Hook):** `Git blame tells you WHO wrote the code. But it never tells you WHY they chose that architecture, or what alternatives they deliberately rejected. We built an open-source, local-only tool to fix this — especially for AI-generated code. Meet Whyline 🧵👇` [Attach the 20s VHS GIF]
- **Tweet 2:** `The problem: Claude Code and Codex are great at different things. Claude plans and writes tests; Codex rips through surgical edits. But switching between them is painful: the second agent starts completely blind.`
- **Tweet 3:** `We tried passive instructions in AGENTS.md. Over 14 commits, we measured it: Claude Code only read passive instructions unprompted 43% of the time. Passive context files fail. You need deterministic handoffs.` [Attach benchmark screenshot]
- **Tweet 4:** `Whyline connects them via a git-committed decision ledger. When an agent decides something, it records the rationale AND the rejected alternatives. When you switch, 'whyline run' hands off the context in <1200 tokens.`
- **Tweet 5:** `The killer feature: months later, run 'whyline explain path/to/file.py:42'. It matches git blame to the decision record and explains the exact reasoning and rejected choices.`
- **Tweet 6:** `Free, Apache-2.0, zero API keys (uses your existing vendor subscriptions), zero telemetry. Built in Python with a full Textual TUI. Check it out on GitHub: [link]`

---

### 5.4 The GitHub Trending Flywheel
Getting on GitHub Trending (Python or Overall) is the single highest-ROI catalyst for an open-source project.
- **The Threshold:** To hit Python Trending, a repo typically needs **50–80 stars** in a 24-hour period. To hit Overall Trending, it needs **150–250 stars**.
- **The Mechanism:**
  1. Coordinate Phase 1 launch (Hacker News Show HN + Twitter thread + r/Python post) on the **same day**.
  2. Direct all initial traffic to the GitHub repo.
  3. When the threshold is crossed, GitHub's algorithm places Whyline on `github.com/trending/python`.
  4. Once on Trending:
     - Automated Twitter bots (`@TrendingGithub`, `@GitHubTrending`) tweet the repo.
     - Chinese open-source aggregators (阮一峰 Weekly, HelloGitHub) syndicate it to tens of thousands of developers.
     - Tech aggregators and newsletter curators scrape the trending list weekly.

---

### 5.5 Developer Newsletters & Syndication
Tech newsletter curators constantly look for interesting open-source developer tools. Pitching them with a ready-made blurb yields high conversion:

- **Target Newsletters:**
  1. **Console.dev:** Curates the best open-source developer tools every week. Perfect match.
  2. **TLDR Tech / TLDR AI:** Over 1M tech readers. Short 3-sentence blurb format.
  3. **PyCoder's Weekly / Python Weekly:** The premier Python newsletters.
  4. **Changelog Weekly:** Covers notable open-source projects and developer workflows.
  5. **Bytes.dev:** High-engagement, humorous JavaScript/Developer newsletter.

**The Outreach Pitch Email (Curator Template):**
> *Subject: Interesting open-source CLI: Whyline (Git-native decision provenance for AI agents)*
>
> *Hi [Name],*
>
> *Thought Whyline might be of interest for [Newsletter Name].*
>
> *It's an open-source, local-only Python CLI (Apache-2.0) that solves a big headache with AI coding agents (Claude Code, Codex): when switching between them, the second agent starts blind and has no idea what trade-offs were already decided or rejected.*
>
> *Instead of another cloud wrapper, Whyline records structured decisions (`--because` and `--rejected`) into Git-committed Markdown. Months later, `whyline explain file:line` tells you why that code exists using git blame + decision matching.*
>
> *Repo: https://github.com/anishmoncivarghese/whyline*
>
> *Happy to answer any questions or share our empirical benchmark on agent instruction read-rates.*

---

## 6. Neutralizing Anticipated Technical Objections

When a tool starts gaining traction, technical communities will critique it. Having immediate, respectful, and razor-sharp answers turns skeptics into advocates.

```
┌────────────────────────────────────────────────────────────────────────┐
│                      OBJECTION HANDLING PLAYBOOK                       │
├──────────────────────────────┬─────────────────────────────────────────┤
│ Skeptical Question           │ The Winning Technical Response          │
├──────────────────────────────┼─────────────────────────────────────────┤
│ "Why not just write good git │ "Commit messages capture what changed at│
│ commit messages or PRs?"     │ the commit level, but rarely capture    │
│                              │ specific rejected options per decision. │
│                              │ More importantly, agents don't parse git│
│                              │ logs for rejected trade-offs. Whyline   │
│                              │ packages decisions into a 1,200-token   │
│                              │ handoff packet that agents consume. Plus│
│                              │ 'whyline explain' maps directly to line.│
├──────────────────────────────┼─────────────────────────────────────────┤
│ "Isn't this just another     │ "No. Whyline does NOT run agents in     │
│ agent orchestration hype     │ parallel, does not manage queues, does  │
│ framework like AutoGPT?"     │ not parse outputs, and does not touch   │
│                              │ your API keys. It is a Git-native relay.│
│                              │ You run your vendor CLIs directly.      │
│                              │ Whyline gets completely out of the way."│
├──────────────────────────────┼─────────────────────────────────────────┤
│ "Why should I trust agents to│ "We measured this empirically in m0:    │
│ self-report decisions?"      │ Claude Code recorded 150% and Codex     │
│                              │ 130% of non-trivial changes unprompted. │
│                              │ But reviewing agents recorded less. We  │
│                              │ publish our exact data and methodology  │
│                              │ openly in RESULTS.md."                  │
├──────────────────────────────┼─────────────────────────────────────────┤
│ "Why not just use .cursorrules│ "Passive context files work for broad  │
│ or AGENTS.md directly?"      │ repo style, but our benchmarks showed   │
│                              │ Claude Code reads unprompted only 43% of│
│                              │ the time across sessions. Handoffs need │
│                              │ deterministic execution ('whyline run').│
└──────────────────────────────┴─────────────────────────────────────────┘
```

---

## 7. The 90-Day Tactical Execution Roadmap

A structured week-by-week execution plan to take Whyline from hidden gem to widely recognized developer standard.

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                         90-DAY STRATEGIC TIMELINE                              │
├────────────────┬───────────────────────────────────────────────────────────────┤
│ Days 1 – 14    │ Foundation, Asset Polish, Homebrew, and Reddit Karma Sprint   │
├────────────────┼───────────────────────────────────────────────────────────────┤
│ Days 15 – 30   │ The Technical Research Blitz ("The 43% Benchmark" Article)     │
├────────────────┼───────────────────────────────────────────────────────────────┤
│ Days 31 – 45   │ Coordinated Launch Week (Show HN + Reddit + GitHub Trending)  │
├────────────────┼───────────────────────────────────────────────────────────────┤
│ Days 46 – 60   │ Newsletter Syndication, Influencer Demos, Podcast Outreach   │
├────────────────┼───────────────────────────────────────────────────────────────┤
│ Days 61 – 90   │ Ecosystem Expansion: VS Code CodeLens Prototype & Community   │
└────────────────┴───────────────────────────────────────────────────────────────┘
```

### Phase 1: Foundation & Karma Bootstrap (Days 1–14)
- [ ] **Karma Sprint:** Execute 3 high-value technical comments daily on `r/Python`, `r/ClaudeAI`, and `r/OpenAI` to lift Reddit karma above 100.
- [ ] **Visual Assets:** Record a crisp 20-second terminal GIF using `vhs` showing Claude -> Codex -> `whyline explain`.
- [ ] **Interactive Demo Repo:** Create `github.com/anishmoncivarghese/whyline-demo` with pre-recorded decisions for instant testing.
- [ ] **Homebrew Formula:** Submit or set up `brew tap anishmoncivarghese/whyline` for friction-free Mac installation.
- [ ] **Awesome Lists:** Submit PRs to `awesome-claude`, `awesome-cli`, and `awesome-python-applications`.

### Phase 2: The Empirical Research Blitz (Days 15–30)
- [ ] **Write Technical Article:** Draft a comprehensive blog post: *"We measured how often Claude Code and Codex actually read repository context files (and why prompt-based memory fails)"*.
- [ ] **Publish on Personal Blog / Substack / dev.to:** Ground the article in `m0/RESULTS.md` data. Include charts, failure rates, and code snippets.
- [ ] **Soft Launch Article on Reddit:** Post the article as a discussion on `r/LocalLLaMA` and `r/ClaudeAI`. Gauge initial feedback and fix edge cases.

### Phase 3: Coordinated Launch Week (Days 31–45)
- [ ] **Day 31 (Tuesday, 07:30 AM ET):** Submit **Show HN: Whyline – Git-native decision provenance for coding agents**.
- [ ] **Day 31 (07:35 AM ET):** Post the Twitter/X breakdown thread tagging relevant AI/CLI builders.
- [ ] **Day 31 (Active Monitoring):** Respond to every HN comment. If flagged or dropped into dead queue, initiate the Dang Email Protocol.
- [ ] **Day 32:** Post the architectural deep-dive to `r/Python` emphasizing the zero-dependency stdlib design and Textual TUI.
- [ ] **Day 33:** Post the agent-cooperation case study to `r/ClaudeAI` and `r/ChatGPTCoding`.
- [ ] **Day 34–35:** Monitor star velocity to secure placement on GitHub Trending (Python).

### Phase 4: Newsletter Syndication & Creator Outreach (Days 46–60)
- [ ] **Newsletter Blitz:** Send the curator pitch email to Console.dev, TLDR Tech, PyCoder's Weekly, and Changelog.
- [ ] **YouTube / Creator Demos:** Reach out to developer YouTubers who cover CLI tools and AI engineering (e.g., ThePrimeagen, Fireship, Dreams of Code, DevOps Toolkit) offering a 2-minute demo clip.
- [ ] **Changelog Podcast Pitch:** Pitch a discussion on "The problem with AI code provenance and why git blame needs an upgrade" to the Changelog podcast.

### Phase 5: Ecosystem Expansion & Moat Building (Days 61–90)
- [ ] **VS Code CodeLens Extension (Alpha):** Build a lightweight VS Code extension that renders Whyline decisions inline directly above functions/lines (e.g., `Whyline: Pin better-sqlite3 | Rejected: ^11.0.0`). CodeLens integration visualizes Whyline's value without leaving the editor.
- [ ] **Community Showcase:** Create a `SHOWCASE.md` in the repo featuring real projects instrumented with Whyline.
- [ ] **Git Hook Automation:** Introduce an optional pre-commit check that prompts developers or agents to log decisions when major diffs are detected.

---

## 8. Success Metrics & Tracking Dashboard

Track the following quantitative milestones across the 90-day campaign:

| Milestone / Metric | 30 Days Target | 60 Days Target | 90 Days Target |
|--------------------|----------------|----------------|----------------|
| **GitHub Stars**   | 250            | 1,500          | 5,000+         |
| **Hacker News**    | Show HN posted | Front Page (Top 10) | Featured in HN Digest |
| **Reddit Karma**   | 150+           | 500+           | Community regular |
| **PyPI / uv Downloads** | 1,000/mo  | 7,500/mo       | 25,000+/mo     |
| **Newsletter Features** | 1 niche   | 2 major (TLDR/Console) | 4+ features |
| **GitHub Trending**| Python Top 10  | Python #1      | Overall Trending |

---

## 9. Conclusion: The Winning Philosophy

Whyline does not need to compete with multi-million dollar agent companies or pretend to be an all-encompassing AI cloud platform. 

Its path to becoming famous is through **developer authenticity, empirical honesty, and solving the real, unglamorous problem of decision amnesia**:
- Be the tool that respects developer sovereignty (local-only, zero markup, git-committed).
- Be the tool that tells the truth about AI agent limitations (43% read rates, empirical testing).
- Be the tool that upgrades `git blame` for the AI era.

By executing this staged, karma-resilient distribution engine, Whyline will establish itself as an indispensable utility in every serious developer's multi-agent workflow.

## Grok

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
