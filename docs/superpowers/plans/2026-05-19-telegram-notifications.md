# Telegram Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Echo every vault change — new house pages and page updates — to the user's phone via a dedicated Telegram bot.

**Architecture:** The Obsidian vault is the source of truth; Telegram is a read-only echo. A shared module `funda_tracker/telegram_notify.py` owns the Telegram API call and the token. `run.py` builds the new-house message by reading the pages `notegen` just created. The `gmail-sync` Claude command writes an echo of its page edits to a file, and its wrapper `gmail-sync.sh` sends that file through the same module. All sends are best-effort — a notification failure never breaks a poll or sync.

**Tech Stack:** Python 3.13 (stdlib `urllib` for HTTP, existing `PyYAML` for secrets and frontmatter), pytest, zsh, the Telegram Bot API.

---

> **⚠️ Git note:** This project is **not currently a git repository**. Each task ends
> with a Commit step for completeness. If you have not run `git init`, treat each
> Commit step as a checkpoint — verify the task's tests pass, then skip the `git`
> commands and move on.

> **Test command:** run tests with `.venv/bin/python3 -m pytest` from the project
> root `/Users/may/Documents/may/house`.

---

### Task 1: Config scaffolding

Creates the secrets template and protects the real secrets file.

**Files:**
- Create: `secrets.example.yaml`
- Modify: `.gitignore`

- [ ] **Step 1: Create `secrets.example.yaml`**

Create `/Users/may/Documents/may/house/secrets.example.yaml` with exactly:

```yaml
# Copy this file to secrets.yaml and fill in real values.
# secrets.yaml is git-ignored — never commit it.
#
# telegram_bot_token: create a bot by messaging @BotFather on Telegram (/newbot).
# telegram_chat_id:   send your new bot a message, then run
#                     .venv/bin/python3 -m funda_tracker.telegram_notify --probe
telegram_bot_token: "REPLACE_WITH_BOT_TOKEN"
telegram_chat_id: "REPLACE_WITH_CHAT_ID"
```

- [ ] **Step 2: Add `secrets.yaml` to `.gitignore`**

Append a new line `secrets.yaml` to `/Users/may/Documents/may/house/.gitignore`
(if it is not already present). The file should now contain a `secrets.yaml` entry
alongside the existing `.venv/`, `logs/`, `state.json` etc.

- [ ] **Step 3: Verify**

Run: `cd /Users/may/Documents/may/house && grep -c secrets.yaml .gitignore && ls secrets.example.yaml`
Expected: prints `1` then `secrets.example.yaml` — no errors.

- [ ] **Step 4: Commit**

```bash
git add secrets.example.yaml .gitignore
git commit -m "chore: add secrets template and git-ignore secrets.yaml"
```

---

### Task 2: telegram_notify.py — message formatters

Creates the module with its header and the pure formatter functions, test-first. The
new-house formatter reads house-page frontmatter — Telegram mirrors the vault.

**Files:**
- Create: `funda_tracker/telegram_notify.py`
- Test: `tests/test_telegram_notify.py`

- [ ] **Step 1: Write the failing tests**

Create `/Users/may/Documents/may/house/tests/test_telegram_notify.py` with exactly:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/test_telegram_notify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'funda_tracker.telegram_notify'`.

- [ ] **Step 3: Create the module with header and formatters**

Create `/Users/may/Documents/may/house/funda_tracker/telegram_notify.py` with exactly
this content (the full header includes imports used by later tasks — leave them in):

```python
"""Sends tracker notifications to Telegram.

The Obsidian vault is the source of truth; these messages are a short read-only
echo of what an automation added to it. Best-effort: a send failure (or a missing
secrets.yaml) is logged and never raised, so a Funda poll or Gmail sync is never
broken by a notification problem. Messages are plain text — Telegram auto-links
raw URLs, which avoids every Markdown/HTML escaping pitfall.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
SECRETS_PATH = ROOT / "secrets.yaml"
LOG_DIR = ROOT / "logs"

_API = "https://api.telegram.org"
_TIMEOUT = 10
_MAX_LISTINGS = 10


# --- message formatting -----------------------------------------------------

def _read_frontmatter(path) -> dict:
    """Parse the YAML frontmatter of a house page. Returns {} if unreadable."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        fm = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return {}
    return fm if isinstance(fm, dict) else {}


