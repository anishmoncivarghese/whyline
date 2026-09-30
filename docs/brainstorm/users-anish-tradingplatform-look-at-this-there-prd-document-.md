# Brainstorm: /Users/anish/TradingPlatform look at this there PRD document, understand this question was Say if I take a open source model can I train it for quant analysis like, stock market prediction. Stock market prediction is difficult but what all things will be required to say set up a model which does the research and get the information. Say even after training there should be a smaller model which on a daily basis do research feed into the model RAG so that model can make decision , sentiment analysis , India Trade etc, I was thinking of prediction India market.

## Codex

# Revised synthesis: an India-focused AI quant research platform

## Verdict

Yes, an open-weight model can be useful here, but it should not be trained as a monolithic “Indian stock predictor.” After comparing the independent passes, the strongest design is a modular research system:

1. A small language model reads filings, announcements, policy releases and licensed news, then emits evidence-linked structured events.
2. A point-in-time retrieval layer supplies only information that was available at the decision timestamp and can retrieve comparable historical events.
3. Conventional statistical and machine-learning models estimate return ranks, probabilities, volatility and downside from numeric features plus the structured events.
4. Deterministic portfolio, risk and execution code decides whether a forecast is tradable. The LLM never places or sizes an order.
5. A human approves new exposure; automation may cancel or reduce risk within pre-authorised limits.

The other pass reinforces this separation and usefully makes the “daily worker” concrete. My main revision is to make the proposed two-tier language-model workflow an optional implementation pattern rather than the core source of edge: a local 7–14B model can triage routine documents and difficult cases can be escalated, but the project must first prove data legality, timestamp integrity and a post-cost numeric baseline. Model names, presumed correlations and fixed infrastructure choices should remain hypotheses until benchmarked.

The durable asset is not a fine-tuned LLM. It is the legally usable, clean, point-in-time event ledger; reproducible feature snapshots; realistic simulator; experiment registry; and operational controls. If no stable post-cost edge appears, the same platform can still succeed as an auditable India-market research copilot.

## Shared conclusions from both passes

There is strong agreement on the following:

- Directly prompting or fine-tuning a general LLM on price strings is a poor primary forecasting approach. Its text objective, numeric representation and uncertainty output do not match the trading problem.
- The daily small model should perform triage, entity resolution and structured extraction—not self-modify or issue trades.
- RAG must enforce an `as_of` boundary during backtests and live decisions. Generic “latest document” retrieval causes look-ahead leakage.
- Numeric forecasting should start with regularised linear models and LightGBM/XGBoost-style tabular models. Time-series foundation models are challengers, not assumed winners.
- Full Indian transaction costs, historical constituents, corporate actions, liquidity and realistic fills must be present before performance is judged.
- Execution must remain isolated from model prose and tool calls, with human approval, reconciliation, a kill switch and a no-trade outcome.
- Cash equities and end-of-day research are the sensible first scope; intraday and derivatives multiply both noise and operational risk.

That consensus is the architecture I would recommend.

## Where I would be more cautious than the other pass

Several attractive claims should not be promoted into requirements without evidence:

- Delivery percentage, FII/DII flows, GIFT Nifty, crude, DXY and overseas markets are plausible features—not proven durable predictors. Measure incremental out-of-sample value after release-time alignment and costs.
- A historical-analogue RAG sample such as 14 similar events is too small to support a confident “win rate” without uncertainty intervals, shrinkage and multiple-testing controls.
- Generic FinBERT sentiment is a baseline, not an independent truth-check. Both an LLM and FinBERT can share the same conceptual error. Human-labelled India-specific evaluation is the reference.
- Do not assume that most filings may be scraped, archived or used to train models merely because they are public. Source licences must explicitly cover retention, systematic research, derived features and model training.
- Do not automate broker login or TOTP unless the broker explicitly permits that flow. Authentication convenience cannot override broker terms or security controls.
- A Kite GTT is a broker-side trigger that submits a limit order when triggered; it is not guaranteed exchange protection and may not fill through a gap. It must be reconciled.
- An order ID confirms broker/OMS acceptance, not execution. Holdings, positions, orders and trades must be reconciled from broker state.
- Exact tax rates, exchange charges, API fees, market hours, order types and SEBI/broker rules are mutable configuration. They must come from dated authoritative sources and be revalidated before live use.
- A cloud provider, vector database, orchestrator or named open model should not be hard-coded into the product requirement. Choose them through measured workload and compliance needs.

