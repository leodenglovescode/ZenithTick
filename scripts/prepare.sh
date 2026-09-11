#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
EXPECTED_DIR="/opt/zenitick"
CONFIG_DIR="/etc/zenitick"
CONFIG_FILE="${CONFIG_DIR}/zenitick.env"

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

if [[ "$#" -gt 1 ]]; then
  echo "Usage: sudo ${PROJECT_DIR}/scripts/prepare.sh [PI_LAN_IP]" >&2
  exit 1
fi

if [[ "$#" -eq 1 ]]; then
  BIND_ADDRESS="$1"
else
  echo "IPv4 addresses currently assigned to this Pi:"
  ip -4 -o address show scope global | awk '{ print "  " $4 }'
  read -r -p "Private LAN IPv4 address for ZenithTick: " BIND_ADDRESS
fi

if ! python3 - "${BIND_ADDRESS}" <<'PY'
import ipaddress
import sys

try:
    address = ipaddress.IPv4Address(sys.argv[1])
except ipaddress.AddressValueError:
    raise SystemExit(1)

networks = (
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
)
raise SystemExit(0 if any(address in network for network in networks) else 1)
PY
then
  echo "${BIND_ADDRESS} is not a private RFC1918 IPv4 address." >&2
  exit 1
fi

if ! ip -4 -o address show | awk -v expected="${BIND_ADDRESS}/" '
  index($4, expected) == 1 { found = 1 }
  END { exit !found }
'; then
  echo "This Pi does not currently own ${BIND_ADDRESS}; refusing to configure it." >&2
  exit 1
fi

echo "Installing the minimal Python runtime..."
apt-get update
apt-get install --no-install-recommends python3-venv ca-certificates

echo "Creating the isolated Python environment..."
python3 -m venv "${PROJECT_DIR}/.venv"
"${PROJECT_DIR}/.venv/bin/pip" install --upgrade pip
"${PROJECT_DIR}/.venv/bin/pip" install -r "${PROJECT_DIR}/requirements.txt"

echo "Writing the explicit LAN-only bind configuration..."
install -d -m 0755 "${CONFIG_DIR}"
install -m 0644 /dev/null "${CONFIG_FILE}"
printf 'ZENITICK_BIND=%s\nZENITICK_PORT=8080\n' "${BIND_ADDRESS}" > "${CONFIG_FILE}"

echo
echo "Preparation complete. No service was installed or started."
echo "Configured dashboard address: http://${BIND_ADDRESS}:8080"
echo "Next, run this without sudo:"
echo "  ${PROJECT_DIR}/scripts/run-foreground.sh"
