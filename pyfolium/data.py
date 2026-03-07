"""Data loading utilities for Pyfolium.

This module provides functions to load asset data from various sources
including CSV files and pandas DataFrames.
"""

from pathlib import Path

import pandas as pd


def _check_density(
    data: pd.DataFrame,
    frequency: str,
    min_density: float | None,
) -> None:
    """Validate that data density is consistent with the requested frequency.

    Computes the ratio of actual data points to the number of periods that
    would exist in a gapless range at the given frequency. A low ratio
    indicates the data was likely recorded at a coarser frequency than
    requested (e.g., monthly data loaded as daily).

    Args:
        data: DataFrame with a PeriodIndex (after dedup).
        frequency: Pandas period frequency string.
        min_density: Minimum acceptable density ratio (0.0–1.0).
            None disables the check.

    Raises:
        ValueError: If density falls below *min_density*.
    """
    if min_density is None:
        return
    if len(data) == 1:
        raise ValueError(
            "Cannot assess data density with a single observation. "
            "Provide at least two data points."
        )

    first_period = data.index.min()
    last_period = data.index.max()
    expected_range = pd.period_range(
        start=first_period, end=last_period, freq=frequency
    )
    expected_count = len(expected_range)

    if expected_count == 0:
        return

    density = len(data) / expected_count

    if density < min_density:
        raise ValueError(
            f"Data density too low: {density:.1%} of expected periods present "
            f"(threshold: {min_density:.0%}). The data has {len(data)} observations "
            f"spanning {expected_count} {frequency}-frequency periods "
            f"({first_period} to {last_period}). "
            f"This usually means the data frequency doesn't match the requested "
            f"frequency '{frequency}'. Set min_density=None to disable this check."
        )


def _build_asset_dataframe(
    data: pd.DataFrame,
    frequency: str,
    price_column: str,
    income_column: str | None,
    min_density: float | None,
) -> pd.DataFrame:
    """Build a normalised asset DataFrame from raw input.

    Validates columns, renames to canonical names ("price", "income"),
    rejects duplicate periods, and runs the density sanity check.

    Args:
        data: DataFrame with a PeriodIndex.
        frequency: Pandas period frequency string.
        price_column: Name of the column containing prices.
        income_column: Name of the column containing income/dividends.
            None to exclude income data.
        min_density: Minimum acceptable data density (0.0–1.0).
            None disables the check.

    Returns:
        DataFrame with columns "price" (and "income" if requested).

    Raises:
        ValueError: If *price_column* or an explicitly provided
            *income_column* is missing from *data*, if duplicate periods
            are found, or if density is too low.
    """
    if price_column not in data.columns:
        raise ValueError(
            f"Price column '{price_column}' not found. "
            f"Available columns: {list(data.columns)}"
        )

    result_data: dict[str, pd.Series] = {"price": data[price_column]}

    if income_column is not None:
        if income_column not in data.columns:
            raise ValueError(
                f"Income column '{income_column}' not found. "
                f"Available columns: {list(data.columns)}"
            )
        result_data["income"] = data[income_column].fillna(0.0)

    result = pd.DataFrame(result_data)

    # Reject duplicate periods — they indicate data quality issues
    duplicated = result.index.duplicated(keep=False)
    if duplicated.any():
        dup_periods = result.index[duplicated].unique().tolist()
        raise ValueError(
            f"Duplicate periods found: {dup_periods}. "
            "Input data must have unique periods."
        )

    _check_density(result, frequency, min_density)

    return result


def load_from_csv(
    file_path: str | Path,
    frequency: str,
    date_column: str = "Date",
    price_column: str = "Close",
    income_column: str | None = None,
    min_density: float | None = 0.5,
) -> pd.DataFrame:
    """Load asset data from a CSV file.

    Args:
        file_path: Path to CSV file.
        frequency: Data frequency as pandas period alias (e.g., "D", "W", "M").
        date_column: Name of column containing dates.
        price_column: Name of column containing price data.
        income_column: Name of column containing income/dividend data.
            Must exist in the CSV when provided. Set to None (default) to
            exclude income data.
        min_density: Minimum ratio of actual data points to expected periods
            in the date range (0.0–1.0). Catches frequency mismatches like
            monthly data loaded as daily. Set to None to disable.

    Returns:
        DataFrame with PeriodIndex and columns: "price" (and "income" if
        *income_column* is provided).

    Raises:
        FileNotFoundError: If *file_path* does not exist.
        ValueError: If *price_column* or *income_column* is missing from the
            CSV, or if data density is below *min_density*.

    Example:
        >>> df = load_from_csv("data/Stock.csv", frequency="D",
        ...                    income_column="Dividend")
        >>> df.head()
                    price  income
        2020-01-01  73.41    0.00
        2020-01-02  74.36    0.00
        ...
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    data = pd.read_csv(file_path)

    if data.empty:
        raise ValueError(f"CSV file is empty: {file_path}")

    # Convert to PeriodIndex
    data[date_column] = pd.to_datetime(data[date_column])
    data.index = data[date_column].dt.to_period(frequency)
    data = data.drop(columns=[date_column])

    return _build_asset_dataframe(
        data, frequency, price_column, income_column, min_density
    )


def load_from_dataframe(
    data: pd.DataFrame,
    frequency: str,
    date_column: str | None = None,
    price_column: str = "price",
    income_column: str | None = None,
    min_density: float | None = 0.5,
) -> pd.DataFrame:
    """Prepare a pandas DataFrame for use with Pyfolium Assets.

    This function converts a DataFrame to the format expected by Asset class:
    - PeriodIndex at specified frequency
    - Columns named "price" and optionally "income"

    Args:
        data: Input DataFrame with date index or date column.
        frequency: Data frequency as pandas period alias (e.g., "D", "W", "M").
        date_column: Name of column containing dates (if not using index).
        price_column: Name of column containing price data.
        income_column: Name of column containing income/dividend data.
            Must exist in the DataFrame when provided. Set to None (default)
            to exclude income data.
        min_density: Minimum ratio of actual data points to expected periods
            in the date range (0.0–1.0). Catches frequency mismatches like
            monthly data loaded as daily. Set to None to disable.

    Returns:
        DataFrame with PeriodIndex and columns: "price" (and "income" if
        *income_column* is provided).

    Raises:
        ValueError: If *date_column*, *price_column*, or *income_column* is
            missing, or if data density is below *min_density*.

    Example:
        >>> import pandas as pd
        >>> df = pd.DataFrame({
        ...     "date": pd.date_range("2020-01-01", periods=5),
        ...     "close": [100, 101, 102, 103, 104],
        ...     "div": [0, 0, 0.5, 0, 0]
        ... })
        >>> result = load_from_dataframe(df, frequency="D", date_column="date",
        ...                              price_column="close", income_column="div")
    """
    data = data.copy()

    # Handle date column or index
    if date_column is not None:
        if date_column not in data.columns:
            raise ValueError(f"Date column '{date_column}' not found in DataFrame")
        data[date_column] = pd.to_datetime(data[date_column])
        data.index = data[date_column].dt.to_period(frequency)
        data = data.drop(columns=[date_column])
    else:
        # Assume index is already datetime-like
        if not isinstance(data.index, pd.PeriodIndex):
            data.index = pd.to_datetime(data.index).to_period(frequency)

    return _build_asset_dataframe(
        data, frequency, price_column, income_column, min_density
    )
