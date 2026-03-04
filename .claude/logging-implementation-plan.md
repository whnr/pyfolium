# Logging & Observability — Implementation Plan

*Based on [logging-spec.md](.claude/logging-spec.md). This plan is the step-by-step blueprint; the spec is the design rationale.*

---

## Phase 0: New module `pyfolium/logging.py`

Create the types that everything else depends on. No existing code changes yet.

### 0.1 `Severity(IntEnum)`

```python
class Severity(IntEnum):
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
```

IntEnum so `>=` comparisons work for filtering.

### 0.2 `LogEntry` (frozen dataclass, slots)

```python
@dataclass(frozen=True, slots=True)
class LogEntry:
    severity: Severity
    timestamp: float          # time.monotonic()
    period: pd.Period
    source: str               # "runner", "strategy", "hook"
    message: str
    data: dict[str, Any] | None = None
```

### 0.3 `OutputMode(str, Enum)`

```python
class OutputMode(str, Enum):
    SILENT = "silent"
    SUMMARY = "summary"
    PROGRESS = "progress"
    RICH = "rich"              # Phase 3 — multi-bar + scrolling log
```

`str, Enum` so it serializes cleanly and works in match/case.

`RICH` is reserved for Phase 3. In Phases 0–2 it raises `NotImplementedError("RICH output requires the 'rich' extra: pip install pyfolium[rich]")`.

### 0.4 Tests

- `Severity` ordering: `DEBUG < INFO < WARNING < ERROR`
- `LogEntry` is frozen (assigning raises `FrozenInstanceError`)
- `LogEntry` equality and sorting by timestamp
- `OutputMode` values are strings

**Files created:** `pyfolium/logging.py`, `tests/test_logging.py`

---

## Phase 1: Wire into `BacktestRunner` + `BacktestResult`

Replace the ad-hoc error machinery with the structured log.

### 1.1 `BacktestRunner` changes

| Before | After |
|--------|-------|
| `_errors: list[tuple[pd.Period, Exception]]` | `_log: list[LogEntry]` |
| `warnings.warn(...)` in lenient mode | `_emit(severity, message, data)` appends `LogEntry` |
| `run(progress=False)` | `run(output=OutputMode.SILENT)` |

New private method:

```python
def _emit(self, severity: Severity, message: str, data: dict | None = None) -> None:
    self._log.append(LogEntry(
        severity=severity,
        timestamp=time.monotonic(),
        period=self.portfolio.current_period,
        source="runner",
        message=message,
        data=data,
    ))
```

**Emit points** (ERROR + WARNING only in first implementation):

| Location | Severity | Message pattern |
|----------|----------|-----------------|
| `run_period()` exception catch | ERROR | `"Exception during period {period}: {exc}"` |
| `run_period()` lenient recovery | WARNING | `"Lenient mode: skipped error in period {period}"` |
| `_trigger_hooks()` exception | WARNING | `"Hook '{event}' raised {exc.__class__.__name__}: {exc}"` |
| `run()` end, if trade failures detected | WARNING | `"Backtest completed with {n}/{total} failed trades in trades_df"` |

The last one is the P2-6 resolution: a single summary warning when `trades_df` has `success=False` rows, surfaced once at backtest end — not per-trade.

**OutputMode handling in `run()`:**

```python
def run(self, *, output: OutputMode = OutputMode.SILENT) -> BacktestResult:
```

| Mode | Behavior |
|------|----------|
| `SILENT` | No terminal output. Log captured in result only. |
| `SUMMARY` | One-line summary printed at end: `"Backtest: {n} periods, {time:.2f}s, {errors} errors, {warnings} warnings"` |
| `PROGRESS` | tqdm bar during execution + summary line at end. |
| `RICH` | `NotImplementedError` (Phase 3). |

**Backward compat:** `progress=True` is **removed**, not deprecated. No users exist yet (per spec).

### 1.2 Strategy log drain

After each `strategy.step()` call in `run_period()`:

```python
self.strategy.step()
# drain strategy log
self._log.extend(self.strategy._log)
self.strategy._log.clear()
```

This is a 2-line addition. The strategy's `_log` and `log()` method come in Phase 2.

### 1.3 `BacktestResult` changes

