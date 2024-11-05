from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional

import pandas as pd


@dataclass
class TaxConfig:
    """Configuration for tax calculations"""

    short_term_rate: float = 0.0
    long_term_holding_period: timedelta = timedelta(365)  # at least one year
    long_term_rate: float = 0.0
    withhold_tax: bool = False

    def is_long_term(self, purchase_date: datetime, sale_date: datetime) -> bool:
        """Check if a transaction is long-term"""
        return sale_date - purchase_date >= self.long_term_holding_period

    def calculate_tax(
        self, purchase_date: datetime, sale_date: datetime, proceeds: float
    ) -> float:
        """
        Calculate tax for a given transaction.

        This is useful if you have tax withholding and
        want to calculate the tax for each transaction.
        Don't use it if you want to calculate the total tax
        for your portfolio at the end of a period.

        Parameters
        ----------
        purchase_date : datetime
            Date of purchase
        sale_date : datetime
            Date of sale
        proceeds : float
            Proceeds from sale. Will raise an error if negative.

        Returns
        -------
        tax : float
            Calculated tax. Will be zero if the transaction is not long-term.k

        Raises
        ------
        ValueError
            If proceeds is negative
        """
        if proceeds < 0.0:
            raise ValueError(
                "Proceeds must be non-negative. You have to handle losses in Portfolio."
            )
        if self.is_long_term(purchase_date, sale_date):
            tax = proceeds * self.long_term_rate
        else:
            tax = proceeds * self.short_term_rate
        return tax


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


class Asset:
    """Represents a financial asset with data.

    A price column is required.
    A dividend column is optional.
    Any other columns can be added to the dataframe.
    It will automatically add itself to the asset universe.

    Attributes
    ----------
    symbol : str
        The symbol of the asset.
    assetUniverse : AssetUniverse
        The asset universe that the asset will be added to.
    data : pd.DataFrame
        The data must have a period index.
        The frequency of the data must match the data_frequency of the assetUniverse.
    metadata : Optional[Dict[str, str]]
        Additional metadata of the asset.
    price_column : str
        The name of the column containing the price of the asset."""

    def __init__(
        self,
        symbol: str,
        assetUniverse: "AssetUniverse",
        data: pd.DataFrame,
        price_column: str = "price",
        income_column: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ):
        self.symbol = symbol
        self.assetUniverse = assetUniverse
        self.data = data
        self.price_column = price_column
        if income_column:
            self.income_column = income_column
        self.metadata = metadata

        if self.price_column not in self.data.columns:
            raise ValueError(f"Column {self.price_column} not in data")

        if not isinstance(self.data.index, pd.PeriodIndex):
            raise ValueError("Data must have a period index")

        if self.data.index.freqstr != self.assetUniverse.data_frequency:
            raise ValueError(
                f"Data frequency of {self.data.index.freqstr}"
                f"does not match data_frequency of {self.assetUniverse.data_frequency}"
            )

        self.start_time = self.data.index.min()
        self.end_time = self.data.index.max()

        # Add the asset to the parent asset universe
        self.assetUniverse.add_asset(self)

    def get_price_at(self, period: pd.Period, precise: bool = False) -> float:
        return self.data.loc[period][self.price_column]  # type: ignore

    def get_income_at(self, period: pd.Period, precise: bool = False) -> float:
        return self.data.loc[period][self.income_column]  # type: ignore

    @property
    def price(self):
        return self.data[self.price_column]

    @property
    def income(self):
        return self.data[self.income_column]


class AssetUniverse:
    def __init__(self, data_frequency: str):
        """
        Initialize the AssetUniverse

        Parameters
        ----------
        data_frequency : str
            String describing the frequency of the data.
            Must be one of the pandas period aliases like 'D' or 'M'.
        """
        self.data_frequency = data_frequency
        self.assets: Dict[str, Asset] = {}

    def add_asset(self, asset: Asset):
        self.assets[asset.symbol] = asset
