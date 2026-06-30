"""Tests for calendar_push fallback behavior."""

from pathlib import Path

from funda_tracker import calendar_push


_PAGE = """\
---
funda_id: "{id}"
address: "{address}"
city: "Tilburg"
url: "https://example.test/{id}"
status: "📅 Viewing booked"
viewing_at: "{viewing_at}"
---

# {address}

## Process log

- 2026-06-17 — Move.nl confirmed a viewing for Tuesday 23 June 2026 at 15:00
"""


def _page(tmp_path: Path, page_id: str, address: str, viewing_at: str) -> Path:
    path = tmp_path / f"{page_id}-{address.lower().replace(' ', '-')}.md"
    path.write_text(
        _PAGE.format(id=page_id, address=address, viewing_at=viewing_at),
        encoding="utf-8",
    )
    return path


def test_push_writes_deterministic_ics_fallback(tmp_path, monkeypatch):
    page = _page(tmp_path, "44492178", "Brasemstraat 35", "2026-06-23T15:00")
    fallback_dir = tmp_path / "calendar-imports"

    def _fail(*args, **kwargs):
        raise RuntimeError("osascript failed")

    monkeypatch.setattr(calendar_push, "FALLBACK_DIR", fallback_dir)
    monkeypatch.setattr(calendar_push.subprocess, "run", _fail)

    result = calendar_push.push(page)

    ics_path = fallback_dir / "44492178-20260623T1500.ics"
    assert result == f"fallback: wrote .ics to {ics_path} (Apple Calendar automation unavailable)"
    assert ics_path.exists()
    text = ics_path.read_text(encoding="utf-8")
    assert "BEGIN:VCALENDAR" in text
    assert "SUMMARY:🏠 Viewing — Brasemstraat 35\\, Tilburg" in text
    assert "DTSTART;TZID=Europe/Amsterdam:20260623T150000" in text
    assert "[house-tracker:44492178]" in text


def test_push_reuses_existing_ics_fallback(tmp_path, monkeypatch):
    page = _page(tmp_path, "44492178", "Brasemstraat 35", "2026-06-23T15:00")
    fallback_dir = tmp_path / "calendar-imports"

    def _fail(*args, **kwargs):
        raise RuntimeError("osascript failed")

    monkeypatch.setattr(calendar_push, "FALLBACK_DIR", fallback_dir)
    monkeypatch.setattr(calendar_push.subprocess, "run", _fail)

    first = calendar_push.push(page)
    second = calendar_push.push(page)

    ics_path = fallback_dir / "44492178-20260623T1500.ics"
    assert first == f"fallback: wrote .ics to {ics_path} (Apple Calendar automation unavailable)"
    assert second == f"fallback: .ics already exists at {ics_path} (Apple Calendar automation unavailable)"
