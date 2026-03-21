"""Tests for examples/backtest_runner_example.py.

Each test exercises one example function and verifies meaningful financial
behavior — not just structural correctness. Prices are deterministic
(fixed seeds and linear patterns), so outputs are reproducible.
"""

import pandas as pd

from examples.backtest_runner_example import (
    example_compare_strategies,
    example_custom_period_range,
    example_data_loading,
    example_hooks,
    example_logging,
    example_output_modes,
    example_simple,
    example_step_by_step,
    example_tax_loss_harvesting,
    example_taxes_and_fees,
)
from pyfolium import BacktestResult, BacktestRunner


class TestExampleSimple:
    """Example 1: BuyAndHold on STOCK_A with $50k initial cash."""

    def test_returns_successful_result(self, capsys):
        result = example_simple()
        assert isinstance(result, BacktestResult)
        assert result.success is True
        assert result.total_periods == 252

    def test_cash_includes_dividends(self, capsys):
        """With the income_column fix, 4 dividend payments of $100 each
        are collected at periods 60, 120, 180, 240 (period 0 has no
        holdings yet). So cash = 50000 - 10000 + 400 = $40,400.
        """
        result = example_simple()
        assert result.portfolio.cash == 40_400.0

    def test_holdings(self, capsys):
        result = example_simple()
        holdings = result.portfolio.holdings.loc[result.end_period]
        assert holdings["STOCK_A"] == 100.0
        assert holdings["STOCK_B"] == 0.0

    def test_prints_output(self, capsys):
        example_simple()
        captured = capsys.readouterr()
        assert "Backtest completed successfully" in captured.out
        assert "$40,400.00" in captured.out


class TestExampleTaxesAndFees:
    """Example 2: TaxAwareStrategy with TaxConfig and FeeConfig."""

    def test_returns_successful_result(self, capsys):
        result = example_taxes_and_fees()
        assert isinstance(result, BacktestResult)
        assert result.success is True

    def test_fees_were_charged(self, capsys):
        result = example_taxes_and_fees()
        txns = result.portfolio.transactions
        total_fees = txns["fee"].sum()
        assert total_fees > 0

    def test_short_term_gains_realized(self, capsys):
        """Selling after 100 days (< 1 year) should classify as short-term."""
        result = example_taxes_and_fees()
        txns = result.portfolio.transactions
        sells = txns[txns["type"] == "sell"]
        assert not sells.empty
        assert sells["short_term_gains"].sum() > 0
        assert sells["long_term_gains"].sum() == 0

    def test_tax_was_withheld(self, capsys):
        """With withhold_tax=True, tax is deducted from cash at sale time."""
        result = example_taxes_and_fees()
        txns = result.portfolio.transactions
        sells = txns[txns["type"] == "sell"]
        assert sells["tax_paid"].sum() > 0
        # Tax owed should be 0 since withholding covers it
        assert result.portfolio.tax_owed == 0.0


class TestExampleTaxLossHarvesting:
    """Example 3: TaxLossHarvestingStrategy using sell_lot()."""

    def test_returns_successful_result(self, capsys):
        result = example_tax_loss_harvesting()
        assert isinstance(result, BacktestResult)
        assert result.success is True

    def test_harvested_the_more_expensive_lot(self, capsys):
        """The strategy should sell the lot bought at ~$122 (period 30),
        not the lot bought at $100 (period 0). Only the cheaper lot remains.
        """
        result = example_tax_loss_harvesting()
        open_lots = result.portfolio.open_lots.get("FUND", [])
        assert len(open_lots) == 1
        remaining_lot = open_lots[0]
        # The remaining lot should be the one bought at period 0 ($100)
        assert remaining_lot.period == pd.Period("2023-01-01", "D")
        assert remaining_lot.cost_basis_per_share == 100.0
        assert remaining_lot.quantity_remaining == 50

    def test_realized_loss(self, capsys):
        """Selling the expensive lot at a lower price should create a loss."""
        result = example_tax_loss_harvesting()
        txns = result.portfolio.transactions
        sells = txns[txns["type"] == "sell"]
        assert not sells.empty
        total_gains = sells["short_term_gains"].sum() + sells["long_term_gains"].sum()
        assert total_gains < 0  # Loss

    def test_strategy_logged_harvest(self, capsys):
        """The strategy emits an INFO log entry when harvesting."""
        result = example_tax_loss_harvesting()
        strategy_info = [
            e
            for e in result.log
            if e.source == "strategy" and e.message == "Harvesting tax loss"
        ]
        assert len(strategy_info) == 1
        assert "cost_basis" in strategy_info[0].data


class TestExampleDataLoading:
    """Example 4: load_from_dataframe() workflow."""

    def test_returns_successful_result(self, capsys):
        result = example_data_loading()
        assert isinstance(result, BacktestResult)
        assert result.success is True
        assert result.total_periods == 252

    def test_data_loaded_correctly(self, capsys):
        """The loaded data should produce a working backtest with positive value."""
        result = example_data_loading()
        assert result.portfolio.total_value > 0

    def test_prints_data_info(self, capsys):
        example_data_loading()
        captured = capsys.readouterr()
        assert "252 periods" in captured.out
        assert "PeriodIndex" in captured.out
        assert "price" in captured.out


