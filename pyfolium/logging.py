"""Structured logging types for backtest observability.

Provides severity levels, log entries, and output mode configuration
for BacktestRunner and strategy logging.
"""

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any

import pandas as pd


class Severity(IntEnum):
    """Log severity levels, ordered by importance.

    IntEnum so that ``>=`` comparisons work for filtering:
    ``entry.severity >= Severity.WARNING`` selects warnings and errors.
    """

    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40


@dataclass(frozen=True, slots=True)
class LogEntry:
    """Immutable, timestamped log record produced during a backtest.

    Attributes:
        severity: Importance level of the log entry.
        timestamp: Monotonic clock value (``time.monotonic()``).
        period: The portfolio period when this entry was created.
        source: Origin of the entry (``"runner"``, ``"strategy"``, ``"hook"``).
        message: Human-readable description.
        data: Optional structured payload (e.g. exception, trade details).
    """

    severity: Severity
    timestamp: float
    period: pd.Period
    source: str
    message: str
    data: dict[str, Any] | None = field(default=None)


class OutputMode(StrEnum):
    """Controls terminal output during ``BacktestRunner.run()``.

    ``str, Enum`` so values serialize cleanly and work in ``match``/``case``.
    """

    SILENT = "silent"
    SUMMARY = "summary"
    PROGRESS = "progress"
