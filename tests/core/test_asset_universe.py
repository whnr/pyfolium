from hhfk.core import Asset


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


def test_asset_universe_get_price_matrix(sample_asset_data, sample_asset_universe):
    assert False


def test_asset_universe_get_period_index_range(
    sample_asset_data, sample_asset_universe
):
    assert False
