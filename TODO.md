# Pyfolium Improvement Backlog

This document tracks potential improvements identified during architecture review. Each item is categorized and prioritized for curation.

**Status Legend:**
- 🔴 **CRITICAL** - Fix before scaling to production
- 🟡 **HIGH** - High impact, should do soon
- 🟢 **MEDIUM** - Nice to have, moderate impact
- 🔵 **LOW** - Future consideration
- ❌ **REJECTED** - Decided against (with rationale)

---

## 🔴 Critical Fixes

### 1. Fix API Documentation Inconsistencies
**Priority:** 🔴 CRITICAL
**Effort:** 2-3 hours
**Status:** ⏳ TODO

**Problem:**
- `docs/index.rst:39-87` contains outdated API examples that don't match current implementation
- Examples will fail if users copy-paste them

**Issues Found:**
```python
# WRONG (in docs/index.rst)
asset = Asset('AAPL', asset_data, universe)  # Wrong parameter order
tax_config = TaxConfig(holding_period_days=365)  # Wrong parameter name
portfolio = Portfolio(universe, initial_cash=10000)  # No initial_cash parameter

# CORRECT (actual API)
asset = Asset('AAPL', universe, asset_data)  # symbol, universe, data
tax_config = TaxConfig(long_term_holding_period=pd.DateOffset(years=1))
portfolio = Portfolio(universe)
portfolio.move_cash(10000)
```

**Files to Fix:**
- [ ] `docs/index.rst` lines 39-87
- [ ] `docs/quickstart.rst` - verify all examples
- [ ] Run all doc examples as tests to prevent regression

**Acceptance Criteria:**
- All documentation examples run without errors
- API matches current implementation exactly
- Add CI step to test documentation examples

---

### 2. Add Portfolio Value Helper Method
**Priority:** 🟡 HIGH
**Effort:** 2-3 hours
**Status:** ⏳ TODO

**Problem:**
Users must repeatedly calculate `cash + sum(holdings * prices)` across codebase:
- `examples/backtest_runner_example.py` lines 96, 177, 212, 305, 308, 311
- Every strategy that needs portfolio value
- Error-prone and verbose

**Solution:**
```python
class Portfolio:
    def get_value(self, period: pd.Period | None = None) -> float:
        """Calculate total portfolio value (cash + holdings) at given period.

        Args:
            period: Period to calculate value for (default: current_period)

        Returns:
            Total portfolio value in currency units
        """
        period = period or self.current_period
        holdings = self.holdings.loc[period]
        prices = self.asset_universe.price_matrix.loc[period]
        return float(self.cash + (holdings * prices).sum())
```

**Files to Modify:**
- [ ] `pyfolium/core.py` - add method to Portfolio class
- [ ] `examples/backtest_runner_example.py` - refactor to use helper
- [ ] `tests/core/test_portfolio.py` - add tests

**Acceptance Criteria:**
- Method handles current and historical periods
- Returns float (not Series)
- All examples updated to use it

---

## 🟡 High Impact Improvements

### 3. Integration Guide for Analytics Libraries
**Priority:** 🟡 HIGH
**Effort:** 4-6 hours
**Status:** ⏳ TODO

**Rationale:**
Instead of building analytics in Pyfolium, document integration with existing tools.

**Research Findings:**
- **QuantStats** (recommended) - Actively maintained, 6.4k stars, latest release Sept 2025
  - Inputs: pandas Series of daily returns
  - Outputs: 50+ metrics, tearsheets, HTML reports
  - Installation: `pip install quantstats`

- **empyrical-reloaded** - Maintained fork of Zipline's empyrical
  - Inputs: pandas Series of returns
  - Outputs: Individual metrics (Sharpe, Sortino, max drawdown, etc.)

- **pyfolio-reloaded** - Maintained fork with tearsheets
  - More comprehensive but heavier dependency

**Solution:**
Create `docs/integrations/` with guides:

1. **QuantStats Integration** (`docs/integrations/quantstats.md`):
```python
import quantstats as qs
from pyfolium import BacktestRunner

# Run backtest
result = BacktestRunner(portfolio, strategy).run()

# Calculate returns from history
history = result.portfolio.history
returns = history['cash'].pct_change().dropna()

# Generate metrics
print(qs.stats.sharpe(returns))
print(qs.stats.max_drawdown(returns))

# Generate full tearsheet
qs.reports.html(returns, output='backtest_report.html')
```

