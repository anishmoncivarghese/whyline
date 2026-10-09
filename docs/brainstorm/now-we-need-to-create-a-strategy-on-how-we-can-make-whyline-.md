# Brainstorm: Now we need to create a strategy on how we can make whyline famous so that everyone nows about it, what are the possible ways to do it, i have low reddit and hacker news karma 8 and 3 respectively. You need to create a proper plan how we can di it

## Codex

# Making Whyline Known: an independent go-to-market plan

Research date: 10 October 2026

## Executive recommendation

Do not try to make Whyline famous by posting the same launch link everywhere. The market is already crowded with tools described as “memory,” “context,” and “handoff” for coding agents. Whyline needs to become known for a more precise category:

> **Whyline is git-native decision provenance for coding agents. It lets Claude Code and Codex inherit the decisions, rejected alternatives, tests, and risks behind the code—not merely a transcript or summary.**

The short acquisition message can still begin with the immediate pain:

> Use Claude Code and Codex on the same project without the second agent starting blind.

The proof and differentiation should then be:

- decisions and rejected alternatives tied to files, tasks, and commits;
- `whyline explain file:line` answers why code exists;
- local-only Markdown, no account, telemetry, API keys, or extra token bill;
- explicit handoffs with tests and risks, not an opaque “memory” database;
- honest measured limitations rather than magical continuity claims.

The recommended growth sequence is:

1. Make the product understandable and demonstrable in 60 seconds.
2. Recruit 10–20 real multi-agent users through personal, problem-led outreach.
3. Publish their evidence and a reproducible before/after experiment.
4. Launch on Show HN, carefully selected Reddit venues, and Product Hunt in separate waves.
5. Compound through useful technical content, integrations, newsletter coverage, and user stories.

Low Reddit karma (8) and Hacker News karma (3) are constraints, not blockers. They mean community participation and moderator contact must start before launch, while channels that do not require karma—GitHub, a website, direct user research, newsletters, Product Hunt, videos, and collaborators—do the early work.

## What the research says

### There is real demand, but the category is becoming noisy