def _page_line(fm: dict) -> str:
    """Render one house page's frontmatter as a short plain-text block."""
    address = fm.get("address") or "House"
    city = fm.get("city") or ""
    price = fm.get("price")
    m2 = fm.get("m2")
    rooms = fm.get("rooms")
    label = fm.get("energy_label")
    status = fm.get("status") or ""
    url = fm.get("url") or ""

    facts = []
    if price:
        facts.append(f"€ {int(price):,}".replace(",", "."))
    if m2:
        facts.append(f"{m2} m²")
    if rooms:
        facts.append(f"{rooms} rooms")
    if label:
        facts.append(f"label {label}")

    lines = ["🏠 " + str(address) + (f", {city}" if city else "")]
    if facts:
        lines.append(" · ".join(facts))
    if status:
        lines.append(str(status))
    if url:
        lines.append(str(url))
    return "\n".join(lines)


def format_new_pages(paths) -> str:
    """Build the 'new houses on Funda' message by reading each created page."""
    paths = list(paths)
    n = len(paths)
    header = f"🆕 {n} new house{'s' if n != 1 else ''} on Funda"
    blocks = []
    for p in paths[:_MAX_LISTINGS]:
        fm = _read_frontmatter(p)
        if fm:
            blocks.append(_page_line(fm))
    text = header + "\n\n" + "\n\n".join(blocks)
    if n > _MAX_LISTINGS:
        text += f"\n\n…and {n - _MAX_LISTINGS} more"
    return text


def format_failure(what: str, detail: str = "") -> str:
    """Build a failure-alert message. (Operational — not vault data.)"""
    text = f"⚠️ {what}"
    if detail:
        text += f"\n{detail}"
    return text
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python3 -m pytest tests/test_telegram_notify.py -v`
Expected: PASS — all 4 tests green.

- [ ] **Step 5: Commit**

```bash
git add funda_tracker/telegram_notify.py tests/test_telegram_notify.py
git commit -m "feat: telegram_notify page-sourced message formatters"
```

---

### Task 3: telegram_notify.py — sending

Adds secrets loading, `send()`, and `send_throttled()`, test-first for the no-op guard.

**Files:**
- Modify: `funda_tracker/telegram_notify.py`
- Test: `tests/test_telegram_notify.py`

- [ ] **Step 1: Write the failing test**

Append this test to `/Users/may/Documents/may/house/tests/test_telegram_notify.py`:

```python


def test_send_without_secrets_is_noop(tmp_path, monkeypatch):
    import funda_tracker.telegram_notify as tn

    monkeypatch.setattr(tn, "SECRETS_PATH", tmp_path / "absent.yaml")
    assert tn.send("hello") is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_telegram_notify.py::test_send_without_secrets_is_noop -v`
Expected: FAIL — `AttributeError: module 'funda_tracker.telegram_notify' has no attribute 'send'`.

- [ ] **Step 3: Append the sending functions**

Append to `/Users/may/Documents/may/house/funda_tracker/telegram_notify.py`:

```python


# --- sending ----------------------------------------------------------------

def _read_secrets() -> dict:
    """Raw contents of secrets.yaml, or {} if it is missing/unreadable."""
    try:
        with open(SECRETS_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except OSError:
        return {}


def _load_secrets() -> tuple[str, str] | None:
    """Return (bot_token, chat_id), or None if either is missing."""
    data = _read_secrets()
    token = str(data.get("telegram_bot_token") or "").strip()
    chat_id = str(data.get("telegram_chat_id") or "").strip()
    if not token or not chat_id:
        return None
    return token, chat_id


def send(text: str) -> bool:
    """POST a plain-text message to the configured Telegram chat.

    Returns True on success. Never raises. A no-op returning False when
    secrets.yaml is missing or incomplete, or when text is empty.
    """
    if not (text or "").strip():
        return False
    secrets = _load_secrets()
    if secrets is None:
        log.warning("telegram: secrets.yaml missing/incomplete — notification skipped")
        return False
    token, chat_id = secrets
    url = f"{_API}/bot{token}/sendMessage"
    payload = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}
    ).encode()
    try:
        with urllib.request.urlopen(url, data=payload, timeout=_TIMEOUT) as resp:
            resp.read()
        return True
    except Exception as e:  # noqa: BLE001 — notifications must never break a run
        log.warning("telegram: send failed: %s", e)
        return False


