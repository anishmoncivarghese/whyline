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

# Retained handoffs, then a public story

Revised combined-review pass, 2026-10-10. Audience: the maintainer. Karma on hand: Hacker News 3, Reddit 8.

## The strategy

The goal is a developer who already runs Claude Code and Codex on one long-lived repository, installs Whyline, and uses it for a second handoff because the first one saved them from re-briefing. Fame for the bare name is a worse goal. The category around it is crowded, and the bare name is already taken.

Lead sentence, on every public surface:

> The next coding agent should not start blind.

Proof sentence, once they are looking:

> Git records what changed. Whyline records the decision, the rejected alternative, and can explain why a line exists.

That order matters. The switch is the weekly pain. `whyline explain` is the moment a handoff file does not reproduce. "Agent memory," a zero-bill campaign, and the measurement are support for that pair. Four parallel narratives split a solo maintainer into four launches.

The first screen of the README already has the right shape: a decision record, an explicit handoff, `explain`, and a limits list. Match it. Leave the console, the scheduler, chat, and the relay off the first screen of every launch asset. The relay is real. It stays off until `whyline init --relay`, it assigns an implementer and a reviewer, and it spends the subscription quota of the CLIs it starts. Deny that and a careful reader will catch it. Lead with it and the project is filed under orchestration.

Karma 3 and karma 8 delay two broadcast posts. They do not delay design partners, the demo, the essay, in-tool discovery, or editors.

## Where the other proposals diverge

Taken into this plan: one beachhead, the lead sentence above, posts staggered by days, a retention gate before Show HN, design partners recruited in private, a six-hour weekly budget, and install lines a stranger can run without adopting uv. Homebrew can wait until someone will bump a formula on purpose.

Refused:

- A 72-hour comment sprint scored by a karma number. Comments where you have a fact to add are participation. A quota of comments, aimed at clearing a filter, is farming even when the text is technical. "50–150 karma in 48 hours" is not a rule of Reddit. History in karma-farm subreddits is a ban footprint. There is no target karma.
- A proxy Show HN from an account above some karma line. The maker owns the submission and the afternoon of replies. A person who uses the tool may write about it on their own. Setting that up is a different act.
- Asking `hn@ycombinator.com` for the second-chance pool, or describing that mailbox as a way onto the front page. Moderators pull overlooked posts. They do not take applications. If the account cannot submit at all, one short note is enough: the account appears restricted, here is the URL, what do you recommend. Then wait.
- A same-day Hacker News, Reddit, and X push, and any plan that treats "50–80 stars in a day" or "150–250 stars in a day" as the mechanism. Those figures are not a published GitHub contract. Steering several audiences at the repository together, so a trending page trips, has the shape of vote coordination. It also leaves no day to repair what the first thread found. Trending is a side effect of a real discussion.
- A list of creators to tag, and a thread written in advance for them. One note is reasonable when the artifact matches work that person already does in public.
- Pasting a title, first comment, or thread that a model wrote. Hacker News forbids generated and AI-edited text. This file may hold an outline. The maintainer writes the words that get submitted.
- Posts about the Textual console, a stdlib core, or a Python architecture tour. Those audiences are not people whose second agent started blank.
- Pull requests scattered across awesome lists. `hesreallyhim/awesome-claude-code` takes a human submission through its issue form, wants the project older than 14 days with later commits, and wants one line with no pitch and no emoji. This repository meets the age rule. A generic Python or CLI list selects the wrong readers.
- A VS Code CodeLens, or any new editor surface, inside these 90 days. That is a new product. It waits until strangers are already handing off twice.
- Public targets for stars, a download count, a front-page rank, or a trending slot. PyPI totals mix in mirrors and CI. Stars with no second handoff are a reason to downgrade that channel.

One timing disagreement with the stricter of the two plans. The measurement essay does not wait for five retained users. Its evidence is already in `m0/RESULTS.md`. It waits until a stranger can install a pinned release and the pages they will hit agree with that file. Show HN, and the editor notes, wait for the retention gate.

## Beachhead and wording

Solo developers and small teams who run Claude Code and Codex in the same repository, switch because of the task or the quota or the context window, and have seen the second agent redo or undo a decision. They already live in git. They will try a local Apache-2.0 tool.

The beachhead sentence names those two CLIs. The docs keep the truth that `whyline run` also starts Grok and Antigravity. Leave for later: single-agent throwaway tasks, inbound Slack or Jira, and anyone looking for a swarm.

Qualifier, repeated until it is dull:

> Whyline for coding agents — git-native decision handoffs for Claude Code and Codex.

