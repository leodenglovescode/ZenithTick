#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/opt/zenitick"
UNIT_NAME="zenitick-dashboard.service"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run updates with sudo:" >&2
  echo "  sudo ${PROJECT_DIR}/scripts/update.sh" >&2
  exit 1
fi

if [[ ! -d "${PROJECT_DIR}/.git" ]]; then
  echo "${PROJECT_DIR} is not a Git checkout. Reinstall it from GitHub first." >&2
  exit 1
fi

git -C "${PROJECT_DIR}" pull --ff-only
"${PROJECT_DIR}/.venv/bin/pip" install -r "${PROJECT_DIR}/requirements.txt"
install -m 0644 "${PROJECT_DIR}/systemd/${UNIT_NAME}" "/etc/systemd/system/${UNIT_NAME}"
systemctl daemon-reload
systemctl restart "${UNIT_NAME}"
systemctl --no-pager --full status "${UNIT_NAME}"
