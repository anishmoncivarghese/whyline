# Independent research: an India-focused AI quant research platform

## Bottom line

Yes, an open-weight model can be part of this system, but “train an LLM to predict the Indian stock market” is the wrong framing. The viable product is a **point-in-time research and decision-support pipeline** with four different components:

1. A small language model turns unstructured filings, announcements, policy releases and licensed news into structured, cited event records.
2. Conventional statistical/ML models estimate probabilities, return ranks and risk from numeric features plus those event records.
3. A point-in-time retrieval system gives the research model relevant source documents and historical analogues. Updating this store daily is not model training.
4. Deterministic portfolio, risk and execution code decides whether a forecast is tradable. The LLM never sends an order.

The PRD is directionally strong because it already makes most of these separations. The best next step is not to fine-tune an LLM or build all six models. It is a **data-feasibility and baseline phase**: acquire legally usable point-in-time Indian data, reproduce each day as it was known then, and determine whether simple cross-sectional models beat momentum and no-skill baselines after full costs. If that fails, a larger model and RAG will not rescue it.

The recommended V1 remains long-only or long/cash, end-of-day NSE cash equities, with human approval. Do not start with intraday or F&O. SEBI's studies consistently show that the great majority of individual F&O traders lose money; in FY25 the reported loss-maker rate was about 91% after costs. The system should be allowed to finish as a high-quality research copilot if no durable trading edge is found.

## The key conceptual correction: there is no single “quant model”

The question combines several jobs that should not share a training objective.

| Job | Appropriate method | What is learned or updated |
| --- | --- | --- |
| Read filings/news | Open-weight 7–14B instruct model, plus deterministic parsers | Prompt/schema first; LoRA only after a labelled error set exists |
| Sentiment/event detection | Classifier or small LLM | India-specific labelled events, not generic positive/negative prose |
| Retrieve market memory | Hybrid keyword + vector retrieval with metadata filters | Index receives new documents daily; model weights do not change |
| Forecast returns/ranks | Logistic regression, LightGBM/XGBoost, regularised linear models; time-series foundation model only as a challenger | Rolling numeric training set |
| Estimate volatility/tails | EWMA/GARCH/quantile regression/boosting | Rolling numeric training set |
| Combine signals | Calibrated logistic regression before a more complex meta-model | Strictly out-of-fold base-model predictions |
| Construct portfolio | Optimisation or simple rules | No LLM; constraints and risk budgets are code |
| Execute orders | State machine and broker API | No learned policy in V1 |

This separation prevents a fluent explanation from being mistaken for a calibrated forecast. An LLM may extract “management cut FY27 revenue guidance by 3%” from a filing. It should not convert that sentence directly into “buy/sell.” A forecast model should consume fields such as event type, surprise magnitude, source reliability, novelty and age, alongside market features.

## What the PRD gets right

- NSE execution with US and global markets used as overnight covariates is a coherent India-first scope.
- Point-in-time availability, immutable raw data, historical constituents, corporate actions and cost-aware walk-forward evaluation are correctly treated as foundational.
- Human approval for new risk, autonomous risk reduction, signed approvals, reconciliation and a kill switch form a sensible control boundary.
- LLMs are outside the order path and emit structured events rather than price forecasts.
- A “no edge found” result is accepted as valid.
- Starting with cash equities and deferring intraday and derivatives is the correct risk order.

These choices are more important than which open-weight LLM is selected.

## Changes I would make to the PRD before implementation

### 1. Make data feasibility Gate 0, before model development

The hardest problem is not inference compute. It is reconstructing what was publicly knowable at each historical timestamp and having the rights to use it.

Gate 0 should require a 20-stock pilot over at least five years and preferably a 10–15 year EOD history before the full Nifty 100 build. For every row, preserve:

- `event_time`: when the underlying event occurred;
- `published_at`: source publication timestamp;
- `ingested_at`: when this system first saw it;
- `effective_from`: when the feature may enter a decision;
- source URL/document hash, parser version and correction lineage.

This bitemporal structure is essential for restatements, delayed filings, corrected bhavcopies and macro revisions. “Quarter ended June” is not the availability date of a June-quarter result.

