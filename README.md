# Pyfolium

## Historical Hindsight Forecasting Kit

> **Hätte hätte Fahrradkette** — A German saying meaning "if only, if only" or "shoulda coulda woulda," used when looking back at missed opportunities. The perfect name for a backtesting library, though we opted for "Pyfolium" instead (because Python package names with umlauts are... challenging).

Pyfolium provides a robust framework for simulating historical portfolio performance with support for taxes, capital gains tracking, transaction fees, dividend income, and custom trading strategies.

## Features

- **Period-based state machine** enforces correct operation sequencing
- **Comprehensive tax system** with FIFO/LIFO accounting, short/long-term capital gains
- **Transaction fee modeling** with fixed, percentage, and min/max fee caps
- **Dividend/income tracking** and distribution
- **Full transaction history** and portfolio state snapshots
- **Strategy framework** for implementing custom trading algorithms
- **Type-safe** with pandas-stubs integration

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/pyfolium.git
cd pyfolium

# Install using uv (recommended)
uv sync

# Or using pip
pip install -e .
```

## Quick Start

```python
import pandas as pd
from pyfolium.core import Asset, AssetUniverse, Portfolio, TaxConfig, FeeConfig

# 1. Create an asset universe
universe = AssetUniverse(data_frequency='D')  # Daily data

# 2. Add assets with price/income data
asset_data = pd.DataFrame({
    'price': [100, 102, 105, 103],
    'income': [0, 0, 2, 0]  # Quarterly dividend
}, index=pd.period_range('2024-01', periods=4, freq='D'))

asset = Asset(
    symbol='AAPL',
    asset_universe=universe,
    asset_data=asset_data,
    price_column='price',
    income_column='income'
)

# 3. Configure taxes and fees
tax_config = TaxConfig(
    short_term_rate=0.30,
    long_term_rate=0.15,
    long_term_holding_periods=365
)

fee_config = FeeConfig(
    fixed_fee=1.0,
    percentage_fee=0.001,
    min_fee=1.0,
    max_fee=20.0
)

# 4. Create portfolio
portfolio = Portfolio(
    asset_universe=universe,
    initial_cash=10000.0,
    tax_config=tax_config,
    fee_config=fee_config
)

# 5. Run backtest (manual period loop)
for period in universe.get_period_index_range():
    # Step 1: Collect income/dividends
    portfolio.collect_income()

    # Step 2: Execute trades
    portfolio.buy_asset('AAPL', quantity=10)

    # Step 3: Record history
    portfolio.update_history()

    # Step 4: Advance to next period
    portfolio.advance_period()

# Access results
print(portfolio.history)  # Full portfolio history
print(portfolio.transactions)  # All transactions
print(portfolio.holdings)  # Current positions
```

## Strategy Framework

Implement custom strategies by subclassing `BaseStrategy`:

```python
from pyfolium.strategy import BaseStrategy

class BuyAndHold(BaseStrategy):
    def get_trades(self) -> list[tuple[str, float]]:
        """Returns list of (symbol, quantity) trades."""
        period = self.portfolio.current_period

        # Buy on first period
        if period == self.asset_universe.get_period_index_range()[0]:
            return [('AAPL', 10), ('MSFT', 5)]
        return []

# Use the strategy
strategy = BuyAndHold(
    portfolio=portfolio,
    asset_universe=universe,
    parameters={'initial_allocation': 0.8}
)

# Execute strategy steps
for period in universe.get_period_index_range():
    portfolio.collect_income()
    strategy.step()  # Get trades and execute them
    portfolio.update_history()
    portfolio.advance_period()
```

## Architecture

### Period Workflow

Pyfolium uses a strict state machine to ensure operations happen in the correct order:

```
┌─────────────────┐
│ COLLECT_INCOME  │ → collect_income()
└────────┬────────┘
         ▼
┌─────────────────┐
│   TRANSACT      │ → buy_asset(), sell_asset(), move_cash()
└────────┬────────┘
         ▼
┌─────────────────┐
│     DONE        │ → update_history(), advance_period()
└────────┬────────┘
         │
         └──────────► (next period)
```

### Key Components

- **`Asset`**: Individual financial instrument with price and income data
- **`AssetUniverse`**: Container managing all tradeable assets with aligned price/income matrices
- **`Portfolio`**: Core backtesting engine tracking cash, positions, transactions, and tax lots
- **`BaseStrategy`**: Abstract class for implementing trading strategies
- **`TaxConfig`**: Tax rules (FIFO/LIFO, short/long-term rates, withholding)
- **`FeeConfig`**: Transaction fee structure (fixed, percentage, caps)

## Tax System

Pyfolium tracks tax lots for accurate capital gains calculations:

- **FIFO or LIFO** accounting for determining which shares are sold
- **Short-term vs. long-term** capital gains based on holding period
- **Per-share cost basis** tracking for partial lot sales
- **Tax withholding** option on gains and income
- Transaction fees integrated into cost basis

**Note:** Current implementation does not refund withheld tax on losses.

## Development

### Setup

```bash
uv sync  # Install all dependencies including dev tools
```

### Testing

```bash
uv run pytest                    # Run all tests with coverage
uv run pytest tests/core/        # Run specific test directory
uv run pytest -k "test_name"     # Run specific test
```

### Code Quality

```bash
uv run ruff format .             # Format code
uv run ruff check --fix .        # Lint and fix issues
uv run mypy pyfolium/            # Type check
uv run pre-commit run --all-files  # Run all checks
```

## Project Status

**Core Features: Production Ready**
- ✅ Portfolio backtesting engine
- ✅ Tax calculations (FIFO/LIFO, capital gains)
- ✅ Transaction fees
- ✅ Strategy framework
- ✅ 70+ comprehensive tests

**Missing/In Development:**
- ⚠️ High-level backtest runner/automation
- ⚠️ Data loaders for external sources (Yahoo Finance, etc.)
- ⚠️ Example strategies and notebooks
- ⚠️ Performance reporting and visualization
- ⚠️ Documentation website

## Requirements

- Python 3.12+
- pandas 2.0+

## License

[Add your license here]

## Contributing

Contributions are welcome! Please ensure tests pass and code is formatted:

```bash
uv run pre-commit run --all-files
uv run pytest
```

## Acknowledgments

Built with modern Python tooling: uv, ruff, pytest, pydantic, and pandas. Inspired by the desire to answer the eternal question: "What if I had invested in that instead?"
