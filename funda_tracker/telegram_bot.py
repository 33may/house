"""Telegram bot that dispatches each incoming message to a Claude session.

Long-polls Telegram. Each message reaches the Claude CLI with the house-tracker
system prompt pre-loaded. Sessions live for `SESSION_TTL` — within that window,
follow-up messages resume the same Claude session (via --resume) and share its
full memory of the chat. After the TTL expires, the next message starts fresh.

Single-user: only the chat id configured in secrets.yaml as `telegram_chat_id` can
talk to the bot; messages from any other chat are ignored.

Run it:
    .venv/bin/python3 -m funda_tracker.telegram_bot
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from funda_tracker import apply_command, telegram_notify

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "logs"
STATE_DIR.mkdir(parents=True, exist_ok=True)
SESSION_PATH = STATE_DIR / "telegram-session.json"
OFFSET_PATH = STATE_DIR / "telegram-offset.json"

SESSION_TTL = timedelta(hours=1)
LONG_POLL_TIMEOUT = 25  # seconds — Telegram holds the connection up to this long
TELEGRAM_MAX_LEN = 3900  # under 4096 to leave headroom
CLAUDE_TIMEOUT = 600  # seconds per request; long enough for tool-heavy work
CLAUDE_MODEL = "sonnet"  # Anthropic model that answers chats

SYSTEM_PROMPT = f"""You are the house-hunt assistant for the user's Funda tracker at {ROOT}.

