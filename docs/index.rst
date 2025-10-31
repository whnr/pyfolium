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

* **Tax Support**: Track short-term and long-term capital gains with FIFO or LIFO accounting
* **Fee Modeling**: Fixed fees, percentage-based fees, and min/max caps
* **Income Tracking**: Support for dividends and other asset income
* **Custom Strategies**: Extensible strategy framework via BaseStrategy ABC
* **Period-based Simulation**: Flexible time period management (daily, monthly, etc.)
* **Complete History**: Full transaction log and portfolio state history

Quick Example
-------------

.. code-block:: python

   from pyfolium.core import AssetUniverse, Asset, Portfolio, TaxConfig, FeeConfig
   import pandas as pd

   # Create asset universe
   universe = AssetUniverse(data_frequency='D')

   # Add assets with price data
   asset_data = pd.DataFrame({
       'price': [100, 101, 102, 103],
       'income': [0, 0, 0, 1]
   }, index=pd.period_range('2024-01-01', periods=4, freq='D'))

   asset = Asset('AAPL', asset_data, universe)

   # Create portfolio with tax and fee configuration
   tax_config = TaxConfig(
       short_term_rate=0.37,
       long_term_rate=0.20,
       holding_period_days=365
   )

   fee_config = FeeConfig(
       fixed_fee=0,
       percent_fee=0.001
   )

   portfolio = Portfolio(
       universe=universe,
       initial_cash=10000,
       tax_config=tax_config,
       fee_config=fee_config
   )

   # Execute trades
   portfolio.buy_asset('AAPL', quantity=10)
   portfolio.update_history()
   portfolio.advance_period()

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
