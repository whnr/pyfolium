"""Tests for data gaps handling.

Two failure modes are tested, each with a distinct philosophy:

1. Construction-time (fail-fast): Asset.__init__ rejects price data that contains NaN.
   If a user provides a price series with NaN within its own declared date range, that
   is data corruption and should be caught immediately.

2. Trade-time (graceful failure): When a strategy attempts to trade an asset at a period
   outside that asset's declared data range, the universe's price_matrix returns NaN
   (due to reindex). buy_asset / sell_asset detect this and raise ValueError, which
   execute_trades catches and records as success=False in trades_df.

3. Income (silent zero): NaN income for a period means the asset has no data there.
   collect_income treats it as zero — nothing to collect, no transaction registered.
"""

import pandas as pd
import pytest

from pyfolium.core import Asset, AssetUniverse, Portfolio
from pyfolium.strategy import BaseStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_universe_with_two_assets_different_start_dates():
    """Return a universe where asset B starts one period after asset A.

    Period index: [2023-01-01, 2023-01-02, 2023-01-03]
    Asset A: data for all 3 periods.
    Asset B: data only from 2023-01-02 onward.

    The universe price_matrix therefore has NaN for B on 2023-01-01
    (filled by reindex from the broader A range).
    """
    universe = AssetUniverse(data_frequency="D")
    periods_a = pd.period_range("2023-01-01", periods=3, freq="D")
    periods_b = pd.period_range("2023-01-02", periods=2, freq="D")

    Asset(
        symbol="A",
        asset_universe=universe,
        data=pd.DataFrame({"price": [10.0, 11.0, 12.0]}, index=periods_a),
        price_column="price",
    )
    Asset(
        symbol="B",
        asset_universe=universe,
        data=pd.DataFrame({"price": [20.0, 21.0]}, index=periods_b),
        price_column="price",
    )
    return universe


class _BuyBStrategy(BaseStrategy):
    """Minimal strategy that always tries to buy 1 share of B."""

    def get_trades(self) -> list[tuple[str, float]]:
        return [("B", 1.0)]


# ---------------------------------------------------------------------------
# 1. Construction-time NaN rejection
# ---------------------------------------------------------------------------


def test_asset_rejects_nan_prices():
    """Asset.__init__ must raise ValueError when the price column contains NaN."""
    universe = AssetUniverse(data_frequency="D")
    periods = pd.period_range("2023-01-01", periods=3, freq="D")

    data_with_nan = pd.DataFrame({"price": [10.0, float("nan"), 12.0]}, index=periods)

    with pytest.raises(ValueError, match="NaN"):
        Asset(
            symbol="GAP",
            asset_universe=universe,
            data=data_with_nan,
            price_column="price",
        )


def test_asset_accepts_clean_prices():
    """Asset.__init__ must succeed when the price column has no NaN."""
    universe = AssetUniverse(data_frequency="D")
    periods = pd.period_range("2023-01-01", periods=3, freq="D")

    data_clean = pd.DataFrame({"price": [10.0, 11.0, 12.0]}, index=periods)
    asset = Asset(
        symbol="CLEAN",
        asset_universe=universe,
        data=data_clean,
        price_column="price",
    )
    assert asset.symbol == "CLEAN"


def test_asset_accepts_nan_income_column():
    """NaN in the income column must NOT be rejected — income NaN means zero income."""
    universe = AssetUniverse(data_frequency="D")
    periods = pd.period_range("2023-01-01", periods=3, freq="D")

    data = pd.DataFrame(
        {"price": [10.0, 11.0, 12.0], "income": [0.5, float("nan"), 0.5]},
        index=periods,
    )
    # Should not raise
    asset = Asset(
        symbol="INC",
        asset_universe=universe,
        data=data,
        price_column="price",
        income_column="income",
    )
    assert asset.symbol == "INC"


# ---------------------------------------------------------------------------
# 2. Trade-time graceful failure via execute_trades
# ---------------------------------------------------------------------------


def test_buy_before_asset_start_records_failure_in_trades_df():
    """Buying an asset on a period before its data range records success=False.

    The universe covers 2023-01-01 to 2023-01-03. Asset B only has data from
    2023-01-02. On the first period (2023-01-01) the portfolio starts. A strategy
    that tries to buy B on that period should see a failed trade recorded, and the
    backtest should NOT crash.
    """
    universe = _make_universe_with_two_assets_different_start_dates()
    portfolio = Portfolio(asset_universe=universe)

    # Manually step the portfolio to the first period and execute the strategy
    portfolio.collect_income()
    portfolio.move_cash(10_000.0)

    strategy = _BuyBStrategy(portfolio)
    strategy.step()  # tries to buy B on 2023-01-01 (before B's data starts)

    assert len(strategy.trades_df) == 1
    trade = strategy.trades_df.iloc[0]
    assert trade["symbol"] == "B"
    assert trade["success"] == False  # noqa: E712 — numpy bool, not Python bool
    assert trade["executed_quantity"] == 0

    # Portfolio cash must be unchanged (trade was not executed)
    assert portfolio.cash == 10_000.0
    # Portfolio holdings must be zero for B
    assert portfolio.holdings.loc[portfolio.current_period, "B"] == 0.0


