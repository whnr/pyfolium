import pandas as pd
from pytest import approx, raises

from pyfolium.core import (
    Asset,
    AssetUniverse,
    FeeConfig,
    Portfolio,
    PortfolioState,
    TaxConfig,
)


def assert_transaction(
    transaction: pd.Series,
    period: pd.PeriodDtype,
    type: str,
    transaction_amount: float,
    symbol: str | None = None,
    quantity: float | None = None,
    lot_quantity_remaining: float | None = None,
    price: float | None = None,
    fee: float | None = None,
    cost_basis_per_share: float | None = None,
    tax_paid: float | None = None,
    long_term_gains: float | None = None,
    short_term_gains: float | None = None,
):
    """
    Asserts that a transaction series has the expected values.

    It taks a single transaction from the Portfolio.transactions DataFrame.
    All other parameters are the expected values for the transaction.

    """

    # Helper function to handle NaN vs None comparison using pandas
    def assert_value_equal(actual, expected):
        if pd.isna(expected):  # check if expected value is NaN
            assert pd.isna(actual)  # check if actual value is also NaN
        else:
            assert actual == expected

    # Perform assertions using named arguments
    assert_value_equal(transaction["period"], period)
    assert_value_equal(transaction["type"], type)
    assert_value_equal(transaction["symbol"], symbol)
    assert_value_equal(transaction["quantity"], quantity)
    assert_value_equal(transaction["lot_quantity_remaining"], lot_quantity_remaining)
    assert_value_equal(transaction["price"], price)
    assert_value_equal(transaction["fee"], fee)
    assert_value_equal(transaction["cost_basis_per_share"], cost_basis_per_share)
    assert_value_equal(transaction["tax_paid"], tax_paid)
    assert_value_equal(transaction["long_term_gains"], long_term_gains)
    assert_value_equal(transaction["short_term_gains"], short_term_gains)
    assert_value_equal(transaction["transaction_amount"], transaction_amount)


def test_portfolio_init_with_no_assets_raises():
    """Testing the minimal initialization of the Portfolio class."""

    asset_universe = AssetUniverse(data_frequency="D")

    # Adding an empty universe shall raise an error
    with raises(ValueError):
        Portfolio(asset_universe=asset_universe)


def test_minimal_portfolio_init(asset_universe_with_assets):
    portfolio = Portfolio(asset_universe=asset_universe_with_assets)

    assert (
        portfolio.current_period
        == asset_universe_with_assets.get_period_index_range()[0]
    )
    assert isinstance(portfolio.current_period, pd.Period)

    assert portfolio.cash == 0.0
    assert isinstance(portfolio.cash, float)

    assert portfolio.tax_owed == 0.0
    assert isinstance(portfolio.tax_owed, float)
    assert isinstance(portfolio.tax_config, TaxConfig)
    assert isinstance(portfolio.fee_config, FeeConfig)

    assert isinstance(portfolio.history, pd.DataFrame)
    assert set(portfolio.history.columns) == set(Portfolio.history_columns)

    assert isinstance(portfolio.transactions, pd.DataFrame)
    assert set(portfolio.transactions.columns) == set(
        Portfolio.transaction_columns.keys()
    )

    assert isinstance(portfolio.holdings, pd.DataFrame)
    expected_holdings_columns = asset_universe_with_assets.asset_symbols_list
    assert set(portfolio.holdings.columns) == set(expected_holdings_columns)


def test_portfolio_basic_states(portfolio_with_assets_taxes_fees):
    portfolio = portfolio_with_assets_taxes_fees

    current_period = portfolio.current_period

    assert portfolio._states[current_period] == PortfolioState.COLLECT_INCOME

    portfolio.collect_income()
    assert portfolio._states[current_period] == PortfolioState.TRANSACT

    portfolio.update_history()
    assert portfolio._states[current_period] == PortfolioState.DONE

    portfolio.advance_period()
    current_period = portfolio.current_period
    assert portfolio._states[current_period] == PortfolioState.COLLECT_INCOME


def test_portfolio_wrong_state_errors(portfolio_with_assets_taxes_fees):
    portfolio = portfolio_with_assets_taxes_fees

    # attempt to transact before collecting income
    with raises(
        RuntimeError, match="wrong state: COLLECT_INCOME. Expected state: TRANSACT"
    ):
        portfolio.move_cash(1.0)

    portfolio.collect_income()
    # attempt to collect income again
    with raises(
        RuntimeError, match="wrong state: TRANSACT. Expected state: COLLECT_INCOME"
    ):
        portfolio.collect_income()

    portfolio.update_history()
    with raises(
        RuntimeError, match="wrong state: DONE. Expected state: COLLECT_INCOME"
    ):
        portfolio.collect_income()


def test_portfolio_state_incomplete_periods_errors(portfolio_with_assets_taxes_fees):
    portfolio = portfolio_with_assets_taxes_fees

    # attempt to start in the wrong period
    with raises(RuntimeError, match="Last period was not in the DONE state"):
        portfolio.advance_period()


