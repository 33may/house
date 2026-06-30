"""Translates Dutch listing text to English.

Best-effort: if translation fails (network, rate-limit, library missing) the original
Dutch text is returned unchanged — a translation problem must never break page creation.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Google's free endpoint caps a single request near 5000 characters.
_MAX_CHARS = 4500


def to_english(text: str | None) -> str:
    """Translate Dutch → English. Returns the original text on any failure."""
    text = (text or "").strip()
    if not text:
        return ""
    try:
        from deep_translator import GoogleTranslator

        return GoogleTranslator(source="nl", target="en").translate(text[:_MAX_CHARS])
    except Exception as e:  # noqa: BLE001 — never let translation break a run
        log.warning("translation failed, keeping Dutch original: %s", e)
        return text
