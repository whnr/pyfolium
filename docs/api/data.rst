Data Module
===========

.. automodule:: pyfolium.data
   :members:
   :undoc-members:
   :show-inheritance:

Functions
---------

load_from_csv
^^^^^^^^^^^^^

.. autofunction:: pyfolium.data.load_from_csv

load_from_dataframe
^^^^^^^^^^^^^^^^^^^

.. autofunction:: pyfolium.data.load_from_dataframe

Example Usage
-------------

.. code-block:: python

   from pyfolium.data import load_from_csv, load_from_dataframe
   from pyfolium.core import AssetUniverse
   import pandas as pd

   # Load from CSV
   universe = AssetUniverse(data_frequency='D')
   load_from_csv(
       universe=universe,
       symbol='AAPL',
       csv_path='data/aapl.csv',
       price_column='close',
       income_column='dividend'
   )

   # Load from DataFrame
   df = pd.DataFrame({
       'price': [100, 101, 102],
       'income': [0, 0, 1]
   }, index=pd.period_range('2024-01-01', periods=3, freq='D'))

   load_from_dataframe(
       universe=universe,
       symbol='MSFT',
       dataframe=df,
       price_column='price',
       income_column='income'
   )