These corrections do not weaken the concept; they prevent an implementation guess from becoming a false safety assumption.

## Correct model decomposition

| Function | Recommended starting method | What may update |
| --- | --- | --- |
| Document triage and fact extraction | Schema-constrained open-weight instruct model plus deterministic parsers | Prompts/schema first; adapter fine-tuning only after labelled errors accumulate |
| Event classification | Small classifier or LLM with abstention | Reviewed India-specific events |
| Evidence retrieval | Entity filters + BM25 + embeddings + reranking | Daily append-only index, not model weights |
| Historical analogues | Deterministic event filters and numeric joins | Event ledger and realised outcomes |
| Return/rank forecast | Linear/logistic baseline, LightGBM/XGBoost | Scheduled rolling training set |
| Volatility and tail risk | EWMA/GARCH, quantile regression or boosting | Scheduled rolling training set |
| Signal combination | Calibrated regression using out-of-fold base predictions | Controlled offline retraining |
| Portfolio and risk | Deterministic constraints/optimisation | Versioned policy configuration |
| Execution | Broker adapter and state machine | No learned policy in V1 |

A time-series foundation model can be tested, but only as one challenger. With roughly 100 instruments and daily data, the effective independent sample is much smaller than the raw stock-day count because stocks and adjacent days are correlated.

## What “daily research feeding RAG” should mean

Daily ingestion and model training are different operations.

The daily worker should:

1. ingest documents and preserve the original bytes;
2. deduplicate versions and record corrections;
3. resolve company names, symbols and stable instrument identifiers;
4. classify source and event type;
5. extract facts, numeric values and exact evidence spans;
6. attach publication, ingestion and eligibility timestamps;
7. assign confidence and abstain on ambiguity;
8. quarantine failed validations;
9. append accepted records to the point-in-time store and retrieval indexes.

It should not update production weights every day. Keep a champion model frozen for a controlled interval. Train a challenger offline only after labels mature, compare it on untouched data and promote it through a recorded approval with rollback available.

A suitable event record is:

```json
{
  "instrument_id": "NSE:INFY",
  "event_type": "guidance_revision",
  "direction": "negative",
  "surprise_value": -0.03,
  "surprise_unit": "revenue_guidance_midpoint_pct",
  "novelty": 0.92,
  "confidence": 0.88,
  "event_time": "...",
  "published_at": "...",
  "ingested_at": "...",
  "effective_from": "...",
  "source_tier": "exchange_filing",
  "source_uri": "...",
  "source_hash": "...",
  "evidence": [{"page": 4, "text": "..."}],
  "extractor_version": "...",
  "review_status": "machine_extracted"
}
```

The system should retain the machine result, human corrections and lineage. Fine-tuning is justified only when a reviewed error set shows repeatable failures that prompting, parsing and retrieval cannot fix.

## Point-in-time RAG design

Use two logically separate views:

- **As-of evidence index:** reconstructs only documents eligible by the historical decision cutoff.
- **Current research index:** exposes the latest corrected corpus for present-day research.

Every backtest retrieval must have an enforced `as_of` filter. Each record needs at least `event_time`, `published_at`, `ingested_at` and `effective_from`. Period-end dates must never substitute for publication dates.

Retrieval should combine:

- stable instrument/entity filters;
- event taxonomy and source tier;
- keyword/BM25 matching for exact numbers and terms;
- embeddings for semantic candidates;
- reranking;
- an evidence-span requirement.

Historical analogues are useful only if their realised outcomes are joined in deterministic code. For example, retrieve prior guidance cuts with similar magnitude, sector and regime, then compute their 1/5/20-session residual returns, dispersion and adverse excursion from the market database. The LLM may explain the set but should not calculate or invent its statistics.

Analogue outputs must include sample size, uncertainty, selection logic and sensitivity to reasonable neighbour definitions. “Similar” is itself a model choice and must be walk-forward validated.

## Data Gate 0: the real first milestone

Before choosing an LLM, prove that historical days can be reconstructed as they were known at the time.

Start with about 20 liquid stocks across sectors. Prefer a long EOD history—ideally spanning multiple regimes—but judge sufficiency from the target horizon and effective sample size rather than a magical year count.

