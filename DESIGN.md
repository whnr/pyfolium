# Pyfolium Design Guide

*This document describes the architectural style, modeling philosophy, and design decisions behind pyfolium. It complements the [README](README.md) (which covers usage) and the internal [review findings](.claude/review-findings.md) (which tracks implementation work). It may be superseded by full documentation in the future.*

## Core Philosophy

Pyfolium is a **backtesting engine**, not an analytics platform. It simulates portfolio evolution through time with tax and fee awareness, then gets out of the way. Analysis, visualization, and optimization are the user's choice — pyfolium produces clean pandas DataFrames that plug into any downstream tooling.

This means pyfolium deliberately does **not** include:

- Performance analytics (Sharpe, drawdown, etc.)
- Visualization or plotting
- Data fetching or market data APIs
- Portfolio optimization
- Risk models

These are all better served by mature, dedicated libraries. Pyfolium's job is to answer one question accurately: *"Given this strategy, these assets, these tax rules, and these fees — what would have happened?"*

## The Asset-First Model

Everything that has a price over time is an **Asset**. This is the fundamental modeling primitive.

An Asset is nothing more than a time series of prices (and optionally income) at a fixed frequency, identified by a symbol and living inside an AssetUniverse. This deliberate simplicity means that many financial concepts that other libraries treat as special cases are just assets in pyfolium:

- **Stocks, ETFs, bonds** — the obvious case. Price series with optional dividend income.
- **Risk-free rate** — model it as an asset whose price grows at the risk-free rate. A strategy that "parks cash in T-bills" simply buys this asset. No special API needed.
- **Cash equivalents, money market funds** — same treatment. An asset with very low volatility and small income.
- **Currencies** — an asset with a price expressed in the portfolio's base currency.
- **Commodities, crypto** — price series, no income column.

This keeps the core engine simple: the Portfolio only knows about cash and assets. There is no parallel system for "benchmarks" or "risk-free instruments" — those are just assets that a strategy may or may not choose to hold.

### Why model the risk-free rate as an asset?

Many backtesting frameworks have a special `risk_free_rate` parameter baked into the engine. This creates problems:

1. **Rigidity** — the risk-free rate is hard-coded as a scalar or simple curve, when in reality it's a full time series with its own dynamics.
2. **Inconsistency** — the risk-free "return" doesn't flow through the same tax/fee machinery as everything else. In reality, T-bill income is taxable.
3. **Scope creep** — once you have a risk-free rate parameter, you're one step from building Sharpe ratios and risk models into the engine itself.

By modeling it as an asset, the risk-free rate gets the same treatment as everything else: it has a price history, it can generate income, transactions in it incur fees, and gains are taxed. A strategy that allocates to "risk-free" simply buys that asset. Analytics libraries downstream can compute Sharpe ratios using whatever risk-free series they prefer.

## Time Model: Discrete Periods

Time advances in **discrete periods** (daily, monthly, etc.), not continuously. Each period is a pandas `Period` object at a fixed frequency shared across all assets in the universe.

Within each period, operations follow a strict sequence enforced by a state machine:

```
COLLECT_INCOME → TRANSACT → DONE → advance_period() → COLLECT_INCOME
```

This ordering exists because it mirrors how real portfolios work:

1. **Income first** — dividends and coupons arrive before trading opens.
2. **Transact** — buy, sell, move cash. Multiple transactions allowed per period.
3. **Record** — snapshot the portfolio state into history.
4. **Advance** — move to the next period.

The state machine prevents impossible operations (e.g., buying before income is collected, or recording history mid-trade). It's strict by design: silent mis-ordering would produce subtly wrong backtests that are hard to debug.

### Frequency consistency

All assets in an AssetUniverse must share the same frequency. This is an intentional constraint — mixing daily and monthly data in the same backtest introduces alignment ambiguity. If you need monthly rebalancing with daily price data, use daily frequency and have your strategy act only on month boundaries.

## Portfolio: Cash + Holdings + History

The Portfolio is the central object. It tracks:

- **Cash** — a single scalar. All cash is fungible.
- **Holdings** — a DataFrame of position quantities indexed by period and asset symbol.
- **Transactions** — a complete log of every buy, sell, and cash movement.
- **History** — a per-period snapshot of the portfolio state (cash, holdings value, tax owed).
- **Tax lots** — per-share cost basis tracking for capital gains calculations.

### Why a single cash balance?

Some frameworks model multiple cash accounts or currencies. Pyfolium keeps a single cash balance in one implicit base currency. Multi-currency support comes naturally through the asset model: hold a "EUR/USD" asset to represent euro exposure.

### Cash is a transaction, not a precondition

The Portfolio always starts with zero cash. Initial capital enters through `move_cash()` — the same API used for mid-backtest deposits and withdrawals. This is deliberate:

1. **Every cash flow is a transaction.** Deposits, withdrawals, dividends, and trade settlements all appear in the transaction log with a period, a type, and an amount. Initial capital is no exception — it's a deposit that happens on day one.

2. **The transaction log is the complete record.** If initial cash were a constructor parameter, it would be invisible in the transaction history. A user reviewing the log would see trades consuming cash that appeared from nowhere. By requiring an explicit `move_cash()`, the source of every dollar is traceable.

3. **Timing matters.** A backtest that starts with $100k on January 1st is different from one where $50k arrives January 1st and $50k arrives July 1st. Both are expressed naturally with `move_cash()` at the appropriate period.

This does create first-period ceremony that every user must write:

```python
portfolio = Portfolio(universe)
portfolio.collect_income()   # transitions state (no holdings yet, so no-op)
portfolio.move_cash(50000)   # the actual deposit
portfolio.update_history()   # record period 1
portfolio.advance_period()   # ready for period 2
```

This is acknowledged as an ergonomic rough edge. The `collect_income()` call is especially gratuitous — there are no holdings, so there is no income to collect. It exists purely to satisfy the state machine. See the review findings for planned improvements to reduce this boilerplate without breaking the "cash is a transaction" invariant.

### Immutability boundaries

The AssetUniverse (prices, income) is **shared** across portfolio clones. Price data doesn't change during a backtest — it represents the historical record. Portfolio state (cash, holdings, transactions) is **owned** and deep-copied on `clone()`. This makes strategy comparison efficient: cloning a portfolio doesn't duplicate the (potentially large) price matrix.

## Tax and Fee Awareness

Taxes and fees are **first-class citizens**, not post-hoc adjustments. They flow through every transaction:

- **Fees** are deducted at trade time and incorporated into cost basis.
- **Capital gains taxes** are computed per tax lot using FIFO or LIFO accounting, with short-term vs long-term classification based on holding period.
- **Income taxes** (on dividends) can be withheld at collection time.

This matters because taxes and fees dramatically affect real portfolio performance. A strategy that looks profitable before taxes may be destructive after them. By embedding tax/fee logic in the engine, every strategy automatically gets realistic cost modeling.

### Configs as templates, not final implementations

`TaxConfig` and `FeeConfig` are **reasonable defaults and starting templates**, not exhaustive models of every tax jurisdiction or brokerage fee schedule. Real-world tax systems are staggeringly diverse — US federal vs state rules, wash sale restrictions, international withholding treaties, German *Abgeltungssteuer*, etc. No single config class can capture all of this without becoming an unmaintainable monolith.

The design intent is:

1. **The shipped configs cover the common case** — short-term vs long-term capital gains with FIFO/LIFO, flat-rate income tax withholding, fixed + percentage fees with caps. This handles a large class of backtests accurately enough.

2. **Users should be able to swap in their own implementations** — a user modeling US wash sale rules, German *Verlustverrechnungstöpfe* (loss offset pools), or a brokerage with tiered commission schedules should be able to provide their own tax or fee class that the Portfolio accepts without modification.

3. **The interface is the contract, not the implementation** — Portfolio should depend on *what* a tax/fee config provides (rates, lot ordering, fee calculation), not on *which specific class* provides it. This means:
   - `FeeConfig.calculate_fee(transaction_value) → float` is the fee interface.
   - Tax config needs a similar pattern: the tax calculation logic that currently lives in Portfolio's sell and income paths should be delegable to the config.

**Current state:** FeeConfig is partially there — it owns `calculate_fee()`. TaxConfig is purely declarative (rates and strategy name), with the actual gain classification, lot selection, and withholding logic hardcoded in Portfolio. This coupling needs to loosen so that a `WashSaleTaxConfig` or `GermanTaxConfig` can override the tax calculation without forking Portfolio.

**Direction:** Extract tax calculation methods into TaxConfig (or a companion TaxCalculator), so that:
- The default TaxConfig keeps today's simple behavior
- Subclasses can override lot selection (specific lot ID), gain classification (wash sale adjustments), or withholding logic (jurisdiction-specific rules)
- Portfolio calls the config's methods rather than implementing tax math directly

This is tracked in the review findings under the implementation roadmap.

### Tax lot tracking

Each purchase creates a tax lot with a per-share cost basis. When selling, lots are consumed in FIFO or LIFO order. This enables:

- Accurate capital gains calculation for any holding period
- Short-term vs long-term gain classification
- Future: specific lot identification for tax-loss harvesting (see roadmap in review findings)

## Data Integrity: Gaps and Guards

The backtesting engine must never silently operate on missing data. A NaN price flowing into a buy or sell produces NaN cash flows, NaN cost basis, and a corrupted backtest — all without raising an error.