The official NSE MCP page is useful for exploration and exposes five years of bhavcopy history, but its own disclaimer says the data is informational, not for real-time trading or commercial deployment, and does not grant permission to train or fine-tune models. It therefore cannot silently become the production training feed. Obtain explicit licences or use a vendor whose contract permits systematic research, derived features, retention and model training. The same check is required for news archives.

Nifty's current constituent download is not a survivorship-free history. Historical constituent data is a separate NSE Indices product. Without it, a “Nifty 100 backtest” will inadvertently select today's winners in the past.

### 2. Treat the small daily model as an extractor, not a self-training agent

The daily service should not retrain itself from fresh news. It should:

1. ingest and deduplicate documents;
2. resolve company/ticker/entity aliases;
3. classify source and event type;
4. extract structured facts with exact evidence spans;
5. assign confidence and abstain when evidence is insufficient;
6. append the source and record to the point-in-time store;
7. run quality checks before features become eligible.

A useful event schema is richer than the PRD example:

```json
{
  "instrument_id": "NSE:INFY",
  "event_type": "guidance_revision",
  "direction": "negative",
  "surprise_value": -0.03,
  "surprise_unit": "revenue_guidance_midpoint_pct",
  "novelty": 0.92,
  "confidence": 0.88,
  "published_at": "...",
  "effective_from": "...",
  "source_tier": "exchange_filing",
  "source_uri": "...",
  "evidence": [{"page": 4, "text": "..."}],
  "extractor_version": "...",
  "status": "machine_extracted"
}
```

The store should retain both machine output and later human correction. Fine-tuning becomes worthwhile only after hundreds or thousands of reviewed examples reveal stable error categories. Until then, schema-constrained prompting plus a strong validation harness is cheaper and easier to audit.

Generic FinBERT is an English financial-sentiment baseline, not an Indian trading signal. Its three-way positive/neutral/negative output does not understand whether a result beat consensus, whether an order win is material relative to revenue, or whether the news was already priced. India-specific work should focus on **event type, numeric surprise, novelty and tradable horizon**, with multilingual and code-mixed evaluation where needed.

### 3. Define RAG as evidence and analogue retrieval, not a prediction engine

RAG should have two physically or logically separate indexes:

- **As-of evidence index:** only documents available by the decision cutoff. This is what historical replays query.
- **Current research index:** the latest corrected corpus for present-day research.

Every retrieval query must include an `as_of` filter. Otherwise a backtest can retrieve a later annual report, amended filing or retrospective article and leak the future.

Use hybrid retrieval: company/entity filters + event taxonomy + BM25/keyword search + embeddings + reranking. Pure semantic similarity is unsafe for numeric facts and similarly named companies.

Historical analogues should be constructed deterministically. For example, retrieve prior guidance cuts with similar surprise magnitude and regime, then join their subsequent 1/5/20-day returns from the market database. Do not ask the LLM to remember or calculate those returns. The model may summarise the analogue set, but the numeric join and statistics must be code.

### 4. Make simple tabular models the primary forecast baseline

For 100 instruments, daily rows are not “big data.” Ten years yields roughly 250,000 stock-days before filtering, and adjacent observations are highly dependent. A deep foundation model can easily add complexity without independent information.

Begin with these challengers:

- no-skill/base-rate classifier;
- Nifty buy-and-hold and cash;
- 1/3/6/12-month momentum and short-term reversal rules;
- regularised linear/logistic model;
- LightGBM/XGBoost cross-sectional ranker;
- an equal-weight ensemble of independently useful signals;
- Chronos-2 or another time-series foundation model only as a challenger.

Chronos-2 is genuinely open under Apache-2.0 and supports covariates and quantile forecasts, so it is reasonable to test. It should not be declared the default before it beats naive, linear and boosting baselines on the exact financial target after costs. Forecasting a return distribution is not the same as producing profitable portfolio ranks.

Predict modest, testable targets rather than an exact next-day price:

- cross-sectional rank of next-day or next-5-day residual return;
- probability of exceeding the instrument-specific round-trip cost and risk buffer;
- conditional return quantiles;
- realised volatility and downside-tail estimate;
- probability of a stop or gap event.

Neutralise or explicitly model market beta and sector effects so that a model is not rewarded merely for predicting the Nifty direction.

### 5. Strengthen evaluation against research overfitting

