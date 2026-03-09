# Pyfolium

**Hätte hätte Fahrradkette** — If only, if only...

A Python backtesting library for portfolio management with support for taxes, fees, income, and custom trading strategies.

## Philosophy & Scope

Pyfolium is a **backtesting engine**, not a full-featured analytics platform.

**What it does:** Tax-aware, fee-aware portfolio backtesting with enforced transaction ordering, an extensible strategy framework, and clean pandas-based data structures.

**What it doesn't do:** Performance analytics, visualization, data fetching, optimization, risk models.

Pyfolium outputs clean pandas DataFrames (`portfolio.history`, `portfolio.transactions`) that plug into whichever libraries you prefer for those tasks.

## Installation

```bash
# Using uv (recommended)
uv sync

# Set up pre-commit hooks (runs ruff automatically on commit)
uv run setup-dev

# Or using pip
pip install -e .
pip install pre-commit
pre-commit install
```

## Quick Start

```python
import pandas as pd

from pyfolium import (
    Asset,
    AssetUniverse,
    BacktestRunner,
    BaseStrategy,
    OutputMode,
    Portfolio,
)


# 1. Create asset universe
universe = AssetUniverse(data_frequency='D')

# 2. Add assets with price data
dates = pd.period_range('2023-01-01', periods=252, freq='D')
data = pd.DataFrame({
    'price': [100 + i * 0.5 for i in range(252)],
    'income': [1.0 if i % 60 == 0 else 0.0 for i in range(252)]
}, index=dates)

Asset('Stock', universe, data)
print(f"{universe}\n")

# 3. Define strategy — initial_cash seeds the portfolio on the first period
class BuyAndHold(BaseStrategy):
    def __init__(self, portfolio, initial_cash):
        super().__init__(portfolio, initial_cash=initial_cash)
        self.invested = False

    def get_trades(self):
        if not self.invested:
            self.invested = True
            price = self.asset_universe.price_matrix.loc[
                    self.portfolio.current_period, 'Stock'
                    ]
            return [('Stock', self.initial_cash/price)]
        return []

# 4. Create portfolio and run backtest
portfolio = Portfolio(universe)
runner = BacktestRunner(portfolio, BuyAndHold(portfolio, 50000))
result = runner.run(output=OutputMode.PROGRESS)
print(f"\nFinal portfolio value: {result.portfolio.total_value:,.2f}")
print(portfolio)
```

## BacktestRunner

Automates the period-by-period simulation loop:

```python
# Simple usage
runner = BacktestRunner(portfolio, strategy)
result = runner.run()

# With progress bar
result = runner.run(output=OutputMode.PROGRESS)

# Custom hooks (callback receives the runner instance)
def log_value(runner):
    print(f"Period {runner.current_period}: {runner.portfolio.cash:,.2f}")

runner.register_hook('period_end', log_value)
result = runner.run()

# Step-by-step control
runner = BacktestRunner(portfolio, strategy)
for _ in range(10):
    runner.run_period()
    if runner.portfolio.cash < 0:
        break
```

**Available Hooks**: `period_start`, `period_end`, `backtest_start`, `backtest_end`, `error`

## Logging & Observability

`BacktestRunner` captures structured log entries during execution. Control terminal output with `OutputMode`:

```python
result = runner.run(output=OutputMode.SILENT)    # default — log in result only
result = runner.run(output=OutputMode.SUMMARY)   # one-line summary at end
result = runner.run(output=OutputMode.PROGRESS)  # tqdm bar + summary
```

After a run, inspect `result.log` (list of `LogEntry`), `result.log_df` (DataFrame view), `result.errors`, `result.warnings`, and `result.success`. Strategies can emit entries via `self.log(Severity.WARNING, "message")` inside `get_trades()`.

## Strategy Comparison

Clone portfolios to compare strategies:

```python
base = Portfolio(universe)

clone1 = base.clone()
clone2 = base.clone()
result1 = BacktestRunner(clone1, Strategy1(clone1, initial_cash=100000)).run()
result2 = BacktestRunner(clone2, Strategy2(clone2, initial_cash=100000)).run()

print(f"Strategy 1: {result1.portfolio.cash:,.2f}")
print(f"Strategy 2: {result2.portfolio.cash:,.2f}")
```

## Custom Strategies

Subclass `BaseStrategy` and implement `get_trades()`:

