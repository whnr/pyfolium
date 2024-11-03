from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, NamedTuple, Optional, Tuple

import pandas as pd

@dataclass
class TaxConfig:
    """Configuration for tax calculations"""

    short_term_rate: float = 0.0
    long_term_holding_period: timedelta = timedelta(365)  # at least one year
    long_term_rate: float = 0.0
    withhold_tax: bool = False


@dataclass
class FeeConfig:
    """Configuration for transaction fees"""

    fixed_fee: float = 0.0  # Fixed fee per trade
    percentage_fee: float = 0.0  # Percentage of trade value
    minimum_fee: float = 0.0  # Minimum fee per trade
    maximum_fee: float = float("inf")  # Maximum fee per trade

    def calculate_fee(self, transaction_value: float) -> float:
        """Calculate the fee for a given transaction value"""
        percentage_based = transaction_value * self.percentage_fee
        total_fee = self.fixed_fee + percentage_based
        return max(min(total_fee, self.maximum_fee), self.minimum_fee)


@dataclass
class Asset:
    """Represents a financial asset with price and optional dividend history"""

    symbol: str
    data: pd.DataFrame
    price_column: str = "price"
    dividend_column: Optional[str] = "dividend"

    def __post_init__(self):
        if not isinstance(self.data.index, pd.DatetimeIndex):
            raise ValueError("DataFrame must have a DatetimeIndex")
        if self.price_column not in self.data.columns:
            raise ValueError(f"Price column '{self.price_column}' not found in data")
        if self.dividend_column and self.dividend_column not in self.data.columns:
            self.data[self.dividend_column] = 0.0