def test_advance_period():
    universe = AssetUniverse(data_frequency="D")
    periods = pd.period_range("2025-01-01", periods=2, freq="D")
    Asset(
        symbol="TEST",
        asset_universe=universe,
        data=pd.DataFrame(
            {
                "price": [1.0, 2.0],
                "income": [1.0, 2.0],
            },
            index=periods,
        ),
    )
    portfolio = Portfolio(asset_universe=universe)

    portfolio.collect_income()
    portfolio.update_history()
    portfolio.advance_period()
    assert portfolio.current_period == portfolio.history.index[1]

    portfolio.collect_income()
    portfolio.update_history()
    with raises(StopIteration, match="End of history reached"):
        portfolio.advance_period()


def test_advance_period_carries_forward_holdings(portfolio_with_assets_taxes_fees):
    """Holdings from the current period are carried forward on advance."""
    portfolio = portfolio_with_assets_taxes_fees
    symbol = "TEST"

    # Buy in period 0
    portfolio.collect_income()
    portfolio.cash += 10_000.0
    portfolio.buy_asset(symbol, 5.0)
    portfolio.update_history()

    current_holdings = portfolio.holdings.loc[portfolio.current_period, symbol]
    assert current_holdings == 5.0

    # Advance — period 1 should inherit period 0's holdings
    portfolio.advance_period()
    assert portfolio.holdings.loc[portfolio.current_period, symbol] == 5.0


def test_buy_sell_only_modifies_current_period(portfolio_with_assets_taxes_fees):
    """Trades only affect the current period row, not future periods."""
    portfolio = portfolio_with_assets_taxes_fees
    symbol = "TEST"

    # Buy in period 0
    portfolio.collect_income()
    portfolio.cash += 10_000.0
    portfolio.buy_asset(symbol, 5.0)

    # Future periods should still be 0 (not forward-filled)
    assert portfolio.holdings.iloc[0][symbol] == 5.0
    assert portfolio.holdings.iloc[1][symbol] == 0.0

    portfolio.update_history()
    portfolio.advance_period()

    # After advance, period 1 is carried forward
    assert portfolio.holdings.iloc[1][symbol] == 5.0

    # Sell in period 1
    portfolio.collect_income()
    portfolio.sell_asset(symbol, 3.0)
    assert portfolio.holdings.loc[portfolio.current_period, symbol] == 2.0

    # Period 2 still untouched until next advance
    assert portfolio.holdings.iloc[2][symbol] == 0.0


def test_register_transaction(portfolio_with_assets_taxes_fees):
    portfolio = portfolio_with_assets_taxes_fees

    # add a minimal valid transaction
    portfolio._register_transaction(
        type="deposit",
        transaction_amount=1.0,
    )

    assert len(portfolio.transactions) == 1
    assert portfolio.transactions.iloc[0]["period"] == portfolio.current_period
    assert portfolio.transactions.iloc[0]["type"] == "deposit"
    assert portfolio.transactions.iloc[0]["transaction_amount"] == 1.0

    # add a transaction that uses all the columns
    # this is non-sense, but this methods job is just to register
    # the transaction
    portfolio._register_transaction(
        type="sell",
        transaction_amount=1.0,
        symbol="TEST",
        quantity=-2.0,
        lot_quantity_remaining=3.0,
        price=4.0,
        fee=5.0,
        cost_basis_per_share=6.0,
        tax_paid=7.0,
        long_term_gains=8.0,
        short_term_gains=9.0,
    )

    assert len(portfolio.transactions) == 2
    assert portfolio.transactions.iloc[1]["period"] == portfolio.current_period
    assert portfolio.transactions.iloc[1]["type"] == "sell"
    assert portfolio.transactions.iloc[1]["transaction_amount"] == 1.0
    assert portfolio.transactions.iloc[1]["symbol"] == "TEST"
    assert portfolio.transactions.iloc[1]["quantity"] == -2.0
    assert portfolio.transactions.iloc[1]["lot_quantity_remaining"] == 3.0
    assert portfolio.transactions.iloc[1]["price"] == 4.0
    assert portfolio.transactions.iloc[1]["fee"] == 5.0
    assert portfolio.transactions.iloc[1]["cost_basis_per_share"] == 6.0
    assert portfolio.transactions.iloc[1]["tax_paid"] == 7.0
    assert portfolio.transactions.iloc[1]["long_term_gains"] == 8.0
    assert portfolio.transactions.iloc[1]["short_term_gains"] == 9.0


def test_register_transaction_missing_minimum_colums(portfolio_with_assets_taxes_fees):
    portfolio = portfolio_with_assets_taxes_fees

    with raises(KeyError, match="Missing required columns: {'transaction_amount'}"):
        portfolio._register_transaction(type="deposit")


def test_register_transaction_raises_if_period_provided(
    portfolio_with_assets_taxes_fees,
):
    """Test that we raise, even if the correct period is provided.
    We don't want people to provide the period manually."""
    portfolio = portfolio_with_assets_taxes_fees

    with raises(
        ValueError,
        match="Remove the `period` kwarg. We will always use the current period.",
    ):
        portfolio._register_transaction(
            period=portfolio.current_period,
            type="deposit",
            transaction_amount=1.0,
        )


