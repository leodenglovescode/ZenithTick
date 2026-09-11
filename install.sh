#!/usr/bin/env bash
set -Eeuo pipefail

readonly REPOSITORY_URL="https://github.com/leodenglovescode/ZenithTick.git"
readonly APP_DIR="/opt/zenitick"
readonly CONFIG_DIR="/etc/zenitick"
readonly CONFIG_FILE="${CONFIG_DIR}/zenitick.env"
readonly REVISION_FILE="${CONFIG_DIR}/deployed-revision"
readonly STATE_DIR="/var/lib/zenitick"
readonly CONTROL_PATH="/usr/local/sbin/zenitickctl"
readonly SERVICE_NAME="zenitick-dashboard.service"
readonly UPDATE_SERVICE_NAME="zenitick-update.service"
readonly UPDATE_TIMER_NAME="zenitick-update.timer"
readonly DEFAULT_PORT="8989"

BIND_ARGUMENT=""
PORT_ARGUMENT=""
AUTO_UPDATE="yes"
ASSUME_YES="no"
PURGE_DATA="no"
AUTOMATIC="no"

log() {
  printf '\n==> %s\n' "$*"
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
ZenithTick installer and service manager

Usage:
  install.sh install [--bind ADDRESS] [--port PORT] [--no-auto-update]
  zenitickctl update [--automatic]
  zenitickctl uninstall [--purge] [--yes]
  zenitickctl status
  zenitickctl auto-update enable|disable|status

Actions:
  install       Install dependencies, application, configuration, and service.
  update        Fast-forward to the latest GitHub main branch and restart safely.
  uninstall     Remove the application and service; preserve history by default.
  status        Show service, update timer, revision, and dashboard address.
  auto-update   Enable, disable, or inspect the daily GitHub update timer.

Options:
  --bind ADDRESS       Exact private RFC1918 IPv4 address assigned to this Pi.
  --port PORT          Unprivileged dashboard port (default: 8989).
  --auto-update        Enable daily automatic updates (install default).
  --no-auto-update     Do not enable daily automatic updates.
  --automatic          Non-interactive update mode used by systemd.
  --purge              Also delete /var/lib/zenitick satellite history.
  --yes                Skip the uninstall confirmation.
EOF
}

require_root() {
  [[ "${EUID}" -eq 0 ]] || die "Run this action with sudo."
}

acquire_lock() {
  exec 9> /run/lock/zenitick-installer.lock
  flock -n 9 || die "Another ZenithTick install or update is already running."
}

read_config_value() {
  local key="$1"
  [[ -r "${CONFIG_FILE}" ]] || return 0
  awk -F= -v wanted="${key}" '$1 == wanted { print substr($0, index($0, "=") + 1); exit }' "${CONFIG_FILE}"
}

is_private_ipv4() {
  python3 - "$1" <<'PY'
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
}

is_assigned_ipv4() {
  ip -4 -o address show | awk -v expected="$1/" '
    index($4, expected) == 1 { found = 1 }
    END { exit !found }
  '
}

select_bind_address() {
  local existing candidate
  local -a candidates=()
  existing="$(read_config_value ZENITICK_BIND)"

  if [[ -n "${BIND_ARGUMENT}" ]]; then
    SELECTED_BIND="${BIND_ARGUMENT}"
  elif [[ -n "${existing}" ]]; then
    SELECTED_BIND="${existing}"
  else
    while IFS= read -r candidate; do
      if is_private_ipv4 "${candidate}"; then
        candidates+=("${candidate}")
      fi
    done < <(ip -4 -o address show scope global | awk '{ sub(/\/.*/, "", $4); print $4 }')

    if [[ "${#candidates[@]}" -eq 1 ]]; then
      SELECTED_BIND="${candidates[0]}"
      printf 'Using detected private LAN address: %s\n' "${SELECTED_BIND}"
    elif [[ "${#candidates[@]}" -gt 1 ]]; then
      printf 'Private IPv4 addresses assigned to this Pi:\n'
      printf '  %s\n' "${candidates[@]}"
      [[ -r /dev/tty ]] || die "Multiple private addresses found; rerun with --bind ADDRESS."
      read -r -p "Private LAN address for ZenithTick: " SELECTED_BIND < /dev/tty
    else
      die "No private RFC1918 IPv4 address is assigned to this Pi."
    fi
  fi

  is_private_ipv4 "${SELECTED_BIND}" || die "${SELECTED_BIND} is not a private RFC1918 IPv4 address."
  is_assigned_ipv4 "${SELECTED_BIND}" || die "This Pi does not currently own ${SELECTED_BIND}."
}

