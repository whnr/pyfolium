# Logging & Observability Specification

*Spec for: P2-6 (trade failure visibility) + Logging architecture (replace `.errors` with `.log`) + OutputMode (terminal filtering)*
*Depends on: P1-4 (error recovery) — resolved. Strict/lenient mode is implemented.*
*Date: 2026-03-01*

---

## Problem Statement

BacktestRunner captures exceptions in `_errors: list[tuple[pd.Period, Exception]]`, which is too narrow. Three categories of runtime events go unrecorded or are invisible:

1. **Trade failures** — `BaseStrategy.execute_trades()` catches `ValueError` and records `success=False` in `trades_df`, but emits no warning and produces no log entry. AI-written strategies can silently fail every trade for an entire backtest. (P2-6) FLOCOMMENT: Isn't that actually a great pattern? The trade is still registered, but as failed. That's where it matters! Isn't that what a strategy would care about? It's all about `get_trades`. If the trade has been made good! If not I'll find it there.

2. **Operational warnings** — Lenient-mode recovery, hook exceptions, and negative-cash conditions use `warnings.warn()`, which produces unstructured output that isn't captured in the result object. Users can't programmatically inspect what happened.

3. **Normal execution diagnostics** — There is no record of what happened period-by-period beyond raw `transactions` and `history` DataFrames. No summary of trades attempted vs executed, no lifecycle events, no timestamps.

The current `BacktestResult.errors` is a flat list of `(period, exception)` tuples. The `success` property is binary. There is no severity model, no structured data, and no filtering.

FLOCOMMENT: Is another point that we cannot debug when or what something was slow? How would we do perforance profiling where a strategy might get slow over time? --> don't we need timestamps for that?

## Goals

1. Replace `_errors` / `errors` with a structured `log` that captures events at multiple severity levels.
2. Subsume P2-6: trade failures become WARNING-level log entries automatically.
3. Subsume `warnings.warn()` calls in the runner: these become log entries with proper severity.
4. Add an `OutputMode` enum controlling what gets printed to terminal during `run()`.
5. Expose the log as a queryable DataFrame on `BacktestResult`.
6. backwards compatibility not required. Noone is using this module yet. Write Documentation as if it has always been this way.

FLOCOMMENT: on dataframe: Why a dataframe as the goal? Isn't a df bad for appending unnkown lengths of anything? Isn't this much better as a dict? Or a list?

## Non-Goals (future observability, out of scope)

- **Per-period structured summaries** (trades attempted/executed/failed, portfolio value, cash) — useful for LLM consumers but a separate feature that builds *on top of* the log infrastructure. Can be added as INFO-level entries later or as a dedicated `period_summary` DataFrame. FLOCOMMENT: Is a per-period structured summary ever a good idea? If we run 10,000 periods = 30 years we'll dump 1M tokens at an LLM. That would be mayhem, right? I think there needs to be a leaner approach to observability in general. We want to capture all data in dfs.
- **Streaming/callback log consumers** — e.g., a websocket that pushes log entries in real time. The hook system already provides extension points; the log is a capture mechanism, not a pub/sub system.
- **Log persistence** — writing logs to files, databases, or external services. Users can serialize `result.log_df` however they want.
- **Python `logging` module integration** — the standard library logger is designed for application-level logging with global state (handlers, formatters, levels). Pyfolium's log is a *simulation record* scoped to a single backtest run. Mixing the two would create confusing interactions (global log level affecting simulation capture, handler configuration leaking between runs). The `LogEntry` structure is intentionally independent. Users who want to bridge the two can write a hook or post-process `log_df`.FLOCOMMENT: If I understand this correctly: We'd want to do this because there might be concurrency (8 strategies running in parallel) where we don't all the messages to end up in one application log.
- **`STRUCTURED` OutputMode with per-period JSON dicts** — described in review-findings.md as a fourth output mode yielding per-period structured data for LLMs. This is better implemented as a separate feature (period summary generation) once the log infrastructure exists. The three modes (SILENT, SUMMARY, PROGRESS) cover the immediate needs. FLOCOMMENT: As said above: I think these might be a bad idea at every period, maybe it should be up to the strategy to define periodic outputs in an expected format for themselves?

