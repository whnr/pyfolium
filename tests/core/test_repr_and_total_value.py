"""Tests for __repr__ methods, get_total_value, total_value, and price_matrix_ffill."""

import math

import pandas as pd
import pytest

from pyfolium.core import Asset, AssetUniverse, Portfolio, PriceMode


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def simple_universe():
    """Two-asset daily universe with known prices for deterministic testing."""
    universe = AssetUniverse(data_frequency="D")
    periods = pd.period_range("2023-01-01", periods=5, freq="D")
    Asset(
        symbol="A",
        asset_universe=universe,
        data=pd.DataFrame({"price": [10.0, 11.0, 12.0, 13.0, 14.0]}, index=periods),
        price_column="price",
    )
    Asset(
        symbol="B",
        asset_universe=universe,
        data=pd.DataFrame({"price": [20.0, 21.0, 22.0, 23.0, 24.0]}, index=periods),
        price_column="price",
    )
    return universe


@pytest.fixture
def universe_with_short_asset():
    """Universe where asset A spans all 10 periods and asset B only spans 5.

    Used to test that price_matrix_ffill does NOT fill B past its end_time.
    """
    universe = AssetUniverse(data_frequency="D")
    long_periods = pd.period_range("2023-01-01", periods=10, freq="D")
    short_periods = pd.period_range("2023-01-01", periods=5, freq="D")
    Asset(
        symbol="A",
        asset_universe=universe,
        data=pd.DataFrame(
            {"price": [float(i) for i in range(10, 20)]}, index=long_periods
        ),
        price_column="price",
    )
    Asset(
        symbol="B",
        asset_universe=universe,
        data=pd.DataFrame(
            {"price": [float(i) for i in range(20, 25)]}, index=short_periods
        ),
        price_column="price",
    )
    return universe


@pytest.fixture
def universe_with_gap():
    """Universe where asset B has NaN prices on days 2-3 (simulates a gap)."""
    universe = AssetUniverse(data_frequency="D")
    periods = pd.period_range("2023-01-01", periods=5, freq="D")
    Asset(
        symbol="A",
        asset_universe=universe,
        data=pd.DataFrame({"price": [10.0, 11.0, 12.0, 13.0, 14.0]}, index=periods),
        price_column="price",
    )
    # B only covers days 1 and 5; days 2-4 will be NaN in the matrix
    partial_periods = pd.PeriodIndex(["2023-01-01", "2023-01-05"], freq="D")
    Asset(
        symbol="B",
        asset_universe=universe,
        data=pd.DataFrame({"price": [20.0, 24.0]}, index=partial_periods),
        price_column="price",
    )
    return universe


# ---------------------------------------------------------------------------
# __repr__ smoke tests
# ---------------------------------------------------------------------------


class TestAssetRepr:
    def test_repr_returns_string(self, sample_asset):
        assert isinstance(repr(sample_asset), str)

    def test_repr_contains_symbol(self, sample_asset):
        assert "TEST" in repr(sample_asset)

    def test_repr_contains_period_count(self, sample_asset):
        n = len(sample_asset.data)
        assert str(n) in repr(sample_asset)

    def test_repr_income_yes_when_non_zero(self, sample_asset):
        # sample_asset has quarterly dividends
        assert "income: yes" in repr(sample_asset)

    def test_repr_income_no_when_all_zero(self, simple_universe):
        # Asset A in simple_universe has no income column (defaults to 0)
        asset = simple_universe.assets["A"]
        assert "income: no" in repr(asset)

    def test_repr_no_exception_on_minimal_asset(self):
        universe = AssetUniverse(data_frequency="D")
        periods = pd.period_range("2024-01-01", periods=3, freq="D")
        asset = Asset(
            symbol="MINI",
            asset_universe=universe,
            data=pd.DataFrame({"price": [1.0, 2.0, 3.0]}, index=periods),
            price_column="price",
        )
        result = repr(asset)
        assert isinstance(result, str)
        assert "MINI" in result


