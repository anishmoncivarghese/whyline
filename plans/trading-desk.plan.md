<!-- whyline-plan v1 | source: hand | drafted-by: claude | created: 2026-11-03T20:00:00+05:30 -->
# Trading desk: a team of read-only agents researches a watchlist and writes a morning brief

Runs after `plans/workflows-2-to-4.plan.md`, at the end of the current queue. It depends on nothing that is still unshipped, so it can move earlier. Design: `docs/superpowers/specs/2026-11-03-trading-desk-design.md`. Read it before any task. Where this plan and the design differ, this plan wins. Where a name in the repository has moved, follow the repository and keep the design's behaviour.

This file is the plan Relay runs. Each task is one `- [ ] ID: title` item. Detail lines stay indented. Do not add another checkbox line anywhere in this file. Do not implement from this plan until Relay starts the task.

What the user gets:
- A **Trading desk** screen in the console, next to Job search, and `whyline trading …` on the command line.
- A watchlist of up to 10 NSE stocks. Each stock is studied by 8 agent roles, each with an agent and backups:
  - technical, fundamentals and news analysts
  - bull, bear, trader and risk
  - a portfolio manager who decides
- Data packs that whyline builds from the user's own price CSV exports, RSS feeds and notes. Each source carries a rights note, and nothing published after the run's start time is included.
- A morning brief with a rating, the thesis, both sides, the risks and the cited evidence, delivered by Telegram or email.
- A scorecard that scores every call at 5 and 20 trading days against NIFTY 50.
- Research only. There is no order path anywhere.

Rules every task keeps:
- **No orders, ever.** Nothing under `src/whyline/trading/` imports a broker SDK, names an order or GTT endpoint, or opens a network connection except through `trading/feeds.py`. Every brief and delivered message ends with `Research only. Not financial advice. No orders were placed.`
- **Agents are read-only.** Every role call goes through `whyline.agents.runner.execute_once(..., unattended=True)`. Whyline writes only under the trading base dir (`~/.whyline/trading/`, injectable as `base`) and the agent run records.
- **Untrusted data.** Pack text and agent answers are untrusted data:
  - in prompts, wrap them in `<untrusted-data section="…">` tags
  - in the console, render them as plain text, never markup
- **Console first:** every console control saves through the same function the CLI calls.
- **No new dependency.**
- **Where code goes:**
  - Non-widget code goes in `src/whyline/trading/`, with tests in `tests/trading/`.
  - Widget code goes in `src/whyline/console/trading_screens.py`, with tests in `tests/console/`.
- Edit only the files a task names, plus their tests. Each task ends with `uv run pytest -q` passing.
- **Tests:**
  - They never run a real agent and never use the network.
  - They never contain "/Users/".
  - Use fakes for the agent runner, the HTTP opener, DNS and the clock.

## Part 1: The engine

