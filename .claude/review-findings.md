# Architecture Review Findings & Action Plan

*Created: 2026-02-22 | Session: review-architecture-changes-GWIjK*
*Updated: 2026-02-24 | Data gaps handling implemented + refactored per PR review (universe matrices as sole runtime data interface, removed get_price_at/get_income_at)*
*Updated: 2026-02-28 | Rebased onto development; mypy → pyright (cast() for reportAssignmentType, warnings demoted in pyproject.toml for remaining pandas-stubs false-positives)*
*Context: Full codebase review for production readiness — decades of daily data, AI-written strategies*

**After completion items will be deleted and can be recovered from git commit history.**

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
- Correctness bugs (DataFrame mutation, ignored parameter)
- AI bloat (empty context manager, dead code)
- Missing features for production use (specific lot identification, portfolio.total_value)
- Examples not testable

---

## P0 — Performance: Will break at scale

### P0-2: Replace transaction `pd.concat` with pre-allocated buffer
**File:** `pyfolium/core.py:492-496`
**Problem:** Every `_register_transaction` call does `pd.concat` which copies the entire
transaction history. O(n) per trade, O(n²) total.
**Fix:**
- Add `trade_fraction` parameter to Portfolio.__init__ (default 0.10)
- Pre-allocate: `estimated_rows = n_periods * n_assets * trade_fraction`
- Use write cursor: `self._txn_buffer.iloc[self._txn_cursor] = kwargs`
- When buffer fills, grow by `estimated_rows` (amortized O(1))
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
**Design doc update:** Update `DESIGN.md` "Tax lot tracking" section once implemented.

---

## P1 — Correctness bugs

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

### P4-4: Audit `examples/backtest_runner_example.py` for correctness
**File:** `examples/backtest_runner_example.py`
**Problem:** Flagged during PR review as potentially unreliable AI-generated code.
Needs verification that all 7 examples actually run successfully and produce
correct results — not just plausible-looking code that compiles.
**Fix:** Run the file end-to-end, fix any failures, remove Example 7 (context manager —
see P2-4). Update all examples to use the new strategy-owns-start-conditions pattern
once that's implemented.

---

## Additional notes from review

### AssetUniverse "immutable" documentation lie
**File:** `pyfolium/core.py:405` (clone docstring)
Comment says "Shared reference (immutable)" but AssetUniverse has `add_asset()`.
**Decision needed:** Either make it actually immutable (freeze after Portfolio init)
or fix the comment. For production, freezing is safer.

### Strategy `step()` returns nothing
**File:** `pyfolium/strategy.py:78-81`
Consider having `step()` return the trades list or a StepResult for introspection.
Low priority — strategies can inspect `trades_df`.

### Verbosity / observability model for different consumers
**Files:** `pyfolium/simulation.py`, `pyfolium/strategy.py`
**Problem:** The only output mode is tqdm (progress bar for human terminals). This doesn't
serve the three real consumers:

1. **Human at terminal**: Wants progress bar + final summary. Current tqdm works.
2. **LLM writing strategies**: Needs structured feedback — did trades execute? What failed?
   What's my portfolio value? tqdm is noise. Silent ValueError swallowing (P2-6) hides the
   signal the LLM actually needs.
3. **Batch/CI runner**: Wants zero output on success, full diagnostics on failure.

**Design:** Replace boolean `progress` with a verbosity/output enum:
```python
class OutputMode(str, Enum):
    SILENT = "silent"      # No output. Errors in result object only.
    SUMMARY = "summary"    # One-line summary at end (CI/batch).
    PROGRESS = "progress"  # tqdm bar (human terminal).
    STRUCTURED = "structured"  # Per-period structured log (LLM/programmatic).
```

`STRUCTURED` mode would yield/log per-period dicts:
```python
{
    "period": "2024-01-15",
    "trades_attempted": 3,
    "trades_executed": 2,
    "trades_failed": [{"symbol": "AAPL", "qty": 100, "reason": "insufficient cash"}],
    "portfolio_value": 152340.50,
    "cash": 12340.50,
}
```

