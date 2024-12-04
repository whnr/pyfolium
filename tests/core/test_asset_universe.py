import pandas as pd
from pytest import raises

from pyfolium.core import Asset


def test_asset_universe_empty(sample_asset_universe, sample_asset_data):
    assert sample_asset_universe.empty

    Asset(
        symbol="TEST",
        assetUniverse=sample_asset_universe,
        data=sample_asset_data,
        price_column="price",
        income_column="dividend",
    )

    assert not sample_asset_universe.empty


def test_asset_in_universe(sample_asset_data, sample_asset_universe):
    assetUniverse = sample_asset_universe

    new_asset = Asset(
        symbol="TEST",
        assetUniverse=assetUniverse,
        data=sample_asset_data,
        price_column="price",
        income_column="dividend",
    )

    assert len(assetUniverse.assets) == 1
    assert new_asset in assetUniverse.assets.values()


def test_adding_empty_asset_raises_error(sample_asset_universe):
    with raises(ValueError):
        Asset(
            symbol="TEST",
            assetUniverse=sample_asset_universe,
            data=pd.DataFrame(),
            price_column="price",
            income_column="dividend",
        )


def test_adding_asset_with_same_symbol_raises_error(
    sample_asset_universe, sample_asset_data
):
    with raises(ValueError):
        Asset(
            symbol="TEST",
            assetUniverse=sample_asset_universe,
            data=sample_asset_data,
            price_column="price",
            income_column="dividend",
        )

        Asset(
            symbol="TEST",
            assetUniverse=sample_asset_universe,
            data=sample_asset_data,
            price_column="price",
            income_column="dividend",
        )


def test_asset_universe_price_matrix(sample_asset_data, sample_asset_universe):
    assert sample_asset_universe.price_matrix.empty

    asset = Asset(
        symbol="TEST",
        assetUniverse=sample_asset_universe,
        data=sample_asset_data,
        price_column="price",
        income_column="dividend",
    )

    assert not sample_asset_universe.price_matrix.empty
    assert asset.price.equals(sample_asset_universe.price_matrix["TEST"])

    asset2 = Asset(
        symbol="TEST2",
        assetUniverse=sample_asset_universe,
        data=sample_asset_data,
        price_column="price",
        income_column="dividend",
    )

    assert len(sample_asset_universe.price_matrix.columns) == 2
    assert asset2.price.equals(sample_asset_universe.price_matrix["TEST2"])


def test_asset_universe_price_matrix_different_lengths(
    sample_asset_data, sample_asset_universe
):
    Asset(
        symbol="TEST",
        assetUniverse=sample_asset_universe,
        data=sample_asset_data,
        price_column="price",
        income_column="dividend",
    )

    short_asset_data = sample_asset_data.copy()
    # shorten the data by a year
    short_asset_data = short_asset_data[:-365]

    Asset(
        symbol="TEST2",
        assetUniverse=sample_asset_universe,
        data=short_asset_data,
        price_column="price",
        income_column="dividend",
    )
    assert len(sample_asset_universe.price_matrix.columns) == 2

    assert len(sample_asset_universe.price_matrix["TEST"]) == len(
        sample_asset_universe.price_matrix["TEST2"]
    )


def test_asset_universe_income_matrix(sample_asset_data, sample_asset_universe):
    assert sample_asset_universe.income_matrix.empty

    asset = Asset(
        symbol="TEST",
        assetUniverse=sample_asset_universe,
        data=sample_asset_data,
        price_column="price",
        income_column="dividend",
    )

    assert not sample_asset_universe.income_matrix.empty
    assert asset.income.equals(sample_asset_universe.income_matrix["TEST"])

    no_dividend_asset_data = sample_asset_data.copy()
    # drop the dividend column
    no_dividend_asset_data.drop(columns=["dividend"], inplace=True)

    asset2 = Asset(
        symbol="TEST2",
        assetUniverse=sample_asset_universe,
        data=no_dividend_asset_data,
        price_column="price",
    )

    assert len(sample_asset_universe.income_matrix.columns) == 2
    assert asset2.income.equals(sample_asset_universe.income_matrix["TEST2"])
    assert len(sample_asset_universe.income_matrix.index) == len(
        sample_asset_universe.price_matrix["TEST2"]
    )


def test_asset_universe_get_period_index_range(
    sample_asset_data, sample_asset_universe
):
    """Test that assets with two non-overlapping periods will generate
    a single period index range without any gaps"""

    old_asset_data = sample_asset_data.copy()
    # offset the index by 10 years
    old_asset_data.index -= 10 * 365
    # drop the dividend column to make it harder
    old_asset_data.drop(columns=["dividend"], inplace=True)

    Asset(
        symbol="old",
        assetUniverse=sample_asset_universe,
        data=old_asset_data,
        price_column="price",
    )
    Asset(
        symbol="new",
        assetUniverse=sample_asset_universe,
        data=sample_asset_data,
        price_column="price",
        income_column="dividend",
    )

    # Determine the period index range we should have
    first_date = sample_asset_universe.assets["old"].start_time
    last_date = sample_asset_universe.assets["new"].end_time
    expected_period_index_range = pd.period_range(
        first_date, last_date, freq=sample_asset_universe.data_frequency
    )
    # Make sure we have the right number of periods
    assert len(sample_asset_universe.get_period_index_range()) == len(
        expected_period_index_range
    )

    # Check if this also works for the price matrix
    assert len(sample_asset_universe.price_matrix.index) == len(
        expected_period_index_range
    )
    # and the income matrix
    assert len(sample_asset_universe.income_matrix.index) == len(
        expected_period_index_range
    )
