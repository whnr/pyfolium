# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Pyfolium is a Python backtesting library for portfolio management and trading strategies. It provides a framework for simulating historical portfolio performance with support for taxes, fees, income (dividends), and custom trading strategies.

The project name is a German pun: "Hätte hätte Fahrradkette" (roughly translates to "if only, if only" - used when looking back at missed opportunities), fitting for a backtesting library.

## Development Commands

### Environment Setup
- Package manager: `uv` (fast, modern Python package manager)
- Install dependencies: `uv sync` (installs all dependencies including dev)
- Run commands in venv: `uv run <command>` (auto-activates venv)
- Activate environment manually: `source .venv/bin/activate`
- Python version: 3.12+

### Testing
- Run all tests: `uv run pytest`
- Run specific test file: `uv run pytest tests/core/test_portfolio.py`
- Run specific test: `uv run pytest tests/core/test_portfolio.py::test_name`
- Tests include automatic coverage reporting to `coverage/` directory
- Coverage targets: `pyfolium.core` and `pyfolium.strategy`

### Code Quality
- Format and fix: `uv run ruff format .` (replaces black)
- Lint and fix: `uv run ruff check --fix .` (replaces flake8 and isort)
- Lint only: `uv run ruff check .`
- Type checking: `uv run mypy pyfolium/`
- Run all checks: `uv run pre-commit run --all-files`

All code quality tools configured in `pyproject.toml`:
- **Ruff**: Extremely fast linter and formatter (replaces black, isort, flake8)
- Line length: 88 characters
- Import sorting: isort-compatible, with pyfolium as first-party
- Linting rules: pycodestyle, pyflakes, pep8-naming, pyupgrade, flake8-bugbear, and more

## Architecture

### Core Data Flow

The library operates on a period-based system where time advances in discrete steps. Each period represents a unit of time (day, month, etc.) during which a sequence of operations must occur:

1. **Collect Income** (`collect_income()`) - Dividends/income from holdings are distributed
2. **Transact** (`buy_asset()`, `sell_asset()`, `move_cash()`) - Execute trades and cash movements
3. **Update History** (`update_history()`) - Record period state before advancing
4. **Advance Period** (`advance_period()`) - Move to next period

This state machine is enforced via `PortfolioState` enum to prevent operations in wrong order.

### Key Components

**AssetUniverse** (`pyfolium/core.py:141`): Container for all tradeable assets
- Maintains `price_matrix` and `income_matrix` DataFrames with aligned PeriodIndex
- All assets must have matching `data_frequency` (e.g., 'D' for daily, 'M' for monthly)
- Automatically updates matrices when assets are added

**Asset** (`pyfolium/core.py:41`): Individual financial instrument
- Requires DataFrame with PeriodIndex at specified frequency
- Must have a price column; income column optional (defaults to 0)
- Self-registers with parent AssetUniverse on initialization
- Validates index is monotonic and matches universe frequency

**Portfolio** (`pyfolium/core.py:213`): The core backtesting engine
- Tracks `cash`, `tax_owed`, `holdings` (positions over time)
- Maintains complete `transactions` log and `history` of account states
- Tax lots tracked via FIFO or LIFO for capital gains calculations
- Current period tracked via `current_period` and advanced strictly monotonously

**BaseStrategy** (`pyfolium/strategy.py:9`): Abstract class for trading strategies
- Subclasses must implement `get_trades()` returning list of (symbol, quantity) tuples
- `step()` method gets trades and executes them via portfolio
- Tracks all trade attempts (successful and failed) in `trades_df`

### Tax System

The tax system (`TaxConfig` in `pyfolium/core.py:9`) supports:
- Short-term vs long-term capital gains based on holding period
- FIFO or LIFO tax lot accounting
- Optional tax withholding on gains and income
- Per-share cost basis tracking for partial lot sales

**Important**: Current implementation has known limitation - withheld tax on gains is not refunded on losses.

### Fee System

Fee calculation (`FeeConfig` in `pyfolium/core.py:26`):
- Fixed fee per trade
- Percentage-based fee
- Minimum and maximum fee caps
- Fees incorporated into cost basis for tax calculations

## Testing Patterns

The test suite uses extensive pytest fixtures (see `tests/conftest.py`):
- `sample_asset_universe`: Empty universe with daily frequency
- `sample_asset_data`: Random walk price data with quarterly dividends
- `portfolio_with_assets_taxes_fees`: Fully configured portfolio for complex scenarios
- Asset fixtures for income and sell testing with specific price/income patterns

Tests use `deepdiff` for DataFrame comparisons and `pytest-mock` for mocking.

## Code Style

- Docstring format: Google style (changed from previous style as of commit 52ca78d)
- Line length: 88 characters (black default)
- Type hints: Preferred for public methods, using pandas-stubs for DataFrame typing
- Pandas display: Tests configure unlimited column display for debugging

## Project Structure

```
pyfolium/
├── core.py         # Asset, AssetUniverse, Portfolio, TaxConfig, FeeConfig
└── strategy.py     # BaseStrategy ABC

tests/
├── conftest.py     # Shared fixtures
├── core/           # Tests for core components
└── strategy/       # Tests for strategy system

strategies/         # User-defined strategies (empty, for users to populate)
examples/           # Example usage (empty, for users to populate)
```

## Current State

Recent development (from commit history):
- Module renamed to "Pyfolium"
- BaseStrategy ABC implemented
- New period handling system in Portfolio
- Docstrings converted to Google style

The `strategies/` and `examples/` directories are empty placeholder directories intended for user-defined strategies and example notebooks.