2. **Visualization Guide** (`docs/integrations/plotting.md`)
3. **Data Sources Guide** (`docs/integrations/data_sources.md`)

**Files to Create:**
- [ ] `docs/integrations/quantstats.md`
- [ ] `docs/integrations/plotting.md` (matplotlib/plotly examples)
- [ ] `docs/integrations/data_sources.md` (yfinance, alpaca, etc.)
- [ ] `examples/integration_quantstats.py` - working example
- [ ] Update `docs/index.rst` to link to integrations

**Acceptance Criteria:**
- Working end-to-end example with QuantStats
- Shows how to convert portfolio.history to returns
- Demonstrates tearsheet generation

---

### 4. Add BacktestResult Helper Properties
**Priority:** 🟡 HIGH
**Effort:** 3-4 hours
**Status:** ⏳ TODO

**Problem:**
BacktestResult is too lean - users repeat basic calculations.

**Solution:**
```python
@dataclass
class BacktestResult:
    # ... existing fields ...

    @property
    def final_portfolio_value(self) -> float:
        """Total portfolio value (cash + holdings) at end_period."""
        return self.portfolio.get_value(self.end_period)

    @property
    def initial_portfolio_value(self) -> float:
        """Total portfolio value at start_period."""
        return self.portfolio.get_value(self.start_period)

    @property
    def total_return(self) -> float:
        """Total return over backtest period (not annualized)."""
        initial = self.initial_portfolio_value
        final = self.final_portfolio_value
        return (final - initial) / initial if initial > 0 else 0.0

    @property
    def trade_count(self) -> int:
        """Number of trades executed (buy/sell only)."""
        trades = self.strategy.trades_df
        return len(trades[trades['success'] == True])

    @property
    def failed_trade_count(self) -> int:
        """Number of trades that failed to execute."""
        return len(self.strategy.trades_df[self.strategy.trades_df['success'] == False])
```

**Files to Modify:**
- [ ] `pyfolium/simulation.py` - add properties
- [ ] `tests/simulation/test_backtest_runner.py` - add tests
- [ ] Update examples to demonstrate usage

**Acceptance Criteria:**
- All properties cached (computed once)
- Handles edge cases (zero initial value, no trades)
- Documented with examples

---

### 5. Add __repr__ Methods to Core Classes
**Priority:** 🟢 MEDIUM
**Effort:** 2-3 hours
**Status:** ⏳ TODO

**Problem:**
Debugging is harder without readable string representations.

**Current Behavior:**
```python
>>> portfolio
<pyfolium.core.Portfolio object at 0x7f8b3c4d5e10>
```

**Desired Behavior:**
```python
>>> portfolio
Portfolio(period=2023-01-15, cash=$45,230.50, holdings=2 assets)

>>> asset
Asset(symbol='AAPL', periods=252, price_range=$100.00-$225.50)

>>> universe
AssetUniverse(frequency='D', assets=['AAPL', 'GOOGL', 'MSFT'])
```

**Files to Modify:**
- [ ] `pyfolium/core.py` - add __repr__ to Asset, AssetUniverse, Portfolio
- [ ] `pyfolium/strategy.py` - add __repr__ to BaseStrategy
- [ ] `tests/` - add tests for __repr__ methods

**Acceptance Criteria:**
- Informative but concise (single line)
- Shows key state information
- Doesn't trigger expensive computations

---

## 🟢 Medium Impact Improvements

### 6. Refactor Monolithic core.py
**Priority:** 🟢 MEDIUM
**Effort:** 1 day
**Status:** ⏳ TODO

**Problem:**
`core.py` is 839 lines with 6 major classes - harder to navigate.

**Proposed Structure:**
```
pyfolium/core/
├── __init__.py       # Re-exports for backward compatibility
├── asset.py          # Asset, AssetUniverse (~200 LOC)
├── portfolio.py      # Portfolio, PortfolioState (~450 LOC)
├── config.py         # TaxConfig, FeeConfig (~100 LOC)
└── constants.py      # Shared constants/enums
```

**Benefits:**
- Easier navigation
- Clearer module boundaries
- Simpler testing
- Better IDE performance

**Migration Strategy:**
```python
# pyfolium/core/__init__.py - maintain backward compatibility
from pyfolium.core.asset import Asset, AssetUniverse
from pyfolium.core.portfolio import Portfolio, PortfolioState
from pyfolium.core.config import TaxConfig, FeeConfig

__all__ = [
    "Asset",
    "AssetUniverse",
    "Portfolio",
    "PortfolioState",
    "TaxConfig",
    "FeeConfig",
]
```

