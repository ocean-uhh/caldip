"""Tests for caldip.report.status against the real caldip status vocabulary.

The status strings used here are the exact nine forms produced by caldip (three
templates over T/C/P), taken from the detailed statistics CSVs in the repo.
"""

import pytest

from caldip.report.status import (
    FLAGGED_KIND,
    MISSING_KIND,
    NO_DATA_KIND,
    OK_KIND,
    UNKNOWN_KIND,
    classify_status,
)


@pytest.mark.parametrize("text", ["T OK", "C OK", "P OK"])
def test_ok_forms(text):
    """Each '{var} OK' form classifies as ok with no magnitude."""
    result = classify_status(text)
    assert result.kind == OK_KIND
    assert result.magnitude is None
    assert result.direction is None


@pytest.mark.parametrize("text", ["T NO DATA", "C NO DATA", "P NO DATA"])
def test_no_data_forms(text):
    """Each '{var} NO DATA' form classifies as no_data, not flagged."""
    assert classify_status(text).kind == NO_DATA_KIND


def test_flagged_high_captures_direction_and_magnitude():
    """A 'reads high by N' status yields direction 'high' and magnitude N."""
    result = classify_status("T reads high by 0.012")
    assert result.kind == FLAGGED_KIND
    assert result.direction == "high"
    assert result.magnitude == pytest.approx(0.012)


def test_flagged_low_captures_direction_and_magnitude():
    """A 'reads low by N' status yields direction 'low' and magnitude N."""
    result = classify_status("P reads low by 29.774")
    assert result.kind == FLAGGED_KIND
    assert result.direction == "low"
    assert result.magnitude == pytest.approx(29.774)


@pytest.mark.parametrize("text", ["", "   ", None])
def test_empty_is_missing_not_unknown(text):
    """An empty or whitespace cell is missing (no warning), not unknown."""
    assert classify_status(text).kind == MISSING_KIND


@pytest.mark.parametrize(
    "text", ["T reads sideways by 3", "temperature high", "T flagged"]
)
def test_unrecognised_nonempty_is_unknown(text):
    """A non-empty status matching no template routes to unknown, not flagged.

    This is the tripwire: an upstream wording change surfaces as unknown rather
    than being silently counted as ok or flagged.
    """
    assert classify_status(text).kind == UNKNOWN_KIND