def send_throttled(text: str, key: str, min_gap_seconds: int) -> bool:
    """Like send(), but sends at most once per min_gap_seconds for the given key."""
    stamp = LOG_DIR / f".notify-{key}"
    now = time.time()
    try:
        last = float(stamp.read_text())
    except (OSError, ValueError):
        last = 0.0
    if now - last < min_gap_seconds:
        log.info("telegram: '%s' throttled (last sent %.0fs ago)", key, now - last)
        return False
    ok = send(text)
    if ok:
        try:
            LOG_DIR.mkdir(exist_ok=True)
            stamp.write_text(str(now))
        except OSError as e:
            log.warning("telegram: could not write throttle stamp: %s", e)
    return ok
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python3 -m pytest tests/test_telegram_notify.py -v`
Expected: PASS — all 5 tests green.

- [ ] **Step 5: Commit**

```bash
git add funda_tracker/telegram_notify.py tests/test_telegram_notify.py
git commit -m "feat: telegram_notify send and send_throttled"
```

---

### Task 4: telegram_notify.py — command-line interface

Adds the `__main__` entrypoint so the module is runnable: `--probe`, `--file PATH`, or literal text. This is what `gmail-sync.sh` and the setup steps call.

**Files:**
- Modify: `funda_tracker/telegram_notify.py`

- [ ] **Step 1: Append the CLI**

Append to `/Users/may/Documents/may/house/funda_tracker/telegram_notify.py`:

```python


# --- command-line interface -------------------------------------------------

def _probe() -> int:
    """Print recent chat IDs from getUpdates — a setup helper for finding chat_id."""
    token = str(_read_secrets().get("telegram_bot_token") or "").strip()
    if not token:
        print("No telegram_bot_token in secrets.yaml — add it first.")
        return 1
    try:
        with urllib.request.urlopen(f"{_API}/bot{token}/getUpdates", timeout=_TIMEOUT) as resp:
            data = json.load(resp)
    except Exception as e:  # noqa: BLE001
        print(f"getUpdates failed: {e}")
        return 1
    chats: dict = {}
    for upd in data.get("result", []):
        msg = upd.get("message") or upd.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if chat.get("id") is not None:
            chats[chat["id"]] = (
                chat.get("first_name") or chat.get("title") or chat.get("username") or ""
            )
    if not chats:
        print("No chats yet. Send your bot a message in Telegram, then run --probe again.")
        return 1
    print("Recent chats — copy the right id into secrets.yaml as telegram_chat_id:")
    for cid, name in chats.items():
        print(f"  {cid}  {name}")
    return 0


def _main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not argv:
        print("usage: python3 -m funda_tracker.telegram_notify [--probe | --file PATH | TEXT]")
        return 2
    if argv[0] == "--probe":
        return _probe()
    if argv[0] == "--file":
        if len(argv) < 2:
            print("--file needs a path")
            return 2
        try:
            text = Path(argv[1]).read_text(encoding="utf-8").strip()
        except OSError as e:
            print(f"could not read {argv[1]}: {e}")
            return 1
        if not text:
            return 0
        return 0 if send(text) else 1
    return 0 if send(" ".join(argv)) else 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
```

- [ ] **Step 2: Verify the module imports and the CLI runs**

Run: `cd /Users/may/Documents/may/house && .venv/bin/python3 -m funda_tracker.telegram_notify`
Expected: prints the `usage:` line and exits (no traceback). It is fine that no
message is sent — `secrets.yaml` does not exist yet.

- [ ] **Step 3: Verify the full test suite still passes**

Run: `.venv/bin/python3 -m pytest -q`
Expected: PASS — all tests (existing + the 5 new) green.

- [ ] **Step 4: Commit**

```bash
git add funda_tracker/telegram_notify.py
git commit -m "feat: telegram_notify CLI (--probe, --file, text)"
```

---

### Task 5: Wire the Funda poll

Switches `run.py` from the macOS banner to a Telegram echo built from the pages it created, adds a throttled failure alert, and removes the now-dead `notify.py`.

**Files:**
- Modify: `run.py`
- Delete: `funda_tracker/notify.py`

- [ ] **Step 1: Update the imports**

In `/Users/may/Documents/may/house/run.py`, replace this line:

```python
from funda_tracker.notegen import write_note
```

with:

```python
from funda_tracker.notegen import note_path, write_note
```

and replace this line:

```python
from funda_tracker.notify import notify
```

with:

```python
from funda_tracker.telegram_notify import format_failure, format_new_pages, send, send_throttled
```

- [ ] **Step 2: Collect the paths of pages created this run**

In `run.py`, replace this block:

```python
                if dry_run:
                    log.info("[dry-run] would create page for %s — %s",
                             summary.id, listing.title)
                    created.append(listing)
                    continue

                if write_note(HOUSES_DIR, listing, is_enriched) is not None:
                    created.append(listing)
                state.mark_seen(summary.id)
