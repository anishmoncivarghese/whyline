# Brainstorm: /Users/anish/TradingPlatform look at this there PRD document, understand this question was Say if I take a open source model can I train it for quant analysis like, stock market prediction. Stock market prediction is difficult but what all things will be required to say set up a model which does the research and get the information. Say even after training there should be a smaller model which on a daily basis do research feed into the model RAG so that model can make decision , sentiment analysis , India Trade etc, I was thinking of prediction India market.

## Codex

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

## Antigravity

# Independent Research Pass: Training Open-Source Models & Hierarchical Multi-Model RAG for Indian Quant Trading

**Author:** Antigravity (Independent Pass)  
**Date:** September 30, 2026  
**Target Repository:** `/Users/anish/TradingPlatform`  
**Referenced Document:** [PRD AI-Assisted Quant Research & Algo Trading Platform.md](file:///Users/anish/TradingPlatform/PRD%20AI-Assisted%20Quant%20Research%20&%20Algo%20Trading%20Platform.md)  
**Core Question Under Analysis:**
> *"Say if I take an open source model can I train it for quant analysis like, stock market prediction. Stock market prediction is difficult but what all things will be required to say set up a model which does the research and get the information. Say even after training there should be a smaller model which on a daily basis do research feed into the model RAG so that model can make decision , sentiment analysis , India Trade etc, I was thinking of prediction India market."*

---

## 1. Executive Summary & Core Verdict

The user's intuition contains a fundamentally sound insight paired with a dangerous retail misconception:

1. **The Dangerous Misconception: Direct Price Prediction via LLM Fine-Tuning.**
   Attempting to train or fine-tune an open-source Large Language Model (e.g., Llama-3, Qwen-2.5, DeepSeek) to directly output stock price predictions, next-day directions, or buy/sell orders is mathematically and empirically flawed. Financial price time-series have a near-zero signal-to-noise ratio (SNR), extreme non-stationarity, and continuous numerical properties that standard Byte-Pair Encoding (BPE) auto-regressive tokenizers mutilate. Furthermore, commercial and open LLMs are already contaminated with post-cutoff historical price memory, invalidating historical backtesting.
2. **The Sound Insight: A Two-Tier Research Agent & Point-in-Time RAG Architecture.**
   Deploying a lightweight, fast, open-source model (e.g., `Qwen-2.5-7B` or `Llama-3.1-8B` alongside `FinBERT`) as an automated **Daily Research Worker** that extracts structured event data, filters noise from corporate filings and news, and populates a **Point-in-Time Historical Memory (RAG)** is an institutional-grade architecture.
3. **The Necessary Quant Separation (The PRD Core Principle):**
   To make this work in the Indian equity market (NSE/BSE), the platform must enforce strict separation of concerns:
   - **Language Models (LLMs):** Extract structured facts, event categories, sentiment polarity, and guidance revisions from raw text. They **never** output price targets or trade orders.
   - **Time-Series & Tabular Models (LightGBM, XGBoost, Chronos-2):** Combine structured event signals with numerical price/volume/macro features to generate probabilistic forecasts ($P(\text{up})$, expected return, volatility quantiles).
   - **Deterministic Code (Risk & Execution Engine):** Sizes positions, validates portfolio limits, computes transaction friction, checks SEBI compliance, and interfaces with Zerodha Kite Connect.
   - **Human-in-the-Loop:** Approves the evening trade plan; automated systems handle execution and risk reduction.

---

## 2. Deconstructing the Hypothesis: Can You Train an Open-Source Model for Quant Analysis?

### 2.1 Why Direct LLM Price Prediction Fails

When machine learning practitioners attempt to prompt or fine-tune an LLM with historical price sequences (e.g., `"Here are the last 30 daily closes for RELIANCE.NS. Predict tomorrow's close."`), failure is guaranteed due to five structural reasons:

```
[ Raw Price Time-Series ] ──> [ BPE Tokenizer ] ──> [ Auto-Regressive Attention ] ──> [ Hallucinated / Overfitted Output ]
         ❌ Numbers split arbitrarily        ❌ Optimizes text perplexity,         ❌ Uncalibrated probabilities,
            ("1245.50" -> "12","45",".","50")   not financial loss / Sharpe           zero risk awareness
```

1. **Tokenization Pathology:** LLM tokenizers (tiktoken, SentencePiece) split numbers based on corpus frequency rather than mathematical value. `1024` might be a single token, whereas `1025` might be split into two (`"10"` and `"25"`). This completely breaks arithmetic continuity and ordinal spatial relationships.
2. **Information-Theoretic Mismatch:** Financial prices follow stochastic processes with fat tails, volatility clustering, and low SNR ($R^2 < 0.01$ per step). LLMs optimize cross-entropy loss over token sequences; when applied to high-entropy financial noise, the model rapidly overfits spurious historical sequences.
3. **Catastrophic Forgetting & Non-Stationarity:** Financial market regimes shift violently (e.g., 2020 COVID crash, 2022 rate hike cycle, 2024–2026 Indian retail liquidity boom). LLM fine-tuning suffers from catastrophic forgetting when trained on sequential non-stationary regimes.
4. **Pre-training Data Snooping (Lookahead Leakage):** Any open-source model pre-trained on Common Crawl or web dumps has already absorbed future financial reports, historical prices, and news outcomes. Backtesting a 2021 strategy using a 2024 model produces completely contaminated, irreproducible backtests.
5. **Lack of Calibrated Uncertainty:** Quant trading requires probability distributions (e.g., "62% probability of $>0.8\%$ return with 1.2% downside standard deviation"), not deterministic narrative tokens.

---

### 2.2 The Valid Role of Open-Source Models: The Modular Quant Stack

Rather than training a monolithic "all-in-one" trading model, modern quant architecture divides labor across three distinct model classes:

| Model Tier | Optimal Model Selection | Function in System | Training / Adaptation Strategy |
| :--- | :--- | :--- | :--- |
| **A. Unstructured Research & NLP** | `Qwen-2.5-7B-Instruct` / `Llama-3.1-8B-Instruct` + `FinBERT` | Text-to-feature extraction, corporate filing parsing, news triage, entity normalization | LoRA / QLoRA fine-tuning on annotated Indian corporate filings (NSE/BSE) for strict JSON event generation. |
| **B. Continuous Time-Series Forecaster** | `Amazon Chronos-2` / `TimesFM` / `PatchTST` | Zero-shot / fine-tuned probabilistic quantile forecasting (P10, P50, P90 returns) | Pretrained time-series foundation models fine-tuned on historical NSE daily/hourly OHLCV + macro covariates. |
| **C. Cross-Sectional Alpha & Meta-Model** | `LightGBM` / `XGBoost` / `CatBoost` | Combines NLP event scores, technical indicators, macro cues, and quantile forecasts into $P(\text{up})$ and rank IC | Purged, walk-forward training on tabular feature matrices. |

---

## 3. Designing the Autonomous Research & Information Ingestion Pipeline

To generate next-day signals for the Indian market, the system must continuously ingest, parse, and normalize both domestic market data and global overnight catalysts.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                INGESTION SOURCES                                       │
├──────────────────────────┬─────────────────────────────┬───────────────────────────────┤
│ Indian Market Data (EOD) │ Indian Unstructured Filings │ Global Overnight & Macro Cues │
│ - NSE Bhavcopy Archives  │ - NSE Corporate Announce.   │ - GIFT Nifty (GIFT City)      │
│ - Delivery % & Traded Val│ - Quarterly Financials      │ - US Markets: S&P, Nasdaq, VIX│
│ - Kite Connect EOD/1-min │ - Board Meetings & Capex    │ - US 10Y Yield & DXY Index    │
│ - FII / DII Net Cash Flow│ - Promoter Pledge (SEBI PIT)│ - Brent Crude Oil & Gold      │
│ - NSE F&O Open Interest  │ - Financial Media & Press   │ - Asian Markets (Nikkei, HS)  │
└────────────┬─────────────┴──────────────┬──────────────┴───────────────┬───────────────┘
             │                            │                              │
             ▼                            ▼                              ▼
┌──────────────────────────┐ ┌───────────────────────────┐ ┌─────────────────────────────┐
│ Parquet Storage (PIT)    │ │ Local Worker LLM (Triage) │ │ Macro Alignment Engine      │
│ `published_at` timestamp │ │ Qwen-2.5-7B / FinBERT     │ │ Overnight delta calculation │
└────────────┬─────────────┘ └────────────┬──────────────┘ └─────────────┬───────────────┘
             │                            │                              │
             └────────────────────┬───────┴──────────────────────────────┘
                                  ▼
                   ┌──────────────────────────────┐
                   │ Point-in-Time Vector DB      │
                   │ & Historical Analogue RAG    │
                   │ (Qdrant / pgvector)          │
                   └──────────────┬───────────────┘
                                  ▼
                   ┌──────────────────────────────┐
                   │ Feature Store (Polars/DuckDB)│
                   │ Technical + NLP + Macro      │
                   └──────────────┬───────────────┘
                                  ▼
                   ┌──────────────────────────────┐
                   │ LightGBM Meta-Predictor      │
                   │ & Deterministic Risk Engine  │
                   └──────────────────────────────┘
```

### 3.1 Primary Indian Market Data Ingestion
1. **NSE Bhavcopy & Delivery Statistics:**
   - **Delivery Quantity to Traded Quantity Ratio:** High delivery percentages ($>60\%$) coupled with unusual volume indicate institutional accumulation or distribution, filtering out retail intraday churn.
   - **Price Adjustment Engine:** Corporate actions (splits, bonuses, dividends, rights issues) must be maintained in dual format:
     - *Adjusted series:* Used strictly for calculating continuous historical returns and technical indicators.
     - *Unadjusted series:* Used for order execution, historical gap analysis, and options strike tracking.
2. **Institutional Flows (FII & DII Data):**
   - Daily net buying/selling in cash equity and F&O index futures published daily by NSE around 18:30 IST. Strong correlation with next-day market momentum.
3. **Zerodha Kite Connect Historical Data:**
   - Provides verified historical minute/daily candles. Kite Connect now bundles historical data directly into its flat ₹500/month Connect API tier.

### 3.2 Indian Corporate Filings & Unstructured Announcements
The primary repository of Indian corporate truth is the **NSE NEAPS** and **BSE Corporate Announcements** system:
- **Earnings Releases & Investor Presentations:** Revenue, EBITDA margin surprise vs consensus, management guidance revisions.
- **Regulatory Filings under SEBI (LODR) Regulations, 2015:**
  - Material events under Regulation 30 (contract wins, litigation, plant shutdowns, regulatory inspections/USFDA 483s).
  - Shareholding patterns under Regulation 31 (promoter pledging, mutual fund holding changes).
  - Insider disclosures under SEBI (Prohibition of Insider Trading) Regulations (Form C disclosures of promoter/director market transactions).
- **Bulk & Block Deals:** Large institutional transactions executed during trading hours or in special windows.

### 3.3 Global Overnight Macro Cues (Critical for Indian Next-Day Opening)
The Indian equity market (09:15–15:30 IST) is heavily influenced by overnight global developments:
1. **GIFT Nifty (formerly SGX Nifty):**
   - Trades at GIFT City from 06:30 IST to 03:40 IST (next day).
   - The price spread between GIFT Nifty at 08:30 IST and the previous day's NSE Nifty 50 close is the single strongest predictor of the morning gap-up or gap-down.
2. **Brent Crude Oil:**
   - India imports $>85\%$ of its crude oil requirements. Sudden spikes in Brent directly hurt the Indian Rupee (INR), widen the current account deficit, and compress margins for downstream sectors (Asian Paints, Berger Paints, MRF, HPCL, BPCL).
3. **US Treasury Yields (10Y) & US Dollar Index (DXY):**
   - Rising US yields trigger capital outflows from emerging markets (FII net selling in India).
4. **US & Asian Equities:**
   - Performance of S&P 500, Nasdaq 100, and CBOE VIX overnight, followed by early Asian trade (Nikkei 225, Hang Seng, Kospi between 05:30 and 08:00 IST).

---

## 4. The Two-Tier Agent + Point-in-Time RAG Architecture

The user explicitly requested: *"a smaller model which on a daily basis do research feed into the model RAG so that model can make decision, sentiment analysis, India Trade etc."*

Here is the exact blueprint for implementing that workflow:

### 4.1 Tier 1: Small Local Worker Model (Triage & Information Extraction)
Instead of running expensive LLM API calls on thousands of daily press releases, a lightweight local model runs as a daemon or scheduled batch process.

- **Recommended Setup:** `Qwen-2.5-7B-Instruct` or `Llama-3.1-8B-Instruct` quantized to 4-bit (AWQ / GPTQ) running on a modest GPU (Nvidia RTX 3060/4060 or cloud instance) via `vLLM` or `Ollama`.
- **Processing Flow:**
  1. Ingest raw text from RSS feeds, NSE announcement JSON payloads, and news APIs.
  2. **Noise Filtering:** Discard boilerplate compliance filings (e.g., loss of share certificates under Reg 39(3), compliance certificates under Reg 7(3), credit rating confirmations with no change).
  3. **Entity Resolution:** Map colloquial names ("TaMo", "Tata Motors Ltd", "JLR parent") to official NSE symbol `TATAMOTORS` and ISIN `INE155A01022`.
  4. **Strict Schema Extraction:** Output structured JSON conforming to a Pydantic schema using constrained decoding (via `Outlines` or `Instructor`).

```json
{
  "ticker": "TATAMOTORS",
  "isin": "INE155A01022",
  "event_type": "earnings_guidance",
  "sentiment_polarity": 0.78,
  "surprise_direction": "positive",
  "surprise_magnitude_std": 1.45,
  "catalyst_horizon_days": 3,
  "confidence_score": 0.92,
  "source": "NSE_NEAPS_CORP_FILING",
  "published_at": "2026-09-30T17:45:12+05:30",
  "headline": "Tata Motors reports Q2 EBITDA margin expansion of 180 bps led by JLR demand; raises FY outlook."
}
```

- **Sentiment Calibration:** FinBERT (or an Indian-market fine-tuned BERT model) provides a fast, deterministic check on the LLM's sentiment scoring to prevent generative hallucinations.

---

### 4.2 Tier 2: Point-in-Time Financial RAG (Market Memory Engine)

Standard document RAG is dangerous in quantitative trading because it retrieves text without understanding the subsequent market reaction or temporal constraints. We implement **Point-in-Time Quant RAG**:

```
[ Incoming Event: Tata Motors Margin Beat ]
                       │
                       ▼
┌────────────────────────────────────────────────────────┐
│ Vector DB Filter: `published_at` < Simulation Timestamp│
│ (Strictly prevents lookahead leakage)                  │
└──────────────────────┬─────────────────────────────────┘
                       │
                       ▼
┌────────────────────────────────────────────────────────┐
│ Historical Analogue Retrieval Engine                   │
│ Matches: Similar margin beats in Auto/Manufacturing    │
│ during similar Macro Regimes (e.g., Crude > $80)       │
└──────────────────────┬─────────────────────────────────┘
                       │
                       ▼
┌────────────────────────────────────────────────────────┐
│ Statistical Output Distribution                        │
│ - Historical N=14 analogues                            │
│ - T+1 Forward Return: Mean +1.4%, Win Rate 71%        │
│ - T+3 Forward Return: Mean +2.1%, Win Rate 64%        │
│ - Max Drawdown across analogues: -1.8%                 │
└────────────────────────────────────────────────────────┘
```

1. **Temporal Filtering (`published_at`):**
   Every stored vector in the vector database (e.g., Qdrant, Milvus, or PostgreSQL with `pgvector`) contains strict metadata: `published_at`, `effective_at`, `ticker`, `sector`, and `regime_id`.
   When retrieving analogues during a backtest or live trading cut-off at 18:00 IST on date $T$, the vector query **must enforce**:
   $$\text{Filter: } \texttt{published\_at} \le T_{\text{cutoff}}$$
   This mathematically prevents the RAG system from retrieving events that happened in the future.
2. **Analogue Vector Representation:**
   The embedding is computed over the event summary combined with the macroeconomic regime at that time:
   `Embedding = Enc(Event_Summary + Sector + Macro_Regime)`
3. **Retrieval Output is Quantitative, Not Conversational:**
   The RAG engine does not return an essay. It returns an aggregated statistical object:
   - Sample size of historical analogues ($N$)
   - Historical win rate over 1, 3, and 5 trading days
   - Expected return and standard deviation
   - Maximum historical adverse excursion (MAE) to calibrate stop-loss width.

---

### 4.3 Tier 3: Selective Escalation to Frontier LLMs (Cost Control)

For the vast majority (95–98%) of corporate announcements, the local 7B/8B model is completely sufficient. However, complex, ambiguous events require frontier reasoning:
- Hostile takeover bids / complex demergers (e.g., Jio Financial spin-off).
- Unprecedented regulatory actions (e.g., RBI banning a bank from issuing digital credit cards or SEBI barring key executives).
- Ambiguous multi-page forensic audit qualifications.

**Escalation Logic:**
- If `local_model_confidence < 0.70` or `event_type == "material_regulatory_action"`:
- Escalate to Claude 3.5 Sonnet, GPT-4o, or Gemini 1.5 Pro via API.
- Cap daily escalations at $\le 20\text{--}50$ calls/day to enforce strict operating budget limits.

---

### 4.4 Tier 4: The Meta-Predictor & Deterministic Risk Execution

The output of the RAG engine and local NLP worker feeds into the statistical decision engine alongside price/volume features:

$$\mathbf{X}_{t} = \big[ \underbrace{\mathbf{x}_{\text{tech}}}_{\text{RSI, ATR, Vol, Gaps}}, \underbrace{\mathbf{x}_{\text{flow}}}_{\text{FII/DII, Delivery\%}}, \underbrace{\mathbf{x}_{\text{macro}}}_{\text{GIFT Nifty, Crude, DXY}}, \underbrace{\mathbf{x}_{\text{nlp}}}_{\text{Sentiment, Surprise}}, \underbrace{\mathbf{x}_{\text{rag}}}_{\text{Analogue } \mu, \sigma, \text{Win\%}} \big]$$

- **The Statistical Model (LightGBM):** Evaluates $\mathbf{X}_t$ to output calibrated $P(\text{up})$ and cross-sectional rank across the liquid universe (Nifty 100).
- **The Deterministic Risk Engine:**
  - Evaluates whether expected return exceeds the **Transaction Cost Hurdle**.
  - Determines position sizing using Volatility-Adjusted Fractional Kelly or Risk-Per-Trade budgeting (default 0.5% portfolio risk).
  - Sets stop-loss and profit target based on $k \times \text{ATR}_{14}$.
  - Enforces portfolio-level constraints (max 20% sector exposure, max 5% single-stock exposure).
- **Human Review & Evening Approval:** The system compiles the top trade proposals by 19:00 IST into an interactive dashboard. The human clicks "Approve", and the armed orders execute via Kite Connect the next morning during the 09:15–11:00 IST execution window.

---

## 5. Indian Market Operational, Cost & Regulatory Realities

Building an algorithmic system for India requires navigating unique statutory, broker, and market-structure conditions.

### 5.1 The Hidden Hurdle Rate: Indian Equity Transaction Costs

A common reason retail algo developers fail is calculating net returns using raw prices or simple brokerage fees. Indian cash delivery (CNC) and intraday (MIS) trades are subject to heavy statutory levies:

| Cost Component | NSE Cash Equity (Delivery / Swing V1) | NSE Cash Equity (Intraday MIS) | Practical Impact on Strategy |
| :--- | :--- | :--- | :--- |
| **Brokerage (Zerodha)** | ₹0 (Zero brokerage on delivery) | ₹20 or 0.03% (whichever is lower) | Minimal impact on delivery. |
| **STT (Securities Transaction Tax)** | **0.1% on Buy AND 0.1% on Sell** (Total = **0.20%**) | **0.025% on Sell only** | **Crushing cost on swing trading.** A 1–3 day swing requires $>0.20\%$ gross return just to pay STT! |
| **Exchange Turnover Charges** | 0.00297% (NSE) | 0.00297% (NSE) | Minor. |
| **GST** | 18% on (Brokerage + Exchange fees) | 18% on (Brokerage + Exchange fees) | Minor. |
| **SEBI Turnover Charges** | ₹10 per crore (0.0001%) | ₹10 per crore (0.0001%) | Minor. |
| **Stamp Duty** | 0.015% on Buy | 0.003% on Buy | Statutory state duty. |
| **DP (Depository) Charges** | **₹13.50 + 18% GST = ~₹15.93 per scrip debit** | ₹0 (No DP debit for intraday) | Severe drag on small position sizes (e.g., selling ₹10,000 of stock costs 0.16% in DP charge alone). |
| **Bid-Ask Spread & Slippage** | 0.05% – 0.15% per leg | 0.05% – 0.15% per leg | Market orders suffer severe penalty; requires limit bands. |

**The Minimum Viable Hurdle Rate:**
$$\text{Total Round-Trip Friction (Delivery Swing)} \approx 0.20\% (\text{STT}) + 0.03\% (\text{Stamp/Fees}) + 0.10\% (\text{Slippage}) + \frac{₹15.93}{\text{Position Size}}$$
For a ₹50,000 trade, round-trip friction is approximately **0.36% to 0.45%**.
Therefore, any trade proposal where the model's expected return is less than **$0.40\% + \text{Modelled Cost} \approx 0.80\%\text{--}1.00\%$** must be rejected by the risk engine.

---

### 5.2 SEBI Algorithmic Trading Regulatory Framework

The regulatory regime governing algorithmic trading in India establishes clear operational constraints for retail developers:

1. **Mandatory Static IP Whitelisting:**
   - Broker APIs (Zerodha Kite Connect) mandate that all order placement endpoints accept requests **exclusively from whitelisted static IPv4 addresses**.
   - Dynamic residential broadband (Airtel, JioFiber), mobile hotspots, and standard laptop connections will fail or face API rejections.
   - **Operational Solution:** The execution engine must reside on a dedicated cloud VPS (e.g., AWS `ap-south-1` Mumbai or DigitalOcean Bangalore) configured with a fixed Elastic/Static IP. The user's laptop serves purely as a monitoring dashboard and approval portal.
2. **Order Rate Limits & Registration Exemption:**
   - Individual trading strategies operating below **10 orders per second per exchange** are classified as personal API usage and do not require formal exchange-level algorithm certification and broker audit.
   - The platform must enforce client-side token-bucket rate limiters ($\le 3\text{--}5$ orders/sec) to ensure it never approaches the 10 orders/sec threshold.
3. **Mandatory Kill Switch & Auditability:**
   - Systems must provide an immediate software kill switch to cancel all open orders, disable new entries, and optionally liquidate active exposure.
   - Complete, immutable audit logs mapping every order to its input features, model score, and human approval signature must be maintained.
4. **Licensing Boundary (SEBI RA / RIA Regulations):**
   - The platform is strictly legal for **personal proprietary trading**.
   - If the user sells trade signals, distributes the RAG recommendations, or automates friends'/family's accounts, it violates SEBI (Research Analysts) Regulations, 2014 and SEBI (Investment Advisers) Regulations, 2013, exposing the operator to severe regulatory penalties.

---

### 5.3 Zerodha Kite Connect Operational Nuances

1. **Daily Morning Session Authentication (2FA Ritual):**
   - Kite Connect API access tokens expire every morning around 06:00 IST.
   - Fully unattended headless boot without user intervention requires automated TOTP generation via Python `pyotp`, or an explicit morning check-in ritual where the user approves the session token at 08:00 IST.
2. **DDPI (Demat Debit and Pledge Instruction):**
   - **Crucial Requirement:** Without an active DDPI on the Zerodha Demat account, selling delivery shares (CNC) requires manual CDSL TPIN generation and SMS OTP entry on the web.
   - An automated swing platform **cannot execute automated stop-losses on delivery holdings without DDPI**. DDPI must be confirmed active before entering live Mode 2.
3. **Execution Order Types & Slippage Control:**
   - Never use raw Market orders (`ORDER_TYPE_MARKET`) on the open; market orders during the 09:15–09:20 opening volatility suffer severe negative slippage.
   - Use **Market-if-Touched (MIT)** or **Limit Orders with a Slippage Band** (e.g., Limit Price = Current Ask + 0.20%). If not filled within 15 minutes, unarm or cancel.
   - Use Kite **GTT (Good-Till-Triggered)** orders for resting stop-losses so protective stops remain active at the exchange/broker level even if the cloud server loses network connectivity.

---

## 6. Validation Methodology: Preventing Lookahead & Data Snooping

In quant finance, more strategies fail from backtest self-deception than bad ideas. Developing an AI-driven platform requires rigorous experimental design:

```
Full Historical Dataset (2018 - 2026)
├──────────────────────┬──────────────────────┬──────────────────────┤
│  Train Split         │  Purge / Embargo     │  Test Split          │
│  (Rolling Window)    │  (Drop Overlapping)  │  (Out-of-Sample)     │
└──────────────────────┴──────────────────────┴──────────────────────┘
         ▲                                              ▲
         │                                              │
Features strictly derived                     Evaluated on unseen future;
from t <= 18:00 IST                           must beat Buy & Hold and
                                              Momentum baselines post-cost
```

1. **Purged and Embargoed Walk-Forward Cross-Validation:**
   - Multi-day holding horizons (e.g., 3-day holding period) cause overlapping return labels in consecutive days ($y_t$ and $y_{t+1}$ share 2 days of common price movement). Standard K-Fold CV creates massive data leakage.
   - We must apply **Purging** (removing training samples whose label window overlaps with the test set) and **Embargoing** (removing training samples immediately following the test set to account for auto-regressive memory).
2. **Point-in-Time Accounting for Financial Fundamentals:**
   - If Infosys reports Q3 earnings on January 12 at 18:30 IST, the Q3 financial figures must **not** be accessible to any feature calculation on January 12 at 18:00 IST or any preceding date.
   - The feature store must index corporate disclosures by `filing_datetime`, not `period_ending_date`.
3. **Survivorship Bias Mitigation:**
   - Backtesting solely on current Nifty 100 members overstates performance by omitting companies that deteriorated, went bankrupt, or were delisted (e.g., Yes Bank, DHFL, Sintex, Reliance Communications).
   - Universe definition must reflect historical index constituent archives on each date $t$.
4. **The Deflated Sharpe Ratio (DSR):**
   - When searching through dozens of model configurations, prompt templates, and feature combinations, backtest performance is inflated by selection bias. We must track the number of trials ($N$) and compute the Deflated Sharpe Ratio (López de Prado) to verify true statistical significance.

---

## 7. Phased Implementation Roadmap & Go/No-Go Gates

To prevent capital loss and control engineering complexity, development must progress through strict, verifiable milestones:

```
[ Phase 0: Data Foundation ] ──> [ Phase 1: Quant Baseline ] ──> [ Phase 2: NLP/RAG Engine ]
  • Parquet lake                  • LightGBM + Chronos-2           • Local Qwen-2.5-7B
  • NSE Bhavcopy + Kite           • Technical & Flow features      • Qdrant Point-in-Time RAG
  • Corporate filings             • Purged Walk-Forward CV         • Historical Analogue stats
                                            │
                                            ▼
                                   [ Gate 1 (G1) Check ]
                                   Sharpe >= 1.0 post-cost?
                                   If NO -> Stop / Research Only
                                            │ Yes
                                            ▼
[ Phase 5: Live Small Capital] <── [ Phase 4: Live Paper Algo ] <── [ Phase 3: Meta-Ensemble ]
  • Approved orders only           • 60 trading days paper          • Ensemble combination
  • Kite API + Static IP           • Zero reconciliation mismatch   • Evening Approval UI
  • Real slippage tracking         • Automated Kill switch test     • Risk engine limits
```

### Phase Details & Success Gates

- **Phase 0: Data Infrastructure & Storage (Month 1)**
  - Automated pipelines for NSE Bhavcopy, Kite EOD data, and corporate disclosures.
  - Parquet data lake with strict `published_at` temporal indexing.
  - Universe filtering: Nifty 100 constituents with historical changes.
- **Phase 1: Pure Quantitative & Time-Series Baseline (Month 2)**
  - Build the non-LLM baseline: LightGBM model trained on technical indicators, delivery %, FII/DII flows, and Chronos-2 quantile forecasts.
  - **Milestone:** Baseline walk-forward performance established without any NLP complexity.
- **Phase 2: Open-Source NLP & Point-in-Time RAG (Month 3)**
  - Deploy local `Qwen-2.5-7B-Instruct` on vLLM/Ollama for daily announcement triage and JSON extraction.
  - Set up Qdrant vector database with temporal filtering for Historical Analogue retrieval.
  - Benchmark extraction accuracy and latency on 1,000 historical filings.
- **Phase 3: Meta-Ensemble & Backtesting Validation (Month 4)**
  - Combine quantitative features with NLP/RAG features into the meta-ensemble.
  - **Gate 1 (G1) Criteria:**
    - Out-of-sample Sharpe Ratio $\ge 1.0$ after deducting full round-trip Indian transaction costs (STT, stamp, slip).
    - Maximum Drawdown $\le 15\%$.
    - Mean Rank Information Coefficient (IC) $\ge 0.03$.
    - *If G1 fails:* System remains in research mode (Mode 0). No money is risked.
- **Phase 4: Paper Trading & Kite Reconciliation (Months 5–6)**
  - 60 consecutive trading days in simulated live execution (Mode 2 Paper).
  - Evening plan published by 19:00 IST; morning pre-open check at 08:30 IST; simulated fills based on actual order-book ticks.
  - **Gate 2 / 3 Criteria:**
    - Paper performance within 30% of backtest expectation.
    - Zero state mismatches between local ledger and Kite Connect API.
    - Verified kill-switch tripping on test triggers.
- **Phase 5: Live Trading (Small Size, Mode 2) (Month 7+)**
  - Live execution on capital allocated specifically for small-size testing (e.g., ₹1,00,000 to ₹2,00,000).
  - Human review and approval required every evening; unattended risk reduction permitted.
  - Track live slippage vs modeled slippage.

---

## 8. Technology Stack & Operational Cost Breakdown

### 8.1 Production Technology Stack

| Layer | Component | Selection & Rationale |
| :--- | :--- | :--- |
| **Language & Environment** | Python 3.11+ | Universal standard for quant research, ML, and broker SDKs. |
| **Data Processing & Lake** | Polars + PyArrow + DuckDB | Extremely fast columnar processing for tick and candle data; out-of-core memory safety. |
| **Tabular & Time-Series ML** | LightGBM, XGBoost, Chronos-2 | Gold standard for cross-sectional tabular alpha and quantile time-series forecasting. |
| **NLP Worker Model** | Qwen-2.5-7B-Instruct via vLLM | Exceptional instruction-following, structured JSON schema generation, low VRAM footprint. |
| **Sentiment Fast-Path** | FinBERT (HuggingFace) | Deterministic sentiment baseline running at millisecond latency. |
| **Vector Database & RAG** | Qdrant (Self-hosted) | Native support for complex payload filters (`published_at <= timestamp`). |
| **Orchestration & Workflow** | Prefect or Dagster | Scheduled daily EOD DAG execution, retries, alert callbacks. |
| **Broker Interface** | Zerodha `kiteconnect` Python SDK | Official SDK, supports WebSocket order feeds and GTT placement. |
| **Hosting & Compliance** | AWS `ap-south-1` (Mumbai) | Minimal latency to NSE, dedicated Elastic IP for SEBI static IP compliance. |

---

### 8.2 Monthly Operational Budget Estimate (INR)

| Expense Item | Provider / Solution | Estimated Cost (₹ / month) | Optimization Notes |
| :--- | :--- | :--- | :--- |
| **Broker API** | Zerodha Kite Connect | ₹500 | Flat fee; historical data now bundled. |
| **Cloud Hosting (Static IP)** | AWS EC2 `t4g.xlarge` (Mumbai) | ₹2,500 – ₹3,500 | Dedicated Elastic IP for SEBI compliance; 4 vCPU, 16 GB RAM. |
| **GPU Inference (Local LLM)** | On-Demand RunPod / Local Rig | ₹0 – ₹2,500 | If run on a local workstation overnight, cost is ₹0. In cloud, spin up spot GPU for 1 hour at EOD. |
| **Frontier LLM Escalation** | Claude 3.5 Sonnet / GPT-4o | ₹1,000 – ₹2,500 | Limited to $\le 30$ escalated complex corporate events/day. |
| **News & Data Feeds** | NSE Web / Free RSS / Public APIs | ₹0 – ₹2,000 | Scraped corporate filings are free; paid news feeds optional in V1. |
| **Total Estimated Op-Ex** | — | **₹4,000 – ₹10,500 / month** | Sustainable for a personal quant project. |

---

## 9. Conclusion & Actionable Next Steps

The user's vision of an autonomous research system using an open-source model and daily RAG is **technically sound and achievable**, provided that:
1. The open-source LLM is used strictly for **structured entity and event extraction**, not for price forecasting or direct order generation.
2. The RAG system implements **Point-in-Time temporal filtering** and acts as an analogue return retrieval engine rather than a generic chatbot.
3. Quant forecasts are generated by **statistical and time-series models (LightGBM, Chronos-2)** that operate on numerical features.
4. The system rigorously models **Indian transaction friction (STT, DP charges, slippage)** and respects **SEBI algo rules (static IP, rate limits, kill switch)**.

### Immediate Practical Next Steps:
1. **Verify DDPI status** on the Zerodha account to confirm whether automated delivery selling is operational.
2. **Provision an Indian cloud VPS with a Static IP** (e.g., AWS Mumbai) and register the IP on the Kite Connect developer portal.
3. **Build the Phase 1 Baseline:** Train a pure numerical LightGBM model on Nifty 100 Bhavcopy features to establish the non-NLP performance benchmark before introducing LLM complexity.
4. **Prototype the Local Filing Parser:** Set up a local `Qwen-2.5-7B` instance using `vLLM` to parse raw NSE corporate announcements into structured Pydantic schemas.
