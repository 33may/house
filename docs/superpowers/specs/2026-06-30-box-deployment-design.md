# Box Deployment — Design Spec

> **Linear:** MAY-162 — *Continuous deployment on local laptop server* (House Copilot, team May33)
> **Date:** 2026-06-30
> **Status:** Approved design — ready for implementation plan

## Goal

Develop on the **Mac**, run all services 24/7 on the **maylenovo box** (the "lavide" Lenovo laptop, Ubuntu). Versioning and deployment are managed entirely through **git** — never manual file copy. A push to GitHub propagates to the box automatically, gated by tests, without ever taking the live tool dark.

**Done when:**
- Push to `main` → box pulls → tests run → services restart, all automatic and single-trigger.
- `poll` + Telegram `bot` + `gmail` + calendar run as managed services that survive sleep / logout / reboot.
- A red test run never deploys; the old version stays live.
- The repo is a clean, shareable GitHub repo containing **no secrets and no personal house data**.

## Topology

```
  Mac (dev)  --git push-->  GitHub (origin, shareable)
                                  ^
                                  | git fetch (deploy loop, every 2-5 min)
                                  |
                          maylenovo box (Ubuntu, prod) -- runs all services
```

- **GitHub = origin.** Normal repo, shareable with friends.
- **Mac = dev.** Edit, commit, push. Run tests locally too.
- **Box = prod.** Pulls origin on a timer, deploys on change, runs the services. The box never receives pushes directly and exposes no inbound ports.

## 1. Repo & data boundary

`git init` the project, create GitHub repo `house`, set as `origin`.

**Committed (code):**
- `funda_tracker/`, `run.py`, `gmail-sync.sh`, `requirements.txt`
- `tests/`
- `deploy/` (new — scripts + systemd unit templates, see §4)
- `secrets.example.yaml`, `preferences.yaml`, `README.md`, `HOUSE_AGENT.md`, docs/

**Gitignored — box-only, never shared:**
- Secrets: `secrets.yaml`, Gmail OAuth token, the Playwright Chrome user-data profile.
- Runtime state: `state.json`, `logs/`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `.playwright-mcp/`.
- Agent-private: `.agent-memory/`, `.remember/`.
- **Obsidian-Sync–owned house data:** `houses/`, `daily/`, `meetings/`, `sessions/`, `tasks/`, `Houses Board.md`, `Today outreach *.md`. These live in the same directory tree but are owned by **Obsidian Sync**, not git.

The existing `.gitignore` already covers `.venv/ logs/ state.json __pycache__/ *.pyc .pytest_cache/ secrets.yaml .playwright-mcp/`; this spec **extends** it with the Obsidian dirs, the Chrome profile path, the Gmail token, `.agent-memory/`, and `.remember/`.

> **Note:** the code repo dir and the Obsidian-synced house dirs share one tree (`houses/` lives inside the project). This is fine — git ignores those paths while Obsidian Sync writes into them independently.

## 2. Path portability (prerequisite)

Code must run identically on Mac (`/Users/may/Documents/may/house`) and box (`/home/may/house`).

- `run.py` already resolves `ROOT` relatively — good.
- The **3 launchd plists hardcode `/Users/may/...`** and are macOS-only — they are replaced by systemd units (§3), not ported.
- **Action:** audit `funda_tracker/config.py` and `gmail-sync.sh` for any hardcoded `/Users/may` paths; parameterize via a single `.env` / config (`PROJECT_ROOT`, `VAULT_ROOT`) loaded at startup. Default to repo-relative when unset.

## 3. Service layer — systemd user units (replace the 3 plists)

Run as **systemd user services** for `may`, with `loginctl enable-linger may` so they survive logout and reboot.

| launchd plist | systemd replacement | schedule |
|---|---|---|
| `com.may.funda` (poll) | `funda-poll.service` + `funda-poll.timer` | every ~20 min |
| `com.may.funda-gmail` | `funda-gmail.service` + `funda-gmail.timer` | hourly |
| `com.may.funda-bot` | `funda-bot.service` (long-running) | always-on |

- Unit templates live in `deploy/systemd/` (committed), installed into `~/.config/systemd/user/` by bootstrap (§5).
- The **applier** is launched by `funda-bot.service`. Its Chrome uses the live desktop session (`DISPLAY=:0`), with **Xvfb** as fallback if no graphical session is present.
- `logind`: set `HandleLidSwitch=ignore` so lid-closed = still serving.

## 4. The deploy loop ("the loop")

`deploy/deploy.sh` (idempotent):
1. `git fetch origin`.
2. If `origin/main` == local `HEAD` → exit (no-op).
3. Else: `git pull` → sync venv (`pip install -r requirements.txt`).
4. **Run `pytest` (the 43 tests).**
5. **Green:** `systemctl --user daemon-reload` + `restart` the services.
   **Red:** abort before restart — old version stays live — log + send Telegram alert.

Driven by `funda-deploy.service` (oneshot) + `funda-deploy.timer` (every 2–5 min). Tests are the deploy gate; a bad push never takes the tool dark.

**Edge case — deploy mid-apply:** if the applier is mid-submission, `deploy.sh` skips the restart that cycle (lockfile check) and retries next tick, so a viewing request is never interrupted.

## 5. First-time bootstrap (one-time, documented)

`deploy/bootstrap.sh` + a `deploy/README.md` runbook:
- Install Ubuntu deps: `git python3-venv python3-pip xvfb`, **real Google Chrome** (`.deb`, needs `channel=chrome` for DataDome bypass).
- Clone repo to `/home/may/house`; create venv; `pip install -r requirements.txt`.
- Drop in `secrets.yaml` (copied manually from a secure source).
- Install + enable systemd units; `enable-linger`; set lid behavior; enable the deploy timer.

**Manual one-time (human, at the box):**
- Funda login in the box's Chrome to seed the **DataDome-cleared persistent profile** (cannot be reliably copied from the Mac — likely device-bound).
- Sign into **Obsidian Sync** and sync the vault to the deploy path so house-page writes propagate.

## 6. Known risks (tracked in spec)

- **DataDome profile** must be re-seeded on the box; copying the Mac profile may not carry clearance.
- **Obsidian Sync must run on the box** or the tracker writes house pages into a dir nothing syncs.
- **Laptop power:** must stay on AC and never suspend, else "always-on" fails.
- **Deploy mid-apply** interruption — mitigated by the lockfile skip (§4).
- **Secrets discipline:** the shareable repo must be verified clean of `secrets.yaml` / tokens / profile before first push.

## Out of scope

- GitHub Actions / cloud CI (tests run on the box; can add later).
- Direct push-to-box bare repo (rejected — we want a shareable GitHub repo).
- Multi-box / scaling beyond the single maylenovo laptop.
- Applier robustness / interaction-format work — that's MAY-163.

## Physical setup checklist (human, on the box — parallel track)

Power: on AC; never suspend; lid-close = do nothing.
Access: `openssh-server`; note LAN IP + username; add Mac SSH key to `authorized_keys`.
GitHub: box SSH key added as repo **deploy key** (read).
Deps: `git python3-venv python3-pip xvfb` + real Google Chrome `.deb`.
Desktop: enable GNOME **auto-login** (so `DISPLAY=:0` exists after reboot).
Obsidian: install + sign into Sync, sync vault to `/home/may/house`.
Ready: Funda creds (one-time login), a copy of `secrets.yaml`.