```

with:

```python
                if dry_run:
                    log.info("[dry-run] would create page for %s — %s",
                             summary.id, listing.title)
                    created.append(note_path(HOUSES_DIR, listing))
                    continue

                path = write_note(HOUSES_DIR, listing, is_enriched)
                if path is not None:
                    created.append(path)
                state.mark_seen(summary.id)
```

- [ ] **Step 3: Add a throttled failure alert**

In `run.py`, replace this block:

```python
    except FundaError as e:
        log.error("Funda request failed — will retry next run: %s", e)
        return 1
```

with:

```python
    except FundaError as e:
        log.error("Funda request failed — will retry next run: %s", e)
        if not dry_run:
            send_throttled(
                format_failure(
                    "Funda poll failed — will retry in 20 min.",
                    f"{type(e).__name__}: {e}",
                ),
                key="funda-fail",
                min_gap_seconds=10800,
            )
        return 1
```

- [ ] **Step 4: Echo the new pages to Telegram**

In `run.py`, replace this block:

```python
    if created and not dry_run:
        addresses = ", ".join((lst.title or "house") for lst in created[:3])
        notify(
            f"{len(created)} new house{'s' if len(created) != 1 else ''} on Funda",
            addresses,
        )
```

with:

```python
    if created and not dry_run:
        send(format_new_pages(created))
```

- [ ] **Step 5: Delete the dead macOS notifier**

Run: `rm /Users/may/Documents/may/house/funda_tracker/notify.py`

(`run.py` no longer imports it, and nothing else references it.)

- [ ] **Step 6: Verify**

Run: `cd /Users/may/Documents/may/house && .venv/bin/python3 -m pytest -q && .venv/bin/python3 run.py --dry-run`
Expected: tests PASS, and the dry run finishes with `=== run finished ===` and exit
code 0 — no `ImportError`, no traceback. (A dry run sends nothing by design.)

- [ ] **Step 7: Commit**

```bash
git add run.py funda_tracker/notify.py
git commit -m "feat: Funda poll echoes new pages and failures to Telegram"
```

---

### Task 6: Wire the Gmail sync

Makes the `gmail-sync` command echo its vault edits to a file, and makes its wrapper send that file (and alert on failure).

**Files:**
- Modify: `.claude/commands/gmail-sync.md`
- Modify: `gmail-sync.sh`

- [ ] **Step 1: Allow the `Write` tool in the command**

In `/Users/may/Documents/may/house/.claude/commands/gmail-sync.md`, in the YAML
frontmatter, replace this line:

```
allowed-tools: Read, Edit, Glob, Grep, mcp__claude_ai_Gmail__search_threads, mcp__claude_ai_Gmail__get_thread
```

with:

```
allowed-tools: Read, Edit, Write, Glob, Grep, mcp__claude_ai_Gmail__search_threads, mcp__claude_ai_Gmail__get_thread
```

- [ ] **Step 2: Add the echo-writing step to the command**

Append the following new section to the **end** of
`/Users/may/Documents/may/house/.claude/commands/gmail-sync.md` (after the
`### 4. Report` section). The block below is wrapped in four backticks so its inner
fence renders — type a normal three-backtick fence in the actual file:

````markdown

### 5. Write the Telegram echo

If this run changed the vault — any house whose `status` you changed, or any page
you appended a process-log line to — use the `Write` tool to write a short echo of
those changes to `logs/gmail-sync-message.txt`. The wrapper `gmail-sync.sh` sends
this file to the user on Telegram. The message is a mirror of what you wrote to the
vault — never more than that.

Format — a header line, a blank line, then one line per page you touched. Each line
is the address and the change you made to that page:

```
📬 House updates

📅 Coba Pulskenslaan 9 — 📨 Viewing requested → 📅 Viewing booked
❌ Generaal de Wetstraat 35 — 📨 Viewing requested → ❌ Rejected (slots full)
⚠️ Boekweitstraat 19 — broker asked a question, no status change
```

Lead each line with the new status emoji (📅 / ❌ / 🆕), or ⚠️ if you made no status
change but logged something or flagged it. Keep each line to one short sentence in
English. Plain text only — no Markdown. If this run changed nothing in the vault, do
not create the file at all — the wrapper sends nothing when the file is absent.

