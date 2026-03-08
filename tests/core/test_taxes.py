import pandas as pd
import pytest

from pyfolium.core import TaxConfig, TaxLot, TaxResult


class TestTaxResult:
    def test_construction(self):
        result = TaxResult(tax_liability=100.0, tax_paid=50.0)
        assert result.tax_liability == 100.0
        assert result.tax_paid == 50.0

    def test_frozen(self):
        result = TaxResult(tax_liability=100.0, tax_paid=0.0)
        with pytest.raises(AttributeError):
            result.tax_liability = 200.0  # type: ignore[misc]

    def test_slots(self):
        assert hasattr(TaxResult, "__slots__")


class TestLongTermCutoffPeriod:
    def test_daily_frequency_default_offset(self):
        config = TaxConfig()
        current = pd.Period("2024-06-15", freq="D")
        cutoff = config.long_term_cutoff_period(current, "D")
        expected = pd.Period("2023-06-15", freq="D")
        assert cutoff == expected

    def test_monthly_frequency(self):
        config = TaxConfig()
        current = pd.Period("2024-06", freq="M")
        cutoff = config.long_term_cutoff_period(current, "M")
        expected = pd.Period("2023-06", freq="M")
        assert cutoff == expected

    def test_custom_offset(self):
        config = TaxConfig(long_term_holding_period=pd.DateOffset(days=30))
        current = pd.Period("2024-03-15", freq="D")
        cutoff = config.long_term_cutoff_period(current, "D")
        expected = pd.Period("2024-02-14", freq="D")
        assert cutoff == expected


class TestClassifyGain:
    def test_short_term(self):
        config = TaxConfig()
        purchase = pd.Period("2024-01-01", freq="D")
        sale = pd.Period("2024-06-01", freq="D")
        assert config.classify_gain(purchase, sale, "D") == "short_term"

    def test_long_term(self):
        config = TaxConfig()
        purchase = pd.Period("2023-01-01", freq="D")
        sale = pd.Period("2024-06-01", freq="D")
        assert config.classify_gain(purchase, sale, "D") == "long_term"

    def test_boundary_exactly_on_cutoff(self):
        config = TaxConfig(long_term_holding_period=pd.DateOffset(days=2))
        purchase = pd.Period("2024-01-01", freq="D")
        sale = pd.Period("2024-01-03", freq="D")
        # cutoff = 2024-01-01, purchase <= cutoff → long_term
        assert config.classify_gain(purchase, sale, "D") == "long_term"

    def test_one_day_before_cutoff(self):
        config = TaxConfig(long_term_holding_period=pd.DateOffset(days=2))
        purchase = pd.Period("2024-01-02", freq="D")
        sale = pd.Period("2024-01-03", freq="D")
        assert config.classify_gain(purchase, sale, "D") == "short_term"


class TestCalculateTax:
    def test_zero_gains(self):
        config = TaxConfig(short_term_rate=0.3, long_term_rate=0.15)
        result = config.calculate_tax(0.0, 0.0)
        assert result.tax_liability == 0.0
        assert result.tax_paid == 0.0

    def test_short_term_only(self):
        config = TaxConfig(short_term_rate=0.3, long_term_rate=0.15)
        result = config.calculate_tax(1000.0, 0.0)
        assert result.tax_liability == 300.0
        assert result.tax_paid == 0.0

    def test_long_term_only(self):
        config = TaxConfig(short_term_rate=0.3, long_term_rate=0.15)
        result = config.calculate_tax(0.0, 1000.0)
        assert result.tax_liability == 150.0
        assert result.tax_paid == 0.0

    def test_mixed_gains(self):
        config = TaxConfig(short_term_rate=0.3, long_term_rate=0.15)
        result = config.calculate_tax(500.0, 500.0)
        assert result.tax_liability == pytest.approx(225.0)
        assert result.tax_paid == 0.0

    def test_negative_gains_pass_through(self):
        config = TaxConfig(short_term_rate=0.3, long_term_rate=0.15)
        result = config.calculate_tax(-1000.0, 0.0)
        assert result.tax_liability == -300.0
        assert result.tax_paid == 0.0

    def test_withholding_positive_gains(self):
        config = TaxConfig(short_term_rate=0.3, long_term_rate=0.15, withhold_tax=True)
        result = config.calculate_tax(1000.0, 0.0)
        assert result.tax_liability == 0.0
        assert result.tax_paid == 300.0

    def test_withholding_negative_gains_no_tax_paid(self):
        config = TaxConfig(short_term_rate=0.3, long_term_rate=0.15, withhold_tax=True)
        result = config.calculate_tax(-1000.0, 0.0)
        assert result.tax_liability == -300.0
        assert result.tax_paid == 0.0

    def test_zero_rates(self):
        config = TaxConfig(short_term_rate=0.0, long_term_rate=0.0)
        result = config.calculate_tax(1000.0, 1000.0)
        assert result.tax_liability == 0.0
        assert result.tax_paid == 0.0


class TestSelectLots:
    @pytest.fixture
    def lots(self):
        return [
            TaxLot(
                symbol="S",
                period=pd.Period("2024-01-01", freq="D"),
                quantity=10.0,
                quantity_remaining=10.0,
                cost_basis_per_share=100.0,
                txn_index=0,
            ),
            TaxLot(
                symbol="S",
                period=pd.Period("2024-03-01", freq="D"),
                quantity=20.0,
                quantity_remaining=20.0,
                cost_basis_per_share=110.0,
                txn_index=1,
            ),
            TaxLot(
                symbol="S",
                period=pd.Period("2024-02-01", freq="D"),
                quantity=15.0,
                quantity_remaining=15.0,
                cost_basis_per_share=105.0,
                txn_index=2,
            ),
        ]

    def test_fifo_ordering(self, lots):
        config = TaxConfig(tax_strategy="FIFO")
        result = config.select_lots(lots)
        periods = [lot.period for lot in result]
        assert periods == sorted(periods)

    def test_lifo_ordering(self, lots):
        config = TaxConfig(tax_strategy="LIFO")
        result = config.select_lots(lots)
        periods = [lot.period for lot in result]
        assert periods == sorted(periods, reverse=True)

    def test_filters_closed_lots(self, lots):
        lots[1].quantity_remaining = 0.0
        config = TaxConfig(tax_strategy="FIFO")
        result = config.select_lots(lots)
        assert len(result) == 2
        assert all(lot.is_open for lot in result)

    def test_returns_new_list(self, lots):
        config = TaxConfig(tax_strategy="FIFO")
        result = config.select_lots(lots)
        assert result is not lots

    def test_empty_list(self):
        config = TaxConfig(tax_strategy="FIFO")
        result = config.select_lots([])
        assert result == []


def test_tax_config(tax_config):
    assert tax_config.short_term_rate == 0.2
    assert tax_config.long_term_rate == 0.1
    assert tax_config.long_term_holding_period == pd.DateOffset(years=1)
    assert tax_config.withhold_tax is False
    assert tax_config.tax_strategy == "FIFO"
    assert tax_config.allow_specific_lot is True