**Files to Create/Modify:**
- [ ] Create new module structure
- [ ] Update imports throughout codebase
- [ ] Verify all tests pass
- [ ] Add deprecation warnings if needed

**Acceptance Criteria:**
- All existing imports still work
- No test failures
- Docs updated with new structure

---

### 7. Add Data Validation Utilities
**Priority:** 🟢 MEDIUM
**Effort:** 1 day
**Status:** ⏳ TODO

**Problem:**
Asset data can have gaps, NaNs, inconsistencies - no built-in validation.

**Solution:**
Create `pyfolium/validation.py`:

```python
from dataclasses import dataclass

@dataclass
class ValidationResult:
    valid: bool
    warnings: list[str]
    errors: list[str]

    def __str__(self):
        return f"Valid: {self.valid}, {len(self.warnings)} warnings, {len(self.errors)} errors"

def validate_asset_data(
    data: pd.DataFrame,
    price_column: str = 'price',
    income_column: str | None = 'income'
) -> ValidationResult:
    """Check asset data for common issues.

    Checks:
    - Missing values (NaN) in price/income
    - Non-positive prices
    - Price discontinuities (gaps > 50%)
    - Duplicate periods
    - Non-monotonic index
    """

def fill_missing_prices(
    data: pd.DataFrame,
    method: str = 'ffill'
) -> pd.DataFrame:
    """Fill missing price data using forward fill or interpolation."""

def detect_price_outliers(
    data: pd.DataFrame,
    threshold: float = 3.0
) -> pd.DataFrame:
    """Detect price outliers using z-score method."""
```

**Files to Create:**
- [ ] `pyfolium/validation.py`
- [ ] `tests/test_validation.py`
- [ ] Update `pyfolium/__init__.py` to export
- [ ] Add example in `examples/data_validation.py`

**Acceptance Criteria:**
- Catches common data issues
- Provides actionable warnings
- Optional auto-fix for some issues

---

### 8. Improve Error Messages
**Priority:** 🟢 MEDIUM
**Effort:** 2-3 hours
**Status:** ⏳ TODO

**Problem:**
Some error messages lack context for debugging.

**Examples to Fix:**

```python
# CURRENT: core.py:127
raise ValueError(
    f"Data frequency of {self.data.index.freqstr}"
    f"does not match data_frequency of {self.assetUniverse.data_frequency}"
)

# IMPROVED:
raise ValueError(
    f"Asset '{self.symbol}' has frequency '{self.data.index.freqstr}' "
    f"but universe expects '{self.assetUniverse.data_frequency}'. "
    f"Convert data using: data.index = data.index.to_period('{self.assetUniverse.data_frequency}')"
)

# CURRENT: core.py:728
raise ValueError(
    f"Quantity to sell {quantity} is greater than current holdings "
    f"{current_holding_quantity} for symbol {symbol}."
)

# IMPROVED:
raise ValueError(
    f"Cannot sell {quantity} shares of {symbol}. "
    f"Current holdings: {current_holding_quantity} shares. "
    f"Shortfall: {quantity - current_holding_quantity} shares."
)
```

**Files to Review:**
- [ ] `pyfolium/core.py` - all ValueError/RuntimeError
- [ ] `pyfolium/simulation.py` - error messages
- [ ] `pyfolium/data.py` - FileNotFoundError, etc.

**Acceptance Criteria:**
- Error messages include actual vs expected values
- Suggest fixes where possible
- No generic "invalid input" messages

---

### 9. Add Logging Infrastructure
**Priority:** 🟢 MEDIUM
**Effort:** 4-5 hours
**Status:** ⏳ TODO

**Problem:**
No logging makes debugging production issues harder.

**Solution:**
```python
import logging

logger = logging.getLogger(__name__)

class Portfolio:
    def buy_asset(self, symbol: str, quantity: float):
        logger.debug(f"Buying {quantity} shares of {symbol} at {price}")
        # ... existing code ...
        logger.info(f"Purchased {quantity} {symbol} for ${total_cost:,.2f}")

    def sell_asset(self, symbol: str, quantity: float):
        logger.debug(f"Selling {quantity} shares of {symbol}")
        # ... existing code ...
        logger.info(
            f"Sold {quantity} {symbol}, "
            f"realized gains: ${long_term_gains + short_term_gains:,.2f}"
        )
```

