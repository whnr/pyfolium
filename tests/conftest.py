import numpy as np
import pandas as pd
import pytest

from hhfk.core import Asset, AssetUniverse, FeeConfig, Portfolio, TaxConfig


@pytest.fixture
def tax_config():
    """Fixture for standard tax configuration"""
    return TaxConfig(
        short_term_rate=0.20,
        long_term_rate=0.10,
    )


@pytest.fixture
def fee_config():
    """Fixture for standard fee configuration"""
    return FeeConfig(
        fixed_fee=1.0,
        percentage_fee=0.01,
        minimum_fee=5.0,
        maximum_fee=20.0,
    )


@pytest.fixture
def day_date_range():
    """Fixture providing a date range for testing"""
    periodIndex = pd.period_range("2023-01-01", periods=365 * 2, freq="D")
    return periodIndex


@pytest.fixture
def month_date_range():
    """Fixture providing a date range for testing"""
    periodIndex = pd.period_range("2023-01-01", periods=24, freq="M")
    return periodIndex


@pytest.fixture
def sample_asset_universe():
    """An empty asset universe with a base frequency of 'D'"""
    return AssetUniverse(data_frequency="D")


@pytest.fixture
def sample_asset_data(day_date_range):
    """Fixture providing sample asset data with price and dividend history"""
    np.random.seed(42)
    price_data = 100 * (1 + np.random.randn(len(day_date_range)).cumsum() * 0.02)
    dividend_data = np.zeros(len(day_date_range))
    dividend_data[::90] = price_data[::90] * 0.01  # Quarterly dividends

    return pd.DataFrame(
        {"price": price_data, "dividend": dividend_data}, index=day_date_range
    )


@pytest.fixture
def sample_asset(sample_asset_data, sample_asset_universe):
    """Fixture providing a sample asset with price and dividend data"""
    return Asset(
        symbol="TEST",
        assetUniverse=sample_asset_universe,
        data=sample_asset_data,
        metadata={"description": "test asset", "type": "equity"},
        price_column="price",
        income_column="dividend",
    )


@pytest.fixture
def asset_universe_with_assets(sample_asset_universe, sample_asset_data):
    """Fixture providing a sample asset universe with assets"""
    Asset(
        symbol="TEST",
        assetUniverse=sample_asset_universe,
        data=sample_asset_data,
        metadata={"description": "test asset", "type": "equity"},
        price_column="price",
        income_column="dividend",
    )
    Asset(
        symbol="TEST2",
        assetUniverse=sample_asset_universe,
        data=sample_asset_data,
        metadata={"description": "test asset 2", "type": "equity"},
        price_column="price",
        income_column="dividend",
    )
    return sample_asset_universe


@pytest.fixture
def default_portfolio(sample_asset_universe):
    """Fixture providing a default portfolio"""
    return Portfolio(asset_universe=sample_asset_universe)


@pytest.fixture
def portfolio_with_assets(asset_universe_with_assets):
    """Fixture providing a portfolio with tax and fee configuration"""
    return Portfolio(
        asset_universe=asset_universe_with_assets,
    )


@pytest.fixture
def portfolio_with_assets_taxes_fees(
    asset_universe_with_assets, tax_config, fee_config
):
    """Fixture providing a portfolio with tax and fee configuration"""
    return Portfolio(
        asset_universe=asset_universe_with_assets,
        tax_config=tax_config,
        fee_config=fee_config,
    )


@pytest.fixture
def asset_universe_for_income_testing():
    asset_universe = AssetUniverse(data_frequency="D")
    periods = pd.period_range("2023-01-01", periods=3, freq="D")

    Asset(
        symbol="A",
        assetUniverse=asset_universe,
        data=pd.DataFrame(
            {"price": [10.0, 10.0, 10.0], "income": [1.0, 2.0, 3.0]}, index=periods
        ),
        price_column="price",
        income_column="income",
    )
    Asset(
        symbol="B",
        assetUniverse=asset_universe,
        data=pd.DataFrame(
            {"price": [20.0, 20.0, 20.0], "income": [-4.0, -5.0, -6.0]}, index=periods
        ),
        price_column="price",
        income_column="income",
    )

    return asset_universe


@pytest.fixture
def asset_universe_for_sell_asset_testing():
    asset_universe = AssetUniverse(data_frequency="D")
    periods = pd.period_range("2023-01-01", periods=3, freq="D")

    Asset(
        symbol="A",
        assetUniverse=asset_universe,
        data=pd.DataFrame({"price": [10.0, 12.0, 14.0]}, index=periods),
        price_column="price",
    )
    Asset(
        symbol="B",
        assetUniverse=asset_universe,
        data=pd.DataFrame({"price": [20.0, 15.0, 10.0]}, index=periods),
        price_column="price",
    )

    return asset_universe


@pytest.fixture
def portfolio_for_sell_asset_testing_1pct_fee_50pct_short_25pct_long(
    asset_universe_for_sell_asset_testing,
):
    tax_config = TaxConfig(
        long_term_holding_period=pd.DateOffset(days=2),
        short_term_rate=0.5,
        long_term_rate=0.25,
        withhold_tax=False,
    )

    fee_config = FeeConfig(
        percentage_fee=0.01,
    )

    return Portfolio(
        asset_universe=asset_universe_for_sell_asset_testing,
        tax_config=tax_config,
        fee_config=fee_config,
    )
