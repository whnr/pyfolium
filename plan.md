# P0-2 + P0-3 Refactor: Transaction Buffer + TaxLot Dataclass

## Goal

Replace the O(n²) `pd.concat` transaction appending and full-DataFrame tax lot scanning
with an O(1)-amortized list-of-dicts buffer and a first-class `TaxLot` dataclass. Add a
synthetic benchmark (100 assets, 50 years daily, taxes+fees) to measure before/after.

## Relationship to Tax/Fee Extensibility Roadmap

This refactor is the **prerequisite** for the Tax/Fee config extensibility pattern
described in `review-findings.md:181-201`. The dependency chain is:

1. **P0-3 (this plan)**: `TaxLot` dataclass — lots become first-class objects
2. **Phase 1**: Extract tax methods from Portfolio into TaxConfig:
   - `TaxConfig.select_lots(lots: list[TaxLot]) → list[TaxLot]` (subsumes FIFO/LIFO)
   - `TaxConfig.classify_gain(purchase_period, sale_period) → "short_term" | "long_term"`
   - `TaxConfig.calculate_tax(short_term_gains, long_term_gains) → float`
3. **Phase 2**: Portfolio delegates to config methods instead of hardcoding tax math
4. **P1-5**: `sell_lot()` for specific lot identification (tax-loss harvesting)

The `TaxLot` dataclass is designed to carry all information a future
`TaxConfig.select_lots()` needs: `symbol`, `period`, `cost_basis_per_share`,
`quantity_remaining`. No redesign needed when Phase 1 lands.

---

## Design Decisions (confirmed with user)

1. **Buffer strategy**: List-of-dicts + lazy DataFrame property
2. **Lot tracking**: Separate `TaxLot` dataclass (full P0-3 scope)
3. **TaxLot location**: In `core.py` alongside Portfolio
4. **Benchmark location**: `examples/` directory
5. **Benchmark config**: With taxes and fees (exercises hot paths)

---

## Step 0: Create branch and write benchmark (BEFORE refactor)

### 0a. Create/checkout branch `claude/plan-refactor-benchmark-xJiCZ`

### 0b. Create `examples/benchmark.py`

Synthetic benchmark script:
- **100 assets**, daily data, **50 years** (~18,262 periods)
- **Prices**: Geometric Brownian Motion per asset
  - `μ = 0.08/252` (8% annualized drift)
  - `σ = 0.20/√252` (~20% annualized volatility)
  - Starting prices: uniform random $20-$200
  - `S(t+1) = S(t) * exp((μ - σ²/2) + σ * Z)` where Z ~ N(0,1)
- **Income**: quarterly dividends (~2% yield annualized), so every ~63 trading days
  each asset pays `price * 0.02 / 4`
- **Tax config**: short_term_rate=0.30, long_term_rate=0.15, withhold_tax=True, FIFO
- **Fee config**: fixed=1.0, percentage=0.001, min=1.0, max=20.0
- **Strategy**: `RandomTraderStrategy`
  - Period 1: fully invest ~equal-weight across all 100 assets
  - Every ~21 periods (monthly): pick 10 random assets, sell 10% of holdings,
    pick 10 different random assets, buy with proceeds
  - Uses `np.random.default_rng(42)` for reproducibility
- **Measurement**: `time.perf_counter()` for wall clock, print periods/second
- Script outputs: setup time, simulation time, total transactions, periods/sec

### 0c. Run benchmark, record baseline numbers

Commit: "Add synthetic benchmark for P0-2 profiling (pre-refactor baseline)"

---

## Step 1: Add `TaxLot` dataclass to `core.py`

```python
@dataclass(slots=True)
class TaxLot:
    """A single tax lot created by a purchase transaction.

    Attributes:
        symbol: Asset symbol this lot belongs to.
        period: Period when the lot was created (purchase date).
        quantity: Original quantity purchased.
        quantity_remaining: Quantity not yet sold. Decremented by sell_asset().
        cost_basis_per_share: Per-share cost including fees.
        txn_index: Index into Portfolio._txn_buffer for this lot's buy transaction.
    """
    symbol: str
    period: pd.Period
    quantity: float
    quantity_remaining: float
    cost_basis_per_share: float
    txn_index: int

    @property
    def is_open(self) -> bool:
        return self.quantity_remaining > 0
```

Add `TaxLot` to `__init__.py` exports and `__all__`.

---

## Step 2: Refactor `Portfolio` internals in `core.py`

### 2a. New internal storage in `__init__`