---

## Design

### 1. `LogEntry` dataclass

```python
# pyfolium/simulation.py

from dataclasses import dataclass, field
from enum import IntEnum

class Severity(IntEnum):
    """Log severity levels, ordered by importance."""
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40

@dataclass(frozen=True, slots=True)
class LogEntry:
    """A single structured log entry from a backtest run.

    Attributes:
        severity: Severity level (DEBUG, INFO, WARNING, ERROR).
        FLOCOMMENT: add something like this timestamp: The simulation time when the event occurred.
        period: The simulation period when the event occurred.
        source: Dot-path identifying where the event originated
            (e.g., "runner", "strategy", "hook").
        message: Human-readable description of the event.
        data: Optional structured data for programmatic inspection.
    """
    severity: Severity
    timestamp: FLOCOMMENT: something here. Maybe float
    period: pd.Period
    source: str
    message: str
    data: dict | None = None
```

**Design decisions:**

- **`frozen=True, slots=True`** — log entries are immutable records. No mutation after creation. Slots for memory efficiency (a long backtest could produce thousands of entries).
- **`Severity` as `IntEnum`** — enables `>=` comparisons for filtering (`entry.severity >= Severity.WARNING`). Standard DEBUG/INFO/WARNING/ERROR. No CRITICAL — an ERROR that stops the backtest is distinguishable by context (strict mode raises, lenient mode continues).
- **`source` field** — identifies the component: `"runner"`, `"strategy"`, `"hook"`. Useful for filtering ("show me only strategy-level events").
- **`data` field** — optional dict for structured context. Trade failures include `{"symbol": "AAPL", "quantity": 100, "error": "no price data"}`. Exceptions include `{"exception_type": "ValueError", "traceback": "..."}`. Can be `None` for simple messages.
- **No wall-clock timestamp in the dataclass** — the log is a simulation record. Wall-clock time is irrelevant after the fact. Terminal output (controlled by OutputMode) may include wall-clock timestamps for real-time monitoring, but the persisted log uses simulation periods only. FLOCOMMENT: I don't agree. I think this is great for performance monitoring.

FLOCOMMENT: The major decision that is missing for me in this explanation is: Why a df? To align it with our general simulation structure? makes sense? But we don't want to add single rows to dfs, right?

### 2. `OutputMode` enum

```python
# pyfolium/simulation.py

class OutputMode(str, Enum):
    """Controls terminal output during backtest execution."""
    SILENT = "silent"      # No terminal output. Log captured in result only.
    SUMMARY = "summary"    # One-line summary at end (total periods, time, error count).
    PROGRESS = "progress"  # tqdm progress bar (current behavior with progress=True).
```

**Replaces:** The `progress: bool` parameter on `BacktestRunner.run()`.

**Interaction with log:** OutputMode controls what gets *printed*. The log always captures everything regardless of OutputMode. The log is the complete record; terminal output is a filtered view.

FLOCOMMENT: Isn't this typically a verbosity level that we'd want to set? Like a summary is nice, but maybe we want a bit more? I guess that can be set with the level for logging? I'm a bit confused what should be shown. Should it be hooks that the strategy defines to get output when it wants. Like the examples already show how that can be done. So what will be left for the log in that case? Duplicating everything: useless. Warnings, sure! Errors, sure! Having an actual place where the strategy can write it's decsisions? Now were talking! Those should come as NOTICE, or INFO, right? Like when a strategy does something normal: INFO, when it has to course correct because something is out of whack: NOTICE.

### 3. Changes to `BacktestRunner`

#### 3.1 Constructor changes

