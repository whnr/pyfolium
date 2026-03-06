# Architecture Review Findings & Action Plan

*Created: 2026-02-22 | Session: review-architecture-changes-GWIjK*
*Updated: 2026-02-24 | Data gaps handling implemented + refactored per PR review (universe matrices as sole runtime data interface, removed get_price_at/get_income_at)*
*Updated: 2026-02-28 | Rebased onto dev; mypy → pyright (cast() for reportAssignmentType, warnings demoted in pyproject.toml for remaining pandas-stubs false-positives)*
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
- ~~AI bloat (empty context manager, dead code)~~ ✓ DONE (`06b1920`)
- Missing features for production use (specific lot identification, ~~portfolio.total_value~~ ✓)
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

### ~~P2-6: Silent failure swallowing in `execute_trades`~~ ✓ DONE
Subsumed by structured logging (`c97e900`). `BacktestRunner` emits a summary WARNING
at backtest end when `trades_df` has `success=False` rows.

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
- ~~Remove Example 7 (empty context manager — see P2-4)~~ ✓ Old Example 7 removed; replaced with strategy logging demo.

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
Needs verification that all examples actually run successfully and produce
correct results — not just plausible-looking code that compiles.
**Fix:** Run the file end-to-end, fix any failures. ~~Remove old Example 7 (context manager)~~ ✓ Done.
~~Update all examples to use strategy-owns-start-conditions pattern~~ ✓ Done.
~~Update examples for OutputMode API~~ ✓ Done (`444c88d`).

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

### ~~Verbosity / observability model for different consumers~~ ✓ DONE
Implemented as `OutputMode(StrEnum)` in `pyfolium/logging.py` with `SILENT`, `SUMMARY`,
`PROGRESS`. `STRUCTURED` was dropped — `result.log_df` serves the programmatic/LLM use case
without a separate output mode. `RICH` mode (multi-bar for parallel optimization) planned as
Phase 3. See `.claude/logging-spec.md` and `DESIGN.md` "Observability" section.

### ~~Logging architecture: replace `.errors` with `.log`~~ ✓ DONE
Implemented in `c97e900`. `BacktestRunner._log: list[LogEntry]` replaces `_errors`.
`BacktestResult` exposes `.log`, `.log_df`, `.errors`, `.warnings`, `.success`.
`BaseStrategy.log()` + drain pattern for strategy-authored entries.
See `.claude/logging-spec.md` for full design rationale.

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

### ~~Strategy owns start conditions (initial cash + start period)~~ ✓ DONE
**Implemented in:** commit on branch `claude/add-strategy-start-conditions-yUnRc`

`BaseStrategy.__init__` now accepts `initial_cash: float | None = None` and
`start_period: pd.Period | None = None` as keyword-only parameters. `BacktestRunner` uses
three-way resolution for `start_period` (explicit runner arg > strategy.start_period >
portfolio.current_period) and injects `initial_cash` via `move_cash()` on the first period,
after `collect_income()` (TRANSACT state), before `strategy.step()`.

All examples updated to drop the 4-line boilerplate. 13 new tests added (5 in
`test_basestrategy.py`, 8 in `test_backtest_runner.py`).

---

## Implementation order

Recommended sequence:

6. ~~**P2-6** (trade failure warnings)~~ ✓ DONE — Subsumed by structured logging; summary WARNING emitted at backtest end when `trades_df` has failures.
7. **P2-7, P2-8, P2-9** (data.py cleanup) — Grouped, moderate effort
9. **P0-2** (transaction pre-allocation) — Core change, needs careful testing
10. **P0-3 + P1-5** (lot tracker + sell_lot) — Feature addition + performance
11. **Tax/fee extensibility phase 1** — Extract tax methods from Portfolio into TaxConfig. Depends on P0-3.
12. ~~**P1-4** (error recovery)~~ ✓ DONE — `strict` flag on `BacktestRunner`; lenient mode records errors in structured log and recovers.
13. ~~**Logging architecture**~~ ✓ DONE — `pyfolium/logging.py` with `Severity`, `LogEntry`, `OutputMode`; `BacktestRunner._log` + `_emit()`; `BacktestResult.log`/`log_df`/`errors`/`warnings`/`success`; `BaseStrategy.log()` + drain pattern.
14. ~~**Verbosity/OutputMode**~~ ✓ DONE — `OutputMode.SILENT`/`SUMMARY`/`PROGRESS` replaces `progress=True`. `RICH` mode planned (Phase 3, pending).
16. **P4-*** (testable examples, audit existing) — After all API changes settle

Each step should be a single reviewable commit.
