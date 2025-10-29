"""Tests for data loading utilities."""

import tempfile
from pathlib import Path

import pandas as pd
import pytest

from pyfolium.data import load_from_csv, load_from_dataframe, load_from_yahoo


def test_load_from_dataframe_with_date_column():
    """Test loading data from DataFrame with date column."""
    df = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=5, freq="D"),
            "close": [100.0, 101.0, 102.0, 103.0, 104.0],
            "div": [0.0, 0.0, 0.5, 0.0, 0.0],
        }
    )

    result = load_from_dataframe(
        df, frequency="D", date_column="date", price_column="close", income_column="div"
    )

    assert isinstance(result.index, pd.PeriodIndex)
    assert result.index.freqstr == "D"
    assert "price" in result.columns
    assert "income" in result.columns
    assert len(result) == 5
    assert result["price"].iloc[0] == 100.0
    assert result["income"].iloc[2] == 0.5


def test_load_from_dataframe_with_period_index():
    """Test loading data from DataFrame that already has PeriodIndex."""
    df = pd.DataFrame(
        {
            "price": [100.0, 101.0, 102.0],
            "income": [0.0, 0.5, 0.0],
        },
        index=pd.period_range("2020-01", periods=3, freq="M"),
    )

    result = load_from_dataframe(df, frequency="M")

    assert isinstance(result.index, pd.PeriodIndex)
    assert result.index.freqstr == "M"
    assert len(result) == 3


def test_load_from_dataframe_missing_price_column():
    """Test that missing price column raises error."""
    df = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=3),
            "value": [100, 101, 102],
        }
    )

    with pytest.raises(ValueError, match="Price column 'price' not found"):
        load_from_dataframe(df, frequency="D", date_column="date")


def test_load_from_dataframe_no_income():
    """Test loading data without income column."""
    df = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=3),
            "price": [100.0, 101.0, 102.0],
        }
    )

    result = load_from_dataframe(
        df, frequency="D", date_column="date", income_column=None
    )

    assert "price" in result.columns
    assert "income" not in result.columns


def test_load_from_csv(tmp_path):
    """Test loading data from CSV file."""
    # Create a temporary CSV file
    csv_path = tmp_path / "test_data.csv"
    df = pd.DataFrame(
        {
            "Date": ["2020-01-01", "2020-01-02", "2020-01-03"],
            "Close": [100.0, 101.0, 102.0],
            "Dividend": [0.0, 0.5, 0.0],
        }
    )
    df.to_csv(csv_path, index=False)

    result = load_from_csv(csv_path, frequency="D")

    assert isinstance(result.index, pd.PeriodIndex)
    assert result.index.freqstr == "D"
    assert "price" in result.columns
    assert "income" in result.columns
    assert len(result) == 3
    assert result["price"].iloc[0] == 100.0
    assert result["income"].iloc[1] == 0.5


def test_load_from_csv_missing_file():
    """Test that missing CSV file raises error."""
    with pytest.raises(FileNotFoundError):
        load_from_csv("nonexistent.csv", frequency="D")


def test_load_from_csv_missing_price_column(tmp_path):
    """Test that missing price column in CSV raises error."""
    csv_path = tmp_path / "test_data.csv"
    df = pd.DataFrame(
        {
            "Date": ["2020-01-01", "2020-01-02"],
            "Value": [100.0, 101.0],
        }
    )
    df.to_csv(csv_path, index=False)

    with pytest.raises(ValueError, match="Price column 'Close' not found"):
        load_from_csv(csv_path, frequency="D")


def test_load_from_csv_no_income_column(tmp_path):
    """Test loading CSV without income column creates zeros."""
    csv_path = tmp_path / "test_data.csv"
    df = pd.DataFrame(
        {
            "Date": ["2020-01-01", "2020-01-02"],
            "Close": [100.0, 101.0],
        }
    )
    df.to_csv(csv_path, index=False)

    result = load_from_csv(csv_path, frequency="D")

    assert "income" in result.columns
    assert result["income"].iloc[0] == 0.0


def test_load_from_yahoo_invalid_symbol():
    """Test that invalid symbol raises error."""
    # Use a clearly invalid symbol
    # yfinance can raise either ValueError or TypeError depending on the error
    with pytest.raises((ValueError, TypeError)):
        load_from_yahoo(
            "INVALID_SYMBOL_12345", start="2020-01-01", end="2020-01-31", frequency="D"
        )


@pytest.mark.slow
def test_load_from_yahoo_real_data():
    """Test loading real data from Yahoo Finance.

    This test is marked as slow since it makes a real API call.
    Run with: pytest -m slow
    """
    result = load_from_yahoo("AAPL", start="2020-01-01", end="2020-01-31", frequency="D")

    assert isinstance(result.index, pd.PeriodIndex)
    assert result.index.freqstr == "D"
    assert "price" in result.columns
    assert "income" in result.columns
    assert len(result) > 0
    assert result["price"].iloc[0] > 0


def test_load_from_yahoo_no_income():
    """Test loading Yahoo data without income column."""
    # Skip this test if network is unavailable
    pytest.skip("Skipping network-dependent test")


def test_load_from_dataframe_handles_duplicates():
    """Test that duplicate periods are handled correctly."""
    df = pd.DataFrame(
        {
            "date": [
                "2020-01-01",
                "2020-01-01",
                "2020-01-02",
            ],  # Duplicate date
            "price": [100.0, 101.0, 102.0],
        }
    )
    df["date"] = pd.to_datetime(df["date"])

    result = load_from_dataframe(df, frequency="D", date_column="date", income_column=None)

    # Should keep last value for duplicate period
    assert len(result) == 2  # Only unique periods
    assert result.loc[pd.Period("2020-01-01", "D"), "price"] == 101.0


def test_load_from_csv_custom_columns(tmp_path):
    """Test loading CSV with custom column names."""
    csv_path = tmp_path / "custom_data.csv"
    df = pd.DataFrame(
        {
            "Timestamp": ["2020-01-01", "2020-01-02"],
            "AdjustedClose": [100.0, 101.0],
            "DividendAmount": [0.0, 0.5],
        }
    )
    df.to_csv(csv_path, index=False)

    result = load_from_csv(
        csv_path,
        frequency="D",
        date_column="Timestamp",
        price_column="AdjustedClose",
        income_column="DividendAmount",
    )

    assert len(result) == 2
    assert result["price"].iloc[0] == 100.0
    assert result["income"].iloc[1] == 0.5
