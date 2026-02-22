# Architecture Review Findings & Action Plan

*Created: 2026-02-22 | Session: review-architecture-changes-GWIjK*
*Context: Full codebase review for production readiness — decades of daily data, AI-written strategies*

## Session Summary

This review examined every source file in pyfolium line-by-line. The codebase was largely
written by Claude (AI), with the original Portfolio/Asset core and DataFrame design decisions
made by the human author. The code passes its test suite but has structural issues that will
break at scale and several correctness bugs.

### What's solid (don't touch)
- Core domain model (Asset, AssetUniverse, Portfolio state machine)
- Tax system design (short/long term, FIFO/LIFO, withholding)
- Fee system design (fixed + percentage with min/max caps)
- Test fixtures in conftest.py (14 focused, well-composed fixtures)
- Original hand-written tests (state machine, transaction verification)

### What needs work
- Performance bottlenecks in hot path (O(n²) patterns)
- Several correctness bugs (no-op astype, DataFrame mutation, ignored parameter)
- AI bloat (redundant validators, empty context manager, dead code)
- Missing features for production use (specific lot identification, portfolio.total_value)
- Examples not testable

---

## P0 — Performance: Will break at scale

### P0-1: Replace `_update_future_holdings` with single-row write
**File:** `pyfolium/core.py:432-446`
**Problem:** Every `buy_asset`/`sell_asset` writes to ALL future rows in the holdings DataFrame.
With 5,200 periods and 3 trades/day = ~81M row writes total.
**Fix:**
- In `buy_asset`/`sell_asset`: replace `_update_future_holdings(symbol, qty)` with
  `self.holdings.loc[self.current_period, symbol] += qty` (O(1))
- In `advance_period()`: add `self.holdings.loc[next_period] = self.holdings.loc[self.current_period]`
  to carry forward (O(assets))
- Delete `_update_future_holdings` method entirely
**Strategy interface:** Unchanged. `holdings.loc[current_period]` returns same values.
Past periods return same history. Only change: future periods show 0 instead of forward-filled.
**Test impact:** Tests that check holdings at future periods may need updating.
Search for `holdings.loc[` in tests to find affected assertions.

### P0-2: Replace transaction `pd.concat` with pre-allocated buffer
**File:** `pyfolium/core.py:492-496`
**Problem:** Every `_register_transaction` call does `pd.concat` which copies the entire
transaction history. O(n) per trade, O(n²) total.
**Fix:**
- Add `trade_fraction` parameter to Portfolio.__init__ (default 0.10)
- Pre-allocate: `estimated_rows = n_periods * n_assets * trade_fraction`
- Use write cursor: `self._txn_buffer.iloc[self._txn_cursor] = kwargs`
- When buffer fills, double it (amortized O(1))
- Expose `transactions` as property: `return self._txn_buffer.iloc[:self._txn_cursor]`
**Strategy interface:** Unchanged. `portfolio.transactions` returns a DataFrame.
**Sizing math:** 5,200 periods × 500 assets × 0.10 = 260K rows × 15 cols ≈ 30MB. Trivial.
**Alternative (if iloc assignment is still slow):** Columnar numpy arrays with lazy DataFrame build.
Profile first before going there.

### P0-3: Tax lot tracker as first-class data structure
**File:** `pyfolium/core.py:711-716` (sell_asset), `575-578` (collect_income)
**Problem:** Every sell and every income collection scans the ENTIRE transaction log
to find matching buy lots via DataFrame boolean indexing.
**Fix:**
- Add `TaxLot` dataclass: `period, quantity, remaining, cost_basis_per_share, lot_id`
- Add `self._open_lots: dict[str, list[TaxLot]]` to Portfolio
- In `buy_asset`: append to `self._open_lots[symbol]`
- In `sell_asset`/`collect_income`: read from `self._open_lots[symbol]` (O(1) lookup)
- **IMPORTANT**: Expose to strategies (not internal-only!) — see P1-5 for `sell_lot()`
**Strategy interface:** New `portfolio.open_lots["AAPL"]` for fast lot access.
New `portfolio.open_lots_df` property for DataFrame view.
**Why exposed:** Specific lot identification is required for tax-loss harvesting strategies.
The US allows selective lot selling; FIFO/LIFO are just defaults.

---

## P1 — Correctness bugs

### P1-1: `history.astype(float)` is a no-op ✅ FIXED IN THIS SESSION
**File:** `pyfolium/core.py:358`
**Problem:** `self.history.astype(float)` creates new DataFrame but result is never assigned.
History columns remain `object` dtype.
**Fix:** `self.history = self.history.astype(float)`

### P1-2: Asset constructor mutates caller's DataFrame
**File:** `pyfolium/core.py:144`
**Problem:** When no income column provided, `self.data[self.income_column] = 0` modifies
the input DataFrame in-place, adding an "income" column the caller never asked for.
**Fix:** Add `self.data = data.copy()` early in `__init__`, before any mutations.
**Test:** Create a DataFrame, pass to Asset, verify original DataFrame unchanged.