Walk-forward testing is necessary but not sufficient when many features, labels, horizons and hyperparameters have been tried. Add:

- a registry of every experiment, including failures;
- purging and embargo for overlapping labels;
- out-of-fold base predictions for the meta-model;
- one final untouched time period used once;
- Deflated Sharpe Ratio and a multiple-testing/backtest-overfitting diagnostic;
- confidence intervals from block/bootstrap methods appropriate for serial dependence;
- calibration curves/Brier score for probabilities;
- regime and sector stability, not only aggregate Sharpe;
- a shadow portfolio that captures every rejected and accepted proposal.

Fixed pass values such as Sharpe >= 1.0, rank IC >= 0.03 and drawdown <= 15% are useful operating targets, but they are not statistical evidence by themselves. The gate must also consider turnover, capacity, trial count, parameter stability and whether a handful of dates/stocks produced the result.

Backtests should simulate:

- the real 18:00 information cutoff and next-session entry window;
- delistings, symbol changes, splits, dividends and constituent changes;
- missing/stale data causing abstention;
- spreads, gap-through-stop loss, partial fills and unfilled limit orders;
- all current taxes and charges plus a conservative slippage stress;
- DP charge per scrip on delivery sales, which is material for small trade sizes;
- operating cost as a separate business metric, not as a reason to accept a bad trade.

### 6. Correct the protective-order assumption

A Kite GTT is a broker-side trigger. When triggered, it places a limit order; it is not a continuously resting exchange stop and a trigger does not guarantee a fill. It may protect against the research server being offline, but not against gaps beyond the limit, insufficient holdings/authorisation, broker failure or exchange rejection.

Therefore:

- model overnight gap risk in position sizing;
- reconcile that GTTs exist and quantities match holdings every day;
- alert on trigger-without-fill and rejected orders;
- define what the user must do during broker outages;
- test DDPI/authorisation and every protective path with the actual account;
- never describe a GTT as guaranteed protection.

Kite also states that an `order_id` only acknowledges OMS placement, not exchange receipt or execution. Completion must be established from order updates/trades and reconciled against holdings and positions.

### 7. Make compliance broker-confirmed, not inferred only from the circular

The PRD is broadly current that the retail algo framework became applicable to all brokers from 1 April 2026. Official NSE material says all API orders require appropriate algo tagging, including orders within the 10-orders-per-second threshold, and a tech-savvy client using a direct API needs a static IP. The 10 OPS threshold relates to strategy-registration treatment; it is not an exemption from every control.

Before Mode 2, obtain written confirmation from Zerodha/NSE-compatible documentation for:

- how this personal strategy is classified and tagged;
- whether and how the static IP is registered;
- current permitted order types and rate limits;
- whether any strategy registration is required for this exact setup;
- DDPI/authorisation behaviour for automated CNC exits;
- sandbox-to-live differences and failure modes;
- the current treatment of black-box logic if the system is ever offered to anyone else.

Keep V1 strictly personal. The moment recommendations or automation are provided to others, Research Analyst/Investment Adviser and algo-provider obligations can change materially. This needs professional compliance advice, not an architectural assumption.

## Proposed system architecture

```text
Licensed/official sources
        |
        v
Immutable raw store + source rights registry
        |
        +--> deterministic parsers / entity resolution
        |             |
        |             v
        |       small LLM extraction --> evidence-linked event ledger
        |                                      |
        +-------------------> point-in-time feature store
                                               |
                           +-------------------+------------------+
                           |                                      |
                    forecast models                       as-of RAG index
                           |                                      |
                           +------------> research brief <--------+
                                           + proposal
                                               |
                                      deterministic portfolio/risk
                                               |
                                         human approval
                                               |
                                      signed execution intent
                                               |
                              broker adapter + reconciliation
```

Research and execution should be separate deployables, service accounts and networks. The execution service accepts only a narrow, versioned proposal schema plus an unexpired approval. It does not accept prose, prompts or tool calls from the research model.

## Minimum data required

### Market and reference data

- Adjusted and unadjusted NSE EOD OHLCV.
- Corporate actions and symbol/identifier history.
- Historical Nifty membership, sector classification and delisted instruments.
- Tradability flags, price bands, surveillance status and liquidity measures.
- Actual broker fills and contract-note charges for cost calibration.