```python
class BacktestRunner:
    def __init__(
        self,
        portfolio: Portfolio,
        strategy: BaseStrategy,
        *,
        start_period: pd.Period | None = None,
        end_period: pd.Period | None = None,
        strict: bool = True,
    ):
        # ... existing init logic ...

        # Replace _errors with structured log
        self._log: list[LogEntry] = []

        # Remove: self._errors: list[tuple[pd.Period, Exception]] = []
```

**`_log` replaces `_errors`.**  The runner appends `LogEntry` objects instead of `(period, exception)` tuples.

#### 3.2 Internal logging method

```python
def _log_event(
    self,
    severity: Severity,
    message: str,
    source: str = "runner",
    data: dict | None = None,
) -> None:
    """Append a structured log entry."""
    entry = LogEntry(
        severity=severity,
        period=self.current_period,
        source=source,
        message=message,
        data=data,
    )
    self._log.append(entry)
```

Simple append — no filtering, no printing. Terminal output is handled separately by `run()` based on OutputMode.

#### 3.3 `run_period()` changes

Current error handling in `run_period()` (lines 304-344) changes as follows:

**Exception capture (currently `_errors.append`):**

```python
except Exception as e:
    self._log_event(
        Severity.ERROR,
        f"Exception during period execution: {e}",
        data={"exception_type": type(e).__name__, "exception_msg": str(e)},
    )
    self._trigger_hooks("error")

    if self._strict:
        raise

    # Lenient mode: attempt graceful recovery (existing logic unchanged)
    ...
```

**Lenient-mode recovery warning (currently `warnings.warn`):**

```python
# Replace warnings.warn() with log entry
self._log_event(
    Severity.WARNING,
    f"Recovered from error in period {self.current_period}, "
    f"advancing to next period",
    data={"recovery_action": "update_history_and_advance"},
)
```

**Hook exception warning (currently `warnings.warn` in `_trigger_hooks`):**

```python
def _trigger_hooks(self, event: str) -> None:
    for callback in self._hooks[event]:
        try:
            callback(self)
        except Exception as e:
            self._log_event(
                Severity.WARNING,
                f"Hook for event '{event}' raised: {e}",
                source="hook",
                data={"event": event, "exception_type": type(e).__name__},
            )
```

#### 3.4 `run()` signature change

```python
def run(self, *, output: OutputMode = OutputMode.SILENT) -> BacktestResult:
```

**Replaces:** `progress: bool = False`.

**Behavior by mode:**

| Mode | Behavior |
|------|----------|
| `SILENT` | No terminal output. Equivalent to current `progress=False`. |
| `SUMMARY` | After completion, prints one line: `Backtest complete: 252 periods in 1.34s (0 errors, 2 warnings)`. |
| `PROGRESS` | tqdm progress bar. Equivalent to current `progress=True`. FLOCOMMENT: I think this should also auto show the SUMMARY. No reason why a human liking progress bars would not also want a single line summary at the end|

**Implementation:** The `run()` method wraps the execution loop with mode-specific setup/teardown. The log is populated regardless of mode.

### 4. Changes to `BacktestResult` FLOHERE