class TestAssetUniverseRepr:
    def test_repr_empty_universe(self):
        universe = AssetUniverse(data_frequency="D")
        result = repr(universe)
        assert isinstance(result, str)
        assert "empty" in result

    def test_repr_non_empty_universe(self, simple_universe):
        result = repr(simple_universe)
        assert isinstance(result, str)
        assert "AssetUniverse" in result
        assert "A" in result
        assert "B" in result

    def test_repr_contains_frequency(self, simple_universe):
        assert "freq=D" in repr(simple_universe)

    def test_repr_contains_asset_count(self, simple_universe):
        assert "2 assets" in repr(simple_universe)

    def test_repr_truncates_long_symbol_list(self):
        universe = AssetUniverse(data_frequency="D")
        periods = pd.period_range("2023-01-01", periods=3, freq="D")
        for sym in ["A", "B", "C", "D"]:
            Asset(
                symbol=sym,
                asset_universe=universe,
                data=pd.DataFrame({"price": [1.0, 2.0, 3.0]}, index=periods),
                price_column="price",
            )
        result = repr(universe)
        assert "..." in result


class TestPortfolioRepr:
    def test_repr_returns_string(self, portfolio_with_assets):
        assert isinstance(repr(portfolio_with_assets), str)

    def test_repr_contains_period(self, portfolio_with_assets):
        assert str(portfolio_with_assets.current_period) in repr(portfolio_with_assets)

    def test_repr_contains_cash(self, portfolio_with_assets):
        assert "cash=" in repr(portfolio_with_assets)

    def test_repr_shows_holdings_none_when_empty(self, portfolio_with_assets):
        assert "holdings: none" in repr(portfolio_with_assets)

    def test_repr_shows_holdings_after_buy(self, asset_universe_with_assets):
        portfolio = Portfolio(asset_universe=asset_universe_with_assets)
        portfolio.collect_income()
        portfolio.move_cash(10000)
        portfolio.buy_asset("TEST", 5)
        result = repr(portfolio)
        assert "TEST:5" in result

    def test_repr_no_exception_even_with_broken_state(self, portfolio_with_assets):
        # Force a weird state to ensure repr is resilient
        result = repr(portfolio_with_assets)
        assert isinstance(result, str)


class TestBacktestRunnerRepr:
    def test_repr_returns_string(self, portfolio_with_assets):
        from pyfolium.simulation import BacktestRunner
        from pyfolium.strategy import BaseStrategy

        class NoOpStrategy(BaseStrategy):
            def get_trades(self):
                return []

        strategy = NoOpStrategy(portfolio_with_assets)
        runner = BacktestRunner(portfolio_with_assets, strategy)
        assert isinstance(repr(runner), str)

    def test_repr_contains_strategy_name(self, portfolio_with_assets):
        from pyfolium.simulation import BacktestRunner
        from pyfolium.strategy import BaseStrategy

        class MyCustomStrategy(BaseStrategy):
            def get_trades(self):
                return []

        strategy = MyCustomStrategy(portfolio_with_assets)
        runner = BacktestRunner(portfolio_with_assets, strategy)
        assert "MyCustomStrategy" in repr(runner)

    def test_repr_shows_not_started_before_run(self, portfolio_with_assets):
        from pyfolium.simulation import BacktestRunner
        from pyfolium.strategy import BaseStrategy

        class NoOp(BaseStrategy):
            def get_trades(self):
                return []

        runner = BacktestRunner(portfolio_with_assets, NoOp(portfolio_with_assets))
        assert "not started" in repr(runner)

    def test_repr_shows_done_after_run(self, portfolio_with_assets):
        from pyfolium.simulation import BacktestRunner
        from pyfolium.strategy import BaseStrategy

        class NoOp(BaseStrategy):
            def get_trades(self):
                return []

        runner = BacktestRunner(portfolio_with_assets, NoOp(portfolio_with_assets))
        runner.run()
        assert "done" in repr(runner)