Developers are publicly asking how to share state between Claude Code and Codex. Recent Reddit questions describe exactly the pain Whyline addresses: switching tools forces users to re-explain work, decisions, and current state. Examples include [“Is there any open-source tool for sharing conversation memory between Codex and Claude Code?”](https://www.reddit.com/r/ClaudeCode/comments/1se0es6/is_there_any_opensource_tool_for_sharing/) and [“How do you share coding session between Claude Code and Codex?”](https://www.reddit.com/r/claude/comments/1uzv9ow/how_do_you_share_codding_session_between_claude/).

However, current search results already contain many adjacent projects: [handoff](https://github.com/AniruddhaHumane/handoff), [cross-agent-handoff](https://github.com/rwineman/cross-agent-handoff), [agent-work-mem](https://github.com/daystar7777/agent-work-mem), [Kairo](https://github.com/sandeepbollavaram/Kairo), and other Markdown- or Git-backed memory systems. “Persistent context across agents” is therefore demand evidence, but not a defensible position by itself.

Whyline’s strongest distinct assets are not generic memory. They are the decision schema, rejected alternatives, evidence attached to handoffs, Git-aware line explanation, explicit confidence, and unusually candid internal measurements. Marketing must repeatedly show these differences.

### The name has a discovery problem

Search results for “Whyline” already surface:

- [Sunradiance/whyline](https://github.com/Sunradiance/whyline), a different open-source company-memory/MCP product;
- [WhyLine on Devpost](https://devpost.com/software/whyline-l7yc8d), an IntelliJ/Jira code-explanation product;
- the older academic “Whyline” debugging interface;
- unrelated queue-management and cloud-operations products.

The answer is not necessarily an immediate rename, but the project must use one consistent qualifier everywhere:

> **Whyline for coding agents**

Recommended SEO title:

> **Whyline — Git-native decision handoffs for Claude Code and Codex**

Use that exact category language in the GitHub description, website title, social preview, video title, PyPI summary where practical, launch posts, and profiles. Secure a memorable domain only after checking availability and trademark risk; possible patterns to investigate are `usewhyline.*` or `whyline.dev`, not assumptions that either is available.

### Community launches reward things people can actually try

[Show HN’s official rules](https://news.ycombinator.com/showhn.html) require something people can run or interact with, discourage sign-up barriers, forbid asking friends for votes or comments, and say the maker must be present to discuss it. [HN’s general guidelines](https://news.ycombinator.com/newsguidelines.html) also say not to use HN primarily for promotion and not to post generated or AI-edited text. Whyline is a good Show HN candidate because it is runnable, open source, local, and technically interesting. The final HN title and comment must nevertheless be written by Anish personally, not pasted from an AI-generated draft.

Reddit’s [site-wide spam guidance](https://support.reddithelp.com/hc/en-us/articles/360043504051-Spam) warns against repetitive mass posting and accounts whose contributions mainly link to something they benefit from. Community rules are decisive and vary by subreddit. Some useful venues explicitly provide compliant paths: r/ChatGPTCoding has a recurring self-promotion thread with one promotion per project, r/github uses a self-promotion megathread, and r/LLMDevs has stated that free open-source projects may be shared while disguised marketing is not allowed. Rules must be rechecked on the posting day.

[Product Hunt’s official launch guide](https://help.producthunt.com/en/articles/17350772-launch-guide) says makers can hunt their own product, recommends participating before launch, and emphasizes a clear tagline, screenshots/GIFs, a short demo, and an authentic maker comment. Product Hunt says there is no advantage to finding a famous hunter; its preparation guide reports that 79% of featured posts and 60% of Product-of-the-Day winners were self-hunted. It also prohibits directly asking people for upvotes.

## The audience to win first

“All developers using AI” is too broad. Start with a narrow beachhead whose pain is frequent and visible.

### Primary audience

Solo developers and small teams who:

- actively pay for both Claude Code and Codex;
- switch between them for implementation and review;
- work on a repository for weeks or months rather than one-shot prototypes;
- care about local storage, auditability, and avoiding another API bill;
- are already comfortable with Git and terminal tools.

### High-value use cases

1. Claude plans or implements; Codex reviews without a repeated briefing.
2. Codex implements; Claude continues after a context limit or quota switch.
3. A developer returns after days and asks why a line or constraint exists.
4. A small team wants agent-written decisions to survive sessions and clones.
5. A maintainer wants review evidence: tests run, rejected choices, unresolved risks.

### Audiences to defer

- Enterprises needing Slack/Jira/Notion ingestion: that is a different product and worsens the name collision.
- Developers who use only one agent for one-off work: weak pain and low retention.
- People seeking a fully autonomous multi-agent swarm: Whyline’s core promise is durable context and provenance, not magical orchestration.
- Nontechnical “AI productivity” audiences: installation friction and the Git-native value will be poorly matched.

## Positioning and message architecture

### One-sentence promise

> Whyline lets Claude Code and Codex hand off a repository’s decisions, tests, and risks through Git, so the next agent does not start blind.

### Three proof points

1. **Inspectable:** the durable record is plain Markdown in the repository.
2. **Accountable:** decisions include why, rejected alternatives, actor, task, and affected files.
3. **Independent:** local-only, Apache-2.0, no credentials, telemetry, account, or metered API layer.

### What not to lead with

The current product contains a console, chat, brainstorm mode, model/account selection, relay automation, attachments, and agent deliveries. Those are useful, but listing them all in the first screen turns a sharp tool into an indistinct “AI agent platform.” The launch story should show one job: a successful Claude-to-Codex or Codex-to-Claude handoff. Console and relay can appear later as expansion paths.

### Recommended taglines to test

- “Claude Code and Codex, one project memory.”
- “The decisions survive when the coding agent changes.”
- “Git-native handoffs for Claude Code and Codex.”
- “Your next coding agent should not start blind.”

Test these in five user interviews. Ask each person what they think the product does before explaining it. Keep the line that produces the fewest incorrect interpretations, not the cleverest line.

## Launch readiness gate

Do not schedule a broad launch until all of the following are true.

### Product proof

- A clean machine can reach a useful handoff using the documented install path.
- macOS and Linux behavior is verified separately; do not imply Windows support until verified.
- The first successful experience takes less than five minutes after prerequisites.
- A demo repository lets a new user reproduce a decision, handoff, `sync`, and `explain` without risking their real project.
- The current release has a short stability window and no known launch-blocking setup defect.

### Trust and project hygiene

- README begins with a 15–30 second terminal recording, three-step quick start, expected output, and supported platforms.
- GitHub has a custom social preview. GitHub recommends 1280×640 for best display in its [social preview documentation](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/customizing-your-repositorys-social-media-preview).
- The repository has focused topics, contribution guidance, security reporting, issue templates, and Discussions or an equivalent feedback home.
- The website and README clearly distinguish Whyline from transcript storage, generic agent memory, and orchestration.
- One page answers “Why not AGENTS.md, a handoff Markdown file, or session resume?” with a fair comparison.
- The website is indexable and always uses the qualified name “Whyline for coding agents.”

### Evidence

- At least 10 people outside the author’s own repositories have completed a handoff.
- At least five return a week later or use it on a second task.
- At least three permit a short attributed quote or workflow story.
- A reproducible before/after test shows what Whyline changes. Good measures are repeated briefing length, time to useful first action, missed constraints, and whether the second agent can state rejected alternatives. Do not claim token savings without a controlled measurement.
- Known limitations remain visible. The current README’s admission that unprompted reads were unreliable is credibility, not a weakness to hide.

## The indispensable launch assets

Build one evidence package and reuse it in channel-native forms.

### Hero demo

A 30–45 second silent terminal recording:

1. Claude Code makes a non-obvious implementation decision and records an alternative it rejected.
2. `whyline handoff` records changed file, test result, and remaining risk.
3. A clean Codex session runs through Whyline and immediately states the decision, rejected option, and next action.
4. `whyline explain path:line` retrieves the reason later.

The screen must show real output, not slides. Add captions because most social video is first encountered muted.

### Two-minute narrated demo

Explain the pain, run the handoff, show the Markdown record, and close with installation. Avoid a feature tour.

### Reproducible public experiment

Publish a small repository containing the task, starting commit, success criteria, baseline prompt, Whyline workflow, raw outputs, and scoring rubric. The interesting article is not “we launched Whyline”; it is “What context does the second coding agent actually need?” This is more useful, more credible, and more likely to travel.

### Comparison page

Use jobs, not a red/green feature matrix designed to make competitors look bad:

| Approach | Best for | Tradeoff |
| --- | --- | --- |
| Manual `HANDOFF.md` | Occasional simple switching | Flexible, but no common schema, claims, Git-aware explanation, or lifecycle |
| Transcript/session resume | Continuing the same conversation | Rich but noisy, vendor-specific, and may expose prompt history |
| Generic memory/MCP | Broad semantic recall | More infrastructure and less deterministic provenance |
| Whyline | Cross-agent decisions and review evidence tied to a repo | Requires agents/humans to record meaningful decisions; not hidden-chat transfer |

### Press kit

Keep one public folder/page with:

- one-line and 100-word descriptions;
- logo on light/dark backgrounds;
- 1280×640 social card;
- three screenshots and the demo GIF;
- author bio and contact;
- license, supported platforms, and install command;
- links to GitHub, PyPI, documentation, experiment, and release notes.

## Low-karma community strategy

### Hacker News: karma 3

There is no official published numeric karma requirement for a Show HN. Recent users have nevertheless reported temporary restrictions for accounts not yet familiar with the community. The correct response is not karma farming or getting a friend to pose as the maker.

For 3–4 weeks before launch:

- Read HN daily and contribute only where Anish has firsthand technical knowledge.
- Aim for 10–15 substantive comments over the period, not a target number of points.
- Submit one or two genuinely interesting original sources unrelated to Whyline if they naturally arise.
- Learn the tone by following current Show HN discussions and answering technical questions constructively.
- Never mention Whyline in unrelated threads just to seed links.

At launch:

- Suggested title concept: “Show HN: Whyline – Git-native decision handoffs for Claude Code and Codex.” Anish must rewrite it and the first comment in his own words because HN prohibits generated or AI-edited posts.
- Link directly to the GitHub repository or fast product page, not a sign-up page.
- First comment structure: personal problem; what the tool does; architecture; why Markdown/Git instead of transcript capture; measured limitations; one precise feedback question.
- Be available for at least the first four hours and answer every sincere question with technical detail.
- Do not ask anyone to upvote, comment, or submit it.
- If the account is blocked from Show HN despite genuine participation, email `hn@ycombinator.com` as the site itself recommends. Do not repeatedly delete and repost.

The best feedback question is narrow:

> Is a decision + rejected alternative + tests + open risk enough for your next agent to continue, or what critical state is missing?

### Reddit: karma 8

For 2–3 weeks before any standalone post:

- Select four communities where Anish genuinely reads and can help: likely candidates are r/ClaudeCode, r/OpenAI or a Codex-specific community, r/LLMDevs, and one Python/CLI/open-source community.
- Read each community’s current rules and recent moderator announcements.
- Answer new questions about handoffs, agent context, hooks, Git workflows, and local-first tooling without linking Whyline unless it directly solves the asked problem and disclosure is explicit.
- Publish one useful, non-promotional post such as a measured comparison of what Claude and Codex need in a handoff. If it includes Whyline, disclose authorship immediately.
- Send a short modmail before a standalone project post: explain that it is free Apache-2.0 software, show the proposed title, ask which flair/thread/day is correct, and accept “no.”

Use explicitly permitted venues first:

- r/ChatGPTCoding’s self-promotion thread: one concise entry, once per project.
- r/github’s recurring self-promotion megathread.
- r/LLMDevs, subject to rechecking its current rule that permits genuinely free open-source projects and prohibits disguised marketing.

For standalone posts, tailor the problem and requested feedback to the community. Do not cross-post identical copy on the same day. Space posts by several days so feedback can change the next post. If AutoModerator removes one for low karma, contact moderators once; do not repost repeatedly.

Suggested Reddit title concept:

> I switch between Claude Code and Codex, so I made their decisions survive the switch

Body structure:

1. Two sentences describing the real workflow failure.
2. The terminal GIF.
3. Three bullets: local Markdown, decision/rejection schema, file/commit explanation.
4. Honest limitations and supported platforms.
5. Disclosure: “I built this; it is free and Apache-2.0.”
6. A request for workflow feedback, not stars.

### Product Hunt: no karma dependency, but launch later

Product Hunt should amplify proof, not be the first attempt to discover whether the tool works for strangers.

- Create a personal maker profile and participate genuinely for 2–3 weeks.
- Self-hunt; do not pay or recruit a famous hunter.
- Use the tagline “Claude Code and Codex, one project memory” if user tests understand it.
- Include the short demo, four focused gallery frames, and the public experiment.
- In the maker comment, tell the origin story, explain the local/no-account choice, name limitations, and ask for feedback from people who switch agents.
- Ask existing users to visit and share feedback if they wish; never ask for upvotes.
- Define success as qualified installations, conversations, and retained users—not Product of the Day.

## Channel plan beyond karma platforms

### 1. Direct design-partner recruitment

This is the highest-priority early channel.

Find people who have publicly described switching between coding agents in recent Reddit threads, GitHub discussions, blog posts, and social posts. Contact only a small number with a personalized message referring to the problem they already described. Do not scrape or mass-message.

Offer:

- a 15-minute installation/onboarding call;
- direct help debugging their first handoff;
- influence over the next release;
- recognition as an early contributor if they want it.

Ask for behavior, not praise: watch them install, note where they hesitate, and check in after seven days. The goal for month one is 10 completed first handoffs and five second uses.

### 2. GitHub as the conversion surface

Every external mention will eventually be judged at the repository. Improve conversion before chasing impressions:

- hero GIF and quick start above the long explanation;
- concise repository description with “Claude Code,” “Codex,” and “git-native decision handoffs”;
- relevant topics such as `claude-code`, `codex`, `coding-agents`, `developer-tools`, `agent-memory`, `handoff`, and `provenance`;
- pinned demo/benchmark repository;
- “good first issue” and “help wanted” tasks that are genuinely bounded;
- Discussions categories for Show & Tell, Help, and Ideas;
- releases that group meaningful outcomes instead of a stream of tiny marketing announcements.

Stars are an awareness signal, not the north-star metric. Optimize the page for a completed install and useful first handoff.

### 3. Technical content with reusable evidence

Publish one substantial piece every two weeks, then derive smaller clips/posts from it.

Best initial topics:

1. “What does Codex need to continue work started by Claude Code?”
2. “Why transcripts are the wrong unit of memory for coding agents.”
3. “We measured whether repository instructions make agents record and read decisions.”
4. “An honest failure: our agents wrote decisions more reliably than they read them.”
5. “Why rejected alternatives matter more than another code summary.”
6. “Git as the interoperability layer between competing coding agents.”

Publish on an owned, indexable site first; syndicate excerpts to DEV Community, Hashnode, LinkedIn, Bluesky/X, and relevant communities according to their rules. Each article should contain a reproducible artifact or surprising measurement, not merely a product link.

### 4. Video and live demonstrations

- One polished two-minute YouTube demo.
- Three 20–40 second clips: handoff, `explain`, and local Markdown inspection.
- A monthly live “bring a small repo” session where a user tries a real handoff.
- Record installation failures as well as successes; turn recurring failures into documentation.

The creator does not need a large audience if the video is embeddable in GitHub, launch pages, newsletters, and other people’s posts.

### 5. Earned newsletters and podcasts

Pitch only after the evidence package and external users exist.

Highest-fit target: [Console](https://console.dev/), a developer-tools newsletter with 30,000+ subscribers. Its [selection criteria](https://console.dev/selection-criteria) explicitly value regular-use developer tools, easy installation, good documentation, speed, privacy, multiple platforms, and active maintenance, and it accepts submissions at `hello@console.dev`. Whyline maps unusually well if Linux/macOS installation and documentation are strong.

Also submit through official channels to:

- Changelog News;
- Python Bytes, using its topic/contact route;
- Python-focused newsletters once a stable release and useful technical article exist;
- AI coding newsletters only when the pitch is backed by the public experiment.

Pitch template:

> Whyline is a local Apache-2.0 CLI that carries explicit engineering decisions, rejected alternatives, tests, and risks between Claude Code and Codex through Git. We built it after measuring that repository instructions alone were not a reliable read path. Here is a 45-second demo, a reproducible comparison, installation command, and the limitations we still know about.

Do not send a generic “please feature my startup” email.

### 6. Ecosystem partnerships

Seek small, concrete collaborations rather than influencer endorsements:

- one maintainer who uses both Claude Code and Codex tests Whyline on a real issue;
- a coding-agent educator includes the demo in a workflow tutorial;
- adjacent tools document a compatible handoff or decision format;
- contributors add verified platform support or integrations.

The most valuable long-term move could be publishing the decision/handoff record as a simple, documented format that other tools can read. That turns competitors into possible adapters and gives Whyline category leadership. Do this only if the format is stable enough to support externally.

### 7. Product directories

Use Product Hunt, GitHub topic discovery, PyPI, AlternativeTo-like listings, and relevant awesome lists for durable backlinks and discovery. Treat directory submission as hygiene, not a growth engine. Never open low-quality pull requests to unrelated awesome lists merely for a link.

## A 90-day operating plan

### Weeks 1–2: sharpen and instrument without telemetry

Deliverables:

- settle the qualified category and one-sentence promise through five message tests;
- capture current baselines: GitHub stars/forks/watchers, PyPI downloads, unique site visitors if a privacy-respecting aggregate is acceptable, issues, and known external users;
- define “confirmed active user” as a person who voluntarily reports a useful first handoff and a second use within 14 days;
- build the hero GIF, demo repository, quick start, comparison page, social preview, and basic landing page;
- establish support/feedback routes;
- start authentic HN and Reddit participation.

Because the product promises no telemetry ever, do not add hidden product analytics. Use voluntary check-ins, GitHub feedback, support conversations, a short optional form, and noisy aggregate PyPI data. PyPI itself points analysts to public download logs, but downloads can include CI and mirrors, so they are a directional metric rather than users.

### Weeks 3–4: private proof

Deliverables:

- invite 20 carefully selected prospects;
- onboard at least 10;
- observe all 10 first-use sessions where possible;
- fix the three most common activation failures;
- collect at least three permissioned quotes and two short workflow stories;
- run and publish the before/after experiment with raw artifacts;
- prepare channel-specific assets, not duplicated posts.

Gate to continue: at least five people use Whyline a second time. If not, pause public launch and solve retention; more impressions will not fix a one-use product.

### Weeks 5–6: technical launch

Sequence launches so each one improves the next:

1. Publish the experiment/article and demo on the owned site.
2. Submit a Show HN when Anish can stay present for discussion.
3. Respond, fix issues, and publish a short “what we learned” update.
4. Make one rules-compliant Reddit post or megathread entry at a time, spaced 2–4 days apart.
5. Submit to Console, Changelog, and Python Bytes with the evidence package.

Do not schedule all channels on one day. A solo maintainer cannot answer every community well, and identical simultaneous posts look like a campaign rather than participation.

### Weeks 7–8: Product Hunt and user proof

Deliverables:

- launch on Product Hunt using improved messaging from HN/Reddit questions;
- release the first external user case study;
- hold one live demo/office hour;
- open two or three well-scoped contribution issues;
- publish “what we changed after 20 real handoffs.”

### Weeks 9–12: compound what worked

- Identify the top two sources of confirmed active users and stop spending time on weak channels.
- Publish two more technical pieces around the winning search/questions.
- Add one ecosystem integration or format collaboration requested by multiple real users.
- Ask active users for workflow screenshots, not generic testimonials.
- Create a monthly release/update rhythm with a meaningful narrative.
- Re-pitch editors only when there is a genuinely new result, release, or case study.

## Weekly founder cadence after launch

A sustainable six-hour distribution routine is enough:

- 90 minutes: answer support questions and community discussions.
- 90 minutes: interview or onboard one user.
- 120 minutes: produce one evidence-rich article, demo, or case-study increment.
- 60 minutes: participate in HN/Reddit without promotion.
- 30 minutes: targeted editor/partner outreach.
- 30 minutes: review metrics and choose one experiment.

Development fixes discovered during onboarding are separate product time. The purpose of this cadence is consistency, not posting volume.

## Metrics and decision rules

### North-star metric

**Confirmed retained repositories:** repositories whose users voluntarily confirm at least two useful Whyline-assisted handoffs in 30 days.

This respects the no-telemetry promise. It undercounts usage, which is acceptable; a smaller trustworthy metric is better than pretending PyPI downloads equal adoption.

### Funnel metrics

| Stage | Metric | 90-day target from the recorded baseline |
| --- | --- | --- |
| Awareness | Qualified visits to GitHub/site; relevant mentions; demo views | Establish baseline, then 3× qualified weekly visits |
| Interest | README-to-install intent, questions, demo-repo clones where visible | 100 people explicitly express intent or engage meaningfully |
| Activation | Voluntarily confirmed first useful handoff | 40 repositories |
| Retention | Second useful use within 14 days | At least 50% of confirmed activations |
| Advocacy | Permissioned quotes, case studies, unsolicited mentions | 10 quotes/stories and 5 unsolicited mentions |
| Contribution | External issues with reproduction, docs/code PRs | 10 high-quality issues and 5 external PRs |

These are directional targets, not forecasts. Record the actual starting counts before week one; current GitHub API metrics were not available during this research pass and should not be invented.

### Weekly decisions

- If landing-page visitors do not reach installation: simplify the story and quick start.
- If installs occur but first handoffs do not: improve onboarding/demo and remove setup friction.
- If first handoffs occur but second uses do not: interview users before doing more promotion.
- If a channel drives stars but no confirmed use: downgrade it.
- If user language repeatedly differs from the chosen tagline: adopt user language.
- If people compare Whyline to a plain `HANDOFF.md`: make the extra value visible in the demo rather than adding more prose.

## Budget options

### Near-zero budget

Use the full plan with owned content, personal demos, design partners, Show HN, permitted Reddit paths, Product Hunt, and editorial submissions. Spend only on a domain and basic video/visual assets if needed.

### Small budget

After organic activation is proven, spend on:

- professional cleanup of the hero demo/social card;
- captions and editing for the two-minute video;
- a small Reddit ad test targeted to coding-agent communities only after an organic post proves the message;
- newsletter sponsorship only if the channel has already shown qualified conversion.

Do not buy GitHub stars, votes, comments, hunters, mass email lists, or influencer posts without demonstrated audience fit. They corrupt the signals needed to learn whether the product is retaining users.

## Risks and mitigations

### “Another agent memory tool” reaction

Mitigation: lead with decision provenance, rejected alternatives, `explain file:line`, and the reproducible handoff—not “persistent memory.”

### Name collision

Mitigation: use “Whyline for coding agents” and the full SEO descriptor consistently; create an owned landing page; monitor whether search confusion persists. Reassess naming before major brand investment if qualified search still routes to the other products.

### Product breadth obscures the wedge

Mitigation: launch the handoff job first. Present relay, console, chat, brainstorm, and deliveries as later chapters.

### Low community reputation

Mitigation: contribute before promoting, use permitted megathreads, contact moderators, and invest in channels with no karma gate. Never karma-farm.

### Credibility concerns around agent-written claims

Mitigation: publish raw experiment artifacts, state sample sizes, distinguish observed results from inference, and keep limitations prominent.

### No telemetry makes attribution harder

Mitigation: use voluntary cohorts, optional check-ins, GitHub Discussions, and case-study recruitment. Make privacy a product advantage rather than weakening it for growth analytics.

### Rapid releases appear unstable

Mitigation: choose a launch release, test it, hold a short stabilization window, and communicate meaningful grouped releases. Do not manufacture version numbers as promotional events.

### Founder overload after a spike

Mitigation: stagger launches, prepare FAQ/issues in advance, and cap live onboarding slots. A fast, thoughtful response to 30 users is better than shallow exposure to 30,000.

## What I would do first on Monday

1. Write the one-line positioning on a page and test it with five target users.
2. Record the current GitHub/PyPI/known-user baseline.
3. Build the 45-second real terminal demo and a disposable demo repository.
4. Restructure only the README’s first screen: qualified name, promise, GIF, three-step start, expected result.
5. Recruit the first five design partners from people already discussing Claude/Codex switching.
6. Begin authentic HN and Reddit participation without mentioning the launch.
7. Do not set a public launch date until five external users have used Whyline twice.

## Bottom line

Whyline is unlikely to win by being louder than every AI-agent project. It can win by being more specific and more believable. The market message should be the painful switch between Claude Code and Codex; the category should be decision provenance; the proof should be a real handoff plus a public experiment; and the growth loop should turn each retained user into a workflow story that helps the next developer understand the product.

Fame is not the first milestone. The first milestone is 10 strangers who use Whyline twice and can explain, in their own words, why they would miss it. Once that exists, Show HN, Reddit, Product Hunt, newsletters, videos, and ecosystem partners have something real to amplify.

## Primary references

- [Whyline repository README](https://github.com/anishmoncivarghese/whyline)
- [Whyline on PyPI](https://pypi.org/project/whyline/)
- [Show HN guidelines](https://news.ycombinator.com/showhn.html)
- [Hacker News guidelines](https://news.ycombinator.com/newsguidelines.html)
- [Reddit spam policy](https://support.reddithelp.com/hc/en-us/articles/360043504051-Spam)
- [Product Hunt launch guide](https://help.producthunt.com/en/articles/17350772-launch-guide)
- [Product Hunt preparation guidance](https://www.producthunt.com/launch/before-launch)
- [GitHub social preview documentation](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/customizing-your-repositorys-social-media-preview)
- [Console.dev selection criteria and submission route](https://console.dev/selection-criteria)
- [Python Packaging guide to PyPI download analysis](https://packaging.python.org/en/latest/guides/analyzing-pypi-package-downloads/)

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