```python
@dataclass
class BacktestResult:
    portfolio: Portfolio
    strategy: BaseStrategy
    start_period: pd.Period
    end_period: pd.Period
    total_periods: int
    execution_time: float
    log: list[LogEntry] = field(default_factory=list)

    @property
    def log_df(self) -> pd.DataFrame:
        """Log entries as a queryable DataFrame.

        Columns: severity, period, source, message, data
        """
        if not self.log:
            return pd.DataFrame(
                columns=["severity", "period", "source", "message", "data"]
            )
        return pd.DataFrame(
            [
                {
                    "severity": e.severity.name,
                    "period": e.period,
                    "source": e.source,
                    "message": e.message,
                    "data": e.data,
                }
                for e in self.log
            ]
        )

    @property
    def errors(self) -> list[LogEntry]:
        """All ERROR-level log entries."""
        return [e for e in self.log if e.severity >= Severity.ERROR]

    @property
    def warnings(self) -> list[LogEntry]:
        """All WARNING-level log entries."""
        return [
            e for e in self.log
            if e.severity == Severity.WARNING
        ]

    @property
    def success(self) -> bool:
        """Returns True if backtest completed without errors."""
        return not any(e.severity >= Severity.ERROR for e in self.log)

    def __repr__(self) -> str:
        n_errors = sum(1 for e in self.log if e.severity >= Severity.ERROR)
        n_warnings = sum(1 for e in self.log if e.severity == Severity.WARNING)
        parts = [
            f"BacktestResult({self.start_period} to {self.end_period}",
            f"{self.total_periods} periods",
            f"{self.execution_time:.2f}s",
        ]
        if n_errors:
            parts.append(f"{n_errors} errors")
        if n_warnings:
            parts.append(f"{n_warnings} warnings")
        return ", ".join(parts) + ")"
```

**Breaking changes:**

| Before | After | Migration |
|--------|-------|-----------|
| `result.errors` returns `list[tuple[pd.Period, Exception]]` | `result.errors` returns `list[LogEntry]` | Access `entry.period` and `entry.data["exception_msg"]` instead of tuple unpacking |
| `result.success` checks `len(self.errors) == 0` | `result.success` checks severity levels | Semantically identical — errors are ERROR-level entries |
| `run(progress=True)` | `run(output=OutputMode.PROGRESS)` | Direct rename |

### 5. Changes to `BaseStrategy` (P2-6)

The strategy needs a way to emit log entries that the runner captures. Two options considered:

**Option A: Strategy calls back to runner's log (rejected)**
Would require the strategy to hold a reference to the runner, creating a circular dependency. The strategy currently only knows about the portfolio.

**Option B: Strategy accumulates its own log, runner collects it (chosen)**
The strategy has a `_log` list. After each `step()`, the runner drains it into its own log. This preserves the current architecture where the strategy only knows about the portfolio.

```python
# pyfolium/strategy.py

class BaseStrategy(ABC):
    def __init__(self, portfolio, parameters=None, *, initial_cash=None, start_period=None):
        # ... existing init ...
        self._log: list[LogEntry] = []

    def execute_trades(self, trades: list[tuple[str, float]]) -> None:
        for symbol, quantity in trades:
            try:
                if quantity > 0:
                    self.portfolio.buy_asset(symbol, quantity)
                    self._record_trade(symbol, quantity, quantity)
                elif quantity < 0:
                    self.portfolio.sell_asset(symbol, abs(quantity))
                    self._record_trade(symbol, quantity, quantity)
            except ValueError as e:
                self._record_trade(symbol, quantity, 0, success=False)
                self._log.append(LogEntry(
                    severity=Severity.WARNING,
                    period=self.portfolio.current_period,
                    source="strategy",
                    message=f"Trade failed for {symbol} qty={quantity}: {e}",
                    data={
                        "symbol": symbol,
                        "desired_quantity": quantity,
                        "error": str(e),
                    },
                ))
                continue
```

**Runner collects strategy log entries after each step:**

```python
# In BacktestRunner.run_period(), after strategy.step():
self.strategy.step()
# Drain strategy log entries into runner log
self._log.extend(self.strategy._log)
self.strategy._log.clear()
```

**Import consideration:** `LogEntry` and `Severity` are defined in `simulation.py`. The strategy module imports from `core.py` only. To avoid a circular import (`strategy.py` → `simulation.py` → `strategy.py`), extract `LogEntry` and `Severity` into a separate module.

### 6. New module: `pyfolium/logging.py`

```python
"""Structured logging primitives for backtest execution.

This module defines the LogEntry and Severity types used by both
BacktestRunner and BaseStrategy. It is deliberately independent of
the Python standard library's logging module — see the spec for rationale.
"""

from dataclasses import dataclass
from enum import IntEnum

import pandas as pd


class Severity(IntEnum):
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40


@dataclass(frozen=True, slots=True)
class LogEntry:
    severity: Severity
    period: pd.Period
    source: str
    message: str
    data: dict | None = None
```