### P1-3: `get_income_at` ignores `precise` parameter
**File:** `pyfolium/core.py:182-183`
**Problem:** Method accepts `precise` kwarg but always does exact lookup.
`get_price_at` properly handles `precise=False` with `asof()`.
**Fix:** Mirror `get_price_at` logic:
```python
def get_income_at(self, period, precise=True):
    if precise:
        return float(self.income[period])
    return float(self.income.asof(period))
```
**Test:** Add test with period between known income dates.

### P1-4: Error recovery in BacktestRunner silently corrupts state
**File:** `pyfolium/simulation.py:277-286`
**Problem:** On error, runner forces state to DONE and continues. Income may not have been
collected, holdings not updated, history incomplete. Silent corruption is worse than crashing.
**Fix options:**
1. **Strict mode (default):** Raise on first error, stop backtest
2. **Lenient mode (opt-in):** Log warning with full context, mark period as failed in results,
   skip to next period without corrupting state
3. Never force `_states` to DONE — that's lying about what happened
**Decision needed:** Discuss which behavior is right for AI-generated strategies.
Strict is safer; lenient is useful during strategy development.

### P1-5: Add `sell_lot()` method for specific lot identification
**File:** `pyfolium/core.py` (new method on Portfolio)
**Problem:** Only FIFO/LIFO exist. US tax system allows specific lot identification.
Tax-loss harvesting strategies need to choose which lot to sell.
**Design:**
```python
def sell_lot(self, symbol: str, lot_id: int, quantity: float):
    """Sell a specific tax lot by ID."""
    lot = self._open_lots[symbol][lot_id]  # O(1)
    # ... same tax/fee logic as sell_asset but for one specific lot
```
**Depends on:** P0-3 (lot tracker data structure)

---

## P2 — Design issues & cleanup

### P2-1: Missing space in error message ✅ FIXED IN THIS SESSION
**File:** `pyfolium/core.py:127-129`
**Problem:** Two f-strings concatenate without space: "Data frequency of Ddoes not match..."
**Fix:** Add space at start of second f-string.

### P2-2: `type` shadows Python builtin ✅ FIXED IN THIS SESSION
**File:** `pyfolium/core.py:640-643`
**Problem:** `type = "deposit"` shadows `type()`.
**Fix:** Rename to `txn_type`.

### P2-3: Remove redundant TaxConfig validator ✅ FIXED IN THIS SESSION
**File:** `pyfolium/core.py:33-39`
**Problem:** `@field_validator("tax_strategy")` duplicates the `pattern="^(FIFO|LIFO)$"`
constraint already on the Field definition.
**Fix:** Remove the `@field_validator` method.

### P2-4: Remove empty context manager
**File:** `pyfolium/simulation.py:362-370`
**Problem:** `__enter__`/`__exit__` do nothing. Context managers manage resources; there are none.
**Fix:** Remove `__enter__`, `__exit__`. Remove Example 7 from examples.
**Test impact:** Remove `test_context_manager` from test_backtest_runner.py.

### P2-5: Add `Portfolio.total_value` property
**File:** `pyfolium/core.py` (new property on Portfolio)
**Problem:** Every example and every strategy repeats:
```python
holdings = portfolio.holdings.loc[portfolio.current_period]
prices = universe.price_matrix.loc[portfolio.current_period]
total_value = portfolio.cash + (holdings * prices).sum()
```
**Fix:**
```python
@property
def total_value(self) -> float:
    holdings = self.holdings.loc[self.current_period]
    prices = self.asset_universe.price_matrix.loc[self.current_period]
    return self.cash + (holdings * prices).sum()
```
**Test:** Verify against manual calculation at various points.

### P2-6: Silent failure swallowing in `execute_trades`
**File:** `pyfolium/strategy.py:74-75`
**Problem:** ValueError in buy/sell is caught and silently recorded as failed.
AI-written strategies could make broken trades for entire backtest with no warning.
**Fix:** Add `import warnings` and `warnings.warn(f"Trade failed: {symbol} {quantity}: {e}")`
inside the except block. Keep recording in trades_df.

### P2-7: `load_from_csv` silently creates zero income on column name mismatch
**File:** `pyfolium/data.py:66-70`
**Problem:** If `income_column="Dividend"` but CSV has `"Dividends"`, creates zeros silently.
**Fix:** When `income_column` is explicitly provided and not found, raise ValueError.
Only create zeros when `income_column` is None (explicitly opted out).

### P2-8: Double date parsing in `load_from_csv`
**File:** `pyfolium/data.py:45,51`
**Problem:** `parse_dates=[date_column]` then `pd.to_datetime()` again.
**Fix:** Remove `parse_dates` from `read_csv`, keep the explicit `to_datetime`.

