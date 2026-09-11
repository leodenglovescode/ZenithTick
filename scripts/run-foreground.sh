#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BIND_ADDRESS="192.168.3.99"
PORT="8080"

if [[ "${EUID}" -eq 0 ]]; then
  echo "Run this check as your normal user, not with sudo." >&2
  exit 1
fi

if [[ ! -x "${PROJECT_DIR}/.venv/bin/gunicorn" ]]; then
  echo "Python environment not found. Run sudo ${PROJECT_DIR}/scripts/prepare.sh first." >&2
  exit 1
fi

if ! ip -4 -o address show | grep -qE "[[:space:]]inet ${BIND_ADDRESS}/"; then
  echo "This host does not currently own ${BIND_ADDRESS}; refusing to bind elsewhere." >&2
  exit 1
fi

if ss -H -ltn "sport = :${PORT}" | grep -q .; then
  echo "TCP port ${PORT} is already in use. Inspect it before continuing:" >&2
  echo "  sudo ss -ltnp 'sport = :${PORT}'" >&2
  exit 1
fi

echo "Read-only upstream checks:"
chronyc -c tracking || echo "WARNING: chronyc tracking is currently unavailable." >&2
chronyc -c sources || echo "WARNING: chronyc sources are currently unavailable." >&2

echo
echo "Starting the foreground dashboard at http://${BIND_ADDRESS}:${PORT}"
echo "Open that address from a LAN browser, verify the data, then press Ctrl-C."
echo "This check does not install or start a systemd service."

cd "${PROJECT_DIR}"
exec env \
  ZENITICK_BIND="${BIND_ADDRESS}" \
  ZENITICK_PORT="${PORT}" \
  ZENITICK_HISTORY_DB="/tmp/zenitick-history.sqlite3" \
  "${PROJECT_DIR}/.venv/bin/gunicorn" \
  --workers 1 \
  --threads 4 \
  --timeout 15 \
  --bind "${BIND_ADDRESS}:${PORT}" \
  --access-logfile - \
  --error-logfile - \
  "web.app:create_app()"