### Company information

- Exchange filings with exact timestamps and original documents.
- Financial results and restatements with publication timestamps.
- Board meetings, corporate actions, shareholding patterns and scheduled results.
- Consensus estimates only if a licensed point-in-time archive is affordable; otherwise do not invent a “surprise” feature from hindsight.

### India and global context

- RBI policy/releases and DBIE series, preserving release vintages where revisions occur.
- MoSPI CPI/IIP/GDP releases with their release calendar and revision history.
- INR, Indian yields, crude/gold, FII/DII flows and market breadth.
- S&P 500, Nasdaq, VIX, US yields, DXY, crude and relevant Asian closes, aligned carefully to IST and actual market-close availability.
- Licensed Indian/global business news. RSS availability is not necessarily a right to archive or train.

Every dataset should have an owner, licence, freshness SLO, expected publication time, correction policy and backfill procedure. A source-rights registry belongs in the architecture, not in procurement notes.

## A safer daily operating loop

1. **During the day:** ingest documents and market data idempotently; quarantine schema changes and duplicates.
2. **After close:** reconcile EOD prices/corporate actions, run extraction, validate timestamps and freeze a decision snapshot.
3. **At cutoff:** materialise features from only eligible records and record a content hash of the complete snapshot.
4. **Forecast:** run calibrated base models and the meta-model; compare every score with the cost/no-trade threshold.
5. **Portfolio:** optimise or rank under cash, sector, correlation, liquidity, turnover and risk limits; allow no-trade.
6. **Explain:** generate the brief only from the frozen snapshot, with citations and clear model uncertainty.
7. **Approve:** user authorises exact instruments, size bands, prices, exits, expiry and invalidation conditions.
8. **Pre-open:** add overnight data and fresh news only to cancellation/reduction logic in V1. Never substitute a new trade without approval.
9. **Execute:** submit permitted limit/stop/GTT instructions, consume order updates and reconcile actual state.
10. **Learn:** after labels mature, append outcomes to the training set; retrain on a schedule only after tests pass, not continuously in production.

The distinction between daily ingestion and scheduled retraining matters. A model that changes weights every day is harder to reproduce, monitor and approve. Daily features can update while a champion model remains frozen for a month or quarter. A challenger can train offline and replace it only after a documented validation and rollback check.

## Practical model and infrastructure choices

For a personal V1, a single CPU VM can run ingestion, tabular inference, DuckDB/PostgreSQL and scheduling. A local 7–14B quantised model can run on a capable workstation or rented GPU batch; a paid frontier API may be cheaper and more reliable for only the highest-importance documents. Training a foundation model from scratch is unnecessary and financially unrealistic.

Use model selection criteria beyond headline benchmarks:

- licence permits intended use;
- structured-output reliability;
- long-document handling and citation fidelity;
- Indian company/entity recognition;
- numeric extraction accuracy;
- English plus required Indian-language performance;
- latency, memory and total monthly cost;
- ability to pin exact weights/tokenizer and run reproducibly.

Evaluate the extractor on a private, manually reviewed set of Indian filings. Report field-level precision/recall, numeric exact match, ticker resolution, evidence correctness and abstention quality. Do not choose it based on chat quality.

## Recommended phased plan

### Phase 0: feasibility and contracts (4–6 weeks)

- Select 20 liquid NSE stocks across sectors plus Nifty benchmarks.
- Secure legally usable price, constituent, filing and news history.
- Implement identifiers, timestamps, raw immutability and as-of queries.
- Hand-audit 30 historical dates for leakage and corporate-action correctness.
- Get broker confirmation of current API/static-IP/tagging/DDPI requirements.

**Exit:** historical day snapshots can be replayed with no known future data; source rights are documented.

### Phase 1: numeric baseline lab (6–10 weeks)

- Build momentum, reversal, linear and LightGBM baselines.
- Model full costs and realistic next-day fills.
- Run purged walk-forward tests and log all trials.
- Add no text features initially.

**Exit:** at least one simple signal has stable, incremental out-of-sample value after costs. If not, stop trading development and retain the research product.

### Phase 2: research copilot and event features (6–10 weeks)

