import pandas as pd
from pytest import raises

from hhfk.core import AssetUniverse, FeeConfig, Portfolio, PortfolioState, TaxConfig


def test_portfolio_init_with_no_assets_raises():
    """Testing the minimal initialization of the Portfolio class."""

    asset_universe = AssetUniverse(data_frequency="D")

    # Adding an empty universe shall raise an error
    with raises(ValueError):
        portfolio = Portfolio(asset_universe=asset_universe)


def test_minimal_portfolio_init(asset_universe_with_assets):
    portfolio = Portfolio(asset_universe=asset_universe_with_assets)
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


def test_portfolio_basic_states(portfolio_with_config):
    portfolio = portfolio_with_config

    current_period = portfolio.history.index[0]

    assert portfolio._states[current_period] == PortfolioState.COLLECT_INCOME

    portfolio.collect_income_per_period(current_period)
    assert portfolio._states[current_period] == PortfolioState.TRANSACT

    portfolio.update_history_for_period(current_period)
    assert portfolio._states[current_period] == PortfolioState.DONE

    current_period = portfolio.history.index[1]
    assert portfolio._states[current_period] == PortfolioState.COLLECT_INCOME


def test_portfolio_wrong_state_errors(portfolio_with_config):
    portfolio = portfolio_with_config

    current_period = portfolio.history.index[0]

    # attempt to transact before collecting income
    with raises(
        RuntimeError, match="wrong state: COLLECT_INCOME. Expected state: TRANSACT"
    ):
        portfolio.move_cash(current_period, 1.0)

    portfolio.collect_income_per_period(current_period)
    # attempt to collect income again
    with raises(
        RuntimeError, match="wrong state: TRANSACT. Expected state: COLLECT_INCOME"
    ):
        portfolio.collect_income_per_period(current_period)

    portfolio.update_history_for_period(current_period)
    with raises(
        RuntimeError, match="wrong state: DONE. Expected state: COLLECT_INCOME"
    ):
        portfolio.collect_income_per_period(current_period)


def test_portfolio_state_incomplete_periods_errors(portfolio_with_config):
    portfolio = portfolio_with_config

    # attempt to start in the wrong period
    current_period = portfolio.history.index[1]
    with raises(RuntimeError, match="Last period was not in the DONE state"):
        portfolio.collect_income_per_period(current_period)


def test_update_future_holdings_change_whole_future(portfolio_with_config):
    portfolio = portfolio_with_config
    symbol_1 = "TEST"
    symbol_2 = "TEST2"

    # updates all holdings in the future
    current_period = portfolio.history.index[0]
    portfolio._update_future_holdings(current_period, symbol_1, 1.0)
    assert portfolio.holdings[symbol_1].all() == 1.0
    assert portfolio.holdings[symbol_2].all() == 0.0


def test_update_future_holdings_keep_past_untouched(portfolio_with_config):
    portfolio = portfolio_with_config
    symbol_1 = "TEST"

    current_period = portfolio.history.index[0]
    portfolio._update_future_holdings(current_period, symbol_1, 1.0)
    current_period = portfolio.history.index[1]
    portfolio._update_future_holdings(current_period, symbol_1, 2.0)
    assert (portfolio.holdings.iloc[1:][symbol_1] == 3.0).all()
    assert portfolio.holdings.iloc[0][symbol_1] == 1.0


def test_update_future_holdings_reduce_holdings(portfolio_with_config):
    portfolio = portfolio_with_config
    symbol_1 = "TEST"
    symbol_2 = "TEST2"

    current_period = portfolio.history.index[0]
    portfolio._update_future_holdings(current_period, symbol_1, 1.0)
    current_period = portfolio.history.index[1]
    portfolio._update_future_holdings(current_period, symbol_1, 2.0)
    current_period = portfolio.history.index[2]
    portfolio._update_future_holdings(current_period, symbol_1, -1.0)
    assert (portfolio.holdings.iloc[2:][symbol_1] == 2.0).all()


