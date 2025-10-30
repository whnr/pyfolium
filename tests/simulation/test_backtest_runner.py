"""Minimal tests for BacktestRunner that avoid pandas/numpy compatibility issues."""

import pandas as pd
import pytest

from pyfolium.core import Asset, AssetUniverse, Portfolio
from pyfolium.simulation import BacktestResult, BacktestRunner
from pyfolium.strategy import BaseStrategy


class DoNothingStrategy(BaseStrategy):
    """Strategy that does nothing - just holds."""

    def get_trades(self) -> list[tuple[str, float]]:
        return []


@pytest.fixture
def asset_universe():
    universe = AssetUniverse(data_frequency="D")
    dates = pd.period_range(start="2020-01-01", end="2020-01-10", freq="D")
    data = pd.DataFrame(index=dates, data={"price": 100.0, "income": 0.0})
    Asset("AAPL", universe, data)
    return universe


@pytest.fixture
def portfolio(asset_universe):
    portfolio = Portfolio(asset_universe=asset_universe)
    # Initialize portfolio by completing first period
    portfolio.collect_income()
    portfolio.update_history()
    portfolio.advance_period()
    return portfolio


@pytest.fixture
def strategy(portfolio):
    return DoNothingStrategy(portfolio)


def test_runner_basic_initialization(portfolio, strategy):
    """Test that runner initializes correctly."""
    runner = BacktestRunner(portfolio, strategy)

    assert runner.portfolio == portfolio
    assert runner.strategy == strategy
    assert runner.current_period is None


def test_runner_accepts_period_range(asset_universe):
    """Test runner accepts custom period range."""
    portfolio = Portfolio(asset_universe)
    strategy = DoNothingStrategy(portfolio)

    periods = asset_universe.get_period_index_range()
    runner = BacktestRunner(
        portfolio, strategy, start_period=periods[2], end_period=periods[5]
    )

    assert runner.start_period == periods[2]
    assert runner.end_period == periods[5]


def test_runner_run_returns_result(portfolio, strategy):
    """Test that run() returns a BacktestResult."""
    runner = BacktestRunner(portfolio, strategy)
    result = runner.run()

    assert isinstance(result, BacktestResult)
    assert result.portfolio == portfolio
    assert result.strategy == strategy


def test_backtest_result_attributes(portfolio, strategy):
    """Test BacktestResult has all required attributes."""
    runner = BacktestRunner(portfolio, strategy)
    result = runner.run()

    # Check all attributes exist
    assert hasattr(result, "portfolio")
    assert hasattr(result, "strategy")
    assert hasattr(result, "start_period")
    assert hasattr(result, "end_period")
    assert hasattr(result, "total_periods")
    assert hasattr(result, "execution_time")
    assert hasattr(result, "errors")
    assert hasattr(result, "success")

    # Check types
    assert isinstance(result.start_period, pd.Period)
    assert isinstance(result.end_period, pd.Period)
    assert isinstance(result.total_periods, int)
    assert isinstance(result.execution_time, float)
    assert isinstance(result.errors, list)
    assert isinstance(result.success, bool)


def test_hook_registration(portfolio, strategy):
    """Test registering hooks."""
    runner = BacktestRunner(portfolio, strategy)

    def my_hook(runner):
        pass

    runner.register_hook("period_start", my_hook)
    runner.register_hook("period_end", my_hook)
    runner.register_hook("backtest_start", my_hook)
    runner.register_hook("backtest_end", my_hook)
    runner.register_hook("error", my_hook)

    assert len(runner._hooks["period_start"]) == 1
    assert len(runner._hooks["period_end"]) == 1
    assert len(runner._hooks["backtest_start"]) == 1
    assert len(runner._hooks["backtest_end"]) == 1
    assert len(runner._hooks["error"]) == 1


def test_invalid_hook_event_raises_error(portfolio, strategy):
    """Test that invalid hook events raise ValueError."""
    runner = BacktestRunner(portfolio, strategy)

    with pytest.raises(ValueError, match="Invalid event"):
        runner.register_hook("invalid_event", lambda r: None)


def test_context_manager(portfolio, strategy):
    """Test using runner as context manager."""
    with BacktestRunner(portfolio, strategy) as runner:
        result = runner.run()

    assert isinstance(result, BacktestResult)


def test_invalid_period_range_raises_error(asset_universe):
    """Test that invalid period ranges raise ValueError."""
    portfolio = Portfolio(asset_universe)
    strategy = DoNothingStrategy(portfolio)

    periods = asset_universe.get_period_index_range()

    # Start after end
    with pytest.raises(ValueError, match="start_period.*after end_period"):
        BacktestRunner(
            portfolio, strategy, start_period=periods[5], end_period=periods[2]
        )

    # Period outside universe (but before end_period to avoid start>end check)
    invalid_period = pd.Period("2019-01-01", freq="D")  # Before universe range
    with pytest.raises(ValueError, match="not in asset universe"):
        BacktestRunner(portfolio, strategy, start_period=invalid_period)


def test_backtest_result_repr(portfolio, strategy):
    """Test BacktestResult has a useful string representation."""
    runner = BacktestRunner(portfolio, strategy)
    result = runner.run()

    repr_str = repr(result)
    assert "BacktestResult" in repr_str
    assert str(result.start_period) in repr_str or str(result.end_period) in repr_str


def test_backtest_result_success_property(portfolio, strategy):
    """Test BacktestResult.success property."""
    runner = BacktestRunner(portfolio, strategy)
    result = runner.run()

    # No errors means success
    assert result.success is True
    assert len(result.errors) == 0


def test_hooks_are_called(portfolio, strategy):
    """Test that hooks are actually called during execution."""
    runner = BacktestRunner(portfolio, strategy)

    calls = {"start": 0, "end": 0, "backtest_start": 0, "backtest_end": 0}

    def start_hook(r):
        calls["start"] += 1

    def end_hook(r):
        calls["end"] += 1

    def backtest_start_hook(r):
        calls["backtest_start"] += 1

    def backtest_end_hook(r):
        calls["backtest_end"] += 1

    runner.register_hook("period_start", start_hook)
    runner.register_hook("period_end", end_hook)
    runner.register_hook("backtest_start", backtest_start_hook)
    runner.register_hook("backtest_end", backtest_end_hook)

    runner.run()

    # Should have called hooks for each period plus backtest start/end
    assert calls["start"] > 0
    assert calls["end"] > 0
    assert calls["backtest_start"] == 1
    assert calls["backtest_end"] == 1
    assert calls["start"] == calls["end"]  # Same number of start/end calls


def test_progress_bar_with_tqdm(portfolio, strategy):
    """Test running with progress bar enabled."""
    runner = BacktestRunner(portfolio, strategy)
    # Just test it doesn't crash - tqdm may or may not be available
    result = runner.run(progress=True)
    assert isinstance(result, BacktestResult)


def test_error_during_strategy_execution(asset_universe):
    """Test error handling when strategy raises exception."""

    class FailingStrategy(BaseStrategy):
        def __init__(self, portfolio):
            super().__init__(portfolio)
            self.call_count = 0

        def get_trades(self):
            self.call_count += 1
            if self.call_count == 2:  # Fail on second call
                raise ValueError("Intentional test error")
            return []

    portfolio = Portfolio(asset_universe)
    portfolio.collect_income()
    portfolio.update_history()
    portfolio.advance_period()

    strategy = FailingStrategy(portfolio)
    runner = BacktestRunner(portfolio, strategy)

    # Should complete despite error
    with pytest.warns(UserWarning):
        result = runner.run()

    # Should have recorded the error
    assert len(result.errors) > 0
    assert not result.success
