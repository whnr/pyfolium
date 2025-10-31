from copy import deepcopy
from enum import Enum

import pandas as pd
from pydantic import BaseModel, Field, field_validator


class TaxConfig(BaseModel):
    """Configuration for tax calculations with validation.

    This config uses Pydantic for automatic validation of tax rates and strategies.

    Attributes:
        short_term_rate: Tax rate for short-term capital gains (0.0 to 1.0)
        long_term_holding_period: Period to qualify for long-term gains
        long_term_rate: Tax rate for long-term capital gains (0.0 to 1.0)
        withhold_tax: Whether to withhold tax immediately on gains
        tax_strategy: Tax lot selection strategy ("FIFO" or "LIFO")

    Note:
        Current limitation: When you withhold tax but sell at a loss,
        you will not get tax back.
    """

    short_term_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    long_term_holding_period: pd.DateOffset = Field(
        default_factory=lambda: pd.DateOffset(years=1)
    )
    long_term_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    withhold_tax: bool = False
    tax_strategy: str = Field(default="FIFO", pattern="^(FIFO|LIFO)$")

    @field_validator("tax_strategy")
    @classmethod
    def validate_tax_strategy(cls, v: str) -> str:
        """Validate that tax strategy is either FIFO or LIFO."""
        if v not in ["FIFO", "LIFO"]:
            raise ValueError(f"tax_strategy must be 'FIFO' or 'LIFO', got '{v}'")
        return v

    model_config = {"arbitrary_types_allowed": True}  # Allow pd.DateOffset


class FeeConfig(BaseModel):
    """Configuration for transaction fees with validation.

    This config uses Pydantic for automatic validation of fee parameters.

    Attributes:
        fixed_fee: Fixed fee per trade (non-negative)
        percentage_fee: Percentage of trade value as fee (0.0 to 1.0)
        minimum_fee: Minimum fee per trade (non-negative)
        maximum_fee: Maximum fee per trade (non-negative)
    """

    fixed_fee: float = Field(default=0.0, ge=0.0)
    percentage_fee: float = Field(default=0.0, ge=0.0, le=1.0)
    minimum_fee: float = Field(default=0.0, ge=0.0)
    maximum_fee: float = Field(default=float("inf"), gt=0.0)

    @field_validator("maximum_fee")
    @classmethod
    def validate_max_fee(cls, v: float, info) -> float:
        """Validate that maximum_fee >= minimum_fee."""
        if "minimum_fee" in info.data and v < info.data["minimum_fee"]:
            raise ValueError(
                f"maximum_fee ({v}) must be >= minimum_fee ({info.data['minimum_fee']})"
            )
        return v

    def calculate_fee(self, transaction_value: float) -> float:
        """Calculate the fee for a given transaction value.

        Args:
            transaction_value: Absolute value of the transaction

        Returns:
            Fee amount bounded by minimum_fee and maximum_fee
        """
        percentage_based = transaction_value * self.percentage_fee
        total_fee = self.fixed_fee + percentage_based
        return max(min(total_fee, self.maximum_fee), self.minimum_fee)


class Asset:
    """Represents a financial asset with data.

    A price column is required.
    A dividend column is optional.
    Any other columns can be added to the dataframe.
    It will automatically add itself to the asset universe.

    Attributes:
        symbol (str): The symbol of the asset.
        assetUniverse (AssetUniverse): The asset universe that the asset will be
            added to.
        data (pd.DataFrame): The data must have a period index.
            The frequency of the data must match the data_frequency of the
            assetUniverse.
        metadata (Dict[str, str], optional): Additional metadata of the asset.
        price_column (str): The name of the column containing the price of the
            asset."""

    def __init__(
        self,
        symbol: str,
        assetUniverse: "AssetUniverse",
        data: pd.DataFrame,
        price_column: str = "price",
        income_column: str | None = None,
        metadata: dict[str, str] | None = None,
    ):
        self.symbol = symbol
        self.assetUniverse = assetUniverse
        self.data = data
        self.price_column = price_column
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

        if not self.data.index.is_monotonic_increasing or not self.data.index.is_unique:
            raise ValueError(
                f"Period index of asset with symbol {self.symbol} "
                "is not strictly monotonic"
            )

        if income_column:
            if income_column not in self.data.columns:
                raise ValueError(f"Column {income_column} not in data")
            self.income_column = income_column
        else:
            # if no income column is provided, create an empty one
            self.income_column = "income"
            self.data[self.income_column] = 0

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
        """
        Get the price of the asset at the given period

        Args:
            period (pd.Period): The period to get the price for
            precise (bool, optional): Whether to get the price
                for the exact period or the asof value

        Returns:
            float: The price of the asset at the given period
        """
        # if it's before the start date raise an key error
        if period < self.start_time:
            raise KeyError("Data not available before the start date")

        if not precise:
            # Return the last available price before the period
            return float(self.price.asof(period))

        return float(self.price[period])

    def get_income_at(self, period: pd.Period, precise: bool = True) -> float:
        return float(self.income[period])


