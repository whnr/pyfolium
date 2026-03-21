"""Example usage of BacktestRunner for running portfolio backtests.

This example demonstrates both simple and advanced usage patterns of the
BacktestRunner class for automating portfolio simulations.

Examples progress from basic usage through realistic financial modeling
with taxes, fees, lot-level trading, and structured logging.
"""

import numpy as np
import pandas as pd

from pyfolium import (
    Asset,
    AssetUniverse,
    BacktestResult,
    BacktestRunner,
    BaseStrategy,
    FeeConfig,
    OutputMode,
    Portfolio,
    Severity,
    TaxConfig,
    load_from_dataframe,
)


# =============================================================================
# Setup: Create sample data and universes
# =============================================================================


def create_sample_universe() -> AssetUniverse:
    """Create a sample asset universe with two stocks.

    STOCK_A: Linearly growing stock with quarterly dividends.
    STOCK_B: Volatile random-walk stock, no dividends.
    """
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
    Asset("STOCK_A", universe, stock_a_data, income_column="income")

    # Stock B: Volatile stock, no dividends
    np.random.seed(42)
    cumulative_returns = np.cumsum(np.random.randn(252) * 0.02)
    stock_b_prices = 50 * (1 + cumulative_returns)
    stock_b_data = pd.DataFrame(
        {
            "price": pd.Series(stock_b_prices, index=dates),
        }
    )
    Asset("STOCK_B", universe, stock_b_data)

    return universe


def create_tax_harvesting_universe() -> AssetUniverse:
    """Create a universe with a stock that rises then falls, ideal for TLH.

    FUND: Rises from $100 to $130 (days 0-40), drops to $80 (days 41-80),
    then recovers to $100 (days 81-120). Buying at different points creates
    lots with gains and losses at any given time.
    """
    universe = AssetUniverse(data_frequency="D")
    dates = pd.period_range(start="2023-01-01", periods=120, freq="D")

    prices = []
    for i in range(120):
        if i <= 40:
            prices.append(100 + i * 0.75)  # rises: 100 → 130
        elif i <= 80:
            prices.append(130 - (i - 40) * 1.25)  # drops: 130 → 80
        else:
            prices.append(80 + (i - 80) * 0.5)  # recovers: 80 → 100
    fund_data = pd.DataFrame({"price": pd.Series(prices, index=dates)})
    Asset("FUND", universe, fund_data)

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


class TaxAwareStrategy(BaseStrategy):
    """Strategy that buys early and sells later to demonstrate tax treatment.

    Buys at the start, sells a portion after 100 periods to realize
    short-term capital gains (with daily data and a 1-year holding period,
    100 days is well within the short-term window).
    """

    def __init__(self, portfolio, **kwargs):
        super().__init__(portfolio, parameters={}, **kwargs)
        self.bought = False
        self.sold = False
        self.periods_elapsed = 0

    def get_trades(self):
        self.periods_elapsed += 1

        if not self.bought and self.portfolio.cash >= 10000:
            self.bought = True
            return [("STOCK_A", 100)]

        if self.bought and not self.sold and self.periods_elapsed >= 100:
            self.sold = True
            return [("STOCK_A", -50)]  # Sell half → short-term gain

        return []


class TaxLossHarvestingStrategy(BaseStrategy):
    """Strategy that harvests tax losses by selling specific losing lots.

    Buys FUND in two lots at different prices, then uses sell_lot() to
    specifically sell the lot purchased at a higher price (the loser),
    bypassing FIFO ordering to maximize realized losses.
    """

    def __init__(self, portfolio, **kwargs):
        super().__init__(portfolio, parameters={}, **kwargs)
        self.lot_a_bought = False
        self.lot_b_bought = False
        self.harvested = False
        self.periods_elapsed = 0

    def get_trades(self):
        # Buy orders go through the normal execute_trades path
        self.periods_elapsed += 1

        if not self.lot_a_bought and self.periods_elapsed == 1:
            self.lot_a_bought = True
            return [("FUND", 50)]  # Lot A: buy at ~$100

        if not self.lot_b_bought and self.periods_elapsed == 30:
            self.lot_b_bought = True
            return [("FUND", 50)]  # Lot B: buy at ~$122

        return []

    def step(self):
        """Override step to handle lot-specific selling."""
        trades = self.get_trades()
        self.execute_trades(trades)

        # At period 90, price is ~$85 — both lots are underwater but
        # Lot B ($122) has a larger loss than Lot A ($100).
        # Sell Lot B specifically to harvest the bigger loss.
        if not self.harvested and self.periods_elapsed == 90:
            open_lots = self.portfolio.open_lots.get("FUND", [])
            if len(open_lots) >= 2:
                # Sort by cost basis descending to find the most expensive lot
                lots_by_cost = sorted(
                    open_lots, key=lambda lot: lot.cost_basis_per_share, reverse=True
                )
                losing_lot = lots_by_cost[0]

                self.log(
                    Severity.INFO,
                    "Harvesting tax loss",
                    data={
                        "lot_period": str(losing_lot.period),
                        "cost_basis": losing_lot.cost_basis_per_share,
                        "quantity": losing_lot.quantity_remaining,
                    },
                )

                self.portfolio.sell_lot(losing_lot, losing_lot.quantity_remaining)
                self._record_trade(
                    "FUND",
                    -losing_lot.quantity_remaining,
                    -losing_lot.quantity_remaining,
                    category="tax_loss_harvest",
                )
                self.harvested = True


