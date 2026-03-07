# Architecture Review Findings & Action Plan

*Created: 2026-02-22 | Session: review-architecture-changes-GWIjK*
*Context: Full codebase review for production readiness — decades of daily data, AI-written strategies*

**After completion items will be deleted and can be recovered from git commit history.**

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
**Strategy interface:** New `portfolio.open_lots["Stock"]` for fast lot access.
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

## P4 — Make examples testable

### P4-1: Refactor examples to return values
**File:** `examples/backtest_runner_example.py`
**Problem:** Examples use print(), can't be imported and tested.
**Fix:**
- Each `example_*()` function returns its result (BacktestResult or relevant values)
- Keep print() for human readability but add return statements

### P4-2: Add test file for examples
**File:** `tests/test_examples.py` (new)

### P4-3: Missing `__init__.py` or pytest path config for examples
**Check:** Ensure examples directory is importable from tests.
May need `examples/__init__.py` or pytest `pythonpath` config update.

### P4-4: Audit `examples/backtest_runner_example.py` for correctness
**File:** `examples/backtest_runner_example.py`
**Problem:** Flagged during PR review as potentially unreliable AI-generated code.
Needs verification that all examples actually run successfully and produce
correct results.

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

---

## Implementation order

Recommended sequence:

6. ~~**P2-6** (trade failure warnings)~~ ✓ DONE
7. ~~**P2-7, P2-8, P2-9** (data.py cleanup)~~ ✓ DONE
9. **P0-2** (transaction pre-allocation) — Core change, needs careful testing
10. **P0-3 + P1-5** (lot tracker + sell_lot) — Feature addition + performance
11. **Tax/fee extensibility phase 1** — Extract tax methods from Portfolio into TaxConfig. Depends on P0-3.
12. ~~**P1-4** (error recovery)~~ ✓ DONE
13. ~~**Logging architecture**~~ ✓ DONE
14. ~~**Verbosity/OutputMode**~~ ✓ DONE
16. **P4-*** (testable examples, audit existing) — After all API changes settle

Each step should be a single reviewable commit.