This replaces both P2-6 (trade failure warnings become structured data instead of
`warnings.warn`) and the tqdm logic. It also makes BacktestResult more useful — the
structured log becomes part of the result, queryable as a DataFrame.

**Interaction with hooks:** The existing hook system (`period_start`, `period_end`) overlaps
with this. Consider whether hooks should be the mechanism for structured output (hook that
accumulates structured data) or whether structured output should be built-in and hooks
remain for custom side effects only. Built-in is cleaner — hooks are user extension points,
not the primary observability mechanism.

**Implementation order:** After P2-6 (trade failure visibility) and P1-4 (error recovery),
since this subsumes both.

### Logging architecture: replace `.errors` with `.log`
**Files:** `pyfolium/simulation.py` (BacktestRunner, BacktestResult)
**Problem:** BacktestRunner has an `_errors` list of `(period, exception)` tuples. This is
too narrow — it only captures exceptions, not warnings, trade failures, or general diagnostics.
There's no structured way to inspect what happened during a backtest beyond the raw
transaction log.

**Design:**
Replace `_errors` / `errors` with a `log` attribute that captures structured entries:

```python
@dataclass
class LogEntry:
    severity: str       # "DEBUG", "INFO", "WARNING", "ERROR"
    period: pd.Period   # simulation period when event occurred
    message: str        # human-readable description
    data: dict | None   # optional structured data (trade details, etc.)
```

Key properties:
- **Terminal output**: both wall-clock timestamp AND period/period timestamp on every line.
  Example: `[14:32:05 | 2024-03-15] WARNING: Trade failed: AAPL qty=100 — price is NaN`
- **Result data structure**: period numbers/timestamps, no wall-clock (irrelevant after the
  fact). The log becomes a queryable DataFrame in `BacktestResult`.
- **Standard severity levels**: DEBUG (trade details), INFO (period summaries), WARNING
  (failed trades, negative cash), ERROR (exceptions caught by the runner).
- **Subsumes current patterns**: `warnings.warn()` calls become log entries. `_errors` list
  becomes `log.query("severity == 'ERROR'")`. tqdm progress can read from the log stream.
- **Interaction with OutputMode/Verbosity**: The Verbosity enum (SILENT, SUMMARY, PROGRESS,
  STRUCTURED) controls *what gets printed to terminal*. The log always captures everything
  regardless of verbosity — it's the complete record, print settings are just filters.

**Depends on:** P1-4 (error recovery design decision) — the logging system needs to know
what severity to assign to recovered vs fatal errors.
**Design doc update:** Consider adding a "Observability" section to `DESIGN.md` once implemented.

### `collect_income` recomputes `earliest_long_term_period` inside loop
**File:** `pyfolium/core.py:582-585`
Move computation outside the `for symbol in symbols` loop.
Minor optimization but easy fix.

### Tax/fee config extensibility (template pattern)
**Files:** `pyfolium/core.py` (TaxConfig, FeeConfig, Portfolio.sell_asset, Portfolio.collect_income)
**Problem:** TaxConfig is purely declarative — rates and a strategy name string. All tax
calculation logic (lot selection, gain classification, withholding) is hardcoded in Portfolio's
sell and income paths. Users cannot swap in custom tax rules (wash sales, jurisdiction-specific
logic) without modifying Portfolio itself.

FeeConfig is better — it owns `calculate_fee()` — but still tightly coupled.

**Design intent:** Configs are templates and reasonable defaults, not exhaustive implementations.
Users should be able to subclass or replace them for their jurisdiction.

**Fix (phased):**
1. **Phase 1:** Extract tax calculation into methods on TaxConfig:
   - `classify_gain(purchase_period, sale_period) → "short_term" | "long_term"`
   - `calculate_tax(short_term_gains, long_term_gains) → float`
   - `select_lots(lots, strategy) → ordered_lots` (subsumes FIFO/LIFO + specific lot ID)
