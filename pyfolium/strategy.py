from abc import ABC, abstractmethod

import pandas as pd

from .core import Portfolio


class BaseStrategy(ABC):
    """Abstract base class for all trading strategies

    Attributes:
        portfolio: The portfolio this strategy manages
        asset_universe: The universe of tradeable assets
        parameters: Dictionary of strategy-specific parameters
        trades_df: DataFrame tracking all attempted trades
    """

    def __init__(self, portfolio: Portfolio, parameters: dict | None = None):
        self.portfolio = portfolio
        self.asset_universe = portfolio.asset_universe
        self.parameters = parameters or {}

        # Track all trade attempts and their execution
        self.trades_df = pd.DataFrame(
            index=pd.Index([], name="trade_id"),
            columns=[
                "period",
                "symbol",
                "quantity",
                "executed_quantity",
                "category",  # strategy-specific trade categorization
                "success",
            ],
        )

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
        """Record trade attempt in trades_df"""
        self.trades_df.loc[len(self.trades_df)] = {  # type: ignore
            "period": self.portfolio.current_period,
            "symbol": symbol,
            "quantity": desired_quantity,
            "executed_quantity": executed_quantity,
            "category": category,
            "success": success,
        }

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