Both `simulation.py` and `strategy.py` import from `pyfolium.logging`. No circular dependency.

### 7. What gets logged and at what severity

| Severity | Source | Event | `data` contents |
|----------|--------|-------|-----------------|
| ERROR | runner | Exception during period execution | `exception_type`, `exception_msg` |
| ERROR | runner | Unrecoverable state after lenient-mode error | `exception_type`, `exception_msg` |
| WARNING | strategy | Trade failed (ValueError in buy/sell) | `symbol`, `desired_quantity`, `error` |
| WARNING | runner | Lenient-mode recovery (period skipped) | `recovery_action` |
| WARNING | hook | Hook callback raised exception | `event`, `exception_type` |
| INFO | runner | Backtest started | `start_period`, `end_period`, `strict` |
| INFO | runner | Backtest completed | `total_periods`, `execution_time`, `n_errors`, `n_warnings` |
| DEBUG | runner | Period started | (none needed — period is on the entry) |
| DEBUG | runner | Initial cash injected | `amount` |

**INFO and DEBUG entries are opt-in.** The first implementation should focus on ERROR and WARNING (the entries that replace existing `_errors` and `warnings.warn()` calls). INFO/DEBUG entries can be added incrementally without API changes — they just append more entries to the same log.

**Minimum viable implementation:** ERROR + WARNING entries only. This covers all current error handling patterns and P2-6.

### 8. Interaction with hooks

**Hooks remain unchanged.** They are user extension points for custom side effects (sending alerts, writing to databases, collecting custom metrics). The log is the built-in observability mechanism.

**The `"error"` hook still fires** when an exception occurs. Hook callbacks receive the runner, so they can inspect `runner._log[-1]` for the just-recorded error entry if needed.

**Hook exceptions become log entries** (WARNING level) instead of `warnings.warn()` calls.

### 9. `warnings.warn()` removal

All `warnings.warn()` calls in `simulation.py` are replaced by `_log_event()` calls. The `import warnings` statement can be removed from `simulation.py` once all calls are replaced.

`strategy.py` never had `import warnings` — trade failures go directly to the strategy's `_log` list.

**User-facing behavior change:** Code that uses `pytest.warns(UserWarning)` to detect lenient-mode errors will need to change to inspecting `result.log` or `result.errors`. This affects two existing tests:
- `test_error_during_strategy_execution` (line 250)
- `test_lenient_mode_history_remains_consistent` (line 318)

---

## API Surface Summary

### New public types

| Type | Module | Description |
|------|--------|-------------|
| `Severity` | `pyfolium.logging` | IntEnum: DEBUG, INFO, WARNING, ERROR |
| `LogEntry` | `pyfolium.logging` | Frozen dataclass: severity, period, source, message, data |
| `OutputMode` | `pyfolium.simulation` | StrEnum: SILENT, SUMMARY, PROGRESS |

### Changed APIs

| API | Before | After |
|-----|--------|-------|
| `BacktestRunner.run()` | `progress: bool = False` | `output: OutputMode = OutputMode.SILENT` |
| `BacktestResult.errors` | `list[tuple[pd.Period, Exception]]` | `list[LogEntry]` (property, filtered to ERROR severity) |
| `BacktestResult.success` | `len(self.errors) == 0` | `not any(severity >= ERROR)` (semantically same) |

### New APIs

| API | Type | Description |
|-----|------|-------------|
| `BacktestResult.log` | `list[LogEntry]` | Complete structured log from the run |
| `BacktestResult.log_df` | `pd.DataFrame` (property) | Log as queryable DataFrame |
| `BacktestResult.warnings` | `list[LogEntry]` (property) | WARNING-level entries |
| `BaseStrategy._log` | `list[LogEntry]` | Strategy's log buffer (drained by runner after each step) |

