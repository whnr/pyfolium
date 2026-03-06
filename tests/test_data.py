"""Tests for data loading utilities."""

import numpy as np
import pandas as pd
import pytest

from pyfolium.data import load_from_csv, load_from_dataframe


# ---------------------------------------------------------------------------
# load_from_dataframe — basic behaviour
# ---------------------------------------------------------------------------


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

    result = load_from_dataframe(df, frequency="M", income_column="income")

    assert isinstance(result.index, pd.PeriodIndex)
    assert result.index.freqstr == "M"
    assert "income" in result.columns
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


def test_load_from_dataframe_default_no_income():
    """Default income_column=None means no income column in output."""
    df = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=3),
            "price": [100.0, 101.0, 102.0],
        }
    )

    result = load_from_dataframe(df, frequency="D", date_column="date")

    assert "income" not in result.columns


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

    result = load_from_dataframe(
        df, frequency="D", date_column="date", income_column=None
    )

    # Should keep last value for duplicate period
    assert len(result) == 2  # Only unique periods
    assert result.loc[pd.Period("2020-01-01", "D"), "price"] == 101.0


# ---------------------------------------------------------------------------
# load_from_dataframe — income column validation (P2-7)
# ---------------------------------------------------------------------------


def test_load_from_dataframe_explicit_income_missing_raises():
    """Explicitly naming a missing income column must raise ValueError."""
    df = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=3),
            "price": [100.0, 101.0, 102.0],
        }
    )

    with pytest.raises(ValueError, match="Income column 'dividends' not found"):
        load_from_dataframe(
            df, frequency="D", date_column="date", income_column="dividends"
        )


# ---------------------------------------------------------------------------
# load_from_csv — basic behaviour
# ---------------------------------------------------------------------------


def test_load_from_csv(tmp_path):
    """Test loading data from CSV file."""
    csv_path = tmp_path / "test_data.csv"
    df = pd.DataFrame(
        {
            "Date": ["2020-01-01", "2020-01-02", "2020-01-03"],
            "Close": [100.0, 101.0, 102.0],
            "Dividend": [0.0, 0.5, 0.0],
        }
    )
    df.to_csv(csv_path, index=False)

    result = load_from_csv(csv_path, frequency="D", income_column="Dividend")

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


def test_load_from_csv_default_no_income(tmp_path):
    """Default income_column=None means no income column in output."""
    csv_path = tmp_path / "test_data.csv"
    df = pd.DataFrame(
        {
            "Date": ["2020-01-01", "2020-01-02"],
            "Close": [100.0, 101.0],
        }
    )
    df.to_csv(csv_path, index=False)

    result = load_from_csv(csv_path, frequency="D")

    assert "price" in result.columns
    assert "income" not in result.columns


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


# ---------------------------------------------------------------------------
# load_from_csv — income column validation (P2-7)
# ---------------------------------------------------------------------------


def test_load_from_csv_explicit_income_missing_raises(tmp_path):
    """Explicitly naming a missing income column must raise ValueError."""
    csv_path = tmp_path / "test_data.csv"
    df = pd.DataFrame(
        {
            "Date": ["2020-01-01", "2020-01-02"],
            "Close": [100.0, 101.0],
        }
    )
    df.to_csv(csv_path, index=False)

    with pytest.raises(ValueError, match="Income column 'Dividend' not found"):
        load_from_csv(csv_path, frequency="D", income_column="Dividend")


# ---------------------------------------------------------------------------
# Data density sanity check
# ---------------------------------------------------------------------------


def test_density_rejects_monthly_in_daily():
    """Monthly data loaded as daily should fail the density check."""
    dates = pd.date_range("2020-01-01", periods=12, freq="MS")
    df = pd.DataFrame({"price": range(100, 112)}, index=dates)

    with pytest.raises(ValueError, match="Data density too low"):
        load_from_dataframe(df, frequency="D")


def test_density_passes_weekday_stock_data():
    """Daily stock data (weekdays only) has ~69% density — should pass."""
    # Generate one year of weekday-only dates
    all_days = pd.date_range("2020-01-01", "2020-12-31", freq="D")
    weekdays = all_days[all_days.weekday < 5]
    rng = np.random.default_rng(42)
    df = pd.DataFrame(
        {"price": rng.uniform(90, 110, size=len(weekdays))}, index=weekdays
    )

    result = load_from_dataframe(df, frequency="D")

    assert len(result) == len(weekdays)


def test_density_disabled_with_none():
    """Setting min_density=None disables the check entirely."""
    dates = pd.date_range("2020-01-01", periods=12, freq="MS")
    df = pd.DataFrame({"price": range(100, 112)}, index=dates)

    result = load_from_dataframe(df, frequency="D", min_density=None)

    assert len(result) == 12


def test_density_skipped_for_short_data():
    """Fewer than 3 data points should skip the density check."""
    dates = pd.to_datetime(["2020-01-01", "2020-12-31"])
    df = pd.DataFrame({"price": [100.0, 110.0]}, index=dates)

    # 2 points over 366 daily periods — 0.5% density, but check is skipped
    result = load_from_dataframe(df, frequency="D")

    assert len(result) == 2


def test_density_custom_threshold():
    """Custom threshold can be stricter or more lenient."""
    # ~60% density: 4 out of 7 days
    dates = pd.to_datetime(
        [
            "2020-01-01",
            "2020-01-02",
            "2020-01-03",
            "2020-01-04",
            "2020-01-05",
            "2020-01-06",
            "2020-01-07",
        ]
    )
    # Keep only 4 of 7
    sparse_dates = dates[[0, 2, 4, 6]]
    df = pd.DataFrame({"price": [100.0, 102.0, 104.0, 106.0]}, index=sparse_dates)

    # Strict threshold — should fail
    with pytest.raises(ValueError, match="Data density too low"):
        load_from_dataframe(df, frequency="D", min_density=0.7)

    # Lenient threshold — should pass
    result = load_from_dataframe(df, frequency="D", min_density=0.5)
    assert len(result) == 4


def test_density_check_via_csv(tmp_path):
    """Density check also works through the CSV loading path."""
    csv_path = tmp_path / "sparse.csv"
    # Monthly data points spanning a year
    dates = pd.date_range("2020-01-01", periods=12, freq="MS")
    df = pd.DataFrame({"Date": dates.strftime("%Y-%m-%d"), "Close": range(100, 112)})
    df.to_csv(csv_path, index=False)

    with pytest.raises(ValueError, match="Data density too low"):
        load_from_csv(csv_path, frequency="D")

    # Should pass with check disabled
    result = load_from_csv(csv_path, frequency="D", min_density=None)
    assert len(result) == 12