def test_register_transaction_invalid_type(portfolio_with_assets_taxes_fees):
    portfolio = portfolio_with_assets_taxes_fees

    with raises(ValueError, match="Invalid transaction type: invalid_type"):
        portfolio._register_transaction(
            type="invalid_type",
            transaction_amount=1.0,
        )


def test_register_transaction_unexpected_columns(portfolio_with_assets_taxes_fees):
    portfolio = portfolio_with_assets_taxes_fees

    with raises(
        KeyError, match="Unexpected columns in transaction: {'unexpected_column'}"
    ):
        portfolio._register_transaction(
            type="deposit",
            transaction_amount=1.0,
            unexpected_column=1.0,
        )


def test_update_history(portfolio_with_assets_taxes_fees):
    portfolio = portfolio_with_assets_taxes_fees

    portfolio.collect_income()
    # Add mock data to the portfolio that should be ignored
    portfolio._register_transaction(
        type="sell",
        transaction_amount=500.0,
        long_term_gains=1000.0,
        short_term_gains=2000.0,
        tax_paid=3000.0,
    )
    portfolio.update_history()
    portfolio.advance_period()

    # Get the portfolio in the right state
    portfolio.collect_income()
    # Add mock data to the portfolio
    portfolio.cash = 100.0
    portfolio.tax_owed = 10.0
    portfolio._register_transaction(
        type="sell",
        transaction_amount=500.0,
        long_term_gains=10.0,
        short_term_gains=20.0,
        tax_paid=30.0,
    )
    portfolio._register_transaction(
        type="sell",
        transaction_amount=500.0,
        long_term_gains=1.0,
        short_term_gains=2.0,
        tax_paid=3.0,
    )
    portfolio.update_history()

    current_period = portfolio.current_period
    assert portfolio.history.loc[current_period]["cash"] == 100.0
    assert portfolio.history.loc[current_period]["tax_owed"] == 10.0
    assert portfolio.history.loc[current_period]["long_term_gains_in_period"] == 11.0
    assert portfolio.history.loc[current_period]["short_term_gains_in_period"] == 22.0
    assert portfolio.history.loc[current_period]["taxes_paid_in_period"] == 33.0


def test_update_history_transitions_to_done_state(portfolio_with_assets_taxes_fees):
    portfolio = portfolio_with_assets_taxes_fees

    portfolio.collect_income()
    portfolio.update_history()
    assert portfolio._states[portfolio.current_period] == PortfolioState.DONE


def test_update_history_raised_if_not_in_transact_state(
    portfolio_with_assets_taxes_fees,
):
    portfolio = portfolio_with_assets_taxes_fees

    with raises(
        RuntimeError,
        match="wrong state: COLLECT_INCOME. Expected state: TRANSACT",
    ):
        portfolio.update_history()

    portfolio._states[portfolio.current_period] = PortfolioState.DONE
    with raises(
        RuntimeError,
        match="wrong state: DONE. Expected state: TRANSACT",
    ):
        portfolio.update_history()


def test_collect_income(asset_universe_for_income_testing):
    # simple setup: 2 assets, 3 periods
    asset_universe = asset_universe_for_income_testing

    portfolio = Portfolio(asset_universe=asset_universe)

    # we are not holding anything yet and expect no income
    portfolio.collect_income()
    portfolio.move_cash(100)
    portfolio.buy_asset(symbol="A", quantity=10.0)
    portfolio.update_history()
    # we are holding one asset and expect no income because we just bought it
    current_period = portfolio.current_period
    assert portfolio.history.loc[current_period]["long_term_gains_in_period"] == 0.0
    assert portfolio.history.loc[current_period]["short_term_gains_in_period"] == 0.0

    portfolio.advance_period()
    # we are holding 10 of `A` and expect 20 short term income
    portfolio.collect_income()
    portfolio.sell_asset(symbol="A", quantity=10.0)
    portfolio.update_history()

    current_period = portfolio.current_period
    assert portfolio.history.loc[current_period]["long_term_gains_in_period"] == 0.0
    assert portfolio.history.loc[current_period]["short_term_gains_in_period"] == 20.0
    assert portfolio.cash == 120

    portfolio.advance_period()
    # we're back to no holdings. Don't expect any extra income
    portfolio.collect_income()
    portfolio.update_history()
    assert portfolio.cash == 120


def test_collect_income_negative_gains(asset_universe_for_income_testing):
    tax_config = TaxConfig(
        short_term_rate=0.5,
    )
    portfolio = Portfolio(
        asset_universe=asset_universe_for_income_testing, tax_config=tax_config
    )

    portfolio.collect_income()
    # We are buying asset B, price 20
    # Negative gains of -4, -5, -6 over the 3 periods
    quantity = 5
    portfolio.move_cash(100)
    portfolio.buy_asset(symbol="B", quantity=quantity)
    portfolio.update_history()
    current_period = portfolio.current_period
    assert portfolio.history.loc[current_period]["short_term_gains_in_period"] == 0.0
    assert portfolio.cash == 0

    portfolio.advance_period()
    portfolio.collect_income()
    assert portfolio.tax_owed == 0
    assert portfolio.cash == -5 * quantity
    portfolio.update_history()
    current_period = portfolio.current_period
    assert portfolio.history.loc[current_period]["short_term_gains_in_period"] == -25.0


