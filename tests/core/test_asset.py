from datetime import timedelta
from math import isnan

import pandas as pd
from pytest import raises

from pyfolium.core import Asset, AssetUniverse


def test_asset_fixture(sample_asset):
    assert sample_asset.symbol == "TEST"
    assert sample_asset.price_column == "price"
    assert sample_asset.income_column == "dividend"
    assert isinstance(sample_asset.data, pd.DataFrame)
    assert isinstance(sample_asset.data.index, pd.PeriodIndex)


def test_asset_creation_errors(sample_asset_data):
    monthly_universe = AssetUniverse(data_frequency="M")

    # The index is not a period index
    with raises(ValueError):
        Asset(
            symbol="TEST",
            assetUniverse=monthly_universe,
            data=pd.DataFrame({"price": [1, 2, 3]}),
            price_column="price",
        )

    # Adding daily asset to monthly universe shall raise an error
    with raises(ValueError):
        Asset(
            symbol="TEST",
            assetUniverse=monthly_universe,
            data=sample_asset_data,
            price_column="price",
            income_column="dividend",
        )

    # The asset does not have any price data
    with raises(ValueError):
        Asset(
            symbol="TEST",
            assetUniverse=monthly_universe,
            data=pd.DataFrame(),
            price_column="price",
        )

    daily_universe = AssetUniverse(data_frequency="D")

    # We cannot find the income column
    with raises(ValueError):
        Asset(
            symbol="TEST",
            assetUniverse=daily_universe,
            data=sample_asset_data,
            price_column="price",
            income_column="foobar",
        )


def test_asset_index_strict_monotonicity():
    daily_universe = AssetUniverse(data_frequency="D")
    # index with duplicates
    i_duplicates = pd.PeriodIndex(["2023-01-01", "2023-01-01", "2023-01-02"], freq="D")
    # index with non-monotonic data
    i_non_monotonic = pd.PeriodIndex(
        ["2023-01-01", "2023-01-03", "2023-01-02"], freq="D"
    )
    data = {"price": [1, 2, 3]}

    with raises(ValueError, match="is not strictly monotonic"):
        Asset(
            symbol="TEST",
            assetUniverse=daily_universe,
            data=pd.DataFrame(data, index=i_duplicates),
            price_column="price",
        )

    with raises(ValueError, match="is not strictly monotonic"):
        Asset(
            symbol="TEST",
            assetUniverse=daily_universe,
            data=pd.DataFrame(data, index=i_non_monotonic),
            price_column="price",
        )


def test_asset_accessors(sample_asset):
    end_time = sample_asset.end_time
    start_time = sample_asset.start_time
    assert (sample_asset.price == sample_asset.data["price"]).all()
    assert sample_asset.income.equals(sample_asset.data["dividend"])

    # get the values at a specific time.
    assert sample_asset.get_price_at(end_time) == sample_asset.data["price"][end_time]

    start_income = sample_asset.data["dividend"][start_time]
    assert (
        sample_asset.get_income_at(start_time) == 0.0
        if isnan(start_income)
        else start_income
    )
    end_income = sample_asset.data["dividend"][end_time]
    assert (
        sample_asset.get_income_at(end_time) == 0.0 if isnan(end_income) else end_income
    )


def test_asset_precise_price_access(sample_asset):
    end_time = sample_asset.end_time
    start_time = sample_asset.start_time

    # retrieving values for a precise time outside the index raises an error
    with raises(KeyError):
        sample_asset.get_price_at(end_time + timedelta(days=1))

    # retrieving values for an imprecise time before the start date raises an error
    with raises(KeyError):
        sample_asset.get_price_at(start_time - timedelta(days=1), precise=False)

    # getting a value for an imprecise time (e.g. after the end date) does not raise
    assert (
        sample_asset.get_price_at(end_time + timedelta(days=1), precise=False)
        == sample_asset.data["price"][end_time]
    )


def test_asset_income_precise_access(sample_asset):
    end_time = sample_asset.end_time
    start_time = sample_asset.start_time

    # retrieving any value without a label returns 0
    with raises(KeyError):
        sample_asset.get_income_at(end_time + timedelta(days=1))
    with raises(KeyError):
        sample_asset.get_income_at(start_time - timedelta(days=1))


def test_asset_does_not_mutate_caller_dataframe(
    sample_asset_data, sample_asset_universe
):
    """Asset.__init__ must not add columns to the caller's DataFrame (P1-2)."""
    # Make an explicit copy so we can compare against it later
    original_columns = list(sample_asset_data.columns)

    daily_universe = AssetUniverse(data_frequency="D")
    Asset(
        symbol="NOMUT",
        assetUniverse=daily_universe,
        data=sample_asset_data,
        price_column="price",
        # No income_column — triggers the branch that previously mutated the frame
    )

    # The caller's DataFrame must be unchanged
    assert list(sample_asset_data.columns) == original_columns
    assert "income" not in sample_asset_data.columns


def test_asset_with_income_column_does_not_mutate_caller_dataframe(
    sample_asset_data, sample_asset_universe
):
    """Asset.__init__ must not mutate the caller's DataFrame even when an income
    column is provided and additional column operations are applied internally."""
    original_columns = list(sample_asset_data.columns)
    original_values = sample_asset_data.copy(deep=True)

    Asset(
        symbol="NOMUT2",
        assetUniverse=sample_asset_universe,
        data=sample_asset_data,
        price_column="price",
        income_column="dividend",
    )

    assert list(sample_asset_data.columns) == original_columns
    assert sample_asset_data.equals(original_values)
