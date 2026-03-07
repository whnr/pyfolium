import pandas as pd
import pytest

from pyfolium.core import Asset, AssetUniverse, Portfolio
from pyfolium.logging import LogEntry, Severity
from pyfolium.strategy import BaseStrategy


class SimpleStrategy(BaseStrategy):
    def get_trades(self) -> list[tuple[str, float]]:
        return [("Stock", 100)]


class ConfiguredStrategy(BaseStrategy):
    """Strategy used for testing initial_cash and start_period storage."""

    def get_trades(self) -> list[tuple[str, float]]:
        return []


@pytest.fixture
def asset_universe():
    universe = AssetUniverse(data_frequency="D")
    dates = pd.period_range(start="2020-01-01", end="2020-01-10", freq="D")
    data = pd.DataFrame(index=dates, data={"price": 100.0, "income": 0.0})
    Asset("Stock", universe, data)
    return universe


@pytest.fixture
def portfolio(asset_universe):
    return Portfolio(asset_universe=asset_universe)


@pytest.fixture
def strategy(portfolio):
    return SimpleStrategy(portfolio)


def test_strategy_initialization(strategy, portfolio):
    """Test basic strategy initialization and attributes"""
    assert strategy.portfolio == portfolio
    assert strategy.asset_universe == portfolio.asset_universe
    assert isinstance(strategy.parameters, dict)
    assert list(strategy.trades_df.columns) == [
        "period",
        "symbol",
        "quantity",
        "executed_quantity",
        "category",
        "success",
    ]


def test_record_trade(strategy):
    """Test trade recording functionality"""
    strategy._record_trade("Stock", 100, 100, "test", True)

    trade = strategy.trades_df.iloc[0]
    assert trade["symbol"] == "Stock"
    assert trade["quantity"] == 100
    assert trade["executed_quantity"] == 100
    assert trade["category"] == "test"
    assert trade["success"]
    assert trade["period"] == strategy.portfolio.current_period


def test_get_trades(strategy):
    trades = strategy.get_trades()

    assert trades == [("Stock", 100)]


def test_get_trades_must_be_implemented():
    """Test that get_trades is required"""

    class IncompleteStrategy(BaseStrategy):
        pass

    with pytest.raises(TypeError):
        IncompleteStrategy(portfolio)


def test_execute_trades_calls_portfolio(strategy, mocker):
    """Test that execute_trades properly calls portfolio methods"""
    mock_buy = mocker.patch.object(strategy.portfolio, "buy_asset")
    mock_sell = mocker.patch.object(strategy.portfolio, "sell_asset")

    strategy.execute_trades([("Stock", 100), ("GOOGL", -50)])

    mock_buy.assert_called_once_with("Stock", 100)
    mock_sell.assert_called_once_with("GOOGL", 50)


def test_execute_trades_handles_valueerror(strategy, mocker):
    """Test that execute_trades handles ValueError properly."""
    # Mock the buy_asset method to raise a ValueError
    mock_buy = mocker.patch.object(
        strategy.portfolio, "buy_asset", side_effect=ValueError("Insufficient funds")
    )
    mock_record_trade = mocker.patch.object(strategy, "_record_trade")

    # Execute trades where one will trigger the ValueError
    trades = [("Stock", 100)]  # This will raise a ValueError
    strategy.execute_trades(trades)

    # Assert that buy_asset was called and raised a ValueError
    mock_buy.assert_called_once_with("Stock", 100)

    # Verify that _record_trade was called with success=False due to the exception
    mock_record_trade.assert_called_once_with("Stock", 100, 0, success=False)


def test_step_executes_trades(strategy, mocker):
    """Test that step calls get_trades and execute_trades"""
    mock_execute = mocker.patch.object(strategy, "execute_trades")
    strategy.step()
    mock_execute.assert_called_once_with([("Stock", 100)])


# ---------------------------------------------------------------------------
# Start condition attributes
# ---------------------------------------------------------------------------


def test_strategy_default_initial_cash_is_none(portfolio):
    """initial_cash defaults to None when not provided."""
    assert SimpleStrategy(portfolio).initial_cash is None


def test_strategy_default_start_period_is_none(portfolio):
    """start_period defaults to None when not provided."""
    assert SimpleStrategy(portfolio).start_period is None


def test_strategy_stores_initial_cash(portfolio):
    """initial_cash is stored as provided."""
    strategy = ConfiguredStrategy(portfolio, initial_cash=50000.0)
    assert strategy.initial_cash == 50000.0


def test_strategy_stores_start_period(portfolio, asset_universe):
    """start_period is stored as provided."""
    period = pd.Period("2020-01-05", freq="D")
    strategy = ConfiguredStrategy(portfolio, start_period=period)
    assert strategy.start_period == period


def test_strategy_parameters_unaffected_by_new_params(portfolio):
    """Providing initial_cash and start_period does not affect parameters dict."""
    period = pd.Period("2020-01-03", freq="D")
    strategy = ConfiguredStrategy(
        portfolio,
        parameters={"alpha": 0.5},
        initial_cash=10000.0,
        start_period=period,
    )
    assert strategy.parameters == {"alpha": 0.5}
    assert strategy.initial_cash == 10000.0
    assert strategy.start_period == period


# ---------------------------------------------------------------------------
# Strategy logging
# ---------------------------------------------------------------------------


def test_strategy_log_starts_empty(strategy):
    """Strategy _log is empty on initialization."""
    assert strategy._log == []


def test_strategy_log_creates_entry_with_correct_source(strategy):
    """log() creates a LogEntry with source='strategy'."""
    strategy.log(Severity.INFO, "test message")

    assert len(strategy._log) == 1
    entry = strategy._log[0]
    assert isinstance(entry, LogEntry)
    assert entry.source == "strategy"
    assert entry.severity == Severity.INFO
    assert entry.message == "test message"
    assert entry.data is None


def test_strategy_log_with_data(strategy):
    """log() attaches optional data dict."""
    strategy.log(Severity.DEBUG, "details", data={"key": "value"})

    entry = strategy._log[0]
    assert entry.data == {"key": "value"}


def test_strategy_log_uses_current_period(strategy):
    """log() records the portfolio's current_period."""
    strategy.log(Severity.WARNING, "watch out")

    entry = strategy._log[0]
    assert entry.period == strategy.portfolio.current_period


def test_strategy_log_has_monotonic_timestamp(strategy):
    """log() entries have increasing timestamps."""
    strategy.log(Severity.INFO, "first")
    strategy.log(Severity.INFO, "second")

    assert strategy._log[1].timestamp >= strategy._log[0].timestamp


def test_strategy_log_accumulates_multiple_entries(strategy):
    """Multiple log() calls accumulate in _log."""
    strategy.log(Severity.DEBUG, "a")
    strategy.log(Severity.INFO, "b")
    strategy.log(Severity.WARNING, "c")

    assert len(strategy._log) == 3
    assert [e.severity for e in strategy._log] == [
        Severity.DEBUG,
        Severity.INFO,
        Severity.WARNING,
    ]


def test_strategy_log_clearable(strategy):
    """_log can be cleared (as the runner does after draining)."""
    strategy.log(Severity.INFO, "will be drained")
    strategy._log.clear()

    assert strategy._log == []
