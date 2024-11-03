from datetime import datetime, timedelta

from pytest import approx, raises


def test_tax_config(tax_config):
    assert tax_config.short_term_rate == 0.2
    assert tax_config.long_term_rate == 0.1
    assert tax_config.long_term_holding_period == timedelta(365)
    assert tax_config.withhold_tax is False

    value = 1000.0  # Example capital gain
    puchase_date = datetime(2023, 1, 1)

    # test tax calculation for short-term gains
    sale_date = datetime(2023, 2, 1)
    short_term_tax = tax_config.calculate_tax(puchase_date, sale_date, value)
    assert short_term_tax == approx(value * 0.2)

    # test tax calculation for long-term gains
    sale_date = datetime(2024, 2, 1)
    long_term_tax = tax_config.calculate_tax(puchase_date, sale_date, value)
    assert long_term_tax == approx(value * 0.1)

    # negative tax calculation should raise an error
    with raises(ValueError):
        tax_config.calculate_tax(puchase_date, puchase_date, -1)


def test_long_term_holding_period(tax_config):
    assert tax_config.long_term_holding_period == timedelta(365)

    purchase_date = datetime(2023, 1, 1)
    short_term_date = datetime(2023, 2, 1)
    assert tax_config.is_long_term(purchase_date, short_term_date) is False
    long_term_date = datetime(2024, 1, 1)
    assert tax_config.is_long_term(purchase_date, long_term_date) is True
