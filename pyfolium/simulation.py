"""Backtest simulation orchestration.

Provides BacktestRunner for automating backtest execution with hooks,
progress reporting, and error handling.
"""

import warnings
from collections import defaultdict
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from time import time

import pandas as pd


try:
    from tqdm import tqdm

    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

from .core import Portfolio, PortfolioState
from .strategy import BaseStrategy


@dataclass
class BacktestResult:
    """Container for backtest results.

    This is a lean data container that holds references to the portfolio and
    strategy after backtest completion, along with execution metadata.

    All analysis (returns, Sharpe ratio, drawdowns, etc.) should be calculated
    by the user from portfolio.history and portfolio.transactions.

    Attributes:
        portfolio: Portfolio instance after backtest completion
        strategy: Strategy instance after backtest completion
        start_period: First period of the backtest
        end_period: Last period of the backtest
        total_periods: Number of periods simulated
        execution_time: Wall-clock time in seconds
        errors: List of (period, exception) tuples for errors encountered
    """

    portfolio: Portfolio
    strategy: BaseStrategy
    start_period: pd.Period
    end_period: pd.Period
    total_periods: int
    execution_time: float
    errors: list[tuple[pd.Period, Exception]] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Returns True if backtest completed without errors."""
        return len(self.errors) == 0

    def __repr__(self) -> str:
        error_str = f", {len(self.errors)} errors" if self.errors else ""
        return (
            f"BacktestResult({self.start_period} to {self.end_period}, "
            f"{self.total_periods} periods, {self.execution_time:.2f}s{error_str})"
        )


class BacktestRunner:
    """Orchestrates backtest execution with hooks for customization.

    This class automates the period-by-period execution loop for backtesting,
    handling income collection, strategy execution, history updates, and
    period advancement.

    The runner enforces the Portfolio state machine:
        COLLECT_INCOME → TRANSACT → DONE → advance_period → COLLECT_INCOME

    Hooks can be registered for the following events:
        - 'period_start': Called at the beginning of each period
        - 'period_end': Called after update_history() but before advance_period()
        - 'backtest_start': Called before the first period
        - 'backtest_end': Called after the last period
        - 'error': Called when an exception occurs during a period

    Hook callbacks should accept the BacktestRunner instance as their only argument.

    Attributes:
        portfolio: Portfolio being simulated
        strategy: Strategy executing trades
        start_period: First period to simulate (None = portfolio's first period)
        end_period: Last period to simulate (None = portfolio's last period)
        current_period: Current period being processed (None before run)

    Example:
        Basic usage::

            runner = BacktestRunner(portfolio, strategy)
            result = runner.run()

        With custom logging::

            def log_cash(runner):
                print(f"{runner.current_period}: ${runner.portfolio.cash:,.2f}")

            runner = BacktestRunner(portfolio, strategy)
            runner.register_hook('period_end', log_cash)
            result = runner.run()

        Step-by-step execution::

            runner = BacktestRunner(portfolio, strategy)
            runner.run_period()  # Execute first period
            runner.run_period()  # Execute second period
            # ... etc
    """

    def __init__(
        self,
        portfolio: Portfolio,
        strategy: BaseStrategy,
        *,
        start_period: pd.Period | None = None,
        end_period: pd.Period | None = None,
    ):
        """Initialize the BacktestRunner.

        Args:
            portfolio: Portfolio instance to simulate
            strategy: Strategy instance to execute trades
            start_period: Optional start period (default: portfolio's current_period)
            end_period: Optional end period (default: last period in universe)

        Raises:
            ValueError: If start_period > end_period
            ValueError: If periods are outside the portfolio's universe range
        """
        self.portfolio = portfolio
        self.strategy = strategy

        # Determine period range
        universe_periods = portfolio.asset_universe.get_period_index_range()
        self.start_period = start_period or portfolio.current_period
        self.end_period = end_period or universe_periods[-1]

        # Validate period range
        if self.start_period > self.end_period:
            raise ValueError(
                f"start_period {self.start_period} is after "
                f"end_period {self.end_period}"
            )
        if self.start_period not in universe_periods:
            raise ValueError(
                f"start_period {self.start_period} not in asset universe period range"
            )
        if self.end_period not in universe_periods:
            raise ValueError(
                f"end_period {self.end_period} not in asset universe period range"
            )

        # Advance portfolio to start_period if needed
        while portfolio.current_period < self.start_period:
            try:
                # Skip periods before start by just advancing
                # pandas-stubs limitation with Period indexing
                if portfolio._states[portfolio.current_period] != PortfolioState.DONE:  # type: ignore[call-overload]
                    # Need to complete the current period first
                    portfolio.collect_income()
                    portfolio.update_history()
                portfolio.advance_period()
            except StopIteration as e:
                raise ValueError(
                    f"Cannot advance to start_period {self.start_period}"
                ) from e

        # State tracking
        self.current_period: pd.Period | None = None
        self._errors: list[tuple[pd.Period, Exception]] = []
        self._hooks: dict[str, list[Callable]] = defaultdict(list)
        self._periods_completed = 0

    def register_hook(self, event: str, callback: Callable) -> None:
        """Register a callback for a specific event.

        Args:
            event: Event name ('period_start', 'period_end', 'backtest_start',
                   'backtest_end', 'error')
            callback: Callable that accepts the BacktestRunner as its only argument

        Example:
            def my_hook(runner):
                print(f"Period: {runner.current_period}")

            runner.register_hook('period_end', my_hook)
        """
        valid_events = {
            "period_start",
            "period_end",
            "backtest_start",
            "backtest_end",
            "error",
        }
        if event not in valid_events:
            raise ValueError(f"Invalid event '{event}'. Must be one of {valid_events}")
        self._hooks[event].append(callback)

    def _trigger_hooks(self, event: str) -> None:
        """Trigger all hooks registered for an event."""
        for callback in self._hooks[event]:
            try:
                callback(self)
            except Exception as e:
                warnings.warn(
                    f"Hook for event '{event}' raised exception: {e}", stacklevel=2
                )

    def run_period(self) -> None:
        """Execute a single period of the backtest.

        This method performs the complete period cycle:
        1. Trigger 'period_start' hooks
        2. Collect income
        3. Execute strategy
        4. Update history
        5. Trigger 'period_end' hooks
        6. Advance to next period

        If an error occurs, it's caught, stored, and 'error' hooks are triggered.
        The portfolio state may be inconsistent after an error.

        Raises:
            StopIteration: If end of backtest period range is reached
            RuntimeError: If portfolio is in an invalid state
        """
        self.current_period = self.portfolio.current_period

        # Check if we've reached the end
        if self.current_period > self.end_period:
            raise StopIteration("End of backtest period range reached")

        self._trigger_hooks("period_start")

        try:
            # Execute the standard period cycle
            self.portfolio.collect_income()
            self.strategy.step()
            self.portfolio.update_history()

            self._trigger_hooks("period_end")

            self._periods_completed += 1

            # Advance to next period
            # If we just completed the end_period, we're done
            if self.current_period >= self.end_period:
                raise StopIteration("Completed all periods")

            # End of portfolio history is expected - suppress StopIteration
            with suppress(StopIteration):
                self.portfolio.advance_period()

        except StopIteration:
            # Let StopIteration pass through - it's how we exit the loop
            raise
        except Exception as e:
            # Store error and trigger error hooks
            self._errors.append((self.current_period, e))
            self._trigger_hooks("error")

            # Warn but continue
            warnings.warn(
                f"Error in period {self.current_period}: {e}. "
                f"Continuing with next period...",
                stacklevel=2,
            )

            # Try to advance anyway to avoid getting stuck
            try:
                # Force state to DONE if we're stuck
                self.portfolio._states[self.current_period] = PortfolioState.DONE
                self.portfolio.advance_period()
            except (StopIteration, RuntimeError):
                # Can't recover, re-raise
                raise RuntimeError(
                    f"Cannot recover from error in period {self.current_period}. "
                    f"Portfolio may be in inconsistent state."
                ) from e

    def run(self, *, progress: bool = False) -> BacktestResult:
        """Execute the complete backtest simulation.

        Args:
            progress: If True, show progress bar (requires tqdm)

        Returns:
            BacktestResult containing portfolio, strategy, and metadata

        Example:
            result = runner.run(progress=True)
            print(f"Completed {result.total_periods} periods in "
                  f"{result.execution_time:.2f}s")
        """
        # Calculate total periods to run
        universe_periods = self.portfolio.asset_universe.get_period_index_range()
        # get_loc returns int for unique labels (periods are unique in PeriodIndex)
        start_idx: int = universe_periods.get_loc(self.start_period)  # type: ignore[assignment]
        end_idx: int = universe_periods.get_loc(self.end_period)  # type: ignore[assignment]
        total_periods: int = end_idx - start_idx + 1

        # Trigger start hooks
        self._trigger_hooks("backtest_start")

        # Setup progress bar if requested
        if progress:
            if not TQDM_AVAILABLE:
                warnings.warn(
                    "Progress bar requested but tqdm is not installed. "
                    "Install with: pip install tqdm",
                    stacklevel=2,
                )
                pbar = None
            else:
                pbar = tqdm(
                    total=int(total_periods),
                    desc="Running backtest",
                    unit="period",
                )
        else:
            pbar = None

        # Execute the backtest
        start_time = time()
        try:
            while True:
                try:
                    self.run_period()
                    if pbar:
                        pbar.update(1)
                except StopIteration:
                    # Normal completion
                    break
        finally:
            if pbar:
                pbar.close()

        execution_time = time() - start_time

        # Trigger end hooks
        self._trigger_hooks("backtest_end")

        # Create result
        result = BacktestResult(
            portfolio=self.portfolio,
            strategy=self.strategy,
            start_period=self.start_period,
            end_period=self.end_period,
            total_periods=self._periods_completed,
            execution_time=execution_time,
            errors=self._errors.copy(),
        )

        return result

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        # No cleanup needed for now, but placeholder for future
        # (e.g., closing database connections, flushing logs, etc.)
        return False  # Don't suppress exceptions
