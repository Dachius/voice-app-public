#!/usr/bin/env bash
# Sync app/ to the VM (ssh alias `dev`, service user `claude`) and restart the service. Excludes runtime state.
set -euo pipefail
cd "$(dirname "$0")"
rsync -az --delete \
  --exclude venv --exclude data --exclude token --exclude .env --exclude __pycache__ --exclude 'smoke*.py' \
  --rsync-path="sudo -u claude rsync" app/ dev:/home/claude/voice-app/
ssh dev 'sudo systemctl restart voice-app && sleep 2 && systemctl is-active voice-app && curl -s -o /dev/null -w "health %{http_code}\n" http://127.0.0.1:8770/health'