select_port() {
  local existing
  existing="$(read_config_value ZENITICK_PORT)"
  SELECTED_PORT="${PORT_ARGUMENT:-${existing:-${DEFAULT_PORT}}}"
  [[ "${SELECTED_PORT}" =~ ^[0-9]+$ ]] || die "Port must be an integer."
  (( SELECTED_PORT >= 1024 && SELECTED_PORT <= 65535 )) || die "Port must be between 1024 and 65535."
}

check_port_available() {
  local old_bind old_port candidate upper_bound confirmation attempt listener_pids pid
  old_bind="$(read_config_value ZENITICK_BIND)"
  old_port="$(read_config_value ZENITICK_PORT)"
  if ! ss -H -ltn "sport = :${SELECTED_PORT}" | grep -q .; then
    return 0
  fi

  if systemctl is-active --quiet "${SERVICE_NAME}"; then
    if [[ "${old_port}" == "${SELECTED_PORT}" ]] \
      && [[ "${old_bind}" == "${SELECTED_BIND}" || -z "${old_bind}" ]]; then
      printf 'Port %s belongs to the existing ZenithTick service; it will be replaced cleanly.\n' "${SELECTED_PORT}"
      return 0
    fi
  fi

  printf 'TCP port %s is already in use by:\n' "${SELECTED_PORT}" >&2
  ss -ltnp "sport = :${SELECTED_PORT}" >&2 || true

  if [[ -r /dev/tty ]]; then
    read -r -p "Stop the process(es) using port ${SELECTED_PORT}? [y/N] " confirmation < /dev/tty
    case "${confirmation}" in
      y|Y|yes|YES)
        listener_pids="$(fuser -n tcp "${SELECTED_PORT}" 2>/dev/null || true)"
        for pid in ${listener_pids}; do
          [[ "${pid}" =~ ^[0-9]+$ ]] || continue
          if (( pid <= 1 )); then
            printf 'Refusing to signal protected PID %s.\n' "${pid}" >&2
            continue
          fi
          kill -TERM "${pid}" 2>/dev/null || true
        done
        for attempt in {1..5}; do
          if ! ss -H -ltn "sport = :${SELECTED_PORT}" | grep -q .; then
            printf 'Port %s is now free.\n' "${SELECTED_PORT}"
            return 0
          fi
          sleep 1
        done
        printf 'Port %s was reopened, probably by a supervising service.\n' "${SELECTED_PORT}" >&2
        ;;
      *)
        printf 'The existing listener was left running.\n'
        ;;
    esac
  else
    printf 'No interactive terminal is available; the existing listener was left running.\n' >&2
  fi

  if [[ -n "${PORT_ARGUMENT}" ]]; then
    die "The explicitly requested port is occupied. Stop its owning service or choose another --port value."
  fi

  upper_bound=$(( SELECTED_PORT + 100 ))
  (( upper_bound > 65535 )) && upper_bound=65535
  for (( candidate = SELECTED_PORT + 1; candidate <= upper_bound; candidate++ )); do
    if ! ss -H -ltn "sport = :${candidate}" | grep -q .; then
      printf 'Default port %s is busy; using the next free port, %s.\n' "${SELECTED_PORT}" "${candidate}"
      SELECTED_PORT="${candidate}"
      return 0
    fi
  done

  die "No free port was found in the next 100 ports. Rerun with --port PORT."
}

