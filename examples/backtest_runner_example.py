"""Example usage of BacktestRunner for running portfolio backtests.

This example demonstrates both simple and advanced usage patterns of the
BacktestRunner class for automating portfolio simulations.
"""

import pandas as pd

from pyfolium import Asset, AssetUniverse, BacktestRunner, BaseStrategy, Portfolio


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
    import numpy as np

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

    def __init__(self, portfolio, symbol="STOCK_A", quantity=100):
        super().__init__(portfolio, parameters={"symbol": symbol, "quantity": quantity})
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

    def __init__(self, portfolio, target_allocations=None):
        target_allocations = target_allocations or {"STOCK_A": 0.5, "STOCK_B": 0.5}
        super().__init__(
            portfolio, parameters={"target_allocations": target_allocations}
        )
        self.target_allocations = target_allocations
        self.days_since_rebalance = 0
        self.rebalance_frequency = 20

    def get_trades(self):
        self.days_since_rebalance += 1

        if self.days_since_rebalance < self.rebalance_frequency:
            return []

        self.days_since_rebalance = 0

        # Calculate current portfolio value
        holdings = self.portfolio.holdings.loc[self.portfolio.current_period]
        prices = self.asset_universe.price_matrix.loc[self.portfolio.current_period]
        portfolio_value = self.portfolio.cash + (holdings * prices).sum()

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

    # Initialize with cash
    portfolio.collect_income()
    portfolio.move_cash(50000)
    portfolio.update_history()
    portfolio.advance_period()

    # Create strategy
    strategy = BuyAndHoldStrategy(portfolio, symbol="STOCK_A", quantity=100)

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
    """Run backtest with progress bar (requires tqdm)."""
    print("\n" + "=" * 70)
    print("Example 2: With Progress Bar")
    print("=" * 70)

    universe = create_sample_universe()
    portfolio = Portfolio(universe)

    portfolio.collect_income()
    portfolio.move_cash(100000)
    portfolio.update_history()
    portfolio.advance_period()

    strategy = MonthlyRebalanceStrategy(portfolio)

    runner = BacktestRunner(portfolio, strategy)
    result = runner.run(progress=True)  # Shows progress bar!

    print(f"\nFinal portfolio value: ${result.portfolio.cash:,.2f}")


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

    portfolio.collect_income()
    portfolio.move_cash(50000)
    portfolio.update_history()
    portfolio.advance_period()

    strategy = BuyAndHoldStrategy(portfolio, symbol="STOCK_B", quantity=200)

    # Define custom hooks
    def log_period_start(runner):
        """Log at the start of each period."""
        if runner._periods_completed % 50 == 0:  # Log every 50 periods
            holdings = runner.portfolio.holdings.loc[runner.current_period]
            prices = runner.asset_universe.price_matrix.loc[runner.current_period]
            portfolio_value = runner.portfolio.cash + (holdings * prices).sum()
            period_num = runner._periods_completed
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

    portfolio.collect_income()
    portfolio.move_cash(50000)
    portfolio.update_history()
    portfolio.advance_period()

    strategy = BuyAndHoldStrategy(portfolio)

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

    # Create base portfolio
    base_portfolio = Portfolio(universe)
    base_portfolio.collect_income()
    base_portfolio.move_cash(100000)
    base_portfolio.update_history()
    base_portfolio.advance_period()

    # Strategy 1: Buy and hold STOCK_A
    portfolio1 = base_portfolio.clone()
    strategy1 = BuyAndHoldStrategy(portfolio1, symbol="STOCK_A", quantity=200)
    result1 = BacktestRunner(portfolio1, strategy1).run()

    # Strategy 2: Buy and hold STOCK_B
    portfolio2 = base_portfolio.clone()
    strategy2 = BuyAndHoldStrategy(portfolio2, symbol="STOCK_B", quantity=400)
    result2 = BacktestRunner(portfolio2, strategy2).run()

    # Strategy 3: Balanced rebalancing
    portfolio3 = base_portfolio.clone()
    strategy3 = MonthlyRebalanceStrategy(portfolio3)
    result3 = BacktestRunner(portfolio3, strategy3).run()

    # Compare results
    print("\nStrategy Comparison:")
    print(f"  Strategy 1 (STOCK_A only): Final cash = ${result1.portfolio.cash:,.2f}")
    print(f"  Strategy 2 (STOCK_B only): Final cash = ${result2.portfolio.cash:,.2f}")
    print(f"  Strategy 3 (Rebalancing):  Final cash = ${result3.portfolio.cash:,.2f}")


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

    portfolio.collect_income()
    portfolio.move_cash(50000)
    portfolio.update_history()
    portfolio.advance_period()

    strategy = BuyAndHoldStrategy(portfolio)

    # Run only for first 100 periods
    periods = universe.get_period_index_range()
    runner = BacktestRunner(
        portfolio,
        strategy,
        start_period=periods[1],  # Start from second period
        end_period=periods[100],  # End at 100th period
    )
    result = runner.run()

    print(f"\nRan backtest from {result.start_period} to {result.end_period}")
    print(f"Total periods simulated: {result.total_periods}")


# =============================================================================
# Example 7: Context Manager
# =============================================================================


def example_context_manager():
    """Use BacktestRunner as a context manager."""
    print("\n" + "=" * 70)
    print("Example 7: Context Manager Pattern")
    print("=" * 70)

    universe = create_sample_universe()
    portfolio = Portfolio(universe)

    portfolio.collect_income()
    portfolio.move_cash(50000)
    portfolio.update_history()
    portfolio.advance_period()

    strategy = BuyAndHoldStrategy(portfolio)

    # Use context manager for automatic cleanup
    with BacktestRunner(portfolio, strategy) as runner:
        result = runner.run()

    print(f"\nBacktest completed: {result.success}")
    print(f"Final cash: ${result.portfolio.cash:,.2f}")


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
    example_context_manager()

    print("\n" + "=" * 70)
    print("All examples completed!")
    print("=" * 70)
