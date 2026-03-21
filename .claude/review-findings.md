# Architecture Review Findings & Action Plan

*Created: 2026-02-22 | Session: review-architecture-changes-GWIjK*
*Context: Full codebase review for production readiness — decades of daily data, AI-written strategies*

**After completion items will be deleted and can be recovered from git commit history.**

## Additional notes from review

### Strategy `step()` returns nothing
**File:** `pyfolium/strategy.py:78-81`
Consider having `step()` return the trades list or a StepResult for introspection.
Low priority — strategies can inspect `trades_df`.

### Tax/fee config extensibility (template pattern)

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
16. ~~**P4-*** (testable examples, audit existing) — After all API changes settle~~ ✓ DONE

Each step should be a single reviewable commit.