Replace:
```python
self.transactions = pd.DataFrame(columns=...)
self.transactions = self.transactions.astype(...)
```

With:
```python
# Transaction buffer: list of dicts, O(1) append
self._txn_buffer: list[dict] = []
# Period index: period → list of indices into _txn_buffer
self._txn_period_index: dict[pd.Period, list[int]] = {}
# Tax lots: symbol → list of TaxLot (open and closed)
self._tax_lots: dict[str, list[TaxLot]] = {}
# Dirty flag for lazy DataFrame rebuild
self._txn_df_cache: pd.DataFrame | None = None
```

### 2b. `transactions` becomes a property

```python
@property
def transactions(self) -> pd.DataFrame:
    """Transaction log as a DataFrame (built lazily from internal buffer)."""
    if self._txn_df_cache is None:
        if not self._txn_buffer:
            # Return empty DataFrame with correct schema
            df = pd.DataFrame(columns=list(Portfolio.transaction_columns.keys()))
            df = df.astype(Portfolio.transaction_columns)
            df["period"] = df["period"].astype(
                pd.PeriodDtype(freq=self.asset_universe.data_frequency)
            )
            self._txn_df_cache = df
        else:
            self._txn_df_cache = pd.DataFrame(self._txn_buffer)
    return self._txn_df_cache
```

### 2c. Rewrite `_register_transaction()`

Replace `pd.concat` with:
```python
def _register_transaction(self, **kwargs) -> int:
    """Register a transaction. Returns the buffer index."""
    # ... same validation as before ...
    transaction["period"] = self.current_period
    idx = len(self._txn_buffer)
    self._txn_buffer.append(transaction)

    # Update period index
    self._txn_period_index.setdefault(self.current_period, []).append(idx)

    # Invalidate cache
    self._txn_df_cache = None

    return idx
```

### 2d. Rewrite `update_history()` to use period index

Replace:
```python
period_transactions = self.transactions[
    self.transactions["period"] == self.current_period
]
```

With:
```python
indices = self._txn_period_index.get(self.current_period, [])
long_term_gains = sum(
    self._txn_buffer[i].get("long_term_gains", 0) or 0 for i in indices
)
short_term_gains = sum(
    self._txn_buffer[i].get("short_term_gains", 0) or 0 for i in indices
)
taxes_paid = sum(
    self._txn_buffer[i].get("tax_paid", 0) or 0 for i in indices
)
```

No DataFrame filtering needed — O(k) where k = transactions this period.

### 2e. Rewrite `buy_asset()` to create TaxLot

After `_register_transaction(...)`, add:
```python
idx = self._register_transaction(...)
lot = TaxLot(
    symbol=symbol,
    period=self.current_period,
    quantity=quantity,
    quantity_remaining=quantity,
    cost_basis_per_share=cost_basis_per_share,
    txn_index=idx,
)
self._tax_lots.setdefault(symbol, []).append(lot)
```

### 2f. Rewrite `sell_asset()` to use TaxLot list

Replace the DataFrame-filtering approach:
```python
tax_lots = self.transactions[
    (self.transactions["type"] == "buy")
    & (self.transactions["symbol"] == symbol)
    & (self.transactions["lot_quantity_remaining"] > 0)
    & (self.transactions["period"] <= self.current_period)
]
```

With direct TaxLot iteration:
```python
lots = self._tax_lots.get(symbol, [])
open_lots = [lot for lot in lots if lot.is_open]

if self.tax_config.tax_strategy == "FIFO":
    open_lots.sort(key=lambda lot: lot.period)
elif self.tax_config.tax_strategy == "LIFO":
    open_lots.sort(key=lambda lot: lot.period, reverse=True)

current_holding_quantity = sum(lot.quantity_remaining for lot in open_lots)
```

And replace the lot consumption loop:
```python
for lot in open_lots:
    lot_quantity_sold = min(quantity_to_sell, lot.quantity_remaining)
    lot_gains = lot_quantity_sold * (cost_basis_per_share - lot.cost_basis_per_share)

    if lot.period <= earliest_long_term_period:
        long_term_gains += lot_gains
    else:
        short_term_gains += lot_gains

    lot.quantity_remaining -= lot_quantity_sold
    # Also update the buffer dict for consistency
    self._txn_buffer[lot.txn_index]["lot_quantity_remaining"] = lot.quantity_remaining
    self._txn_df_cache = None  # invalidate

    quantity_to_sell -= lot_quantity_sold
    if quantity_to_sell <= 0:
        break
```