def test_collect_income_short_long_term(asset_universe_for_income_testing):
    # simple setup: 2 assets, 3 periods
    asset_universe = asset_universe_for_income_testing
    tax_config = TaxConfig(
        long_term_holding_period=pd.DateOffset(days=2),
    )

    portfolio = Portfolio(asset_universe=asset_universe, tax_config=tax_config)
    # we are not holding anything yet and expect no income
    portfolio.collect_income()
    portfolio.move_cash(100)
    portfolio.buy_asset(symbol="A", quantity=10.0)
    portfolio.update_history()
    portfolio.advance_period()

    # we are holding 10 of `A` and expect 20 short term income
    portfolio.collect_income()
    portfolio.update_history()
    current_period = portfolio.current_period
    assert portfolio.history.loc[current_period]["long_term_gains_in_period"] == 0.0
    assert portfolio.history.loc[current_period]["short_term_gains_in_period"] == 20.0
    assert portfolio.cash == 20

    portfolio.advance_period()
    # we're now in the long term holding period and expect 30 long term income
    portfolio.collect_income()
    portfolio.update_history()
    current_period = portfolio.current_period
    assert portfolio.history.loc[current_period]["long_term_gains_in_period"] == 30.0
    assert portfolio.history.loc[current_period]["short_term_gains_in_period"] == 0.0
    assert portfolio.cash == 50


def test_collect_income_short_long_term_50tax(
    asset_universe_for_income_testing,
):
    # simple setup: 2 assets, 3 periods
    asset_universe = asset_universe_for_income_testing
    # 50% tax rate no withholding
    tax_config = TaxConfig(
        long_term_holding_period=pd.DateOffset(days=2),
        long_term_rate=0.5,
        short_term_rate=0.5,
    )

    portfolio = Portfolio(asset_universe=asset_universe, tax_config=tax_config)
    # we are not holding anything yet and expect no income
    portfolio.collect_income()
    portfolio.move_cash(100)
    portfolio.buy_asset(symbol="A", quantity=10.0)
    portfolio.update_history()

    portfolio.advance_period()

    # we are holding 10 of `A` and expect 20 short term income
    portfolio.collect_income()
    portfolio.update_history()
    current_period = portfolio.current_period
    assert portfolio.history.loc[current_period]["short_term_gains_in_period"] == 20.0
    assert portfolio.history.loc[current_period]["taxes_paid_in_period"] == 0
    assert portfolio.cash == 20
    assert portfolio.tax_owed == 10

    portfolio.advance_period()
    # we're now in the long term holding period and expect 30 long term income
    portfolio.collect_income()
    portfolio.update_history()
    current_period = portfolio.current_period
    assert portfolio.history.loc[current_period]["long_term_gains_in_period"] == 30.0
    assert portfolio.history.loc[current_period]["taxes_paid_in_period"] == 0
    assert portfolio.cash == 50
    assert portfolio.tax_owed == 25


def test_collect_income_short_long_term_tax_withholding(
    asset_universe_for_income_testing,
):
    # simple setup: 2 assets, 3 periods
    asset_universe = asset_universe_for_income_testing
    # 50% tax rate no withholding
    tax_config = TaxConfig(
        long_term_holding_period=pd.DateOffset(days=2),
        long_term_rate=0.5,
        short_term_rate=0.5,
        withhold_tax=True,
    )

    portfolio = Portfolio(asset_universe=asset_universe, tax_config=tax_config)
    # we are not holding anything yet and expect no income
    portfolio.collect_income()
    portfolio.move_cash(100)
    portfolio.buy_asset(symbol="A", quantity=10.0)
    portfolio.update_history()

    portfolio.advance_period()
    # we are holding 10 of `A` and expect 20 short term income
    portfolio.collect_income()
    portfolio.update_history()
    current_period = portfolio.current_period
    assert portfolio.history.loc[current_period]["short_term_gains_in_period"] == 20.0
    assert portfolio.history.loc[current_period]["taxes_paid_in_period"] == 10.0
    assert portfolio.cash == 10.0
    assert portfolio.tax_owed == 0.0

    portfolio.advance_period()
    # we're now in the long term holding period and expect 30 long term income
    portfolio.collect_income()
    portfolio.update_history()
    current_period = portfolio.current_period
    assert portfolio.history.loc[current_period]["long_term_gains_in_period"] == 30.0
    assert portfolio.history.loc[current_period]["taxes_paid_in_period"] == 15.0
    assert portfolio.cash == 25.0
    assert portfolio.tax_owed == 0.0


