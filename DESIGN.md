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

This ordering is an **accounting convention**, not a model of how markets actually work. Real dividends involve three separate dates (ex-dividend, record, payment) that are weeks apart and don't align to any period boundary. Real markets are continuous — you can buy a stock, receive a bond coupon, and sell something else in any order within the same day.

The state machine exists to **prevent accounting ambiguity in discrete simulation**:

1. **Collect income** — settle all income for the period before any trades execute. This avoids the question: *"Should a dividend earned this period be available to spend this period?"* The convention says yes — income is collected first, then available for trading.
2. **Transact** — buy, sell, move cash. Multiple transactions allowed per period.
3. **Record** — snapshot the portfolio state into history.
4. **Advance** — move to the next period.

The strictness is deliberate. Silent mis-ordering would produce subtly wrong backtests — for instance, recording history before a trade would capture stale state, or trading before income collection could produce different results depending on execution order. The state machine makes the convention explicit and enforced rather than implicit and fragile.

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

1. **Every cash flow is a transaction.** Deposits, withdrawals, dividends, and trade settlements all appear in the transaction log with a period, a type, and an amount. Initial capital is no exception — it's a deposit that happens at the start of the strategy's investment period.

2. **The transaction log is the complete record.** If initial cash were a constructor parameter, it would be invisible in the transaction history. A user reviewing the log would see trades consuming cash that appeared from nowhere. By requiring an explicit deposit, the source of every dollar is traceable.

3. **Timing matters.** A backtest that starts with $100k on January 1st is different from one where $50k arrives January 1st and $50k arrives July 1st. Both are expressed naturally with `move_cash()` at the appropriate period.

### Strategy owns its start conditions

The execution logic — including when to start investing and how much initial capital to deploy — belongs to the **strategy**, not to manual user ceremony. A strategy declares its `initial_cash` and optionally its `start_period`. The BacktestRunner reads these, fast-forwards to the right period, deposits the cash as the first transaction, and begins the simulation loop.

```python
portfolio = Portfolio(universe)
strategy = BuyAndHold(portfolio, initial_cash=50000)
result = BacktestRunner(portfolio, strategy).run()
```

This solves three problems at once:

- **No boilerplate.** The four-line ceremony (`collect_income` → `move_cash` → `update_history` → `advance_period`) disappears. The runner handles state-machine traversal.
- **Warmup data.** A strategy that needs 200 days of moving-average data sets `start_period` to day 201. The runner fast-forwards there without processing empty periods.
- **Cash stays a transaction.** The deposit still appears in the transaction log at the correct period. The invariant is preserved — the runner just automates the mechanics.

The `clone()` workflow also simplifies — clone a portfolio, create different strategies with the same `initial_cash`, and compare:

```python
portfolio = Portfolio(universe)
s1 = AggressiveStrategy(portfolio.clone(), initial_cash=100000)
s2 = ConservativeStrategy(portfolio.clone(), initial_cash=100000)
result1 = BacktestRunner(s1.portfolio, s1).run()
result2 = BacktestRunner(s2.portfolio, s2).run()
```

See the review findings for implementation details.

### Immutability boundaries

The AssetUniverse (prices, income) is **shared** across portfolio clones. Price data doesn't change during a backtest — it represents the historical record. Portfolio state (cash, holdings, transactions) is **owned** and deep-copied on `clone()`. This makes strategy comparison efficient: cloning a portfolio doesn't duplicate the (potentially large) price matrix.

### Cloning preserves time position

`clone()` copies the portfolio's current period, state machine position, and complete history. A clone made at period 50 starts at period 50 with all transactions and holdings intact. This enables mid-backtest branching: run a common strategy for 100 periods, clone, then diverge with different strategies from that checkpoint. Each clone is fully independent — trades in one don't affect the other.

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

## Data Integrity: Gaps and Graceful Failure

Price data has gaps. There are no prices on weekends. Assets start and end on different dates. Quarterly data expanded to daily frequency has NaN on most days. **This is normal, not an error.**

Pyfolium handles data gaps at two levels with different philosophies:

### At construction: clean data in

Asset validates that the data the user *actually provides* is clean:

- **PeriodIndex required** — rejects data without a PeriodIndex.
- **Monotonic and unique index** — rejects duplicate or out-of-order periods.
- **Frequency match** — frequency must match the AssetUniverse.
- **No NaN in price column** — rejects price series containing NaN. If the user provides 252 daily prices, all 252 must be real numbers. This catches data corruption at the source — a CSV with missing rows, a bad API response, a merge gone wrong.

This is a data quality gate. Pyfolium trusts the data it's given, so the data must be trustworthy. If your source data has gaps (weekends, holidays), clean or filter it *before* constructing the Asset. Quarterly dividends on a daily-frequency asset? Provide only the days that have prices. The AssetUniverse handles alignment.

### At trade time: graceful failure

When the AssetUniverse aligns assets with different date ranges via `reindex()`, it fills non-overlapping regions with NaN. This is expected — you can't trade an asset before it exists or after it delists.

If a strategy attempts a trade at a period where the price is NaN, the trade **fails gracefully** rather than crashing the backtest:

- `buy_asset()` / `sell_asset()` look up the price via `universe.price_matrix.loc[period, symbol]`. For out-of-range periods this returns NaN.
- The NaN guard raises `ValueError`, which `execute_trades()` catches and records as `success=False` in `trades_df`.
- The strategy continues executing. It can handle the failure by:
  1. Checking data availability *before* placing a trade (e.g., `pd.isna(universe.price_matrix.loc[period, symbol])`).
  2. Inspecting `trades_df` for failed trades after the period.

