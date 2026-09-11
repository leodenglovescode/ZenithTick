#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
EXPECTED_DIR="/opt/zenitick"
UNIT_NAME="zenitick-dashboard.service"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this service installation step with sudo:" >&2
  echo "  sudo ${PROJECT_DIR}/scripts/install-service.sh" >&2
  exit 1
fi

if [[ "${PROJECT_DIR}" != "${EXPECTED_DIR}" ]]; then
  echo "ZenithTick must be installed at ${EXPECTED_DIR}; found ${PROJECT_DIR}." >&2
  exit 1
fi

if [[ ! -x "${PROJECT_DIR}/.venv/bin/gunicorn" ]]; then
  echo "Python environment not found. Run ${PROJECT_DIR}/scripts/prepare.sh first." >&2
  exit 1
fi

echo "This step installs and starts ${UNIT_NAME}."
read -r -p "Did the foreground dashboard and live GPS/chrony checks pass? [y/N] " confirmation
case "${confirmation}" in
  y|Y|yes|YES) ;;
  *)
    echo "Service installation cancelled. Complete the foreground verification first."
    exit 1
    ;;
esac

install -m 0644 "${PROJECT_DIR}/systemd/${UNIT_NAME}" "/etc/systemd/system/${UNIT_NAME}"
systemctl daemon-reload
systemctl enable --now "${UNIT_NAME}"
systemctl --no-pager --full status "${UNIT_NAME}"

echo
echo "ZenithTick is running at http://192.168.3.99:8080"