def test_collect_income_transaction(asset_universe_for_income_testing):
    # The previous test is already making sure that most of the logic works.
    # Let's just make sure that we fill all the expected fields here.abs

    # simple setup: 2 assets, 3 periods
    asset_universe = asset_universe_for_income_testing

    quantity = 10.0
    portfolio = Portfolio(asset_universe=asset_universe)
    # we are not holding anything yet and expect no income
    portfolio.collect_income()
    portfolio.move_cash(100)
    portfolio.buy_asset(symbol="A", quantity=quantity)
    portfolio.update_history()

    portfolio.advance_period()
    # we are holding 10 of `A` and expect 20 short term income
    portfolio.collect_income()

    assert_transaction(
        transaction=portfolio.transactions.iloc[2],
        period=portfolio.current_period,
        type="income",
        symbol="A",
        quantity=quantity,
        long_term_gains=0,
        short_term_gains=20,
        tax_paid=0,
        transaction_amount=20,
    )


def test_collect_income_states(portfolio_with_assets_taxes_fees):
    portfolio = portfolio_with_assets_taxes_fees

    portfolio.collect_income()
    assert portfolio._states[portfolio.current_period] == PortfolioState.TRANSACT

    with raises(
        RuntimeError, match="wrong state: TRANSACT. Expected state: COLLECT_INCOME"
    ):
        portfolio.collect_income()

    portfolio.update_history()
    with raises(
        RuntimeError, match="wrong state: DONE. Expected state: COLLECT_INCOME"
    ):
        portfolio.collect_income()


def test_move_cash(portfolio_with_assets_taxes_fees):
    portfolio = portfolio_with_assets_taxes_fees

    portfolio.collect_income()
    portfolio.move_cash(100)
    assert portfolio.cash == 100
    portfolio.move_cash(50)
    assert portfolio.cash == 150
    portfolio.move_cash(-50)
    assert portfolio.cash == 100
    portfolio.move_cash(0.0)
    assert portfolio.cash == 100


def test_move_cash_transaction(portfolio_with_assets_taxes_fees):
    portfolio = portfolio_with_assets_taxes_fees

    portfolio.collect_income()
    # Resgister two transactions
    portfolio.move_cash(100)
    portfolio.move_cash(-100)

    assert_transaction(
        transaction=portfolio.transactions.iloc[0],
        period=portfolio.current_period,
        type="deposit",
        transaction_amount=100.0,
    )
    assert_transaction(
        transaction=portfolio.transactions.iloc[1],
        period=portfolio.current_period,
        type="withdrawal",
        transaction_amount=-100.0,
    )


def test_move_cash_states(portfolio_with_assets_taxes_fees):
    portfolio = portfolio_with_assets_taxes_fees

    with raises(
        RuntimeError, match="wrong state: COLLECT_INCOME. Expected state: TRANSACT"
    ):
        portfolio.move_cash(100)

    portfolio.collect_income()
    portfolio.move_cash(100)
    assert portfolio._states[portfolio.current_period] == PortfolioState.TRANSACT
    portfolio.update_history()

    with raises(RuntimeError, match="wrong state: DONE. Expected state: TRANSACT"):
        portfolio.move_cash(100)


def test_buy_asset(portfolio_with_assets):
    portfolio = portfolio_with_assets
    period = portfolio.current_period
    portfolio.collect_income()

    quantity = 10.0
    expected_cost = portfolio.asset_universe.price_matrix.loc[period, "TEST"] * quantity
    portfolio.cash += expected_cost
    portfolio.buy_asset("TEST", quantity)

    assert portfolio.holdings.iloc[0]["TEST"] == quantity
    assert portfolio.cash == 0


def test_buy_asset_transaction(portfolio_with_assets_taxes_fees):
    portfolio = portfolio_with_assets_taxes_fees
    portfolio.collect_income()

    quantity = 10.0
    price = portfolio.asset_universe.price_matrix.loc[portfolio.current_period, "TEST"]
    expected_fee = portfolio.fee_config.calculate_fee(quantity * price)
    expected_cost = price * quantity + expected_fee
    expected_cost_basis_per_share = expected_cost / quantity
    portfolio.cash += expected_cost
    portfolio.buy_asset("TEST", quantity)

    assert portfolio.cash == 0
    assert len(portfolio.transactions) == 1

    assert_transaction(
        transaction=portfolio.transactions.iloc[0],
        period=portfolio.current_period,
        type="buy",
        symbol="TEST",
        quantity=quantity,
        lot_quantity_remaining=quantity,
        price=price,
        fee=expected_fee,
        cost_basis_per_share=expected_cost_basis_per_share,
        transaction_amount=-expected_cost,
    )


def test_buy_asset_quantity_errors(portfolio_with_assets):
    portfolio = portfolio_with_assets
    portfolio.collect_income()

    with raises(ValueError):
        portfolio.buy_asset("TEST", 0.0)

    with raises(ValueError):
        portfolio.buy_asset("TEST", -1.0)

    with raises(KeyError):
        portfolio.buy_asset("UNKNOWN", 10.0)


def test_buy_asset_states(portfolio_with_assets):
    portfolio = portfolio_with_assets

    with raises(
        RuntimeError, match="wrong state: COLLECT_INCOME. Expected state: TRANSACT"
    ):
        portfolio.buy_asset("TEST", 10.0)

    portfolio.collect_income()
    portfolio.buy_asset("TEST", 10.0)
    assert portfolio._states[portfolio.current_period] == PortfolioState.TRANSACT


