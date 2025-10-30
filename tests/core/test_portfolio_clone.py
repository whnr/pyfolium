import pandas as pd
import pytest

from pyfolium.core import Asset, AssetUniverse, FeeConfig, Portfolio, TaxConfig


@pytest.fixture
def asset_universe():
    universe = AssetUniverse(data_frequency="D")
    dates = pd.period_range(start="2020-01-01", end="2020-01-10", freq="D")
    data = pd.DataFrame(index=dates, data={"price": 100.0, "income": 1.0})
    Asset("AAPL", universe, data)
    Asset("GOOGL", universe, data)
    return universe


@pytest.fixture
def portfolio(asset_universe):
    tax_config = TaxConfig(short_term_rate=0.2, long_term_rate=0.1)
    fee_config = FeeConfig(fixed_fee=1.0, percentage_fee=0.01)
    return Portfolio(asset_universe, tax_config=tax_config, fee_config=fee_config)


def test_clone_creates_independent_copy(portfolio):
    """Test that clone creates an independent copy."""
    portfolio.move_cash(10000)
    portfolio.update_history()
    portfolio.advance_period()

    cloned = portfolio.clone()

    # They should be different objects
    assert cloned is not portfolio
    assert cloned.history is not portfolio.history
    assert cloned.transactions is not portfolio.transactions
    assert cloned.holdings is not portfolio.holdings


def test_clone_preserves_state(portfolio):
    """Test that clone preserves all portfolio state."""
    portfolio.move_cash(10000)
    portfolio.update_history()
    portfolio.advance_period()

    portfolio.collect_income()
    portfolio.buy_asset("AAPL", 50)
    portfolio.update_history()
    portfolio.advance_period()

    cloned = portfolio.clone()

    # Check that state is preserved
    assert cloned.cash == portfolio.cash
    assert cloned.tax_owed == portfolio.tax_owed
    assert cloned.current_period == portfolio.current_period
    assert cloned._current_period_idx == portfolio._current_period_idx


def test_clone_preserves_configs(portfolio):
    """Test that clone preserves tax and fee configs."""
    cloned = portfolio.clone()

    assert cloned.tax_config.short_term_rate == portfolio.tax_config.short_term_rate
    assert cloned.tax_config.long_term_rate == portfolio.tax_config.long_term_rate
    assert cloned.fee_config.fixed_fee == portfolio.fee_config.fixed_fee
    assert cloned.fee_config.percentage_fee == portfolio.fee_config.percentage_fee


def test_clone_shares_asset_universe(portfolio):
    """Test that clone shares the same asset universe reference."""
    cloned = portfolio.clone()

    # AssetUniverse should be the same object (shared reference)
    assert cloned.asset_universe is portfolio.asset_universe


def test_clone_copies_dataframes(portfolio):
    """Test that clone deep copies all DataFrames."""
    portfolio.move_cash(10000)
    portfolio.update_history()
    portfolio.advance_period()

    cloned = portfolio.clone()

    # Modify cloned portfolio
    cloned.move_cash(5000)
    cloned.update_history()

    # Original should be unchanged
    assert cloned.cash != portfolio.cash


def test_clone_copies_transactions(portfolio):
    """Test that clone copies transaction history."""
    portfolio.move_cash(10000)
    portfolio.update_history()
    portfolio.advance_period()

    portfolio.collect_income()
    portfolio.buy_asset("AAPL", 50)

    cloned = portfolio.clone()

    assert len(cloned.transactions) == len(portfolio.transactions)
    assert cloned.transactions is not portfolio.transactions

    # Verify independence
    portfolio.buy_asset("GOOGL", 30)
    assert len(portfolio.transactions) > len(cloned.transactions)


def test_clone_copies_holdings(portfolio):
    """Test that clone copies holdings DataFrame."""
    portfolio.move_cash(10000)
    portfolio.update_history()
    portfolio.advance_period()

    portfolio.collect_income()
    portfolio.buy_asset("AAPL", 50)
    portfolio.update_history()
    portfolio.advance_period()

    cloned = portfolio.clone()

    # Check holdings are copied
    assert (
        cloned.holdings.loc[cloned.current_period, "AAPL"]
        == portfolio.holdings.loc[portfolio.current_period, "AAPL"]
    )

    # Verify independence
    portfolio.buy_asset("AAPL", 50)
    portfolio.update_history()
    portfolio.advance_period()

    assert (
        portfolio.holdings.loc[portfolio.current_period, "AAPL"]
        != cloned.holdings.loc[cloned.current_period, "AAPL"]
    )


