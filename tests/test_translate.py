"""Tests for the translation module (no network — covers the guard cases)."""

from funda_tracker.translate import to_english


def test_empty_input_returns_empty():
    assert to_english("") == ""
    assert to_english(None) == ""
    assert to_english("   ") == ""
