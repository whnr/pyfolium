import pandas as pd
from pytest import raises

from hhfk.core import Asset, AssetUniverse


def test_asset_fixture(sample_asset):
    assert sample_asset.symbol == "TEST"
    assert sample_asset.price_column == "price"
    assert sample_asset.income_column == "dividend"
    assert isinstance(sample_asset.data, pd.DataFrame)
    assert isinstance(sample_asset.data.index, pd.PeriodIndex)


def test_asset_in_unniverse(sample_asset_data, sample_asset_universe):
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


def test_asset_creation_errors(sample_asset):
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
            data=sample_asset.data,
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


def test_asset_accessors(sample_asset):
    end_time = sample_asset.end_time
    assert (sample_asset.price == sample_asset.data["price"]).all()
    assert (sample_asset.income == sample_asset.data["dividend"]).all()

    assert sample_asset.get_price_at(end_time) == sample_asset.data["price"][end_time]
    assert (
        sample_asset.get_income_at(end_time) == sample_asset.data["dividend"][end_time]
    )
