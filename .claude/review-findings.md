# Architecture Review Findings & Action Plan

*Created: 2026-02-22 | Session: review-architecture-changes-GWIjK*
*Context: Full codebase review for production readiness — decades of daily data, AI-written strategies*

**After completion items will be deleted and can be recovered from git commit history.**

---

## P0 — Performance: Will break at scale

### ~~P0-2: Replace transaction `pd.concat` with pre-allocated buffer~~ ✓ DONE
### ~~P0-3: Tax lot tracker as first-class data structure~~ ✓ DONE

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

### ~~Verbosity / observability model for different consumers~~ ✓ DONE
Implemented as `OutputMode(StrEnum)` in `pyfolium/logging.py` with `SILENT`, `SUMMARY`,
`PROGRESS`. `STRUCTURED` was dropped — `result.log_df` serves the programmatic/LLM use case
without a separate output mode. `RICH` mode (multi-bar for parallel optimization) planned as
Phase 3. See `.claude/logging-spec.md` and `DESIGN.md` "Observability" section.

### ~~Logging architecture~~ ✓ DONE
Implemented in `c97e900`. `BacktestRunner._log: list[LogEntry]` with structured entries.
`BacktestResult` exposes `.log`, `.log_df`, `.errors`, `.warnings`, `.success`.
`BaseStrategy.log()` + drain pattern for strategy-authored entries.
See `.claude/logging-spec.md` for full design rationale.

### ~~`collect_income` recomputes `earliest_long_term_period` inside loop~~ ✓ DONE (P0-2/P0-3 refactor)

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
3. ~~**Phase 3:** Same pattern for FeeConfig if needed (tiered commissions, etc.)~~ ✓ DONE

**Depends on:** P0-3 (tax lot data structure) for the lot selection interface.
**Design doc:** See `DESIGN.md` "Configs as templates" section.

---

## Implementation order

Recommended sequence:

6. ~~**P2-6** (trade failure warnings)~~ ✓ DONE — Subsumed by structured logging; summary WARNING emitted at backtest end when `trades_df` has failures.
7. ~~**P2-7, P2-8, P2-9** (data.py cleanup)~~ ✓ DONE
9. ~~**P0-2** (transaction pre-allocation)~~ ✓ DONE
10. ~~**P0-3**~~ ✓ DONE — **P1-5** (sell_lot) — Feature addition, depends on P0-3
11. ~~**Tax/fee extensibility phase 1** — Extract tax methods from Portfolio into TaxConfig. Depends on P0-3.~~ ✓ DONE
12. ~~**P1-4** (error recovery)~~ ✓ DONE
13. ~~**Logging architecture**~~ ✓ DONE
14. ~~**Verbosity/OutputMode**~~ ✓ DONE
16. **P4-*** (testable examples, audit existing) — After all API changes settle

Each step should be a single reviewable commit.
