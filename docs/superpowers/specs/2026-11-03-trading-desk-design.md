# Trading desk: a team of agents that researches a watchlist and writes a morning brief

Date: 2026-11-03. Status: design for `plans/trading-desk.plan.md` (TRD-1..16).

## 1. What this is, and why

The user wants something like the Job search agent for the Indian stock market. A team of agents, each in a set role and each with backups, studies a short watchlist and hands the user a brief. The role layout follows TauricResearch/TradingAgents (Apache-2.0):

- analysts
- a bull and a bear researcher who debate
- a trader
- a risk reviewer
- a portfolio manager who decides

It is built on what whyline already has:

- the read-only agent runner with backup chains (`whyline.agents.runner.execute_once`)
- the shared scheduler tick
- deliveries (Telegram and email)
- the console

The user's own TradingPlatform PRD and brainstorm (`~/TradingPlatform/`) set the stance, and this design keeps to it:

- The LLM is a **research and extraction layer**. It does not predict prices and it does not trade.
- Data has to be point-in-time (nothing published after the decision time) and from sources the user has the right to use.
- Every call is logged and later scored against an outcome before anyone trusts it.
- In the PRD's terms this is **Mode 0, Research**.

**What success looks like:** on a weekday morning before 09:15 IST, the user opens one brief. For each watched stock it gives:

- a rating
- the thesis
- the bull case and the bear case
- the risks
- the evidence each claim rests on

A scorecard tells the user honestly whether the desk's past calls have been any good.

## 2. Goals, non-goals, anti-goals

**Goals**
- A desk of 8 roles per stock. Each role has an assigned agent and a backup chain, chosen by the user.
- Point-in-time data packs built by whyline from sources the user configures. Every source carries a rights note.
- Answers checked against a schema, with citations checked against the pack.
- A brief delivered by the existing Telegram and email deliveries.
- A scorecard that scores every call at 5 and 20 trading days against NIFTY 50.
- Everything reachable in the console (console first), with `whyline trading …` for scripts.

**Non-goals for this release** (later designs)
- A Kite Connect price source. It needs the credential store from workflows-2 (WF-14).
- Antigravity as a role agent. It has no verified read-only mode in `whyline.agents.capabilities`. It appears in the picker automatically once one is added there.
- A sentiment analyst. There is no licensed social-media source.
- Analysts running in parallel.
- A paper portfolio that tracks positions over time.
- Intraday runs.

**Anti-goals** (any of these makes it a failure even if it works)
- **Any order path.** No broker SDK, no order or GTT endpoint, no code that could place, modify or cancel an order. Moving beyond Mode 0 needs a new design.
- **Scraping exchange websites.** NSE and BSE terms forbid it, and the brainstorm's Gate 0 rules it out. Data comes from files the user exports and RSS feeds the user adds.
- **Agents that can change anything.** Every role runs in its CLI's read-only, unattended-cleared mode, the same as Agents.
- **A brief that reads like advice to act.** Every brief and every delivered message ends with: `Research only. Not financial advice. No orders were placed.` Ratings describe a view on a horizon, not an instruction.
- **Overclaiming the scorecard.** Below 20 scored calls it shows no percentages.

## 3. Files and storage

Everything lives under `~/.whyline/trading/` (folders 0700, files 0600) and is never inside a repository.

| Path | What |
|---|---|
| `desk.toml` | Settings: watchlist, roles, sources, schedule, limits |
| `prices/` | Default prices folder: `<SYMBOL>.csv` and `NIFTY50.csv` |
| `notes/<SYMBOL>/` | Default notes folder: the user's own research files per stock |
| `news.sqlite` | Fetched RSS items, so a re-run reads the same items |
| `desk.sqlite` | Runs, per-stock progress, calls, scores, agent usage-limit memory |
| `runs/<run_id>/` | One folder per run (below) |

A run folder contains:
- `<SYMBOL>/pack/`: the data pack, with a hidden `sources.json` mapping ids to origins
- `<SYMBOL>/roles/<role>.json`: the checked answer of each role
- `<SYMBOL>/verdict.md`
- `brief.md`: all stocks
- `run.json`: status

Role calls also leave the usual agent run records, made by `execute_once`, as workflow agent steps do.

## 4. Settings (`desk.toml`)

