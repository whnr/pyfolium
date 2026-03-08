"""Synthetic benchmark for pyfolium performance profiling.

Setup: 100 assets, daily data, 50 years (~18,262 periods)
Prices: Geometric Brownian Motion (μ=8%, σ=20% annualized)
Income: Quarterly dividends (~2% yield annualized)
Strategy: Fully invest at period 1, then monthly random rebalance
    (sell 10% of 10 random holdings, buy 10 different with proceeds)
Tax: 30% short-term, 15% long-term, withholding enabled, FIFO
Fees: $1 fixed + 0.1%, min $1, max $20

Usage:
    uv run python examples/benchmark.py
"""

import time

import numpy as np
import pandas as pd

from pyfolium import (
    Asset,
    AssetUniverse,
    BacktestRunner,
    BaseStrategy,
    FeeConfig,
    Portfolio,
    TaxConfig,
)


def generate_gbm_prices(
    n_periods: int,
    n_assets: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate realistic stock prices via Geometric Brownian Motion.

    Args:
        n_periods: Number of daily periods.
        n_assets: Number of assets to generate.
        rng: Numpy random generator for reproducibility.

    Returns:
        Array of shape (n_periods, n_assets) with price paths.
    """
    mu = 0.08 / 252  # 8% annualized drift
    sigma = 0.20 / np.sqrt(252)  # 20% annualized volatility

    start_prices = rng.uniform(20, 200, size=n_assets)
    log_returns = (mu - 0.5 * sigma**2) + sigma * rng.standard_normal(
        (n_periods - 1, n_assets)
    )

    log_prices = np.zeros((n_periods, n_assets))
    log_prices[0] = np.log(start_prices)
    log_prices[1:] = np.cumsum(log_returns, axis=0) + np.log(start_prices)

    return np.exp(log_prices)


def generate_quarterly_dividends(
    n_periods: int,
    n_assets: int,
    prices: np.ndarray,
) -> np.ndarray:
    """Generate quarterly dividends at ~2% annualized yield.

    Args:
        n_periods: Number of daily periods.
        n_assets: Number of assets.
        prices: Price array for yield calculation.

    Returns:
        Array of shape (n_periods, n_assets) with dividend payments.
    """
    income = np.zeros((n_periods, n_assets))
    quarterly_interval = 63  # ~quarterly in trading days
    for t in range(0, n_periods, quarterly_interval):
        income[t] = prices[t] * 0.02 / 4  # 2% annual / 4 quarters
    return income


class RandomTraderStrategy(BaseStrategy):
    """Fully invest at period 1, then monthly random rebalance."""

    def __init__(self, portfolio: Portfolio, rng_seed: int = 42, **kwargs):
        super().__init__(portfolio, parameters={"rng_seed": rng_seed}, **kwargs)
        self._rng = np.random.default_rng(rng_seed)
        self._invested = False
        self._periods_since_rebalance = 0
        self._rebalance_interval = 21  # ~monthly

    def get_trades(self) -> list[tuple[str, float]]:
        symbols = self.portfolio.asset_universe.asset_symbols_list
        prices = self.portfolio.asset_universe.price_matrix.loc[
            self.portfolio.current_period
        ]

        if not self._invested:
            self._invested = True
            cash = self.portfolio.cash
            per_asset = cash / len(symbols) * 0.99  # 1% buffer for fees
            trades = []
            for sym in symbols:
                price = prices[sym]
                if pd.notna(price) and price > 0:
                    qty = per_asset / price
                    if qty >= 0.01:
                        trades.append((sym, qty))
            return trades

        self._periods_since_rebalance += 1
        if self._periods_since_rebalance < self._rebalance_interval:
            return []
        self._periods_since_rebalance = 0

        # Pick 10 held assets to sell 10% of
        holdings = self.portfolio.holdings.loc[self.portfolio.current_period]
        held = [s for s in symbols if holdings[s] > 0.01]
        if len(held) < 10:
            return []

        sell_symbols = list(
            self._rng.choice(held, size=min(10, len(held)), replace=False)
        )
        trades: list[tuple[str, float]] = []
        sell_value = 0.0
        for sym in sell_symbols:
            qty = holdings[sym] * 0.10
            if qty >= 0.01:
                trades.append((sym, -qty))
                price = prices[sym]
                if pd.notna(price):
                    sell_value += qty * float(price)

        # Pick 10 different assets to buy with proceeds
        buy_candidates = [s for s in symbols if s not in sell_symbols]
        if not buy_candidates:
            return trades
        buy_symbols = list(
            self._rng.choice(
                buy_candidates, size=min(10, len(buy_candidates)), replace=False
            )
        )
        per_buy = sell_value / len(buy_symbols) * 0.95  # fee buffer
        for sym in buy_symbols:
            price = prices[sym]
            if pd.notna(price) and price > 0:
                qty = per_buy / float(price)
                if qty >= 0.01:
                    trades.append((sym, qty))

        return trades


def run_benchmark() -> None:
    """Run the benchmark and print timing results."""
    rng = np.random.default_rng(42)

    n_assets = 100
    n_years = 50
    n_periods = n_years * 365 + n_years // 4  # include leap days

    print(
        f"Setting up benchmark: {n_assets} assets, {n_years} years, {n_periods} periods"
    )
    print("=" * 70)

    # --- Setup phase ---
    t0 = time.perf_counter()

    dates = pd.period_range(start="1975-01-01", periods=n_periods, freq="D")
    prices = generate_gbm_prices(n_periods, n_assets, rng)
    income = generate_quarterly_dividends(n_periods, n_assets, prices)

    universe = AssetUniverse(data_frequency="D")
    for i in range(n_assets):
        symbol = f"ASSET_{i:03d}"
        data = pd.DataFrame(
            {"price": prices[:, i], "income": income[:, i]},
            index=dates,
        )
        Asset(symbol, universe, data)

    tax_config = TaxConfig(
        short_term_rate=0.30,
        long_term_rate=0.15,
        withhold_tax=True,
        tax_strategy="FIFO",
    )
    fee_config = FeeConfig(
        fixed_fee=1.0,
        percentage_fee=0.001,
        minimum_fee=1.0,
        maximum_fee=20.0,
    )

    portfolio = Portfolio(universe, tax_config=tax_config, fee_config=fee_config)
    strategy = RandomTraderStrategy(portfolio, initial_cash=1_000_000)
    runner = BacktestRunner(portfolio, strategy)

    t_setup = time.perf_counter() - t0
    print(f"Setup time:      {t_setup:.2f}s")

    # --- Simulation phase ---
    t1 = time.perf_counter()
    result = runner.run()
    t_sim = time.perf_counter() - t1

    n_txns = len(result.portfolio.transactions)
    periods_completed = result.total_periods
    print(f"Simulation time: {t_sim:.2f}s")
    print(f"Periods:         {periods_completed}")
    print(f"Transactions:    {n_txns}")
    print(f"Periods/sec:     {periods_completed / t_sim:,.0f}")
    print(f"Final value:     ${result.portfolio.total_value:,.2f}")
    print(f"Success:         {result.success}")
    print(f"Errors:          {len(result.errors)}")
    print("=" * 70)


if __name__ == "__main__":
    run_benchmark()
