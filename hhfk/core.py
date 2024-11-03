from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, NamedTuple, Optional, Tuple

import pandas as pd


class TaxLot(NamedTuple):
    """Represents a tax lot for capital gains calculations"""

    purchase_date: datetime
    quantity: float
    price: float
    fees: float

    @property
    def cost_basis_per_share(self) -> float:
        return (self.quantity * self.price + self.fees) / self.quantity


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


@dataclass
class Transaction:
    """Represents a buy/sell transaction including fees"""

    timestamp: datetime
    asset_symbol: str
    quantity: float  # positive for buy, negative for sell
    price: float
    fees: float = 0.0

    @property
    def total_cost(self) -> float:
        return self.quantity * self.price + self.fees


class Position:
    """
    Tracks position in an asset including tax lots and dividend history
    """

    def __init__(self, asset_symbol: str):
        self.asset_symbol = asset_symbol
        self.tax_lots: List[TaxLot] = []
        self.dividends_received: float = 0.0
        self.realized_gains: Dict[int, float] = {}  # Year -> Gains
        self.transactions: List[Transaction] = []

    @property
    def quantity(self) -> float:
        return sum(lot.quantity for lot in self.tax_lots)

    @property
    def cost_basis(self) -> float:
        return sum(lot.quantity * lot.cost_basis_per_share for lot in self.tax_lots)

    def add_tax_lot(
        self, purchase_date: datetime, quantity: float, price: float, fees: float
    ):
        self.tax_lots.append(TaxLot(purchase_date, quantity, price, fees))

    def _get_holding_period(
        self, purchase_date: datetime, sale_date: datetime
    ) -> timedelta:
        return sale_date - purchase_date

    def get_long_and_short_term_quantites(
        self, tax_config: TaxConfig
    ) -> Tuple[float, float]:
        long_term_quantity = 0.0
        short_term_quantity = 0.0
        for lot in self.tax_lots:
            period = self._get_holding_period(
                lot.purchase_date, sale_date=lot.purchase_date
            )
            if period > tax_config.long_term_holding_period:
                short_term_quantity += lot.quantity
            else:
                long_term_quantity += lot.quantity
        return long_term_quantity, short_term_quantity

    def sell_shares(
        self,
        sale_date: datetime,
        quantity: float,
        price: float,
        fees: float,
        tax_config: TaxConfig,
    ) -> Tuple[float, float, float]:
        """
        Sell shares using FIFO method and calculate gains/losses
        Returns: (total_proceeds, long_term_gain, short_term_gain, realized_gain)
        """
        if quantity > self.quantity:
            raise ValueError("Insufficient shares for sale")

        remaining_quantity = quantity
        fee_per_share = fees / quantity
        total_proceeds = 0.0
        short_term_gains = 0.0
        long_term_gains = 0.0
        new_tax_lots = []

        for lot in self.tax_lots:
            if remaining_quantity <= 0:
                new_tax_lots.append(lot)
                continue

            lot_sale_quantity = min(remaining_quantity, lot.quantity)
            remaining_quantity -= lot_sale_quantity

            # Calculate proceeds and gain/loss
            proceeds = lot_sale_quantity * (price - fee_per_share)
            total_proceeds += proceeds

            cost = lot_sale_quantity * lot.cost_basis_per_share

            gain = proceeds - cost

            # Determine holding period and record gain/loss
            period = self._get_holding_period(lot.purchase_date, sale_date)
            if period > tax_config.long_term_holding_period:
                long_term_gains += gain
            else:
                short_term_gains += gain

            # Update tax lot if partially sold
            if lot_sale_quantity < lot.quantity:
                remaining_ratio = (lot.quantity - lot_sale_quantity) / lot.quantity
                new_tax_lots.append(
                    TaxLot(
                        lot.purchase_date,
                        lot.quantity - lot_sale_quantity,
                        lot.price,
                        lot.fees * remaining_ratio,
                    )
                )

        self.tax_lots = new_tax_lots

        # Record realized gains by year
        sale_year = sale_date.year
        if sale_year not in self.realized_gains:
            self.realized_gains[sale_year] = 0.0
        self.realized_gains[sale_year] += long_term_gains + short_term_gains

        return total_proceeds, long_term_gains, short_term_gains