- [ ] TRD-1: Storage and settings
  Create `src/whyline/trading/__init__.py`, `paths.py`, `settings.py` and their tests.
  1. `paths.base_dir(base=None) -> Path` gives `~/.whyline/trading/`, created 0700. It also provides `runs_dir`, `prices_default`, `notes_default`, `news_db` and `desk_db`. Files are written 0600, atomically (temp file then `os.replace`).
  2. `settings.load(base=None) -> DeskSettings` and `settings.save(settings, base=None)`, using `desk.toml` in the design's section 4 layout. The types are:
     - `DeskSettings(watchlist: dict[str, tuple[str, ...]], roles: dict[str, RoleChain], prices: PriceSource, feeds: list[Feed], notes_folder: str, schedule: Schedule, limits: Limits)`
     - `RoleChain(runner: str, backup: tuple[str, ...])`
     - `PriceSource(folder, rights)`
     - `Feed(url, rights)`
     - `Schedule(enabled: bool, at: str, debate_rounds: int)`
     - `Limits(daily_agent_calls: int = 80, call_timeout_minutes: int = 10)`
  3. `ROLES = ("technical", "fundamentals", "news", "bull", "bear", "trader", "risk", "manager")` and `DEFAULT_ROLES` are copied exactly from the design's table. A missing `desk.toml` loads the defaults with an empty watchlist and the default folders.
  4. Small savers, each validating and then saving: `add_symbol(symbol, aliases)`, `remove_symbol`, `set_role(role, runner, backup)`, `set_prices(folder, rights)`, `set_notes(folder)`, `add_feed(url, rights)`, `remove_feed(index)`, `set_schedule(enabled=None, at=None, debate_rounds=None)`, `set_limits(daily_agent_calls=None, call_timeout_minutes=None)`. Each refusal raises `SettingsError` with the design's exact message.
  5. `effective_chain(role, settings, enabled=None) -> list[str]` returns the runner then the backups, minus CLIs turned off in Settings (`whyline.account.enabled_agents`) or not `capabilities.can_run_unattended`.
  Tests:
  - round trip
  - defaults
  - each refusal in the design's section 4, including the empty-rights message
  - 11 symbols are refused
  - a backup that repeats the runner is refused
  - `effective_chain` skips a disabled CLI and `antigravity`

- [ ] TRD-2: Shared JSON answers and document text
  Create `src/whyline/agents/jsonout.py` and `src/whyline/textfiles.py`. Edit `src/whyline/workflows/steps/agent.py` and `src/whyline/jobs/profile.py`. Add tests.
  1. Move the workflow agent step's `_is_type`, `_check` and `_parse_json` into `jsonout` as `check(value, schema) -> str | None` and `parse(text, schema) -> tuple[object, str]`. The workflow step calls them, and its behaviour is unchanged.
  2. Move `jobs.profile`'s `.docx`, `.pdf` and plain-text readers into `textfiles.read_text(path) -> str`, which raises `TextFileError` with the same messages. The CV import calls it, and its behaviour is unchanged.
  Tests: the existing workflow and CV tests pass unchanged; add direct tests for `jsonout.parse` (fenced, bare, invalid, missing field) and for `read_text`.

- [ ] TRD-3: Prices and indicators
  Create `src/whyline/trading/prices.py` and its tests.
  1. `load(folder, symbol) -> Series | PriceProblem`, where:
     - `Series(rows: list[Bar])`
     - `Bar(date: date, open, high, low, close: float, volume: float)`
     - `PriceProblem(reason: str)`
  2. It reads `<SYMBOL>.csv` exactly as the design's section 5 describes:
     - headers matched case-insensitively
     - the three date formats
     - sorted, with repeated dates deduplicated
     - one bad row makes the file unusable, with `row N: <why>`
  3. `cut(series, as_of: date) -> Series` drops rows after `as_of`.
  4. `indicators(series, benchmark: Series | None) -> Indicators` computes:
     - returns over 1, 5, 20 and 60 rows
     - SMA 20, 50 and 200
     - RSI 14 (Wilder)
     - ATR 14 (Wilder)
     - the 52-week (252 rows) high and low, and the % distance from each
     - volume against its 20-row average
     - the benchmark returns and the differences
     Any value without enough rows is `None`.
  5. `stale(series, as_of) -> date | None` gives the last date when it is more than 4 calendar days before `as_of`.
  6. `render(series, ind, start_id=1) -> tuple[str, dict[str, dict]]` returns the `prices.md` text: the last 20 rows as a table with ids `P1..P20`, then the indicators as `P21..`. It also returns the id-to-origin map (file and row date, or `indicator`).
  Tests: hand-computed RSI, ATR and SMA on a 30-row fixture; each date format; a bad row; the cut drops future rows; stale; a missing benchmark leaves its fields `None`.

