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

    result = calendar_push.push(page, backend="apple")

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

    first = calendar_push.push(page, backend="apple")
    second = calendar_push.push(page, backend="apple")

    ics_path = fallback_dir / "44492178-20260623T1500.ics"
    assert first == f"fallback: wrote .ics to {ics_path} (Apple Calendar automation unavailable)"
    assert second == f"fallback: .ics already exists at {ics_path} (Apple Calendar automation unavailable)"


def test_push_google_backend_uses_injected_creator(tmp_path):
    page = _page(tmp_path, "44492178", "Brasemstraat 35", "2026-06-23T15:00")
    seen = {}

    def fake_creator(**kwargs):
        seen.update(kwargs)
        return "created: evt_abc123"

    result = calendar_push.push(page, backend="google", google_creator=fake_creator)

    assert result == "created: evt_abc123"
    assert seen["summary"] == "🏠 Viewing — Brasemstraat 35, Tilburg"
    assert seen["location"] == "Brasemstraat 35, Tilburg"
    assert seen["marker"] == "[house-tracker:44492178]"
    assert seen["start"].isoformat() == "2026-06-23T15:00:00"
    assert seen["end"].isoformat() == "2026-06-23T15:30:00"


def test_push_google_backend_falls_back_to_ics_on_error(tmp_path, monkeypatch):
    page = _page(tmp_path, "44492178", "Brasemstraat 35", "2026-06-23T15:00")
    fallback_dir = tmp_path / "calendar-imports"
    monkeypatch.setattr(calendar_push, "FALLBACK_DIR", fallback_dir)

    def boom(**kwargs):
        raise RuntimeError("connector down")

    result = calendar_push.push(page, backend="google", google_creator=boom)

    ics_path = fallback_dir / "44492178-20260623T1500.ics"
    assert result == f"fallback: wrote .ics to {ics_path} (Google Calendar unavailable)"
    assert ics_path.exists()
