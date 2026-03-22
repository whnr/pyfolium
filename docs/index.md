# Pyfolium

**Hätte hätte Fahrradkette** — *If only, if only...*

Pyfolium is an income-aware, tax-aware, and fee-aware portfolio backtesting
engine for Python. It simulates historical portfolio evolution period-by-period,
enforces correct transaction ordering, and returns clean pandas DataFrames that
plug into whichever analytics or visualization libraries you prefer.

## Installation

=== "pip"

    ```bash
    pip install pyfolium
    ```

=== "uv"

    ```bash
    uv add pyfolium
    ```

## Quick start

```python
import pandas as pd
from pyfolium import Asset, AssetUniverse, Portfolio, BacktestRunner, BaseStrategy

# 1. Create universe and assets
universe = AssetUniverse(data_frequency="M")
stock = Asset(
    symbol="Stock",
    data=pd.DataFrame(
        {"price": range(100, 113)},
        index=pd.period_range("2020-01", periods=13, freq="M"),
    ),
    universe=universe,
)

# 2. Set up portfolio
portfolio = Portfolio(asset_universe=universe, starting_cash=10_000)

# 3. Define a strategy
class BuyAndHold(BaseStrategy):
    def get_trades(self) -> list[tuple[str, int]]:
        if self.portfolio.current_period == self.portfolio.start_period:
            return [("Stock", 50)]
        return []

# 4. Run backtest
strategy = BuyAndHold(portfolio=portfolio, parameters={"name": "buy-and-hold"})
result = BacktestRunner(strategy=strategy, asset_universe=universe).run()

print(result.portfolio.history)
```

## Design philosophy

Pyfolium is a **backtesting engine**, not a full-featured analytics platform.

| What it does | What it doesn't do |
|---|---|
| Income-aware, tax-aware, fee-aware backtesting | Data fetching |
| Enforced transaction ordering via state machine | Performance analytics |
| Extensible strategy framework | Visualization |
| Clean pandas DataFrame outputs | Portfolio optimization |

Pyfolium outputs `portfolio.history` and `portfolio.transactions` as DataFrames —
bring your own analytics and plotting.

## Next steps

Explore the [API Reference](api/index.md) to learn about each module.