In dry-run, do not write the file; instead print what it would contain.
````

- [ ] **Step 3: Update `gmail-sync.sh` to send the echo**

Replace the entire contents of `/Users/may/Documents/may/house/gmail-sync.sh` with:

```zsh
#!/bin/zsh
# Throttled launcher for the /gmail-sync Claude Code command.
#
# launchd runs this at login and once per hour — and once shortly after the Mac
# wakes from sleep (a missed interval fires on wake), i.e. soon after the laptop
# is opened. This script enforces the real cadence: it starts a sync only if the
# last successful one was more than 4 hours ago, so opening the lid many times a
# day stays cheap.
#
# After a sync it sends a Telegram echo: /gmail-sync writes one to
# logs/gmail-sync-message.txt when it changed the vault; a failed run sends an alert.

set -u
export PATH="/Users/may/.local/bin:/opt/homebrew/opt/node@22/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

PROJECT="/Users/may/Documents/may/house"
STAMP="$PROJECT/logs/gmail-sync.last"          # unix epoch of last successful sync
LOG="$PROJECT/logs/gmail-sync.log"
MSG="$PROJECT/logs/gmail-sync-message.txt"     # Telegram echo written by /gmail-sync
MIN_GAP=14400                                  # 4 hours, in seconds
CLAUDE="/Users/may/.local/bin/claude"
VENV_PY="$PROJECT/.venv/bin/python3"

cd "$PROJECT" || exit 0
mkdir -p "$PROJECT/logs"

now=$(date +%s)
when=$(date '+%Y-%m-%d %H:%M:%S')

if [[ -f "$STAMP" ]]; then
  last=$(cat "$STAMP" 2>/dev/null || echo 0)
  [[ "$last" =~ ^[0-9]+$ ]] || last=0
  gap=$(( now - last ))
  if (( gap < MIN_GAP )); then
    echo "$when  skip — last sync $(( gap / 60 )) min ago (< 4h)" >> "$LOG"
    exit 0
  fi
fi

# Clear any stale echo so a fresh one is sent only if /gmail-sync writes one.
rm -f "$MSG"

echo "$when  running /gmail-sync ..." >> "$LOG"
"$CLAUDE" -p "/gmail-sync" \
  --permission-mode acceptEdits \
  --allowedTools "Read,Edit,Write,Glob,Grep,mcp__claude_ai_Gmail" \
  --model claude-sonnet-4-6 >> "$LOG" 2>&1
rc=$?   # note: 'status' is a read-only special variable in zsh — do not use it

if (( rc == 0 )); then
  echo "$now" > "$STAMP"
  echo "$(date '+%Y-%m-%d %H:%M:%S')  done (ok)" >> "$LOG"
  if [[ -s "$MSG" ]]; then
    "$VENV_PY" -m funda_tracker.telegram_notify --file "$MSG" >> "$LOG" 2>&1
    echo "$(date '+%Y-%m-%d %H:%M:%S')  telegram echo sent" >> "$LOG"
  fi
else
  echo "$(date '+%Y-%m-%d %H:%M:%S')  FAILED (exit $rc) — will retry next wake" >> "$LOG"
  "$VENV_PY" -m funda_tracker.telegram_notify \
    "⚠️ Gmail sync failed (exit $rc) — will retry next wake." >> "$LOG" 2>&1
fi
exit 0
```

- [ ] **Step 4: Verify the script is syntactically valid**

Run: `zsh -n /Users/may/Documents/may/house/gmail-sync.sh && echo "syntax ok"`
Expected: prints `syntax ok` — no errors. (A real run is exercised in Task 8; the
4-hour throttle will skip it now anyway.)

- [ ] **Step 5: Commit**

```bash
git add .claude/commands/gmail-sync.md gmail-sync.sh
git commit -m "feat: gmail-sync echoes its vault edits to Telegram"
```

---

### Task 7: Document it in the README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a Notifications section**

In `/Users/may/Documents/may/house/README.md`, add the following section immediately
before the `## Files` section. The block is wrapped in four backticks so its inner
fences render — type normal three-backtick fences in the actual file:

````markdown
## Notifications (Telegram)

The Obsidian vault is the source of truth; Telegram is a short read-only echo of it.
Whenever an automation adds to the vault, a copy goes to your phone:

- The **Funda poll** echoes every new house page it creates, plus a throttled alert
  (at most once per 3 h) if a poll fails.
- The **Gmail sync** echoes each page it updates — the status change and the
  process-log line — and flags anything that needs your attention.

