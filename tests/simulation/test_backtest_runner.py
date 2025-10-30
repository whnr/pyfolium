import pandas as pd
import pytest

from pyfolium.core import Asset, AssetUniverse, Portfolio
from pyfolium.simulation import BacktestResult, BacktestRunner
from pyfolium.strategy import BaseStrategy


class BuyAndHoldStrategy(BaseStrategy):
    """Simple strategy that buys on first period and holds."""

    def __init__(self, portfolio, symbol="AAPL", quantity=100):
        super().__init__(portfolio, parameters={"symbol": symbol, "quantity": quantity})
        self.symbol = symbol
        self.quantity = quantity
        self.executed = False

    def get_trades(self) -> list[tuple[str, float]]:
        if not self.executed:
            self.executed = True
            return [(self.symbol, self.quantity)]
        return []


class RebalanceStrategy(BaseStrategy):
    """Strategy that trades every period."""

    def get_trades(self) -> list[tuple[str, float]]:
        # Buy 10 shares each period
        return [("AAPL", 10)]


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
    portfolio.collect_income()
    portfolio.move_cash(10000)  # Start with cash
    portfolio.update_history()
    portfolio.advance_period()
    return portfolio


@pytest.fixture
def strategy(portfolio):
    return BuyAndHoldStrategy(portfolio)


def test_runner_initialization(portfolio, strategy):
    """Test basic runner initialization."""
    runner = BacktestRunner(portfolio, strategy)

    assert runner.portfolio == portfolio
    assert runner.strategy == strategy
    assert runner.start_period == portfolio.current_period
    assert runner.end_period == portfolio.asset_universe.get_period_index_range()[-1]
    assert runner.current_period is None


def test_runner_custom_period_range(asset_universe):
    """Test runner with custom start and end periods."""
    portfolio = Portfolio(asset_universe)
    strategy = BuyAndHoldStrategy(portfolio)

    periods = asset_universe.get_period_index_range()
    start = periods[2]
    end = periods[5]

    runner = BacktestRunner(portfolio, strategy, start_period=start, end_period=end)

    assert runner.start_period == start
    assert runner.end_period == end


def test_runner_invalid_period_range(portfolio, strategy):
    """Test that invalid period ranges raise errors."""
    periods = portfolio.asset_universe.get_period_index_range()

    # Start after end
    with pytest.raises(ValueError, match="start_period.*after end_period"):
        BacktestRunner(
            portfolio, strategy, start_period=periods[5], end_period=periods[2]
        )

    # Period outside universe
    invalid_period = pd.Period("2030-01-01", freq="D")
    with pytest.raises(ValueError, match="not in asset universe"):
        BacktestRunner(portfolio, strategy, start_period=invalid_period)


def test_run_period_single_execution(portfolio, strategy):
    """Test executing a single period."""
    runner = BacktestRunner(portfolio, strategy)
    initial_period = portfolio.current_period

    runner.run_period()

    # Check that portfolio advanced
    assert portfolio.current_period > initial_period
    assert (
        runner.current_period == initial_period
    )  # Runner tracks the period we just completed
    assert runner._periods_completed == 1


def test_run_period_multiple_times(portfolio, strategy):
    """Test executing multiple periods manually."""
    runner = BacktestRunner(portfolio, strategy)
    initial_period = portfolio.current_period

    for _i in range(3):
        runner.run_period()

    assert runner._periods_completed == 3
    assert portfolio.current_period == initial_period + 3


def test_run_period_stops_at_end(portfolio, strategy):
    """Test that run_period raises StopIteration at the end."""
    periods = portfolio.asset_universe.get_period_index_range()
    runner = BacktestRunner(portfolio, strategy, end_period=periods[1])

    runner.run_period()  # Period 0

    # Next call should raise StopIteration
    with pytest.raises(StopIteration):
        runner.run_period()


def test_run_complete_backtest(portfolio, strategy):
    """Test running a complete backtest."""
    runner = BacktestRunner(portfolio, strategy)
    result = runner.run()

    assert isinstance(result, BacktestResult)
    assert result.portfolio == portfolio
    assert result.strategy == strategy
    assert result.total_periods > 0
    assert result.execution_time > 0
    assert result.success  # No errors


def test_run_with_limited_period_range(asset_universe):
    """Test running backtest with limited period range."""
    portfolio = Portfolio(asset_universe)
    portfolio.move_cash(10000)
    portfolio.update_history()
    portfolio.advance_period()

    strategy = BuyAndHoldStrategy(portfolio)

    periods = asset_universe.get_period_index_range()
    runner = BacktestRunner(
        portfolio, strategy, start_period=periods[1], end_period=periods[4]
    )
    result = runner.run()

    assert result.start_period == periods[1]
    assert result.end_period == periods[4]
    assert result.total_periods == 4  # Periods 1,2,3,4