```toml
[watchlist]
INFY = { aliases = ["Infosys"] }
HDFCBANK = { aliases = ["HDFC Bank"] }

[roles.technical]      # one table per role; defaults below
runner = "codex"
backup = ["grok", "claude"]

[sources.prices]
folder = "~/.whyline/trading/prices"
rights = "My Zerodha Console exports, personal use"

[[sources.feeds]]
url = "https://example.com/markets.rss"
rights = "Publisher RSS for personal reading"

[sources.notes]
folder = "~/.whyline/trading/notes"

[schedule]
enabled = false
at = "07:30"            # weekdays, local time
debate_rounds = 1       # 1 or 2

[limits]
daily_agent_calls = 80  # 0 = off
call_timeout_minutes = 10
```

Validation refuses each of these with a plain message:
- a symbol that does not match `^[A-Z0-9&-]{1,20}$`
- more than 10 symbols
- a role runner or backup outside the agents that `capabilities.can_run_unattended` accepts
- a backup that repeats its runner
- a feed URL that is not `https://`
- a prices source or feed with empty `rights`: "Say what lets you use this source, for example: my broker export, personal use."
- `debate_rounds` outside 1..2
- `at` not in `HH:MM` format

The rights note is the light version of the brainstorm's source-rights registry. Whyline records it and does not judge it.

