"""Minimal tests for Portfolio.clone() that avoid state machine complexities."""

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


def test_clone_method_exists(portfolio):
    """Test that clone method exists."""
    assert hasattr(portfolio, "clone")
    assert callable(portfolio.clone)


def test_clone_creates_different_object(portfolio):
    """Test that clone creates a new object."""
    cloned = portfolio.clone()

    assert cloned is not portfolio
    assert isinstance(cloned, Portfolio)


def test_clone_preserves_basic_state(portfolio):
    """Test that clone preserves basic state."""
    cloned = portfolio.clone()

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


def test_clone_has_independent_dataframes(portfolio):
    """Test that clone has independent DataFrames."""
    cloned = portfolio.clone()

    # DataFrames should be different objects
    assert cloned.history is not portfolio.history
    assert cloned.transactions is not portfolio.transactions
    assert cloned.holdings is not portfolio.holdings
    assert cloned._states is not portfolio._states


def test_multiple_clones(portfolio):
    """Test creating multiple clones from the same portfolio."""
    clone1 = portfolio.clone()
    clone2 = portfolio.clone()
    clone3 = portfolio.clone()

    # All should be independent
    assert clone1 is not clone2
    assert clone1 is not clone3
    assert clone2 is not clone3

    # All should have same state
    assert clone1.cash == clone2.cash == clone3.cash == portfolio.cash
    assert (
        clone1.current_period
        == clone2.current_period
        == clone3.current_period
        == portfolio.current_period
    )


def test_clone_preserves_holdings_shape(portfolio):
    """Test that clone preserves holdings DataFrame shape."""
    cloned = portfolio.clone()

    assert cloned.holdings.shape == portfolio.holdings.shape
    assert list(cloned.holdings.columns) == list(portfolio.holdings.columns)
    assert len(cloned.holdings.index) == len(portfolio.holdings.index)


def test_clone_preserves_history_shape(portfolio):
    """Test that clone preserves history DataFrame shape."""
    cloned = portfolio.clone()

    assert cloned.history.shape == portfolio.history.shape
    assert list(cloned.history.columns) == list(portfolio.history.columns)
    assert len(cloned.history.index) == len(portfolio.history.index)


def test_clone_preserves_state_series(portfolio):
    """Test that clone preserves the state series."""
    cloned = portfolio.clone()

    assert len(cloned._states) == len(portfolio._states)
    assert (
        cloned._states[cloned.current_period]
        == portfolio._states[portfolio.current_period]
    )
