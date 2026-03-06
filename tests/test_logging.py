"""Tests for pyfolium.logging types."""

import pandas as pd
import pytest

from pyfolium.logging import LogEntry, OutputMode, Severity


class TestSeverity:
    def test_ordering(self):
        assert Severity.DEBUG < Severity.INFO < Severity.WARNING < Severity.ERROR

    def test_gte_filtering(self):
        assert Severity.WARNING >= Severity.WARNING
        assert Severity.ERROR >= Severity.WARNING
        assert not Severity.INFO >= Severity.WARNING

    def test_is_int(self):
        assert int(Severity.DEBUG) == 10
        assert int(Severity.ERROR) == 40


class TestLogEntry:
    @pytest.fixture
    def sample_entry(self):
        return LogEntry(
            severity=Severity.INFO,
            timestamp=1.0,
            period=pd.Period("2020-01-01", freq="D"),
            source="runner",
            message="test message",
        )

    def test_frozen(self, sample_entry):
        with pytest.raises(AttributeError):
            sample_entry.message = "modified"  # type: ignore[misc]

    def test_equality(self):
        kwargs = {
            "severity": Severity.INFO,
            "timestamp": 1.0,
            "period": pd.Period("2020-01-01", freq="D"),
            "source": "runner",
            "message": "test",
        }
        assert LogEntry(**kwargs) == LogEntry(**kwargs)

    def test_sorting_by_timestamp(self):
        period = pd.Period("2020-01-01", freq="D")
        entries = [
            LogEntry(Severity.INFO, 3.0, period, "runner", "third"),
            LogEntry(Severity.INFO, 1.0, period, "runner", "first"),
            LogEntry(Severity.INFO, 2.0, period, "runner", "second"),
        ]
        sorted_entries = sorted(entries, key=lambda e: e.timestamp)
        assert [e.message for e in sorted_entries] == ["first", "second", "third"]

    def test_data_defaults_to_none(self, sample_entry):
        assert sample_entry.data is None

    def test_data_with_dict(self):
        entry = LogEntry(
            severity=Severity.ERROR,
            timestamp=1.0,
            period=pd.Period("2020-01-01", freq="D"),
            source="runner",
            message="error",
            data={"exception": ValueError("boom")},
        )
        assert "exception" in entry.data


class TestOutputMode:
    def test_values_are_strings(self):
        assert OutputMode.SILENT == "silent"
        assert OutputMode.SUMMARY == "summary"
        assert OutputMode.PROGRESS == "progress"

    def test_string_construction(self):
        assert OutputMode("silent") is OutputMode.SILENT
