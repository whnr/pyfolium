"""Minimal tests for BacktestRunner that avoid pandas/numpy compatibility issues."""

import pandas as pd
import pytest

from pyfolium.core import Asset, AssetUniverse, Portfolio
from pyfolium.simulation import BacktestResult, BacktestRunner
from pyfolium.strategy import BaseStrategy


class DoNothingStrategy(BaseStrategy):
    """Strategy that does nothing - just holds."""

    def __init__(self, portfolio, **kwargs):
        super().__init__(portfolio, **kwargs)

    def get_trades(self) -> list[tuple[str, float]]:
        return []


class CashCheckingStrategy(BaseStrategy):
    """Records portfolio cash at the moment get_trades() is first called."""

    def __init__(self, portfolio, **kwargs):
        super().__init__(portfolio, **kwargs)
        self.first_period_cash: float | None = None
        self._first_call = True

    def get_trades(self) -> list[tuple[str, float]]:
        if self._first_call:
            self.first_period_cash = self.portfolio.cash
            self._first_call = False
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
    """Lenient mode records errors and continues without corrupting state."""

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
    runner = BacktestRunner(portfolio, strategy, strict=False)

    # Should complete despite error
    with pytest.warns(UserWarning):
        result = runner.run()

    # Should have recorded the error
    assert len(result.errors) > 0
    assert not result.success


def test_strict_mode_raises_on_first_error(asset_universe):
    """strict=True (default) re-raises the first exception immediately."""

    class AlwaysFailingStrategy(BaseStrategy):
        def get_trades(self):
            raise ValueError("Intentional failure")

    portfolio = Portfolio(asset_universe)
    portfolio.collect_income()
    portfolio.update_history()
    portfolio.advance_period()

    strategy = AlwaysFailingStrategy(portfolio)
    runner = BacktestRunner(portfolio, strategy, strict=True)

    with pytest.raises(ValueError, match="Intentional failure"):
        runner.run()


def test_strict_is_default(asset_universe):
    """Verify strict=True is the default, not lenient mode."""

    class AlwaysFailingStrategy(BaseStrategy):
        def get_trades(self):
            raise ValueError("Intentional failure")

    portfolio = Portfolio(asset_universe)
    portfolio.collect_income()
    portfolio.update_history()
    portfolio.advance_period()

    strategy = AlwaysFailingStrategy(portfolio)
    runner = BacktestRunner(portfolio, strategy)  # no explicit strict=

    with pytest.raises(ValueError, match="Intentional failure"):
        runner.run()


def test_lenient_mode_history_remains_consistent(asset_universe):
    """After a lenient-mode error, the failed period still has a history row."""

    class FailOnPeriod2(BaseStrategy):
        def __init__(self, portfolio):
            super().__init__(portfolio)
            self.call_count = 0

        def get_trades(self):
            self.call_count += 1
            if self.call_count == 2:
                raise ValueError("Period 2 failure")
            return []

    portfolio = Portfolio(asset_universe)
    portfolio.collect_income()
    portfolio.update_history()
    portfolio.advance_period()

    strategy = FailOnPeriod2(portfolio)
    runner = BacktestRunner(portfolio, strategy, strict=False)

    with pytest.warns(UserWarning):
        result = runner.run()

    # History should have no NaN rows — the failed period must still be recorded
    assert not result.portfolio.history.isnull().all(axis=1).any(), (
        "Failed period left a missing history row"
    )


# ---------------------------------------------------------------------------
# Tests for start_period precedence
# ---------------------------------------------------------------------------


def test_runner_uses_strategy_start_period_when_runner_has_none(asset_universe):
    """When runner has no start_period, strategy.start_period is used."""
    portfolio = Portfolio(asset_universe)
    periods = asset_universe.get_period_index_range()
    target_start = periods[3]

    strategy = DoNothingStrategy(portfolio, start_period=target_start)
    runner = BacktestRunner(portfolio, strategy)

    assert runner.start_period == target_start


