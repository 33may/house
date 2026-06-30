# Deploying to the maylenovo box

Dev on the Mac → run everything on the **maylenovo** Lenovo laptop (Ubuntu).
Versioned with git; the box pulls `origin/main` on a timer, tests, and restarts
services only on green. See the full design in
`docs/superpowers/specs/2026-06-30-box-deployment-design.md`.

## Topology

```
Mac (dev) --git push--> GitHub (origin) <--git fetch (loop, 3 min)-- maylenovo box (prod, runs all services)
```

## What lives where

| | In git (GitHub) | Box-only (gitignored) |
|---|---|---|
| Code | `funda_tracker/`, `run.py`, `gmail-sync.sh`, `deploy/`, `tests/` | — |
| Secrets | — | `secrets.yaml`, `~/.config/funda/funda.env`, Chrome profile (`logs/funda-profile/`), claude/codex auth |
| House data | — | `houses/`, `daily/`, board, notes (owned by **Obsidian Sync**) |
| Runtime | — | `state.json`, `logs/` |

## Services (systemd user units)

| Unit | Type | Cadence | Does |
|---|---|---|---|
| `funda-poll.timer` | oneshot | 20 min | `run.py` — find new listings, write pages |
| `funda-gmail.timer` | oneshot | 6 h | `gmail-sync.sh` — broker email → vault |
| `funda-bot.service` | long-run | always | Telegram bot + Playwright auto-applier |
| `funda-deploy.timer` | oneshot | 3 min | `deploy.sh` — the git deploy loop |

## First-time setup

### A. Physical (you, at the box)
- Plug in to AC; Power settings: never suspend; lid-close = do nothing.
- `sudo apt install openssh-server`; note the LAN IP + username; add your Mac's SSH key to `~/.ssh/authorized_keys`.
- Generate an SSH key on the box and add it as a **deploy key (read)** on the GitHub repo.
- Enable GNOME **auto-login** (so `DISPLAY=:0` exists for the applier's Chrome after reboot).

### B. Automated
```bash
# on the box, as `may`
git clone git@github.com:33may/house.git ~/house   # or let bootstrap do it
bash ~/house/deploy/bootstrap.sh
```
This installs deps + Chrome, builds the venv, installs & enables all units, enables
linger, sets lid behavior, and starts the timers.

### C. Manual logins (only a human can do these)
1. **`secrets.yaml`** — copy your `telegram_bot_token` + `telegram_chat_id` file into `~/house/`.
2. **Funda / DataDome** — open Chrome on the box, log into Funda once so the persistent
   profile (`logs/funda-profile/`) carries the anti-bot clearance. Cannot be copied from the Mac.
3. **`claude` CLI** — install + `claude` login (the Gmail sync runs `claude -p` with the Gmail connector).
4. **`codex` CLI** — install + auth (the Telegram bot drives Codex, model `gpt-5.4`).
5. **Obsidian Sync** — install Obsidian, sign in, sync the vault into `~/house` so `houses/` etc. exist and round-trip.

## Daily use
```bash
# Deploy = just push from the Mac:
git push                      # box pulls within ~3 min, tests, restarts on green

systemctl --user list-timers              # see next runs
systemctl --user status funda-bot         # bot health
journalctl --user -u funda-deploy -n 50   # deploy loop log
tail -f ~/house/logs/deploy.log           # deploy decisions + alerts
```

A failed test run on a push **does not** take the tool dark: `deploy.sh` reverts the
working tree to the last-good commit, leaves services running, and sends a Telegram alert.

<!-- deploy pipeline verified live on maylenovo 2026-06-30 -->