def test_clone_copies_history(portfolio):
    """Test that clone copies history DataFrame."""
    portfolio.move_cash(10000)
    portfolio.update_history()
    portfolio.advance_period()

    cloned = portfolio.clone()

    # Check history is copied
    original_period = portfolio.current_period - 1
    assert (
        cloned.history.loc[original_period, "cash"]
        == portfolio.history.loc[original_period, "cash"]
    )

    # Verify independence
    portfolio.move_cash(5000)
    portfolio.update_history()

    assert (
        portfolio.history.loc[portfolio.current_period, "cash"]
        != cloned.history.loc[cloned.current_period, "cash"]
    )


def test_clone_preserves_state_machine(portfolio):
    """Test that clone preserves portfolio state machine."""
    portfolio.move_cash(10000)
    portfolio.update_history()
    portfolio.advance_period()

    # Leave portfolio in COLLECT_INCOME state
    cloned = portfolio.clone()

    # Clone should be in same state

    assert (
        cloned._states[cloned.current_period]
        == portfolio._states[portfolio.current_period]
    )


def test_cloned_portfolio_can_transact_independently(portfolio):
    """Test that cloned portfolio can transact independently."""
    portfolio.move_cash(10000)
    portfolio.update_history()
    portfolio.advance_period()

    cloned = portfolio.clone()

    # Both should be able to transact independently
    portfolio.collect_income()
    portfolio.buy_asset("AAPL", 30)
    portfolio.update_history()

    cloned.collect_income()
    cloned.buy_asset("GOOGL", 20)
    cloned.update_history()

    # Check they have different holdings
    assert portfolio.holdings.loc[portfolio.current_period, "AAPL"] == 30
    assert cloned.holdings.loc[cloned.current_period, "GOOGL"] == 20
    assert cloned.holdings.loc[cloned.current_period, "AAPL"] == 0


def test_multiple_clones(portfolio):
    """Test creating multiple clones from the same portfolio."""
    portfolio.move_cash(10000)
    portfolio.update_history()
    portfolio.advance_period()

    clone1 = portfolio.clone()
    clone2 = portfolio.clone()
    clone3 = portfolio.clone()

    # All should be independent
    assert clone1 is not clone2
    assert clone1 is not clone3
    assert clone2 is not clone3

    # All should have same state
    assert clone1.cash == clone2.cash == clone3.cash == portfolio.cash


def test_clone_of_portfolio_with_complex_state(portfolio):
    """Test cloning portfolio with transactions, holdings, and tax state."""
    portfolio.move_cash(100000)
    portfolio.update_history()
    portfolio.advance_period()

    # Build up complex state
    for _ in range(3):
        portfolio.collect_income()
        portfolio.buy_asset("AAPL", 10)
        portfolio.update_history()
        portfolio.advance_period()

    portfolio.collect_income()
    portfolio.sell_asset("AAPL", 15)
    portfolio.update_history()

    # Clone and verify
    cloned = portfolio.clone()

    assert cloned.cash == portfolio.cash
    assert cloned.tax_owed == portfolio.tax_owed
    assert len(cloned.transactions) == len(portfolio.transactions)
    assert (
        cloned.holdings.loc[cloned.current_period, "AAPL"]
        == portfolio.holdings.loc[portfolio.current_period, "AAPL"]
    )


def test_clone_preserves_tax_lots(portfolio):
    """Test that clone preserves tax lot tracking for capital gains."""
    portfolio.move_cash(100000)
    portfolio.update_history()
    portfolio.advance_period()

    # Create multiple tax lots
    portfolio.collect_income()
    portfolio.buy_asset("AAPL", 10)
    portfolio.update_history()
    portfolio.advance_period()

    portfolio.collect_income()
    portfolio.buy_asset("AAPL", 20)
    portfolio.update_history()
    portfolio.advance_period()

    cloned = portfolio.clone()

    # Both should have same tax lots
    original_lots = portfolio.transactions[
        (portfolio.transactions["type"] == "buy")
        & (portfolio.transactions["symbol"] == "AAPL")
    ]
    cloned_lots = cloned.transactions[
        (cloned.transactions["type"] == "buy")
        & (cloned.transactions["symbol"] == "AAPL")
    ]

    assert len(original_lots) == len(cloned_lots)
    assert (
        original_lots["lot_quantity_remaining"].sum()
        == cloned_lots["lot_quantity_remaining"].sum()
    )


def test_clone_at_different_periods(portfolio):
    """Test cloning portfolio at different points in time."""
    portfolio.move_cash(10000)
    portfolio.update_history()
    portfolio.advance_period()

    # Clone at period 1
    clone_period_1 = portfolio.clone()

    portfolio.collect_income()
    portfolio.buy_asset("AAPL", 50)
    portfolio.update_history()
    portfolio.advance_period()

    # Clone at period 2
    clone_period_2 = portfolio.clone()

    # They should be at different periods with different states
    assert clone_period_1.current_period < clone_period_2.current_period
    assert clone_period_1.cash > clone_period_2.cash  # Period 2 spent cash
    assert clone_period_2.holdings.loc[clone_period_2.current_period, "AAPL"] == 50
