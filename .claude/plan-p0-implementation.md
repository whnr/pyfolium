# P0-1 Implementation Plan: Replace `_update_future_holdings` with single-row write

## Recommendation: P0-1 only (P0-2 as a separate follow-up)

### Why P0-2 should NOT be bundled with P0-1

P0-2 (transaction buffer pre-allocation) has a hidden complexity: `sell_asset()` and
`collect_income()` **mutate existing transaction rows** in-place:

```python
# sell_asset, lines 762-764:
self.transactions.loc[lot, "lot_quantity_remaining"] = 0
self.transactions.loc[lot, "lot_quantity_remaining"] -= lot_quantity_sold
```

Any pre-allocated buffer approach must support both O(1) append AND random-access mutation
of existing rows. The `transactions` property (returning `self._txn_buffer.iloc[:cursor]`)
may return a copy vs view depending on pandas version, which would silently break the
mutation path. This requires careful design around:
- Whether to expose `_txn_buffer` directly for mutations
- Changing `sell_asset`/`collect_income` to use the buffer instead of the property
- Index stability between the buffer and the filtered views used in lot selection

P0-1 is clean, self-contained, and independently valuable. Bundling P0-2 doubles the
review surface and debugging complexity for no coupling benefit.

---

## P0-1 Change Summary

**Goal:** Eliminate O(n²) holdings writes. Currently every `buy_asset`/`sell_asset` writes
to ALL future rows in the holdings DataFrame. With 5,200 periods and 3 trades/day,
that's ~81M row-writes total. After the fix: O(1) per trade, O(assets) per advance.

**Behavioral change:** Future periods (beyond `current_period`) will show 0 instead of
forward-filled values. This is more correct — you shouldn't query future state during a
backtest. The `holdings.loc[current_period]` view is unchanged.

---

## Step-by-step changes

### Step 1: Modify `buy_asset()` — core.py:683

Replace:
```python
self._update_future_holdings(symbol, quantity)
```
With:
```python
self.holdings.loc[self.current_period, symbol] += quantity
```

### Step 2: Modify `sell_asset()` — core.py:796

Replace:
```python
self._update_future_holdings(symbol, -quantity)
```
With:
```python
self.holdings.loc[self.current_period, symbol] -= quantity
```

### Step 3: Modify `advance_period()` — core.py:490-505

After advancing `_current_period_idx` and updating `current_period`, carry forward
holdings from the previous period:

```python
def advance_period(self) -> None:
    if self._states[self.current_period] != PortfolioState.DONE:
        raise RuntimeError("Last period was not in the DONE state.")
    if self._current_period_idx + 1 >= len(self.history.index):
        raise StopIteration("End of history reached")
    previous_period = self.current_period
    self._current_period_idx += 1
    self.current_period = self.history.index[self._current_period_idx]
    # Carry forward holdings from the completed period
    self.holdings.loc[self.current_period] = self.holdings.loc[previous_period]
```

This is O(assets) per advance — trivial even with 500 assets.

### Step 4: Delete `_update_future_holdings()` — core.py:424-438

Remove the entire method. It has no other callers.

### Step 5: Update tests

**Remove 3 tests** that directly test the deleted method:
- `test_update_future_holdings_change_whole_future` (line ~175)
- `test_update_future_holdings_keep_past_untouched` (line ~186)
- `test_update_future_holdings_reduce_holdings` (line ~198)

These tests validate the old forward-fill behavior which is being intentionally removed.

**Verify existing tests still pass** — the following access patterns are safe:
- `portfolio.holdings.iloc[0]["TEST"]` in `test_buy_asset` — accesses current period ✓
- `portfolio.holdings.iloc[1]["A"]` in `test_sell_asset` — accesses period 1 AFTER
  `advance_period()` was called (so it's the current period at that point) ✓
- All other holdings accesses go through `holdings.loc[current_period]` ✓

**Add 2 new tests:**

1. `test_advance_period_carries_forward_holdings` — buy assets in period 0, advance,
   verify period 1 has the same holdings without any explicit update.

2. `test_buy_sell_only_modifies_current_period` — buy in period 0, verify period 1+
   still shows 0. Advance, verify period 1 now shows the carried-forward value.

### Step 6: Run full test suite

`uv run pytest` — verify all tests pass, no regressions.

### Step 7: Run linter/formatter

`uv run ruff check --fix . && uv run ruff format .`

---

## Risk assessment

**Low risk.** The change is mechanically simple:
- 2 call sites changed (buy/sell)
- 1 method gains 2 lines (advance_period)
- 1 method deleted
- External API unchanged — `holdings.loc[current_period]` returns identical values

**Edge case to verify:** The BacktestRunner's `__init__` fast-forward loop calls
`advance_period()` to skip to `start_period`. After this change, it will carry forward
zero holdings each time (since no trades happen during skip). This is correct — empty
portfolios should have zero holdings everywhere.

**Edge case to verify:** `Portfolio.clone()` deep-copies `self.holdings`. After the change,
the cloned holdings will only have meaningful values up to `current_period` (future periods
are 0). This is correct — the clone picks up exactly where the original left off.