```python
@dataclass
class BacktestResult:
    portfolio: Portfolio
    strategy: BaseStrategy
    start_period: pd.Period
    end_period: pd.Period
    total_periods: int
    execution_time: float
    log: list[LogEntry]                     # replaces errors

    @cached_property
    def log_df(self) -> pd.DataFrame:
        """Lazy DataFrame view of the log."""
        if not self.log:
            return pd.DataFrame(
                columns=["severity", "timestamp", "period", "source", "message", "data"]
            )
        return pd.DataFrame([
            {
                "severity": e.severity.name,
                "timestamp": e.timestamp,
                "period": e.period,
                "source": e.source,
                "message": e.message,
                "data": e.data,
            }
            for e in self.log
        ])

    @property
    def errors(self) -> list[LogEntry]:
        return [e for e in self.log if e.severity >= Severity.ERROR]

    @property
    def warnings(self) -> list[LogEntry]:
        return [e for e in self.log if e.severity == Severity.WARNING]

    @property
    def success(self) -> bool:
        return not any(e.severity >= Severity.ERROR for e in self.log)
```

**Breaking change to `errors`:** Previously `list[tuple[pd.Period, Exception]]`, now `list[LogEntry]`. The exception object is available via `entry.data["exception"]` for entries with severity ERROR. Tests must update.

### 1.4 Hook exception handling

`_trigger_hooks()` currently uses `warnings.warn()`. Replace with `_emit(WARNING, ...)`:

```python
except Exception as exc:
    self._emit(
        Severity.WARNING,
        f"Hook '{event}' raised {exc.__class__.__name__}: {exc}",
        data={"event": event, "exception": exc},
    )
```

### 1.5 Tests

Update **all** existing tests that rely on the old interface:

- `test_backtest_runner.py`: Replace `result.errors` tuple checks with `LogEntry` checks. Replace `pytest.warns(UserWarning)` with log inspection. Update `run(progress=True)` → `run(output=OutputMode.PROGRESS)`.
- New tests:
  - `_emit()` creates valid `LogEntry` with correct source and timestamp
  - Lenient mode populates log with ERROR + WARNING entries
  - Hook exceptions appear in log as WARNING
  - `result.log_df` returns correct DataFrame
  - `result.success` / `result.errors` / `result.warnings` filter correctly
  - `OutputMode.PROGRESS` shows tqdm (existing behavior, new API)
  - `OutputMode.SUMMARY` prints summary line (capture stdout)
  - `OutputMode.SILENT` prints nothing
  - Trade failure summary warning at backtest end
  - `OutputMode.RICH` raises `NotImplementedError`

**Files changed:** `pyfolium/simulation.py`, `tests/simulation/test_backtest_runner.py`

---

## Phase 2: Strategy logging

### 2.1 `BaseStrategy` changes

Add `_log` list and `log()` convenience method:

```python
class BaseStrategy(ABC):
    def __init__(self, ...):
        ...
        self._log: list[LogEntry] = []

    def log(
        self,
        severity: Severity,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Record a log entry. Called from get_trades() to capture strategy reasoning."""
        self._log.append(LogEntry(
            severity=severity,
            timestamp=time.monotonic(),
            period=self.portfolio.current_period,
            source="strategy",
            message=message,
            data=data,
        ))
```

### 2.2 Tests

- Strategy `log()` creates entries with `source="strategy"`
- Entries accumulate in `strategy._log`
- After `runner.run()`, strategy entries appear in `result.log` (drain test)
- `strategy._log` is empty after drain
- Multiple calls per period accumulate correctly

**Files changed:** `pyfolium/strategy.py`, `tests/strategy/test_basestrategy.py`

---

## Phase 3: Rich multi-bar display (`OutputMode.RICH`)

This is the pacman-style display for massive parallel optimization runs. It requires the `rich` library as an optional dependency.

### 3.1 The vision

