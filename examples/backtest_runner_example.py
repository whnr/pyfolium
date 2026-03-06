"""Example usage of BacktestRunner for running portfolio backtests.

This example demonstrates both simple and advanced usage patterns of the
BacktestRunner class for automating portfolio simulations.
"""

import numpy as np
import pandas as pd

from pyfolium import (
    Asset,
    AssetUniverse,
    BacktestRunner,
    BaseStrategy,
    OutputMode,
    Portfolio,
    Severity,
)


# =============================================================================
# Setup: Create sample data and universe
# =============================================================================


def create_sample_universe():
    """Create a sample asset universe with two stocks."""
    universe = AssetUniverse(data_frequency="D")

    # Create 252 trading days (1 year)
    dates = pd.period_range(start="2023-01-01", periods=252, freq="D")

    # Stock A: Growing stock with dividends
    stock_a_data = pd.DataFrame(
        {
            "price": pd.Series([100 + i * 0.5 for i in range(252)], index=dates),
            "income": pd.Series(
                [1.0 if i % 60 == 0 else 0.0 for i in range(252)], index=dates
            ),
        }
    )
    Asset("STOCK_A", universe, stock_a_data)

    # Stock B: Volatile stock, no dividends

    np.random.seed(42)
    cumulative_returns = np.cumsum(np.random.randn(252) * 0.02)
    stock_b_prices = 50 * (1 + cumulative_returns)
    stock_b_data = pd.DataFrame(
        {
            "price": pd.Series(stock_b_prices, index=dates),
            "income": 0.0,
        }
    )
    Asset("STOCK_B", universe, stock_b_data)

    return universe


# =============================================================================
# Example Strategies
# =============================================================================


class BuyAndHoldStrategy(BaseStrategy):
    """Simple buy-and-hold strategy that invests on day 1."""

    def __init__(self, portfolio, symbol="STOCK_A", quantity=100, **kwargs):
        super().__init__(
            portfolio, parameters={"symbol": symbol, "quantity": quantity}, **kwargs
        )
        self.symbol = symbol
        self.quantity = quantity
        self.invested = False

    def get_trades(self):
        if not self.invested and self.portfolio.cash >= 10000:
            self.invested = True
            return [(self.symbol, self.quantity)]
        return []


class MonthlyRebalanceStrategy(BaseStrategy):
    """Rebalance to target allocations every 20 trading days."""

    def __init__(self, portfolio, target_allocations=None, **kwargs):
        target_allocations = target_allocations or {"STOCK_A": 0.5, "STOCK_B": 0.5}
        super().__init__(
            portfolio, parameters={"target_allocations": target_allocations}, **kwargs
        )
        self.target_allocations = target_allocations
        self.days_since_rebalance = 0
        self.rebalance_frequency = 20

    def get_trades(self):
        self.days_since_rebalance += 1

        if self.days_since_rebalance < self.rebalance_frequency:
            return []

        self.days_since_rebalance = 0

        portfolio_value = self.portfolio.total_value
        holdings = self.portfolio.holdings.loc[self.portfolio.current_period]
        prices = self.asset_universe.price_matrix.loc[self.portfolio.current_period]

        # Calculate target shares for each asset
        trades = []
        for symbol, target_pct in self.target_allocations.items():
            target_value = portfolio_value * target_pct
            current_shares = holdings[symbol]
            target_shares = target_value / prices[symbol]
            share_diff = target_shares - current_shares

            if abs(share_diff) > 0.1:  # Only trade if difference is significant
                trades.append((symbol, share_diff))

        return trades


# =============================================================================
# Example 1: Simple Usage
# =============================================================================


