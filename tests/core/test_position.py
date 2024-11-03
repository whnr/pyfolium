from datetime import datetime

from hhfk.core import Position


def test_position_fifo_ordering(portfolio_with_config, sample_asset):
    """Test FIFO (First-In-First-Out) ordering of tax lots"""
    position = Position(sample_asset.symbol)

    # Add multiple tax lots
    position.add_tax_lot(datetime(2024, 1, 1), 50, 10.0, 9.95)
    position.add_tax_lot(datetime(2024, 1, 2), 50, 11.0, 9.95)

    # Sell partial position
    proceeds, long_term_gain, short_term_gain = position.sell_shares(
        datetime(2024, 2, 1), 60, 12.0, 9.95, portfolio_with_config.tax_config
    )

    # Check that first lot was fully sold and second lot was partially sold
    assert len(position.tax_lots) == 1
    assert position.tax_lots[0].quantity == 40
    assert position.tax_lots[0].price == 11.0  # confirm it's the second lot