class TestExampleOutputModes:
    """Example 5: MonthlyRebalanceStrategy with OutputMode.SUMMARY."""

    def test_returns_successful_result(self, capsys):
        result = example_output_modes()
        assert isinstance(result, BacktestResult)
        assert result.success is True
        assert result.total_periods == 252

    def test_rebalancing_produced_trades(self, capsys):
        """MonthlyRebalance should trade every 20 periods = ~12 rebalances."""
        result = example_output_modes()
        trades = result.strategy.trades_df
        assert len(trades) > 10

    def test_portfolio_grew(self, capsys):
        """With STOCK_A growing linearly, total value should exceed initial $100k."""
        result = example_output_modes()
        assert result.portfolio.total_value > 100_000


class TestExampleHooks:
    """Example 6: Hooks for observability."""

    def test_returns_successful_result(self, capsys):
        result = example_hooks()
        assert isinstance(result, BacktestResult)
        assert result.success is True
        assert result.total_periods == 252

    def test_hooks_produced_output(self, capsys):
        example_hooks()
        captured = capsys.readouterr()
        assert "Period 0:" in captured.out
        assert "Period 50:" in captured.out
        assert "Backtest complete" in captured.out

    def test_single_trade_executed(self, capsys):
        """BuyAndHold buys once."""
        result = example_hooks()
        assert len(result.strategy.trades_df) == 1


class TestExampleStepByStep:
    """Example 7: Manual run_period() debugging."""

    def test_returns_runner(self, capsys):
        runner = example_step_by_step()
        assert isinstance(runner, BacktestRunner)

    def test_ran_10_periods(self, capsys):
        runner = example_step_by_step()
        assert runner._periods_completed == 10

    def test_portfolio_state_after_10_periods(self, capsys):
        """BuyAndHold buys 100 STOCK_A at $100 on period 0.
        After 10 periods, cash = $40,000 (no dividends in first 10 periods).
        """
        runner = example_step_by_step()
        assert runner.portfolio.cash == 40_000.0
        holdings = runner.portfolio.holdings.iloc[runner._periods_completed - 1]
        assert holdings["STOCK_A"] == 100.0

    def test_prints_step_details(self, capsys):
        example_step_by_step()
        captured = capsys.readouterr()
        assert "STOCK_A=100" in captured.out
        assert "Period 1:" in captured.out
        assert "Period 10:" in captured.out


class TestExampleCompareStrategies:
    """Example 8: Portfolio.clone() for strategy comparison."""

    def test_returns_three_results(self, capsys):
        results = example_compare_strategies()
        assert isinstance(results, dict)
        assert len(results) == 3
        for result in results.values():
            assert isinstance(result, BacktestResult)
            assert result.success is True

    def test_stock_a_outperforms_stock_b(self, capsys):
        """STOCK_A grows linearly (100→225.50), STOCK_B is volatile around $50.
        STOCK_A should produce higher total value.
        """
        results = example_compare_strategies()
        assert (
            results["stock_a_only"].portfolio.total_value
            > results["stock_b_only"].portfolio.total_value
        )

    def test_all_positive_value(self, capsys):
        results = example_compare_strategies()
        for result in results.values():
            assert result.portfolio.total_value > 0

    def test_base_portfolio_independence(self, capsys):
        """Verify the example prints that base portfolio is unchanged."""
        example_compare_strategies()
        captured = capsys.readouterr()
        assert "Base portfolio cash (should be 0): $0.00" in captured.out


class TestExampleCustomPeriodRange:
    """Example 9: start_period on strategy, end_period on runner."""

    def test_returns_successful_result(self, capsys):
        result = example_custom_period_range()
        assert isinstance(result, BacktestResult)
        assert result.success is True

    def test_period_range(self, capsys):
        result = example_custom_period_range()
        assert result.total_periods == 100
        assert result.start_period == pd.Period("2023-01-02", "D")
        assert result.end_period == pd.Period("2023-04-11", "D")


class TestExampleLogging:
    """Example 10: Structured logging from strategies."""

    def test_returns_successful_result(self, capsys):
        result = example_logging()
        assert isinstance(result, BacktestResult)
        assert result.success is True

    def test_log_entry_count(self, capsys):
        """252 periods: 1 INFO (buy) + 251 DEBUG (hold)."""
        result = example_logging()
        strategy_entries = [e for e in result.log if e.source == "strategy"]
        assert len(strategy_entries) == 252

    def test_first_entry_is_investment(self, capsys):
        result = example_logging()
        strategy_entries = [e for e in result.log if e.source == "strategy"]
        first = strategy_entries[0]
        assert first.severity.name == "INFO"
        assert first.message == "Investing initial capital"
        assert first.data["cash"] == 50000.0
        assert first.data["price"] == 100.0

    def test_subsequent_entries_are_debug_with_data(self, capsys):
        result = example_logging()
        strategy_entries = [e for e in result.log if e.source == "strategy"]
        for entry in strategy_entries[1:]:
            assert entry.severity.name == "DEBUG"
            assert entry.data is not None
            assert "price" in entry.data
            assert "unrealized_value" in entry.data

    def test_log_df_filtering(self, capsys):
        """log_df stores severity as string names (INFO, DEBUG, etc.)."""
        result = example_logging()
        df = result.log_df
        assert len(df[df["severity"] == "INFO"]) == 1
        assert len(df[df["severity"] == "DEBUG"]) == 251