**Default roles** (my call; spread across providers, with bull and bear on different agents so the debate isn't one model arguing with itself):

| Role | Runner | Backup |
|---|---|---|
| technical | codex | grok, claude |
| fundamentals | codex | claude |
| news | grok | claude, codex |
| bull | claude | codex |
| bear | codex | claude |
| trader | claude | codex |
| risk | codex | claude |
| manager | claude | codex |

When a default names a provider that is turned off in Settings, the next one in its chain is used. The roles screen shows the chain as the runner will actually try it.

## 5. The data pack (point-in-time)

Built by whyline, never by an agent, for each stock at `as_of` = the run's start time. Every item gets a source id, and `sources.json` records each id's origin (file path and row range, or feed URL, item link and published time).

- **Prices (`prices.md`, ids `P1..`)**
  - Read `<SYMBOL>.csv` with columns `date,open,high,low,close,volume`. Header names are matched case-insensitively and extra columns are ignored.
  - Dates may be `YYYY-MM-DD`, `DD-MM-YYYY` or `DD-Mon-YYYY`. Rows are sorted by date, and a repeated date keeps the last row. A row that cannot be read makes the whole file unusable, with a message naming the row number. A half-read price series is worse than none.
  - Drop rows dated after `as_of`'s date.
  - Show the last 20 rows, plus indicators computed in Python (no new dependency):
    - 1/5/20/60-day returns
    - SMA 20/50/200
    - RSI 14
    - ATR 14
    - 52-week high and low, and the distance from each
    - volume against its 20-day average
    - the same returns for NIFTY 50 and the difference. Without `NIFTY50.csv`, these are left out, the brief flags `no NIFTY50.csv`, and the stock's calls stay pending in the scorecard.
  - A missing file skips the stock: `no prices file`.
  - A last row older than 4 calendar days before `as_of` keeps the stock but flags it `prices last updated <date>` in the pack and the brief.
- **News (`news.md`, ids `N1..`)**
  - Items from the user's feeds, fetched at the start of the run.
  - Only items with `published <= as_of` and within the last 7 days.
  - Matched when the symbol or an alias appears in the title or summary, case-insensitively, on word boundaries.
  - At most 30 per stock, newest first.
  - Each item gives its title, summary (HTML stripped, at most 600 characters), link and published time.
  - An item with no published time is kept as `published unknown` and marked so.
- **Fundamentals (`fundamentals.md`, ids `F1..`)**
  - The text of the user's files in `notes/<SYMBOL>/`: `.md`, `.txt`, `.docx` and `.pdf`, read with the CV import's readers. Those move from `whyline.jobs.profile` to a shared `whyline.textfiles.read_text(path)`, and the CV import keeps calling it.
  - A file that cannot be read is skipped and named in the stock's flags.
  - At most 20 files and 200 KB of text per stock.
  - Files modified after `as_of` are left out.

**Feed fetching**
- `https` only, a 15 s timeout, at most 2 MB per feed.
- Redirects are followed only to the same host.
- A host that resolves to a private, loopback or link-local address is refused.
- RSS 2.0 and Atom are parsed with the standard library.
- A feed that fails is named in the brief's notes, and the run continues.

**Prompts.** Pack files and earlier roles' answers are given to agents as event files, which the runner already labels untrusted. Each prompt wraps them in `<untrusted-data section="…">` and says to ignore any instructions inside them.

## 6. Roles and answers

Each role is a fixed prompt in `src/whyline/trading/roles/<role>.md` plus a JSON schema. A role call is an `AgentDef` named `trading-<role>`, run through `execute_once(..., unattended=True)`. The provider-enabled, unattended-clearance, read-only and backup rules therefore all apply unchanged.

The JSON answer is parsed and checked the way workflow agent steps do it: the first fenced `json` block or the whole answer, then a schema check, with one repair turn. That code moves to a shared `whyline.agents.jsonout`, and workflows keeps calling it.

| Role | Sees | Answer (required fields) |
|---|---|---|
| technical | prices | `summary`, `signal` (positive/neutral/negative), `confidence` (low/medium/high), `points[{claim, evidence[]}]` |
| fundamentals | fundamentals | same as technical |
| news | news | same as technical |
| bull | pack + 3 analyst answers (+ bear's case in round 2) | `case`, `points[{claim, evidence[]}]`, `rebuttal` (empty in round 1) |
| bear | the same, with bull's case | same as bull |
| trader | analysts + debate | `idea` (buy/hold/sell/avoid), `horizon_days` (5 or 20), `invalidation`, `paper_weight_pct` (0..10), `reason` |
| risk | everything above | `verdict` (ok/reduce/reject), `concerns[]`, `notes` |
| manager | everything above | `rating` (buy/overweight/hold/underweight/sell), `confidence`, `horizon_days`, `thesis`, `key_risks[]`, `evidence[]` |

`paper_weight_pct` is a share of a hypothetical paper portfolio, never rupees and never the user's account.

**Citation check** (deterministic, after each answer)
- An evidence id that is not in the pack is removed and counted as `unknown source`.
- A claim left with no evidence is kept and marked `unsupported`.
- The brief shows both counts per stock.

**Usage memory.** When an attempt reports `usage_limit until HH:MM`, the desk stores that time for that CLI in `desk.sqlite`. Until then, every role chain skips that CLI, so the run doesn't try an agent it knows is out.

## 7. A run

Per stock, in watchlist order, one call at a time:
1. pack
2. technical, fundamentals and news
3. bull, then bear
4. with 2 rounds, bull again, then bear again, each seeing the other's case
5. trader
6. risk
7. manager

That is 8 calls per stock, or 10 with 2 rounds.

- **Resume.** A role whose `roles/<role>.json` exists and passes its schema is not called again. Resume is safe after a crash, a stop or a wait.
- **When every agent in a chain is out of usage:**
  - the run becomes `waiting` with `wake_at` = the earliest reset
  - the tick resumes it at that time
  - a wait past 12:00 local time ends the run instead: the stocks not finished are `not reached`
- **Failure rules:**
  - A failed analyst leaves the stock running without it. Later roles are told, and the brief flags `no <role> view`.
  - A failed bull, bear, trader, risk or manager gives the stock `no verdict — <role> failed: <reason>`, and the run moves on to the next stock.
- **Limits:**
  - one run at a time
  - a 3-hour wall clock, after which the remaining stocks are `not reached`
  - the daily agent-call cap, counted across runs and resetting at local midnight; reaching it makes the remaining stocks `not reached (daily cap)`
- **Run states:** `queued`, `running`, `waiting`, `succeeded` (every stock has a verdict or a reason), `failed` (pack or brief could not be written), `stopped`.
- Runs execute detached as `whyline trading _execute <run_id>`, started by Run now or by the tick.

## 8. The brief

`brief.md` per run, rendered by whyline (never written by an agent). For each stock:

```
INFY — Hold · medium confidence · 20 trading days
Thesis: <manager.thesis>
Bull: <first line of bull.case>   Bear: <first line of bear.case>
Trader idea: avoid (paper 0%) · Risk review: reduce — <first concern>
Key risks: <manager.key_risks, joined>
Evidence: P3 (prices, 2026-11-02), N2 (Economic Times, 2026-11-02 18:40), F1 (Q2 results notes)
Flags: prices last updated 2026-10-30 · 1 unsupported claim · no news view
```

After the stocks come:
- feed failures
- the scorecard line (section 9)
- the footer `Research only. Not financial advice. No orders were placed.`

The Telegram and email deliveries send the brief through `whyline.agents.deliver.send` with the delivery the user set for the desk. The desk stores it in `deliveries.toml` under the id `trading:desk`. A failed delivery is shown on the run, and the run still succeeds.

## 9. Scorecard

Each manager verdict is stored as a call with:
- run, symbol, `as_of`, rating, confidence, horizon
- the stock's last close on or before `as_of`
- NIFTY 50's last close on or before `as_of`

Scoring runs at the start of each run and on `whyline trading score`, using the same prices files. At 5 and 20 trading days later (counted in the stock's own CSV rows), the score is:
- excess return = stock return − NIFTY return
- **right** when:
  - buy or overweight, and excess > 0
  - sell or underweight, and excess < 0
  - hold, and |excess| < 2%
- otherwise **wrong**
- pending until enough rows exist

The scorecard shows, for the last 90 days, per horizon, overall and by confidence:
- counts of right, wrong and pending
- a hit rate only when there are at least 20 scored calls
- below that: `Too few scored calls to judge (12 of 20).`

The brief's scorecard line uses the 20-day horizon.

## 10. Console

A **Trading desk** entry next to Job search opens `TradingDeskScreen`, with these sections:
- **Watchlist:** add and remove symbols with aliases. Each row shows the last price date, or `no prices file`.
- **Roles:** for each role, an agent picker and a backup list. CLIs that are disabled in Settings or have no read-only mode are shown greyed with the reason.
- **Data sources:**
  - prices folder, with its rights note and an `Open folder` button
  - feeds: add with a rights note, remove, and `Test` (fetch and show the item count)
  - notes folder
- **Schedule and delivery:** on or off, time, debate rounds, daily cap, and the existing delivery editor.
- **Runs:**
  - Run now
  - the list of runs
  - a running run shows a spinner, the stock and role in progress, the agent, and the elapsed time
  - a waiting run shows `waiting for <cli> until HH:MM`
  - Open brief, Resume and Stop
- **Scorecard:** the section 9 table.

Every control saves through the same function the CLI calls.

## 11. Command line

`whyline trading`:
- `watch add SYMBOL [--alias X]...`, `watch remove SYMBOL`, `watch list`
- `roles`, `role set ROLE --agent X [--backup Y,Z]`
- `source prices DIR --rights TEXT`, `source notes DIR`, `source add-feed URL --rights TEXT`, `source remove-feed N`, `source test-feed N`
- `schedule on|off [--at HH:MM] [--rounds 1|2]`, `limits --daily-calls N --timeout-minutes N`
- `run [--symbol S]`, `runs`, `show RUN`, `resume RUN`, `stop RUN`
- `score`, `doctor` (checks folders, files, feeds, agents and the scheduler)

## 12. Scheduling

The shared tick (`whyline.agents.tick.run_tick`) gets a trading pass next to its workflow pass, isolated so that a failure there never stops the others. It does two things:
- It starts a run when the schedule is due (weekdays at `at`, through `whyline.agents.schedule.plan_tick`, with a `Trigger(kind="weekdays", at=…)`), and records a missed run when the machine was asleep for more than the usual catch-up window. `desk.sqlite` stores when the schedule was turned on (`accepted_at`) and when the last scheduled run started (`last_run_at`). Turning it off and on again resets `accepted_at`, so old due times are never caught up.
- It resumes a `waiting` run whose `wake_at` has passed.

## 13. Safety rules every task keeps

- No code under `src/whyline/trading/` imports a broker SDK or names an order endpoint. Network access is the feed fetcher only. A guard test checks both.
- Agents run read-only and unattended-cleared only. Whyline writes only under `~/.whyline/trading/` and the agent run records.
- Pack text and agent answers are untrusted data everywhere: in prompts, and in the console (rendered as text, never markup).
- Tests never run a real agent, never use the network, and never contain `/Users/`.

## 14. Testing and acceptance

**Unit tests**
- settings validation
- the price cut-off and indicators against hand-computed values
- RSS and Atom parsing
- feed limits and private-host refusal
- pack ids and the manifest
- schema and repair
- the citation check
- resume, waiting and failure rules, using a fake runner
- brief rendering
- scoring
- the tick pass
- CLI and console round trips

**Acceptance**, with fake agents: a 2-stock run, where one stock's manager chain is out of usage, ends with:
- one verdict
- one `waiting` run that resumes after `wake_at`
- a brief carrying the footer, the flags and the evidence ids
- a delivered message
- calls stored for scoring

## 15. Calls made in this design (for review)

- The desk lives in whyline (`src/whyline/trading/`), not in the TradingPlatform repo. It reuses whyline's runner, tick, deliveries and console, and TradingPlatform stays the place for the later quant stack.
- 8 roles: 3 analysts (technical, fundamentals, news), bull, bear, trader, one risk reviewer and the manager. Sentiment is dropped, and the three TradingAgents risk personas become one.
- Data comes from user-exported price CSVs, user-added RSS feeds and the user's notes, with a rights note on each source. Kite comes later.
- Ratings use TradingAgents' five levels. Horizons are 5 or 20 trading days, and scoring is against NIFTY 50.
- Calls run one at a time, because the shared runner sets process environment variables per call.
- The run order puts this plan at the end of the current queue. It depends on nothing that is still unshipped, so it can move earlier.