def example_simple():
    """Simplest possible backtest - just run it!"""
    print("=" * 70)
    print("Example 1: Simple Usage")
    print("=" * 70)

    # Setup
    universe = create_sample_universe()
    portfolio = Portfolio(universe)

    strategy = BuyAndHoldStrategy(
        portfolio, symbol="STOCK_A", quantity=100, initial_cash=50000
    )

    # Run backtest - that's it!
    runner = BacktestRunner(portfolio, strategy)
    result = runner.run()

    # Display results
    print("\nBacktest completed successfully!")
    periods = result.total_periods
    exec_time = result.execution_time
    print(f"Simulated {periods} periods in {exec_time:.2f} seconds")
    print(f"Final cash: ${result.portfolio.cash:,.2f}")
    print(
        f"Final holdings: {result.portfolio.holdings.loc[result.end_period].to_dict()}"
    )
    print(f"Errors: {len(result.errors)}")


# =============================================================================
# Example 2: With Progress Bar
# =============================================================================


def example_with_progress():
    """Run backtest with different output modes."""
    print("\n" + "=" * 70)
    print("Example 2: Output Modes")
    print("=" * 70)

    universe = create_sample_universe()
    portfolio = Portfolio(universe)

    strategy = MonthlyRebalanceStrategy(portfolio, initial_cash=100000)

    runner = BacktestRunner(portfolio, strategy)
    # OutputMode.PROGRESS shows a tqdm bar + summary line
    result = runner.run(output=OutputMode.PROGRESS)

    print(f"\nFinal portfolio value: ${result.portfolio.total_value:,.2f}")

    # Other modes:
    # runner.run(output=OutputMode.SILENT)   — no terminal output (default)
    # runner.run(output=OutputMode.SUMMARY)  — one-line summary at end


# =============================================================================
# Example 3: Custom Hooks for Logging
# =============================================================================


def example_with_hooks():
    """Use hooks to log portfolio state during simulation."""
    print("\n" + "=" * 70)
    print("Example 3: Custom Hooks for Logging")
    print("=" * 70)

    universe = create_sample_universe()
    portfolio = Portfolio(universe)

    strategy = BuyAndHoldStrategy(
        portfolio, symbol="STOCK_B", quantity=200, initial_cash=50000
    )

    # Define custom hooks
    def log_period_start(runner):
        """Log at the start of each period."""
        if runner._periods_completed % 50 == 0:  # Log every 50 periods
            period_num = runner._periods_completed
            portfolio_value = runner.portfolio.total_value
            print(f"Period {period_num}: Portfolio value = ${portfolio_value:,.2f}")

    def log_backtest_end(runner):
        """Log summary at the end."""
        print("\n✓ Backtest complete!")
        print(f"  Total trades executed: {len(runner.strategy.trades_df)}")

    # Register hooks
    runner = BacktestRunner(portfolio, strategy)
    runner.register_hook("period_start", log_period_start)
    runner.register_hook("backtest_end", log_backtest_end)

    # Run with hooks
    runner.run()


# =============================================================================
# Example 4: Step-by-Step Execution
# =============================================================================


def example_step_by_step():
    """Execute backtest step-by-step for debugging."""
    print("\n" + "=" * 70)
    print("Example 4: Step-by-Step Execution")
    print("=" * 70)

    universe = create_sample_universe()
    portfolio = Portfolio(universe)

    strategy = BuyAndHoldStrategy(portfolio, initial_cash=50000)

    runner = BacktestRunner(portfolio, strategy)

    # Run first 10 periods manually
    print("\nRunning first 10 periods manually:")
    for i in range(10):
        runner.run_period()
        print(f"  Period {i + 1}: Cash = ${runner.portfolio.cash:,.2f}")

        # Could add custom logic here, e.g., stop on condition
        if runner.portfolio.cash < 0:
            print("  WARNING: Negative cash detected!")
            break


# =============================================================================
# Example 5: Comparing Multiple Strategies
# =============================================================================


