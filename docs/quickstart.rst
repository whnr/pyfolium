Quick Start Guide
=================

This guide will walk you through the basic concepts and usage of Pyfolium.

Core Concepts
-------------

Pyfolium operates on a **period-based system** where time advances in discrete steps.
Each period represents a unit of time (day, month, etc.) during which operations must
occur in a specific sequence:

1. **Collect Income** - Dividends/income from holdings are distributed
2. **Transact** - Execute trades and cash movements
3. **Update History** - Record period state before advancing
4. **Advance Period** - Move to next period

Basic Workflow
--------------

1. Create an Asset Universe
^^^^^^^^^^^^^^^^^^^^^^^^^^^

The ``AssetUniverse`` is a container for all tradeable assets in your backtest:

.. code-block:: python

   from pyfolium.core import AssetUniverse

   universe = AssetUniverse(data_frequency='D')  # Daily frequency

2. Add Assets
^^^^^^^^^^^^^

Each ``Asset`` requires price data and optionally income data:

.. code-block:: python

   import pandas as pd
   from pyfolium.core import Asset

   # Create price and income data
   dates = pd.period_range('2024-01-01', periods=252, freq='D')
   asset_data = pd.DataFrame({
       'price': [100 + i * 0.1 for i in range(252)],
       'income': [0.25 if i % 90 == 89 else 0 for i in range(252)]  # Quarterly dividends
   }, index=dates)

   asset = Asset('AAPL', asset_data, universe)

3. Configure Portfolio
^^^^^^^^^^^^^^^^^^^^^^

Create a portfolio with tax and fee settings:

.. code-block:: python

   from pyfolium.core import Portfolio, TaxConfig, FeeConfig

   # Tax configuration
   tax_config = TaxConfig(
       short_term_rate=0.37,      # Short-term capital gains rate
       long_term_rate=0.20,       # Long-term capital gains rate
       holding_period_days=365,   # Days to qualify for long-term
       method='FIFO',             # Tax lot accounting method
       withhold_on_gains=True,    # Withhold tax on gains
       withhold_on_income=True    # Withhold tax on income
   )

   # Fee configuration
   fee_config = FeeConfig(
       fixed_fee=0,           # No fixed fee per trade
       percent_fee=0.001,     # 0.1% of trade value
       min_fee=0,            # No minimum fee
       max_fee=None          # No maximum fee cap
   )

   portfolio = Portfolio(
       universe=universe,
       initial_cash=100000,
       tax_config=tax_config,
       fee_config=fee_config
   )

4. Execute Trades
^^^^^^^^^^^^^^^^^

Trade within the period state machine:

.. code-block:: python

   # Buy 100 shares of AAPL
   portfolio.buy_asset('AAPL', quantity=100)

   # Update history to record this period's state
   portfolio.update_history()

   # Advance to next period
   portfolio.advance_period()

   # Collect any dividends
   portfolio.collect_income()

   # Sell 50 shares
   portfolio.sell_asset('AAPL', quantity=50)

   # Update and advance
   portfolio.update_history()
   portfolio.advance_period()

5. Analyze Results
^^^^^^^^^^^^^^^^^^

Access portfolio history and transactions:

.. code-block:: python

   # View transaction history
   print(portfolio.transactions)

   # View portfolio value over time
   print(portfolio.history)

   # Access current holdings
   print(portfolio.holdings)

   # Check current cash and tax owed
   print(f"Cash: ${portfolio.cash:.2f}")
   print(f"Tax Owed: ${portfolio.tax_owed:.2f}")

Using Strategies
----------------

For systematic trading, extend the ``BaseStrategy`` class:

.. code-block:: python

   from pyfolium.strategy import BaseStrategy

   class BuyAndHold(BaseStrategy):
       """Simple buy and hold strategy."""

       def get_trades(self) -> list[tuple[str, float]]:
           """Return list of (symbol, quantity) tuples."""
           # Buy 100 shares on first period, hold thereafter
           if self.portfolio.current_period == self.portfolio.universe.periods[0]:
               return [('AAPL', 100)]
           return []

   # Create strategy
   strategy = BuyAndHold(portfolio)

Using BacktestRunner (Recommended)
-----------------------------------

The ``BacktestRunner`` automates the simulation loop and provides progress tracking, hooks, and error handling:

.. code-block:: python

   from pyfolium.simulation import BacktestRunner

   # Simple usage with progress bar
   runner = BacktestRunner(portfolio, strategy, show_progress=True)
   result = runner.run()

   print(f"Final portfolio value: ${result.final_value:.2f}")
   print(f"Total periods: {result.periods_completed}")

   # Access portfolio and strategy from result
   print(result.portfolio.history)
   print(result.strategy.trades_df)

Custom Hooks
^^^^^^^^^^^^

Add custom behavior at key points in the simulation:

.. code-block:: python

   def log_period_end(context):
       print(f"Period {context.current_period}: Value = ${context.portfolio_value:.2f}")

   def log_errors(context):
       print(f"Error in period {context.current_period}: {context.error}")

   runner = BacktestRunner(
       portfolio,
       strategy,
       hooks={
           'period_end': log_period_end,
           'error': log_errors
       }
   )
   result = runner.run()

Manual Loop (Alternative)
^^^^^^^^^^^^^^^^^^^^^^^^^^

For more control, you can run the simulation manually:

.. code-block:: python

   for period in universe.periods:
       portfolio.collect_income()
       strategy.step()
       portfolio.update_history()
       portfolio.advance_period()

Next Steps
----------

* Explore the :doc:`api/index` for detailed API documentation
* Check the ``examples/backtest_runner_example.py`` for comprehensive examples
* Read about :doc:`api/simulation` for BacktestRunner hooks and customization
* Read about :doc:`api/core` for in-depth understanding of the core components