```
  Optimization: ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  42% 168/400
  ──────────────────────────────────────────────────────────────────────
  ✓ aggressive_growth     1200 periods  3.42s   +23.4% return
  ✓ conservative_income   1200 periods  2.81s   +11.2% return
  ✗ momentum_v3           1200 periods  4.17s   +8.1%  (12 trade failures)
  ✓ mean_reversion_v2     1200 periods  3.95s   +15.7% return
  ──────────────────────────────────────────────────────────────────────
  worker-01: ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸         87%  1044/1200
  worker-02: ━━━━━━━━━━━━━━━╸                             38%   456/1200
  worker-03: ━━━━━━━━━━━━━━━━━━━━━━━╸                     59%   708/1200
  worker-04: ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100%  1200/1200
  worker-05: ━━━━━━━╸                                     19%   228/1200
  ...
  worker-16: ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸              76%   912/1200
```

Three visual zones:
1. **Global bar** (top) — overall progress across all backtests
2. **Scrolling summaries** (middle) — completed backtests scroll through, most recent at bottom
3. **Worker bars** (bottom) — one bar per active worker, fixed positions

### 3.2 Why `rich`, not `tqdm`

**tqdm** can stack bars via `position=N`, but:
- No scrolling log region between bars — `tqdm.write()` pushes output above *all* bars, not between specific ones
- 16 bars cause terminal flicker (each bar redraws independently via `\r` + ANSI escapes)
- No layout composition — you can't say "bars at bottom, logs in middle, global bar at top"

**rich** solves all three:
- `rich.live.Live` + `rich.layout.Layout` composes arbitrary regions that refresh atomically
- `rich.progress.Progress` supports N tasks with `add_task()` / `update()` — each task is a bar
- `progress.console.print()` outputs scrolling text *above* the live display
- Single composite render — no flicker regardless of bar count
- `Group` or `Table` can combine multiple `Progress` instances into a single renderable

### 3.3 Architecture: `RichDisplay` class

New file: `pyfolium/display.py`

```python
class RichDisplay:
    """Pacman-style multi-bar display for parallel backtest runs.

    Composes three visual zones using rich.live.Live:
    - Global progress bar (top)
    - Scrolling summary log (middle)
    - Per-worker progress bars (bottom)
    """

    def __init__(self, total_backtests: int, num_workers: int): ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def update_worker(self, worker_id: int, advance: int = 1) -> None: ...
    def complete_worker(self, worker_id: int, summary: str) -> None: ...
    def update_global(self, advance: int = 1) -> None: ...
    def log_message(self, message: str) -> None: ...
```

**Implementation sketch:**

```python
from rich.live import Live
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

class RichDisplay:
    def __init__(self, total_backtests: int, num_workers: int):
        # Global progress
        self._global_progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("{task.percentage:>3.0f}%"),
            TextColumn("{task.completed}/{task.total}"),
        )
        self._global_task = self._global_progress.add_task(
            "Optimization", total=total_backtests
        )

        # Per-worker progress
        self._worker_progress = Progress(
            TextColumn("{task.description}"),
            BarColumn(),
            TextColumn("{task.percentage:>3.0f}%"),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
        )
        self._worker_tasks: dict[int, TaskID] = {}
        for i in range(num_workers):
            task_id = self._worker_progress.add_task(
                f"worker-{i+1:02d}", total=0, visible=False
            )
            self._worker_tasks[i] = task_id

        # Scrolling summaries (ring buffer, keep last ~50)
        self._summaries: deque[str] = deque(maxlen=50)

        # Composed layout
        self._live = Live(self._build_renderable(), refresh_per_second=12)

    def _build_renderable(self) -> Group:
        parts = [self._global_progress]
        if self._summaries:
            summary_text = Text("\n".join(self._summaries))
            parts.append(Panel(summary_text, title="Completed", border_style="dim"))
        parts.append(self._worker_progress)
        return Group(*parts)
```

### 3.4 Integration with `BacktestRunner`

`RichDisplay` is **not** owned by `BacktestRunner`. The runner remains single-backtest focused. Instead, `RichDisplay` is used by the *caller* — an optimization loop or parallel executor:

```python
from concurrent.futures import ProcessPoolExecutor
from pyfolium.display import RichDisplay

display = RichDisplay(total_backtests=400, num_workers=16)
display.start()

with ProcessPoolExecutor(max_workers=16) as pool:
    futures = {}
    for i, params in enumerate(param_grid):
        future = pool.submit(run_single_backtest, params)
        futures[future] = i

    for future in as_completed(futures):
        worker_id = futures[future]
        result = future.result()
        display.complete_worker(worker_id, summary=format_result(result))
        display.update_global(advance=1)

display.stop()
```