def test_sell_asset(asset_universe_for_sell_asset_testing):
    portfolio = Portfolio(asset_universe=asset_universe_for_sell_asset_testing)

    portfolio.collect_income()
    portfolio.move_cash(100)
    portfolio.buy_asset("A", 10.0)
    assert portfolio.cash == 0.0
    portfolio.update_history()

    portfolio.advance_period()
    portfolio.collect_income()

    portfolio.sell_asset("A", 5.0)
    assert portfolio.cash == 5.0 * 12.0
    portfolio.update_history()

    current_period = portfolio.current_period
    assert portfolio.holdings.iloc[1]["A"] == 5.0
    assert portfolio.history.loc[current_period]["short_term_gains_in_period"] == 10.0


def test_sell_asset_transaction(asset_universe_for_sell_asset_testing):
    portfolio = Portfolio(asset_universe=asset_universe_for_sell_asset_testing)

    portfolio.collect_income()

    portfolio.buy_asset("A", 10.0)
    portfolio.sell_asset("A", 5.0)

    assert len(portfolio.transactions) == 2

    assert_transaction(
        transaction=portfolio.transactions.iloc[1],
        period=portfolio.current_period,
        type="sell",
        symbol="A",
        quantity=5.0,
        price=10.0,
        fee=0.0,
        tax_paid=0.0,
        long_term_gains=0.0,
        short_term_gains=0.0,
        transaction_amount=50.0,
    )


def test_sell_asset_short_term_gains_and_tax_owed(
    portfolio_for_sell_asset_testing_1pct_fee_50pct_short_25pct_long,
):
    """This test covers short terms gain

    If this passes, then cost basis with fees is working as well!
    """
    portfolio = portfolio_for_sell_asset_testing_1pct_fee_50pct_short_25pct_long

    portfolio.collect_income()
    quantity = 10.0
    portfolio.move_cash(101.0)
    portfolio.buy_asset(symbol="A", quantity=quantity)
    assert portfolio.cash == 0
    cost_basis = 101.0 / quantity
    portfolio.update_history()

    portfolio.advance_period()
    portfolio.collect_income()
    portfolio.sell_asset(symbol="A", quantity=quantity)
    portfolio.update_history()

    # the sell transaction does not log a cost basis.
    # so we calculate the gains with the 1% fee deducted.
    expected_short_term_gains = (12 * (1 - 0.01) - cost_basis) * quantity
    assert portfolio.history.loc[portfolio.current_period][
        "short_term_gains_in_period"
    ] == approx(expected_short_term_gains)
    assert portfolio.tax_owed == approx(expected_short_term_gains * 0.5)


def test_sell_asset_long_term_gains(
    portfolio_for_sell_asset_testing_1pct_fee_50pct_short_25pct_long,
):
    portfolio = portfolio_for_sell_asset_testing_1pct_fee_50pct_short_25pct_long

    portfolio.collect_income()
    quantity = 10.0
    portfolio.move_cash(101.0)
    portfolio.buy_asset(symbol="A", quantity=quantity)
    assert portfolio.cash == 0
    cost_basis = 101.0 / quantity
    portfolio.update_history()

    portfolio.advance_period()
    portfolio.collect_income()
    portfolio.update_history()

    portfolio.advance_period()
    # now we have a long term gain
    portfolio.collect_income()
    portfolio.sell_asset(symbol="A", quantity=quantity)
    portfolio.update_history()
    current_period = portfolio.current_period

    # the sell transaction does not log a cost basis.
    # so we calculate the gains with the 1% fee deducted.
    expected_short_term_gains = (14 * (1 - 0.01) - cost_basis) * quantity
    assert portfolio.history.loc[current_period]["long_term_gains_in_period"] == approx(
        expected_short_term_gains
    )


def test_sell_asset_transaction_amount(
    portfolio_for_sell_asset_testing_1pct_fee_50pct_short_25pct_long,
):
    portfolio = portfolio_for_sell_asset_testing_1pct_fee_50pct_short_25pct_long

    portfolio.collect_income()
    quantity = 10.0
    portfolio.move_cash(101.0)
    portfolio.buy_asset(symbol="A", quantity=quantity)
    assert portfolio.cash == 0
    portfolio.update_history()

    portfolio.advance_period()
    portfolio.collect_income()
    portfolio.sell_asset(symbol="A", quantity=quantity)
    portfolio.update_history()

    # since we have no withholding we expect the whole money to flow
    # except for the 1% fee
    expected_transaction_amount = (12 * (1 - 0.01)) * quantity
    assert portfolio.cash == approx(expected_transaction_amount)
    assert portfolio.transactions.iloc[-1]["transaction_amount"] == approx(
        expected_transaction_amount
    )