class AssetUniverse:
    def __init__(self, data_frequency: str):
        """Initialize the empty AssetUniverse

        Args:
            data_frequency (str): String describing the frequency of the data.
                Must be one of the pandas period aliases like 'D' or 'M'.
        """
        self.data_frequency = data_frequency
        self.assets: dict[str, Asset] = {}
        self.price_matrix: pd.DataFrame = pd.DataFrame()
        self.income_matrix: pd.DataFrame = pd.DataFrame()
        self.empty = True

    def add_asset(self, asset: Asset):
        """Add an asset to the universe with incremental matrix updates.

        This method uses incremental column addition instead of full matrix
        rebuilds for O(n) vs O(n²) performance when adding n assets.

        Args:
            asset: Asset to add to the universe

        Raises:
            ValueError: If asset symbol already exists or asset data is empty
        """
        # Check if we're trying to add an asset with the same symbol
        if asset.symbol in self.assets:
            raise ValueError(f"Asset with symbol {asset.symbol} already exists")
        # check if the asset is empty. Never happens, but we keep it just in case
        if asset.data.empty:
            raise ValueError(f"Asset with symbol {asset.symbol} is empty")

        self.assets[asset.symbol] = asset

        # Incremental update: just add columns instead of rebuilding entire matrix
        new_period_range = self.get_period_index_range()

        # Add new columns
        self.price_matrix[asset.symbol] = asset.price
        self.income_matrix[asset.symbol] = asset.income

        # Reindex to handle expanded period range (fills with NaN for missing periods)
        self.price_matrix = self.price_matrix.reindex(new_period_range)
        self.income_matrix = self.income_matrix.reindex(new_period_range)

        # Finally flag that the universe is not empty anymore
        self.empty = False

    @property
    def asset_symbols_list(self) -> list[str]:
        """
        Get the list of asset symbols in the asset universe.

        Returns:
            List[str]: A list of symbols representing the assets in the universe.
        """
        return list(self.assets.keys())

    def get_period_index_range(self) -> pd.PeriodIndex:
        """
        Get the period index range for the asset universe.

        It contains all periods between the start and end time of the assets.

        Returns:
            pd.PeriodIndex: The gapless period index range for the asset universe.
        """
        return pd.period_range(
            min(asset.start_time for asset in self.assets.values()),
            max(asset.end_time for asset in self.assets.values()),
            freq=self.data_frequency,
        )


class PortfolioState(Enum):
    COLLECT_INCOME = "COLLECT_INCOME"
    TRANSACT = "TRANSACT"
    DONE = "DONE"


