# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Pyfolium is a Python backtesting library for portfolio management and trading strategies. It provides a framework for simulating historical portfolio performance with support for taxes, fees, income (dividends), and custom trading strategies.

The project name is a German pun: "Hätte hätte Fahrradkette" (roughly translates to "if only, if only" - used when looking back at missed opportunities), fitting for a backtesting library.

## Development Commands

### Environment Setup
- Package manager: `uv` (fast, modern Python package manager)
- Install dependencies: `uv sync` (installs all dependencies including dev)
- Set up pre-commit hooks: `uv run setup-dev` (run once after initial sync)
- Run commands in venv: `uv run <command>` (auto-activates venv)
- Activate environment manually: `source .venv/bin/activate`
- Python version: 3.12+

**Note:** After running `setup-dev`, pre-commit hooks will automatically run ruff and pyright on every commit. Use `uv run pre-commit run --all-files` to run all hooks locally.

### Testing
- Run all tests: `uv run pytest`
- Run specific test file: `uv run pytest tests/simulation/test_backtest_runner.py`
- Run specific test: `uv run pytest tests/simulation/test_backtest_runner.py::test_name`
- Tests include automatic coverage reporting to `coverage/` directory
- Coverage targets: `pyfolium.core`, `pyfolium.strategy`, `pyfolium.simulation`, `pyfolium.data`

**Development style: test-driven.** Write or update tests before (or alongside) implementation. Every new feature or bug fix must have a corresponding test. The test suite is the contract — if it passes, the implementation is correct.

### Code Intelligence

Prefer LSP over Grep/Glob/Read for code navigation:
- `goToDefinition` / `goToImplementation` to jump to source
- `findReferences` to see all usages across the codebase
- `workspaceSymbol` to find where something is defined
- `documentSymbol` to list all symbols in a file
- `hover` for type info without reading the file
- `incomingCalls` / `outgoingCalls` for call hierarchy

Before renaming or changing a function signature, use
`findReferences` to find all call sites first.

Use Grep/Glob only for text/pattern searches (comments,
strings, config values) where LSP doesn't help.

After writing or editing code, check LSP diagnostics before
moving on. Fix any type errors or missing imports immediately.

### Code Quality
- Format and fix: `uv run ruff format .` (replaces black)
- Lint and fix: `uv run ruff check --fix .` (replaces flake8 and isort)
- Lint only: `uv run ruff check .`
- Type checking: `uv run pyright pyfolium/`
- Run all checks: `uv run pre-commit run --all-files`

All code quality tools configured in `pyproject.toml`:
- **Ruff**: Extremely fast linter and formatter (replaces black, isort, flake8)
- **Pyright**: Static type checker in `standard` mode; pandas-stubs false-positives on `Period`/`Scalar` demoted to warnings (non-blocking) in `[tool.pyright]`
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

**AssetUniverse** (`pyfolium/core.py`): Container for all tradeable assets
- Maintains `price_matrix` and `income_matrix` DataFrames with aligned PeriodIndex
- All assets must have matching `data_frequency` (e.g., 'D' for daily, 'M' for monthly)
- Automatically updates matrices when assets are added

**Asset** (`pyfolium/core.py`): Validated data container for a financial instrument
- Requires DataFrame with PeriodIndex at specified frequency
- Must have a price column with no NaN values; income column optional (defaults to 0)
- Self-registers with parent AssetUniverse on initialization
- Validates index is monotonic and matches universe frequency
- Rejects NaN prices at construction (data quality gate)
- Runtime price/income queries go through `universe.price_matrix`/`income_matrix`, not Asset methods

**TaxLot** (`pyfolium/core.py`): Dataclass representing a single purchase lot
- Created by `buy_asset()`, consumed by `sell_asset()` in FIFO/LIFO order
- Tracks `symbol`, `period`, `quantity`, `quantity_remaining`, `cost_basis_per_share`
- Exposed to strategies via `portfolio.open_lots` for lot-level introspection

