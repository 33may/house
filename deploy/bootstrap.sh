#!/usr/bin/env bash
# One-time (idempotent) bootstrap for the maylenovo Ubuntu box.
# Run AS the `may` user (not root; it uses sudo where needed):
#     bash ~/house/deploy/bootstrap.sh
#
# Safe to re-run. It does NOT touch secrets.yaml or the Obsidian-synced house data.
set -euo pipefail

PROJECT="${FUNDA_PROJECT:-$HOME/house}"
REPO="${FUNDA_REPO:-git@github.com:33may/house.git}"
USER_NAME="$(id -un)"

echo "==> 1/8 system dependencies"
sudo apt-get update -qq
sudo apt-get install -y git python3-venv python3-pip xvfb zsh curl

echo "==> 2/8 Google Chrome (real channel — needed for the DataDome bypass)"
if ! command -v google-chrome >/dev/null 2>&1; then
  tmp=$(mktemp /tmp/chrome-XXXX.deb)
  curl -fsSL -o "$tmp" https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
  sudo apt-get install -y "$tmp"
  rm -f "$tmp"
fi

echo "==> 3/8 clone / update repo at $PROJECT"
if [ ! -d "$PROJECT/.git" ]; then
  git clone "$REPO" "$PROJECT"
else
  git -C "$PROJECT" fetch -q origin main && git -C "$PROJECT" checkout -q main
fi
cd "$PROJECT"

echo "==> 4/8 python venv + deps"
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q -r requirements.txt
./.venv/bin/python -m playwright install-deps chromium 2>/dev/null || true

echo "==> 5/8 box env file"
mkdir -p "$HOME/.config/funda"
if [ ! -f "$HOME/.config/funda/funda.env" ]; then
  cp deploy/funda.env.example "$HOME/.config/funda/funda.env"
  echo "    wrote ~/.config/funda/funda.env — EDIT paths if your home isn't /home/may"
fi

echo "==> 6/8 install systemd user units"
mkdir -p "$HOME/.config/systemd/user"
cp deploy/systemd/*.service deploy/systemd/*.timer "$HOME/.config/systemd/user/"
systemctl --user daemon-reload

echo "==> 7/8 keep services alive without a login session, and ignore the lid"
sudo loginctl enable-linger "$USER_NAME"
sudo sed -i 's/^#\?HandleLidSwitch=.*/HandleLidSwitch=ignore/' /etc/systemd/logind.conf
sudo sed -i 's/^#\?HandleLidSwitchExternalPower=.*/HandleLidSwitchExternalPower=ignore/' /etc/systemd/logind.conf
sudo systemctl restart systemd-logind || true

echo "==> 8/8 enable + start services"
systemctl --user enable --now funda-poll.timer funda-gmail.timer funda-deploy.timer
systemctl --user enable --now funda-bot.service || \
  echo "    (bot did not start — likely missing secrets.yaml or codex/claude auth; see runbook)"

cat <<EOF

==> bootstrap done.
   Still MANUAL (see deploy/README.md):
     - drop secrets.yaml into $PROJECT
     - one-time Funda login in Chrome to seed the DataDome profile
     - authenticate the claude + codex CLIs (gmail sync + bot)
     - sign into Obsidian Sync and point the vault at $PROJECT
   Check status:  systemctl --user list-timers; systemctl --user status funda-bot
EOF
