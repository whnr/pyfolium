# Pyfolium

**Hätte hätte Fahrradkette** — If only, if only...

A Python backtesting library for portfolio management with support for taxes, fees, income, and custom trading strategies.

## Philosophy & Scope

Pyfolium is a **backtesting engine**, not a full-featured analytics platform. Our philosophy:

### What Pyfolium Does
- ✅ **Accurate simulation**: Tax-aware, fee-aware portfolio backtesting
- ✅ **State management**: Enforces correct transaction ordering and history tracking
- ✅ **Strategy framework**: Simple, extensible interface for trading algorithms
- ✅ **Data model**: Clean pandas-based data structures for easy integration

### What Pyfolium Doesn't Do
- ❌ **Performance analytics**: Use `quantstats`, `pyfolio`, or `empyrical` for Sharpe ratios, drawdowns, etc.
- ❌ **Visualization**: Use `matplotlib`, `plotly`, or `mplfinance` for charts
- ❌ **Data fetching**: Use `yfinance`, `alpaca-py`, or similar for market data
- ❌ **Optimization**: Use `scipy.optimize`, `optuna`, or `hyperopt` for parameter tuning
- ❌ **Risk models**: Use `PyPortfolioOpt`, `riskfolio-lib` for portfolio optimization

**Integration philosophy**: Pyfolium outputs clean pandas DataFrames (`portfolio.history`, `portfolio.transactions`) that work seamlessly with the ecosystem above. We won't reinvent these wheels.

## Features

- **BacktestRunner**: Automated simulation loop with hooks and progress reporting
- **Portfolio Cloning**: Compare strategies and run parameter optimization
- **Tax System**: FIFO/LIFO accounting with short/long-term capital gains
- **Transaction Fees**: Fixed, percentage, and min/max fee caps
- **State Machine**: Enforces correct operation sequencing per period
- **Strategy Framework**: Abstract base class for custom trading algorithms
- **Type-Safe**: Pydantic validation and pandas-stubs integration

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
from pyfolium import Asset, AssetUniverse, Portfolio, BacktestRunner, BaseStrategy

# 1. Create asset universe
universe = AssetUniverse(data_frequency='D')

# 2. Add assets with price data
dates = pd.period_range('2023-01-01', periods=252, freq='D')
data = pd.DataFrame({
    'price': [100 + i * 0.5 for i in range(252)],
    'income': [1.0 if i % 60 == 0 else 0.0 for i in range(252)]
}, index=dates)

Asset('AAPL', universe, data)

# 3. Create portfolio
portfolio = Portfolio(universe)
portfolio.collect_income()
portfolio.move_cash(50000)
portfolio.update_history()
portfolio.advance_period()

# 4. Define strategy
class BuyAndHold(BaseStrategy):
    def get_trades(self):
        if not hasattr(self, 'invested'):
            self.invested = True
            return [('AAPL', 100)]
        return []

# 5. Run backtest
runner = BacktestRunner(portfolio, BuyAndHold(portfolio))
result = runner.run(progress=True)

print(f"Final cash: ${result.portfolio.cash:,.2f}")
print(f"Execution time: {result.execution_time:.2f}s")
```

## BacktestRunner

Automates the period-by-period simulation loop:

```python
# Simple usage
runner = BacktestRunner(portfolio, strategy)
result = runner.run()

# With progress bar
result = runner.run(progress=True)

# Custom hooks
def log_value(runner):
    print(f"Period {runner.current_period}: ${runner.portfolio.cash:,.2f}")

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

## Strategy Comparison

Clone portfolios to compare strategies:

```python
base = Portfolio(universe)
base.collect_income()
base.move_cash(100000)
base.update_history()
base.advance_period()

# Run different strategies
result1 = BacktestRunner(base.clone(), Strategy1(base)).run()
result2 = BacktestRunner(base.clone(), Strategy2(base)).run()

print(f"Strategy 1: ${result1.portfolio.cash:,.2f}")
print(f"Strategy 2: ${result2.portfolio.cash:,.2f}")
```

## Custom Strategies

