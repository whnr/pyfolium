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

### Immutability boundaries

The AssetUniverse (prices, income) is **shared** across portfolio clones. Price data doesn't change during a backtest — it represents the historical record. Portfolio state (cash, holdings, transactions) is **owned** and deep-copied on `clone()`. This makes strategy comparison efficient: cloning a portfolio doesn't duplicate the (potentially large) price matrix.

## Tax and Fee Awareness

Taxes and fees are **first-class citizens**, not post-hoc adjustments. They flow through every transaction:

- **Fees** are deducted at trade time and incorporated into cost basis.
- **Capital gains taxes** are computed per tax lot using FIFO or LIFO accounting, with short-term vs long-term classification based on holding period.
- **Income taxes** (on dividends) can be withheld at collection time.

This matters because taxes and fees dramatically affect real portfolio performance. A strategy that looks profitable before taxes may be destructive after them. By embedding tax/fee logic in the engine, every strategy automatically gets realistic cost modeling.

### Tax lot tracking

Each purchase creates a tax lot with a per-share cost basis. When selling, lots are consumed in FIFO or LIFO order. This enables:

- Accurate capital gains calculation for any holding period
- Short-term vs long-term gain classification
- Future: specific lot identification for tax-loss harvesting (see roadmap in review findings)

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