class LoggingStrategy(BaseStrategy):
    """Strategy that emits structured log entries for observability.

    Logs trade decisions with context: prices, cash, and reasoning.
    """

    def __init__(self, portfolio, **kwargs):
        super().__init__(portfolio, parameters={}, **kwargs)
        self.invested = False

    def get_trades(self):
        price = float(
            self.asset_universe.price_matrix.loc[
                self.portfolio.current_period, "STOCK_A"
            ]
        )

        if not self.invested and self.portfolio.cash >= 10000:
            self.invested = True
            self.log(
                Severity.INFO,
                "Investing initial capital",
                data={"cash": self.portfolio.cash, "price": price},
            )
            return [("STOCK_A", 50)]

        if self.invested:
            self.log(
                Severity.DEBUG,
                "Holding position",
                data={"price": price, "unrealized_value": price * 50},
            )

        return []


# =============================================================================
# Example 1: Simple Backtest
# =============================================================================


def example_simple() -> BacktestResult:
    """Simplest possible backtest - just run it!"""
    print("=" * 70)
    print("Example 1: Simple Backtest")
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

    return result


# =============================================================================
# Example 2: Taxes & Fees
# =============================================================================


def example_taxes_and_fees() -> BacktestResult:
    """Demonstrate realistic simulation with tax and fee configuration.

    Shows how TaxConfig and FeeConfig affect portfolio economics:
    - Capital gains are classified as short-term (taxed at 30%)
    - Transaction fees reduce proceeds and increase cost basis
    - Tax withholding deducts taxes from cash at the time of sale
    """
    print("\n" + "=" * 70)
    print("Example 2: Taxes & Fees")
    print("=" * 70)

    universe = create_sample_universe()

    # Configure taxes: 30% short-term, 15% long-term, withhold at sale
    tax_config = TaxConfig(
        short_term_rate=0.30,
        long_term_rate=0.15,
        withhold_tax=True,
        tax_strategy="FIFO",
    )

    # Configure fees: $5 fixed + 0.1% of trade value, capped at $25
    fee_config = FeeConfig(
        fixed_fee=5.0,
        percentage_fee=0.001,
        minimum_fee=5.0,
        maximum_fee=25.0,
    )

    portfolio = Portfolio(universe, tax_config=tax_config, fee_config=fee_config)
    strategy = TaxAwareStrategy(portfolio, initial_cash=50000)

    runner = BacktestRunner(portfolio, strategy)
    result = runner.run()

    # Inspect financial impact
    txns = result.portfolio.transactions
    sells = txns[txns["type"] == "sell"]

    print(f"\nFinal cash: ${result.portfolio.cash:,.2f}")
    print(f"Tax owed: ${result.portfolio.tax_owed:,.2f}")
    print(f"Total fees paid: ${txns['fee'].sum():,.2f}")

    if not sells.empty:
        print("\nSale details:")
        print(f"  Short-term gains: ${sells['short_term_gains'].sum():,.2f}")
        print(f"  Long-term gains:  ${sells['long_term_gains'].sum():,.2f}")
        print(f"  Tax withheld:     ${sells['tax_paid'].sum():,.2f}")

    return result


# =============================================================================
# Example 3: Tax-Loss Harvesting with sell_lot()
# =============================================================================