One-time setup:

1. In Telegram, message **@BotFather**, send `/newbot`, and follow the prompts to
   get a **bot token**.
2. Copy the template and paste the token in:
   ```sh
   cp secrets.example.yaml secrets.yaml
   ```
3. Send your new bot any message, then capture your chat ID:
   ```sh
   .venv/bin/python3 -m funda_tracker.telegram_notify --probe
   ```
   Put the printed id into `secrets.yaml` as `telegram_chat_id`.
4. Test it:
   ```sh
   .venv/bin/python3 -m funda_tracker.telegram_notify "Test from the Funda tracker"
   ```

`secrets.yaml` is git-ignored — never commit it. If it is missing, notifications
are silently skipped and the tracker still runs normally.
````

- [ ] **Step 2: Update the Files table**

In `README.md`, in the `## Files` table, change the `funda_tracker/` row from:

```
| `funda_tracker/` | The package: config, fetcher, matcher, notegen, state, notify |
```

to:

```
| `funda_tracker/` | The package: config, fetcher, matcher, notegen, state, telegram_notify |
```

and add these two rows to the same table:

```
| `secrets.example.yaml` | Template for `secrets.yaml` (Telegram token + chat id) |
| `funda_tracker/telegram_notify.py` | Sends vault-change echoes to Telegram |
```

- [ ] **Step 3: Verify**

Run: `grep -c "Notifications (Telegram)" /Users/may/Documents/may/house/README.md`
Expected: prints `1`.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document Telegram notifications setup"
```

---

### Task 8: Bot setup & end-to-end test (interactive — needs the user)

This task cannot be done by a subagent alone — it needs the user to create the bot
in Telegram. Pause and walk the user through it.

**Files:**
- Create: `secrets.yaml` (git-ignored)

- [ ] **Step 1: User creates the bot**

Ask the user to open Telegram, message **@BotFather**, send `/newbot`, choose a
name and username, and paste back the **bot token** (looks like
`123456789:ABCdef...`).

- [ ] **Step 2: Create `secrets.yaml`**

Run: `cp /Users/may/Documents/may/house/secrets.example.yaml /Users/may/Documents/may/house/secrets.yaml`
Then edit `secrets.yaml` and set `telegram_bot_token` to the token from Step 1.
Leave `telegram_chat_id` as the placeholder for now.

- [ ] **Step 3: User messages the bot**

Ask the user to open the new bot in Telegram and send it any message (e.g. "hi").
This gives the bot an update to read.

- [ ] **Step 4: Capture the chat ID**

Run: `cd /Users/may/Documents/may/house && .venv/bin/python3 -m funda_tracker.telegram_notify --probe`
Expected: prints one or more `  <id>  <name>` lines. Edit `secrets.yaml` and set
`telegram_chat_id` to the id whose name matches the user.

- [ ] **Step 5: End-to-end send test**

Run: `cd /Users/may/Documents/may/house && .venv/bin/python3 -m funda_tracker.telegram_notify "✅ Funda tracker notifications are live."`
Expected: exit code 0, and the message arrives in the user's Telegram. If it does
not arrive, recheck the token and chat id in `secrets.yaml`.

- [ ] **Step 6: Confirm the producers are wired**

Run: `cd /Users/may/Documents/may/house && .venv/bin/python3 run.py`
Expected: a normal run. If the poll finds new houses, a `🆕 … new house(s) on
Funda` message arrives in Telegram; if it finds none, no message is sent (correct).
The Gmail-sync path is verified the next time `gmail-sync.sh` runs past its 4-hour
throttle — its echo send is already covered by the Step 5 test of the same
`telegram_notify` module.

- [ ] **Step 7: Done**

No commit — `secrets.yaml` is git-ignored and nothing else changed.

---

## Notes for the implementer

- **Source of truth:** Telegram messages are sourced from the vault — `run.py` reads
  back the pages it created; `gmail-sync` echoes the page edits it made. Never format
  a message from the raw Funda API objects.
- **DRY:** there is exactly one Telegram code path — `telegram_notify.send()`. Do not
  add a second one in `run.py` or the shell script.
- **YAGNI:** no message queue, no retry loop, no daily digest — out of scope per the
  spec.
- **Best-effort:** never let a notification failure raise out of `send()` /
  `send_throttled()`. The `except Exception` clauses are deliberate.
- The spec is at `docs/superpowers/specs/2026-05-19-telegram-notifications-design.md`.
