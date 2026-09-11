#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
EXPECTED_DIR="/opt/zenitick"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this preparation step with sudo:" >&2
  echo "  sudo ${PROJECT_DIR}/scripts/prepare.sh" >&2
  exit 1
fi

if [[ "${PROJECT_DIR}" != "${EXPECTED_DIR}" ]]; then
  echo "ZenithTick must be cloned at ${EXPECTED_DIR}; found ${PROJECT_DIR}." >&2
  echo "The systemd unit intentionally uses the fixed production path." >&2
  exit 1
fi

echo "Installing the minimal Python runtime..."
apt-get update
apt-get install --no-install-recommends python3-venv ca-certificates

echo "Creating the isolated Python environment..."
python3 -m venv "${PROJECT_DIR}/.venv"
"${PROJECT_DIR}/.venv/bin/pip" install --upgrade pip
"${PROJECT_DIR}/.venv/bin/pip" install -r "${PROJECT_DIR}/requirements.txt"

echo
echo "Preparation complete. No service was installed or started."
echo "Next, run this without sudo:"
echo "  ${PROJECT_DIR}/scripts/run-foreground.sh"