def example_tax_loss_harvesting() -> BacktestResult:
    """Demonstrate lot-level introspection and specific-lot selling.

    Uses sell_lot() to bypass FIFO ordering and target the lot with the
    largest unrealized loss — a common tax optimization technique.
    Requires TaxConfig(allow_specific_lot=True).
    """
    print("\n" + "=" * 70)
    print("Example 3: Tax-Loss Harvesting with sell_lot()")
    print("=" * 70)

    universe = create_tax_harvesting_universe()

    tax_config = TaxConfig(
        short_term_rate=0.30,
        long_term_rate=0.15,
        allow_specific_lot=True,
        tax_strategy="FIFO",
    )

    portfolio = Portfolio(universe, tax_config=tax_config)
    strategy = TaxLossHarvestingStrategy(portfolio, initial_cash=50000)

    runner = BacktestRunner(portfolio, strategy)
    result = runner.run()

    # Show what happened
    txns = result.portfolio.transactions
    sells = txns[txns["type"] == "sell"]

    print("\nOpen lots remaining:")
    for symbol, lots in result.portfolio.open_lots.items():
        for lot in lots:
            print(
                f"  {symbol}: {lot.quantity_remaining} shares "
                f"@ ${lot.cost_basis_per_share:.2f} (bought {lot.period})"
            )

    if not sells.empty:
        print(f"\nRealized loss: ${sells['short_term_gains'].sum():,.2f}")
        print("  (Negative = loss harvested for tax offset)")

    return result


# =============================================================================
# Example 4: Data Loading
# =============================================================================


def example_data_loading() -> BacktestResult:
    """Demonstrate load_from_dataframe() for converting external data.

    Shows the typical workflow: raw data with DatetimeIndex and custom
    column names → pyfolium-compatible DataFrame with PeriodIndex.

    For CSV files, use load_from_csv() with similar parameters.
    """
    print("\n" + "=" * 70)
    print("Example 4: Data Loading")
    print("=" * 70)

    # Simulate raw market data (as you might download from a data provider)
    dates = pd.date_range("2023-01-01", periods=252, freq="D")
    raw_data = pd.DataFrame(
        {
            "Close": [100 + i * 0.3 + np.sin(i / 20) * 5 for i in range(252)],
            "Dividend": [0.5 if i % 63 == 0 else 0.0 for i in range(252)],
        },
        index=dates,
    )

    # Convert to pyfolium format: PeriodIndex, standardized column names
    loaded = load_from_dataframe(
        raw_data,
        frequency="D",
        price_column="Close",
        income_column="Dividend",
    )

    print(f"Loaded {len(loaded)} periods of data")
    print(f"Columns: {list(loaded.columns)}")
    print(f"Index type: {type(loaded.index).__name__}")

    # Use in a backtest
    universe = AssetUniverse(data_frequency="D")
    Asset("AKTIE", universe, loaded, income_column="income")

    portfolio = Portfolio(universe)
    strategy = BuyAndHoldStrategy(
        portfolio, symbol="AKTIE", quantity=100, initial_cash=50000
    )

    runner = BacktestRunner(portfolio, strategy)
    result = runner.run()

    print(f"\nBacktest: {result.total_periods} periods, success={result.success}")
    print(f"Final value: ${result.portfolio.total_value:,.2f}")

    return result


# =============================================================================
# Example 5: Output Modes
# =============================================================================


def example_output_modes() -> BacktestResult:
    """Run backtest with different output modes.

    OutputMode.SILENT   — no terminal output (default)
    OutputMode.SUMMARY  — one-line summary at end
    OutputMode.PROGRESS — tqdm progress bar + summary
    """
    print("\n" + "=" * 70)
    print("Example 5: Output Modes")
    print("=" * 70)

    universe = create_sample_universe()
    portfolio = Portfolio(universe)

    strategy = MonthlyRebalanceStrategy(portfolio, initial_cash=100000)

    runner = BacktestRunner(portfolio, strategy)
    # Using SUMMARY here; try PROGRESS for a tqdm bar
    result = runner.run(output=OutputMode.SUMMARY)

    print(f"\nFinal portfolio value: ${result.portfolio.total_value:,.2f}")

    return result


# =============================================================================
# Example 6: Custom Hooks for Logging
# =============================================================================


def example_hooks() -> BacktestResult:
    """Use hooks to log portfolio state during simulation."""
    print("\n" + "=" * 70)
    print("Example 6: Custom Hooks for Logging")
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
    result = runner.run()

    return result


# =============================================================================
# Example 7: Step-by-Step Execution
# =============================================================================


