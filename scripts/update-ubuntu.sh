#!/usr/bin/env bash
set -euo pipefail

# Pull latest code and restart the bot on Ubuntu.
# Usage: sudo ./scripts/update-ubuntu.sh [/opt/discord-bot]

INSTALL_DIR="${1:-/opt/discord-bot}"
SERVICE_NAME="discord-bot"
SERVICE_USER="discordbot"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0 [install-dir]"
  exit 1
fi

if [[ ! -d "${INSTALL_DIR}/.git" ]]; then
  echo "No git repo at ${INSTALL_DIR}. Use setup-ubuntu.sh for a fresh install."
  exit 1
fi

echo "Updating code..."
sudo -u "${SERVICE_USER}" git -C "${INSTALL_DIR}" pull

echo "Updating dependencies..."
"${INSTALL_DIR}/.venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"

echo "Restarting service..."
systemctl restart "${SERVICE_NAME}"
systemctl status "${SERVICE_NAME}" --no-pager
