#!/bin/zsh
# Throttled launcher for the Claude Gmail sync prompt.
#
# Scheduled every 3 hours (systemd timer on the box; launchd on the Mac) — and once
# shortly after wake (a missed interval fires on wake). This script enforces the real
# cadence: it starts a sync only if the last successful one was more than 3 hours ago,
# so extra triggers (boot/wake) stay cheap.
#
# After a sync it sends a Telegram echo: the Codex prompt writes one to
# logs/gmail-sync-message.txt when it changed the vault; a failed run sends an alert.

set -u
# Portable PATH: user-local bins first, then Homebrew (mac) / system (linux), then inherited.
export PATH="$HOME/.local/bin:/opt/homebrew/opt/node@22/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

# PROJECT: env override (set by the box's funda.env) else the dir this script lives in.
PROJECT="${FUNDA_PROJECT:-$(cd "$(dirname "$0")" && pwd)}"
STAMP="$PROJECT/logs/gmail-sync.last"          # unix epoch of last successful sync
LOG="$PROJECT/logs/gmail-sync.log"
RUNLOG="$PROJECT/logs/gmail-sync-run.tmp"
RUNRAW="$PROJECT/logs/gmail-sync-raw.tmp"
MSG="$PROJECT/logs/gmail-sync-message.txt"     # Telegram echo written by the Codex prompt
MIN_GAP=10800                                  # 3 hours, in seconds
CLAUDE="${CLAUDE_BIN:-$(command -v claude || echo "$HOME/.local/bin/claude")}"
MODEL="sonnet"                                 # Anthropic model that runs the sync
PROMPT="$PROJECT/.claude/prompts/gmail-sync.md"
VENV_PY="$PROJECT/.venv/bin/python3"

cd "$PROJECT" || exit 0
mkdir -p "$PROJECT/logs"

now=$(date +%s)
when=$(date '+%Y-%m-%d %H:%M:%S')
dry_run=0
if [[ " ${*:-} " == *" dry-run "* ]]; then
  dry_run=1
fi

if (( dry_run == 0 )) && [[ -f "$STAMP" ]]; then
  last=$(cat "$STAMP" 2>/dev/null || echo 0)
  [[ "$last" =~ ^[0-9]+$ ]] || last=0
  gap=$(( now - last ))
  if (( gap < MIN_GAP )); then
    echo "$when  skip — last sync $(( gap / 60 )) min ago (< 6h)" >> "$LOG"
    exit 0
  fi
fi

# Clear any stale echo so a fresh one is sent only if this run writes one.
rm -f "$MSG"

rm -f "$RUNLOG" "$RUNRAW"
# claude -p reads the prompt from stdin, prints the final report to stdout
# (-> RUNLOG) and tool/diagnostic noise to stderr (-> RUNRAW).
if (( dry_run == 1 )); then
  echo "$when  running Claude Gmail sync (dry-run) ..." >> "$LOG"
  { echo "DRY_RUN=1"; echo; cat "$PROMPT"; } | "$CLAUDE" -p \
    --model "$MODEL" \
    --permission-mode bypassPermissions \
    > "$RUNLOG" 2> "$RUNRAW"
else
  echo "$when  running Claude Gmail sync ..." >> "$LOG"
  "$CLAUDE" -p \
    --model "$MODEL" \
    --permission-mode bypassPermissions \
    < "$PROMPT" > "$RUNLOG" 2> "$RUNRAW"
fi
rc=$?   # note: 'status' is a read-only special variable in zsh — do not use it
if [[ -s "$RUNLOG" ]]; then
  cat "$RUNLOG" >> "$LOG"
else
  cat "$RUNRAW" >> "$LOG"
fi
echo "" >> "$LOG"
if grep -q "Gmail access unavailable" "$RUNLOG" 2>/dev/null; then
  rc=2
fi

if (( rc == 0 )); then
  if (( dry_run == 0 )); then
    echo "$now" > "$STAMP"
  fi
  echo "$(date '+%Y-%m-%d %H:%M:%S')  done (ok)" >> "$LOG"
  if [[ -s "$MSG" ]]; then
    "$VENV_PY" -m funda_tracker.telegram_notify --file "$MSG" >> "$LOG" 2>&1
    echo "$(date '+%Y-%m-%d %H:%M:%S')  telegram echo sent" >> "$LOG"
  fi
  if (( dry_run == 0 )); then
    "$VENV_PY" -m funda_tracker.agenda_notify >> "$LOG" 2>&1
  fi
else
  if (( dry_run == 1 )); then
    echo "$(date '+%Y-%m-%d %H:%M:%S')  dry-run failed (exit $rc)" >> "$LOG"
  else
    echo "$(date '+%Y-%m-%d %H:%M:%S')  FAILED (exit $rc) — will retry next wake" >> "$LOG"
    "$VENV_PY" -m funda_tracker.telegram_notify \
      "⚠️ Gmail sync failed (exit $rc) — will retry next wake." >> "$LOG" 2>&1
  fi
fi
exit 0