class Portfolio:
    history_columns = [
        "cash",
        "tax_owed",
        "long_term_gains_in_period",
        "short_term_gains_in_period",
        "taxes_paid_in_period",
    ]

    transaction_columns = {
        "period": pd.PeriodDtype(freq="D"),  # just using D as a placeholder
        "type": str,
        "symbol": str,
        "quantity": float,
        "lot_quantity_remaining": float,  # for tax lot tracking partial sales
        "price": float,
        "fee": float,
        "cost_basis_per_share": float,
        "tax_paid": float,
        "long_term_gains": float,
        "short_term_gains": float,
        "transaction_amount": float,  # cash flow view
    }

    transaction_types = (
        "buy",
        "sell",
        "income",
        "pay_tax",
        "deposit",
        "withdrawal",
    )

    def __init__(
        self,
        asset_universe: AssetUniverse,
        fee_config: FeeConfig | None = None,
        tax_config: TaxConfig | None = None,
    ):
        """
        Initialize the Portfolio.

        Args:
            asset_universe (AssetUniverse):
                The asset universe containing the assets in the portfolio.
            fee_config (FeeConfig, optional):
                Configuration for transaction fees, by default FeeConfig().
            tax_config (TaxConfig, optional):
                Configuration for tax calculations, by default TaxConfig().

        Attributes:
            current_period: The time we're at right now.
                Shall be advanced strictly monotonously.
                Is initialized to the first period in the AssetUniverse.
            cash (float): The cash balance of the portfolio.
            tax_owed (float): The tax owed by the portfolio.
            history (pd.DataFrame): DataFrame tracking historical cash, taxes, gains.
            transactions (pd.DataFrame): DataFrame containing the transaction history.
            holdings (pd.DataFrame): DataFrame tracking the asset holdings over time.

        Notes:
            The Portfolio is initialized with a cash balance of 0.0.

            The portfolio state is tracked through the `_portfolio_states` series.
            The order of operations to update the portfolio in each period
            is enforced through the following steps:
            1. `collect_income`
            2. execute any transactions like `buy` or `move_cash`
            3. `update_history`

            Nobody is watching if you have enough cash for any transaction.
            You need to check that yourself.
        """
        self.asset_universe = asset_universe
        if self.asset_universe.empty:
            raise ValueError(
                "Asset universe is empty."
                "all assets must be added before initializing the portfolio"
            )
        self.fee_config = fee_config or FeeConfig()
        self.tax_config = tax_config or TaxConfig()
        self.cash: float = 0.0
        self.tax_owed: float = 0.0

        period_index = self.asset_universe.get_period_index_range()
        self._current_period_idx: int = 0
        self.current_period: pd.Period = period_index[self._current_period_idx]

        self.history = pd.DataFrame(
            index=period_index, columns=Portfolio.history_columns
        )
        self.history.astype(float)

        # Initialize empty transactions DataFrame with proper types
        self.transactions = pd.DataFrame(columns=Portfolio.transaction_columns)  # type: ignore[call-overload]
        self.transactions = self.transactions.astype(Portfolio.transaction_columns)
        self.transactions["period"] = self.transactions["period"].astype(
            pd.PeriodDtype(freq=self.asset_universe.data_frequency)
        )

        self.holdings = pd.DataFrame(
            data=0.0, index=period_index, columns=self.asset_universe.asset_symbols_list
        )

        # initialize the portfolio state tracker
        self._states = pd.Series(index=period_index, data=PortfolioState.COLLECT_INCOME)

    def clone(self) -> "Portfolio":
        """Create an independent deep copy of the portfolio.

        This method creates a complete copy of the portfolio with all its state,
        including transactions, holdings, history, and current position. The copy
        shares the same AssetUniverse reference (universes are immutable), but all
        mutable state is independent.

        This is useful for:
        - Running multiple backtests with different strategies on identical
          starting conditions
        - Parameter optimization and sensitivity analysis
        - Creating snapshots for comparison

        Returns:
            Portfolio: A deep copy of the portfolio with independent state

        Example:
            # Run same portfolio with different strategies
            base_portfolio = Portfolio(universe)
            base_portfolio.move_cash(100000)

            portfolio1 = base_portfolio.clone()
            portfolio2 = base_portfolio.clone()

            result1 = BacktestRunner(portfolio1, strategy1).run()
            result2 = BacktestRunner(portfolio2, strategy2).run()
        """
        # Create a new portfolio instance with same universe and configs
        cloned = Portfolio(
            asset_universe=self.asset_universe,  # Shared reference (immutable)
            fee_config=deepcopy(self.fee_config),
            tax_config=deepcopy(self.tax_config),
        )

        # Copy all mutable state
        cloned.cash = self.cash
        cloned.tax_owed = self.tax_owed
        cloned._current_period_idx = self._current_period_idx
        cloned.current_period = self.current_period

        # Deep copy DataFrames (they are mutable)
        cloned.history = self.history.copy(deep=True)
        cloned.transactions = self.transactions.copy(deep=True)
        cloned.holdings = self.holdings.copy(deep=True)
        cloned._states = self._states.copy(deep=True)

        return cloned

    def _check_state(self, expected_state: PortfolioState) -> None:
        current_state = self._states[self.current_period]  # type: ignore[call-overload]
        if current_state != expected_state:
            raise RuntimeError(
                f"Portfolio is in the wrong state: {current_state.value}. "
                f"Expected state: {expected_state.value}"
            )

    def _update_future_holdings(self, symbol: str, quantity: float) -> None:
        """
        Update the future holdings of a symbol in the portfolio.

        Args:
            symbol (str): The symbol of the asset to update the holdings for.
            quantity (float): The quantity of the asset to add to the holdings.
                Sign indicates the direction of the transaction.

        Notes:
            This function is used to update the holdings of an asset in the future,
            elegantly enabling fewer updates to be made in the future.
        """
        mask = self.holdings.index >= self.current_period
        self.holdings.loc[mask, symbol] += quantity

    def _register_transaction(self, **kwargs) -> None:
        """Register a transaction in the portfolio.

        It will always register the transaction during the current period.

        This will only register a transaction if it is valid.
        before the cash balances or holdings are updated.

        Parameters:
            **kwargs: The transaction details. Must contain the following columns:
                - type: The type of the transaction.
                  Must be one of `Portfolio.transaction_types`
                - net_cash_value: The net value of the transaction.
                  As seen from the cash balance.
            Other columns from `Portfolio.transaction_columns`
            depend on the type of the transaction.

        Raises:
            KeyError: If the transaction does not contain the required columns
            ValueError: If the transaction is invalid
                (e.g. period is present or type is not valid)
        """
        if "period" in kwargs:
            raise ValueError(
                "Remove the `period` kwarg. We will always use the current period."
            )
        transaction = kwargs
        transaction["period"] = self.current_period
        required_columns = {"period", "type", "transaction_amount"}
        if not required_columns.issubset(transaction.keys()):
            missing = required_columns - set(transaction.keys())
            raise KeyError(f"Missing required columns: {missing}")

        # Check if the transaction type is valid
        if transaction["type"] not in self.transaction_types:
            raise ValueError(f"Invalid transaction type: {transaction['type']}")

        # Check if there are any unexpected columns in the transaction
        unexpected_columns = set(transaction.keys()) - set(
            Portfolio.transaction_columns
        )
        if unexpected_columns:
            raise KeyError(f"Unexpected columns in transaction: {unexpected_columns}")

        # Concatenate the transaction to the transactions dataframe
        self.transactions = pd.concat(
            [self.transactions, pd.DataFrame([transaction]).dropna(axis=1, how="all")],
            ignore_index=True,
        )

    def advance_period(self) -> None:
        """
        Advance to the next period.

        This method is used to advance to the next period in the portfolio's history.
        It checks if the previous period is finalized and if the end of the history is
        reached. If the previous period is not finalized, it raises a RuntimeError.
        If the end of the history is reached, it raises a StopIteration.

        """
        if self._states[self.current_period] != PortfolioState.DONE:  # type: ignore[call-overload]
            raise RuntimeError("Last period was not in the DONE state.")
        if self._current_period_idx + 1 >= len(self.history.index):
            raise StopIteration("End of history reached")
        self._current_period_idx += 1
        self.current_period = self.history.index[self._current_period_idx]

    def update_history(self) -> None:
        """Update the history of the portfolio for the current period.

        This method is meant to be called after all transactions for the period
        have been processed.
        It will summarize the transactions and update the history of the portfolio.

        Notes:
            This method enforces the order of operations for updating the portfolio.
            It will only run if the portfolio is in the `PortfolioState.TRANSACT` state.
            After running, it will transition the portfolio to the `PortfolioState.DONE`
            state.
        """
        self._check_state(PortfolioState.TRANSACT)

        # get all transactoins for this period and summarize them
        period_transactions = self.transactions[
            self.transactions["period"] == self.current_period
        ]

        self.history.loc[self.current_period] = {  # type: ignore
            "cash": self.cash,
            "tax_owed": self.tax_owed,
            "long_term_gains_in_period": period_transactions["long_term_gains"].sum(),
            "short_term_gains_in_period": period_transactions["short_term_gains"].sum(),
            "taxes_paid_in_period": period_transactions["tax_paid"].sum(),
        }

        self._states[self.current_period] = PortfolioState.DONE

    def collect_income(self):
        """Collect all the income for the current period.

        This method processes the income generated by each asset in the portfolio
        for the current period. It creates a transaction for each asset holding
        that has generated income during the period.

        The method calculates the long-term and short-term income based on the
        holding period of the assets and applies the corresponding tax rates.
        It then registers the income transaction, updates the cash balance,
        and tax liability of the portfolio.

        Notes:
            If an asset has a negative income, negative income will be collected.
            No taxes paid on negative income, but it will register negative gains.
            If you are short on a position, your income will be negative!
        """
        self._check_state(PortfolioState.COLLECT_INCOME)

        symbols = (
            self.holdings.loc[self.current_period]  # type: ignore[call-overload]
            * self.asset_universe.income_matrix.loc[self.current_period]  # type: ignore[call-overload]
        )
        symbols = self.holdings.columns[symbols != 0]

        for symbol in symbols:
            # get the income
            income = self.asset_universe.income_matrix.loc[self.current_period, symbol]  # type: ignore

            # filter transactions to this symbol only buy
            tax_lots = self.transactions[
                (self.transactions["type"] == "buy")
                & (self.transactions["symbol"] == symbol)
            ]
            total_quantity = tax_lots["lot_quantity_remaining"].sum()

            # filter tax lots to those that are long-term
            earliest_long_term_period = (
                self.current_period.to_timestamp()
                - self.tax_config.long_term_holding_period
            ).to_period(self.asset_universe.data_frequency)
            long_term_quantity = tax_lots.loc[
                tax_lots["period"] <= earliest_long_term_period,
                "lot_quantity_remaining",
            ].sum()
            short_term_quantity = total_quantity - long_term_quantity

            long_term_income = long_term_quantity * income
            short_term_income = short_term_quantity * income

            tax_liability = (
                long_term_income * self.tax_config.long_term_rate
                + short_term_income * self.tax_config.short_term_rate
            )

            tax_paid = 0.0
            # If we have negative income, we don't pay any taxes
            # If we are short on a position we will also have to pay money
            if total_quantity * income < 0.0:
                tax_liability = 0.0
            elif self.tax_config.withhold_tax:
                tax_paid = tax_liability
                tax_liability = 0.0

            transaction_amount = short_term_income + long_term_income - tax_paid

            self._register_transaction(
                type="income",
                symbol=symbol,
                quantity=total_quantity,
                long_term_gains=long_term_income,
                short_term_gains=short_term_income,
                tax_paid=tax_paid,
                transaction_amount=transaction_amount,
            )

            self.tax_owed += tax_liability
            self.cash += transaction_amount

        self._states[self.current_period] = PortfolioState.TRANSACT

    def move_cash(self, amount: float):
        """Move cash in or out of the portfolio.

        Args:
            amount (float): The amount of cash to move.
                Sign indicates the direction of the transaction.
                Positive values mean a deposit into the portfolio.
                Negative values mean a withdrawal from the portfolio.

        Notes:
            This function will register a transaction in the portfolio.
        """
        self._check_state(PortfolioState.TRANSACT)

        if amount > 0:
            type = "deposit"
        elif amount < 0:
            type = "withdrawal"
        else:
            return

        self._register_transaction(
            type=type,
            transaction_amount=amount,
        )

        self.cash += amount

    def buy_asset(self, symbol: str, quantity: float):
        """
        Buy an asset in the portfolio during the current period.

        Args:
            symbol (str): The symbol of the asset to buy.
            quantity (float): The quantity of the asset to buy.
                Sign indicates the direction of the transaction.

        Raises:
            ValueError: If the quantity is not positive.

        Notes:
            This function will automatically handle the tax of the purchase.
            It will also update the cash and tax owed balances of the portfolio.
        """
        self._check_state(PortfolioState.TRANSACT)

        if quantity <= 0:
            raise ValueError("Quantity must be positive")

        price = self.asset_universe.assets[symbol].get_price_at(self.current_period)
        fee = self.fee_config.calculate_fee(quantity * price)
        cost_basis_per_share = price + fee / quantity
        transaction_amount = -(quantity * price + fee)

        self._register_transaction(
            type="buy",
            symbol=symbol,
            quantity=quantity,
            lot_quantity_remaining=quantity,
            price=price,
            fee=fee,
            cost_basis_per_share=cost_basis_per_share,
            transaction_amount=transaction_amount,
        )

        self._update_future_holdings(symbol, quantity)

        self.cash += transaction_amount

    def sell_asset(self, symbol: str, quantity: float):
        """Sell a part of an asset in the portfolio during the current period.

        It will only sell any portion of the asset that is currently held.

        Args:
            symbol (str): The symbol of the asset to sell
            quantity (float): The quantity of the asset to sell.
                Quantity must be positive.

        Notes:
            This function will automatically handle the tax implications of the sale.
            It will also update the cash and tax owed balances of the portfolio.
        """
        self._check_state(PortfolioState.TRANSACT)

        tax_lots = self.transactions[
            (self.transactions["type"] == "buy")
            & (self.transactions["symbol"] == symbol)
            & (self.transactions["lot_quantity_remaining"] > 0)
            & (self.transactions["period"] <= self.current_period)
        ]

        if self.tax_config.tax_strategy == "FIFO":
            tax_lots = tax_lots.sort_values("period")
        elif self.tax_config.tax_strategy == "LIFO":
            tax_lots = tax_lots.sort_values("period", ascending=False)
        else:
            raise ValueError(f"Invalid tax strategy: {self.tax_config.tax_strategy}")

        current_holding_quantity = tax_lots["lot_quantity_remaining"].sum()

        if quantity <= 0:
            raise ValueError("Quantity must be greater than 0")
        elif quantity > current_holding_quantity:
            raise ValueError(
                f"Quantity to sell {quantity} is greater than current holdings "
                f"{current_holding_quantity} for symbol {symbol}."
            )
        quantity_to_sell = quantity
        price = self.asset_universe.assets[symbol].get_price_at(self.current_period)
        fee = self.fee_config.calculate_fee(quantity * price)
        cost_basis_per_share = price - fee / quantity

        long_term_gains = 0
        short_term_gains = 0

        earliest_long_term_period = (
            self.current_period.to_timestamp()
            - self.tax_config.long_term_holding_period
        ).to_period(self.asset_universe.data_frequency)

        # sell tax lots until we run out of qunatity_to_sell
        for lot in tax_lots.index:
            # get the basic transaction info
            lot_quantity_remaining = self.transactions.loc[
                lot, "lot_quantity_remaining"
            ]
            transaction_period = self.transactions.loc[lot, "period"]
            lot_cost_basis_per_share = self.transactions.loc[
                lot, "cost_basis_per_share"
            ]

            lot_quantity_sold = min(quantity_to_sell, lot_quantity_remaining)
            lot_gains = lot_quantity_sold * (
                cost_basis_per_share - lot_cost_basis_per_share
            )
            # check if this is a long term transaction
            if transaction_period <= earliest_long_term_period:
                long_term_gains += lot_gains
            else:
                short_term_gains += lot_gains

            if lot_quantity_remaining <= lot_quantity_sold:
                quantity_to_sell -= lot_quantity_sold
                self.transactions.loc[lot, "lot_quantity_remaining"] = 0
            else:
                self.transactions.loc[lot, "lot_quantity_remaining"] -= (
                    lot_quantity_sold
                )
                quantity_to_sell = 0
                break

        tax_liability = (
            long_term_gains * self.tax_config.long_term_rate
            + short_term_gains * self.tax_config.short_term_rate
        )
        tax_paid = 0.0
        if tax_liability <= 0.0:
            pass
        elif self.tax_config.withhold_tax:
            tax_paid = tax_liability
            tax_liability = 0.0

        transaction_amount = quantity * price - fee - tax_paid

        self._register_transaction(
            type="sell",
            symbol=symbol,
            quantity=quantity,
            price=price,
            fee=fee,
            tax_paid=tax_paid,
            long_term_gains=long_term_gains,
            short_term_gains=short_term_gains,
            transaction_amount=transaction_amount,
        )

        # important: quantity_to_sell is negative
        self._update_future_holdings(symbol, -quantity)

        self.cash += transaction_amount
        self.tax_owed += tax_liability

    def pay_tax(self, amount: float | None = None):
        """Pay taxes owed.

        If no amount is provided, all taxes owed will be paid.

        Args:
            amount: float, optional
                The amount of taxes to pay.

        Raises:
            ValueError: If amount is greater than tax owed or negative
        """
        self._check_state(PortfolioState.TRANSACT)

        if amount is None:
            amount = self.tax_owed

        if amount > self.tax_owed:
            raise ValueError("Amount is greater than tax owed")
        elif amount < 0:
            raise ValueError("Amount is negative. That's not how tax works.")
        elif amount == 0:
            return

        self._register_transaction(
            type="pay_tax",
            transaction_amount=-amount,
        )

        self.tax_owed -= amount
        self.cash -= amount