Disambiguation, on the README, PyPI, the demo repository, and any post: a git-committed decision log for coding-agent CLIs. Unrelated to Amy Ko and Brad Myers's Whyline debugger (CHI 2004, public archive `amyjko/whyline`). Unrelated to the npm packages `@malindar/whyline` and `@sal-sovereign-ai-labs/whyline`. The PyPI name `whyline` is this project. The bare word is not.

Order of the message:

1. The next agent starts blind.
2. Decisions, rejected alternatives, tests, and risks live in Markdown git already stores.
3. `whyline explain path:line` shows why that line exists.
4. Local, Apache-2.0, no account, no telemetry, no second bill. `run` uses the subscription already signed in.
5. Instruction-file reads are best effort. `whyline run` carries the handoff.

When someone says a commit message or a `HANDOFF.md` is enough, the concrete difference is the rejected alternative, the token-bounded packet, and explain-by-line. When someone says this is an orchestrator, the concrete difference is that the record does not assign work, and the relay does nothing until they turn it on.

## Claims safe to publish

Source of record: `m0/RESULTS.md`. The public summary `docs/measurement.md` has drifted, and the two have to match before either URL is posted. The summary omits the superseded 75 percent figure and the analyser bug that credited a Codex read to a Claude session. It also still says the reviewer-wording change is unmeasured, while `RESULTS.md` records two later reviewer-voiced entries whose cause is confounded with reviewers moving into the repository. Reconcile the summary to the results file. Do not soften the results file to match the summary.

Write side. One repository, one operator, 14–17 August 2026. Fourteen non-trivial commits, nineteen decisions, each with a because and a rejected alternative. Codex was not reminded. Claude recorded 6 decisions on 4 changes (150 percent). Codex recorded 13 on 10 (130 percent). The rate passes 100 percent because one commit often holds more than one decision. The precommitted bar was 60 percent on Claude and at least one Codex firing. That bar was cleared. It is a property of an agent that owns its session. A dispatched agent recorded nothing, because it follows the dispatcher prompt rather than `AGENTS.md`.

Read side. Claude Code ran `whyline brief` near the start of 3 of 7 sessions it owned, 43 percent, below a 50 percent bar fixed before collection. Codex was observed reading and has no session denominator, so that observation is not a rate. Earlier 67, 75, and 50 percent figures are superseded.

Publish the sentence "we set bars, the write side cleared, the read side missed, and the handoff moved to `whyline run`." Keep the denominators in the same paragraph as the percentages. A graphic of "43%" or of "130–150%" without those definitions becomes the correction.

Hooks, in the README's own words. Claude Code's hooks have been observed. Codex and Antigravity hooks are installed and reported separately by `whyline status`. Until a real Codex event arrives, status stays configured and never observed. Grok has no hook. Decision logging through the instruction file and a hook event are different claims.

`phase0/STATUS.md`, updated 9 August 2026, still lists recruitment and ten measured sessions as unfinished. The m0 run is the maintainer's repository. The privacy-safe recruitment note already exists. Use it. Ten formal sessions remain the research plan. Five public users are the distribution plan.

Pin one release for any public week. `0.3.30` through `0.3.37.1` shipped between 4 and 8 October 2026. macOS and Linux are tested in CI. Windows is not. `uvx` does not leave a durable binary for hooks. The lines to publish are `pipx install whyline` and `uv tool install whyline`, then `whyline init`.

## The package, built once

1. A silent terminal recording, 20 to 45 seconds. One decision with a rejected alternative, a handoff, the next agent starting from that handoff, then `whyline explain` on the line. Real output, captions, no tour.
2. A demo repository with a committed decision. `whyline explain` runs with no agent login. The handoff commands are on the page for people who already have the CLIs. Show HN asks that visitors be able to try the thing.
3. Both install commands smoked on clean macOS and Linux, through init, one note, a sync, a handoff, and an explain. Homebrew stays off this list.
4. README first screen: qualifier, disambiguation, the recording, three commands and the output they produce, platforms, demo link, 3 of 7, the hook sentence, one place to ask for help. A short comparison with a hand-written handoff file, commit messages, ADRs, transcripts, and a generic memory store.
5. Essay materials a stranger can re-read: task, commit range, bars fixed beforehand, and the scoring notes. A later comparison of repeated briefing, missed constraints, and recall of rejected alternatives needs its own precommitted rubric and its raw artifacts. Do not claim token savings. Vendor token totals are not one unit, which `phase0` already says.

## Channels that ignore karma

