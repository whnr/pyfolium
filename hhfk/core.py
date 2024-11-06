from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

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

    @property
    def price(self):
        return self.data[self.price_column]

    @property
    def income(self):
        return self.data[self.income_column]

    def get_price_at(self, period: pd.Period, precise: bool = True) -> float:
        """Get the price of the asset at the given period

        Parameters
        ----------
        period : pd.Period
            The period to get the price for
        precise : bool, optional
            Whether to get the price for the exact period or the asof value

        Returns
        -------
        float
            The price of the asset at the given period
        """
        # if it's before the start date raise an key error
        if period < self.start_time:
            raise KeyError("Data not available before the start date")

        if not precise:
            # Return the last available price before the period
            return self.price.asof(period)

        return self.price[period]

    def get_income_at(self, period: pd.Period, precise: bool = True) -> float:
        return self.income[period]


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

    @property
    def asset_list(self) -> List[str]:
        """
        Get the list of asset symbols in the asset universe.

        Returns
        -------
        List[str]
            A list of symbols representing the assets in the universe.
        """
        return list(self.assets.keys())

    def get_period_index_range(self) -> pd.PeriodIndex:
        """
        Get the period index range for the asset universe

        This spans the start and end time of all assets.

        Returns
        -------
        pd.PeriodIndex
            The period index range for the asset universe
        """
        return pd.period_range(
            min(asset.start_time for asset in self.assets.values()),
            max(asset.end_time for asset in self.assets.values()),
            freq=self.data_frequency,
        )

    def get_price_matrix(self) -> pd.DataFrame:
        """
        Get the price matrix for the asset universe

        Returns
        -------
        pd.DataFrame
            The price matrix for the asset universe
        """
        return pd.DataFrame(
            {asset.symbol: asset.price for asset in self.assets.values()},
            index=self.get_period_index_range(),
        )


class Portfolio:
    transaction_types = (
        "buy",
        "sell",
        "dividend",
        "interest",
        "tax",
        "deposit",
        "withdrawal",
    )

    history_columns = [
        "asset_value",
        "cash_value",
        "long_term_gains",
        "short_term_gains",
        "taxes_paid",
    ]

    transaction_columns = [
        "period",
        "type",
        "symbol",
        "quantity",
        "price",
        "fee",
        "cost_basis",
        "tax",
        "amount",
    ]

    def __init__(
        self,
        asset_universe: AssetUniverse,
        fee_config: FeeConfig = FeeConfig(),
        tax_config: TaxConfig = TaxConfig(),
    ):
        self.asset_universe = asset_universe
        self.fee_config = fee_config
        self.tax_config = tax_config
        self.cash: float = 0.0

        period_index = self.asset_universe.get_period_index_range()
        self.history = pd.DataFrame(
            index=period_index, columns=Portfolio.history_columns
        )

        self.transactions = pd.DataFrame(columns=Portfolio.transaction_columns)

        self.holdings = pd.DataFrame(
            index=period_index, columns=self.asset_universe.asset_list
        )

    def _register_transaction(self):
        raise NotImplementedError

    def move_cash(self, period: pd.Period, amount: float):
        raise NotImplementedError

    def buy_asset(self, period: pd.Period, symbol: str, quantity: float):
        raise NotImplementedError

    def sell_asset(self, period: pd.Period, symbol: str, quantity: float):
        raise NotImplementedError

    def collect_income(self, period: pd.Period, symbol: str, quantity: float):
        raise NotImplementedError

    def pay_tax(self, period: pd.Period):
        raise NotImplementedError
