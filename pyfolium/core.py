from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field, field_validator


@dataclass(frozen=True, slots=True)
class TaxResult:
    """Result of a tax calculation.

    Attributes:
        tax_liability: Amount added to ``tax_owed`` (may be negative for losses).
        tax_paid: Amount withheld from cash (0 when not withholding or on losses).
    """

    tax_liability: float
    tax_paid: float


class TaxConfig(BaseModel):
    """Configuration for tax calculations with validation.

    This config uses Pydantic for automatic validation of tax rates and strategies.
    Calculation methods can be overridden in subclasses for custom tax rules
    (e.g. wash sales, jurisdiction-specific logic).

    Attributes:
        short_term_rate: Tax rate for short-term capital gains (0.0 to 1.0)
        long_term_holding_period: Period to qualify for long-term gains
        long_term_rate: Tax rate for long-term capital gains (0.0 to 1.0)
        withhold_tax: Whether to withhold tax immediately on gains
        tax_strategy: Tax lot selection strategy ("FIFO", "LIFO", or "AVERAGE")
        allow_specific_lot: Whether sell_lot() is permitted (False by default).
            Set to True for jurisdictions that allow specific lot identification
            (e.g. US IRS specific identification method).

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
    tax_strategy: str = Field(default="FIFO", pattern="^(FIFO|LIFO|AVERAGE)$")
    allow_specific_lot: bool = False

    model_config = {"arbitrary_types_allowed": True}  # Allow pd.DateOffset

    def long_term_cutoff_period(
        self,
        current_period: pd.Period,
        data_frequency: str,
    ) -> pd.Period:
        """Compute the earliest period that qualifies as long-term.

        A lot purchased on or before this period is classified as long-term.

        Args:
            current_period: The period of the sale or income event.
            data_frequency: Frequency string (e.g. ``'D'``, ``'M'``).

        Returns:
            The cutoff period. Lots with ``period <= cutoff`` are long-term.
        """
        return (
            current_period.to_timestamp() - self.long_term_holding_period
        ).to_period(data_frequency)

    def classify_gain(
        self,
        purchase_period: pd.Period,
        current_period: pd.Period,
        data_frequency: str,
    ) -> str:
        """Classify a gain as short-term or long-term based on holding period.

        Args:
            purchase_period: When the lot was acquired.
            current_period: When the sale or income event occurs.
            data_frequency: Frequency string for Period conversion.

        Returns:
            ``"long_term"`` if held long enough, otherwise ``"short_term"``.
        """
        cutoff = self.long_term_cutoff_period(current_period, data_frequency)
        if purchase_period <= cutoff:
            return "long_term"
        return "short_term"

    def calculate_tax(
        self,
        short_term_gains: float,
        long_term_gains: float,
    ) -> TaxResult:
        """Calculate tax liability and withholding for given gains.

        Applies ``short_term_rate`` and ``long_term_rate`` to the respective
        gains. If ``withhold_tax`` is ``True`` and the liability is positive,
        the full liability is withheld (paid immediately).

        Args:
            short_term_gains: Total short-term capital gains or income.
            long_term_gains: Total long-term capital gains or income.

        Returns:
            A :class:`TaxResult` with ``tax_liability`` and ``tax_paid``.
        """
        raw_liability = (
            long_term_gains * self.long_term_rate
            + short_term_gains * self.short_term_rate
        )
        if raw_liability <= 0.0:
            return TaxResult(tax_liability=raw_liability, tax_paid=0.0)
        if self.withhold_tax:
            return TaxResult(tax_liability=0.0, tax_paid=raw_liability)
        return TaxResult(tax_liability=raw_liability, tax_paid=0.0)

    def select_lots(self, lots: list["TaxLot"]) -> list["TaxLot"]:
        """Return open lots ordered by the configured tax strategy.

        Args:
            lots: All lots for a given symbol (open and closed).

        Returns:
            A new list containing only open lots, sorted by the tax strategy
            (FIFO: ascending by period, LIFO: descending by period).

        Raises:
            ValueError: If ``tax_strategy`` is not recognized.
        """
        open_lots = [lot for lot in lots if lot.is_open]
        if self.tax_strategy in ("FIFO", "AVERAGE"):
            open_lots.sort(key=lambda lot: lot.period)
        elif self.tax_strategy == "LIFO":
            open_lots.sort(key=lambda lot: lot.period, reverse=True)
        else:
            raise ValueError(f"Invalid tax strategy: {self.tax_strategy}")
        return open_lots

    def effective_cost_basis(
        self,
        lot: "TaxLot",
        all_open_lots: list["TaxLot"],
    ) -> float:
        """Return the cost basis per share to use for gain calculation.

        For FIFO/LIFO, this is the lot's own ``cost_basis_per_share``.
        For AVERAGE, this is the weighted average cost across all open lots
        for the symbol, computed at the time of sale.

        Args:
            lot: The specific lot being sold.
            all_open_lots: All open lots for the same symbol.

        Returns:
            The effective cost basis per share.
        """
        if self.tax_strategy != "AVERAGE":
            return lot.cost_basis_per_share
        total_quantity = sum(ol.quantity_remaining for ol in all_open_lots)
        if total_quantity == 0:
            return lot.cost_basis_per_share
        return (
            sum(ol.quantity_remaining * ol.cost_basis_per_share for ol in all_open_lots)
            / total_quantity
        )


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

    def calculate_fee(
        self,
        transaction_value: float,
        *,
        symbol: str | None = None,
        quantity: float | None = None,
        transaction_type: str | None = None,
    ) -> float:
        """Calculate the fee for a given transaction value.

        The default implementation uses fixed + percentage fees with min/max
        caps. Subclasses can override this method and use the keyword-only
        context parameters to implement tiered commissions, per-asset fee
        schedules, or buy/sell-asymmetric pricing.

        Args:
            transaction_value: Absolute value of the transaction.
            symbol: Asset symbol being traded.
            quantity: Number of shares/units in the trade.
            transaction_type: ``"buy"`` or ``"sell"``.

        Returns:
            Fee amount bounded by minimum_fee and maximum_fee.
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
        asset_universe (AssetUniverse): The asset universe that the asset will be
            added to.
        data (pd.DataFrame): The data must have a period index.
            The frequency of the data must match the data_frequency of the
            asset_universe.
        metadata (Dict[str, str], optional): Additional metadata of the asset.
        price_column (str): The name of the column containing the price of the
            asset."""

    def __init__(
        self,
        symbol: str,
        asset_universe: "AssetUniverse",
        data: pd.DataFrame,
        price_column: str = "price",
        income_column: str | None = None,
        metadata: dict[str, str] | None = None,
    ):
        """Initialize an Asset and register it with the given AssetUniverse.

        Args:
            symbol: Ticker or identifier for this asset.
            asset_universe: Universe this asset belongs to; the asset
                auto-registers itself on construction.
            data: DataFrame with a PeriodIndex at the universe's data
                frequency. Must contain a price column with no NaN values.
            price_column: Column name for prices. Defaults to "price".
            income_column: Column name for income/dividends. If None, an
                all-zero income column named "income" is created automatically.
            metadata: Optional dictionary of arbitrary string metadata.

        Raises:
            ValueError: If price_column is missing from data, data lacks a
                PeriodIndex, the index frequency mismatches the universe, the
                index is non-monotonic or non-unique, or the price column
                contains NaN values.
        """
        self.symbol = symbol
        self.asset_universe = asset_universe
        self.data = data.copy()
        self.price_column = price_column
        self.metadata = metadata

        if self.price_column not in self.data.columns:
            raise ValueError(f"Column {self.price_column} not in data")

        if not isinstance(self.data.index, pd.PeriodIndex):
            raise ValueError("Data must have a period index")

        if self.data.index.freqstr != self.asset_universe.data_frequency:
            raise ValueError(
                f"Data frequency of {self.data.index.freqstr} "
                f"does not match data_frequency of {self.asset_universe.data_frequency}"
            )

        if not self.data.index.is_monotonic_increasing or not self.data.index.is_unique:
            raise ValueError(
                f"Period index of asset with symbol {self.symbol} "
                "is not strictly monotonic"
            )

        if self.data[self.price_column].isna().any():
            raise ValueError(
                f"Price column '{self.price_column}' of asset '{self.symbol}' "
                "contains NaN values. Provide clean price data for all declared "
                "periods."
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
        self.asset_universe.add_asset(self)

    def __repr__(self) -> str:
        price_min = self.data[self.price_column].min()
        price_max = self.data[self.price_column].max()
        n_periods = len(self.data)
        has_income = bool(self.data[self.income_column].any())
        income_flag = "yes" if has_income else "no"
        return (
            f"Asset({self.symbol} | {self.start_time} → {self.end_time} | "
            f"{n_periods} periods | price: {price_min:.2f}–{price_max:.2f} | "
            f"income: {income_flag})"
        )

    @property
    def price(self):
        return self.data[self.price_column]

    @property
    def income(self):
        return self.data[self.income_column]


class AssetUniverse:
    def __init__(self, data_frequency: str):
        """Initialize an empty AssetUniverse.

        Args:
            data_frequency: Pandas period frequency string shared by all
                assets in this universe (e.g. "D" for daily, "M" for
                monthly). Every asset added must use the same frequency.
        """
        self.data_frequency = data_frequency
        self.assets: dict[str, Asset] = {}
        self.price_matrix: pd.DataFrame = pd.DataFrame()
        self.income_matrix: pd.DataFrame = pd.DataFrame()
        self.empty = True
        self._price_matrix_ffill: pd.DataFrame | None = None

    def __repr__(self) -> str:
        if self.empty:
            return f"AssetUniverse(freq={self.data_frequency} | empty)"
        periods = self.get_period_index_range()
        symbols = self.asset_symbols_list
        symbol_str = ", ".join(symbols[:3])
        if len(symbols) > 3:
            symbol_str += ", ..."
        return (
            f"AssetUniverse(freq={self.data_frequency} | {len(self.assets)} assets: "
            f"{symbol_str} | {periods[0]} → {periods[-1]} | {len(periods)} periods)"
        )

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

        # Invalidate the ffill cache since the price matrix changed
        self._price_matrix_ffill = None

        # Finally flag that the universe is not empty anymore
        self.empty = False

    @property
    def price_matrix_ffill(self) -> pd.DataFrame:
        """Forward-filled price matrix, computed lazily on first access.

        Fills intra-life gaps (e.g. market holidays) forward using the most
        recent prior valid price. Does NOT fill past each asset's end_time —
        those periods remain NaN, because the asset no longer exists there.
        The result is cached and recomputed only when new assets are added.

        Returns:
            DataFrame with the same shape as price_matrix where intra-life
            NaN values are replaced by the most recent prior valid price, and
            post-termination periods (after each asset's end_time) are NaN.
        """
        if self._price_matrix_ffill is None:
            filled = self.price_matrix.ffill()
            for symbol, asset in self.assets.items():
                mask = filled.index > asset.end_time
                filled.loc[mask, symbol] = float("nan")
            self._price_matrix_ffill = filled
        return self._price_matrix_ffill

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


@dataclass(slots=True)
class TaxLot:
    """A single tax lot created by a purchase transaction.

    Each call to ``buy_asset()`` creates one TaxLot. As shares are sold,
    ``quantity_remaining`` is decremented. A lot with
    ``quantity_remaining == 0`` is fully closed.

    Attributes:
        symbol: Asset symbol this lot belongs to.
        period: Period when the lot was created (purchase date).
        quantity: Original quantity purchased.
        quantity_remaining: Shares not yet sold.
        cost_basis_per_share: Per-share cost including fees.
        txn_index: Index into the portfolio transaction buffer.
    """

    symbol: str
    period: pd.Period
    quantity: float
    quantity_remaining: float
    cost_basis_per_share: float
    txn_index: int

    @property
    def is_open(self) -> bool:
        """True if this lot still has unsold shares."""
        return self.quantity_remaining > 0


class PortfolioState(Enum):
    COLLECT_INCOME = "COLLECT_INCOME"
    TRANSACT = "TRANSACT"
    DONE = "DONE"


class PriceMode(Enum):
    STRICT = "strict"
    LAST_VALID = "last_valid"


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
        """Initialize a Portfolio backed by the given AssetUniverse.

        Args:
            asset_universe: Universe containing all tradeable assets. Must be
                non-empty; add all assets before constructing the portfolio.
            fee_config: Transaction fee configuration. Defaults to
                FeeConfig() (no fees).
            tax_config: Tax calculation configuration. Defaults to
                TaxConfig() (no taxes).

        Raises:
            ValueError: If asset_universe is empty.

        Notes:
            Portfolio starts at the first period in the universe with 0 cash.
            Operations must follow the state machine order each period:
            collect_income → transact (buy/sell/move_cash) → update_history.
            Cash balances are not validated; you are responsible for ensuring
            sufficient funds before executing transactions.
        """
        self.asset_universe = asset_universe
        if self.asset_universe.empty:
            raise ValueError(
                "Asset universe is empty. "
                "All assets must be added before initializing the portfolio."
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
        self.history = self.history.astype(float)

        # Transaction buffer: list of dicts with O(1) append.
        # DataFrame is built lazily via the .transactions property.
        # Schema defined by Portfolio.transaction_columns; not all keys
        # are present in every entry (e.g. deposits lack "symbol").
        self._txn_buffer: list[dict[str, Any]] = []
        self._txn_period_index: dict[pd.Period, list[int]] = {}
        self._tax_lots: dict[str, list[TaxLot]] = {}
        self._txn_df_cache: pd.DataFrame | None = None

        self.holdings = pd.DataFrame(
            data=0.0, index=period_index, columns=self.asset_universe.asset_symbols_list
        )

        # initialize the portfolio state tracker
        self._states = pd.Series(index=period_index, data=PortfolioState.COLLECT_INCOME)

    def __repr__(self) -> str:
        state = self._states[self.current_period]  # type: ignore[call-overload]
        state_label = state.value if isinstance(state, PortfolioState) else str(state)
        holdings_now = self.holdings.loc[self.current_period]  # type: ignore[call-overload]
        active = holdings_now[holdings_now != 0]
        if active.empty:
            holdings_str = "none"
        else:
            holdings_str = ", ".join(f"{sym}:{qty:g}" for sym, qty in active.items())
        try:
            tv = self.get_total_value()
            total_str = f"total≈{tv:,.2f}"
        except Exception:
            total_str = "total=N/A"
        return (
            f"Portfolio(period={self.current_period} [{state_label}] | "
            f"cash={self.cash:,.2f} | holdings: {holdings_str} | {total_str})"
        )

    @property
    def transactions(self) -> pd.DataFrame:
        """Transaction log as a DataFrame (built lazily from internal buffer).

        Returns a DataFrame with the same schema as ``transaction_columns``.
        The DataFrame is cached and rebuilt only when new transactions are
        registered.
        """
        if self._txn_df_cache is None:
            if not self._txn_buffer:
                df = pd.DataFrame(columns=list(Portfolio.transaction_columns.keys()))
                df = df.astype(Portfolio.transaction_columns)  # type: ignore[arg-type]
                df["period"] = df["period"].astype(
                    pd.PeriodDtype(freq=self.asset_universe.data_frequency)
                )
                self._txn_df_cache = df
            else:
                df = pd.DataFrame(self._txn_buffer)
                # Ensure all schema columns exist (dicts may omit optional fields)
                for col in Portfolio.transaction_columns:
                    if col not in df.columns:
                        df[col] = None
                self._txn_df_cache = df[list(Portfolio.transaction_columns.keys())]
        return self._txn_df_cache

    @property
    def open_lots(self) -> dict[str, list[TaxLot]]:
        """Open tax lots grouped by symbol.

        Returns only lots with ``quantity_remaining > 0``.  Useful for
        strategies that need to inspect lot-level positions (e.g. for
        tax-loss harvesting).
        """
        return {
            symbol: [lot for lot in lots if lot.is_open]
            for symbol, lots in self._tax_lots.items()
        }

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

        # Deep copy DataFrames and buffer structures
        cloned.history = self.history.copy(deep=True)
        cloned._txn_buffer = deepcopy(self._txn_buffer)
        cloned._txn_period_index = deepcopy(self._txn_period_index)
        cloned._tax_lots = deepcopy(self._tax_lots)
        cloned._txn_df_cache = None
        cloned.holdings = self.holdings.copy(deep=True)
        cloned._states = self._states.copy(deep=True)

        return cloned

    def get_total_value(self, price_mode: PriceMode = PriceMode.LAST_VALID) -> float:
        """Compute total portfolio value (cash + equity) at the current period.

        Args:
            price_mode: How to resolve prices for held assets.
                PriceMode.LAST_VALID (default) uses the forward-filled price
                matrix, so the most recent available price is used even when
                today's price is NaN for a data gap. Not forward-filled after
                the end_time of an asset.
                PriceMode.STRICT uses the raw price matrix; if any held asset
                has no price for the current period, returns float("nan").

        Returns:
            Total portfolio value as cash + equity, or float("nan") if the
            equity cannot be computed (only possible in STRICT mode) or
            if an asset is held past its end_time.
        """
        idx = self._current_period_idx
        holdings = self.holdings.iloc[idx]
        if price_mode == PriceMode.LAST_VALID:
            prices = self.asset_universe.price_matrix_ffill.iloc[idx]
            equity = float((holdings * prices).sum(skipna=False))
        else:
            prices = self.asset_universe.price_matrix.iloc[idx]
            equity = float((holdings * prices).sum(skipna=False))
        if pd.isna(equity):
            return float("nan")
        return float(self.cash + equity)

    @property
    def total_value(self) -> float:
        """Total portfolio value using last-valid (forward-filled) prices.

        Convenience property equivalent to ``get_total_value(PriceMode.LAST_VALID)``.
        Use ``get_total_value(PriceMode.STRICT)`` to get NaN when today's price
        data is missing for any held position.

        Returns:
            Cash plus equity valued at the most recent available prices.
        """
        return self.get_total_value()

    def _check_state(self, expected_state: PortfolioState) -> None:
        current_state = self._states.iloc[self._current_period_idx]
        if current_state != expected_state:
            raise RuntimeError(
                f"Portfolio is in the wrong state: {current_state.value}. "
                f"Expected state: {expected_state.value}"
            )

    def _register_transaction(self, **kwargs) -> int:
        """Register a transaction in the portfolio.

        It will always register the transaction during the current period.

        This will only register a transaction if it is valid,
        before the cash balances or holdings are updated.

        Parameters:
            **kwargs: The transaction details. Must contain the following columns:
                - type: The type of the transaction.
                  Must be one of `Portfolio.transaction_types`
                - transaction_amount: The net cash flow of the transaction.
            Other columns from `Portfolio.transaction_columns`
            depend on the type of the transaction.

        Returns:
            Index of the new transaction in the internal buffer.

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

        if transaction["type"] not in self.transaction_types:
            raise ValueError(f"Invalid transaction type: {transaction['type']}")

        unexpected_columns = set(transaction.keys()) - set(
            Portfolio.transaction_columns
        )
        if unexpected_columns:
            raise KeyError(f"Unexpected columns in transaction: {unexpected_columns}")

        idx = len(self._txn_buffer)
        self._txn_buffer.append(transaction)
        self._txn_period_index.setdefault(self.current_period, []).append(idx)
        self._txn_df_cache = None

        return idx

    def advance_period(self) -> None:
        """
        Advance to the next period.

        This method is used to advance to the next period in the portfolio's history.
        It checks if the previous period is finalized and if the end of the history is
        reached. If the previous period is not finalized, it raises a RuntimeError.
        If the end of the history is reached, it raises a StopIteration.

        """
        if self._states.iloc[self._current_period_idx] != PortfolioState.DONE:
            raise RuntimeError("Last period was not in the DONE state.")
        if self._current_period_idx + 1 >= len(self.history.index):
            raise StopIteration("End of history reached")
        prev_idx = self._current_period_idx
        self._current_period_idx += 1
        self.current_period = self.history.index[self._current_period_idx]
        # Carry forward holdings from the completed period (iloc avoids label lookup)
        self.holdings.iloc[self._current_period_idx] = self.holdings.iloc[prev_idx]

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

        indices = self._txn_period_index.get(self.current_period, [])
        long_term_gains = sum(
            self._txn_buffer[i].get("long_term_gains", 0) or 0 for i in indices
        )
        short_term_gains = sum(
            self._txn_buffer[i].get("short_term_gains", 0) or 0 for i in indices
        )
        taxes_paid = sum(self._txn_buffer[i].get("tax_paid", 0) or 0 for i in indices)

        self.history.iloc[self._current_period_idx] = [
            self.cash,
            self.tax_owed,
            long_term_gains,
            short_term_gains,
            taxes_paid,
        ]

        self._states.iloc[self._current_period_idx] = PortfolioState.DONE

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

        idx = self._current_period_idx
        income_this_period = self.asset_universe.income_matrix.iloc[idx].fillna(0)
        current_holdings = self.holdings.iloc[idx]
        symbols = self.holdings.columns[(current_holdings * income_this_period) != 0]

        cutoff = self.tax_config.long_term_cutoff_period(
            self.current_period, self.asset_universe.data_frequency
        )

        for symbol in symbols:
            income = income_this_period[symbol]

            lots = self._tax_lots.get(symbol, [])
            total_quantity = sum(lot.quantity_remaining for lot in lots)
            long_term_quantity = sum(
                lot.quantity_remaining for lot in lots if lot.period <= cutoff
            )
            short_term_quantity = total_quantity - long_term_quantity

            long_term_income = long_term_quantity * income
            short_term_income = short_term_quantity * income

            if total_quantity * income < 0.0:
                tax_result = TaxResult(tax_liability=0.0, tax_paid=0.0)
            else:
                tax_result = self.tax_config.calculate_tax(
                    short_term_income, long_term_income
                )

            transaction_amount = (
                short_term_income + long_term_income - tax_result.tax_paid
            )

            self._register_transaction(
                type="income",
                symbol=symbol,
                quantity=total_quantity,
                long_term_gains=long_term_income,
                short_term_gains=short_term_income,
                tax_paid=tax_result.tax_paid,
                transaction_amount=transaction_amount,
            )

            self.tax_owed += tax_result.tax_liability
            self.cash += transaction_amount

        self._states.iloc[self._current_period_idx] = PortfolioState.TRANSACT

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
            txn_type = "deposit"
        elif amount < 0:
            txn_type = "withdrawal"
        else:
            return

        self._register_transaction(
            type=txn_type,
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

        col_idx = self.holdings.columns.get_loc(symbol)
        raw_price = self.asset_universe.price_matrix.iloc[
            self._current_period_idx, col_idx  # type: ignore[call-overload]
        ]
        if pd.isna(raw_price):  # type: ignore[arg-type]
            raise ValueError(
                f"Cannot buy {symbol} at {self.current_period}: "
                "no price data for this period"
            )
        price = float(raw_price)  # type: ignore[arg-type]
        fee = self.fee_config.calculate_fee(
            quantity * price,
            symbol=symbol,
            quantity=quantity,
            transaction_type="buy",
        )
        cost_basis_per_share = price + fee / quantity
        transaction_amount = -(quantity * price + fee)

        txn_idx = self._register_transaction(
            type="buy",
            symbol=symbol,
            quantity=quantity,
            lot_quantity_remaining=quantity,
            price=price,
            fee=fee,
            cost_basis_per_share=cost_basis_per_share,
            transaction_amount=transaction_amount,
        )

        lot = TaxLot(
            symbol=symbol,
            period=self.current_period,
            quantity=quantity,
            quantity_remaining=quantity,
            cost_basis_per_share=cost_basis_per_share,
            txn_index=txn_idx,
        )
        self._tax_lots.setdefault(symbol, []).append(lot)

        self.holdings.iloc[self._current_period_idx, col_idx] += quantity  # type: ignore[operator]

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

        lots = self._tax_lots.get(symbol, [])
        open_lots = self.tax_config.select_lots(lots)

        current_holding_quantity = sum(lot.quantity_remaining for lot in open_lots)

        if quantity <= 0:
            raise ValueError("Quantity must be greater than 0")
        elif quantity > current_holding_quantity:
            raise ValueError(
                f"Quantity to sell {quantity} is greater than current holdings "
                f"{current_holding_quantity} for symbol {symbol}."
            )

        # Build lot-quantity pairs in FIFO/LIFO order
        lots_to_sell: list[tuple[TaxLot, float]] = []
        remaining = quantity
        for lot in open_lots:
            take = min(remaining, lot.quantity_remaining)
            lots_to_sell.append((lot, take))
            remaining -= take
            if remaining <= 0:
                break

        self._execute_lot_sales(symbol, lots_to_sell, quantity)

    def sell_lot(self, lot: TaxLot, quantity: float) -> None:
        """Sell shares from a specific tax lot.

        Unlike ``sell_asset()`` which consumes lots in FIFO/LIFO order,
        this method targets a single lot chosen by the caller. This enables
        tax-loss harvesting and other tax-optimized strategies.

        Args:
            lot: The TaxLot to sell from. Must be an open lot belonging
                to this portfolio (obtained via ``open_lots``).
            quantity: Number of shares to sell. Must be positive and
                at most ``lot.quantity_remaining``.

        Raises:
            RuntimeError: If portfolio is not in TRANSACT state.
            ValueError: If quantity is invalid, lot is closed, or lot
                does not belong to this portfolio.
        """
        self._check_state(PortfolioState.TRANSACT)

        if not self.tax_config.allow_specific_lot:
            raise ValueError(
                "Tax configuration does not allow specific lot identification. "
                "Use sell_asset() instead, which respects the configured "
                f"{self.tax_config.tax_strategy} ordering."
            )

        if quantity <= 0:
            raise ValueError("Quantity must be greater than 0")

        if not lot.is_open:
            raise ValueError(
                f"Lot for {lot.symbol} (period={lot.period}) is closed; "
                "no shares remain to sell."
            )

        owned_lots = self._tax_lots.get(lot.symbol, [])
        if not any(lot is existing for existing in owned_lots):
            raise ValueError(
                "Lot does not belong to this portfolio. "
                "Use portfolio.open_lots to obtain lot references."
            )

        if quantity > lot.quantity_remaining:
            raise ValueError(
                f"Quantity {quantity} exceeds lot's remaining shares "
                f"{lot.quantity_remaining}."
            )

        self._execute_lot_sales(lot.symbol, [(lot, quantity)], quantity)

    def _execute_lot_sales(
        self,
        symbol: str,
        lots_to_sell: list[tuple[TaxLot, float]],
        total_quantity: float,
    ) -> None:
        """Shared implementation for sell_asset and sell_lot.

        Handles price lookup, fee calculation, gain classification,
        tax withholding, transaction registration, and portfolio updates.

        Args:
            symbol: Asset symbol being sold.
            lots_to_sell: Pairs of (lot, quantity_from_this_lot).
            total_quantity: Total shares being sold across all lots.
        """
        col_idx = self.holdings.columns.get_loc(symbol)
        raw_price = self.asset_universe.price_matrix.iloc[
            self._current_period_idx, col_idx  # type: ignore[call-overload]
        ]
        if pd.isna(raw_price):  # type: ignore[arg-type]
            raise ValueError(
                f"Cannot sell {symbol} at {self.current_period}: "
                "no price data for this period"
            )
        price = float(raw_price)  # type: ignore[arg-type]
        fee = self.fee_config.calculate_fee(
            total_quantity * price,
            symbol=symbol,
            quantity=total_quantity,
            transaction_type="sell",
        )
        sell_basis_per_share = price - fee / total_quantity

        long_term_gains = 0.0
        short_term_gains = 0.0

        cutoff = self.tax_config.long_term_cutoff_period(
            self.current_period, self.asset_universe.data_frequency
        )

        # Snapshot open lots before the loop mutates quantity_remaining.
        # For AVERAGE cost basis, the average is computed once at sale time.
        all_open_lots = [ol for ol in self._tax_lots.get(symbol, []) if ol.is_open]

        for lot, lot_quantity_sold in lots_to_sell:
            cost_basis = self.tax_config.effective_cost_basis(lot, all_open_lots)
            lot_gains = lot_quantity_sold * (sell_basis_per_share - cost_basis)

            if lot.period <= cutoff:
                long_term_gains += lot_gains
            else:
                short_term_gains += lot_gains

            lot.quantity_remaining -= lot_quantity_sold
            self._txn_buffer[lot.txn_index]["lot_quantity_remaining"] = (
                lot.quantity_remaining
            )
            self._txn_df_cache = None

        tax_result = self.tax_config.calculate_tax(short_term_gains, long_term_gains)
        tax_paid = tax_result.tax_paid

        transaction_amount = total_quantity * price - fee - tax_paid

        self._register_transaction(
            type="sell",
            symbol=symbol,
            quantity=total_quantity,
            price=price,
            fee=fee,
            tax_paid=tax_paid,
            long_term_gains=long_term_gains,
            short_term_gains=short_term_gains,
            transaction_amount=transaction_amount,
        )

        self.holdings.iloc[self._current_period_idx, col_idx] -= total_quantity  # type: ignore[operator]

        self.cash += transaction_amount
        self.tax_owed += tax_result.tax_liability

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