install_dependencies() {
  log "Installing required Debian packages"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install --no-install-recommends ca-certificates curl git iproute2 psmisc python3-venv util-linux
}

validate_checkout() {
  local origin branch
  origin="$(git -C "${APP_DIR}" remote get-url origin 2>/dev/null || true)"
  case "${origin}" in
    "${REPOSITORY_URL}"|"https://github.com/leodenglovescode/ZenithTick"|"git@github.com:leodenglovescode/ZenithTick.git") ;;
    *) die "${APP_DIR} has an unexpected Git origin: ${origin:-none}" ;;
  esac
  branch="$(git -C "${APP_DIR}" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
  [[ "${branch}" == "main" ]] || die "The production checkout must remain on the main branch."
}

ensure_checkout() {
  log "Installing ZenithTick from GitHub"
  if [[ -d "${APP_DIR}/.git" ]]; then
    validate_checkout
    git -C "${APP_DIR}" diff --quiet || die "The production checkout has uncommitted changes."
    git -C "${APP_DIR}" diff --cached --quiet || die "The production checkout has staged changes."
    git -C "${APP_DIR}" fetch origin main
    git -C "${APP_DIR}" merge --ff-only origin/main
  elif [[ -e "${APP_DIR}" ]]; then
    die "${APP_DIR} already exists and is not a ZenithTick Git checkout."
  else
    git clone --branch main --depth 1 "${REPOSITORY_URL}" "${APP_DIR}"
  fi
}

install_python_environment() {
  log "Installing Python environment"
  if [[ ! -x "${APP_DIR}/.venv/bin/python" ]]; then
    python3 -m venv "${APP_DIR}/.venv"
  fi
  PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 "${APP_DIR}/.venv/bin/pip" install --upgrade pip
  PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 "${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"
}

write_configuration() {
  log "Writing LAN-only configuration"
  install -d -m 0755 "${CONFIG_DIR}"
  local temporary
  temporary="$(mktemp)"
  printf 'ZENITICK_BIND=%s\nZENITICK_PORT=%s\n' "${SELECTED_BIND}" "${SELECTED_PORT}" > "${temporary}"
  install -m 0644 "${temporary}" "${CONFIG_FILE}"
  rm -f -- "${temporary}"
}

install_project_files() {
  install -m 0755 "${APP_DIR}/install.sh" "${CONTROL_PATH}"
  install -m 0644 "${APP_DIR}/systemd/${SERVICE_NAME}" "/etc/systemd/system/${SERVICE_NAME}"
  install -m 0644 "${APP_DIR}/systemd/${UPDATE_SERVICE_NAME}" "/etc/systemd/system/${UPDATE_SERVICE_NAME}"
  install -m 0644 "${APP_DIR}/systemd/${UPDATE_TIMER_NAME}" "/etc/systemd/system/${UPDATE_TIMER_NAME}"
  systemctl daemon-reload
}

enable_update_timer() {
  systemctl enable --now "${UPDATE_TIMER_NAME}"
}

disable_update_timer() {
  systemctl disable --now "${UPDATE_TIMER_NAME}" 2>/dev/null || true
}

health_check() {
  local bind_address port attempt
  bind_address="$(read_config_value ZENITICK_BIND)"
  port="$(read_config_value ZENITICK_PORT)"
  log "Checking the dashboard service"
  for attempt in {1..20}; do
    if systemctl is-active --quiet "${SERVICE_NAME}" \
      && curl --noproxy '*' --fail --silent --show-error --max-time 2 "http://${bind_address}:${port}/api/status" > /dev/null; then
      printf 'ZenithTick is healthy at http://%s:%s\n' "${bind_address}" "${port}"
      return 0
    fi
    sleep 1
  done
  systemctl --no-pager --full status "${SERVICE_NAME}" || true
  journalctl -u "${SERVICE_NAME}" -n 30 --no-pager || true
  die "ZenithTick did not pass its local API health check."
}