def example_step_by_step() -> BacktestRunner:
    """Execute backtest step-by-step for debugging.

    Returns the runner (not BacktestResult) since the backtest is
    intentionally left incomplete — run_period() advances one period
    at a time, letting you inspect state between steps.
    """
    print("\n" + "=" * 70)
    print("Example 7: Step-by-Step Execution")
    print("=" * 70)

    universe = create_sample_universe()
    portfolio = Portfolio(universe)

    strategy = BuyAndHoldStrategy(portfolio, initial_cash=50000)

    runner = BacktestRunner(portfolio, strategy)

    # Run first 10 periods manually
    print("\nRunning first 10 periods manually:")
    for i in range(10):
        runner.run_period()
        cash = runner.portfolio.cash
        holdings = runner.portfolio.holdings.iloc[runner._periods_completed - 1]
        value = runner.portfolio.total_value
        stock_a = holdings["STOCK_A"]
        print(
            f"  Period {i + 1}: Cash=${cash:,.2f} | "
            f"STOCK_A={stock_a:.0f} | Value=${value:,.2f}"
        )

        # Could add custom logic here, e.g., stop on condition
        if runner.portfolio.cash < 0:
            print("  WARNING: Negative cash detected!")
            break

    return runner


# =============================================================================
# Example 8: Comparing Multiple Strategies
# =============================================================================


def example_compare_strategies() -> dict[str, BacktestResult]:
    """Compare performance of different strategies using clone().

    Portfolio.clone() creates an independent deep copy, so each strategy
    runs on its own portfolio without interference.
    """
    print("\n" + "=" * 70)
    print("Example 8: Comparing Multiple Strategies")
    print("=" * 70)

    universe = create_sample_universe()

    # Add fees to make the comparison realistic
    fee_config = FeeConfig(fixed_fee=5.0, percentage_fee=0.001)
    base_portfolio = Portfolio(universe, fee_config=fee_config)

    # Each strategy gets an independent clone
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

    # Confirm clones are independent — base portfolio is untouched
    print(f"\nBase portfolio cash (should be 0): ${base_portfolio.cash:,.2f}")

    v1 = result1.portfolio.total_value
    v2 = result2.portfolio.total_value
    v3 = result3.portfolio.total_value
    print("\nStrategy Comparison:")
    print(f"  Strategy 1 (STOCK_A only): Total value = ${v1:,.2f}")
    print(f"  Strategy 2 (STOCK_B only): Total value = ${v2:,.2f}")
    print(f"  Strategy 3 (Rebalancing):  Total value = ${v3:,.2f}")

    return {
        "stock_a_only": result1,
        "stock_b_only": result2,
        "rebalancing": result3,
    }


# =============================================================================
# Example 9: Custom Period Range
# =============================================================================


def example_custom_period_range() -> BacktestResult:
    """Run backtest over a specific period range.

    Strategy declares start_period (e.g. after a warmup window).
    Runner declares end_period. Resolution precedence:
    runner arg > strategy.start_period > portfolio.current_period.
    """
    print("\n" + "=" * 70)
    print("Example 9: Custom Period Range")
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

    return result


# =============================================================================
# Example 10: Strategy Logging & Result Inspection
# =============================================================================


def example_logging() -> BacktestResult:
    """Demonstrate structured logging from strategies and result inspection.

    Strategies emit log entries via self.log() with severity levels and
    structured data payloads. The BacktestResult exposes these as a list,
    DataFrame, and convenience filters.
    """
    print("\n" + "=" * 70)
    print("Example 10: Strategy Logging & Result Inspection")
    print("=" * 70)

    universe = create_sample_universe()
    portfolio = Portfolio(universe)

    strategy = LoggingStrategy(portfolio, initial_cash=50000)
    runner = BacktestRunner(portfolio, strategy)
    result = runner.run()

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
        if entry.data:
            print(f"    data: {entry.data}")

    # DataFrame view for analysis
    df = result.log_df
    if not df.empty:
        info_count = len(df[df["severity"] == "INFO"])
        debug_count = len(df[df["severity"] == "DEBUG"])
        print(f"\nLog breakdown: {info_count} INFO, {debug_count} DEBUG")

    return result


# =============================================================================
# Run all examples
# =============================================================================

if __name__ == "__main__":
    example_simple()
    example_taxes_and_fees()
    example_tax_loss_harvesting()
    example_data_loading()
    example_output_modes()
    example_hooks()
    example_step_by_step()
    example_compare_strategies()
    example_custom_period_range()
    example_logging()

    print("\n" + "=" * 70)
    print("All examples completed!")
    print("=" * 70)