1. Five design partners, chosen because they already switch agents in public. The existing recruitment note. Watch the first install. Ask what the second handoff contained. Do not ask for a star.
2. GitHub and PyPI, corrected before any thread points at them. That includes the measurement-page reconciliation.
3. A skill or plugin whose verbs are note, sync, handoff, and explain. The listing text repeats the limit on unprompted reads. Submit the one-line description through the awesome-claude-code issue form.
4. The essay, on a site the maintainer controls, so later posts have a stable URL.
5. Editors, each on their own day, after the essay and the pinned release exist. Console.dev at `hello@console.dev` reviews tools and does not sell reviews. PyCoder's Weekly takes a project link. Changelog News only if a current issue is actually shipping; a directory roundup on 7 October 2026 still showed April as the newest visible issue, so check the week you write. Terminal Trove wants an image and install commands for packages you really publish. Name pipx and uv. Name Homebrew only after a formula exists.
6. Replies under a specific post about a second agent starting blank, or about a line whose reason was lost. One recording. No mention blast.
7. Later, and only after an invite plus a history that is mostly other people's work: Lobsters. New accounts are limited for 70 days, and they cannot use the show tag. Product Hunt and paid newsletter slots wait until a stranger has kept the tool. AlternativeTo fits a replacement for a named product, which this is not.

## Hacker News and Reddit

Primary pages, read 2026-10-10: the guidelines, Show HN, and `showlim`. Show HN is temporarily restricted for people the site does not yet know. There is no published karma threshold. An account at 3 should expect to be told it cannot submit Show HN. The notice describes ordinary contribution as the way through. Promotion as the main use of the account is against the guidelines. An occasional post of one's own work is allowed. Solicited votes and solicited comments attach to the submission and the domain. Deleting and reposting is not a tactic. A quiet Show HN is the common result. Secondary write-ups of an open dataset put the median at 2 points, one of them the author's. That figure is orientation, not an official statistic. The post stays up.

For several weeks, comment on threads about git history, ADRs, local tools, or measurement methodology when a concrete detail is missing. No link, and no "I built." Stop on a day whose only motive is the karma count. A pile of useful comments is not a quota to hit.

Then two posts, handwritten, in this order:

1. The essay, as an ordinary story. The title stays close to the essay's title. The guidelines ask submitters to crop gratuitous numbers, so "43%" stays in the body with its denominator.
2. Show HN, after the retention gate, and only if the account is allowed to submit one. Title shape: `Show HN: Whyline – why a line of code exists, for the next coding agent`. The first comment covers both install lines, the demo repository, what the record refuses to do, the relay's off-by-default status, 3 of 7, the name collision, and the hook status. Weekday morning, US time, afternoon kept clear. That timing is custom. If the post sits at one or two points, leave it. A later submission has to be a different artifact, after a long gap.

Reddit has no site-wide number. Each subreddit's AutoModerator is its own, often unpublished, rule. Karma 8 fails a lot of large filters. Re-read the live rules on the day.

Two communities. One the maintainer would read about Claude Code or Codex with or without this product. And `r/programming` only while its live rules still ban product demos and still allow a technical write-up of something difficult. The measurement essay can fit that exception. A feature list cannot. `r/SideProject` will accept a disclosed feedback post and will not make the tool known.

During those weeks, answer the blank-second-agent question when it is actually asked. Link Whyline only as the direct answer, with authorship in the same comment, once. The standalone post, if the rules allow one, opens with "I built the tool this measures." Wait several days before a second community, and change the wording from what the first thread objected to. One note to the moderators if AutoModerator removes a post. No repost.

## Ninety days

The week of 13 October 2026 is week 1. Move a public post when the pinned release or the install path slips. Leave the calendar alone when the motive is a news cycle.

Weeks 1–2. No post whose subject is Whyline. Freeze a release. Smoke both install commands. Reconcile `docs/measurement.md` with `m0/RESULTS.md`. Put the qualifier, the disambiguation, pipx, the platforms, 3 of 7, and the hook sentence on the first screen. Publish the demo repository and cut the recording. Send the recruitment note to five to ten people. Start the comment practice. Write down the baseline: outside users, stranger issues, stars, PyPI downloads, mentions.

Essay gate: a stranger can install the pinned version and run `explain` on the demo, and every public page they will reach tells the same story as `m0/RESULTS.md`. Failed outside installs stop the essay until the install works. Five retained users are not this gate.

Week 3. The essay, in the maintainer's sentences. The belief about instruction files. The bars written down first. The write-side rates with the reason they exceed 100 percent. The 3 of 7 result. The dispatched-agent miss. The move to `whyline run`. One repository link at the end. Ordinary HN story if the account can submit. Otherwise the single factual email, then a wait. The next day, one Reddit community whose rules allow the write-up. Fold real corrections into the README. No other outlet that day.

Weeks 4–5. Answer the thread. Fix the three failures people actually hit. Keep onboarding partners. Run the before/after comparison only with a rubric fixed beforehand. Do not submit Show HN. Do not delete the essay submission.

