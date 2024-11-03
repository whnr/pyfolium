from datetime import datetime

from pytest import approx

from hhfk.core import Transaction


def test_short_term_gains(portfolio_with_config, sample_asset):
    """Test short-term capital gains calculations"""
    # Buy shares
    buy_transaction = Transaction(
        timestamp=datetime(2024, 1, 1),
        asset_symbol=sample_asset.symbol,
        quantity=100,
        price=10.0,
        fees=9.95,
    )
    portfolio_with_config.add_transaction(buy_transaction)

    # Sell shares for profit after short period
    sell_transaction = Transaction(
        timestamp=datetime(2024, 2, 1),
        asset_symbol=sample_asset.symbol,
        quantity=-100,
        price=15.0,
        fees=9.95,
    )
    portfolio_with_config.add_transaction(sell_transaction)

    # Check tax calculations
    year_summary = portfolio_with_config.get_annual_summary(2024)
    expected_gain = (15.0 * 100) - (10.0 * 100) - 19.90  # Gain minus total fees
    assert year_summary["short_term_gains"] == approx(expected_gain)
    assert year_summary["total_tax_liability"] == approx(
        expected_gain * portfolio_with_config.tax_config.short_term_rate
    )


def test_long_term_gains(portfolio_with_config, sample_asset):
    """Test long-term capital gains calculations"""
    # Buy shares
    buy_transaction = Transaction(
        timestamp=datetime(2023, 1, 1),
        asset_symbol=sample_asset.symbol,
        quantity=100,
        price=10.0,
        fees=9.95,
    )
    portfolio_with_config.add_transaction(buy_transaction)

    # Sell shares for profit after long period
    sell_transaction = Transaction(
        timestamp=datetime(2024, 2, 1),
        asset_symbol=sample_asset.symbol,
        quantity=-100,
        price=15.0,
        fees=9.95,
    )
    portfolio_with_config.add_transaction(sell_transaction)

    # Check tax calculations
    year_summary = portfolio_with_config.get_annual_summary(2024)
    expected_gain = (15.0 * 100) - (10.0 * 100) - 19.90  # Gain minus total fees
    assert year_summary["long_term_gains"] == approx(expected_gain)
    assert year_summary["total_tax_liability"] == approx(
        expected_gain * portfolio_with_config.tax_config.long_term_rate
    )


def test_mixed_term_gains(portfolio_with_config, sample_asset):
    """Test mixed tax lot gains calculations

    Addind two lots over time and selling them partially.
    Fully sell the long-term lot.
    Partially sell the short-term lot.
    """
    # Buy shares first
    buy_transaction = Transaction(
        timestamp=datetime(2023, 1, 1),
        asset_symbol=sample_asset.symbol,
        quantity=100,
        price=10.0,
        fees=9.95,
    )
    portfolio_with_config.add_transaction(buy_transaction)

    buy_transaction = Transaction(
        timestamp=datetime(2024, 1, 1),
        asset_symbol=sample_asset.symbol,
        quantity=100,
        price=10.0,
        fees=9.95,
    )
    portfolio_with_config.add_transaction(buy_transaction)

    # Sell partial holdings after a mixed period. Assuming FIFO
    sell_transaction = Transaction(
        timestamp=datetime(2024, 2, 1),
        asset_symbol=sample_asset.symbol,
        quantity=-150,
        price=15.0,
        fees=9.95,
    )
    portfolio_with_config.add_transaction(sell_transaction)

    # Calculate the expected values for long and short term gains
    proceeds_per_share_after_fees = (150 * 15.0 - 9.95) / 150
    long_term_gain = proceeds_per_share_after_fees * 100 - (100 * 10.0 + 9.95)
    short_term_gain = (
        proceeds_per_share_after_fees * 50 - (100 * 10.0 + 9.95) / 100 * 50
    )

    # Check tax calculations
    year_summary = portfolio_with_config.get_annual_summary(2024)
    assert year_summary["long_term_gains"] == approx(long_term_gain)
    assert year_summary["short_term_gains"] == approx(short_term_gain)
    assert year_summary["total_tax_liability"] == approx(
        long_term_gain * portfolio_with_config.tax_config.long_term_rate
        + short_term_gain * portfolio_with_config.tax_config.short_term_rate
    )