- [ ] TRD-4: RSS and Atom feeds
  Create `src/whyline/trading/feeds.py` and its tests.
  1. `fetch(feed, *, opener=None, resolve=socket.getaddrinfo, now) -> FeedResult(items: list[NewsItem], error: str)`, with `NewsItem(feed_url, title, summary, link, published: datetime | None)`. The fetch:
     - is `https` only
     - has a 15 s timeout
     - reads at most 2 MB (more is `feed is larger than 2 MB`)
     - follows a redirect only to the same host
     - refuses a host whose any resolved address is private, loopback, link-local or reserved, checked with `ipaddress`, before connecting
     - parses RSS 2.0 and Atom with `xml.etree.ElementTree` and refuses a DOCTYPE
     - strips HTML from the summary and cuts it to 600 characters
     - never raises, putting errors in `error`
  2. `store(items, base=None)` and `items_for(symbol, aliases, as_of, base=None) -> list[NewsItem]`, kept in `news.sqlite` and unique by link. Matching:
     - the symbol or an alias, case-insensitive, on word boundaries
     - `published <= as_of` and within 7 days, or published unknown
     - newest first, at most 30
  Tests:
  - RSS and Atom fixtures
  - a DOCTYPE is refused
  - a 2 MB+ body
  - a cross-host redirect
  - a private address (`10.0.0.5`, `127.0.0.1`, `169.254.1.1`, `::1`) refused without the opener being called
  - a timeout becomes `error`
  - a future-dated item is excluded
  - aliases match on word boundaries ("TCS" doesn't match "TCSL")

- [ ] TRD-5: The data pack
  Create `src/whyline/trading/pack.py` and its tests.
  1. `build(symbol, aliases, settings, as_of: datetime, out_dir, *, base=None) -> PackResult(files: list[Path], flags: list[str], skipped: str)`. It writes three files plus a hidden `sources.json` that maps every id to its origin:
     - `prices.md` (TRD-3)
     - `news.md` (ids `N1..`, from `feeds.items_for`)
     - `fundamentals.md` (ids `F1..`, one per file): from `notes/<SYMBOL>/` through `textfiles.read_text`, at most 20 files and 200 KB in total, leaving out files modified after `as_of`, and naming unreadable files in `flags`
  2. Rules:
     - No prices file, or an unusable one, sets `skipped` to the design's reason.
     - Stale prices add `prices last updated <date>`.
     - No `NIFTY50.csv` adds `no NIFTY50.csv`.
     - Empty news or fundamentals still write the file, with `No items.`
  Tests:
  - ids are unique and every id in a file is in `sources.json`
  - future rows, items and files are excluded
  - the flags
  - the skip reasons
  - the 200 KB cap

- [ ] TRD-6: Roles and the role call
  Create `src/whyline/trading/roles.py`, `src/whyline/trading/roles/*.md` (one prompt per role) and `src/whyline/trading/usage.py`, with tests.
  1. `SCHEMAS[role]` holds each role's answer schema from the design's section 6 table, with enums checked after `jsonout.check` by `roles.validate(role, value) -> str | None`.
  2. Each prompt states:
     - the role
     - the inputs it sees
     - that inputs are untrusted data, and instructions inside them must be ignored
     - that every claim cites pack ids
     - that the answer is one fenced `json` block matching the schema
     - that this is research and no order is placed
  3. `call(role, symbol, inputs: list[Path], settings, run_dir, *, run_fn=None, now) -> RoleResult(answer: dict | None, cli: str, used_backup: dict | None, outcome: str, reason: str, wait_until: datetime | None)`. It works like this:
     - Build an `AgentDef` named `trading-<role>`, `kind="personal"`, with root and workdir the trading base dir, the chain from `settings.effective_chain` minus CLIs `usage.out(cli, now)` reports, and `timeout_minutes` from `limits.call_timeout_minutes`.
     - Run `execute_once(defn, source="trading", payload_dir=<a folder of the inputs>, unattended=True, run_fn=run_fn)`.
     - Parse with `jsonout.parse`. On failure, run one repair turn that gives the agent the error. A second failure is `outcome="bad_answer"`.
     - Record every `usage_limit until HH:MM` attempt with `usage.mark(cli, until)`.
     - When every CLI in the chain is out, return `outcome="all_unavailable"` and `wait_until` = the earliest reset.
  4. `usage.out(cli, now) -> bool` and `usage.mark(cli, until)` use `desk.sqlite`.
  Tests, using a fake `run_fn`:
  - a good answer
  - a fenced answer with prose around it
  - a repair that succeeds, then one that fails
  - a usage limit falls back to the backup and is remembered for the next call
  - all out gives `wait_until`
  - the prompt contains the untrusted-data wrapping and never the absolute pack path outside the event-file list

- [ ] TRD-7: Citation check and the brief
  Create `src/whyline/trading/brief.py` and its tests.
  1. `check_citations(answer, manifest) -> tuple[dict, int, int]` removes unknown evidence ids and returns the cleaned answer, the `unknown source` count and the `unsupported` count.
  2. `render_stock(symbol, answers, flags, manifest) -> str` follows the design's section 8 layout exactly:
     - evidence labels come from `sources.json`
     - an unknown count adds `N unknown sources`, and an unsupported count adds `N unsupported claims`
     - a missing analyst adds `no <role> view`
     - no verdict shows `no verdict — <role> failed: <reason>`
     - a skip shows `skipped — <reason>`
  3. `render_brief(run) -> str` gives the stocks in order, then the feed failures, the scorecard line (TRD-9's `score_line`, injected) and the footer. Agent text is escaped so it can't fake a header or the footer, for example a line in the thesis starting with `Research only`.
  Tests: each flag; the layout against a golden string; the footer is always last; an answer containing the footer text or a fake header can't move or duplicate the real footer.

- [ ] TRD-8: A run: order, resume, waiting and limits
  Create `src/whyline/trading/desk.py` and its tests.
  1. `start(symbols=None, *, source: "manual"|"schedule", now, base=None) -> run_id` creates the run folder and a `queued` row in `desk.sqlite`. It refuses while another run is `queued`, `running` or `waiting`: `A desk run is already in progress.`
  2. `execute(run_id, *, run_fn=None, now_fn=datetime.now, fetch=feeds.fetch)` does the following:
     - fetches all feeds once and stores the items
     - runs TRD-9's `score_pending` first
     - for each stock, builds the pack, then calls the roles in the design's section 7 order with each role's inputs
     - saves `roles/<role>.json` after each answer
     - updates `run.json` and the row with the current stock, role and agent, for the screens
     - finishes by rendering `brief.md` and storing the manager's call
  3. Resume: a role whose saved answer passes `roles.validate` is not called again.
  4. The design's section 7 rules apply:
     - analyst failure
     - other-role failure
     - `all_unavailable` makes the run `waiting` with `wake_at`, and a wait past 12:00 makes the rest `not reached`
     - the 3-hour wall clock
     - the daily call cap, counted in `desk.sqlite` per local date
     - `stop(run_id)` is checked between calls
  5. `resume(run_id)` re-runs `execute` on a `waiting` or `stopped` run. `runs(limit=20)` and `get(run_id)` are readers.
  Tests, using a fake runner:
  - a 2-stock happy path makes 8 calls per stock
  - 2 debate rounds make 10
  - a failed analyst
  - a failed manager gives no verdict, and the next stock still runs
  - waiting then resuming calls only the missing roles
  - past noon gives not reached
  - the cap gives not reached (daily cap)
  - the wall clock
  - stop between calls
  - a second start is refused

- [ ] TRD-9: Scorecard
  Create `src/whyline/trading/score.py` and its tests.
  1. `record_call(run_id, symbol, as_of, manager_answer, base=None)` stores the call with the last stock close and the last NIFTY close on or before `as_of`.
  2. `score_pending(prices_folder, base=None, today)` scores at 5 and 20 rows after `as_of`, with the design's section 9 rules: excess return, right or wrong per rating, hold within ±2%, and pending until enough rows or when NIFTY is missing.
  3. `scorecard(days=90, base=None) -> Scorecard` gives counts per horizon, overall and by confidence, and a hit rate only from 20 scored calls. `score_line(base=None) -> str` gives the 20-day line, or `Too few scored calls to judge (N of 20).`
  Tests: each rating's right and wrong at the boundary; hold at exactly 2%; pending without enough rows; no NIFTY; 19 versus 20 scored calls.

- [ ] TRD-10: Schedule, the tick pass and delivery
  Edit `src/whyline/agents/tick.py` and `src/whyline/cli.py` (the hidden `trading _execute RUN`). Create `src/whyline/trading/tick.py` and `src/whyline/trading/deliver.py`, with tests.
  1. `trading.tick.run(now)` is called from `run_tick` next to `_run_workflows`, inside its own `try` with logging, so its failure never stops the agents, workflows or inbox. It:
     - starts a scheduled run through `schedule.plan_tick(Trigger(kind="weekdays", at=…), last_run_at, accepted_at, now)` when the schedule is enabled, and records missed due times
     - resumes `waiting` runs whose `wake_at` has passed
     - starts runs detached with `agents_tick.detached([sys.executable, "-m", "whyline", "trading", "_execute", run_id])`
  2. `set_schedule(enabled=True)` stores `accepted_at = now`, so turning it on again never catches up old due times.
  3. `trading.deliver.send_brief(run_id)` sends `brief.md` through `whyline.agents.deliver.send` with the delivery stored under `trading:desk` (`deliveries.get` / `deliveries.save`). The subject is `Trading desk brief — <date>`. Results go on the run, and a failed delivery doesn't fail the run. `execute` calls it at the end.
  Tests:
  - due, not due and missed
  - re-enabling doesn't catch up
  - a waiting run resumes after `wake_at`
  - a trading pass that raises doesn't stop `_run_workflows`
  - the delivery is sent once with the footer
  - a delivery failure is recorded

- [ ] TRD-11: Guard test: no order path, no network outside feeds, writes stay in the desk
  Create `tests/trading/test_never_trades.py` only.
  1. An AST scan of `src/whyline/trading/` and `src/whyline/console/trading_screens.py` checks for:
     - no import of `kiteconnect`, `upstox`, `dhanhq`, `smartapi`, `fyers`, `breeze_connect`, `requests` or `httpx`
     - no string literal containing `/orders`, `/gtt`, `place_order`, `modify_order` or `cancel_order` (case-insensitive)
     - `urllib.request`, `http.client` and `socket` used only in `trading/feeds.py`
  2. A full fake run (TRD-8 with fake runner, fetch and clock) under a temporary `HOME` checks that:
     - every file written is under the trading base dir or the agent run records
     - every role call went through `execute_once` with `unattended=True`
     - the brief ends with the footer
  Review focus (the complete list): the checks in 1 and 2 above. Read-only agent mode is the real protection for agent actions; these checks catch mistakes in our own code. The AST scan covers direct imports and literal strings only; names built at runtime are out of scope.
  A gap outside this list is not a reason to reject. The reviewer records it with `whyline handoff TRD-11 --issue "follow-up: <gap>"` and approves; the follow-ups become a later task.

## Part 2: Command line and console

- [ ] TRD-12: `whyline trading`
  Edit `src/whyline/cli.py`. Create `src/whyline/trading/cli.py`, `src/whyline/trading/lines.py` and their tests.
  1. The commands are exactly the design's section 11. Each calls the TRD-1, 8 and 9 functions, prints `SettingsError` messages plainly, and exits 1 on refusal.
  2. `lines.py` holds the texts the CLI and console share:
     - `run_line(run, now)`: `Running INFY · bull · claude · 4m 10s`, `Waiting for codex until 12:27`, `Done 08:41 · 3 verdicts · 1 skipped`, `Stopped`, `Failed — <reason>`
     - `watch_line(symbol, settings)`: the last price date or `no prices file`
     - `chain_line(role, settings)`: the chain as it will be tried, with turned-off CLIs named
  3. `doctor` checks:
     - the folders exist
     - each symbol's prices file
     - `NIFTY50.csv`
     - each feed (through `feeds.fetch`)
     - that each role has at least one runnable agent
     - that the scheduler LaunchAgent is installed when the schedule is on
  Tests: each command with fakes; each line text; doctor with a missing NIFTY file and a role with no runnable agent.

- [ ] TRD-13: Trading desk screen: watchlist, roles, sources
  Create `src/whyline/console/trading_screens.py`. Edit `src/whyline/console/tui.py` to add a **Trading desk** entry next to Job search, opening `TradingDeskScreen`. Add tests.
  1. **Watchlist:** a table of symbol, aliases and `watch_line`, with Add (symbol and aliases) and Remove.
  2. **Roles:** for each role, an agent `Select` and a backups field, with the `chain_line` under it. CLIs that are turned off or have no read-only mode are listed greyed with the reason.
  3. **Data sources:**
     - prices folder and its rights note, with Open folder
     - feeds, with Add (URL and rights), Remove and Test (shows the item count or the error)
     - notes folder
  4. Every control saves through the TRD-1 savers and shows `SettingsError` text inline. Untrusted text (feed titles) is shown as plain `Text`, never markup.
  Tests (Textual pilot, waiting for Selects to settle as the console tests already do):
  - add and remove a symbol
  - set a role
  - refusal text for empty rights
  - a feed title containing `[bold]` shows literally

- [ ] TRD-14: Trading desk screen: schedule, delivery, runs and scorecard
  Edit `src/whyline/console/trading_screens.py`. Add tests.
  1. **Schedule and delivery:** on or off, time, debate rounds, daily cap and timeout, saved through `set_schedule` and `set_limits`. Delivery uses the existing delivery editor from the Agents screens, saved under `trading:desk`.
  2. **Runs:**
     - Run now (`desk.start` then a detached execute)
     - a list of the last 20 runs, with `run_line`
     - a running run's line has a spinner frame and refreshes every second, and the screen can be left while it runs
     - Open brief shows `brief.md` as plain text in a scrollable view
     - Resume on waiting or stopped runs, and Stop on running ones
  3. **Scorecard:** the TRD-9 table and line.
  Tests: Run now starts once and a second press while running shows the refusal; Resume and Stop call the desk functions; the scorecard below 20 shows the too-few text; schedule round trip.

## Part 3: Help, docs and release

- [ ] TRD-15: Help, docs and README
  Edit the console Help text and `README.md`, and create `docs/trading-desk.md`, with tests.
  The Help text and `docs/trading-desk.md` explain:
  - what the desk is (research only, Mode 0) and what it is not (no orders, not advice)
  - the 8 roles and their backups
  - the data sources, their rights notes, and the CSV format with an example
  - point-in-time rules
  - the brief and its flags
  - the scorecard and why it shows no percentage below 20 calls
  - the schedule
  - `whyline trading`
  Tests: the Help mentions the Trading desk and `whyline trading`; the doc contains the footer text and the CSV header.

## Publish

- [ ] TRD-16: Publish whyline with TRD-1..15
  relay-profile: release
  Bump the version in `pyproject.toml`, `src/whyline/__init__.py` and `uv.lock` to the next patch version. Write `docs/releases/v<version>.md` from every task since the previous release (`git log v<previous>..HEAD`), in user terms. Run `uv run pytest -q` with the agent CLIs off PATH and `GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1`, and again on Python 3.11. Push, wait for green CI on Linux and macOS, then tag `v<version>`, push the tag and let the release workflow publish to PyPI. Afterwards run `uv tool upgrade whyline` and confirm `whyline --version`.
