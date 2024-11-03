from datetime import datetime, timedelta

from pytest import approx

from hhfk.core import Position, TaxLot


def test_tax_lot_creation():
    """Test basic tax lot creation and properties"""
    lot = TaxLot(
        purchase_date=datetime(2023, 1, 1), quantity=100, price=10.0, fees=9.95
    )
    assert lot.quantity == 100
    assert lot.price == approx(10.0)
    assert lot.fees == approx(9.95)
    cost_basis_per_share = (100 * 10.0 + 9.95) / 100
    assert lot.cost_basis_per_share == approx(cost_basis_per_share)


def test_holding_period_calculation(portfolio_with_config, sample_asset):
    """Test correct determination of holding period"""
    # Create position with tax lots
    position = Position(sample_asset.symbol)

    # Add a tax lot from more than a year ago
    old_date = datetime(2023, 1, 1)
    position.add_tax_lot(old_date, 100, 10.0, 9.95)

    # Add a recent tax lot
    recent_date = datetime(2024, 1, 1)
    position.add_tax_lot(recent_date, 100, 11.0, 9.95)

    # Test holding period determination
    sale_date = datetime(2024, 2, 1)
    period_old = position._get_holding_period(old_date, sale_date)
    period_recent = position._get_holding_period(recent_date, sale_date)

    long_term_period = portfolio_with_config.tax_config.long_term_holding_period

    assert period_old > long_term_period
    assert period_recent < long_term_period