Subclass `BaseStrategy` and implement `get_trades()`:

```python
class MomentumStrategy(BaseStrategy):
    def __init__(self, portfolio, lookback=20):
        super().__init__(portfolio, parameters={'lookback': lookback})
        self.lookback = lookback

    def get_trades(self):
        # Your strategy logic here
        # Return list of (symbol, quantity) tuples
        # Positive quantity = buy, negative = sell
        return [('AAPL', 10), ('GOOGL', -5)]
```

## Tax and Fee Configuration

```python
from pyfolium import TaxConfig, FeeConfig

# Configure taxes
tax_config = TaxConfig(
    short_term_rate=0.30,
    long_term_rate=0.15,
    long_term_holding_period=pd.DateOffset(years=1),
    withhold_tax=True,
    tax_strategy='FIFO'  # or 'LIFO'
)

# Configure fees
fee_config = FeeConfig(
    fixed_fee=1.0,
    percentage_fee=0.001,  # 0.1%
    minimum_fee=1.0,
    maximum_fee=20.0
)

portfolio = Portfolio(universe, tax_config=tax_config, fee_config=fee_config)
```

## Data Loading

```python
from pyfolium import load_from_csv, load_from_dataframe

# From CSV
universe = load_from_csv('prices.csv', frequency='D')

# From DataFrame
df = pd.DataFrame(...)
universe = load_from_dataframe(df, frequency='D')
```

## Development

```bash
# First-time setup
uv sync
uv run setup-dev  # Installs pre-commit hooks

# Run tests
uv run pytest

# Format code (or let pre-commit do it automatically)
uv run ruff format .

# Lint (or let pre-commit do it automatically)
uv run ruff check --fix .

# Type check
uv run mypy pyfolium/

# Run all pre-commit checks manually
uv run pre-commit run --all-files
```

**Note:** After running `setup-dev`, ruff will automatically format and lint your code before each commit.

## Project Structure

```
pyfolium/
├── core.py         # Portfolio, Asset, AssetUniverse, configs
├── strategy.py     # BaseStrategy ABC
├── simulation.py   # BacktestRunner, BacktestResult
└── data.py         # Data loading utilities

tests/
├── core/           # Core component tests
├── strategy/       # Strategy framework tests
└── simulation/     # BacktestRunner tests

examples/           # Usage examples
```

## Architecture

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
- FIFO or LIFO accounting for capital gains
- Per-share cost basis tracking
- Automatic short/long-term classification
- Optional immediate tax withholding

## Examples

See `examples/backtest_runner_example.py` for comprehensive examples including:
- Simple usage
- Progress reporting
- Custom hooks
- Strategy comparison
- Step-by-step execution

## Project Status

**Core Features: Production Ready**
- ✅ Portfolio backtesting engine
- ✅ BacktestRunner with hooks and progress reporting
- ✅ Tax calculations (FIFO/LIFO, capital gains)
- ✅ Transaction fees
- ✅ Strategy framework
- ✅ Portfolio cloning for strategy comparison
- ✅ Data loading utilities
- ✅ 95+ comprehensive tests

**CI/CD:**
- ✅ Automated testing on pull requests and merges
- ✅ Code quality checks (ruff, mypy)
- ✅ Documentation deployment to GitHub Pages
- ✅ Python 3.12 compatibility testing
- ✅ Auto-setup of pre-commit hooks

**In Development:**
- ⚠️ Performance reporting and visualization
- ⚠️ Additional data source integrations

## Documentation

Full documentation is available at [GitHub Pages](https://yourusername.github.io/pyfolium/) (once deployed).

To build documentation locally:

```bash
cd docs
uv run sphinx-build -b html . _build/html
# Open docs/_build/html/index.html in your browser
```

Or use the Makefile:

```bash
cd docs
make html
```

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Contributing

1. Follow existing code style (use `ruff format`)
2. Add tests for new features
3. Update documentation
4. Run `uv run pre-commit run --all-files`

---

**Hätte hätte Fahrradkette** — Because hindsight is 20/20 🚲