def test_buy_on_valid_period_succeeds():
    """Buying asset B on a period within its data range records success=True."""
    universe = _make_universe_with_two_assets_different_start_dates()
    portfolio = Portfolio(asset_universe=universe)

    # Advance to day 2 (2023-01-02) where B has price data
    portfolio.collect_income()
    portfolio.move_cash(10_000.0)
    portfolio.update_history()
    portfolio.advance_period()

    portfolio.collect_income()
    portfolio.move_cash(0.0)  # no-op

    strategy = _BuyBStrategy(portfolio)
    strategy.step()  # buys B on 2023-01-02 — price is 20.0

    assert len(strategy.trades_df) == 1
    trade = strategy.trades_df.iloc[0]
    assert trade["symbol"] == "B"
    assert trade["success"] == True  # noqa: E712 — numpy bool, not Python bool
    assert trade["executed_quantity"] == 1.0
    assert portfolio.holdings.loc[portfolio.current_period, "B"] == 1.0


# ---------------------------------------------------------------------------
# 3. collect_income treats NaN income as zero
# ---------------------------------------------------------------------------


def test_collect_income_ignores_nan_income_outside_asset_range():
    """collect_income must not create transactions for assets with NaN income.

    Asset B starts on 2023-01-02, so its income column is NaN in the universe
    income_matrix on 2023-01-01 (due to reindex). After buying A on day 1
    and advancing to day 2, we verify that collect_income on day 1 produces
    no income transaction for B (since B has no data on that day).
    """
    universe = AssetUniverse(data_frequency="D")
    periods_a = pd.period_range("2023-01-01", periods=3, freq="D")
    periods_b = pd.period_range("2023-01-02", periods=2, freq="D")

    Asset(
        symbol="A",
        asset_universe=universe,
        data=pd.DataFrame(
            {"price": [10.0, 11.0, 12.0], "income": [1.0, 1.0, 1.0]},
            index=periods_a,
        ),
        price_column="price",
        income_column="income",
    )
    Asset(
        symbol="B",
        asset_universe=universe,
        data=pd.DataFrame(
            {"price": [20.0, 21.0], "income": [5.0, 5.0]},
            index=periods_b,
        ),
        price_column="price",
        income_column="income",
    )

    portfolio = Portfolio(asset_universe=universe)

    # Day 1: deposit and buy A. B has NaN income on this day.
    portfolio.collect_income()
    portfolio.move_cash(10_000.0)
    portfolio.buy_asset("A", 10.0)
    portfolio.update_history()
    portfolio.advance_period()

    # Day 2: collect income. Only A should generate income (no phantom income from B
    # that we happen not to hold).
    portfolio.collect_income()

    income_txns = portfolio.transactions[portfolio.transactions["type"] == "income"]
    # A: 10 shares * 1.0 income = 10.0 → one income transaction expected
    assert len(income_txns) == 1
    assert income_txns.iloc[0]["symbol"] == "A"


def test_collect_income_nan_income_for_held_asset_treated_as_zero():
    """Holding an asset whose income is NaN on a given period produces no income txn.

    We build a scenario where we hold B but collect_income runs on 2023-01-01
    (before B's data starts). The income_matrix has NaN for B on that day.
    collect_income must silently skip it — no transaction, no cash change.
    """
    universe = _make_universe_with_two_assets_different_start_dates()
    portfolio = Portfolio(asset_universe=universe)

    # Day 1: force a holding of B (simulate a carry-forward by directly setting)
    # We can't use buy_asset since B has no price on day 1, so we manipulate holdings
    # directly to simulate a scenario where we somehow hold B.
    portfolio._states[portfolio.current_period] = __import__(
        "pyfolium.core", fromlist=["PortfolioState"]
    ).PortfolioState.TRANSACT
    portfolio.holdings.loc[portfolio.current_period, "B"] = 5.0
    portfolio._states[portfolio.current_period] = __import__(
        "pyfolium.core", fromlist=["PortfolioState"]
    ).PortfolioState.COLLECT_INCOME

    # Now collect income. B has NaN income on 2023-01-01, A has no income column
    # (no income column provided → income defaults to 0). Neither should generate
    # an income transaction.
    portfolio.collect_income()

    income_txns = portfolio.transactions[portfolio.transactions["type"] == "income"]
    assert len(income_txns) == 0
    assert portfolio.cash == 0.0
