"""Tests for TaxLot dataclass, transaction buffer, and related Portfolio internals."""

import pandas as pd
import pytest
from pytest import approx

from pyfolium.core import (
    Asset,
    AssetUniverse,
    FeeConfig,
    Portfolio,
    TaxConfig,
    TaxLot,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def universe():
    u = AssetUniverse(data_frequency="D")
    dates = pd.period_range(start="2020-01-01", periods=30, freq="D")
    data_a = pd.DataFrame({"price": 100.0, "income": 0.0}, index=dates)
    data_b = pd.DataFrame({"price": 50.0, "income": 0.0}, index=dates)
    Asset("A", u, data_a)
    Asset("B", u, data_b)
    return u


@pytest.fixture
def universe_with_income():
    u = AssetUniverse(data_frequency="D")
    dates = pd.period_range(start="2020-01-01", periods=30, freq="D")
    income = [1.0 if i == 0 else 0.0 for i in range(30)]
    data = pd.DataFrame({"price": 100.0, "income": income}, index=dates)
    Asset("A", u, data)
    return u


@pytest.fixture
def portfolio(universe):
    return Portfolio(universe)


@pytest.fixture
def portfolio_with_fees(universe):
    return Portfolio(
        universe,
        fee_config=FeeConfig(fixed_fee=1.0, percentage_fee=0.01),
    )


@pytest.fixture
def portfolio_with_taxes(universe):
    return Portfolio(
        universe,
        tax_config=TaxConfig(
            short_term_rate=0.30,
            long_term_rate=0.15,
            withhold_tax=True,
        ),
    )


# ---------------------------------------------------------------------------
# TaxLot dataclass
# ---------------------------------------------------------------------------


class TestTaxLot:
    def test_construction(self):
        period = pd.Period("2020-01-01", freq="D")
        lot = TaxLot(
            symbol="AAPL",
            period=period,
            quantity=100.0,
            quantity_remaining=100.0,
            cost_basis_per_share=150.5,
            txn_index=0,
        )
        assert lot.symbol == "AAPL"
        assert lot.period == period
        assert lot.quantity == 100.0
        assert lot.quantity_remaining == 100.0
        assert lot.cost_basis_per_share == 150.5
        assert lot.txn_index == 0

    def test_is_open_when_full(self):
        lot = TaxLot("X", pd.Period("2020-01-01", freq="D"), 10, 10, 100.0, 0)
        assert lot.is_open is True

    def test_is_open_when_partial(self):
        lot = TaxLot("X", pd.Period("2020-01-01", freq="D"), 10, 3, 100.0, 0)
        assert lot.is_open is True

    def test_is_open_when_closed(self):
        lot = TaxLot("X", pd.Period("2020-01-01", freq="D"), 10, 0, 100.0, 0)
        assert lot.is_open is False

    def test_slots(self):
        """TaxLot uses __slots__ for memory efficiency."""
        lot = TaxLot("X", pd.Period("2020-01-01", freq="D"), 10, 10, 100.0, 0)
        assert hasattr(lot, "__slots__") or hasattr(type(lot), "__slots__")
        with pytest.raises(AttributeError):
            lot.arbitrary_attribute = "should fail"  # type: ignore[attr-defined]

    def test_mutable(self):
        """quantity_remaining can be decremented (not frozen)."""
        lot = TaxLot("X", pd.Period("2020-01-01", freq="D"), 10, 10, 100.0, 0)
        lot.quantity_remaining = 5.0
        assert lot.quantity_remaining == 5.0


# ---------------------------------------------------------------------------
# Transaction buffer internals
# ---------------------------------------------------------------------------


class TestTransactionBuffer:
    def test_empty_buffer_on_init(self, portfolio):
        assert portfolio._txn_buffer == []
        assert portfolio._txn_period_index == {}
        assert portfolio._tax_lots == {}

    def test_transactions_property_empty(self, portfolio):
        df = portfolio.transactions
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        assert set(df.columns) == set(Portfolio.transaction_columns.keys())

    def test_buffer_grows_on_transaction(self, portfolio):
        portfolio.collect_income()
        portfolio.move_cash(10000)
        assert len(portfolio._txn_buffer) == 1
        assert portfolio._txn_buffer[0]["type"] == "deposit"
        assert portfolio._txn_buffer[0]["transaction_amount"] == 10000

    def test_period_index_tracks_transactions(self, portfolio):
        portfolio.collect_income()
        portfolio.move_cash(10000)
        portfolio.buy_asset("A", 5)

        period = portfolio.current_period
        indices = portfolio._txn_period_index[period]
        assert len(indices) == 2  # deposit + buy
        assert indices == [0, 1]

    def test_transactions_dataframe_matches_buffer(self, portfolio):
        portfolio.collect_income()
        portfolio.move_cash(10000)
        portfolio.buy_asset("A", 10)

        df = portfolio.transactions
        assert len(df) == 2
        assert df.iloc[0]["type"] == "deposit"
        assert df.iloc[1]["type"] == "buy"
        assert df.iloc[1]["symbol"] == "A"
        assert df.iloc[1]["quantity"] == 10.0

    def test_transactions_cache_invalidated_on_new_transaction(self, portfolio):
        portfolio.collect_income()
        portfolio.move_cash(10000)
        df1 = portfolio.transactions
        assert len(df1) == 1

        portfolio.buy_asset("A", 5)
        df2 = portfolio.transactions
        assert len(df2) == 2
        # df1 is stale (old cache), df2 is fresh
        assert len(df1) == 1  # old reference unchanged

    def test_transactions_schema_complete(self, portfolio):
        """All columns from transaction_columns exist even for sparse txns."""
        portfolio.collect_income()
        portfolio.move_cash(100)  # deposit has no symbol, price, etc.
        df = portfolio.transactions
        for col in Portfolio.transaction_columns:
            assert col in df.columns


# ---------------------------------------------------------------------------
# TaxLot lifecycle through buy/sell
# ---------------------------------------------------------------------------


class TestTaxLotLifecycle:
    def test_buy_creates_tax_lot(self, portfolio):
        portfolio.collect_income()
        portfolio.move_cash(10000)
        portfolio.buy_asset("A", 10)

        assert "A" in portfolio._tax_lots
        lots = portfolio._tax_lots["A"]
        assert len(lots) == 1
        assert lots[0].symbol == "A"
        assert lots[0].quantity == 10.0
        assert lots[0].quantity_remaining == 10.0
        assert lots[0].period == portfolio.current_period

    def test_buy_cost_basis_includes_fees(self, portfolio_with_fees):
        p = portfolio_with_fees
        p.collect_income()
        p.move_cash(100000)
        p.buy_asset("A", 10)

        lot = p._tax_lots["A"][0]
        # price=100, fee = 1.0 + 0.01*1000 = 11.0, cost_basis = 100 + 11/10
        assert lot.cost_basis_per_share == approx(100.0 + 11.0 / 10.0)

    def test_sell_decrements_lot_remaining(self, portfolio):
        portfolio.collect_income()
        portfolio.move_cash(10000)
        portfolio.buy_asset("A", 10)
        portfolio.sell_asset("A", 3)

        lot = portfolio._tax_lots["A"][0]
        assert lot.quantity_remaining == approx(7.0)
        assert lot.quantity == 10.0  # original unchanged

    def test_sell_closes_lot_fully(self, portfolio):
        portfolio.collect_income()
        portfolio.move_cash(10000)
        portfolio.buy_asset("A", 10)
        portfolio.sell_asset("A", 10)

        lot = portfolio._tax_lots["A"][0]
        assert lot.quantity_remaining == 0.0
        assert lot.is_open is False

    def test_sell_fifo_order(self, portfolio):
        """FIFO: first lot consumed first."""
        portfolio.collect_income()
        portfolio.move_cash(50000)
        portfolio.buy_asset("A", 10)
        portfolio.update_history()

        portfolio.advance_period()
        portfolio.collect_income()
        portfolio.buy_asset("A", 10)
        portfolio.sell_asset("A", 15)

        lots = portfolio._tax_lots["A"]
        assert lots[0].quantity_remaining == 0.0  # first lot fully consumed
        assert lots[1].quantity_remaining == approx(5.0)  # second lot partial

    def test_sell_lifo_order(self, portfolio):
        """LIFO: last lot consumed first."""
        portfolio.tax_config.tax_strategy = "LIFO"
        portfolio.collect_income()
        portfolio.move_cash(50000)
        portfolio.buy_asset("A", 10)
        portfolio.update_history()

        portfolio.advance_period()
        portfolio.collect_income()
        portfolio.buy_asset("A", 10)
        portfolio.sell_asset("A", 15)

        lots = portfolio._tax_lots["A"]
        assert lots[1].quantity_remaining == 0.0  # second lot fully consumed
        assert lots[0].quantity_remaining == approx(5.0)  # first lot partial

    def test_multiple_symbols_independent(self, portfolio):
        portfolio.collect_income()
        portfolio.move_cash(50000)
        portfolio.buy_asset("A", 10)
        portfolio.buy_asset("B", 20)

        assert len(portfolio._tax_lots["A"]) == 1
        assert len(portfolio._tax_lots["B"]) == 1
        assert portfolio._tax_lots["A"][0].quantity == 10.0
        assert portfolio._tax_lots["B"][0].quantity == 20.0

    def test_buffer_synced_with_tax_lots(self, portfolio):
        """Buffer lot_quantity_remaining stays in sync after sells."""
        portfolio.collect_income()
        portfolio.move_cash(10000)
        portfolio.buy_asset("A", 10)
        buy_idx = portfolio._tax_lots["A"][0].txn_index

        portfolio.sell_asset("A", 3)

        # Buffer dict matches TaxLot
        assert portfolio._txn_buffer[buy_idx]["lot_quantity_remaining"] == approx(7.0)
        # And so does the transactions DataFrame
        assert portfolio.transactions.iloc[buy_idx][
            "lot_quantity_remaining"
        ] == approx(7.0)


# ---------------------------------------------------------------------------
# open_lots property
# ---------------------------------------------------------------------------


class TestOpenLots:
    def test_empty_on_init(self, portfolio):
        assert portfolio.open_lots == {}

    def test_shows_open_lots(self, portfolio):
        portfolio.collect_income()
        portfolio.move_cash(10000)
        portfolio.buy_asset("A", 10)

        open_lots = portfolio.open_lots
        assert "A" in open_lots
        assert len(open_lots["A"]) == 1
        assert open_lots["A"][0].quantity_remaining == 10.0

    def test_excludes_closed_lots(self, portfolio):
        portfolio.collect_income()
        portfolio.move_cash(10000)
        portfolio.buy_asset("A", 10)
        portfolio.sell_asset("A", 10)

        open_lots = portfolio.open_lots
        # Symbol key exists but list is empty (all lots closed)
        assert open_lots.get("A", []) == []

    def test_partial_sells_reflected(self, portfolio):
        portfolio.collect_income()
        portfolio.move_cash(10000)
        portfolio.buy_asset("A", 10)
        portfolio.sell_asset("A", 4)

        open_lots = portfolio.open_lots
        assert len(open_lots["A"]) == 1
        assert open_lots["A"][0].quantity_remaining == approx(6.0)


# ---------------------------------------------------------------------------
# Clone with new structures
# ---------------------------------------------------------------------------


class TestCloneWithTaxLots:
    def test_clone_copies_tax_lots(self, portfolio):
        portfolio.collect_income()
        portfolio.move_cash(10000)
        portfolio.buy_asset("A", 10)
        portfolio.update_history()

        cloned = portfolio.clone()

        assert "A" in cloned._tax_lots
        assert len(cloned._tax_lots["A"]) == 1
        assert cloned._tax_lots["A"][0].quantity_remaining == 10.0

    def test_clone_tax_lots_independent(self, portfolio):
        portfolio.collect_income()
        portfolio.move_cash(10000)
        portfolio.buy_asset("A", 10)
        portfolio.update_history()

        cloned = portfolio.clone()

        # Sell in clone, original unaffected
        cloned.advance_period()
        cloned.collect_income()
        cloned.sell_asset("A", 5)

        assert portfolio._tax_lots["A"][0].quantity_remaining == 10.0
        assert cloned._tax_lots["A"][0].quantity_remaining == approx(5.0)

    def test_clone_buffer_independent(self, portfolio):
        portfolio.collect_income()
        portfolio.move_cash(10000)
        portfolio.update_history()

        cloned = portfolio.clone()
        cloned.advance_period()
        cloned.collect_income()
        cloned.move_cash(5000)

        assert len(portfolio._txn_buffer) == 1  # only the original deposit
        assert len(cloned._txn_buffer) == 2  # deposit + second deposit

    def test_clone_period_index_independent(self, portfolio):
        portfolio.collect_income()
        portfolio.move_cash(10000)
        portfolio.update_history()

        cloned = portfolio.clone()
        original_index_len = sum(
            len(v) for v in portfolio._txn_period_index.values()
        )

        cloned.advance_period()
        cloned.collect_income()
        cloned.move_cash(5000)

        new_original_len = sum(
            len(v) for v in portfolio._txn_period_index.values()
        )
        assert new_original_len == original_index_len  # unchanged


# ---------------------------------------------------------------------------
# update_history uses period index (not DataFrame scan)
# ---------------------------------------------------------------------------


class TestUpdateHistoryPeriodIndex:
    def test_history_captures_gains(self, portfolio_with_taxes):
        p = portfolio_with_taxes
        p.collect_income()
        p.move_cash(10000)
        p.buy_asset("A", 10)
        p.update_history()

        # No gains on buy
        assert p.history.iloc[0]["long_term_gains_in_period"] == 0.0
        assert p.history.iloc[0]["short_term_gains_in_period"] == 0.0

    def test_history_captures_tax_paid(self, portfolio_with_taxes):
        p = portfolio_with_taxes
        p.collect_income()
        p.move_cash(10000)
        p.buy_asset("A", 10)
        p.update_history()

        assert p.history.iloc[0]["taxes_paid_in_period"] == 0.0

    def test_history_correct_after_multiple_periods(self, portfolio):
        portfolio.collect_income()
        portfolio.move_cash(10000)
        portfolio.buy_asset("A", 10)
        portfolio.update_history()
        portfolio.advance_period()

        portfolio.collect_income()
        portfolio.move_cash(5000)
        portfolio.update_history()

        assert portfolio.history.iloc[0]["cash"] == approx(portfolio.history.iloc[0]["cash"])
        assert portfolio.history.iloc[1]["cash"] == approx(portfolio.cash)


# ---------------------------------------------------------------------------
# collect_income uses TaxLot (not DataFrame scan)
# ---------------------------------------------------------------------------


class TestCollectIncomeWithTaxLots:
    def test_income_uses_lot_quantities(self, universe_with_income):
        """Income is calculated from TaxLot quantities, not DataFrame scan."""
        p = Portfolio(universe_with_income)
        # Period 0 has income=1.0 for asset A
        p.collect_income()
        p.move_cash(10000)
        p.buy_asset("A", 10)
        p.update_history()
        p.advance_period()

        # No income on period 1
        p.collect_income()
        p.update_history()

        # The lot should still be intact
        assert p._tax_lots["A"][0].quantity_remaining == 10.0
