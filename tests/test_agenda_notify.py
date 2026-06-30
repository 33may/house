"""Tests for agenda_notify — daily action summary and calendar retry."""

from datetime import datetime
from pathlib import Path

from funda_tracker import agenda_notify


_PAGE = """\
---
funda_id: "{id}"
address: "{address}"
city: "Tilburg"
price: 350000
m2: 100
rooms: 4
bedrooms: 3
energy_label: "C"
url: "https://example.test/{id}"
status: "{status}"
declined: false
added: "2026-05-20"
requested: "2026-05-20"
viewing_at: "{viewing_at}"
listed_date: "2026-05-20"
enriched: true
tags:
  - house
---

# {address}

## Notes

_Your thoughts on this house._

## Process log

{log}
"""


def _page(tmp_path: Path, page_id: str, address: str, status: str,
          viewing_at: str = "", log: str = ""):
    path = tmp_path / f"{page_id}-{address.lower().replace(' ', '-')}.md"
    path.write_text(_PAGE.format(
        id=page_id,
        address=address,
        status=status,
        viewing_at=viewing_at,
        log=log,
    ), encoding="utf-8")
    return path


def test_build_agenda_message_lists_viewings_and_actions(tmp_path):
    _page(
        tmp_path,
        "1",
        "Bosscheweg 215",
        "📅 Viewing booked",
        "2026-06-01T16:00",
        "- 2026-05-27 — broker confirmed a viewing for Monday 1 June 2026 at 16:00",
    )
    _page(
        tmp_path,
        "2",
        "Karpatenlaan 36",
        "📅 Viewing booked",
        "",
        "- 2026-05-30 — Appels Makelaardij proposed a viewing on Monday 1 June 2026 at 10:00",
    )
    _page(
        tmp_path,
        "3",
        "Vivaldistraat 63",
        "📨 Viewing requested",
        "",
        "- 2026-05-23 — KIN Makelaars tried to call to schedule viewing but couldn't reach; please call back at (013) 5 339 339",
    )
    _page(
        tmp_path,
        "4",
        "Jan Heynslaan 26",
        "❌ Rejected",
        "",
        "- 2026-05-22 — broker tried to call; please call back at 040-2957957",
    )

    text = agenda_notify.build_agenda_message(
        houses_dir=tmp_path,
        now=datetime(2026, 5, 30, 12, 0),
    )

    assert text.startswith("📌 House agenda")
    assert "Mon 1 Jun 16:00 — Bosscheweg 215" in text
    assert "Karpatenlaan 36 — choose/confirm proposed viewing slot" in text
    assert "Vivaldistraat 63 — call back (013) 5 339 339" in text
    assert "Jan Heynslaan" not in text


def test_build_agenda_message_ignores_past_and_completed_items(tmp_path):
    _page(
        tmp_path,
        "1",
        "Van Alkemadestraat 7",
        "📅 Viewing booked",
        "2026-06-03T16:20",
        "- 2026-05-28 — Adequaat Makelaardij confirmed a viewing for Wednesday 3 June 2026 at 16:20",
    )
    _page(
        tmp_path,
        "2",
        "Breukelsestraat 140",
        "🏠 Viewed",
        "2026-05-27T11:30",
        "- 2026-05-28 — Move.nl announced a bidding deadline of Tuesday 2 June 2026 at 12:00 for this property",
    )
    _page(
        tmp_path,
        "3",
        "Eduard Meijerslaan 17",
        "📅 Viewing booked",
        "",
        "- 2026-05-28 — Rentmeester Makelaardij asked you to call to schedule a viewing next week",
    )

    text = agenda_notify.build_agenda_message(
        houses_dir=tmp_path,
        now=datetime(2026, 6, 5, 12, 0),
    )

    assert text == ""


def test_push_calendar_for_dated_booked_viewings_only(tmp_path, monkeypatch):
    dated = _page(tmp_path, "1", "Bosscheweg 215", "📅 Viewing booked", "2026-06-01T16:00")
    _page(tmp_path, "2", "Karpatenlaan 36", "📅 Viewing booked", "")
    _page(tmp_path, "3", "Merelstraat 6", "🏠 Viewed", "2026-05-29T09:30")
    _page(tmp_path, "4", "Van Alkemadestraat 7", "📅 Viewing booked", "2026-05-29T09:30")
    pushed = []

    monkeypatch.setattr(agenda_notify.calendar_push, "push", lambda path: pushed.append(path.name) or "created")

    result = agenda_notify.push_missing_calendar_events(
        houses_dir=tmp_path,
        now=datetime(2026, 5, 30, 12, 0),
    )

    assert pushed == [dated.name]
    assert result == [f"{dated.name}: created"]


def test_send_agenda_uses_throttled_telegram(tmp_path, monkeypatch):
    _page(tmp_path, "1", "Bosscheweg 215", "📅 Viewing booked", "2030-06-01T16:00")
    sent = []

    monkeypatch.setattr(agenda_notify, "push_missing_calendar_events", lambda houses_dir: [])
    monkeypatch.setattr(
        agenda_notify.telegram_notify,
        "send_throttled",
        lambda text, key, min_gap_seconds: sent.append((text, key, min_gap_seconds)) or True,
    )

    assert agenda_notify.send_agenda(houses_dir=tmp_path, min_gap_seconds=123) is True
    assert sent[0][1:] == ("house-agenda", 123)
    assert "Bosscheweg 215" in sent[0][0]
