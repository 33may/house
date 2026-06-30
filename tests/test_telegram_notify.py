"""Tests for telegram_notify — formatters and the no-secrets guard (no network)."""

from funda_tracker.telegram_notify import format_failure, format_new_pages

_PAGE = """\
---
funda_id: "{id}"
address: "{address}"
city: "Tilburg"
price: 325000
m2: 125
rooms: 5
bedrooms: 4
energy_label: "D"
url: "https://www.funda.nl/detail/koop/tilburg/huis-beneluxlaan-35/43321896/"
status: "🆕 New"
added: "2026-05-19"
requested: ""
listed_date: "2026-04-25"
enriched: true
tags:
  - house
---

# {address}
"""


def _page(tmp_path, page_id="43321896", address="Beneluxlaan 35"):
    p = tmp_path / f"{page_id}-page.md"
    p.write_text(_PAGE.format(id=page_id, address=address), encoding="utf-8")
    return p


def test_format_new_pages_one_house(tmp_path):
    text = format_new_pages([_page(tmp_path)])
    assert "🆕 1 new house on Funda" in text
    assert "Beneluxlaan 35, Tilburg" in text
    assert "€ 325.000" in text
    assert "125 m²" in text
    assert "5 rooms" in text
    assert "label D" in text
    assert "🆕 New" in text
    assert "huis-beneluxlaan-35/43321896" in text


def test_format_new_pages_pluralises_and_counts(tmp_path):
    pages = [
        _page(tmp_path, page_id="1", address="First St 1"),
        _page(tmp_path, page_id="2", address="Second St 2"),
    ]
    text = format_new_pages(pages)
    assert "🆕 2 new houses on Funda" in text
    assert "First St 1" in text
    assert "Second St 2" in text


def test_format_new_pages_caps_at_ten(tmp_path):
    pages = [
        _page(tmp_path, page_id=str(i), address=f"Street {i}") for i in range(13)
    ]
    text = format_new_pages(pages)
    assert "🆕 13 new houses on Funda" in text
    assert "Street 9" in text
    assert "Street 10" not in text
    assert "…and 3 more" in text


def test_format_failure_includes_what_and_detail():
    text = format_failure("Funda poll failed — will retry in 20 min.", "FundaError: timeout")
    assert text.startswith("⚠️ Funda poll failed")
    assert "FundaError: timeout" in text


def test_format_new_pages_all_unreadable_returns_header(tmp_path):
    text = format_new_pages([tmp_path / "does-not-exist.md"])
    assert text == "🆕 1 new house on Funda"


def test_send_without_secrets_is_noop(tmp_path, monkeypatch):
    import funda_tracker.telegram_notify as tn

    monkeypatch.setattr(tn, "SECRETS_PATH", tmp_path / "absent.yaml")
    assert tn.send("hello") is False


def test_send_throttled_respects_the_gap(tmp_path, monkeypatch):
    import funda_tracker.telegram_notify as tn

    monkeypatch.setattr(tn, "LOG_DIR", tmp_path)
    sent = []
    monkeypatch.setattr(tn, "send", lambda text: sent.append(text) or True)

    assert tn.send_throttled("first", key="test", min_gap_seconds=3600) is True
    assert tn.send_throttled("second", key="test", min_gap_seconds=3600) is False
    assert sent == ["first"]
