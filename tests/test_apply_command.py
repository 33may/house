"""Tests for the apply-command orchestration (parsing + house resolution).

No browser here — this is the pure logic that decides WHAT to apply to and with
what message. The browser submit lives in applier.py.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from types import SimpleNamespace

from funda_tracker.apply_command import (
    DEFAULT_MESSAGE,
    default_message,
    handle_apply,
    mark_viewing_requested,
    parse_apply,
    resolve_house,
)


# --- parse_apply -----------------------------------------------------------

def test_parse_plain_apply_has_no_custom_message():
    cmd = parse_apply("apply to Tinelstraat 186")
    assert cmd is not None
    assert cmd.address == "Tinelstraat 186"
    assert cmd.message is None


def test_parse_apply_with_custom_message():
    cmd = parse_apply("apply to Tinelstraat 186: I love this one, call me!")
    assert cmd is not None
    assert cmd.address == "Tinelstraat 186"
    assert cmd.message == "I love this one, call me!"


def test_parse_is_case_insensitive_and_trims():
    cmd = parse_apply("  Apply To   Tinelstraat 186  ")
    assert cmd is not None
    assert cmd.address == "Tinelstraat 186"


def test_parse_non_apply_returns_none():
    assert parse_apply("what's the weather today?") is None
    assert parse_apply("") is None


# --- default_message -------------------------------------------------------

def test_default_message_is_the_english_fallback():
    assert default_message() == DEFAULT_MESSAGE
    assert default_message() == (
        "I really like this house, let me know when it is possible to view it!"
    )


# --- resolve_house ---------------------------------------------------------

def _note(dir_: Path, fid: str, address: str, city: str) -> None:
    (dir_ / f"{fid}-x.md").write_text(textwrap.dedent(f"""\
        ---
        funda_id: "{fid}"
        address: "{address}"
        city: "{city}"
        url: "https://www.funda.nl/detail/koop/{city.lower()}/huis-x/{fid}/"
        status: "🆕 New"
        ---
        # {address}
    """), encoding="utf-8")


def test_resolve_single_match(tmp_path):
    _note(tmp_path, "44408283", "Tinelstraat 186", "Eindhoven")
    _note(tmp_path, "43312011", "Hellebaardstraat 8", "Tilburg")

    matches = resolve_house("Tinelstraat 186", tmp_path)
    assert len(matches) == 1
    assert matches[0].funda_id == "44408283"
    assert matches[0].city == "Eindhoven"
    assert matches[0].url.endswith("/44408283/")


def test_resolve_is_case_insensitive(tmp_path):
    _note(tmp_path, "44408283", "Tinelstraat 186", "Eindhoven")
    matches = resolve_house("tinelstraat 186", tmp_path)
    assert len(matches) == 1


def test_resolve_no_match_returns_empty(tmp_path):
    _note(tmp_path, "44408283", "Tinelstraat 186", "Eindhoven")
    assert resolve_house("Nonexistentstraat 1", tmp_path) == []


def test_resolve_ambiguous_returns_all(tmp_path):
    _note(tmp_path, "111", "Kerkstraat 1", "Eindhoven")
    _note(tmp_path, "222", "Kerkstraat 1", "Tilburg")
    matches = resolve_house("Kerkstraat 1", tmp_path)
    assert len(matches) == 2
    assert {m.city for m in matches} == {"Eindhoven", "Tilburg"}


# --- mark_viewing_requested ------------------------------------------------

def _full_note(path: Path) -> None:
    path.write_text(textwrap.dedent("""\
        ---
        funda_id: "44408283"
        address: "Tinelstraat 186"
        city: "Eindhoven"
        status: "🆕 New"
        requested: ""
        ---
        # Tinelstraat 186

        ## Process log

        - 2026-06-22 — page created
    """), encoding="utf-8")


def test_mark_sets_status_and_requested_date(tmp_path):
    p = tmp_path / "house.md"
    _full_note(p)
    mark_viewing_requested(p, "2026-06-23")
    text = p.read_text(encoding="utf-8")
    assert 'status: "📨 Viewing requested"' in text
    assert 'requested: "2026-06-23"' in text


def test_mark_prepends_process_log_line_and_keeps_history(tmp_path):
    p = tmp_path / "house.md"
    _full_note(p)
    mark_viewing_requested(p, "2026-06-23")
    text = p.read_text(encoding="utf-8")
    assert "- 2026-06-23 — viewing requested via Funda (auto-apply)" in text
    assert "- 2026-06-22 — page created" in text  # history preserved
    # new entry comes before the older one (reverse-chronological)
    assert text.index("2026-06-23 — viewing requested") < text.index("2026-06-22 — page created")


# --- handle_apply (orchestration) ------------------------------------------

def _ok(url, message):
    _ok.calls.append((url, message))
    return SimpleNamespace(ok=True, error=None, screenshot=None)
_ok.calls = []


def test_handle_apply_success_marks_note_and_confirms(tmp_path):
    _ok.calls = []
    _full_note(tmp_path / "44408283-x.md")
    reply = handle_apply("apply to Tinelstraat 186", tmp_path,
                         apply_fn=_ok, today="2026-06-23")
    assert "✅" in reply and "Tinelstraat 186" in reply
    # applier called with the note's url + default message
    assert len(_ok.calls) == 1
    assert _ok.calls[0][1] == DEFAULT_MESSAGE
    # note flipped to requested
    assert "📨 Viewing requested" in (tmp_path / "44408283-x.md").read_text()


def test_handle_apply_uses_custom_message(tmp_path):
    _ok.calls = []
    _full_note(tmp_path / "44408283-x.md")
    handle_apply("apply to Tinelstraat 186: bel me!", tmp_path,
                 apply_fn=_ok, today="2026-06-23")
    assert _ok.calls[0][1] == "bel me!"


def test_handle_apply_no_match(tmp_path):
    reply = handle_apply("apply to Ghoststraat 9", tmp_path, apply_fn=_ok)
    assert "❌" in reply or "geen" in reply.lower() or "no" in reply.lower()


def test_handle_apply_ambiguous(tmp_path):
    _note(tmp_path, "111", "Kerkstraat 1", "Eindhoven")
    _note(tmp_path, "222", "Kerkstraat 1", "Tilburg")
    reply = handle_apply("apply to Kerkstraat 1", tmp_path, apply_fn=_ok)
    assert "Eindhoven" in reply and "Tilburg" in reply


def test_handle_apply_failure_does_not_mark_note(tmp_path):
    def fail(url, message):
        return SimpleNamespace(ok=False, error="not logged in", screenshot=None)
    _full_note(tmp_path / "44408283-x.md")
    reply = handle_apply("apply to Tinelstraat 186", tmp_path,
                         apply_fn=fail, today="2026-06-23")
    assert "not logged in" in reply
    assert "📨 Viewing requested" not in (tmp_path / "44408283-x.md").read_text()