def test_runner_explicit_start_period_overrides_strategy(asset_universe):
    """Explicit runner start_period takes precedence over strategy.start_period."""
    portfolio = Portfolio(asset_universe)
    periods = asset_universe.get_period_index_range()

    strategy = DoNothingStrategy(portfolio, start_period=periods[3])
    runner = BacktestRunner(portfolio, strategy, start_period=periods[5])

    assert runner.start_period == periods[5]


def test_runner_falls_back_to_current_period_when_both_none(asset_universe):
    """When both runner and strategy start_period are None, portfolio.current_period is used."""
    portfolio = Portfolio(asset_universe)
    expected = portfolio.current_period

    runner = BacktestRunner(portfolio, DoNothingStrategy(portfolio))

    assert runner.start_period == expected


# ---------------------------------------------------------------------------
# Tests for initial_cash injection
# ---------------------------------------------------------------------------


def test_initial_cash_available_when_get_trades_runs(asset_universe):
    """initial_cash is injected before strategy.get_trades() on the first period."""
    portfolio = Portfolio(asset_universe)
    strategy = CashCheckingStrategy(portfolio, initial_cash=75000.0)

    BacktestRunner(portfolio, strategy).run()

    assert strategy.first_period_cash == pytest.approx(75000.0)


def test_initial_cash_injected_only_once(asset_universe):
    """initial_cash deposit appears exactly once in portfolio.transactions."""
    portfolio = Portfolio(asset_universe)
    strategy = DoNothingStrategy(portfolio, initial_cash=10000.0)

    BacktestRunner(portfolio, strategy).run()

    deposits = portfolio.transactions[portfolio.transactions["type"] == "deposit"]
    assert len(deposits) == 1
    assert float(deposits.iloc[0]["transaction_amount"]) == pytest.approx(10000.0)


def test_no_deposit_when_initial_cash_is_none(asset_universe):
    """When initial_cash is None (default), no deposit transaction is created."""
    portfolio = Portfolio(asset_universe)

    BacktestRunner(portfolio, DoNothingStrategy(portfolio)).run()

    deposits = portfolio.transactions[portfolio.transactions["type"] == "deposit"]
    assert len(deposits) == 0


def test_initial_cash_works_in_step_by_step_mode(asset_universe):
    """initial_cash is injected correctly when run_period() is used directly."""
    portfolio = Portfolio(asset_universe)
    strategy = CashCheckingStrategy(portfolio, initial_cash=25000.0)

    runner = BacktestRunner(portfolio, strategy)
    try:
        runner.run_period()
    except StopIteration:
        pass

    assert strategy.first_period_cash == pytest.approx(25000.0)


def test_initial_cash_not_reinjected_on_second_run_period(asset_universe):
    """initial_cash is not injected again on the second manual run_period() call."""
    portfolio = Portfolio(asset_universe)
    runner = BacktestRunner(portfolio, DoNothingStrategy(portfolio, initial_cash=5000.0))

    for _ in range(2):
        try:
            runner.run_period()
        except StopIteration:
            break

    deposits = portfolio.transactions[portfolio.transactions["type"] == "deposit"]
    assert len(deposits) == 1


def test_initial_cash_combined_with_strategy_start_period(asset_universe):
    """initial_cash is injected at the resolved start_period, not at period 0."""
    portfolio = Portfolio(asset_universe)
    periods = asset_universe.get_period_index_range()
    start = periods[3]

    strategy = CashCheckingStrategy(portfolio, initial_cash=42000.0, start_period=start)
    runner = BacktestRunner(portfolio, strategy)

    assert runner.start_period == start

    runner.run()

    assert strategy.first_period_cash == pytest.approx(42000.0)
    deposits = portfolio.transactions[portfolio.transactions["type"] == "deposit"]
    assert len(deposits) == 1