class Portfolio:
    """
    Manages multiple positions with tax and fee awareness
    """

    def __init__(
        self,
        initial_cash: float = 0.0,
        tax_config: Optional[TaxConfig] = None,
        fee_config: Optional[FeeConfig] = None,
    ):
        self.cash = initial_cash
        self.positions: Dict[str, Position] = {}
        self.tax_config = tax_config or TaxConfig()
        self.fee_config = fee_config or FeeConfig()
        self.history: List[Tuple[datetime, dict]] = []
        self.annual_summaries: Dict[int, dict] = {}

    def _add_annual_summary(self, year: int):
        self.annual_summaries[year] = {
            "short_term_gains": 0.0,
            "long_term_gains": 0.0,
            "short_term_dividends": 0.0,
            "long_term_dividends": 0.0,
            "fees": 0.0,
            "total_tax_liability": 0.0,
            "taxes_paid": 0.0,
        }

    def add_transaction(self, transaction: Transaction):
        """Process a buy/sell transaction with tax implications"""
        if transaction.asset_symbol not in self.positions:
            self.positions[transaction.asset_symbol] = Position(
                transaction.asset_symbol
            )

        position = self.positions[transaction.asset_symbol]

        year = transaction.timestamp.year
        if year not in self.annual_summaries:
            self._add_annual_summary(year)

        summary = self.annual_summaries[year]

        if transaction.quantity > 0:  # Buy
            position.add_tax_lot(
                transaction.timestamp,
                transaction.quantity,
                transaction.price,
                transaction.fees,
            )
            self.cash -= transaction.total_cost

            # update annual summary
            summary["fees"] += transaction.fees

        else:  # Sell
            quantity = abs(transaction.quantity)
            proceeds, long_term_gains, short_term_gains = position.sell_shares(
                transaction.timestamp,
                quantity,
                transaction.price,
                transaction.fees,
                self.tax_config,
            )
            self.cash += proceeds - transaction.fees

            # Update annual summary
            summary["short_term_gains"] += short_term_gains
            summary["long_term_gains"] += long_term_gains
            summary["fees"] += transaction.fees

    def record_dividend(
        self,
        timestamp: datetime,
        asset_symbol: str,
        amount_per_share: float,
    ):
        """Record dividend with tax implications"""
        if asset_symbol in self.positions:
            long_term_quantity, short_term_quantity = self.positions[
                asset_symbol
            ].get_long_and_short_term_quantites(self.tax_config)

            long_term_dividend = amount_per_share * long_term_quantity
            short_term_dividend = amount_per_share * short_term_quantity

            gross_dividend = long_term_dividend + short_term_dividend
            total_tax_liability = (
                long_term_dividend * self.tax_config.long_term_rate
                + short_term_dividend * self.tax_config.short_term_rate
            )
            net_dividend = gross_dividend - total_tax_liability

            if self.tax_config.withhold_tax:
                self.cash += net_dividend
            else:
                self.cash += gross_dividend

            self.positions[asset_symbol].dividends_received += gross_dividend

            year = timestamp.year
            if year not in self.annual_summaries:
                self._add_annual_summary(year)

            self.annual_summaries[year]["long_term_dividends"] += long_term_dividend
            self.annual_summaries[year]["short_term_dividends"] += short_term_dividend
            self.annual_summaries[year]["total_tax_liability"] += total_tax_liability
            if self.tax_config.withhold_tax:
                self.annual_summaries[year]["taxes_paid"] += total_tax_liability
        else:
            raise ValueError(f"Asset {asset_symbol} not found in portfolio")

    def calculate_tax_liability(self, year: int) -> float:
        """Calculate total tax liability for a given year

        We are not implementing any tax loss harvesting here.
        The minimal tax liability is always 0, never negative.

        FIXME why is this not calculated on every transaction? Where is this used?
        """
        if year not in self.annual_summaries:
            return 0.0

        summary = self.annual_summaries[year]

        # Calculate capital gains taxes
        short_term_tax = (
            summary["short_term_gains"] + summary["short_term_dividends"]
        ) * self.tax_config.short_term_rate
        long_term_tax = (
            summary["long_term_gains"] + summary["long_term_dividends"]
        ) * self.tax_config.long_term_rate

        return min(0, short_term_tax + long_term_tax)

    def get_annual_summary(self, year: int) -> dict:
        """Get comprehensive annual summary including taxes"""
        if year not in self.annual_summaries:
            self._add_annual_summary(year)

        # FIXME this is not good. need to refactor and fix!

        summary = self.annual_summaries[year].copy()
        summary["total_tax_liability"] = self.calculate_tax_liability(year)
        summary["net_profit"] = (
            summary["short_term_gains"]
            + summary["long_term_gains"]
            + summary["short_term_dividends"]
            + summary["long_term_dividends"]
            - summary["fees"]
            - summary["total_tax_liability"]
        )
        return summary

    def get_total_value(self, price_data: Dict[str, float]) -> float:
        """Calculate total portfolio value"""
        return self.cash + sum(
            pos.quantity * price_data[pos.asset_symbol]
            for pos in self.positions.values()
        )

    def update_history(self, timestamp: datetime, price_data: Dict[str, float]):
        """Update portfolio history with current state"""
        self.history.append(
            (
                timestamp,
                {
                    "cash": self.cash,
                    "total_value": self.get_total_value(price_data),
                    "positions": {
                        symbol: pos.quantity for symbol, pos in self.positions.items()
                    },
                    "year_to_date": self.get_annual_summary(timestamp.year),
                },
            )
        )
