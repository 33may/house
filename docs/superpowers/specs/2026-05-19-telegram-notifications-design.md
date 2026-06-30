# Telegram notifications & updates — design

- **Date:** 2026-05-19
- **Status:** approved in brainstorming — revised after the "vault is source of truth" reframe
- **Project:** Funda house-hunt tracker (`/Users/may/Documents/may/house`)

## Problem

The tracker runs two automations — the Funda poll (`run.py`, every 20 min) and the
Gmail sync (`gmail-sync`, after the laptop wakes). The only notification is an
ephemeral macOS desktop banner fired by `run.py`; `gmail-sync` notifies nothing at
all. The user is often away from the laptop, so updates are missed. They want to be
reliably reached — on their phone — about new houses and status changes.

## Design principle — Telegram mirrors the vault

The Obsidian vault (`houses/*.md`) is the **single source of truth**. Telegram is a
**read-only echo** of it: whenever an automation adds something to the vault — a new
house page, or an update to an existing page — a short copy of that same data is
sent to Telegram. Nothing originates in Telegram, and a Telegram message never
contains anything that is not in the vault.

The practical consequence: **message content is sourced from the vault page**, not
from the upstream Funda API objects. A new house's message is built by reading the
`.md` page that `notegen` just created — including its `status` field, which the raw
Funda object does not have.

The one exception is **failure alerts** — operational messages that tell the user an
automation is down. They are not vault data, but the user explicitly wants them.

## Decisions (from brainstorming)

| Question | Decision |
|---|---|
| Channel | **Telegram only** |
| Events | **All four:** new listings · viewing progress · rejections/sold · needs-attention & failures |
| Cadence | **Instant** — one message per automation run that has news |
| Bot | A **fresh dedicated** Telegram bot for the tracker |

## Approach

**Approach A — a shared Python sender module.** One module, `telegram_notify.py`,
owns the Telegram API call and the token. `run.py` imports it directly. The
`gmail-sync` Claude command writes its echo to a file, and its wrapper script
`gmail-sync.sh` sends that file through the same module. One implementation of
"send to Telegram", one place that reads the token, one place to test.

Rejected alternatives:

- **B — shell sender** (`tg-send.sh` that `curl`s Telegram): makes `run.py`, the main
  producer, shell out awkwardly, and adds a `curl` dependency.
- **C — event queue** (producers append events, a separate drainer sends them): adds
  retry robustness, but a queue + drainer + its own schedule is disproportionate
  machinery for a few messages a day. YAGNI.

## Components

| File | Change |
|---|---|
| `funda_tracker/telegram_notify.py` | **NEW** — the sender module (interface below). No new dependencies: stdlib `urllib` for the HTTP POST, existing `PyYAML` to read secrets and house-page frontmatter. |
| `funda_tracker/notify.py` | **REMOVED** — the macOS desktop banner, superseded by Telegram. |
| `run.py` | Drop the `notify` import. Collect the **paths** of pages created this run; on success → `send(format_new_pages(paths))`. On `FundaError` → a throttled failure message. |
| `.claude/commands/gmail-sync.md` | New final step: if the run changed the vault, `Write` a short echo of those page changes to `logs/gmail-sync-message.txt`. Add `Write` to the command's `allowed-tools`. |
| `gmail-sync.sh` | Before the run: delete `logs/gmail-sync-message.txt`. After a successful run: if that file is non-empty, send it via `telegram_notify --file`. On a failed run (`claude -p` exits non-zero): send a failure message. Add `Write` to the headless `--allowedTools`. |
| `secrets.yaml` | **NEW**, git-ignored — holds the bot token and chat ID. |
| `secrets.example.yaml` | **NEW**, committed — a template with placeholder values. |
| `.gitignore` | Add `secrets.yaml`. |
| `tests/test_telegram_notify.py` | **NEW** — unit tests for the formatters and the no-secrets no-op. |
| `README.md` | Document the Telegram setup and the notification behaviour. |

## Data flow

```
New house:    run.py ──► notegen writes houses/<id>-<slug>.md
                     ──► telegram_notify reads that page ──► send() ──► Telegram

Page update:  gmail-sync command edits houses/<id>-<slug>.md
                     ──► writes logs/gmail-sync-message.txt (echo of the edit)
              gmail-sync.sh ──► telegram_notify --file ──────────────► Telegram
```

Both producers send only what was written to the vault: `run.py` reads back the
pages it created; the `gmail-sync` command echoes the status change and process-log
line it appended.

## Message formats

All messages are **plain text** — no Markdown or HTML parse mode. Telegram
auto-links raw URLs, so plain text gives clickable Funda links with zero escaping
bugs. Examples:

```
🆕 1 new house on Funda

🏠 Beneluxlaan 35, Tilburg
€ 325.000 · 125 m² · 5 rooms · label D
🆕 New
https://www.funda.nl/detail/koop/tilburg/huis-beneluxlaan-35/43321896/
```

```
📬 House updates

📅 Coba Pulskenslaan 9 — 📨 Viewing requested → 📅 Viewing booked
❌ Generaal de Wetstraat 35 — 📨 Viewing requested → ❌ Rejected (slots full)
⚠️ Boekweitstraat 19 — broker asked a question, no status change
```

```
⚠️ Funda poll failed — will retry in 20 min.
FundaError: <short reason>
```

The new-house message is built by reading each created page's YAML frontmatter
(`address`, `city`, `price`, `m2`, `rooms`, `energy_label`, `status`, `url`); if more
than 10 are new in one poll it lists 10 and adds an `…and N more` line. The
Gmail-sync message is composed by the `gmail-sync` command, which knows exactly what
it changed: one header line plus one line per page it touched, each line mirroring
the status transition and/or the process-log entry it wrote to that page.

## `telegram_notify.py` — interface

- `send(text: str) -> bool` — POST `text` to the Telegram `sendMessage` API for the
  configured chat. Returns `True` on success. **Never raises.** If `secrets.yaml` is
  missing or incomplete it is a silent no-op that logs a warning and returns `False`.
- `send_throttled(text: str, key: str, min_gap_seconds: int) -> bool` — like `send`,
  but sends at most once per `min_gap_seconds` for the given `key`, tracked by a
  stamp file `logs/.notify-<key>`. Used for failure messages.
- `format_new_pages(paths) -> str` — builds the new-houses message by reading the
  YAML frontmatter of each created house page.
- `format_failure(what: str, detail: str) -> str` — builds a failure message.
- `_read_frontmatter(path) -> dict` — internal helper; parses a house page's YAML
  frontmatter, returns `{}` if the file is unreadable or malformed.
- CLI — `python3 -m funda_tracker.telegram_notify`:
  - `--file PATH` — send the contents of `PATH` (used by `gmail-sync.sh`).
  - `--probe` — call the Telegram `getUpdates` API and print recent chat IDs; a
    setup helper for capturing the chat ID.
  - `TEXT` — send the literal argument as a message.
- Reads `secrets.yaml` from the project root.

## Configuration

`secrets.yaml` (git-ignored, never committed):

```yaml
telegram_bot_token: "123456789:ABCdefGhIJKlmNoPQRstuVWxyz"
telegram_chat_id: "987654321"
```

`secrets.example.yaml` (committed) carries the same keys with placeholder values and
a comment explaining how to obtain each. Notifications are considered enabled when
`secrets.yaml` exists and both keys are non-empty — there is no separate on/off flag.

## Error handling

- Every Telegram send is **best-effort**: network or API failures are logged, never
  raised. A poll or sync never breaks because Telegram was unreachable.
- Missing/incomplete `secrets.yaml` → `send()` is a silent no-op.
- Funda-poll failures: `run.py` reports them with `send_throttled(key="funda-fail",
  min_gap_seconds=10800)` — at most one failure message per 3 hours, so a Funda
  outage cannot spam the user.
- Gmail-sync failures: `gmail-sync.sh` sends a one-off message when `claude -p` exits
  non-zero. (It already retries on the next wake.)
- A poll or sync with no news sends nothing.

## Testing

`tests/test_telegram_notify.py`:

- `format_new_pages` — given temporary house pages written into `tmp_path`, the
  output contains each address, price, energy label, `status`, and URL, and the
  correct count in the header; 13 pages produce a `…and 3 more` line.
- `format_failure` — the output contains the `what` and `detail` text.
- `send()` with no `secrets.yaml` present → returns `False` and raises nothing.

The HTTP call itself is not unit-tested (same decision as `translate.py`, whose
network path is also left untested).

## Setup — the one step that needs the user

1. In Telegram, message **@BotFather** → `/newbot` → choose a name → receive a token.
2. The user provides the token; it is written into `secrets.yaml`.
3. The user sends the new bot any message (so it has an update to read).
4. Run `python3 -m funda_tracker.telegram_notify --probe` → read the chat ID from
   the output and write it into `secrets.yaml`.
5. Send a test message to confirm end-to-end delivery.

## Out of scope (YAGNI)

- Price-change detection on already-tracked houses — `run.py` only diffs *new*
  listing IDs; detecting changes on seen houses is a separate feature.
- Echoing the user's *own* manual edits to the vault — only automation writes are
  echoed; there is no filesystem watcher.
- Keeping the macOS desktop banner — `notify.py` is removed.
- Daily-digest mode — the cadence is instant, one message per run.
- An event queue with retry.
- Multiple recipients / multiple chats.