### What the engine validates today

- **PeriodIndex required** — Asset rejects data without a PeriodIndex.
- **Monotonic and unique index** — Asset rejects duplicate or out-of-order periods.
- **Frequency match** — Asset frequency must match its AssetUniverse.
- **Non-empty data** — AssetUniverse rejects empty assets.

### What it does not yet validate

- **NaN prices within an asset's own date range** — an asset with `[100, NaN, 102]` passes all current checks. A trade on the NaN period silently produces garbage.
- **NaN in the price/income matrices after universe alignment** — when assets have different date ranges, `reindex()` fills the non-overlapping regions with NaN. This is expected (you can't trade an asset before it exists), but there is no guard at trade time to prevent buying into a NaN price.
- **Income column NaN** — similar issue for dividend collection on a NaN income value.

### Design direction

Data gap handling should follow the principle of **fail early, fail loud**:

1. **At Asset construction** — reject price series that contain NaN within their date range. If the user's source data has gaps, they must fill or interpolate before passing it to pyfolium. This is a data preparation concern, not a backtesting engine concern.

2. **At trade time** — guard `buy_asset()` and `sell_asset()` against NaN prices. Raise a clear error: *"Cannot trade {symbol} at period {period}: price is NaN"*. This catches the universe-alignment case where a strategy tries to trade an asset outside its data range.

3. **At income collection** — same guard for `collect_income()` on NaN income values.

The goal is zero silent NaN propagation. If data is missing, the user should know immediately — not discover it when their backtest results look wrong.

## Strategy Framework

Strategies are subclasses of `BaseStrategy` with one required method: `get_trades()`, which returns a list of `(symbol, quantity)` tuples.

The design is deliberately minimal:

- **No market data API** — the strategy accesses `self.portfolio` and its `asset_universe` directly. You have all the data; decide what to do with it.
- **No order types** — trades execute at the current period's price. Limit orders, stop losses, and slippage models are out of scope (they belong in a more complex execution simulation).
- **No position sizing helpers** — compute your own quantities. This avoids baking in assumptions about how sizing should work.

Strategies store their parameters in a `parameters` dict for reproducibility, and track all trade attempts (successful and failed) in `trades_df`.

## BacktestRunner: Orchestration

The BacktestRunner automates the period loop and provides extension points via hooks (`period_start`, `period_end`, `backtest_start`, `backtest_end`, `error`). It owns the simulation lifecycle but delegates all decisions to the strategy.

The runner supports step-by-step execution via `run_period()` for debugging and interactive use.

## Data Flow Summary

```
                  ┌─────────────────┐
                  │  Raw Price Data  │
                  │  (CSV, DataFrame)│
                  └────────┬────────┘
                           │
                    load_from_csv()
                    load_from_dataframe()
                           │
                  ┌────────▼────────┐
                  │      Asset      │  price + income time series
                  └────────┬────────┘
                           │ registers with
                  ┌────────▼────────┐
                  │  AssetUniverse  │  aligned price_matrix + income_matrix
                  └────────┬────────┘
                           │ referenced by
                  ┌────────▼────────┐
                  │    Portfolio    │  cash, holdings, transactions, history
                  └────────┬────────┘
                           │ owned by
              ┌────────────┼────────────┐
              │                         │
     ┌────────▼────────┐      ┌────────▼────────┐
     │  BaseStrategy   │      │ BacktestRunner  │
     │  (get_trades)   │      │ (period loop)   │
     └────────┬────────┘      └────────┬────────┘
              │                         │
              └──────────┬──────────────┘
                         │
                ┌────────▼────────┐
                │ BacktestResult  │  portfolio + strategy + metadata
                └────────┬────────┘
                         │
              ┌──────────▼──────────┐
              │  pandas DataFrames  │  → your analytics library of choice
              └─────────────────────┘
```

## What Pyfolium Is Not

To keep the scope clear, here are explicit non-goals:

- **Not a data provider** — bring your own price data.
- **Not an analytics suite** — use quantstats, empyrical, pyfolio, or pandas for analysis.
- **Not a live trading system** — this is historical simulation only.
- **Not an optimizer** — use scipy, cvxpy, or similar for portfolio optimization.
- **Not a risk engine** — compute VaR, CVaR, and factor exposures downstream.

Pyfolium produces the raw material (portfolio history as DataFrames) that these tools consume.

## Conventions

- **Google-style docstrings** for all public APIs.
- **Type hints** on public methods; pandas-stubs for DataFrame typing.
- **Ruff** for formatting and linting (replaces black, isort, flake8).
- **88-character line length** (black default).
- **Pydantic** for configuration validation (TaxConfig, FeeConfig).
- **PeriodIndex** throughout — not DatetimeIndex. Periods are the natural unit for discrete-time simulation.
