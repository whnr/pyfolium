import pandas as pd


def test_tax_config(tax_config):
    assert tax_config.short_term_rate == 0.2
    assert tax_config.long_term_rate == 0.1
    assert tax_config.long_term_holding_period == pd.DateOffset(years=1)
    assert tax_config.withhold_tax is False
    assert tax_config.tax_strategy == "FIFO"