This means a strategy that blindly trades every period won't crash — it will accumulate `success=False` entries that the user can inspect. A strategy that checks prices first will never encounter the failure at all.

Note: the Asset class is a validated data container that feeds the universe at construction time. At runtime, all price and income queries go through `universe.price_matrix` and `universe.income_matrix` — not through individual Asset methods. This ensures a single, consistent data access path with predictable NaN behavior for out-of-range periods.

### Asset lifetime and forward-fill semantics

`price_matrix_ffill` fills NaN values forward to handle intra-life gaps (e.g. a missing price on a market holiday). It does **not** fill past each asset's `end_time` — the last date in its data.

Two kinds of NaN appear in the raw price matrix with different semantics:

- **Intra-life gap** — a period between `start_time` and `end_time` where no price was recorded (e.g. a market holiday). The ffill matrix fills these with the most recent prior price. Strategies should treat this price as valid.
- **Post-termination** — a period after `end_time`. These remain NaN in the ffill matrix. The asset simply does not exist there.

This distinction matters regardless of asset type. A matured bond, a delisted stock, and a fund with data through last year all have the same model: the data you provided defines the asset's lifetime. Filling past the last data point would fabricate prices that are not in the historical record.

**Strategy responsibility:** it is the strategy's job not to hold an asset past its `end_time`. If a strategy holds asset B through period 100 but B's data ends at period 80, then from period 81 onward:
- `PriceMode.STRICT` — `get_total_value()` returns NaN (B's price is NaN in the raw matrix).
- `PriceMode.LAST_VALID` — `get_total_value()` also returns NaN (B's price is NaN in the ffill matrix, since post-termination periods are not filled).

A strategy can detect this in advance by checking `universe.assets[symbol].end_time` before the period arrives and exiting the position in time.

### Income gaps

NaN income values (from universe alignment) are treated as zero income for that period. There is nothing to collect where there is no data — this is not an error condition.

## Strategy Framework

Strategies are subclasses of `BaseStrategy` with one required method: `get_trades()`, which returns a list of `(symbol, quantity)` tuples.

The design is deliberately minimal:

- **No market data API** — the strategy accesses prices and income via `self.asset_universe.price_matrix` and `self.asset_universe.income_matrix`. These are aligned DataFrames indexed by period and symbol. You have all the data; decide what to do with it.
- **No order types** — trades execute at the current period's price. Limit orders, stop losses, and slippage models are out of scope (they belong in a more complex execution simulation).
- **No position sizing helpers** — compute your own quantities. This avoids baking in assumptions about how sizing should work.

Strategies store their parameters in a `parameters` dict for reproducibility, and track all trade attempts (successful and failed) in `trades_df`.

## BacktestRunner: Orchestration

The BacktestRunner automates the period loop and provides extension points via hooks (`period_start`, `period_end`, `backtest_start`, `backtest_end`, `error`). It owns the simulation lifecycle but delegates all decisions to the strategy.

The runner supports step-by-step execution via `run_period()` for debugging and interactive use.

## Observability: Scoped Logs, Not stdlib Logging

Backtest observability uses **scoped, structured logs** rather than Python's stdlib `logging` module. Every `BacktestRunner` maintains its own `_log: list[LogEntry]`, and each `LogEntry` is a frozen dataclass with severity, timestamp, period, source, message, and optional data payload.

### Why not stdlib logging?

stdlib `logging` is designed for long-running processes where log output goes to files, consoles, or monitoring systems. Backtests are different:

1. **Isolation** — running 400 backtests in parallel would produce interleaved log output from a global logger. Scoped logs keep each backtest's events in its own list, queryable after completion.
2. **Structured data** — `LogEntry` carries typed fields (severity as `IntEnum`, period as `pd.Period`, source as string). stdlib log records require string formatting and parsing to recover structure.
3. **Post-hoc analysis** — `result.log_df` gives a DataFrame of all events, filterable by severity, source, or period. This is the natural interface for a library that outputs DataFrames.

### The drain pattern

Strategies emit log entries via `self.log(severity, message, data)`, which appends to `strategy._log`. After each `strategy.step()` call, the runner drains the strategy's log:

```python
self._log.extend(self.strategy._log)
self.strategy._log.clear()
```

This keeps strategies decoupled from the runner — they don't need a reference to the runner's log, and they're testable in isolation. The `source` field on each entry (`"runner"`, `"strategy"`, `"hook"`) lets consumers filter by origin.

### OutputMode

`OutputMode` controls terminal output during `run()`:

- **SILENT** — no terminal output; log captured in result only.
- **SUMMARY** — one-line summary at end (periods, time, error/warning counts).
- **PROGRESS** — tqdm progress bar during execution plus summary.

This replaces the old `progress=True` boolean with a richer, extensible enum.

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

## Code Conventions

- **Google-style docstrings** for all public APIs.
- **Type hints** on public methods; pandas-stubs for DataFrame typing.
- **Ruff** for formatting and linting (replaces black, isort, flake8).
- **88-character line length.**
- **Pydantic** for configuration validation (TaxConfig, FeeConfig).
- **PeriodIndex** throughout — not DatetimeIndex. Periods are the natural unit for discrete-time simulation.