def test_sell_asset_tax_paid(
    portfolio_for_sell_asset_testing_1pct_fee_50pct_short_25pct_long,
):
    portfolio = portfolio_for_sell_asset_testing_1pct_fee_50pct_short_25pct_long
    # We want to test withholding
    portfolio.tax_config.withhold_tax = True

    portfolio.collect_income()
    quantity = 10.0
    portfolio.move_cash(101.0)
    portfolio.buy_asset(symbol="A", quantity=quantity)
    assert portfolio.cash == 0
    cost_basis = 101.0 / quantity
    portfolio.update_history()

    portfolio.advance_period()
    portfolio.collect_income()
    portfolio.sell_asset(symbol="A", quantity=quantity)
    portfolio.update_history()

    expected_transaction_amount = (12 * (1 - 0.01)) * quantity
    expected_short_term_gains = (12 * (1 - 0.01) - cost_basis) * quantity
    expected_tax = expected_short_term_gains * 0.5

    current_period = portfolio.current_period
    assert portfolio.cash == approx(expected_transaction_amount - expected_tax)
    assert portfolio.tax_owed == 0
    assert portfolio.history.loc[current_period]["taxes_paid_in_period"] == approx(
        expected_tax
    )
    assert portfolio.transactions.iloc[-1]["tax_paid"] == approx(expected_tax)


def test_sell_asset_negative_capital_gains_with_withholding(
    portfolio_for_sell_asset_testing_1pct_fee_50pct_short_25pct_long,
):
    portfolio = portfolio_for_sell_asset_testing_1pct_fee_50pct_short_25pct_long
    # We want to test withholding
    portfolio.tax_config.withhold_tax = True

    portfolio.collect_income()
    quantity = 10.0
    portfolio.move_cash(202.0)
    portfolio.buy_asset(symbol="B", quantity=quantity)
    assert portfolio.cash == 0
    cost_basis = 202.0 / quantity
    portfolio.update_history()

    portfolio.advance_period()
    portfolio.collect_income()
    portfolio.sell_asset(symbol="B", quantity=quantity)
    portfolio.update_history()

    expected_proceeds = (15 * (1 - 0.01)) * quantity
    expected_short_term_gains = (15 * (1 - 0.01) - cost_basis) * quantity
    expected_tax = expected_short_term_gains * 0.5

    # since we have negative capital gains with withholding
    # we expect negative tax owed but no "tax" flowing into cash
    assert portfolio.cash == approx(expected_proceeds)
    assert portfolio.tax_owed == approx(expected_tax)
    assert portfolio.history.loc[portfolio.current_period]["taxes_paid_in_period"] == 0


def test_sell_asset_negative_capital_gains_no_withholding(
    portfolio_for_sell_asset_testing_1pct_fee_50pct_short_25pct_long,
):
    portfolio = portfolio_for_sell_asset_testing_1pct_fee_50pct_short_25pct_long
    # We want to test withholding
    assert portfolio.tax_config.withhold_tax is False

    portfolio.collect_income()
    quantity = 10.0
    portfolio.move_cash(202.0)
    portfolio.buy_asset(symbol="B", quantity=quantity)
    assert portfolio.cash == 0
    cost_basis = 202.0 / quantity
    portfolio.update_history()

    portfolio.advance_period()
    portfolio.collect_income()
    portfolio.sell_asset(symbol="B", quantity=quantity)
    portfolio.update_history()

    expected_proceeds = (15 * (1 - 0.01)) * quantity
    expected_short_term_gains = (15 * (1 - 0.01) - cost_basis) * quantity
    expected_tax = expected_short_term_gains * 0.5

    # since we have negative capital gains with no withholding
    # we expect negative tax owed but no "tax" flowing into cash
    assert portfolio.cash == approx(expected_proceeds)
    assert portfolio.tax_owed == approx(expected_tax)
    assert portfolio.history.loc[portfolio.current_period]["taxes_paid_in_period"] == 0


def test_sell_asset_tax_lot_handling_fifo(portfolio_with_assets):
    portfolio = portfolio_with_assets
    # It should be the default, but you never know
    portfolio.tax_config.tax_strategy = "FIFO"

    # First buy of quantity 10
    portfolio.collect_income()
    portfolio.buy_asset("TEST", 10.0)
    index_buy_1 = portfolio.transactions.index.max()
    portfolio.update_history()

    portfolio.advance_period()
    # Second buy of quantity 10
    portfolio.collect_income()
    portfolio.buy_asset("TEST", 10.0)
    index_buy_2 = portfolio.transactions.index.max()
    portfolio.update_history()

    portfolio.advance_period()
    portfolio.collect_income()
    portfolio.sell_asset("TEST", 5.0)
    assert portfolio.transactions.loc[index_buy_1]["lot_quantity_remaining"] == 5.0
    assert portfolio.transactions.loc[index_buy_2]["lot_quantity_remaining"] == 10.0

    portfolio.sell_asset("TEST", 10.0)
    assert portfolio.transactions.loc[index_buy_1]["lot_quantity_remaining"] == 0.0
    assert portfolio.transactions.loc[index_buy_2]["lot_quantity_remaining"] == 5.0

    portfolio.sell_asset("TEST", 5.0)
    assert portfolio.transactions.loc[index_buy_2]["lot_quantity_remaining"] == 0.0
    assert portfolio.transactions.loc[index_buy_2]["lot_quantity_remaining"] == 0.0


