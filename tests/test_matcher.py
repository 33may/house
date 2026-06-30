"""Tests for the local feature filters."""

from funda_tracker.matcher import passes_local_filters


class FakeDetails:
    def __init__(self, features):
        self.features = features


class FakeListing:
    def __init__(self, features):
        self.property_details = FakeDetails(features)


def test_passes_when_no_filters():
    ok, reason = passes_local_filters(FakeListing({"has_garden": True}), [], [])
    assert ok and reason == ""


def test_require_feature_present():
    ok, _ = passes_local_filters(FakeListing({"has_garden": True}), ["has_garden"], [])
    assert ok


def test_require_feature_missing_fails():
    ok, reason = passes_local_filters(
        FakeListing({"has_garden": False}), ["has_garden"], []
    )
    assert not ok
    assert "has_garden" in reason


def test_exclude_feature_present_fails():
    ok, reason = passes_local_filters(
        FakeListing({"is_fixer_upper": True}), [], ["is_fixer_upper"]
    )
    assert not ok
    assert "is_fixer_upper" in reason


def test_exclude_feature_absent_passes():
    ok, _ = passes_local_filters(FakeListing({}), [], ["is_fixer_upper"])
    assert ok
