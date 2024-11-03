from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from hhfk.core import (
    Asset,
    FeeConfig,
    Portfolio,
    Position,
    TaxConfig,
    TaxLot,
    Transaction,
)


@pytest.fixture
def tax_config():
    """Fixture for standard tax configuration"""
    return TaxConfig(
        short_term_rate=0.30,
        long_term_rate=0.15,
    )


@pytest.fixture
def fee_config():
    """Fixture for standard fee configuration"""
    return FeeConfig(
        fixed_fee=1.0,
        percentage_fee=0.01,
        minimum_fee=5.0,
        maximum_fee=30.0,
    )


@pytest.fixture
def date_range():
    """Fixture providing a date range for testing"""
    start_date = datetime(2023, 1, 1)
    dates = [
        start_date + timedelta(days=x) for x in range(500)
    ]  # Extended for long-term gains testing
    return pd.DatetimeIndex(dates)


@pytest.fixture
def sample_asset_data(date_range):
    """Fixture providing sample asset data with price and dividend history"""
    np.random.seed(42)
    price_data = 100 * (1 + np.random.randn(len(date_range)).cumsum() * 0.02)
    dividend_data = np.zeros(len(date_range))
    dividend_data[::90] = price_data[::90] * 0.01  # Quarterly dividends

    return pd.DataFrame(
        {"price": price_data, "dividend": dividend_data}, index=date_range
    )


@pytest.fixture
def sample_asset(sample_asset_data):
    """Fixture providing a sample asset with price and dividend data"""
    return Asset(
        symbol="TEST",
        data=sample_asset_data,
        price_column="price",
        dividend_column="dividend",
    )


@pytest.fixture
def portfolio_with_config(tax_config, fee_config):
    """Fixture providing a portfolio with tax and fee configuration"""
    return Portfolio(
        initial_cash=100000.0, tax_config=tax_config, fee_config=fee_config
    )