**Portfolio** (`pyfolium/core.py`): The core backtesting engine
- Tracks `cash`, `tax_owed`, `holdings` (positions over time)
- Transactions stored internally as `list[dict]` buffer; `portfolio.transactions` property builds DataFrame lazily
- Tax lots tracked as `TaxLot` dataclass instances via `_tax_lots: dict[str, list[TaxLot]]`
- Period index `_txn_period_index: dict[Period, list[int]]` for O(1) per-period transaction lookup
- Current period tracked via `current_period` / `_current_period_idx`; hot paths use `.iloc` for performance
- `clone()` method creates independent copy for strategy comparison

**BaseStrategy** (`pyfolium/strategy.py`): Abstract class for trading strategies
- Subclasses must implement `get_trades()` returning list of (symbol, quantity) tuples
- `step()` method gets trades and executes them via portfolio
- `log(severity, message, data)` emits structured `LogEntry` to `_log`; drained by runner after each step
- Tracks all trade attempts (successful and failed) in `trades_df`
- Parameters stored in `parameters` dict for reproducibility
- `initial_cash`: optional cash deposited via `move_cash()` at the first active period (keyword-only, `None` by default)
- `start_period`: optional first period for this strategy; `BacktestRunner` resolves it with precedence: explicit runner arg > `strategy.start_period` > `portfolio.current_period` (keyword-only, `None` by default)

**BacktestRunner** (`pyfolium/simulation.py`): Automated simulation orchestration
- Automates the period-by-period execution loop
- Supports custom hooks: `period_start`, `period_end`, `backtest_start`, `backtest_end`, `error`
- Structured logging via `_log: list[LogEntry]`; `_emit()` creates runner entries, strategy entries drained after each step
- `run(output=OutputMode.SILENT)` controls terminal output: `SILENT`, `SUMMARY`, `PROGRESS`
- Step-by-step execution with `run_period()` for debugging
- Lenient mode (`strict=False`) records errors/warnings in log and continues
- Returns `BacktestResult` with portfolio, strategy, metadata, and `log`

### Tax System

The tax system (`TaxConfig` in `pyfolium/core.py`) uses Pydantic for validation and owns all tax calculation logic via overridable methods:
- Short-term vs long-term capital gains based on holding period
- FIFO or LIFO tax lot accounting (validated at init)
- Optional tax withholding on gains and income
- Per-share cost basis tracking for partial lot sales
- Tax rates validated to be between 0.0 and 1.0

`TaxConfig` methods (subclassable for custom tax rules):
- `long_term_cutoff_period(current_period, data_frequency)` → `pd.Period` cutoff
- `classify_gain(purchase_period, current_period, data_frequency)` → `"short_term"` | `"long_term"`
- `calculate_tax(short_term_gains, long_term_gains)` → `TaxResult(tax_liability, tax_paid)`
- `select_lots(lots)` → filtered and sorted `list[TaxLot]`

`TaxResult` is a frozen dataclass returned by `calculate_tax`, containing `tax_liability` (added to `tax_owed`) and `tax_paid` (withheld from cash).

### Fee System

Fee calculation (`FeeConfig` in `pyfolium/core.py`) uses Pydantic for validation:
- Fixed fee per trade
- Percentage-based fee (validated 0.0-1.0)
- Minimum and maximum fee caps (validated max >= min)
- Fees incorporated into cost basis for tax calculations

## Testing Patterns

The test suite uses extensive pytest fixtures (see `tests/conftest.py`):
- `sample_asset_universe`: Empty universe with daily frequency
- `sample_asset_data`: Random walk price data with quarterly dividends
- `portfolio_with_assets_taxes_fees`: Fully configured portfolio for complex scenarios
- Asset fixtures for income and sell testing with specific price/income patterns

Tests use `deepdiff` for DataFrame comparisons and `pytest-mock` for mocking.

## Documentation Freshness

**README.md, DESIGN.md, and CLAUDE.md must be kept in sync with the code.** After any feature implementation or API change, update all three before committing:

