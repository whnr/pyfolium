"""Pyfolium: Portfolio backtesting library.

A Python framework for simulating historical portfolio performance with support
for taxes, fees, income (dividends), and custom trading strategies.
"""

from pyfolium.core import (
    Asset,
    AssetUniverse,
    FeeConfig,
    Portfolio,
    PortfolioState,
    PriceMode,
    TaxConfig,
)
from pyfolium.data import (
    load_from_csv,
    load_from_dataframe,
)
from pyfolium.logging import LogEntry, OutputMode, Severity
from pyfolium.simulation import BacktestResult, BacktestRunner
from pyfolium.strategy import BaseStrategy


__all__ = [
    # Core classes
    "Asset",
    "AssetUniverse",
    "Portfolio",
    "PortfolioState",
    "PriceMode",
    # Configuration
    "TaxConfig",
    "FeeConfig",
    # Simulation
    "BacktestRunner",
    "BacktestResult",
    # Strategy framework
    "BaseStrategy",
    # Data loaders
    "load_from_csv",
    "load_from_dataframe",
    # Logging & observability
    "Severity",
    "LogEntry",
    "OutputMode",
]

__version__ = "0.1.0"