def test_register_transaction(portfolio_with_config):
    portfolio = portfolio_with_config
    current_period = portfolio.history.index[0]

    # add a minimal valid transaction
    portfolio._register_transaction(
        period=current_period,
        type="deposit",
        transaction_amount=1.0,
    )

    assert len(portfolio.transactions) == 1
    assert portfolio.transactions.iloc[0]["period"] == current_period
    assert portfolio.transactions.iloc[0]["type"] == "deposit"
    assert portfolio.transactions.iloc[0]["transaction_amount"] == 1.0

    # add a transaction that uses all the columns
    # this is non-sense, but this methods job is just to register
    # the transaction
    portfolio._register_transaction(
        period=current_period,
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
    assert portfolio.transactions.iloc[1]["period"] == current_period
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


def test_register_transaction_missing_minimum_colums(portfolio_with_config):
    portfolio = portfolio_with_config
    current_period = portfolio.history.index[0]

    with raises(KeyError, match="Missing required columns: {'transaction_amount'}"):
        portfolio._register_transaction(period=current_period, type="deposit")


def test_register_transaction_invalid_type(portfolio_with_config):
    portfolio = portfolio_with_config
    current_period = portfolio.history.index[0]

    with raises(ValueError, match="Invalid transaction type: invalid_type"):
        portfolio._register_transaction(
            period=current_period,
            type="invalid_type",
            transaction_amount=1.0,
        )


def test_register_transaction_invalid_period(portfolio_with_config):
    portfolio = portfolio_with_config
    invalid_period = pd.Period("1970-01")

    with raises(ValueError, match="Invalid period: 1970-01"):
        portfolio._register_transaction(
            period=invalid_period,
            type="deposit",
            transaction_amount=1.0,
        )


def test_register_transaction_unexpected_columns(portfolio_with_config):
    portfolio = portfolio_with_config
    current_period = portfolio.history.index[0]

    with raises(
        KeyError, match="Unexpected columns in transaction: {'unexpected_column'}"
    ):
        portfolio._register_transaction(
            period=current_period,
            type="deposit",
            transaction_amount=1.0,
            unexpected_column=1.0,
        )


def test_update_history_for_period(portfolio_with_config):
    portfolio = portfolio_with_config
    previous_period = portfolio.history.index[0]
    current_period = portfolio.history.index[1]

    portfolio.collect_income_per_period(previous_period)
    # Add mock data to the portfolio that should be ignored
    portfolio._register_transaction(
        period=previous_period,
        type="sell",
        transaction_amount=500.0,
        long_term_gains=1000.0,
        short_term_gains=2000.0,
        tax_paid=3000.0,
    )
    portfolio.update_history_for_period(previous_period)

    # Get the portfolio in the right state
    portfolio.collect_income_per_period(current_period)
    # Add mock data to the portfolio
    portfolio.cash = 100.0
    portfolio.tax_owed = 10.0
    portfolio._register_transaction(
        period=current_period,
        type="sell",
        transaction_amount=500.0,
        long_term_gains=10.0,
        short_term_gains=20.0,
        tax_paid=30.0,
    )
    portfolio._register_transaction(
        period=current_period,
        type="sell",
        transaction_amount=500.0,
        long_term_gains=1.0,
        short_term_gains=2.0,
        tax_paid=3.0,
    )
    portfolio.update_history_for_period(current_period)
    assert portfolio.history.loc[current_period]["cash"] == 100.0
    assert portfolio.history.loc[current_period]["tax_owed"] == 10.0
    assert portfolio.history.loc[current_period]["long_term_gains_in_period"] == 11.0
    assert portfolio.history.loc[current_period]["short_term_gains_in_period"] == 22.0
    assert portfolio.history.loc[current_period]["taxes_paid_in_period"] == 33.0


def test_update_history_transitions_to_done_state(portfolio_with_config):
    portfolio = portfolio_with_config
    current_period = portfolio.history.index[0]

    portfolio.collect_income_per_period(current_period)
    portfolio.update_history_for_period(current_period)
    assert portfolio._states[current_period] == PortfolioState.DONE


def test_update_history_raised_if_not_in_transact_state(portfolio_with_config):
    portfolio = portfolio_with_config
    current_period = portfolio.history.index[0]

    with raises(
        RuntimeError,
        match="wrong state: COLLECT_INCOME. Expected state: TRANSACT",
    ):
        portfolio.update_history_for_period(current_period)

    portfolio._states[current_period] = PortfolioState.DONE
    with raises(
        RuntimeError,
        match="wrong state: DONE. Expected state: TRANSACT",
    ):
        portfolio.update_history_for_period(current_period)


def test_collect_income_per_period(asset_universe_for_income_testing):
    # simple setup: 2 assets, 3 periods
    asset_universe = asset_universe_for_income_testing

    portfolio = Portfolio(asset_universe=asset_universe)
    current_period = portfolio.history.index[0]
    # we are not holding anything yet and expect no income
    portfolio.collect_income_per_period(current_period)
    portfolio.move_cash(current_period, 100)
    portfolio.buy_asset(period=current_period, symbol="A", quantity=10.0)
    portfolio.update_history_for_period(current_period)
    # we are holding one asset and expect no income because we just bought it
    assert portfolio.history.loc[current_period]["long_term_gains_in_period"] == 0.0
    assert portfolio.history.loc[current_period]["short_term_gains_in_period"] == 0.0

    current_period = portfolio.history.index[1]
    # we are holding 10 of `A` and expect 20 short term income
    portfolio.collect_income_per_period(current_period)
    portfolio.sell_asset(period=current_period, symbol="A", quantity=10.0)
    portfolio.update_history_for_period(current_period)
    assert portfolio.history.loc[current_period]["long_term_gains_in_period"] == 0.0
    assert portfolio.history.loc[current_period]["short_term_gains_in_period"] == 20.0
    assert portfolio.cash == 120

    current_period = portfolio.history.index[2]
    # we're back to no holdings. Don't expect any extra income
    portfolio.collect_income_per_period(current_period)
    portfolio.update_history_for_period(current_period)
    assert portfolio.cash == 120


def test_collect_income_per_period_short_long_term(asset_universe_for_income_testing):
    # simple setup: 2 assets, 3 periods
    asset_universe = asset_universe_for_income_testing
    tax_config = TaxConfig(
        long_term_holding_period=pd.DateOffset(days=2),
    )

    portfolio = Portfolio(asset_universe=asset_universe, tax_config=tax_config)
    current_period = portfolio.history.index[0]
    # we are not holding anything yet and expect no income
    portfolio.collect_income_per_period(current_period)
    portfolio.move_cash(current_period, 100)
    portfolio.buy_asset(period=current_period, symbol="A", quantity=10.0)
    portfolio.update_history_for_period(current_period)

    current_period = portfolio.history.index[1]
    # we are holding 10 of `A` and expect 20 short term income
    portfolio.collect_income_per_period(current_period)
    portfolio.update_history_for_period(current_period)
    assert portfolio.history.loc[current_period]["long_term_gains_in_period"] == 0.0
    assert portfolio.history.loc[current_period]["short_term_gains_in_period"] == 20.0
    assert portfolio.cash == 20

    current_period = portfolio.history.index[2]
    # we're now in the long term holding period and expect 30 long term income
    portfolio.collect_income_per_period(current_period)
    portfolio.update_history_for_period(current_period)
    assert portfolio.history.loc[current_period]["long_term_gains_in_period"] == 30.0
    assert portfolio.history.loc[current_period]["short_term_gains_in_period"] == 0.0
    assert portfolio.cash == 50


def test_collect_income_per_period_short_long_term_50tax(
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
    current_period = portfolio.history.index[0]
    # we are not holding anything yet and expect no income
    portfolio.collect_income_per_period(current_period)
    portfolio.move_cash(current_period, 100)
    portfolio.buy_asset(period=current_period, symbol="A", quantity=10.0)
    portfolio.update_history_for_period(current_period)

    current_period = portfolio.history.index[1]
    # we are holding 10 of `A` and expect 20 short term income
    portfolio.collect_income_per_period(current_period)
    portfolio.update_history_for_period(current_period)
    assert portfolio.history.loc[current_period]["short_term_gains_in_period"] == 20.0
    assert portfolio.history.loc[current_period]["taxes_paid_in_period"] == 0
    assert portfolio.cash == 20
    assert portfolio.tax_owed == 10

    current_period = portfolio.history.index[2]
    # we're now in the long term holding period and expect 30 long term income
    portfolio.collect_income_per_period(current_period)
    portfolio.update_history_for_period(current_period)
    assert portfolio.history.loc[current_period]["long_term_gains_in_period"] == 30.0
    assert portfolio.history.loc[current_period]["taxes_paid_in_period"] == 0
    assert portfolio.cash == 50
    assert portfolio.tax_owed == 25


def test_collect_income_per_period_short_long_term_tax_withholding(
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
    current_period = portfolio.history.index[0]
    # we are not holding anything yet and expect no income
    portfolio.collect_income_per_period(current_period)
    portfolio.move_cash(current_period, 100)
    portfolio.buy_asset(period=current_period, symbol="A", quantity=10.0)
    portfolio.update_history_for_period(current_period)

    current_period = portfolio.history.index[1]
    # we are holding 10 of `A` and expect 20 short term income
    portfolio.collect_income_per_period(current_period)
    portfolio.update_history_for_period(current_period)
    assert portfolio.history.loc[current_period]["short_term_gains_in_period"] == 20.0
    assert portfolio.history.loc[current_period]["taxes_paid_in_period"] == 10.0
    assert portfolio.cash == 10.0
    assert portfolio.tax_owed == 0.0

    current_period = portfolio.history.index[2]
    # we're now in the long term holding period and expect 30 long term income
    portfolio.collect_income_per_period(current_period)
    portfolio.update_history_for_period(current_period)
    assert portfolio.history.loc[current_period]["long_term_gains_in_period"] == 30.0
    assert portfolio.history.loc[current_period]["taxes_paid_in_period"] == 15.0
    assert portfolio.cash == 25.0
    assert portfolio.tax_owed == 0.0


def test_collect_income_per_period_states(portfolio_with_config):
    portfolio = portfolio_with_config
    current_period = portfolio.history.index[0]

    portfolio.collect_income_per_period(current_period)
    assert portfolio._states[current_period] == PortfolioState.TRANSACT

    with raises(
        RuntimeError, match="wrong state: TRANSACT. Expected state: COLLECT_INCOME"
    ):
        portfolio.collect_income_per_period(current_period)

    portfolio.update_history_for_period(current_period)
    with raises(
        RuntimeError, match="wrong state: DONE. Expected state: COLLECT_INCOME"
    ):
        portfolio.collect_income_per_period(current_period)


def test_move_cash(portfolio_with_config):
    portfolio = portfolio_with_config
    current_period = portfolio.history.index[0]

    portfolio.collect_income_per_period(current_period)
    portfolio.move_cash(current_period, 100)
    assert portfolio.cash == 100
    portfolio.move_cash(current_period, 50)
    assert portfolio.cash == 150
    portfolio.move_cash(current_period, -50)
    assert portfolio.cash == 100
    portfolio.move_cash(current_period, 0.0)
    assert portfolio.cash == 100


def test_move_cash_states(portfolio_with_config):
    portfolio = portfolio_with_config
    current_period = portfolio.history.index[0]

    with raises(
        RuntimeError, match="wrong state: COLLECT_INCOME. Expected state: TRANSACT"
    ):
        portfolio.move_cash(current_period, 100)

    portfolio.collect_income_per_period(current_period)
    portfolio.move_cash(current_period, 100)
    assert portfolio._states[current_period] == PortfolioState.TRANSACT
    portfolio.update_history_for_period(current_period)

    with raises(RuntimeError, match="wrong state: DONE. Expected state: TRANSACT"):
        portfolio.move_cash(current_period, 100)
