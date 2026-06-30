#!/usr/bin/env bash
# Funda deploy loop — pulls origin/main, tests, and (only if green) restarts services.
# Driven by funda-deploy.timer every few minutes. A failed test run NEVER takes the
# live tool dark: the working tree is reverted to the last-good commit and services
# are left running their previous code.
set -uo pipefail

PROJECT="${FUNDA_PROJECT:-$HOME/house}"
BRANCH="${FUNDA_BRANCH:-main}"
cd "$PROJECT" || { echo "no project dir $PROJECT"; exit 1; }

mkdir -p "$PROJECT/logs"
LOG="$PROJECT/logs/deploy.log"
PY="$PROJECT/.venv/bin/python"
LOCK="$PROJECT/logs/applier.lock"

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "$(ts)  $*" >> "$LOG"; }
notify() { "$PY" -m funda_tracker.telegram_notify "$1" >> "$LOG" 2>&1 || true; }

git fetch -q origin "$BRANCH" || { log "git fetch failed"; exit 1; }
LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"

# Nothing new — quiet no-op (the common case every tick).
[ "$LOCAL" = "$REMOTE" ] && exit 0

# Never restart mid-application: the applier holds a lockfile while submitting.
if [ -f "$LOCK" ]; then
  log "update $REMOTE pending but applier is busy (lock) — retry next tick"
  exit 0
fi

log "new commit $REMOTE (was $LOCAL) — deploying"
git pull -q --ff-only origin "$BRANCH" || { log "ff-only pull failed — manual fix needed"; notify "⚠️ Funda deploy: fast-forward pull failed on the box. Manual fix needed."; exit 1; }

# Sync venv + deps (runtime + the test-gate deps).
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install -q -r requirements.txt >> "$LOG" 2>&1
[ -f requirements-dev.txt ] && ./.venv/bin/pip install -q -r requirements-dev.txt >> "$LOG" 2>&1

# TEST GATE — the only thing standing between a push and the live services.
if ! "$PY" -m pytest -q >> "$LOG" 2>&1; then
  log "TESTS FAILED on $REMOTE — reverting working tree to $LOCAL, services untouched"
  git reset --hard -q "$LOCAL"
  notify "⚠️ Funda deploy aborted: tests failed on ${REMOTE:0:7}. Reverted; previous version still live."
  exit 1
fi

log "tests green — restarting services"
systemctl --user daemon-reload
systemctl --user restart funda-bot.service >> "$LOG" 2>&1 || true
systemctl --user restart funda-poll.timer funda-gmail.timer >> "$LOG" 2>&1 || true
notify "✅ Funda deployed ${REMOTE:0:7} and restarted services."
log "deploy complete @ $REMOTE"
