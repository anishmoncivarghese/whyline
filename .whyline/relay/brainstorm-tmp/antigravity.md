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