def test_short_term_dividend_taxes(portfolio_with_config, sample_asset):
    """Test short-term dividend tax calculations"""
    # Buy shares first
    buy_transaction = Transaction(
        timestamp=datetime(2024, 1, 1),
        asset_symbol=sample_asset.symbol,
        quantity=100,
        price=10.0,
        fees=9.95,
    )
    portfolio_with_config.add_transaction(buy_transaction)

    # Record dividend
    dividend_amount_per_share = 0.3
    dividend_amount = dividend_amount_per_share * 100  # multiply by quantity
    portfolio_with_config.record_dividend(
        timestamp=datetime(2024, 3, 1),
        asset_symbol=sample_asset.symbol,
        amount_per_share=dividend_amount_per_share,
    )

    # Check tax calculations
    year_summary = portfolio_with_config.get_annual_summary(2024)
    assert year_summary["short_term_dividends"] == approx(dividend_amount)
    assert year_summary["total_tax_liability"] == approx(
        dividend_amount * portfolio_with_config.tax_config.short_term_rate
    )


def test_long_term_dividend_taxes(portfolio_with_config, sample_asset):
    """Test long-term dividend tax calculations"""
    # Buy shares first
    buy_transaction = Transaction(
        timestamp=datetime(2023, 1, 1),
        asset_symbol=sample_asset.symbol,
        quantity=100,
        price=10.0,
        fees=9.95,
    )
    portfolio_with_config.add_transaction(buy_transaction)

    # Record dividend
    dividend_amount_per_share = 0.3
    dividend_amount = dividend_amount_per_share * 100  # multiply by quantity
    portfolio_with_config.record_dividend(
        timestamp=datetime(2024, 3, 1),
        asset_symbol=sample_asset.symbol,
        amount_per_share=dividend_amount_per_share,
    )

    # Check tax calculations
    year_summary = portfolio_with_config.get_annual_summary(2024)
    assert year_summary["long_term_dividends"] == approx(dividend_amount)
    assert year_summary["total_tax_liability"] == approx(
        dividend_amount * portfolio_with_config.tax_config.long_term_rate
    )


def test_mixed_term_dividend_taxes(portfolio_with_config, sample_asset):
    """Test mixed tax lot dividend tax calculations"""
    # Buy shares first
    buy_transaction = Transaction(
        timestamp=datetime(2023, 1, 1),
        asset_symbol=sample_asset.symbol,
        quantity=100,
        price=10.0,
        fees=9.95,
    )
    portfolio_with_config.add_transaction(buy_transaction)

    buy_transaction = Transaction(
        timestamp=datetime(2024, 1, 1),
        asset_symbol=sample_asset.symbol,
        quantity=100,
        price=15.0,
        fees=9.95,
    )
    portfolio_with_config.add_transaction(buy_transaction)

    # Record dividend per share. Now that we have two lots.
    dividend_amount_per_share = 0.3
    long_term_dividend_amount = dividend_amount_per_share * 100
    short_term_dividend_amount = dividend_amount_per_share * 100
    portfolio_with_config.record_dividend(
        timestamp=datetime(2024, 3, 1),
        asset_symbol=sample_asset.symbol,
        amount_per_share=dividend_amount_per_share,
    )

    # Check tax calculations
    year_summary = portfolio_with_config.get_annual_summary(2024)
    assert year_summary["short_term_dividends"] == approx(short_term_dividend_amount)
    assert year_summary["long_term_dividends"] == approx(long_term_dividend_amount)
    assert year_summary["total_tax_liability"] == approx(
        short_term_dividend_amount * portfolio_with_config.tax_config.short_term_rate
        + long_term_dividend_amount * portfolio_with_config.tax_config.short_term_rate
    )