record_deployed_revision() {
  local revision temporary
  revision="$(git -C "${APP_DIR}" rev-parse HEAD)"
  temporary="$(mktemp)"
  printf '%s\n' "${revision}" > "${temporary}"
  install -m 0644 "${temporary}" "${REVISION_FILE}"
  rm -f -- "${temporary}"
}

install_action() {
  require_root
  acquire_lock
  install_dependencies
  ensure_checkout
  select_bind_address
  select_port
  check_port_available
  install_python_environment
  write_configuration
  install_project_files

  log "Enabling ZenithTick"
  systemctl enable "${SERVICE_NAME}"
  systemctl restart "${SERVICE_NAME}"
  if [[ "${AUTO_UPDATE}" == "yes" ]]; then
    enable_update_timer
  else
    disable_update_timer
  fi
  health_check
  record_deployed_revision
  printf '\nManage this installation with: sudo zenitickctl status|update|uninstall\n'
}

update_action() {
  require_root
  acquire_lock
  [[ -d "${APP_DIR}/.git" ]] || die "ZenithTick is not installed at ${APP_DIR}."
  [[ -r "${CONFIG_FILE}" ]] || die "Deployment configuration is missing at ${CONFIG_FILE}."
  validate_checkout

  log "Checking GitHub for updates"
  git -C "${APP_DIR}" diff --quiet || die "The production checkout has uncommitted changes."
  git -C "${APP_DIR}" diff --cached --quiet || die "The production checkout has staged changes."
  git -C "${APP_DIR}" fetch origin main
  local current target deployed
  current="$(git -C "${APP_DIR}" rev-parse HEAD)"
  target="$(git -C "${APP_DIR}" rev-parse origin/main)"
  deployed="$(cat "${REVISION_FILE}" 2>/dev/null || true)"
  if [[ "${current}" == "${target}" && "${deployed}" == "${target}" ]]; then
    [[ "${AUTOMATIC}" == "yes" ]] || printf 'ZenithTick is already current at %s.\n' "${current:0:12}"
    return 0
  fi

  git -C "${APP_DIR}" merge --ff-only origin/main
  install_python_environment
  install_project_files
  systemctl restart "${SERVICE_NAME}"
  health_check
  record_deployed_revision
  printf 'Updated ZenithTick from %s to %s.\n' "${current:0:12}" "${target:0:12}"
}

confirm_uninstall() {
  [[ "${ASSUME_YES}" == "yes" ]] && return 0
  [[ -r /dev/tty ]] || die "Interactive confirmation unavailable; rerun with --yes."
  local confirmation
  read -r -p "Remove the ZenithTick service and application? [y/N] " confirmation < /dev/tty
  case "${confirmation}" in
    y|Y|yes|YES) ;;
    *) die "Uninstall cancelled." ;;
  esac
}

uninstall_action() {
  require_root
  acquire_lock
  confirm_uninstall

  log "Removing ZenithTick"
  systemctl disable --now "${UPDATE_TIMER_NAME}" 2>/dev/null || true
  systemctl disable --now "${SERVICE_NAME}" 2>/dev/null || true
  rm -f -- \
    "/etc/systemd/system/${SERVICE_NAME}" \
    "/etc/systemd/system/${UPDATE_SERVICE_NAME}" \
    "/etc/systemd/system/${UPDATE_TIMER_NAME}"
  systemctl daemon-reload
  systemctl reset-failed "${SERVICE_NAME}" "${UPDATE_SERVICE_NAME}" 2>/dev/null || true
  rm -rf -- "${APP_DIR}"
  rm -rf -- "${CONFIG_DIR}"

  if [[ "${PURGE_DATA}" == "yes" ]]; then
    rm -rf -- "${STATE_DIR}"
    printf 'Satellite history was permanently removed.\n'
  else
    printf 'Satellite history was preserved at %s.\n' "${STATE_DIR}"
  fi

  rm -f -- "${CONTROL_PATH}"
  printf 'ZenithTick was uninstalled. Debian packages shared with the system were retained.\n'
}

