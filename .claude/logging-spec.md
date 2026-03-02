# Logging & Observability Specification

*Replaces: P2-6 (trade failure visibility) + `_errors` list + `warnings.warn()` calls + `progress` bool*
*Depends on: P1-4 (error recovery) — resolved.*

---

## Problem

BacktestRunner has three observability gaps:

1. **Unstructured error capture** — `_errors: list[tuple[pd.Period, Exception]]` has no severity, no structured data, and no filtering. `warnings.warn()` calls produce terminal noise that isn't captured in the result.

2. **No performance visibility** — no wall-clock timestamps anywhere. If a strategy gets slower over time (portfolio grows, more lots to scan), there's no way to identify which periods are slow.

3. **No strategy voice** — strategies have no way to record their reasoning. A rebalancing strategy can't say "allocation drifted 7%, rebalancing" in a place the user can inspect after the fact.

**P2-6 reframing:** `trades_df` already captures failed trades with `success=False` — that's the right place for trade-level data. The gap is *signaling*: a backtest can "succeed" while 90% of trades silently failed. The fix is a summary-level warning at backtest end, not per-trade log entries.

## Architecture

### New module: `pyfolium/logging.py`

Defines `Severity` and `LogEntry`. Lives in its own module to avoid circular imports (`strategy.py` and `simulation.py` both need these types).

**Not** the Python `logging` module. Each backtest run gets its own scoped log — no global handlers, no level configuration leaking between runs. Concurrency-safe by isolation (8 parallel backtests = 8 independent logs).

### `Severity(IntEnum)`

Four levels: `DEBUG(10)`, `INFO(20)`, `WARNING(30)`, `ERROR(40)`.

IntEnum enables `>=` comparisons for filtering. No CRITICAL — strict mode re-raises on ERROR, which is sufficient distinction.

### `LogEntry` (frozen dataclass, slots)

| Field | Type | Purpose |
|-------|------|---------|
| `severity` | `Severity` | Filtering and OutputMode thresholds |
| `timestamp` | `float` | Wall-clock time (`time.monotonic()`). Enables performance profiling: identify slow periods, strategies degrading over time. |
| `period` | `pd.Period` | Simulation period when event occurred |
| `source` | `str` | Component origin: `"runner"`, `"strategy"`, `"hook"` |
| `message` | `str` | Human-readable description |
| `data` | `dict \| None` | Structured context for programmatic inspection |

Frozen + slots: immutable records, memory-efficient for long backtests.

### Storage: `list[LogEntry]`, not DataFrame

The log is a `list[LogEntry]` internally — O(1) append, no DataFrame overhead. `BacktestResult.log_df` builds a DataFrame lazily on access for querying convenience. The list is the source of truth; the DataFrame is a view.

### Strategy log drain pattern

Strategies accumulate log entries in their own `_log: list[LogEntry]`. After each `step()`, the runner drains (extends + clears) the strategy's log into the runner's log. This preserves the current architecture: the strategy only knows about the portfolio, no circular dependency with the runner.

Strategies get a `log(severity, message, data=None)` convenience method they can call in `get_trades()` to record decisions:
- **INFO**: normal decisions ("rebalancing: AAPL weight drifted from 30% to 37%")
- **WARNING**: course corrections ("wanted to sell AAPL but insufficient holdings, skipping")

### OutputMode replaces `progress: bool`

`OutputMode(str, Enum)` with three values:

| Mode | Terminal output |
|------|----------------|
| `SILENT` | Nothing. Log captured in result only. |
| `SUMMARY` | One-line summary at end. |
| `PROGRESS` | tqdm bar + summary line at end. |

OutputMode controls what gets *printed*. The log captures everything regardless. `run()` signature: `run(*, output: OutputMode = OutputMode.SILENT)`.

## Severity mapping

What gets logged and at what level:

| Severity | Source | Event |
|----------|--------|-------|
| ERROR | runner | Exception during period execution |
| WARNING | runner | Lenient-mode recovery (period skipped) |
| WARNING | runner | Trade failures detected in `trades_df` (summary at backtest end) |
| WARNING | hook | Hook callback raised exception |
| INFO | runner | Backtest started / completed |
| INFO | strategy | Strategy decisions (user-authored via `self.log()`) |
| DEBUG | runner | Period lifecycle, initial cash injection |

**First implementation: ERROR + WARNING only.** INFO and DEBUG entries can be added later without API changes.

## BacktestResult changes

- `log: list[LogEntry]` — the complete structured log
- `log_df` (property) — lazy DataFrame view of the log
- `errors` (property) — `[e for e in log if e.severity >= ERROR]`
- `warnings` (property) — `[e for e in log if e.severity == WARNING]`
- `success` (property) — `not any(severity >= ERROR)`

No backwards compatibility concerns — nobody is using this module yet. Documentation written as if it has always been this way.

## File changes

| File | Change |
|------|--------|
| `pyfolium/logging.py` | **New.** `Severity`, `LogEntry`, `OutputMode` |
| `pyfolium/simulation.py` | Replace `_errors` with `_log`. Replace `warnings.warn()` with log entries. Change `run()` signature. Update `BacktestResult`. |
| `pyfolium/strategy.py` | Add `_log` list and `log()` method. Runner drains after each `step()`. |
| `pyfolium/__init__.py` | Export new public types |
| `tests/` | Replace `pytest.warns` with log inspection. New tests for log entries, severity, OutputMode. |
| Docs | Update CLAUDE.md, DESIGN.md, README.md |

## Non-goals (future observability)

- **Per-period summaries from the runner** — At 10,000 periods this generates unusable volumes. Periodic diagnostics are the strategy's responsibility via `self.log()`, at whatever granularity makes sense for that strategy.
- **Streaming / pub-sub** — hooks already serve this purpose.
- **Log persistence** — users serialize `log_df` however they want.
- **Python `logging` integration** — scoping and concurrency isolation matter more than stdlib compatibility.
- **STRUCTURED OutputMode** — strategy-defined periodic output is better than runner-generated JSON per period.