**Logging Levels:**
- **DEBUG**: Every transaction detail
- **INFO**: Major operations (buy/sell completed)
- **WARNING**: Unusual situations (large positions, negative cash)
- **ERROR**: Operation failures

**Files to Modify:**
- [ ] `pyfolium/core.py` - add logging
- [ ] `pyfolium/simulation.py` - add logging
- [ ] `pyfolium/strategy.py` - add logging
- [ ] `examples/logging_example.py` - demonstrate configuration

**Acceptance Criteria:**
- Users can enable logging with standard Python logging config
- Default: no logs (don't pollute stdout)
- Structured logging with context

---

### 10. Naming Convention Cleanup
**Priority:** 🟢 MEDIUM
**Effort:** 3-4 hours
**Status:** ⏳ TODO

**Problem:**
Mixed naming conventions hurt readability.

**Issues:**
1. `assetUniverse` parameter (camelCase) vs `asset_universe` everywhere else
2. Transaction columns as dict → should be Pydantic model
3. Some private methods could be public for testing

**Changes:**

```python
# 1. Deprecate camelCase parameter
class Asset:
    def __init__(
        self,
        symbol: str,
        asset_universe: "AssetUniverse",  # NEW preferred name
        data: pd.DataFrame,
        ...
    ):
        # Support both for backward compatibility
        self.asset_universe = asset_universe

# 2. Transaction model
class TransactionRecord(BaseModel):
    period: pd.Period
    type: str
    symbol: str | None = None
    quantity: float | None = None
    # ... etc

    model_config = {"arbitrary_types_allowed": True}

# 3. Make state checks public (or add test hooks)
def check_state(self, expected_state: PortfolioState) -> None:
    """Public state validation for testing/hooks."""
```

**Files to Modify:**
- [ ] `pyfolium/core.py` - parameter name, transaction model
- [ ] Update deprecation warnings
- [ ] Update all examples
- [ ] Update tests

**Acceptance Criteria:**
- Backward compatible (old names work with DeprecationWarning)
- All code uses snake_case
- Clear migration guide in CHANGELOG

---

## 🔵 Low Priority / Future Considerations

### 11. Lazy Evaluation for History DataFrame
**Priority:** 🔵 LOW
**Effort:** 2-3 hours
**Status:** ⏳ TODO

**Problem:**
Pre-allocating entire history DataFrame wastes memory for:
- Parameter sweeps (100+ portfolio clones)
- Monte Carlo simulations (1,000+ runs)
- Partial backtests (test 100 days of 10-year data)

**When NOT needed:**
- Single full backtests
- Small datasets (< 1,000 periods)
- Memory is not constrained

**Solution:**
```python
class Portfolio:
    def __init__(self, ...):
        self._history_records = []  # List instead of DataFrame
        self._history_built = False

    def update_history(self) -> None:
        # Fast: append to list
        self._history_records.append({
            'period': self.current_period,
            'cash': self.cash,
            # ... etc
        })

    @property
    def history(self) -> pd.DataFrame:
        """Lazy construction when accessed."""
        if not self._history_built:
            self._history_df = pd.DataFrame(self._history_records)
            self._history_df.set_index('period', inplace=True)
            self._history_built = True
        return self._history_df
```

**Benefits:**
- 5-10x faster for parameter sweeps
- Lower memory footprint for partial backtests
- Transparent to users (property access)

**Decision Needed:**
- Implement now vs wait for user reports of memory issues?
- Profile first to quantify benefit?

---

### 12. Integration Tests
**Priority:** 🟢 MEDIUM
**Effort:** 1 day
**Status:** ⏳ TODO

**Problem:**
107 unit tests but no end-to-end validation.

**Solution:**
Create `tests/integration/` with:

```python
# test_complete_workflow.py
def test_end_to_end_backtest():
    """Load data, run strategy, verify results."""
    # Load from CSV
    data = load_from_csv('tests/data/sample.csv', frequency='D')

    # Create universe and portfolio
    universe = AssetUniverse('D')
    Asset('TEST', universe, data)
    portfolio = Portfolio(universe, tax_config=..., fee_config=...)

    # Run backtest
    strategy = BuyAndHold(portfolio)
    result = BacktestRunner(portfolio, strategy).run()

    # Verify results
    assert result.success
    assert result.total_periods > 0
    assert result.portfolio.cash >= 0

# test_strategy_comparison.py
def test_clone_and_compare():
    """Verify portfolio cloning for strategy comparison."""

# test_edge_cases.py
def test_market_crash():
    """Test behavior during extreme volatility."""
```

**Files to Create:**
- [ ] `tests/integration/test_complete_workflow.py`
- [ ] `tests/integration/test_strategy_comparison.py`
- [ ] `tests/integration/test_edge_cases.py`
- [ ] `tests/data/sample.csv` - test data

**Acceptance Criteria:**
- Tests run in < 10 seconds
- Cover major user workflows
- Catch integration bugs unit tests miss

---

### 13. Performance Benchmarks
**Priority:** 🔵 LOW
**Effort:** 3-4 hours
**Status:** ⏳ TODO

**Problem:**
No way to track performance regressions.

**Solution:**
Use `pytest-benchmark`:

```python
# tests/benchmarks/test_performance.py
def test_backtest_1000_periods(benchmark):
    universe = create_universe(periods=1000)
    portfolio = Portfolio(universe)
    strategy = SimpleStrategy(portfolio)

    result = benchmark(
        BacktestRunner(portfolio, strategy).run
    )

    assert result.success

def test_portfolio_clone(benchmark):
    portfolio = create_large_portfolio()
    benchmark(portfolio.clone)
```

**Files to Create:**
- [ ] `tests/benchmarks/test_performance.py`
- [ ] Add `pytest-benchmark` to dev dependencies
- [ ] CI step to track performance trends

**Decision Needed:**
- Implement now or wait until performance issues reported?

---

### 14. Property-Based Tests
**Priority:** 🔵 LOW
**Effort:** 1-2 days
**Status:** ⏳ TODO

**Problem:**
Testing specific cases, not general properties.

**Solution:**
Use `hypothesis`:

```python
from hypothesis import given, strategies as st

@given(st.floats(min_value=0, max_value=1))
def test_tax_rate_validation(rate):
    """Tax rates must always be between 0 and 1."""
    config = TaxConfig(short_term_rate=rate)
    assert 0 <= config.short_term_rate <= 1

@given(
    st.floats(min_value=1, max_value=1000),
    st.floats(min_value=1, max_value=100)
)
def test_buy_sell_roundtrip(price, quantity):
    """Buying then selling should be ~neutral (minus fees/taxes)."""
    # ... test logic
```

**Files to Create:**
- [ ] `tests/property/test_portfolio_properties.py`
- [ ] `tests/property/test_config_properties.py`
- [ ] Add `hypothesis` to dev dependencies

**Decision Needed:**
- Value vs effort for this project?

---

## 📚 Documentation Improvements

### 15. Architecture Diagrams
**Priority:** 🟢 MEDIUM
**Effort:** 3-4 hours
**Status:** ⏳ TODO

**Content Needed:**
1. State machine diagram (COLLECT_INCOME → TRANSACT → DONE)
2. Class relationship diagram (UML)
3. Data flow diagram (data loading → backtest → results)

**Tools:**
- Mermaid.js (embeddable in markdown)
- draw.io / diagrams.net
- PlantUML

**Files to Create:**
- [ ] `docs/architecture/state_machine.md`
- [ ] `docs/architecture/class_diagram.md`
- [ ] `docs/architecture/data_flow.md`

---

### 16. Recipe Documentation
**Priority:** 🟡 HIGH
**Effort:** 1 day
**Status:** ⏳ TODO

**Content Needed:**
Common patterns users will want:

1. **Moving Average Crossover Strategy**
2. **Rebalancing to Target Weights**
3. **Handling Missing Data**
4. **Exporting Results to CSV/Excel**
5. **Creating Custom Hooks**
6. **Integrating with QuantStats**
7. **Testing Strategies**

**Files to Create:**
- [ ] `docs/recipes.rst` or `docs/recipes/` directory
- [ ] Link from main documentation

---

### 17. CHANGELOG.md
**Priority:** 🟢 MEDIUM
**Effort:** 1 hour
**Status:** ⏳ TODO

**Format:**
Follow [Keep a Changelog](https://keepachangelog.com/):

```markdown
# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]
### Added
- Philosophy & Scope section to README

## [0.1.0] - 2025-01-15
### Added
- BacktestRunner with hooks and progress reporting
- Portfolio cloning for strategy comparison
- Pydantic validation for TaxConfig and FeeConfig
- Data loading utilities

### Changed
- Switched from black to ruff for formatting
```

**Files to Create:**
- [ ] `CHANGELOG.md` in root
- [ ] Link from README

---

### 18. Jupyter Notebook Examples
**Priority:** 🟡 HIGH
**Effort:** 1 day
**Status:** ⏳ TODO

**Rationale:**
Interactive examples are easier to learn from than scripts.

**Notebooks to Create:**
1. `01_getting_started.ipynb` - Basic backtest
2. `02_strategy_development.ipynb` - Creating custom strategies
3. `03_strategy_comparison.ipynb` - Cloning and comparing
4. `04_quantstats_integration.ipynb` - Analytics and tearsheets
5. `05_advanced_topics.ipynb` - Taxes, fees, debugging

**Files to Create:**
- [ ] `examples/notebooks/*.ipynb`
- [ ] Add `jupyter` to dev dependencies
- [ ] CI step to test notebooks run without errors

---

## ❌ Rejected / Out of Scope

### Analytics Module (Built-in)
**Status:** ❌ REJECTED

**Rationale:**
- QuantStats already does this well (6.4k stars, actively maintained)
- Building our own would be reinventing the wheel
- Better to integrate with ecosystem than create walled garden

**Alternative:**
Document integration with QuantStats (see item #3)

---

### Visualization Features
**Status:** ❌ REJECTED

**Rationale:**
- matplotlib, plotly, mplfinance already exist
- Visualization preferences are highly personal
- Adds dependencies and maintenance burden

**Alternative:**
Provide examples showing integration with common plotting libraries

---

### Data Fetching/Sources
**Status:** ❌ REJECTED

**Rationale:**
- yfinance, alpaca-py, etc. already handle this
- API keys and rate limits are complex
- Data sources change frequently

**Alternative:**
Document how to use popular data sources with Pyfolium

---

### Portfolio Optimization
**Status:** ❌ REJECTED

**Rationale:**
- PyPortfolioOpt, riskfolio-lib are mature solutions
- Complex mathematical optimization out of scope
- Focus on backtesting, not optimization

**Alternative:**
Show how to use scipy.optimize or optuna for parameter tuning

---

### Corporate Actions (Stock Splits, Mergers)
**Status:** 🔵 FUTURE CONSIDERATION

**Rationale:**
- Complex edge cases
- Requires significant data modeling
- Not critical for MVP

**Decision:**
Revisit when users request it with specific use cases

---

### Rebalancing Utilities
**Status:** 🔵 FUTURE CONSIDERATION

**Rationale:**
- Can be implemented in strategies
- Not core to backtesting engine

**Decision:**
Provide recipe/example instead of built-in module

---

### Portfolio Constraints (Position Limits)
**Status:** 🔵 FUTURE CONSIDERATION

**Rationale:**
- Can be enforced in strategy logic
- Edge cases are complex (what happens when violated?)

**Decision:**
Document pattern, don't build into core

---

## Priority Recommendation

If you have **1 week**:
1. ✅ Fix API docs (2-3 hrs) - CRITICAL
2. ✅ Add Portfolio.get_value() (2-3 hrs)
3. ✅ QuantStats integration guide (4-6 hrs)
4. ✅ BacktestResult helpers (3-4 hrs)
5. ✅ Add __repr__ methods (2-3 hrs)

If you have **2 weeks**, add:
6. ✅ Recipe documentation (1 day)
7. ✅ Jupyter notebook examples (1 day)
8. ✅ Error message improvements (2-3 hrs)
9. ✅ Integration tests (1 day)

If you have **1 month**, add:
10. ✅ Refactor core.py (1 day)
11. ✅ Data validation utilities (1 day)
12. ✅ Logging infrastructure (4-5 hrs)
13. ✅ Architecture diagrams (3-4 hrs)

---

## How to Use This File

**For maintainers:**
1. Review each item
2. Update status: ⏳ TODO | 🚧 IN PROGRESS | ✅ DONE | ❌ REJECTED
3. Move items between sections as priorities change
4. Link to GitHub issues for tracking

**For contributors:**
1. Pick an item marked ⏳ TODO
2. Check "Files to Modify/Create" for scope
3. Verify "Acceptance Criteria" before submitting PR
4. Update status to ✅ DONE when merged

---

**Last Updated:** 2025-11-01
**Review Cadence:** Monthly
