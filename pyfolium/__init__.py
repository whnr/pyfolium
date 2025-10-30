"""Pyfolium - A Python backtesting library for portfolio management."""

from pyfolium.core import (
    Asset,
    AssetUniverse,
    FeeConfig,
    Portfolio,
    PortfolioState,
    TaxConfig,
)
from pyfolium.data import (
    load_from_csv,
    load_from_dataframe,
)
from pyfolium.strategy import BaseStrategy


__all__ = [
    # Core classes
    "Asset",
    "AssetUniverse",
    "Portfolio",
    "PortfolioState",
    # Configuration
    "TaxConfig",
    "FeeConfig",
    # Strategy framework
    "BaseStrategy",
    # Data loaders
    "load_from_csv",
    "load_from_dataframe",
]

__version__ = "0.1.0"