```python
class MomentumStrategy(BaseStrategy):
    def __init__(self, portfolio, lookback=20, **kwargs):
        super().__init__(portfolio, parameters={'lookback': lookback}, **kwargs)
        self.lookback = lookback

    def get_trades(self):
        # Return list of (symbol, quantity) tuples
        # Positive quantity = buy, negative = sell
        return [('Stock', 10), ('Aktie', -5)]

# initial_cash and start_period are keyword-only params on BaseStrategy
strategy = MomentumStrategy(portfolio, lookback=30, initial_cash=50000)

# start_period lets a strategy self-describe its warmup requirement
strategy = MomentumStrategy(portfolio, initial_cash=50000, start_period=dates[30])
```

## Tax and Fee Configuration

```python
from pyfolium import TaxConfig, FeeConfig

tax_config = TaxConfig(
    short_term_rate=0.30,
    long_term_rate=0.15,
    long_term_holding_period=pd.DateOffset(years=1),
    withhold_tax=True,
    tax_strategy='FIFO',  # or 'LIFO' or 'AVERAGE'
    allow_specific_lot=False,  # True to enable sell_lot()
)

fee_config = FeeConfig(
    fixed_fee=1.0,
    percentage_fee=0.001,  # 0.1%
    minimum_fee=1.0,
    maximum_fee=20.0
)

portfolio = Portfolio(universe, tax_config=tax_config, fee_config=fee_config)
```

Both `TaxConfig` and `FeeConfig` can be subclassed for custom rules. `FeeConfig.calculate_fee()` receives trade context — including the asset's `metadata` dict — enabling per-asset-class fees, tiered commissions, or buy/sell-asymmetric pricing:

```python
Asset(symbol="Anleihe", asset_universe=universe, data=bond_data,
      price_column="price", metadata={"asset_class": "fixed_income"})

class AssetClassFeeConfig(FeeConfig):
    def calculate_fee(self, transaction_value, *, metadata=None, **kw):
        if (metadata or {}).get("asset_class") == "fixed_income":
            return transaction_value * 0.001  # 0.1% for bonds
        return transaction_value * 0.01       # 1% for equities
```

## Data Loading

```python
from pyfolium import load_from_csv, load_from_dataframe

# load_from_csv and load_from_dataframe return DataFrames
# ready to pass to the Asset constructor
data = load_from_csv('prices.csv', frequency='D', income_column='Dividend')

universe = AssetUniverse(data_frequency='D')
Asset('Stock', universe, data, income_column='income')
```

## Development

```bash
# First-time setup
uv sync
uv run setup-dev  # Installs pre-commit hooks

# Run tests
uv run pytest

# Format code
uv run ruff format .

# Lint
uv run ruff check --fix .

# Type check
uv run pyright pyfolium/

# Run all pre-commit checks manually
uv run pre-commit run --all-files
```

## Project Structure

```
pyfolium/
├── core.py         # Portfolio, Asset, AssetUniverse, TaxLot, configs
├── strategy.py     # BaseStrategy ABC
├── simulation.py   # BacktestRunner, BacktestResult
├── logging.py      # Severity, LogEntry, OutputMode
└── data.py         # Data loading utilities

tests/
├── core/           # Core component tests
├── strategy/       # Strategy framework tests
└── simulation/     # BacktestRunner tests

examples/           # Usage examples
```

## Architecture

For the full design rationale — modeling philosophy, data flow, tax system design, and architectural decisions — see [DESIGN.md](DESIGN.md).

### Period State Machine
Each period follows strict sequencing:
```
COLLECT_INCOME → TRANSACT → DONE → advance_period() → COLLECT_INCOME
```

1. `collect_income()` - Distribute dividends
2. `buy_asset()` / `sell_asset()` / `move_cash()` - Execute trades
3. `update_history()` - Record period state
4. `advance_period()` - Move to next period

### Tax Lot Tracking
- `TaxLot` dataclass: first-class lot records with symbol, period, quantity, cost basis
- FIFO, LIFO, or AVERAGE cost basis accounting via `sell_asset()`
- Specific lot targeting via `sell_lot(lot, quantity)` for tax-loss harvesting (requires `allow_specific_lot=True`)
- Per-share cost basis tracking
- Automatic short/long-term classification
- Optional immediate tax withholding
- `portfolio.open_lots` exposes open lots to strategies

## Examples

See `examples/backtest_runner_example.py` for comprehensive examples including:
- Simple usage
- Output modes (silent, summary, progress bar)
- Custom hooks
- Strategy logging
- Strategy comparison
- Step-by-step execution

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Contributing

1. Follow existing code style (use `ruff format`)
2. Add tests for new features
3. Run `uv run pre-commit run --all-files`
