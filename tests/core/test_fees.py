from typing import Any

import pandas as pd
import pytest

from pyfolium.core import (
    Asset,
    AssetUniverse,
    FeeConfig,
    Portfolio,
)


def test_fee_config(fee_config):
    # test the general fee config exists
    assert fee_config.minimum_fee == 5.0
    assert fee_config.fixed_fee == 1.0
    assert fee_config.percentage_fee == 0.01
    assert fee_config.minimum_fee == 5.0
    assert fee_config.maximum_fee == 20.0


def test_fee_minimum_fee(fee_config):
    assert fee_config.calculate_fee(0.0) == 5.0


def test_fee_medium_fee(fee_config):
    medium_fee = 1.0 + 0.01 * 1000
    assert fee_config.calculate_fee(1000.0) == medium_fee


def test_fee_maximum_fee(fee_config):
    assert fee_config.calculate_fee(1000000.0) == 20.0


# --- Phase 3: FeeConfig extensibility tests ---


class TieredFeeConfig(FeeConfig):
    """Tiered commission schedule: lower rates for larger trades."""

    def calculate_fee(
        self,
        transaction_value: float,
        *,
        symbol: str | None = None,
        quantity: float | None = None,
        transaction_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> float:
        # Tiered: 1% on first 1000, 0.5% on next 4000, 0.1% above 5000
        fee = 0.0
        remaining = transaction_value
        if remaining <= 0:
            return 0.0
        tier1 = min(remaining, 1_000)
        fee += tier1 * 0.01
        remaining -= tier1
        if remaining <= 0:
            return fee
        tier2 = min(remaining, 4_000)
        fee += tier2 * 0.005
        remaining -= tier2
        if remaining > 0:
            fee += remaining * 0.001
        return fee


class AssetClassFeeConfig(FeeConfig):
    """Fee rates driven by the asset's ``asset_class`` metadata field."""

    def calculate_fee(
        self,
        transaction_value: float,
        *,
        symbol: str | None = None,
        quantity: float | None = None,
        transaction_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> float:
        asset_class = (metadata or {}).get("asset_class", "equity")
        if asset_class == "fixed_income":
            return transaction_value * 0.001  # 0.1% for bonds
        return transaction_value * 0.01  # 1% for equities


class BuySellAsymmetricFeeConfig(FeeConfig):
    """Different fee rates for buy vs sell."""

    def calculate_fee(
        self,
        transaction_value: float,
        *,
        symbol: str | None = None,
        quantity: float | None = None,
        transaction_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> float:
        if transaction_type == "sell":
            return transaction_value * 0.005  # 0.5% to sell
        return transaction_value * 0.01  # 1% to buy


def test_tiered_fee_small_trade():
    cfg = TieredFeeConfig()
    assert cfg.calculate_fee(500) == 500 * 0.01


def test_tiered_fee_medium_trade():
    cfg = TieredFeeConfig()
    # 1000 * 0.01 + 2000 * 0.005 = 10 + 10 = 20
    assert cfg.calculate_fee(3_000) == 20.0


def test_tiered_fee_large_trade():
    cfg = TieredFeeConfig()
    # 1000 * 0.01 + 4000 * 0.005 + 5000 * 0.001 = 10 + 20 + 5 = 35
    assert cfg.calculate_fee(10_000) == 35.0


def test_tiered_fee_zero():
    cfg = TieredFeeConfig()
    assert cfg.calculate_fee(0) == 0.0


def test_asset_class_fee_uses_metadata():
    cfg = AssetClassFeeConfig()
    bond_meta = {"asset_class": "fixed_income"}
    equity_meta = {"asset_class": "equity"}
    assert cfg.calculate_fee(10_000, metadata=bond_meta) == 10.0
    assert cfg.calculate_fee(10_000, metadata=equity_meta) == 100.0


def test_asset_class_fee_without_metadata_falls_back():
    cfg = AssetClassFeeConfig()
    # No metadata → defaults to equity rate
    assert cfg.calculate_fee(10_000) == 100.0


def test_buy_sell_asymmetric_fee():
    cfg = BuySellAsymmetricFeeConfig()
    assert cfg.calculate_fee(10_000, transaction_type="buy") == 100.0
    assert cfg.calculate_fee(10_000, transaction_type="sell") == 50.0


def test_buy_sell_asymmetric_fee_no_type():
    cfg = BuySellAsymmetricFeeConfig()
    # No transaction_type → defaults to buy rate
    assert cfg.calculate_fee(10_000) == 100.0


def test_default_fee_config_ignores_context():
    """Default FeeConfig still works when context kwargs are passed."""
    cfg = FeeConfig(fixed_fee=5.0, percentage_fee=0.01)
    # Without context
    assert cfg.calculate_fee(1000) == 15.0
    # With context — same result, kwargs are ignored
    assert (
        cfg.calculate_fee(
            1000, symbol="Aktie", quantity=10, metadata={"asset_class": "equity"}
        )
        == 15.0
    )


# --- Integration: Portfolio passes context to FeeConfig ---


@pytest.fixture
def portfolio_with_asset_class_fees():
    """Portfolio using AssetClassFeeConfig with metadata-tagged assets."""
    universe = AssetUniverse(data_frequency="D")
    periods = pd.period_range("2023-01-01", periods=3, freq="D")

    Asset(
        symbol="Aktie",
        asset_universe=universe,
        data=pd.DataFrame({"price": [100.0, 110.0, 120.0]}, index=periods),
        price_column="price",
        metadata={"asset_class": "equity"},
    )
    Asset(
        symbol="Anleihe",
        asset_universe=universe,
        data=pd.DataFrame({"price": [50.0, 50.0, 50.0]}, index=periods),
        price_column="price",
        metadata={"asset_class": "fixed_income"},
    )

    return Portfolio(
        asset_universe=universe,
        fee_config=AssetClassFeeConfig(),
    )


def test_portfolio_buy_passes_metadata_to_fee_config(portfolio_with_asset_class_fees):
    """Portfolio.buy_asset passes asset metadata to calculate_fee."""
    p = portfolio_with_asset_class_fees
    p.collect_income()
    p.move_cash(100_000)
    p.buy_asset("Aktie", 10)  # 10 * 100 = 1000, equity fee = 1% = 10
    p.buy_asset("Anleihe", 10)  # 10 * 50 = 500, fixed_income fee = 0.1% = 0.5

    txns = p.transactions
    equity_buy = txns[txns["symbol"] == "Aktie"].iloc[0]
    bond_buy = txns[txns["symbol"] == "Anleihe"].iloc[0]

    assert equity_buy["fee"] == pytest.approx(10.0)
    assert bond_buy["fee"] == pytest.approx(0.5)


def test_portfolio_sell_passes_metadata_to_fee_config(portfolio_with_asset_class_fees):
    """Portfolio.sell_asset passes asset metadata to calculate_fee."""
    p = portfolio_with_asset_class_fees
    p.collect_income()
    p.move_cash(100_000)
    p.buy_asset("Aktie", 10)
    p.buy_asset("Anleihe", 10)
    p.update_history()
    p.advance_period()

    p.collect_income()
    p.sell_asset("Aktie", 5)  # 5 * 110 = 550, equity fee = 1% = 5.5
    p.sell_asset("Anleihe", 5)  # 5 * 50 = 250, fixed_income fee = 0.1% = 0.25

    txns = p.transactions
    equity_sell = txns[(txns["symbol"] == "Aktie") & (txns["type"] == "sell")].iloc[0]
    bond_sell = txns[(txns["symbol"] == "Anleihe") & (txns["type"] == "sell")].iloc[0]

    assert equity_sell["fee"] == pytest.approx(5.5)
    assert bond_sell["fee"] == pytest.approx(0.25)


@pytest.fixture
def portfolio_with_asymmetric_fees():
    """Portfolio using BuySellAsymmetricFeeConfig."""
    universe = AssetUniverse(data_frequency="D")
    periods = pd.period_range("2023-01-01", periods=3, freq="D")

    Asset(
        symbol="Stock",
        asset_universe=universe,
        data=pd.DataFrame({"price": [100.0, 100.0, 100.0]}, index=periods),
        price_column="price",
    )

    return Portfolio(
        asset_universe=universe,
        fee_config=BuySellAsymmetricFeeConfig(),
    )


def test_portfolio_passes_transaction_type(portfolio_with_asymmetric_fees):
    """Portfolio passes 'buy' or 'sell' as transaction_type to calculate_fee."""
    p = portfolio_with_asymmetric_fees
    p.collect_income()
    p.move_cash(100_000)
    p.buy_asset("Stock", 10)  # 10 * 100 = 1000, buy fee = 1% = 10
    p.update_history()
    p.advance_period()

    p.collect_income()
    p.sell_asset("Stock", 5)  # 5 * 100 = 500, sell fee = 0.5% = 2.5

    txns = p.transactions
    buy_txn = txns[txns["type"] == "buy"].iloc[0]
    sell_txn = txns[txns["type"] == "sell"].iloc[0]

    assert buy_txn["fee"] == pytest.approx(10.0)
    assert sell_txn["fee"] == pytest.approx(2.5)