### 2g. Rewrite `collect_income()` to use TaxLot list

Replace the transaction DataFrame filtering with:
```python
for symbol in symbols:
    income = income_this_period[symbol]
    lots = self._tax_lots.get(symbol, [])
    open_lots = [lot for lot in lots if lot.is_open]

    total_quantity = sum(lot.quantity_remaining for lot in open_lots)
    long_term_quantity = sum(
        lot.quantity_remaining for lot in open_lots
        if lot.period <= earliest_long_term_period
    )
    short_term_quantity = total_quantity - long_term_quantity
```

Also hoist `earliest_long_term_period` computation OUTSIDE the symbol loop (it's the same for all symbols in a period — this is the minor optimization noted in review-findings).

### 2h. Rewrite `clone()` to copy new structures

Replace:
```python
cloned.transactions = self.transactions.copy(deep=True)
```

With:
```python
from copy import deepcopy
cloned._txn_buffer = deepcopy(self._txn_buffer)
cloned._txn_period_index = deepcopy(self._txn_period_index)
cloned._tax_lots = deepcopy(self._tax_lots)
cloned._txn_df_cache = None  # will be rebuilt on access
```

### 2i. Add public `open_lots` property

```python
@property
def open_lots(self) -> dict[str, list[TaxLot]]:
    """Open tax lots by symbol. Read-only view for strategies."""
    return {
        symbol: [lot for lot in lots if lot.is_open]
        for symbol, lots in self._tax_lots.items()
    }
```

---

## Step 3: Fix tests

### Tests that access `portfolio.transactions` directly
These should mostly work since `transactions` is now a property returning a DataFrame.
Key tests to watch:

- `tests/core/test_portfolio_clone.py:74` — `assert cloned.transactions is not portfolio.transactions`
  This will FAIL because the property rebuilds each time. Change to content equality check.
- Any test that mutates `portfolio.transactions` directly will fail (the property returns
  a new DataFrame each time). Audit and fix.

### New tests to add
- Test `TaxLot` dataclass construction and `is_open` property
- Test that `_txn_buffer` grows correctly
- Test that `_txn_period_index` maps correctly
- Test that `_tax_lots` tracks lots through buy→sell lifecycle
- Test that `clone()` produces independent lot state
- Test that `transactions` property returns correct DataFrame matching old behavior

---

## Step 4: Run benchmark AFTER refactor

Run the same `examples/benchmark.py` script, compare numbers.

Commit: "Refactor transaction storage: list-of-dicts buffer + TaxLot dataclass (P0-2 + P0-3)"

---

## Step 5: Update documentation

### 5a. `CLAUDE.md`
- Update Architecture → Key Components → Portfolio section to describe new internals
- Add TaxLot to component list
- Update "Current State" section

### 5b. `DESIGN.md`
- Update "Tax lot tracking" section to describe TaxLot dataclass
- Add section on transaction buffer design and performance characteristics
- Update "Portfolio: Cash + Holdings + History" to mention open_lots

### 5c. `README.md`
- Add `TaxLot` to exports list in Project Structure
- Update Tax Lot Tracking section to mention `portfolio.open_lots`

### 5d. `__init__.py`
- Export `TaxLot`

### 5e. `.claude/review-findings.md`
- Mark P0-2 as DONE
- Mark P0-3 as DONE
- Update implementation order

Commit: "Update documentation for P0-2/P0-3 refactor"

---

## Step 6: Final validation

1. `uv run pytest` — all tests pass
2. `uv run ruff check .` — no lint errors
3. `uv run ruff format .` — formatted
4. `uv run pyright pyfolium/` — no type errors
5. `uv run python examples/benchmark.py` — benchmark runs, print comparison
6. `uv run python examples/backtest_runner_example.py` — existing examples still work

---

## Risk Assessment

**Low risk**: The external API is unchanged. `portfolio.transactions` still returns a DataFrame.
The only breaking change is that `portfolio.transactions` is now a property (not a mutable attribute),
so code that does `portfolio.transactions.loc[i, col] = val` will silently fail to persist
changes. This is only done internally in `sell_asset()` (lot_quantity_remaining update),
which we're rewriting to use TaxLot directly.

**Medium risk**: The clone test that checks `cloned.transactions is not portfolio.transactions`
will need updating since the property always builds a new DataFrame.

**New public API surface**:
- `TaxLot` dataclass (new export)
- `portfolio.open_lots` property (new)
- `portfolio.transactions` changes from attribute to property (transparent to readers)
