.. Pyfolium documentation master file

Pyfolium Documentation
======================

**Pyfolium** is a Python backtesting library for portfolio management and trading strategies.
It provides a framework for simulating historical portfolio performance with support for taxes,
fees, income (dividends), and custom trading strategies.

The project name is a German pun: "Hätte hätte Fahrradkette" (roughly translates to "if only,
if only" - used when looking back at missed opportunities), fitting for a backtesting library.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   installation
   quickstart
   api/index

Features
--------

* **BacktestRunner**: Automated simulation orchestration with custom hooks and progress reporting
* **Tax Support**: Track short-term and long-term capital gains with FIFO or LIFO accounting
* **Fee Modeling**: Fixed fees, percentage-based fees, and min/max caps
* **Income Tracking**: Support for dividends and other asset income
* **Custom Strategies**: Extensible strategy framework via BaseStrategy ABC
* **Portfolio Cloning**: Create independent portfolio copies for strategy comparison
* **Period-based Simulation**: Flexible time period management (daily, monthly, etc.)
* **Complete History**: Full transaction log and portfolio state history
* **Data Loading**: Utilities for loading asset data from CSV and DataFrames

Quick Example
-------------

.. code-block:: python

   from pyfolium.core import AssetUniverse, Asset, Portfolio, TaxConfig, FeeConfig
   from pyfolium.strategy import BaseStrategy
   from pyfolium.simulation import BacktestRunner
   import pandas as pd

   # Create asset universe
   universe = AssetUniverse(data_frequency='D')

   # Add assets with price data
   asset_data = pd.DataFrame({
       'price': [100, 101, 102, 103, 105],
       'income': [0, 0, 0, 1, 0]
   }, index=pd.period_range('2024-01-01', periods=5, freq='D'))

   asset = Asset('AAPL', asset_data, universe)

   # Create portfolio with tax and fee configuration
   tax_config = TaxConfig(
       short_term_rate=0.37,
       long_term_rate=0.20,
       holding_period_days=365
   )

   fee_config = FeeConfig(fixed_fee=0, percent_fee=0.001)

   portfolio = Portfolio(
       universe=universe,
       initial_cash=10000,
       tax_config=tax_config,
       fee_config=fee_config
   )

   # Define a simple strategy
   class BuyAndHold(BaseStrategy):
       def get_trades(self):
           # Buy on first period
           if self.portfolio.current_period == self.universe.periods[0]:
               return [('AAPL', 10)]
           return []

   strategy = BuyAndHold(portfolio, universe)

   # Run backtest with BacktestRunner
   runner = BacktestRunner(portfolio, strategy, show_progress=True)
   result = runner.run()

   # Access results
   print(f"Final portfolio value: ${result.final_value:.2f}")
   print(result.portfolio.history)

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