### Exports from `pyfolium/__init__.py`

Add `Severity`, `LogEntry`, `OutputMode` to `__all__`.

---

## File Changes

| File | Change |
|------|--------|
| `pyfolium/logging.py` | **New.** `Severity`, `LogEntry` |
| `pyfolium/simulation.py` | Import from `.logging`. Replace `_errors` with `_log`. Add `_log_event()`. Add `OutputMode`. Change `run()` signature. Update `BacktestResult`. Remove `warnings.warn()`. |
| `pyfolium/strategy.py` | Import from `.logging`. Add `_log` list. Log trade failures as WARNING in `execute_trades()`. |
| `pyfolium/__init__.py` | Export `Severity`, `LogEntry`, `OutputMode` |
| `tests/simulation/test_backtest_runner.py` | Update error-related tests. Replace `pytest.warns` with log inspection. Add tests for log entries, OutputMode, log_df. |
| `tests/strategy/test_basestrategy.py` | Add tests for trade failure log entries. |
| `CLAUDE.md` | Update architecture section with logging description |
| `DESIGN.md` | Add "Observability" section |
| `README.md` | Update usage examples if they reference `result.errors` or `progress=True` |

---

## Test Plan

### Unit tests for `LogEntry` and `Severity`

- `Severity` ordering: `DEBUG < INFO < WARNING < ERROR`
- `LogEntry` is frozen (immutable)
- `LogEntry` equality and hashing (for deduplication if needed)

### Unit tests for `OutputMode`

- `SILENT` produces no terminal output
- `SUMMARY` prints exactly one line after completion
- `PROGRESS` shows tqdm bar (existing test adapted)

### BacktestRunner log tests

- Strict mode: ERROR entry logged before re-raise
- Lenient mode: ERROR + WARNING entries logged, backtest continues
- Hook exception: WARNING entry logged with source="hook"
- Clean run: no ERROR or WARNING entries in log
- `result.log` contains all entries in chronological order
- `result.errors` returns only ERROR-level entries
- `result.warnings` returns only WARNING-level entries
- `result.success` is True when no ERROR entries exist
- `result.success` is False when ERROR entries exist (even if warnings present)
- `result.log_df` returns DataFrame with correct columns and types

### Strategy trade failure log tests (P2-6)

- Failed buy produces WARNING entry with source="strategy"
- Failed sell produces WARNING entry with source="strategy"
- Log entry `data` contains symbol, quantity, and error message
- Successful trades produce no log entries (at WARNING+ level)
- Multiple failures in one period each produce separate entries
- Strategy `_log` is drained after each `step()` call
- Strategy `_log` is empty between periods

### Migration / backwards compatibility tests

- `result.errors` property works (returns LogEntry list, not tuples)
- `result.success` works as before
- `run(output=OutputMode.PROGRESS)` works like old `run(progress=True)`

---

## Implementation Order

The implementation order follows the dependency chain and keeps each step independently testable:

1. **`pyfolium/logging.py`** — new module with `Severity` and `LogEntry`. Pure data, no dependencies. Add to `__init__.py` exports.

2. **`BacktestResult` and `BacktestRunner` internals** — replace `_errors` with `_log`, add `_log_event()`, update `BacktestResult` dataclass (new `log` field, `log_df` property, updated `errors`/`warnings`/`success` properties). Update all tests.

3. **`BaseStrategy._log` and trade failure logging** — add `_log` to strategy, log trade failures as WARNING in `execute_trades()`, drain in runner's `run_period()`. This completes P2-6.

4. **`OutputMode` and `run()` signature** — add enum, change `run()` parameter from `progress: bool` to `output: OutputMode`. Implement SILENT/SUMMARY/PROGRESS modes. Update tests.

5. **Documentation** — update CLAUDE.md, DESIGN.md, README.md.

Each step is a single reviewable commit.