def test_backtest_result_attributes(portfolio, strategy):
    """Test that BacktestResult contains correct attributes."""
    runner = BacktestRunner(portfolio, strategy)
    result = runner.run()

    assert hasattr(result, "portfolio")
    assert hasattr(result, "strategy")
    assert hasattr(result, "start_period")
    assert hasattr(result, "end_period")
    assert hasattr(result, "total_periods")
    assert hasattr(result, "execution_time")
    assert hasattr(result, "errors")
    assert hasattr(result, "success")


def test_backtest_result_repr(portfolio, strategy):
    """Test BacktestResult string representation."""
    runner = BacktestRunner(portfolio, strategy)
    result = runner.run()

    repr_str = repr(result)
    assert "BacktestResult" in repr_str
    assert str(result.start_period) in repr_str
    assert str(result.end_period) in repr_str


def test_strategy_execution_during_backtest(asset_universe):
    """Test that strategy is properly executed during backtest."""
    portfolio = Portfolio(asset_universe)
    portfolio.move_cash(100000)
    portfolio.update_history()
    portfolio.advance_period()

    strategy = BuyAndHoldStrategy(portfolio, symbol="AAPL", quantity=50)

    runner = BacktestRunner(portfolio, strategy)
    result = runner.run()

    # Check that trades were executed
    assert len(strategy.trades_df) > 0
    assert strategy.trades_df.iloc[0]["symbol"] == "AAPL"
    assert strategy.trades_df.iloc[0]["quantity"] == 50

    # Check that portfolio has holdings
    assert result.portfolio.holdings.loc[result.end_period, "AAPL"] == 50


def test_hook_registration(portfolio, strategy):
    """Test registering hooks."""
    runner = BacktestRunner(portfolio, strategy)

    def my_hook(runner):
        pass

    runner.register_hook("period_start", my_hook)
    runner.register_hook("period_end", my_hook)

    assert len(runner._hooks["period_start"]) == 1
    assert len(runner._hooks["period_end"]) == 1


def test_hook_invalid_event(portfolio, strategy):
    """Test that invalid hook events raise errors."""
    runner = BacktestRunner(portfolio, strategy)

    with pytest.raises(ValueError, match="Invalid event"):
        runner.register_hook("invalid_event", lambda r: None)


def test_hooks_are_called(portfolio, strategy):
    """Test that hooks are called during execution."""
    runner = BacktestRunner(portfolio, strategy)

    call_count = {"start": 0, "end": 0}

    def start_hook(runner):
        call_count["start"] += 1

    def end_hook(runner):
        call_count["end"] += 1

    runner.register_hook("period_start", start_hook)
    runner.register_hook("period_end", end_hook)

    runner.run_period()
    runner.run_period()

    assert call_count["start"] == 2
    assert call_count["end"] == 2


def test_backtest_start_end_hooks(portfolio, strategy):
    """Test that backtest_start and backtest_end hooks are called."""
    runner = BacktestRunner(portfolio, strategy)

    called = {"start": False, "end": False}

    def start_hook(runner):
        called["start"] = True

    def end_hook(runner):
        called["end"] = True

    runner.register_hook("backtest_start", start_hook)
    runner.register_hook("backtest_end", end_hook)

    runner.run()

    assert called["start"]
    assert called["end"]


def test_hook_receives_runner_instance(portfolio, strategy):
    """Test that hooks receive the runner instance."""
    runner = BacktestRunner(portfolio, strategy)

    received_runner = None

    def my_hook(r):
        nonlocal received_runner
        received_runner = r

    runner.register_hook("period_start", my_hook)
    runner.run_period()

    assert received_runner is runner


def test_hook_can_access_portfolio_state(portfolio, strategy):
    """Test that hooks can access portfolio state."""
    runner = BacktestRunner(portfolio, strategy)

    periods_seen = []

    def track_period(runner):
        periods_seen.append(runner.current_period)

    runner.register_hook("period_start", track_period)
    runner.run()

    assert len(periods_seen) > 0
    assert all(isinstance(p, pd.Period) for p in periods_seen)