### P2-9: Code duplication in `data.py`
**File:** `pyfolium/data.py:56-77` vs `129-150`
**Problem:** Column selection, rename, and dedup logic is ~90% identical.
**Fix:** Extract `_build_result_dataframe(data, price_column, income_column)` helper.

### P2-10: `long_term_gains = 0` not `0.0` ✅ FIXED IN THIS SESSION
**File:** `pyfolium/core.py:739`
**Fix:** Change to `0.0` for type consistency.

---

## P3 — Project configuration

### P3-1: Python version pinning too tight ✅ FIXED IN THIS SESSION
**File:** `pyproject.toml:6`
**Problem:** `requires-python = ">=3.12,<3.13"` blocks Python 3.13+.
**Fix:** `requires-python = ">=3.12"`

### P3-2: Duplicate dev dependency groups ✅ FIXED IN THIS SESSION
**File:** `pyproject.toml:17-30` vs `36-50`
**Problem:** Both `[project.optional-dependencies].dev` and `[dependency-groups].dev` exist
with slightly different contents (types-tqdm version differs).
**Fix:** Remove `[project.optional-dependencies].dev`, keep `[dependency-groups].dev` (uv standard).

### P3-3: tqdm is required but handled as optional ✅ FIXED IN THIS SESSION
**File:** `pyproject.toml:11`, `pyfolium/simulation.py:17-22`
**Problem:** tqdm is in `dependencies` (always installed) but simulation.py has dead
try/except ImportError code.
**Fix:** Remove try/except in simulation.py, import tqdm directly.

### P3-4: Update CLAUDE.md coverage claim ✅ FIXED IN THIS SESSION
**File:** `CLAUDE.md`
**Problem:** Claims "94% coverage" but actual is 91%.
**Fix:** Correct to 91%.

---

## P4 — Make examples testable

### P4-1: Refactor examples to return values
**File:** `examples/backtest_runner_example.py`
**Problem:** Examples use print(), can't be imported and tested.
**Fix:**
- Each `example_*()` function returns its result (BacktestResult or relevant values)
- Keep print() for human readability but add return statements
- Remove Example 7 (empty context manager — see P2-4)

### P4-2: Add test file for examples
**File:** `tests/test_examples.py` (new)
**Fix:**
```python
from examples.backtest_runner_example import (
    example_simple, example_with_progress, ...
)

def test_example_simple():
    result = example_simple()
    assert result.success
    assert result.portfolio.cash > 0
    assert result.total_periods > 0
```

### P4-3: Missing `__init__.py` or pytest path config for examples
**Check:** Ensure examples directory is importable from tests.
May need `examples/__init__.py` or pytest `pythonpath` config update.

---

## Additional notes from review

### AssetUniverse "immutable" documentation lie
**File:** `pyfolium/core.py:405` (clone docstring)
Comment says "Shared reference (immutable)" but AssetUniverse has `add_asset()`.
**Decision needed:** Either make it actually immutable (freeze after Portfolio init)
or fix the comment. For production, freezing is safer.

### `camelCase` parameter `assetUniverse`
**File:** `pyfolium/core.py:107`
Ruff N803 is suppressed specifically for this. Renaming to `asset_universe` is a breaking
change to the Asset constructor API. Do it if we're doing a breaking change pass anyway.

### Strategy `step()` returns nothing
**File:** `pyfolium/strategy.py:78-81`
Consider having `step()` return the trades list or a StepResult for introspection.
Low priority — strategies can inspect `trades_df`.

### `collect_income` recomputes `earliest_long_term_period` inside loop
**File:** `pyfolium/core.py:582-585`
Move computation outside the `for symbol in symbols` loop.
Minor optimization but easy fix.

---

## Implementation order

Recommended sequence for the "big undo session":

1. **Trivial fixes** (P1-1, P2-1, P2-2, P2-3, P2-10, P3-*) — ✅ Done in this session
2. **P1-2** (DataFrame mutation) — Small, isolated, testable
3. **P1-3** (get_income_at precise) — Small, isolated, testable
4. **P2-5** (total_value property) — Small, used by everything downstream
5. **P2-6** (trade failure warnings) — Small, important for AI strategies
6. **P2-7, P2-8, P2-9** (data.py cleanup) — Grouped, moderate effort
7. **P0-1** (holdings write path) — Core change, needs careful testing
8. **P0-2** (transaction pre-allocation) — Core change, needs careful testing
9. **P0-3 + P1-5** (lot tracker + sell_lot) — Feature addition + performance
10. **P1-4** (error recovery) — Design decision needed first
11. **P2-4** (remove context manager) — Affects examples and tests
12. **P4-*** (testable examples) — After all API changes settle

Each step should be a single reviewable commit.
