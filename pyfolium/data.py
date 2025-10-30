"""Data loading utilities for Pyfolium.

This module provides functions to load asset data from various sources
including CSV files and pandas DataFrames.
"""

from pathlib import Path

import pandas as pd


def load_from_csv(
    file_path: str | Path,
    frequency: str,
    date_column: str = "Date",
    price_column: str = "Close",
    income_column: str | None = "Dividend",
) -> pd.DataFrame:
    """Load asset data from a CSV file.

    Args:
        file_path: Path to CSV file
        frequency: Data frequency as pandas period alias (e.g., "D", "W", "M")
        date_column: Name of column containing dates
        price_column: Name of column containing price data
        income_column: Name of column containing income/dividend data
                       Set to None to exclude income data

    Returns:
        DataFrame with PeriodIndex and columns: "price" (and "income" if requested)

    Example:
        >>> df = load_from_csv("data/AAPL.csv", frequency="D")
        >>> df.head()
                    price  income
        2020-01-01  73.41    0.00
        2020-01-02  74.36    0.00
        ...
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Read CSV
    data = pd.read_csv(file_path, parse_dates=[date_column])

    if data.empty:
        raise ValueError(f"CSV file is empty: {file_path}")

    # Convert to PeriodIndex
    data[date_column] = pd.to_datetime(data[date_column])
    data.index = data[date_column].dt.to_period(frequency)
    data = data.drop(columns=[date_column])

    # Select and rename columns
    result_data = {}

    if price_column not in data.columns:
        raise ValueError(
            f"Price column '{price_column}' not found. "
            f"Available columns: {list(data.columns)}"
        )
    result_data["price"] = data[price_column]

    if income_column is not None:
        if income_column in data.columns:
            result_data["income"] = data[income_column].fillna(0.0)
        else:
            # If income column not found, create zeros
            result_data["income"] = 0.0

    result = pd.DataFrame(result_data)

    # Remove any duplicate periods (keep last)
    result = result[~result.index.duplicated(keep="last")]

    return result


def load_from_dataframe(
    data: pd.DataFrame,
    frequency: str,
    date_column: str | None = None,
    price_column: str = "price",
    income_column: str | None = "income",
) -> pd.DataFrame:
    """Prepare a pandas DataFrame for use with Pyfolium Assets.

    This function converts a DataFrame to the format expected by Asset class:
    - PeriodIndex at specified frequency
    - Columns named "price" and optionally "income"

    Args:
        data: Input DataFrame with date index or date column
        frequency: Data frequency as pandas period alias (e.g., "D", "W", "M")
        date_column: Name of column containing dates (if not using index)
        price_column: Name of column containing price data
        income_column: Name of column containing income/dividend data
                       Set to None to exclude income data

    Returns:
        DataFrame with PeriodIndex and columns: "price" (and "income" if requested)

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

    # Select and rename columns
    result_data = {}

    if price_column not in data.columns:
        raise ValueError(
            f"Price column '{price_column}' not found. "
            f"Available columns: {list(data.columns)}"
        )
    result_data["price"] = data[price_column]

    if income_column is not None:
        if income_column in data.columns:
            result_data["income"] = data[income_column].fillna(0.0)
        else:
            # If income column not specified, create zeros
            result_data["income"] = 0.0

    result = pd.DataFrame(result_data)

    # Remove any duplicate periods (keep last)
    result = result[~result.index.duplicated(keep="last")]

    return result