def test_sell_asset_tax_lot_handling_lifo(portfolio_with_assets):
    portfolio = portfolio_with_assets
    portfolio.tax_config.tax_strategy = "LIFO"

    portfolio.collect_income()
    # TODO 2 buy qty 10 transactions in the first two periods
    portfolio.buy_asset("TEST", 10.0)
    index_buy_1 = portfolio.transactions.index.max()
    portfolio.update_history()

    portfolio.advance_period()
    portfolio.collect_income()
    portfolio.buy_asset("TEST", 10.0)
    index_buy_2 = portfolio.transactions.index.max()
    portfolio.update_history()

    portfolio.advance_period()
    portfolio.collect_income()

    portfolio.sell_asset("TEST", 5.0)

    assert portfolio.transactions.loc[index_buy_1]["lot_quantity_remaining"] == 10.0
    assert portfolio.transactions.loc[index_buy_2]["lot_quantity_remaining"] == 5.0

    portfolio.sell_asset("TEST", 10.0)

    assert portfolio.transactions.loc[index_buy_1]["lot_quantity_remaining"] == 5.0
    assert portfolio.transactions.loc[index_buy_2]["lot_quantity_remaining"] == 0.0

    portfolio.sell_asset("TEST", 5.0)
    assert portfolio.transactions.loc[index_buy_2]["lot_quantity_remaining"] == 0.0
    assert portfolio.transactions.loc[index_buy_2]["lot_quantity_remaining"] == 0.0


def test_sell_asset_tax_strategy_error(portfolio_with_assets):
    portfolio = portfolio_with_assets
    portfolio.tax_config.tax_strategy = "UNKNOWN"

    portfolio.collect_income()

    with raises(ValueError, match="Invalid tax strategy"):
        portfolio.sell_asset("TEST", 10.0)


def test_sell_asset_quantity_errors(portfolio_with_assets):
    portfolio = portfolio_with_assets

    portfolio.collect_income()
    portfolio.buy_asset("TEST", 10.0)

    # Sell nothing
    with raises(ValueError, match="Quantity must be greater than 0"):
        portfolio.sell_asset("TEST", 0.0)

    # Sell quantity less than 0
    with raises(ValueError, match="Quantity must be greater than 0"):
        portfolio.sell_asset("TEST", -1.0)

    # Sell more than we own
    with raises(ValueError, match="is greater than current holdings"):
        portfolio.sell_asset("TEST", 20.0)

    # TODO this also works for non-existent assests.
    # But the exceptions should be more explicit


def test_sell_asset_states(portfolio_with_assets):
    portfolio = portfolio_with_assets

    # This also ensures that the state check is the first exception
    # that the method raises
    with raises(
        RuntimeError, match="wrong state: COLLECT_INCOME. Expected state: TRANSACT"
    ):
        portfolio.sell_asset("TEST", 10.0)

    portfolio.collect_income()
    portfolio.buy_asset("TEST", 10.0)
    portfolio.sell_asset("TEST", 10.0)
    assert portfolio._states[portfolio.current_period] == PortfolioState.TRANSACT


def test_pay_tax(portfolio_with_assets_taxes_fees):
    portfolio = portfolio_with_assets_taxes_fees

    portfolio.collect_income()

    # pay all the tax
    portfolio.tax_owed = 100
    portfolio.pay_tax()
    assert portfolio.tax_owed == 0
    assert portfolio.cash == -100

    # pay spefic amount of tax
    portfolio.tax_owed = 100
    portfolio.pay_tax(50)
    assert portfolio.tax_owed == 50
    assert portfolio.cash == -150
    portfolio.tax_owed = 100

    # paying 0 shouldn't change anything
    portfolio.pay_tax(0)
    assert portfolio.tax_owed == 100

    assert len(portfolio.transactions) == 2


def test_pay_tax_transaction(portfolio_with_assets_taxes_fees):
    portfolio = portfolio_with_assets_taxes_fees

    portfolio.collect_income()
    portfolio.tax_owed = 100
    portfolio.pay_tax()

    assert len(portfolio.transactions) == 1

    assert_transaction(
        transaction=portfolio.transactions.iloc[0],
        period=portfolio.current_period,
        type="pay_tax",
        transaction_amount=-100,
    )


def test_pay_tax_errors(portfolio_with_assets_taxes_fees):
    portfolio = portfolio_with_assets_taxes_fees

    portfolio.collect_income()
    with raises(ValueError, match="Amount is greater than tax owed"):
        portfolio.pay_tax(1.0)

    with raises(ValueError, match="Amount is negative. That's not how tax works."):
        portfolio.pay_tax(-1.0)


def test_pay_tax_states(portfolio_with_assets_taxes_fees):
    portfolio = portfolio_with_assets_taxes_fees
    current_period = portfolio.current_period

    portfolio.collect_income()
    portfolio.pay_tax()
    assert portfolio._states[current_period] == PortfolioState.TRANSACT
    portfolio.update_history()

    with raises(RuntimeError, match="wrong state: DONE. Expected state: TRANSACT"):
        portfolio.pay_tax()