Required data includes:

- adjusted and unadjusted NSE OHLCV;
- corporate actions, symbol/ISIN history and delistings;
- point-in-time index membership and sector classification;
- exchange announcements and financial results with original publication timestamps;
- RBI/MoSPI releases with vintages where revisions occur;
- INR, yields, commodities, breadth and institutional-flow data with exact availability times;
- relevant overseas-market features aligned to IST;
- licensed news archives if news is included;
- actual broker fills and contract-note charges for later calibration.

For every source, record owner, licence, allowed uses, retention/training rights, freshness target, publication convention, correction policy and backfill process.

Gate 0 passes only when:

- a historical decision snapshot is reproducible from immutable inputs;
- at least 30 sampled dates have been manually checked for future leakage and corporate-action errors;
- historical constituents and identifiers are available;
- source rights are documented;
- the intended label and real entry process use the same information cutoff.

If Gate 0 fails, do not compensate with a more capable model.

## Forecast targets and baselines

Do not predict an exact future price. Test targets that correspond to an executable decision:

- cross-sectional rank of next-session or next-five-session residual return;
- probability that return exceeds total cost plus a risk margin;
- conditional return quantiles;
- realised volatility and downside-tail estimates;
- overnight gap or stop-hit probability.

First establish:

- no-skill/base-rate predictions;
- Nifty buy-and-hold and cash;
- simple momentum and short-term reversal rules;
- regularised linear/logistic models;
- LightGBM/XGBoost cross-sectional rankers;
- simple ensembles of independently useful signals.

Neutralise or explicitly model market and sector exposure. Otherwise the system may appear to select stocks while merely forecasting the Nifty.

Only after numeric baselines are frozen should text/event features be added one family at a time. The key question is not whether the extractor is accurate in isolation; it is whether a feature adds stable out-of-sample value or measurably saves analyst time.

## Evaluation that resists self-deception

Use walk-forward validation with purging and embargo where labels overlap. Also require:

- a registry of every attempted feature, prompt, label, horizon and hyperparameter;
- out-of-fold predictions for any meta-model;
- a final untouched period used once;
- block/bootstrap confidence intervals suitable for serial dependence;
- calibration curves and Brier score for probabilities;
- rank IC, turnover, drawdown and sector/regime stability;
- Deflated Sharpe Ratio or another explicit multiple-testing correction;
- stress tests for higher costs, delayed data and worse fills;
- a shadow portfolio recording accepted and rejected proposals.

Backtests must simulate the actual cutoff and next-session entry, corporate actions, constituent changes, price bands, stale inputs, unfilled and partial orders, gap-through-stop behaviour, all statutory/broker charges and conservative slippage.

Thresholds such as Sharpe 1.0, IC 0.03 or 15% drawdown can be operating gates, but they are not proof by themselves. Results also need adequate breadth, parameter stability, uncertainty bounds and evidence that a few dates or stocks did not create the apparent edge.

## Daily live operating loop

1. Ingest sources idempotently; quarantine schema changes and duplicates.
2. Reconcile end-of-day prices and corporate actions.
3. Run extraction and validate source timestamps/evidence.
4. Freeze and hash the decision snapshot.
5. Materialise features from eligible records only.
6. Run calibrated forecasts and the cost/no-trade hurdle.
7. Apply deterministic cash, sector, correlation, liquidity, turnover and risk limits.
8. Generate a cited research brief from the frozen snapshot.
9. Have the user approve exact instruments, size/price bands, exits and expiry.
10. Before the open, permit new information only to cancel or reduce an approved trade in V1.
11. Execute through a narrow state machine, consume order updates and reconcile broker state.
12. Append matured outcomes; retrain only through the offline champion/challenger process.

Research and execution should use separate deployables, credentials and network permissions. The execution service should accept only a versioned proposal plus an unexpired signed approval—not prose, prompts or arbitrary model tool calls.

## Practical open-model strategy

Benchmark several currently supportable open-weight models rather than selecting one from reputation. Evaluate:

- commercial-use licence and redistribution constraints;
- structured-output validity;
- numeric extraction exact match;
- evidence fidelity;
- ticker/entity resolution;
- English and required Indian-language/code-mixed performance;
- abstention quality;
- latency, memory and total operating cost;
- reproducible pinning of weights, tokenizer and runtime.

