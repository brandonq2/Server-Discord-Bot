#!/usr/bin/env bash
set -euo pipefail

# Install and configure the bot on Ubuntu.
# Usage: sudo ./scripts/setup-ubuntu.sh [/opt/discord-bot]

INSTALL_DIR="${1:-/opt/discord-bot}"
SERVICE_NAME="discord-bot"
SERVICE_USER="discordbot"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0 [install-dir]"
  exit 1
fi

echo "Installing system packages..."
# Allow apt-get update to succeed even if a third-party repo is unavailable.
# All packages we need are in the standard Ubuntu repos.
if ! apt-get update 2>&1; then
  echo "Warning: one or more apt repositories failed to update."
  echo "This is usually a broken third-party source and will not affect the install."
  echo "Check /etc/apt/sources.list.d/ if you want to clean up the failing repo."
fi
apt-get install -y python3 python3-venv python3-pip git rsync

if ! id "${SERVICE_USER}" &>/dev/null; then
  echo "Creating service user: ${SERVICE_USER}"
  useradd --system --home-dir "${INSTALL_DIR}" --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

echo "Copying project to ${INSTALL_DIR}..."
mkdir -p "${INSTALL_DIR}"
rsync -a --delete \
  --exclude ".venv" \
  --exclude "__pycache__" \
  --exclude ".env" \
  "${PROJECT_DIR}/" "${INSTALL_DIR}/"

if [[ ! -f "${INSTALL_DIR}/.env" ]]; then
  cp "${INSTALL_DIR}/.env.example" "${INSTALL_DIR}/.env"
  echo ""
  echo "Created ${INSTALL_DIR}/.env — edit it and set DISCORD_TOKEN before starting the service."
fi

echo "Creating virtual environment..."
python3 -m venv "${INSTALL_DIR}/.venv"
"${INSTALL_DIR}/.venv/bin/pip" install --upgrade pip
"${INSTALL_DIR}/.venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"

chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"

echo "Installing systemd service..."
sed "s|/opt/discord-bot|${INSTALL_DIR}|g" "${INSTALL_DIR}/deploy/discord-bot.service" \
  > "/etc/systemd/system/${SERVICE_NAME}.service"

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"

echo ""
echo "Setup complete."
echo ""
echo "Next steps:"
echo "  1. Edit ${INSTALL_DIR}/.env and set DISCORD_TOKEN"
echo "  2. sudo systemctl start ${SERVICE_NAME}"
echo "  3. sudo systemctl status ${SERVICE_NAME}"
echo "  4. sudo journalctl -u ${SERVICE_NAME} -f"
