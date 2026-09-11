#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_FILE="/etc/zenitick/zenitick.env"

if [[ "${EUID}" -eq 0 ]]; then
  echo "Run this check as your normal user, not with sudo." >&2
  exit 1
fi

if [[ ! -x "${PROJECT_DIR}/.venv/bin/gunicorn" ]]; then
  echo "Python environment not found. Run sudo ${PROJECT_DIR}/scripts/prepare.sh first." >&2
  exit 1
fi

if [[ ! -r "${CONFIG_FILE}" ]]; then
  echo "Deployment configuration not found. Run sudo ${PROJECT_DIR}/scripts/prepare.sh <PI_LAN_IP>." >&2
  exit 1
fi

set -a
source "${CONFIG_FILE}"
set +a
: "${ZENITICK_BIND:?ZENITICK_BIND is missing from ${CONFIG_FILE}}"
: "${ZENITICK_PORT:?ZENITICK_PORT is missing from ${CONFIG_FILE}}"

if ! ip -4 -o address show | awk -v expected="${ZENITICK_BIND}/" '
  index($4, expected) == 1 { found = 1 }
  END { exit !found }
'; then
  echo "This host does not currently own ${ZENITICK_BIND}; refusing to bind elsewhere." >&2
  exit 1
fi

if ss -H -ltn "sport = :${ZENITICK_PORT}" | grep -q .; then
  echo "TCP port ${ZENITICK_PORT} is already in use. Inspect it before continuing:" >&2
  echo "  sudo ss -ltnp 'sport = :${ZENITICK_PORT}'" >&2
  exit 1
fi

echo "Read-only upstream checks:"
chronyc -c tracking || echo "WARNING: chronyc tracking is currently unavailable." >&2
chronyc -c sources || echo "WARNING: chronyc sources are currently unavailable." >&2

echo
echo "Starting the foreground dashboard at http://${ZENITICK_BIND}:${ZENITICK_PORT}"
echo "Open that address from a LAN browser, verify the data, then press Ctrl-C."
echo "This check does not install or start a systemd service."

cd "${PROJECT_DIR}"
exec env \
  ZENITICK_HISTORY_DB="/tmp/zenitick-history.sqlite3" \
  "${PROJECT_DIR}/.venv/bin/gunicorn" \
  --config "${PROJECT_DIR}/web/gunicorn_config.py" \
  "web.app:create_app()"