A quantised 7–14B model may be sufficient for routine filings on a workstation or rented batch GPU. A cheaper classifier or deterministic parser may handle high-volume boilerplate. Complex documents can be escalated to a stronger model if allowed by the data policy, but escalation must be driven by measured errors or low confidence—not a guessed “98% local coverage.”

Training a foundation model from scratch is unnecessary. Start with constrained prompting and retrieval; use LoRA/QLoRA only after hundreds or thousands of reviewed examples identify stable, economically relevant error modes.

## Phased recommendation

### Phase 0 — data, rights and replayability

Build the 20-stock point-in-time pilot, source-rights registry and historical replay. Confirm current broker/API/static-IP/tagging/DDPI requirements in writing.

**Exit:** no known leakage in audited snapshots; data rights and identifiers are documented.

### Phase 1 — numeric baseline

Build simple price/volume, risk and macro features; implement realistic costs/fills; run purged walk-forward tests.

**Exit:** at least one simple signal shows stable incremental value after costs. If not, stop trading development and keep the research product.

### Phase 2 — event ledger and research copilot

Define an India-specific event taxonomy, benchmark extraction on reviewed filings, implement evidence-cited as-of retrieval and produce a daily brief.

**Exit:** the layer either adds demonstrable forecast value or enough research-time savings to justify itself. Only the first qualifies it as a trading feature.

### Phase 3 — shadow operation

Freeze models and run for at least 20 trading sessions with no automated orders. Exercise stale-data, duplicate-event, model-failure and kill-switch scenarios.

### Phase 4 — broker-realistic paper operation

Run at least 60 trading sessions. Test authentication expiry, restarts, rejects, partial fills, GTT reconciliation and ledger recovery.

### Phase 5 — tiny live capital

Start only after current compliance and broker behaviour are confirmed. Use capital small enough that an operational error is tolerable, track realised slippage and charges, and retain human approval for new exposure.

## Decisions needed before implementation

1. Is the product strictly personal research/trading, or might it distribute signals later?
2. What executable label is intended: close-to-open, next open-to-close, close-to-close, or multi-day residual return?
3. What legally usable historical filings, fundamentals, news and constituent data can be obtained, and at what cost?
4. What is the starting capital and therefore the real cost/capacity hurdle?
5. Which instruments are in V1, and is the scope long-only/long-cash?
6. Is DDPI active, and has the exact exit path been tested with the broker?
7. For each failure, is the safe action abstain, cancel entry, reduce, or alert?
8. What evidence will stop the project rather than trigger more tuning?

## Final recommendation

Approve the concept as a staged research platform, not as an “LLM predicts Indian stocks” project.

The immediate build should be:

- a 20-stock, point-in-time data pilot;
- a source-rights and timestamp audit;
- a simple post-cost numeric baseline;
- a small evidence-linked filing extractor;
- an as-of RAG prototype used for cited research and carefully validated historical analogues.

Do not buy significant GPU capacity, fine-tune a model, or connect live execution until those gates pass. The small daily model is valuable as a disciplined research worker. The trading decision remains a calibrated statistical forecast filtered by deterministic cost, risk, compliance and human-approval rules.

## Primary references retained from the independent pass

- [SEBI: Safer participation of retail investors in algorithmic trading, 4 Feb 2025](https://www.sebi.gov.in/legal/circulars/feb-2025/safer-participation-of-retail-investors-in-algorithmic-trading_91614.html)
- [SEBI implementation glide path](https://www.sebi.gov.in/sebi_data/attachdocs/sep-2025/1759232056254.pdf)
- [NSE FAQ on retail algorithmic trading](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/FAQ_Retail%20Algo_03112025_NSE.pdf)
- [Official NSE AI/MCP data page and use disclaimer](https://www.nseindia.com/nse-mcp)
- [NSE Indices data subscriptions](https://www.niftyindices.com/offerings/data-subscription)
- [RBI Database on Indian Economy](https://statistics.rbi.org.in/)
- [Kite Connect documentation](https://www.kite.trade/docs/connect/v3/)
- [Kite order semantics](https://kite.trade/docs/connect/v3/orders/)
- [Kite GTT semantics](https://kite.trade/docs/connect/v3/gtt/)
- [Zerodha charges](https://zerodha.com/charges)
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
