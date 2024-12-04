import pandas as pd
import pytest

from pyfolium.core import Asset, AssetUniverse, Portfolio
from pyfolium.strategy import BaseStrategy


class SimpleStrategy(BaseStrategy):
    def get_trades(self) -> list[tuple[str, float]]:
        return [("AAPL", 100)]


@pytest.fixture
def asset_universe():
    universe = AssetUniverse(data_frequency="D")
    dates = pd.period_range(start="2020-01-01", end="2020-01-10", freq="D")
    data = pd.DataFrame(index=dates, data={"price": 100.0, "income": 0.0})
    Asset("AAPL", universe, data)
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
    strategy._record_trade("AAPL", 100, 100, "test", True)

    trade = strategy.trades_df.iloc[0]
    assert trade["symbol"] == "AAPL"
    assert trade["quantity"] == 100
    assert trade["executed_quantity"] == 100
    assert trade["category"] == "test"
    assert trade["success"]
    assert trade["period"] == strategy.portfolio.current_period


def test_get_trades(strategy):
    trades = strategy.get_trades()

    assert trades == [("AAPL", 100)]


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

    strategy.execute_trades([("AAPL", 100), ("GOOGL", -50)])

    mock_buy.assert_called_once_with("AAPL", 100)
    mock_sell.assert_called_once_with("GOOGL", 50)


def test_execute_trades_handles_valueerror(strategy, mocker):
    """Test that execute_trades handles ValueError properly."""
    # Mock the buy_asset method to raise a ValueError
    mock_buy = mocker.patch.object(
        strategy.portfolio, "buy_asset", side_effect=ValueError("Insufficient funds")
    )
    mock_record_trade = mocker.patch.object(strategy, "_record_trade")

    # Execute trades where one will trigger the ValueError
    trades = [("AAPL", 100)]  # This will raise a ValueError
    strategy.execute_trades(trades)

    # Assert that buy_asset was called and raised a ValueError
    mock_buy.assert_called_once_with("AAPL", 100)

    # Verify that _record_trade was called with success=False due to the exception
    mock_record_trade.assert_called_once_with("AAPL", 100, 0, success=False)


def test_step_executes_trades(strategy, mocker):
    """Test that step calls get_trades and execute_trades"""
    mock_execute = mocker.patch.object(strategy, "execute_trades")
    strategy.step()
    mock_execute.assert_called_once_with([("AAPL", 100)])