def example_compare_strategies():
    """Compare performance of different strategies using clone()."""
    print("\n" + "=" * 70)
    print("Example 5: Comparing Multiple Strategies")
    print("=" * 70)

    universe = create_sample_universe()

    base_portfolio = Portfolio(universe)

    # Each strategy declares its own initial capital and gets an independent clone
    portfolio1 = base_portfolio.clone()
    strategy1 = BuyAndHoldStrategy(
        portfolio1, symbol="STOCK_A", quantity=200, initial_cash=100000
    )
    result1 = BacktestRunner(portfolio1, strategy1).run()

    portfolio2 = base_portfolio.clone()
    strategy2 = BuyAndHoldStrategy(
        portfolio2, symbol="STOCK_B", quantity=400, initial_cash=100000
    )
    result2 = BacktestRunner(portfolio2, strategy2).run()

    portfolio3 = base_portfolio.clone()
    strategy3 = MonthlyRebalanceStrategy(portfolio3, initial_cash=100000)
    result3 = BacktestRunner(portfolio3, strategy3).run()

    v1 = result1.portfolio.total_value
    v2 = result2.portfolio.total_value
    v3 = result3.portfolio.total_value
    print("\nStrategy Comparison:")
    print(f"  Strategy 1 (STOCK_A only): Total value = ${v1:,.2f}")
    print(f"  Strategy 2 (STOCK_B only): Total value = ${v2:,.2f}")
    print(f"  Strategy 3 (Rebalancing):  Total value = ${v3:,.2f}")


# =============================================================================
# Example 6: Custom Period Range
# =============================================================================


def example_custom_period_range():
    """Run backtest over a specific period range."""
    print("\n" + "=" * 70)
    print("Example 6: Custom Period Range")
    print("=" * 70)

    universe = create_sample_universe()
    portfolio = Portfolio(universe)

    # Strategy declares start period (e.g. after warmup window) and initial cash
    periods = universe.get_period_index_range()
    strategy = BuyAndHoldStrategy(
        portfolio, initial_cash=50000, start_period=periods[1]
    )

    # Runner only needs end_period; start_period comes from the strategy
    runner = BacktestRunner(
        portfolio,
        strategy,
        end_period=periods[100],  # End at 100th period
    )
    result = runner.run()

    print(f"\nRan backtest from {result.start_period} to {result.end_period}")
    print(f"Total periods simulated: {result.total_periods}")


# =============================================================================
# Example 7: Strategy Logging & Result Inspection
# =============================================================================


class LoggingStrategy(BaseStrategy):
    """Strategy that emits log entries for observability."""

    def __init__(self, portfolio, **kwargs):
        super().__init__(portfolio, parameters={}, **kwargs)
        self.invested = False

    def get_trades(self):
        if not self.invested and self.portfolio.cash >= 10000:
            self.invested = True
            self.log(
                Severity.INFO,
                "Investing initial capital",
                data={"cash": self.portfolio.cash},
            )
            return [("STOCK_A", 50)]

        if self.invested:
            self.log(Severity.DEBUG, "Holding position")

        return []


def example_logging():
    """Demonstrate structured logging from strategies and result inspection."""
    print("\n" + "=" * 70)
    print("Example 7: Strategy Logging & Result Inspection")
    print("=" * 70)

    universe = create_sample_universe()
    portfolio = Portfolio(universe)

    strategy = LoggingStrategy(portfolio, initial_cash=50000)
    runner = BacktestRunner(portfolio, strategy)
    result = runner.run(output=OutputMode.SUMMARY)

    # Inspect the log
    print(f"\nTotal log entries: {len(result.log)}")
    print(f"  Errors:   {len(result.errors)}")
    print(f"  Warnings: {len(result.warnings)}")
    print(f"  Success:  {result.success}")

    # Show first few strategy entries
    strategy_entries = [e for e in result.log if e.source == "strategy"]
    print(f"\nStrategy log entries: {len(strategy_entries)}")
    for entry in strategy_entries[:3]:
        print(f"  [{entry.severity.name}] {entry.period}: {entry.message}")

    # DataFrame view for analysis
    df = result.log_df
    if not df.empty:
        print(f"\nlog_df shape: {df.shape}")
        print(f"Columns: {list(df.columns)}")


# =============================================================================
# Run all examples
# =============================================================================

if __name__ == "__main__":
    example_simple()
    example_with_progress()
    example_with_hooks()
    example_step_by_step()
    example_compare_strategies()
    example_custom_period_range()
    example_logging()

    print("\n" + "=" * 70)
    print("All examples completed!")
    print("=" * 70)
