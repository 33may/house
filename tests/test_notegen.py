"""Tests for the Obsidian page generator."""

from funda_tracker.notegen import _slug, _yaml_scalar, write_note


class FakePrice:
    amount = 425000
    formatted = "€ 425.000 k.k."


class FakeListing:
    id = 43117443
    title = "Voorbeeldstraat 12, Eindhoven"
    city = "Eindhoven"
    price = FakePrice()
    living_area = 95
    rooms_count = 4
    bedrooms = 2
    energy_label = "B"
    url = "https://www.funda.nl/koop/eindhoven/huis-43117443/"
    publication_date = "2026-05-18"
    description = "Mooi huis."
    property_details = None
    media = None

    @property
    def broker(self):
        return None


def test_slug():
    assert _slug("Voorbeeldstraat 12, Eindhoven") == "voorbeeldstraat-12-eindhoven"


def test_yaml_scalar():
    assert _yaml_scalar("hi") == '"hi"'
    assert _yaml_scalar(100) == "100"
    assert _yaml_scalar(True) == "true"
    assert _yaml_scalar(None) == '""'


def test_write_note_creates_file(tmp_path):
    path = write_note(tmp_path, FakeListing(), enriched=True)
    assert path is not None and path.exists()
    text = path.read_text(encoding="utf-8")
    assert "funda_id: 43117443" in text
    assert 'status: "🆕 New"' in text
    assert "declined: false" in text
    assert "requested:" in text
    assert "## Notes" in text
    assert "## Process log" in text
    assert "[Open on Funda]" in text


def test_write_note_skips_existing(tmp_path):
    first = write_note(tmp_path, FakeListing(), enriched=True)
    second = write_note(tmp_path, FakeListing(), enriched=True)
    assert first is not None
    assert second is None


def test_write_note_flags_unenriched(tmp_path):
    text = write_note(tmp_path, FakeListing(), enriched=False).read_text(encoding="utf-8")
    assert "enriched: false" in text
    assert "Detail fetch failed" in text