2. **Phase 2:** Portfolio calls config methods instead of implementing tax math directly.
   Default TaxConfig keeps today's behavior. Subclasses override for wash sales, etc.
3. **Phase 3:** Same pattern for FeeConfig if needed (tiered commissions, etc.)

**Depends on:** P0-3 (tax lot data structure) for the lot selection interface.
**Design doc:** See `DESIGN.md` "Configs as templates" section.

### Strategy owns start conditions (initial cash + start period)
**Files:** `pyfolium/strategy.py` (BaseStrategy), `pyfolium/simulation.py` (BacktestRunner)
**Problem:** Every user must write 4 lines of boilerplate to seed initial cash:
```python
portfolio.collect_income()   # no-op, just satisfies state machine
portfolio.move_cash(50000)
portfolio.update_history()
portfolio.advance_period()
```
This ceremony appears in the README, every example, and the clone() docstring. It's the
first thing every new user encounters, and it's confusing.

**Design principle:** Execution logic — including when to start investing and how much capital
to deploy — belongs to the **strategy**, not to manual user ceremony. Cash must still be a
transaction (it appears in the transaction log at the correct period).

**Fix:**
1. **BaseStrategy.__init__** gains `initial_cash: float | None = None` and
   `start_period: pd.Period | None = None` parameters, stored alongside existing `parameters`.
2. **BacktestRunner** reads `strategy.initial_cash` and `strategy.start_period`:
   - If `start_period` is set, runner fast-forwards to that period.
   - Fast-forward for empty portfolios (no holdings, no cash) should be a true index skip —
     just advance `_current_period_idx` without running collect_income/update_history for
     each intermediate period. No state to preserve means no ceremony needed.
   - On the first strategy period, runner deposits `initial_cash` via `move_cash()` before
     calling `strategy.step()`.
3. **Result:** The README example becomes:
   ```python
   portfolio = Portfolio(universe)
   strategy = BuyAndHold(portfolio, initial_cash=50000)
   result = BacktestRunner(portfolio, strategy).run()
   ```

**Warmup data use case:** A strategy needing 200 days of moving-average history sets
`start_period` to day 201. The runner fast-forwards there (no ceremony for empty periods),
deposits cash, and begins. The strategy has access to the full AssetUniverse price history
for lookback calculations.

**Depends on:** Nothing — can be implemented independently.
**Also updates:** README example, all examples in `examples/backtest_runner_example.py`,
clone() docstring in `core.py`.
**Design doc update:** `DESIGN.md` "Strategy owns its start conditions" section — already updated.

---

## Implementation order

Recommended sequence:

4. **Strategy start conditions** — `initial_cash` + `start_period` on BaseStrategy, runner sync. High user-impact, changes the primary API surface.
5. **P2-5** (total_value property) — Small, used by everything downstream
6. **P2-6** (trade failure warnings) — Small, important for AI strategies
7. **P2-7, P2-8, P2-9** (data.py cleanup) — Grouped, moderate effort
9. **P0-2** (transaction pre-allocation) — Core change, needs careful testing
10. **P0-3 + P1-5** (lot tracker + sell_lot) — Feature addition + performance
11. **Tax/fee extensibility phase 1** — Extract tax methods from Portfolio into TaxConfig. Depends on P0-3.
12. **P1-4** (error recovery) — Design decision needed first
13. **Logging architecture** — Replace `.errors` with `.log`, structured entries. Depends on P1-4.
14. **Verbosity/OutputMode** — Terminal filtering over the log. Subsumes P2-6 and tqdm logic.
15. **P2-4** (remove context manager) — Affects examples and tests
16. **P4-*** (testable examples, audit existing) — After all API changes settle

Each step should be a single reviewable commit.