- **README.md** — user-facing: quick start, usage examples, API surface
- **DESIGN.md** — architectural rationale, design decisions, modeling philosophy
- **CLAUDE.md** — this file; development workflow, architecture summary, current state

If a change affects examples, update the files in `examples/` too.

## Code Style

- Docstring format: Google style
- Line length: 88 characters (black default)
- Type hints: Preferred for public methods, using pandas-stubs for DataFrame typing
- Pandas display: Tests configure unlimited column display for debugging
- No backwards-facing comments in code (e.g. "no longer needed", "replaces old approach", "eliminates boilerplate"). Those belong in commit messages and changelogs, not in source files. Code is static; history lives in git.
- If using placeholders for Asset names, never use `AAPL` and `GOOGL`. Use `Stock`, `Aktie`, etc.

## Project Structure

```
pyfolium/
├── core.py         # Asset, AssetUniverse, Portfolio, TaxLot, TaxResult, TaxConfig, FeeConfig
├── strategy.py     # BaseStrategy ABC
├── simulation.py   # BacktestRunner, BacktestResult
├── logging.py      # Severity, LogEntry, OutputMode
└── data.py         # Data loading utilities

tests/
├── conftest.py     # Shared fixtures
├── core/           # Tests for core components
├── strategy/       # Tests for strategy system
├── simulation/     # Tests for BacktestRunner
├── test_logging.py # Tests for logging types
└── test_data.py    # Tests for data loading

examples/
└── backtest_runner_example.py  # Comprehensive usage examples

strategies/         # User-defined strategies (empty, for users to populate)
```

## Current State

Recent features:
- **Tax extensibility (P1)**: `TaxConfig` owns tax calculation via four overridable methods (`long_term_cutoff_period`, `classify_gain`, `calculate_tax`, `select_lots`); `TaxResult` frozen dataclass for structured return values; Portfolio delegates to TaxConfig methods instead of hardcoding tax math; users can subclass TaxConfig for custom rules (wash sales, jurisdiction-specific logic)
- **Transaction buffer + TaxLot (P0-2/P0-3)**: Transactions stored as `list[dict]` with lazy DataFrame via `.transactions` property; `TaxLot` dataclass for O(1) lot lookups in `sell_asset`/`collect_income`; period index for O(1) `update_history`; hot paths use `.iloc` instead of `.loc`; `portfolio.open_lots` exposes lots to strategies; benchmark: 1.83x speedup (137→251 periods/sec on 100-asset, 50yr daily simulation)
- **Structured logging**: `Severity`, `LogEntry`, `OutputMode` in `pyfolium/logging.py`; `BacktestRunner` captures structured log entries; `BaseStrategy.log()` lets strategies emit entries drained by the runner; `BacktestResult` exposes `.log`, `.log_df`, `.errors`, `.warnings`, `.success`; `OutputMode` enum (`SILENT`/`SUMMARY`/`PROGRESS`) controls terminal output
- **Strategy start conditions**: `BaseStrategy` accepts `initial_cash` and `start_period` keyword args; `BacktestRunner` injects cash on the first active period and resolves start period with precedence: runner arg > `strategy.start_period` > `portfolio.current_period`
- **Data gaps handling**: Asset rejects NaN prices at construction; trades on out-of-range periods fail gracefully via `success=False` in `trades_df`; NaN income treated as zero
- **BacktestRunner**: Automated simulation with hooks and progress reporting
- **Portfolio.clone()**: Deep copy for strategy comparison and optimization
- **Pydantic validation**: TaxConfig and FeeConfig with automatic validation
- **Data loading**: `load_from_csv` and `load_from_dataframe` utilities with explicit `income_column` (defaults to `None`; raises `ValueError` when an explicitly named column is missing) and `min_density` sanity check (default `0.5`) that catches frequency mismatches like monthly data loaded as daily
- **Comprehensive examples**: 7 usage patterns in examples/backtest_runner_example.py; benchmark in examples/benchmark.py

See `.claude/review-findings.md` for the full architecture review and action plan.
