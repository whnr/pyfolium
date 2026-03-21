from abc import ABC, abstractmethod
from time import monotonic
from typing import Any

import pandas as pd

from .core import Portfolio, TaxLot
from .logging import LogEntry, Severity


class BaseStrategy(ABC):
    """Abstract base class for all trading strategies

    Attributes:
        portfolio: The portfolio this strategy manages
        asset_universe: The universe of tradeable assets
        parameters: Dictionary of strategy-specific parameters
        trades_df: DataFrame tracking all attempted trades
        initial_cash: Cash to inject via move_cash() at the start of the first
            backtest period, or None if no injection is desired.
        start_period: The first period this strategy should run from, used as
            a fallback when BacktestRunner has no explicit start_period, or
            None to defer to the runner's own default.
    """

    def __init__(
        self,
        portfolio: Portfolio,
        parameters: dict | None = None,
        *,
        initial_cash: float | None = None,
        start_period: pd.Period | None = None,
    ):
        """Initialize the strategy.

        Args:
            portfolio: The portfolio this strategy will manage.
            parameters: Optional dictionary of strategy-specific parameters.
            initial_cash: Cash amount to inject via move_cash() at the start of
                the first period. Injection happens after collect_income()
                (TRANSACT state) and before the strategy's first get_trades()
                call. Defaults to None (no injection).
            start_period: The period from which this strategy should begin.
                BacktestRunner uses this when its own start_period is None.
                Defaults to None.
        """
        self.portfolio = portfolio
        self.asset_universe = portfolio.asset_universe
        self.parameters = parameters or {}
        self.initial_cash = initial_cash
        self.start_period = start_period

        # Structured log — drained by BacktestRunner after each step()
        self._log: list[LogEntry] = []

        # Track all trade attempts and their execution
        self._trades_buffer: list[dict] = []
        self._trades_df_cache: pd.DataFrame | None = None

    @property
    def trades_df(self) -> pd.DataFrame:
        """DataFrame of all trade attempts (built lazily from internal buffer)."""
        if self._trades_df_cache is None:
            if not self._trades_buffer:
                self._trades_df_cache = pd.DataFrame(
                    columns=[
                        "period",
                        "symbol",
                        "quantity",
                        "executed_quantity",
                        "category",
                        "success",
                    ],
                )
            else:
                self._trades_df_cache = pd.DataFrame(self._trades_buffer)
        return self._trades_df_cache

    def log(
        self,
        severity: Severity,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Record a log entry from within the strategy.

        Call this from ``get_trades()`` to capture strategy reasoning,
        debug information, or warnings. Entries are drained into the
        runner's log after each ``step()`` call.

        Args:
            severity: Importance level of the log entry.
            message: Human-readable description.
            data: Optional structured payload (e.g. trade details).
        """
        self._log.append(
            LogEntry(
                severity=severity,
                timestamp=monotonic(),
                period=self.portfolio.current_period,
                source="strategy",
                message=message,
                data=data,
            )
        )

    def get_price(self, symbol: str) -> float:
        """Current-period price for a single asset.

        Args:
            symbol: The asset symbol to look up.

        Returns:
            The asset's price at ``portfolio.current_period``.
        """
        return float(
            self.asset_universe.price_matrix.loc[
                self.portfolio.current_period, symbol
            ]
        )

    def get_prices(self) -> pd.Series:
        """All asset prices for the current period.

        Returns:
            A Series indexed by symbol with prices at
            ``portfolio.current_period``.
        """
        return self.asset_universe.price_matrix.loc[self.portfolio.current_period]

    def get_lots(self, symbol: str) -> list[TaxLot]:
        """Open tax lots for a symbol.

        Convenience wrapper around ``portfolio.open_lots``. Returns an
        empty list when the symbol has no open positions.

        Args:
            symbol: The asset symbol to look up.

        Returns:
            List of open ``TaxLot`` instances (quantity_remaining > 0).
        """
        return self.portfolio.open_lots.get(symbol, [])

    @abstractmethod
    def get_trades(self) -> list[tuple[str, float]]:
        """Generate list of desired trades for the current period

        Returns:
            List of (symbol, quantity) tuples representing desired trades
            Positive quantity for buys, negative for sells
        """
        pass

    def _record_trade(
        self,
        symbol: str,
        desired_quantity: float,
        executed_quantity: float,
        category: str = "",
        success: bool = True,
    ) -> None:
        """Record trade attempt in trades_df."""
        self._trades_buffer.append(
            {
                "period": self.portfolio.current_period,
                "symbol": symbol,
                "quantity": desired_quantity,
                "executed_quantity": executed_quantity,
                "category": category,
                "success": success,
            }
        )
        self._trades_df_cache = None

    def execute_trades(self, trades: list[tuple[str, float]]) -> None:
        """Execute a list of trades in the portfolio"""
        for symbol, quantity in trades:
            try:
                if quantity > 0:
                    self.portfolio.buy_asset(symbol, quantity)
                    self._record_trade(symbol, quantity, quantity)
                elif quantity < 0:
                    self.portfolio.sell_asset(symbol, abs(quantity))
                    self._record_trade(symbol, quantity, quantity)
            except ValueError:
                self._record_trade(symbol, quantity, 0, success=False)
                continue

    def step(self) -> None:
        """Execute one step of the strategy"""
        trades = self.get_trades()
        self.execute_trades(trades)