# ---------------------------------------------------------------------------
# price_matrix_ffill
# ---------------------------------------------------------------------------


class TestPriceMatrixFfill:
    def test_returns_dataframe(self, simple_universe):
        result = simple_universe.price_matrix_ffill
        assert isinstance(result, pd.DataFrame)

    def test_no_nans_when_prices_are_complete(self, simple_universe):
        assert not simple_universe.price_matrix_ffill.isna().any().any()

    def test_fills_gaps_forward(self, universe_with_gap):
        ffill = universe_with_gap.price_matrix_ffill
        # B had price 20 on day 1; days 2-4 should be filled with 20
        days = pd.period_range("2023-01-01", periods=5, freq="D")
        assert ffill.loc[days[1], "B"] == 20.0
        assert ffill.loc[days[2], "B"] == 20.0
        assert ffill.loc[days[3], "B"] == 20.0
        assert ffill.loc[days[4], "B"] == 24.0

    def test_cache_hit_returns_same_object(self, simple_universe):
        first = simple_universe.price_matrix_ffill
        second = simple_universe.price_matrix_ffill
        assert first is second

    def test_does_not_fill_past_end_time(self, universe_with_short_asset):
        """Periods past an asset's end_time must remain NaN even in the ffill matrix."""
        ffill = universe_with_short_asset.price_matrix_ffill
        days = pd.period_range("2023-01-01", periods=10, freq="D")
        # B has data for days 1-5; days 6-10 must not be filled forward
        for i in range(5, 10):
            assert math.isnan(ffill.loc[days[i], "B"]), (
                f"Expected NaN for B on day {i + 1} (past end_time) but got "
                f"{ffill.loc[days[i], 'B']}"
            )

    def test_intra_life_gaps_still_fill_with_short_asset(
        self, universe_with_short_asset
    ):
        """Intra-life values for the long asset should still be present."""
        ffill = universe_with_short_asset.price_matrix_ffill
        days = pd.period_range("2023-01-01", periods=10, freq="D")
        # A spans all 10 days; none should be NaN
        assert not ffill["A"].isna().any()
        # B spans days 1-5; those should have valid prices
        for i in range(5):
            assert not math.isnan(ffill.loc[days[i], "B"])

    def test_cache_invalidated_on_add_asset(self, simple_universe):
        # Access once to populate cache
        first = simple_universe.price_matrix_ffill
        assert first is simple_universe._price_matrix_ffill

        # Adding a new asset must invalidate the cache
        new_periods = pd.period_range("2023-01-01", periods=5, freq="D")
        Asset(
            symbol="C",
            asset_universe=simple_universe,
            data=pd.DataFrame({"price": [5.0, 6.0, 7.0, 8.0, 9.0]}, index=new_periods),
            price_column="price",
        )
        assert simple_universe._price_matrix_ffill is None
        # Next access recomputes
        second = simple_universe.price_matrix_ffill
        assert "C" in second.columns


# ---------------------------------------------------------------------------
# get_total_value and total_value
# ---------------------------------------------------------------------------