status_action() {
  local bind_address port revision service_state timer_enabled timer_state
  bind_address="$(read_config_value ZENITICK_BIND)"
  port="$(read_config_value ZENITICK_PORT)"
  revision="$(git -C "${APP_DIR}" rev-parse --short=12 HEAD 2>/dev/null || true)"
  service_state="$(systemctl is-active "${SERVICE_NAME}" 2>/dev/null || true)"
  timer_enabled="$(systemctl is-enabled "${UPDATE_TIMER_NAME}" 2>/dev/null || true)"
  timer_state="$(systemctl is-active "${UPDATE_TIMER_NAME}" 2>/dev/null || true)"

  printf 'Installation: %s\n' "$([[ -d "${APP_DIR}/.git" ]] && echo present || echo absent)"
  printf 'Revision:     %s\n' "${revision:-unknown}"
  if [[ -n "${bind_address}" && -n "${port}" ]]; then
    printf 'Dashboard:    http://%s:%s\n' "${bind_address}" "${port}"
  else
    printf 'Dashboard:    not configured\n'
  fi
  printf 'Service:      %s\n' "${service_state:-not-installed}"
  printf 'Auto-update:  %s / %s\n' \
    "${timer_enabled:-not-installed}" \
    "${timer_state:-not-installed}"
}

auto_update_action() {
  local operation="${1:-status}"
  case "${operation}" in
    enable)
      require_root
      acquire_lock
      [[ -f "${APP_DIR}/systemd/${UPDATE_TIMER_NAME}" ]] || die "ZenithTick is not installed."
      install_project_files
      enable_update_timer
      printf 'Daily automatic updates are enabled.\n'
      ;;
    disable)
      require_root
      acquire_lock
      disable_update_timer
      printf 'Daily automatic updates are disabled.\n'
      ;;
    status)
      systemctl --no-pager --full status "${UPDATE_TIMER_NAME}" || true
      ;;
    *) die "Unknown auto-update operation: ${operation}" ;;
  esac
}

parse_install_options() {
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --bind) [[ "$#" -ge 2 ]] || die "--bind requires an address"; BIND_ARGUMENT="$2"; shift 2 ;;
      --port) [[ "$#" -ge 2 ]] || die "--port requires a value"; PORT_ARGUMENT="$2"; shift 2 ;;
      --auto-update) AUTO_UPDATE="yes"; shift ;;
      --no-auto-update) AUTO_UPDATE="no"; shift ;;
      -h|--help) usage; exit 0 ;;
      *) die "Unknown install option: $1" ;;
    esac
  done
}

parse_update_options() {
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --automatic) AUTOMATIC="yes"; shift ;;
      -h|--help) usage; exit 0 ;;
      *) die "Unknown update option: $1" ;;
    esac
  done
}

parse_uninstall_options() {
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --purge) PURGE_DATA="yes"; shift ;;
      --yes) ASSUME_YES="yes"; shift ;;
      -h|--help) usage; exit 0 ;;
      *) die "Unknown uninstall option: $1" ;;
    esac
  done
}

main() {
  local action="${1:-help}"
  [[ "$#" -eq 0 ]] || shift
  case "${action}" in
    install) parse_install_options "$@"; install_action ;;
    update) parse_update_options "$@"; update_action ;;
    uninstall) parse_uninstall_options "$@"; uninstall_action ;;
    status) [[ "$#" -eq 0 ]] || die "status takes no options"; status_action ;;
    auto-update) auto_update_action "$@" ;;
    help|-h|--help) usage ;;
    *) usage >&2; die "Unknown action: ${action}" ;;
  esac
}

main "$@"
