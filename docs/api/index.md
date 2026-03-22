# API Reference

Pyfolium is organized into five focused modules:

| Module | Purpose |
|---|---|
| [`pyfolium.core`](core.md) | Asset, Portfolio, tax lots, tax and fee configuration |
| [`pyfolium.strategy`](strategy.md) | `BaseStrategy` abstract class for trading logic |
| [`pyfolium.simulation`](simulation.md) | `BacktestRunner` orchestration and `BacktestResult` |
| [`pyfolium.data`](data.md) | CSV and DataFrame loaders |
| [`pyfolium.logging`](logging.md) | Severity levels, log entries, output modes |

All public symbols are re-exported from the top-level `pyfolium` package, so you
can import directly:

```python
from pyfolium import Asset, Portfolio, BacktestRunner, BaseStrategy
```