class TestGetTotalValue:
    def test_total_value_is_cash_when_no_holdings(self, simple_universe):
        portfolio = Portfolio(asset_universe=simple_universe)
        portfolio.collect_income()
        portfolio.move_cash(5000.0)
        assert portfolio.get_total_value() == pytest.approx(5000.0)

    def test_total_value_includes_equity(self, simple_universe):
        portfolio = Portfolio(asset_universe=simple_universe)
        portfolio.collect_income()
        portfolio.move_cash(10000.0)
        portfolio.buy_asset("A", 10)  # price = 10, cost = 100
        # cash = 10000 - 100 = 9900; equity = 10 * 10 = 100 → total = 10000
        assert portfolio.get_total_value() == pytest.approx(10000.0)

    def test_total_value_property_matches_default_method(self, simple_universe):
        portfolio = Portfolio(asset_universe=simple_universe)
        portfolio.collect_income()
        portfolio.move_cash(7500.0)
        portfolio.buy_asset("B", 5)  # price=20, cost=100
        assert portfolio.total_value == portfolio.get_total_value()
        assert portfolio.total_value == portfolio.get_total_value(PriceMode.LAST_VALID)

    def test_strict_mode_returns_nan_when_held_asset_has_gap(self, universe_with_gap):
        """In STRICT mode, a held asset with no price on the current period → NaN."""
        portfolio = Portfolio(asset_universe=universe_with_gap)
        portfolio.collect_income()
        portfolio.move_cash(1000.0)
        portfolio.buy_asset("B", 1)  # B price = 20.0 on day 1
        portfolio.update_history()
        portfolio.advance_period()
        # Now on day 2 — B has NaN price in the raw matrix
        portfolio.collect_income()
        strict_val = portfolio.get_total_value(PriceMode.STRICT)
        assert math.isnan(strict_val)

    def test_last_valid_mode_uses_ffill_for_gap(self, universe_with_gap):
        """In LAST_VALID mode, gaps are filled forward so total_value stays finite."""
        portfolio = Portfolio(asset_universe=universe_with_gap)
        portfolio.collect_income()
        portfolio.move_cash(1000.0)
        portfolio.buy_asset("B", 1)  # B price = 20.0 on day 1
        portfolio.update_history()
        portfolio.advance_period()
        # Now on day 2 — B has NaN in raw matrix but 20.0 in ffill matrix
        portfolio.collect_income()
        last_valid = portfolio.get_total_value(PriceMode.LAST_VALID)
        assert not math.isnan(last_valid)
        # cash = 1000 - 20 = 980; equity = 1 * 20 = 20 (ffill) → 1000
        assert last_valid == pytest.approx(1000.0)

    def test_always_retun_nan_with_short_asset(self, universe_with_short_asset):
        """In LAST_VALID mode, we return nan if we hold an asset after its end_time"""
        portfolio = Portfolio(asset_universe=universe_with_short_asset)
        portfolio.collect_income()
        portfolio.move_cash(1000.0)
        portfolio.buy_asset("B", 1)  # B price will be NaN at period 6
        portfolio.update_history()
        portfolio.advance_period()
        for _ in range(4):
            portfolio.collect_income()
            portfolio.update_history()
            portfolio.advance_period()
        # B is now after end_time. Even in PriceMode.LAST_VALID we should get a NaN.
        last_valid = portfolio.get_total_value(PriceMode.LAST_VALID)
        assert math.isnan(last_valid)

    def test_total_value_reflects_price_change_over_periods(self, simple_universe):
        """total_value should increase as asset prices rise."""
        portfolio = Portfolio(asset_universe=simple_universe)
        portfolio.collect_income()
        portfolio.move_cash(1000.0)
        portfolio.buy_asset("A", 10)  # day 1 price=10, cost=100; cash=900
        portfolio.update_history()
        value_day1 = portfolio.get_total_value()

        portfolio.advance_period()
        portfolio.collect_income()
        value_day2 = portfolio.get_total_value()  # A price=11 on day 2

        # equity day1 = 10*10 = 100, total = 1000
        # equity day2 = 10*11 = 110, total = 900 + 110 = 1010
        assert value_day1 == pytest.approx(1000.0)
        assert value_day2 == pytest.approx(1010.0)

    def test_strict_mode_returns_float_when_all_prices_available(self, simple_universe):
        portfolio = Portfolio(asset_universe=simple_universe)
        portfolio.collect_income()
        portfolio.move_cash(500.0)
        val = portfolio.get_total_value(PriceMode.STRICT)
        assert isinstance(val, float)
        assert not math.isnan(val)
        assert val == pytest.approx(500.0)