Context:
- The user (Anton) is house-hunting in the Netherlands: Tilburg, Eindhoven, Boxtel, Best, ≤€350k.
- The tracker writes one Obsidian Markdown page per house under houses/*.md.
- Status workflow: 🆕 New → 📨 Viewing requested → 📅 Viewing booked → 🏠 Viewed → 🎯 Offer made, plus ❌ Rejected. A `declined: true` checkbox is a separate manual reject signal.
- Gmail sync (slash command /gmail-sync) updates pages from broker email.
- Apple Calendar push happens automatically on 📅 Viewing booked via `funda_tracker.calendar_push`.
- The user texts you from their phone via Telegram. Keep replies SHORT (1–4 sentences), plain text, no markdown, no headers, no bullet points. Telegram does not render markdown.
- You are running under the Claude CLI with file access to the project. Be decisive. Do not stack clarifying questions; if you truly need one, ask just one.
- When you change the vault, end with a one-line confirmation of what you did.
"""

API = "https://api.telegram.org"


# --- secrets ---------------------------------------------------------------

def _secrets() -> tuple[str, str]:
    secrets = telegram_notify._load_secrets()
    if not secrets:
        raise SystemExit("secrets.yaml missing telegram_bot_token or telegram_chat_id")
    return secrets


# --- session state ---------------------------------------------------------

def _load_session() -> dict | None:
    if not SESSION_PATH.exists():
        return None
    try:
        return json.loads(SESSION_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _save_session(session_id: str, created_at: datetime) -> None:
    SESSION_PATH.write_text(json.dumps(
        {"provider": "claude", "session_id": session_id, "created_at": created_at.isoformat()}, indent=2,
    ))


def _active_session_id() -> str | None:
    """Return the Claude session id if a valid (un-expired) session exists."""
    s = _load_session()
    if not s:
        return None
    try:
        if s.get("provider") != "claude":
            return None
        created_at = datetime.fromisoformat(s["created_at"])
        if datetime.now(timezone.utc) - created_at < SESSION_TTL:
            return s["session_id"]
    except (KeyError, ValueError):
        pass
    return None


def _load_offset() -> int:
    if not OFFSET_PATH.exists():
        return 0
    try:
        return int(json.loads(OFFSET_PATH.read_text()).get("offset", 0))
    except (json.JSONDecodeError, OSError, ValueError):
        return 0


def _save_offset(offset: int) -> None:
    OFFSET_PATH.write_text(json.dumps({"offset": offset}))


# --- telegram I/O ----------------------------------------------------------

def _get_updates(token: str, offset: int) -> list[dict]:
    """Long-poll getUpdates. Returns list of update dicts. Empty on timeout."""
    url = f"{API}/bot{token}/getUpdates"
    params = urllib.parse.urlencode({
        "offset": offset,
        "timeout": LONG_POLL_TIMEOUT,
        "allowed_updates": json.dumps(["message"]),
    })
    full_url = f"{url}?{params}"
    try:
        with urllib.request.urlopen(full_url, timeout=LONG_POLL_TIMEOUT + 5) as resp:
            data = json.loads(resp.read())
    except urllib.error.URLError as e:
        log.warning("telegram: getUpdates network error: %s", e)
        time.sleep(5)
        return []
    except Exception as e:  # noqa: BLE001
        log.warning("telegram: getUpdates failed: %s", e)
        time.sleep(5)
        return []
    if not data.get("ok"):
        log.warning("telegram: getUpdates not ok: %s", data)
        time.sleep(5)
        return []
    return data.get("result", [])


def _send_typing(token: str, chat_id: str) -> None:
    url = f"{API}/bot{token}/sendChatAction"
    payload = urllib.parse.urlencode({"chat_id": chat_id, "action": "typing"}).encode()
    try:
        urllib.request.urlopen(url, data=payload, timeout=5).read()
    except Exception:  # noqa: BLE001
        pass


def _send_text(token: str, chat_id: str, text: str) -> None:
    """Send (chunked if needed) plain-text response back to the chat."""
    text = (text or "").strip() or "(empty response)"
    chunks = [text[i:i + TELEGRAM_MAX_LEN] for i in range(0, len(text), TELEGRAM_MAX_LEN)]
    url = f"{API}/bot{token}/sendMessage"
    for chunk in chunks:
        payload = urllib.parse.urlencode({
            "chat_id": chat_id, "text": chunk, "disable_web_page_preview": "true",
        }).encode()
        try:
            urllib.request.urlopen(url, data=payload, timeout=10).read()
        except Exception as e:  # noqa: BLE001
            log.warning("telegram: sendMessage failed: %s", e)


# --- claude dispatch -------------------------------------------------------

def _parse_claude_json(stdout: str, session_id: str | None) -> tuple[str, str | None]:
    """Parse `claude -p --output-format json` output (a single result object).

    Returns (reply_text, session_id). Falls back to raw text if it isn't the
    expected JSON, and tolerates leading log noise by scanning for the JSON line.
    """
    stdout = (stdout or "").strip()
    if not stdout:
        return "", session_id

    obj = None
    try:
        obj = json.loads(stdout)
    except json.JSONDecodeError:
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    obj = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
    if obj is None:
        return stdout, session_id

    reply = (obj.get("result") or "").strip()
    sid = obj.get("session_id") or session_id
    return reply, sid


def _run_claude(user_msg: str) -> tuple[str, str | None]:
    """Run `claude -p` with either a resumed session or a fresh one.

    The new user message is fed on stdin; on a fresh session the house-hunt
    SYSTEM_PROMPT is appended. Returns (reply_text, session_id).
    """
    session_id = _active_session_id()
    cmd = [
        "claude", "-p",
        "--model", CLAUDE_MODEL,
        "--output-format", "json",
        "--permission-mode", "bypassPermissions",
    ]
    if session_id:
        cmd += ["--resume", session_id]
        log.info("resuming Claude session %s", session_id)
    else:
        cmd += ["--append-system-prompt", SYSTEM_PROMPT]
        log.info("starting new Claude session")

    try:
        proc = subprocess.run(
            cmd, cwd=ROOT, input=user_msg, capture_output=True, text=True, timeout=CLAUDE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return ("⏱️ Claude timed out after "
                f"{CLAUDE_TIMEOUT // 60} min. Try a smaller ask."), session_id

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout).strip()
        log.warning("claude exited %d: %s", proc.returncode, err[-500:])
        return f"⚠️ Claude error: {err[-500:]}", session_id

    return _parse_claude_json(proc.stdout, session_id)


# --- main loop -------------------------------------------------------------

def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token, allowed_chat_id = _secrets()
    log.info("bot online; only chat_id=%s is allowed", allowed_chat_id)

    offset = _load_offset()
    log.info("resuming from update offset %d", offset)

    while True:
        updates = _get_updates(token, offset)
        for upd in updates:
            offset = max(offset, int(upd["update_id"]) + 1)
            _save_offset(offset)

            msg = upd.get("message")
            if not msg:
                continue
            chat_id = str(msg.get("chat", {}).get("id"))
            text = (msg.get("text") or "").strip()
            if not text:
                continue
            if chat_id != allowed_chat_id:
                log.info("ignored message from unauthorized chat_id=%s", chat_id)
                continue

            log.info("> %s", text[:200])
            _send_typing(token, chat_id)

            # "apply to <address>" runs the deterministic Funda submitter directly —
            # no LLM needed. Everything else falls through to the Claude assistant.
            if apply_command.parse_apply(text) is not None:
                try:
                    reply = apply_command.handle_apply(text)
                except Exception as e:  # noqa: BLE001
                    log.exception("apply failed")
                    reply = f"⚠️ Apply error: {e}"
                _send_text(token, chat_id, reply)
                log.info("< apply: %s", reply[:120])
                continue

            try:
                reply, session_id = _run_claude(text)
            except Exception as e:  # noqa: BLE001
                log.exception("dispatch failed")
                _send_text(token, chat_id, f"⚠️ Bot error: {e}")
                continue

            if session_id:
                # Preserve original created_at on resume, refresh on new sessions.
                existing = _load_session()
                if existing and existing.get("session_id") == session_id and _active_session_id():
                    created_at = datetime.fromisoformat(existing["created_at"])
                else:
                    created_at = datetime.now(timezone.utc)
                _save_session(session_id, created_at)

            _send_text(token, chat_id, reply)
            log.info("< sent %d chars", len(reply))


if __name__ == "__main__":
    sys.exit(main())
