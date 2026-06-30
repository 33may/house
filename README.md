# Funda house-hunt tracker

Polls [Funda](https://funda.nl) for listings matching your preferences and drops one
Obsidian page per new house into `houses/`, where you track that house yourself
(notes, status, process log).

## How it works

```
preferences.yaml  →  pyfunda search  →  diff vs state.json  →  enrich new listings
                                                                      ↓
         Telegram notification  ←  write houses/<id>-<slug>.md (status: New)
```

- **Data source:** the `pyfunda` library, which calls Funda's mobile-app JSON API.
  There is no official Funda API — this is unofficial and ToS-gray. Keep poll volume low.
- **De-dup:** `state.json` records every listing id already processed. The tracker
  **only creates pages — it never edits one that exists**, so your notes are always safe.
- **Tracking:** you move a house through its stages by editing the `status:` field:
  `🆕 New` → `📨 Viewing requested` → `📅 Viewing booked` → `🏠 Viewed` → `🎯 Offer made`,
  or `❌ Rejected`. `Houses Board.md` shows every house grouped by stage.

## Setup

```sh
cd /Users/may/Documents/may/house
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

1. Edit **`preferences.yaml`** — set your city, price, size, etc.
2. Test it without writing anything:
   ```sh
   .venv/bin/python3 run.py --dry-run
   ```
3. Do a real run:
   ```sh
   .venv/bin/python3 run.py
   ```
4. In Obsidian, install the **Dataview** plugin so `Houses Board.md` renders.

## Run it automatically (every 20 min)

The `com.may.funda.plist` schedules the tracker via macOS `launchd`:

```sh
cp com.may.funda.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.may.funda.plist
```

To stop it:

```sh
launchctl unload ~/Library/LaunchAgents/com.may.funda.plist
```

The Mac must be awake to poll — it will not run while asleep.

## Gmail sync — broker replies update the pages

A second automation reads your Gmail and moves a house's `status` forward when a
broker or Funda email arrives (viewing requested, scheduled, rejected, …).

- It is the **Codex Gmail sync prompt** (`.codex/prompts/gmail-sync.md`).
  Run it through `gmail-sync.sh`; for a preview, run Codex manually with the prompt and include `dry-run`.
- **`gmail-sync.sh`** runs it headless via `codex exec` and **throttles to one real
  sync per hour**.
- **`com.may.funda-gmail.plist`** triggers `gmail-sync.sh` at login and hourly — macOS
  also fires it shortly after the Mac wakes, so it syncs soon after you open the lid.

It never edits your `## Notes`, only ever moves `status` forward, and uses each page's
`## Process log` to avoid acting on the same email twice. The Gmail connector is
read-only — it reads mail but changes nothing in your inbox.

Current Codex caveat: the wrapper detects `Gmail access unavailable in Codex exec`
and treats that as a failed sync, so it will not advance the success timestamp until
the Codex Gmail connector is active in headless `codex exec` sessions.

Install:

```sh
cp com.may.funda-gmail.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.may.funda-gmail.plist
```

To stop it:

```sh
launchctl bootout gui/$(id -u)/com.may.funda-gmail
```

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

## Telegram bot — chat with the agent

Messages to the Telegram bot (`@funda33_bot`) spawn a Codex CLI session in this
repo, using the local ChatGPT/OpenAI plan login rather than Claude.

Only the chat id stored in `secrets.yaml` (`telegram_chat_id`) can talk to the bot;
other chats are ignored.

Install the launchd daemon:

```sh
cp com.may.funda-bot.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.may.funda-bot.plist
```

Stop / inspect:

```sh
launchctl bootout gui/$(id -u)/com.may.funda-bot
tail -f logs/telegram-bot.out.log
```

State files in `logs/`: `telegram-session.json` (current Codex thread id + creation time)
and `telegram-offset.json` (Telegram update-id checkpoint for crash safety).

## Apple Calendar push

Booked viewings auto-land in your **Apple Calendar** (calendar **Домашній**, default
30 min). The Gmail sync runs `python -m funda_tracker.calendar_push <house.md>` when
it sets `📅 Viewing booked`. The helper is idempotent — it stamps each event with a
`[house-tracker:<funda_id>]` marker in the description, so re-running never creates
duplicates. To push manually:

```sh
.venv/bin/python3 -m funda_tracker.calendar_push houses/<id>-<slug>.md
.venv/bin/python3 -m funda_tracker.calendar_push houses/... --duration 45 --calendar "Work"
```

macOS will prompt once for Calendar automation permission the first time it runs.

## Declining a house

Every house page has a **declined** boolean in frontmatter — an Obsidian checkbox
in the property panel. A house counts as **declined** when either:

- `declined: true` — you tick the checkbox in Obsidian, or
- `status: ❌ Rejected` — the Gmail sync reads a broker's "no".

Declined houses stay in `houses/` but the **Houses Board** filters them out of every
active stage and groups them under the **❌ Declined** section at the bottom — that's
where you see them. Their Funda id stays in `state.json`, so a later poll never
recreates the page.

## Files

| Path | Purpose |
|---|---|
| `preferences.yaml` | Your search criteria — the only file you normally edit |
| `houses/` | One Markdown page per house — your tracker notes |
| `Houses Board.md` | Dataview board grouping houses by status |
| `run.py` | Entry point (`--dry-run` to test) |
| `funda_tracker/` | The package: config, fetcher, matcher, notegen, state, telegram_notify |
| `funda_tracker/telegram_notify.py` | Sends vault-change echoes to Telegram |
| `funda_tracker/calendar_push.py` | Pushes 📅 Viewing booked into Apple Calendar (idempotent) |
| `funda_tracker/telegram_bot.py` | Long-poll bot that turns Telegram messages into Codex sessions (1h TTL) |
| `com.may.funda-bot.plist` | launchd daemon for the Telegram bot listener |
| `secrets.example.yaml` | Template for `secrets.yaml` (Telegram token + chat id) |
| `state.json` | Listing ids already processed (auto-managed) |
| `logs/` | Run logs |
| `com.may.funda.plist` | launchd schedule for the Funda poll |
| `.codex/prompts/gmail-sync.md` | Codex prompt — updates pages from broker email |
| `gmail-sync.sh` | Throttled headless launcher for Codex Gmail sync (one sync / 1h) |
| `com.may.funda-gmail.plist` | launchd schedule for the Gmail sync |

## Tests

```sh
.venv/bin/pip install pytest
.venv/bin/python3 -m pytest
```