Show HN and editor gate: five outside users have completed one useful handoff, and at least three of them have completed a second within 14 days, because they said so. A committed `decisions.md` in a public repository you do not own counts as evidence. A star does not. If the second handoff is missing, stop and ask those users. Another announcement does not repair a one-time tool.

Week 6, only with that gate open and a permitted Show HN account. One Show HN. The question to readers is narrow: what is missing from decision, rejected alternative, tests, and open risk. On later days of that week, Terminal Trove, then the awesome-claude-code form. Console.dev and PyCoder's Weekly go out after the thread has produced a README correction. None of those notes is a request to vote on the thread.

Weeks 7–8. Narrow the in-tool listing to the four verbs. Publish one workflow a partner allowed you to describe. Hold one office hour. Open two bounded contribution issues. On a social network, reply under posts that describe this problem. With no audience there, skip the launch thread. Tag nobody from a list.

Weeks 9–12. A second essay only when outside use produced a fact worth reading: what those users recorded, whether a rejected alternative prevented a repeat, where reviewer notes still vanished, what the precommitted comparison showed. That piece is the Changelog pitch. Without that use, skip the launch. Verify a Codex hook event, or close the reviewer-recording gap, before adding a Homebrew formula.

## The week

About six hours.

- 90 minutes for replies and support.
- 90 minutes for one partner install or conversation.
- Two hours on the demo, the essay, or the comparison.
- One hour of comments that are not about Whyline.
- 30 minutes for a single editor or partner note.
- 30 minutes on the gate, and on whether the next post still deserves to exist.

## Whether it worked

No telemetry. The product promise forbids adding it for a chart.

North star: outside users who report two useful handoffs in the same repository within 30 days. Public decision files are a lower bound, because private repos and uncommitted trials stay invisible.

Internal checks, never copied into a launch post:

| Check | Decision |
| --- | --- |
| Stranger can install and run `explain` on the demo | Essay may go out |
| Five outside first handoffs, three of them repeated within 14 days | Show HN and editors may go out |
| Twenty outside first handoffs by day 90 | Keep this distribution pace |
| Ten second handoffs within 14 days by day 90 | The habit is real |
| Five stranger issues or pull requests, or five permissioned notes | Enough for the second essay |
| Two earned mentions | An essay thread, an editor, or a stranger's own post |

A Show HN at 2 points plus one editor mention is a success when the handoff counts are real. A star spike with no second handoff is a failed channel.

Stop rules. Visits and no installs: the first screen or the install line is wrong. Installs and no first handoff: init and the demo are still too long. A first handoff and no second: stop posting and talk to those users. Stars and no reports: ignore the stars. Readers describe an orchestrator or a memory product: cut the first screen again. Readers say a markdown file would do: show the rejected alternative and `explain`, and change the product if that demonstration fails.

## The next ten working days

1. Choose one release and smoke it on macOS and Linux.
2. Add `pipx install whyline` beside the uv line.
3. Reconcile `docs/measurement.md` with `m0/RESULTS.md`.
4. Put the qualifier, the name sentence, platforms, 3 of 7, and the hook sentence on the first screen.
5. Cut the terminal recording.
6. Publish the demo repository.
7. Send five recruitment notes.
8. Comment where you have a fact. No links.
9. Outline the essay. Leave the sentences for later, in your own words.
10. Record today's outside-user count. Do not announce a Show HN date. That post waits on the retention gate.

## Sources

- This repository: README (relay off until `init --relay`; limits list; version work in `pyproject.toml` at 0.3.37.1), `m0/RESULTS.md`, `docs/measurement.md`, `phase0/STATUS.md` updated 2026-08-09, `phase0/recruitment-message.md`.
- PyPI `whyline` 0.3.37.1, uploaded 2026-10-08.
- Hacker News guidelines, Show HN guidelines, and `showlim`, read 2026-10-10.
- Lobsters about page, read 2026-10-10.
- `hesreallyhim/awesome-claude-code` contributing rules: age, human submitter, issue form, one line, no pitch.
- Terminal Trove submit form.
- Console.dev suggestions at `hello@console.dev`; reviews are not sold.
- r/programming's ban on product posts and "I made this" demos, with room for a technical write-up, as quoted from the subreddit rules by trackers in May–July 2026. Confirm on the day.
- Amy Ko and Brad Myers, the Whyline, CHI 2004, archive `amyjko/whyline`.
- npm `@malindar/whyline` (May 2026) and `@sal-sovereign-ai-labs/whyline` (September 2026).
- Show HN median near 2 points: a secondary summary of an open dataset, not an HN statistic.
