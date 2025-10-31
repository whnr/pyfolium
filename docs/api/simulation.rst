Simulation Module
=================

.. automodule:: pyfolium.simulation
   :members:
   :undoc-members:
   :show-inheritance:

Classes
-------

BacktestRunner
^^^^^^^^^^^^^^

.. autoclass:: pyfolium.simulation.BacktestRunner
   :members:
   :special-members: __init__

BacktestResult
^^^^^^^^^^^^^^

.. autoclass:: pyfolium.simulation.BacktestResult
   :members:
   :undoc-members:

Hooks
-----

The BacktestRunner supports custom hooks at various points in the simulation:

* **period_start**: Called at the beginning of each period
* **period_end**: Called at the end of each period
* **backtest_start**: Called once at the start of the backtest
* **backtest_end**: Called once at the end of the backtest
* **error**: Called when an error occurs during simulation

All hooks receive a ``HookContext`` object with the current state.

Example Usage
-------------

.. code-block:: python

   from pyfolium.simulation import BacktestRunner

   # Simple usage
   runner = BacktestRunner(portfolio, strategy, show_progress=True)
   result = runner.run()

   # With custom hooks
   def my_hook(context):
       print(f"Period: {context.current_period}, Value: {context.portfolio_value}")

   runner = BacktestRunner(
       portfolio,
       strategy,
       hooks={'period_end': my_hook}
   )
   result = runner.run()

   # Step-by-step execution
   runner = BacktestRunner(portfolio, strategy)
   while not runner.is_complete():
       runner.run_period()
