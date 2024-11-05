import numpy as np
import pandas as pd
import pytest

from hhfk.core import Asset, AssetUniverse, FeeConfig, TaxConfig


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
def portfolio_with_config(tax_config, fee_config):
    """Fixture providing a portfolio with tax and fee configuration"""
    raise NotImplementedError
