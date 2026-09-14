#!/usr/bin/env bash
# Deploy from a clone ON the VM (run as user claude): sync app/ into the service directory and restart.
# Counterpart of deploy.sh, which does the same over ssh from a workstation. If you edit on the VM, treat that clone
# as canonical: a workstation checkout must `git pull` before using deploy.sh or it will roll the VM back.
#
# If you run this from inside a voice-app chat session, the restart kills that session: make it your last action,
# or pass --no-restart for static-only changes (JS/HTML/CSS are served live; config.json and *.py need the restart).
set -euo pipefail
cd "$(dirname "$0")"
DEST=${DEST:-/home/claude/voice-app}
rsync -a --delete \
  --exclude venv --exclude data --exclude token --exclude .env --exclude __pycache__ --exclude 'smoke*.py' \
  app/ "$DEST"/
echo "synced app/ -> $DEST"
[[ "${1:-}" == "--no-restart" ]] && { echo "not restarted"; exit 0; }
sudo systemctl restart voice-app && sleep 2 && systemctl is-active voice-app \
  && curl -s -o /dev/null -w "health %{http_code}\n" http://127.0.0.1:8770/health