- Build the event taxonomy, source-cited extraction and as-of RAG.
- Create a reviewed Indian event test set.
- Measure whether each event family improves out-of-sample forecasts, not merely extraction accuracy.
- Add a daily brief with provenance and uncertainty.

**Exit:** the text layer provides measurable incremental value or clearly saves human research time. Either outcome is useful; only the former belongs in the trading model.

### Phase 3: shadow/manual operation (at least 20 trading days)

- Freeze models and log plans without automated orders.
- Compare theoretical prices, executable quotes and actual manual fills.
- Exercise stale-data, duplicate-event, bad-model and kill-switch scenarios.

### Phase 4: broker sandbox/paper, then tiny live capital

- Run at least 60 trading days in a broker-realistic environment.
- Test partial fills, rejects, restart recovery, GTT reconciliation and access-token expiry.
- Start live with capital small enough that operational mistakes are tolerable.
- Promote only after live slippage, charge and reliability evidence agrees with the model.

Do not estimate a fixed 6–8 month finish until Gate 0 establishes data access. Vendor negotiation and historical cleaning can dominate the schedule.

## Go/no-go questions that must be answered first

1. What exact decision is being predicted: next close, open-to-close, close-to-open, or a 1–5 day executable return? The label must match the actual approval and entry process.
2. What legally usable, point-in-time Indian news and fundamentals archive is available, at what price and with what model-training rights?
3. Can historical Nifty membership, delistings and identifiers be acquired for the whole test period?
4. Is the intended system personal research only, or could it eventually distribute signals? This changes compliance scope.
5. What starting capital makes fixed DP charges and operating costs tolerable without forcing unsafe position concentration?
6. Is DDPI active, and has the exact automated exit flow been tested?
7. Which failure is safer for each component: abstain, cancel entry, reduce position or alert the user?
8. What objective evidence will cause the project to stop rather than continue tuning?

## Recommendation

Approve the PRD only after adding a **Phase 0 data/licensing gate**, changing the “daily smaller model” into an evidence-cited extraction service, and demoting all complex forecasting models to challengers behind simple baselines. Build the platform first as a reproducible research system with a no-trade option. RAG should improve evidence access and analogue retrieval; it should not be allowed to create hidden future leakage or act as the portfolio policy.

The durable asset is not a fine-tuned LLM. It is the clean point-in-time event ledger, reproducible feature snapshots, realistic simulator, experiment history and operational controls. Models can be replaced. If those foundations are wrong, every model will produce convincing but false precision.

## Primary sources consulted

- [SEBI: Safer participation of retail investors in algorithmic trading, 4 Feb 2025](https://www.sebi.gov.in/legal/circulars/feb-2025/safer-participation-of-retail-investors-in-algorithmic-trading_91614.html)
- [SEBI: implementation glide path; framework applicable to all brokers from 1 Apr 2026](https://www.sebi.gov.in/sebi_data/attachdocs/sep-2025/1759232056254.pdf)
- [NSE FAQ on retail algorithmic trading, including direct-API static IP, tagging and hosting](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/FAQ_Retail%20Algo_03112025_NSE.pdf)
- [SEBI: FY25 equity-derivatives comparison and individual-trader loss data](https://www.sebi.gov.in/sebi_data/attachdocs/jul-2025/1751900271726.pdf)
- [Official NSE AI/MCP data page and use/training disclaimer](https://www.nseindia.com/nse-mcp)
- [NSE Indices data subscriptions, including historical constituent data](https://www.niftyindices.com/offerings/data-subscription)
- [RBI official data releases and Database on Indian Economy](https://statistics.rbi.org.in/)
- [Kite Connect API documentation](https://www.kite.trade/docs/connect/v3/)
- [Kite order semantics: order placement is not proof of exchange receipt or execution](https://kite.trade/docs/connect/v3/orders/)
- [Kite GTT semantics](https://kite.trade/docs/connect/v3/gtt/)
- [Zerodha's current charges and taxes](https://zerodha.com/charges)
- [Amazon Science Chronos repository and Apache-2.0 licence](https://github.com/amazon-science/chronos-forecasting)
- [Prosus FinBERT model card](https://huggingface.co/ProsusAI/finbert)
- [Bailey et al., The Probability of Backtest Overfitting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253)