For the *single-backtest* `OutputMode.RICH` case, `BacktestRunner.run()` creates a simpler `RichDisplay` with 1 worker, using `progress.console.print()` for log entries as they happen.

### 3.5 `rich` as optional dependency

```toml
# pyproject.toml
[project.optional-dependencies]
rich = ["rich>=13.0"]
```

`pyfolium/display.py` imports `rich` at the top with a guard:

```python
try:
    from rich.live import Live
    from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn
    from rich.console import Group
    from rich.panel import Panel
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
```

`OutputMode.RICH` in `BacktestRunner.run()` checks `HAS_RICH` and raises `ImportError("Install rich for RICH output mode: pip install pyfolium[rich]")` if missing.

### 3.6 Tests

- `RichDisplay` unit tests with mocked `Live` (don't need a real terminal)
- `OutputMode.RICH` without rich installed raises `ImportError`
- `OutputMode.RICH` with rich installed runs without error
- Worker lifecycle: start → update → complete → summary appears
- Global progress advances correctly

**Files created:** `pyfolium/display.py`, `tests/test_display.py`
**Files changed:** `pyfolium/simulation.py` (RICH mode handler), `pyproject.toml` (optional dep)

---

## Phase 4: Exports and documentation

### 4.1 `__init__.py`

Add new public types:

```python
from pyfolium.logging import LogEntry, OutputMode, Severity

__all__ = [
    ...
    # Logging & observability
    "Severity",
    "LogEntry",
    "OutputMode",
]
```

`RichDisplay` is **not** exported from `__init__.py` — it's an advanced API imported directly from `pyfolium.display`.

### 4.2 Documentation updates

| File | Changes |
|------|---------|
| `CLAUDE.md` | Add `pyfolium/logging.py` and `pyfolium/display.py` to project structure. Update "Current State" section. Add `OutputMode` and logging to architecture summary. |
| `DESIGN.md` | Add "Observability" section: why scoped logs not stdlib logging, the drain pattern, OutputMode rationale, rich as optional. |
| `README.md` | Add logging/observability to usage examples. Show `OutputMode.PROGRESS` and `OutputMode.RICH`. |

---

## Execution order

| Step | Phase | What | Tests touch |
|------|-------|------|-------------|
| 1 | 0 | Create `pyfolium/logging.py` with types | `tests/test_logging.py` (new) |
| 2 | 1 | Wire `_log` into `BacktestRunner` + `BacktestResult` | `tests/simulation/test_backtest_runner.py` (update) |
| 3 | 2 | Add `log()` to `BaseStrategy` + drain | `tests/strategy/test_basestrategy.py` (update) |
| 4 | 4 | Update `__init__.py` exports | — |
| 5 | 1+2 | Run full test suite, fix breakage | all |
| 6 | 3 | Create `pyfolium/display.py` with `RichDisplay` | `tests/test_display.py` (new) |
| 7 | 4 | Update CLAUDE.md, DESIGN.md, README.md | — |
| 8 | — | Final `pre-commit run --all-files` + `pytest` | all |

Steps 1–5 are the core implementation. Step 6 is the rich display feature. Step 7 is documentation. Each step is a separate commit.

---

## Open questions resolved

**Q: How to show 16 progress bars with scrolling summaries?**
A: `rich.live.Live` with `Group` composing three zones — global `Progress`, scrolling `Panel`, worker `Progress`. Rich renders atomically (no flicker). `tqdm` can't do the scrolling-log-between-bars layout.

**Q: Is `rich` a required dependency?**
A: No. Optional extra: `pip install pyfolium[rich]`. The core logging system (`Severity`, `LogEntry`, `OutputMode.SILENT/SUMMARY/PROGRESS`) works without rich. Only `OutputMode.RICH` and `RichDisplay` need it.

**Q: What about the existing `tqdm` dependency?**
A: `tqdm` stays for `OutputMode.PROGRESS` (the simple single-bar case). It's already a dependency. `rich` adds the multi-bar capability on top.