def test_error_handling_stores_errors(asset_universe):
    """Test that errors during execution are stored."""

    class FailingStrategy(BaseStrategy):
        def get_trades(self):
            raise ValueError("Intentional error")

    portfolio = Portfolio(asset_universe)
    portfolio.move_cash(10000)
    portfolio.update_history()
    portfolio.advance_period()

    strategy = FailingStrategy(portfolio)
    runner = BacktestRunner(portfolio, strategy)

    # Run should complete despite errors
    with pytest.warns(UserWarning):
        result = runner.run()

    assert len(result.errors) > 0
    assert not result.success


def test_error_hook_is_called(asset_universe):
    """Test that error hooks are called when errors occur."""

    class FailingStrategy(BaseStrategy):
        def get_trades(self):
            raise ValueError("Intentional error")

    portfolio = Portfolio(asset_universe)
    portfolio.move_cash(10000)
    portfolio.update_history()
    portfolio.advance_period()

    strategy = FailingStrategy(portfolio)
    runner = BacktestRunner(portfolio, strategy)

    error_count = {"count": 0}

    def error_hook(runner):
        error_count["count"] += 1

    runner.register_hook("error", error_hook)

    with pytest.warns(UserWarning):
        runner.run()

    assert error_count["count"] > 0


def test_context_manager(portfolio, strategy):
    """Test using runner as context manager."""
    with BacktestRunner(portfolio, strategy) as runner:
        result = runner.run()

    assert isinstance(result, BacktestResult)


def test_multiple_strategies_on_cloned_portfolios(asset_universe):
    """Test running different strategies on cloned portfolios."""
    base_portfolio = Portfolio(asset_universe)
    base_portfolio.move_cash(100000)
    base_portfolio.update_history()
    base_portfolio.advance_period()

    # Clone portfolios for independent backtests
    portfolio1 = base_portfolio.clone()
    portfolio2 = base_portfolio.clone()

    strategy1 = BuyAndHoldStrategy(portfolio1, quantity=50)
    strategy2 = BuyAndHoldStrategy(portfolio2, quantity=100)

    result1 = BacktestRunner(portfolio1, strategy1).run()
    result2 = BacktestRunner(portfolio2, strategy2).run()

    # Verify they executed independently
    assert result1.portfolio.holdings.loc[result1.end_period, "AAPL"] == 50
    assert result2.portfolio.holdings.loc[result2.end_period, "AAPL"] == 100


def test_runner_advances_portfolio_to_start_period(asset_universe):
    """Test that runner advances portfolio to start_period if needed."""
    portfolio = Portfolio(asset_universe)
    portfolio.move_cash(10000)
    portfolio.update_history()
    portfolio.advance_period()

    # Portfolio is at period 1

    periods = asset_universe.get_period_index_range()
    start_period = periods[3]  # Start at period 3

    strategy = BuyAndHoldStrategy(portfolio)
    BacktestRunner(portfolio, strategy, start_period=start_period)

    # Runner should have advanced portfolio to start_period
    assert portfolio.current_period == start_period


def test_income_collection_during_backtest(asset_universe):
    """Test that income is collected during backtest."""
    # Create asset with income
    dates = pd.period_range(start="2020-01-01", end="2020-01-10", freq="D")
    data = pd.DataFrame(index=dates, data={"price": 100.0, "income": 1.0})
    universe = AssetUniverse(data_frequency="D")
    Asset("DIV", universe, data)

    portfolio = Portfolio(universe)
    portfolio.move_cash(10000)
    portfolio.update_history()
    portfolio.advance_period()

    # Buy asset
    portfolio.collect_income()
    portfolio.buy_asset("DIV", 100)
    portfolio.update_history()
    portfolio.advance_period()

    initial_cash = portfolio.cash

    # Run backtest - should collect income
    class HoldStrategy(BaseStrategy):
        def get_trades(self):
            return []

    strategy = HoldStrategy(portfolio)
    runner = BacktestRunner(portfolio, strategy)
    result = runner.run()

    # Cash should increase due to income
    assert result.portfolio.cash > initial_cash


def test_progress_bar_warning_without_tqdm(portfolio, strategy, mocker):
    """Test that warning is raised when progress=True but tqdm not available."""
    # Mock TQDM_AVAILABLE to False
    import pyfolium.simulation

    original_tqdm = pyfolium.simulation.TQDM_AVAILABLE
    pyfolium.simulation.TQDM_AVAILABLE = False

    try:
        runner = BacktestRunner(portfolio, strategy)
        with pytest.warns(UserWarning, match="tqdm is not installed"):
            runner.run(progress=True)
    finally:
        pyfolium.simulation.TQDM_AVAILABLE = original_tqdm
