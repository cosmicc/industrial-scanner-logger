#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-industrial-scanner-logger}"
API_SERVICE_NAME="${API_SERVICE_NAME:-${SERVICE_NAME}-api}"
INSTALL_DIR="${INSTALL_DIR:-/opt/industrial-scanner-logger}"
SERVICE_USER="${SERVICE_USER:-scannerlogger}"
SERVICE_GROUP="${SERVICE_GROUP:-$SERVICE_USER}"
CONFIG_FILE="/etc/industrial-scanner-logger.conf"
LEGACY_ENV_FILE="${LEGACY_ENV_FILE:-/etc/default/${SERVICE_NAME}}"
OUTPUT_DIR="${OUTPUT_DIR:-/scanner-logs}"
LOG_FILE="${LOG_FILE:-/var/log/industrial-scanner-logger.log}"
SCAN_DATA_LOG_DIR="${SCAN_DATA_LOG_DIR:-/var/log/industrial-scanner-logger}"
SCAN_DATA_LOG_PREFIX="${SCAN_DATA_LOG_PREFIX:-scanner-log-data}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-55256}"
PREFIX="${PREFIX:-Site_Shipped_Tracking}"
NO_READ_MESSAGE="${NO_READ_MESSAGE:-__NO_READ__}"
SUCCESS_LENGTH="${SUCCESS_LENGTH:-34}"
MAX_BARCODE_CHARS="${MAX_BARCODE_CHARS:-256}"
MAX_CLIENTS="${MAX_CLIENTS:-10}"
FRAME_IDLE_TIMEOUT="${FRAME_IDLE_TIMEOUT:-0.25}"
CLIENT_IDLE_TIMEOUT="${CLIENT_IDLE_TIMEOUT:-0}"
SHUTDOWN_TIMEOUT="${SHUTDOWN_TIMEOUT:-5}"
TRACKING_REPAIR_ENABLED="${TRACKING_REPAIR_ENABLED:-0}"
TCP_KEEPALIVE_IDLE="${TCP_KEEPALIVE_IDLE:-60}"
TCP_KEEPALIVE_INTERVAL="${TCP_KEEPALIVE_INTERVAL:-15}"
TCP_KEEPALIVE_PROBES="${TCP_KEEPALIVE_PROBES:-4}"
DEFAULT_POSTGRESQL_DSN="postgresql:///scannerlogger?host=/var/run/postgresql&user=scannerlogger"
POSTGRESQL_DSN="${POSTGRESQL_DSN:-${DEFAULT_POSTGRESQL_DSN}}"
POSTGRESQL_TABLE="${POSTGRESQL_TABLE:-scanner_logger.scan_events}"
POSTGRESQL_CONNECT_TIMEOUT="${POSTGRESQL_CONNECT_TIMEOUT:-3}"
POSTGRESQL_RETRY_INTERVAL="${POSTGRESQL_RETRY_INTERVAL:-30}"
LAST_SCANNER_ID="${LAST_SCANNER_ID:-}"
MANDATORY_SCANNER_IDS="${MANDATORY_SCANNER_IDS:-}"
CURRENT_SCAN_RATE_STALE_SECONDS="${CURRENT_SCAN_RATE_STALE_SECONDS:-60}"
API_ENABLED="${API_ENABLED:-1}"
API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"
API_ROOT_PATH="${API_ROOT_PATH:-/api}"
API_LOG_LEVEL="${API_LOG_LEVEL:-info}"
NGINX_ENABLED="${NGINX_ENABLED:-1}"
NGINX_SITE_NAME="${NGINX_SITE_NAME:-industrial-scanner-logger}"
NGINX_LISTEN="${NGINX_LISTEN:-80 default_server}"
NGINX_SERVER_NAME="${NGINX_SERVER_NAME:-_}"
NGINX_WEB_ROOT="${NGINX_WEB_ROOT:-/var/www/scanner-site}"
NGINX_DISABLE_DEFAULT_SITE="${NGINX_DISABLE_DEFAULT_SITE:-1}"
UPDATE_SERVICES_BIN="${UPDATE_SERVICES_BIN:-/usr/local/bin/update-services}"
REFRESH_APP_CONFIG_BIN="${REFRESH_APP_CONFIG_BIN:-/usr/local/bin/refresh-app-config}"
REFRESH_NGINX_BIN="${REFRESH_NGINX_BIN:-/usr/local/bin/refresh-nginx-config}"
START_SERVICE="${START_SERVICE:-1}"
OVERWRITE_CONFIG="${OVERWRITE_CONFIG:-0}"
APT_UPDATED=0

usage() {
    cat <<USAGE
Usage: sudo scripts/install.sh [options]

Install the Industrial Scanner Logger runtime, services, nginx API proxy, and UFW firewall.

Options:
  --service-name NAME       systemd service name [${SERVICE_NAME}]
  --api-service-name NAME   REST API systemd service name [${API_SERVICE_NAME}]
  --install-dir DIR         application install directory [${INSTALL_DIR}]
  --user USER               system user that runs the service [${SERVICE_USER}]
  --group GROUP             system group that runs the service [${SERVICE_GROUP}]
  --output-dir DIR          scanner CSV output directory [${OUTPUT_DIR}]
  --log-file PATH           troubleshooting log file [${LOG_FILE}]
  --scan-data-log-dir DIR   daily raw scan event log directory [${SCAN_DATA_LOG_DIR}]
  --scan-data-log-prefix PREFIX daily raw scan event log prefix [${SCAN_DATA_LOG_PREFIX}]
  --host HOST               receiver bind address [${HOST}]
  --port PORT               receiver TCP port [${PORT}]
  --prefix PREFIX           daily CSV filename prefix [${PREFIX}]
  --no-read-message TEXT    scanner no-read text [${NO_READ_MESSAGE}]
  --success-length NUMBER   numeric barcode length required for success [${SUCCESS_LENGTH}]
  --max-barcode-chars NUM   maximum accepted scanner frame length [${MAX_BARCODE_CHARS}]
  --max-clients NUMBER      maximum simultaneous scanner clients [${MAX_CLIENTS}]
  --frame-idle-timeout SEC  seconds before flushing a partial scanner frame [${FRAME_IDLE_TIMEOUT}]
  --client-idle-timeout SEC seconds before disconnecting an idle scanner client; 0 disables [${CLIENT_IDLE_TIMEOUT}]
  --shutdown-timeout SEC    seconds to wait for scanner threads on stop [${SHUTDOWN_TIMEOUT}]
  --enable-tracking-repair  repair likely truncated tracking scans using same-day successful prefixes
  --disable-tracking-repair disable tracking-number repair [default]
  --tcp-keepalive-idle SEC  idle seconds before TCP keepalive probes start [${TCP_KEEPALIVE_IDLE}]
  --tcp-keepalive-interval SEC seconds between TCP keepalive probes [${TCP_KEEPALIVE_INTERVAL}]
  --tcp-keepalive-probes NUM failed probes before a socket is considered dead [${TCP_KEEPALIVE_PROBES}]
  --postgresql-dsn DSN     PostgreSQL URI/DSN with no shell spaces [${POSTGRESQL_DSN}]
  --postgresql-table NAME  PostgreSQL table in schema.table format [${POSTGRESQL_TABLE}]
  --postgresql-connect-timeout SEC PostgreSQL connection timeout [${POSTGRESQL_CONNECT_TIMEOUT}]
  --postgresql-retry-interval SEC  retry delay after PostgreSQL failures [${POSTGRESQL_RETRY_INTERVAL}]
  --last-scanner-id ID     scanner IP last octet for the final outbound scanner [${LAST_SCANNER_ID:-not set}]
  --mandatory-scanner-ids IDS comma or space-separated scanner IDs that must stay connected [${MANDATORY_SCANNER_IDS:-none}]
  --current-scan-rate-stale-seconds SEC seconds before health scan-rate indicator turns red [${CURRENT_SCAN_RATE_STALE_SECONDS}]
  --enable-api             enable and start the REST API service [default]
  --disable-api            install but disable the REST API service
  --api-host HOST          REST API bind address [${API_HOST}]
  --api-port PORT          REST API TCP port [${API_PORT}]
  --api-root-path PATH     proxy root path for the REST API [${API_ROOT_PATH}]
  --api-log-level LEVEL    uvicorn log level [${API_LOG_LEVEL}]
  --enable-nginx           install and enable the nginx API proxy [default]
  --disable-nginx          skip nginx package and site configuration
  --nginx-site-name NAME   nginx site file name [${NGINX_SITE_NAME}]
  --nginx-listen VALUE     nginx listen value [${NGINX_LISTEN}]
  --nginx-server-name NAME nginx server_name value [${NGINX_SERVER_NAME}]
  --nginx-web-root DIR     document root for the future web interface [${NGINX_WEB_ROOT}]
  --keep-nginx-default-site keep Ubuntu's default nginx site enabled
  --refresh-app-config-bin PATH app config refresh helper path [${REFRESH_APP_CONFIG_BIN}]
  --refresh-nginx-bin PATH nginx refresh helper path [${REFRESH_NGINX_BIN}]
  --overwrite-config        replace an existing config file
  --no-start                install and enable the service, but do not start it now
  -h, --help                show this help

After install, edit receiver options in:
  ${CONFIG_FILE}
USAGE
}

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Missing required command: $1" >&2
        exit 1
    fi
}

apt_get_update_once() {
    if [[ "${APT_UPDATED}" -eq 0 ]]; then
        apt-get update
        APT_UPDATED=1
    fi
}

copy_project_tree() {
    python3 - "$1" "$2" <<'PY'
from pathlib import Path
import shutil
import sys


source = Path(sys.argv[1]).resolve()
destination = Path(sys.argv[2]).resolve()

excluded_names = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".test-output",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "scanner-logs",
}


def ignore_names(_directory, names):
    ignored = set()

    for name in names:
        if name in excluded_names:
            ignored.add(name)
        elif name.endswith(".egg-info"):
            ignored.add(name)
        elif name.endswith(".pyc"):
            ignored.add(name)
        elif ".backup-" in name:
            ignored.add(name)

    return ignored


shutil.copytree(source, destination, dirs_exist_ok=True, ignore=ignore_names)
PY
}

install_html_tree() {
    local source_dir="$1"
    local destination_dir="$2"

    if [[ ! -d "${source_dir}" ]]; then
        return
    fi

    python3 - "${source_dir}" "${destination_dir}" <<'PY'
from pathlib import Path
import os
import shutil
import sys


source = Path(sys.argv[1]).resolve()
destination = Path(sys.argv[2]).resolve()
touched_dirs = {destination}

destination.mkdir(parents=True, exist_ok=True)

for path in source.rglob("*"):
    if path.name in {".gitkeep", ".DS_Store"}:
        continue

    target = destination / path.relative_to(source)

    if path.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        touched_dirs.add(target)
    elif path.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        touched_dirs.add(target.parent)
        shutil.copy2(path, target)
        os.chown(target, 0, 0)
        os.chmod(target, 0o644)

for directory in sorted(touched_dirs, key=lambda item: len(item.parts)):
    os.chown(directory, 0, 0)
    os.chmod(directory, 0o755)
PY
}

escape_sed_replacement() {
    printf "%s" "$1" | sed "s/[&|]/\\\\&/g"
}

validate_api_root_path() {
    if [[ "${API_ROOT_PATH}" != /* || "${API_ROOT_PATH}" == "/" ]]; then
        echo "--api-root-path must start with / and must not be / when nginx is enabled." >&2
        exit 1
    fi

    API_ROOT_PATH="${API_ROOT_PATH%/}"
}

install_nginx_package() {
    if command -v nginx >/dev/null 2>&1; then
        return
    fi

    require_command apt-get

    echo "Installing nginx..."
    export DEBIAN_FRONTEND=noninteractive
    apt_get_update_once
    apt-get install -y nginx
}

install_postgresql_package() {
    if [[ "${POSTGRESQL_DSN}" != "${DEFAULT_POSTGRESQL_DSN}" ]] && command -v psql >/dev/null 2>&1; then
        return
    fi

    if command -v psql >/dev/null 2>&1 && systemctl list-unit-files postgresql.service >/dev/null 2>&1; then
        return
    fi

    require_command apt-get

    echo "Installing PostgreSQL..."
    export DEBIAN_FRONTEND=noninteractive
    apt_get_update_once
    apt-get install -y postgresql
}

run_as_postgres() {
    runuser -u postgres -- "$@"
}

configure_postgresql_database() {
    local schema_file="${INSTALL_DIR_REAL}/db/schema.sql"

    if [[ ! -f "${schema_file}" ]]; then
        echo "Missing PostgreSQL schema file: ${schema_file}" >&2
        exit 1
    fi

    if [[ "${POSTGRESQL_DSN}" == "${DEFAULT_POSTGRESQL_DSN}" ]]; then
        systemctl enable postgresql
        systemctl start postgresql

        if ! run_as_postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${SERVICE_USER}'" | grep -q 1; then
            run_as_postgres createuser --no-superuser --no-createdb --no-createrole "${SERVICE_USER}"
        fi

        if ! run_as_postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='scannerlogger'" | grep -q 1; then
            run_as_postgres createdb -O "${SERVICE_USER}" scannerlogger
        fi

        run_as_postgres psql -d scannerlogger -f "${schema_file}"
        return
    fi

    echo "Applying PostgreSQL schema with configured DSN..."
    psql "${POSTGRESQL_DSN}" -f "${schema_file}"
}

install_ufw_firewall() {
    require_command apt-get

    if ! command -v ufw >/dev/null 2>&1; then
        echo "Installing ufw..."
        export DEBIAN_FRONTEND=noninteractive
        apt_get_update_once
        apt-get install -y ufw
    fi

    echo "Configuring ufw firewall..."
    ufw --force reset
    ufw default deny incoming
    ufw default allow outgoing
    ufw allow 22/tcp
    ufw allow 55256/tcp
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw --force enable
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --service-name)
            SERVICE_NAME="$2"
            API_SERVICE_NAME="${SERVICE_NAME}-api"
            LEGACY_ENV_FILE="/etc/default/${SERVICE_NAME}"
            shift 2
            ;;
        --api-service-name)
            API_SERVICE_NAME="$2"
            shift 2
            ;;
        --install-dir)
            INSTALL_DIR="$2"
            shift 2
            ;;
        --user)
            SERVICE_USER="$2"
            shift 2
            ;;
        --group)
            SERVICE_GROUP="$2"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --log-file)
            LOG_FILE="$2"
            shift 2
            ;;
        --scan-data-log-dir)
            SCAN_DATA_LOG_DIR="$2"
            shift 2
            ;;
        --scan-data-log-prefix)
            SCAN_DATA_LOG_PREFIX="$2"
            shift 2
            ;;
        --host)
            HOST="$2"
            shift 2
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        --prefix)
            PREFIX="$2"
            shift 2
            ;;
        --no-read-message)
            NO_READ_MESSAGE="$2"
            shift 2
            ;;
        --success-length)
            SUCCESS_LENGTH="$2"
            shift 2
            ;;
        --max-barcode-chars)
            MAX_BARCODE_CHARS="$2"
            shift 2
            ;;
        --max-clients)
            MAX_CLIENTS="$2"
            shift 2
            ;;
        --frame-idle-timeout)
            FRAME_IDLE_TIMEOUT="$2"
            shift 2
            ;;
        --client-idle-timeout)
            CLIENT_IDLE_TIMEOUT="$2"
            shift 2
            ;;
        --shutdown-timeout)
            SHUTDOWN_TIMEOUT="$2"
            shift 2
            ;;
        --enable-tracking-repair)
            TRACKING_REPAIR_ENABLED=1
            shift
            ;;
        --disable-tracking-repair)
            TRACKING_REPAIR_ENABLED=0
            shift
            ;;
        --tcp-keepalive-idle)
            TCP_KEEPALIVE_IDLE="$2"
            shift 2
            ;;
        --tcp-keepalive-interval)
            TCP_KEEPALIVE_INTERVAL="$2"
            shift 2
            ;;
        --tcp-keepalive-probes)
            TCP_KEEPALIVE_PROBES="$2"
            shift 2
            ;;
        --postgresql-dsn)
            POSTGRESQL_DSN="$2"
            shift 2
            ;;
        --postgresql-table)
            POSTGRESQL_TABLE="$2"
            shift 2
            ;;
        --postgresql-connect-timeout)
            POSTGRESQL_CONNECT_TIMEOUT="$2"
            shift 2
            ;;
        --postgresql-retry-interval)
            POSTGRESQL_RETRY_INTERVAL="$2"
            shift 2
            ;;
        --last-scanner-id)
            LAST_SCANNER_ID="$2"
            shift 2
            ;;
        --mandatory-scanner-ids)
            MANDATORY_SCANNER_IDS="$2"
            shift 2
            ;;
        --current-scan-rate-stale-seconds)
            CURRENT_SCAN_RATE_STALE_SECONDS="$2"
            shift 2
            ;;
        --enable-api)
            API_ENABLED=1
            shift
            ;;
        --disable-api)
            API_ENABLED=0
            NGINX_ENABLED=0
            shift
            ;;
        --api-host)
            API_HOST="$2"
            shift 2
            ;;
        --api-port)
            API_PORT="$2"
            shift 2
            ;;
        --api-root-path)
            API_ROOT_PATH="$2"
            shift 2
            ;;
        --api-log-level)
            API_LOG_LEVEL="$2"
            shift 2
            ;;
        --enable-nginx)
            NGINX_ENABLED=1
            shift
            ;;
        --disable-nginx)
            NGINX_ENABLED=0
            shift
            ;;
        --nginx-site-name)
            NGINX_SITE_NAME="$2"
            shift 2
            ;;
        --nginx-listen)
            NGINX_LISTEN="$2"
            shift 2
            ;;
        --nginx-server-name)
            NGINX_SERVER_NAME="$2"
            shift 2
            ;;
        --nginx-web-root)
            NGINX_WEB_ROOT="$2"
            shift 2
            ;;
        --keep-nginx-default-site)
            NGINX_DISABLE_DEFAULT_SITE=0
            shift
            ;;
        --refresh-app-config-bin)
            REFRESH_APP_CONFIG_BIN="$2"
            shift 2
            ;;
        --refresh-nginx-bin)
            REFRESH_NGINX_BIN="$2"
            shift 2
            ;;
        --overwrite-config)
            OVERWRITE_CONFIG=1
            shift
            ;;
        --no-start)
            START_SERVICE=0
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if [[ "${API_ENABLED}" -eq 0 ]]; then
    NGINX_ENABLED=0
fi

if [[ "${EUID}" -ne 0 ]]; then
    echo "This installer must be run as root. Re-run it with sudo." >&2
    exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
SERVICE_TEMPLATE="${PROJECT_ROOT}/systemd/industrial-scanner-logger.service"
API_SERVICE_TEMPLATE="${PROJECT_ROOT}/systemd/industrial-scanner-logger-api.service"
NGINX_TEMPLATE="${PROJECT_ROOT}/nginx/industrial-scanner-logger.conf"
HTML_SOURCE_DIR="${PROJECT_ROOT}/html"
UPDATE_SERVICES_SOURCE="${PROJECT_ROOT}/scripts/update-services"
REFRESH_APP_CONFIG_SOURCE="${PROJECT_ROOT}/scripts/refresh-app-config"
REFRESH_NGINX_SOURCE="${PROJECT_ROOT}/scripts/refresh-nginx-config"
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
API_UNIT_FILE="/etc/systemd/system/${API_SERVICE_NAME}.service"
NGINX_AVAILABLE_DIR="/etc/nginx/sites-available"
NGINX_ENABLED_DIR="/etc/nginx/sites-enabled"
NGINX_SITE_FILE="${NGINX_AVAILABLE_DIR}/${NGINX_SITE_NAME}.conf"
NGINX_SITE_LINK="${NGINX_ENABLED_DIR}/${NGINX_SITE_NAME}.conf"
NGINX_DEFAULT_SITE_LINK="${NGINX_ENABLED_DIR}/default"
PYTHON_BIN="${INSTALL_DIR}/.venv/bin/python"

require_command python3
require_command systemctl
require_command sed
require_command runuser

if ! python3 -m venv --help >/dev/null 2>&1; then
    cat >&2 <<'ERROR'
python3 venv support is not installed.

On Ubuntu, install it with:
  sudo apt update
  sudo apt install python3-venv
ERROR
    exit 1
fi

if [[ ! -f "${PROJECT_ROOT}/scanner_tcp_receiver.py" ]]; then
    echo "Could not find scanner_tcp_receiver.py. Run this script from the project checkout." >&2
    exit 1
fi

if [[ ! -f "${SERVICE_TEMPLATE}" ]]; then
    echo "Missing service template: ${SERVICE_TEMPLATE}" >&2
    exit 1
fi

if [[ ! -f "${API_SERVICE_TEMPLATE}" ]]; then
    echo "Missing API service template: ${API_SERVICE_TEMPLATE}" >&2
    exit 1
fi

if [[ "${NGINX_ENABLED}" -eq 1 && ! -f "${NGINX_TEMPLATE}" ]]; then
    echo "Missing nginx site template: ${NGINX_TEMPLATE}" >&2
    exit 1
fi

if [[ ! -f "${UPDATE_SERVICES_SOURCE}" ]]; then
    echo "Missing update helper script: ${UPDATE_SERVICES_SOURCE}" >&2
    exit 1
fi

if [[ ! -f "${REFRESH_APP_CONFIG_SOURCE}" ]]; then
    echo "Missing app config refresh helper script: ${REFRESH_APP_CONFIG_SOURCE}" >&2
    exit 1
fi

if [[ ! -f "${REFRESH_NGINX_SOURCE}" ]]; then
    echo "Missing nginx refresh helper script: ${REFRESH_NGINX_SOURCE}" >&2
    exit 1
fi

if [[ "${NGINX_ENABLED}" -eq 1 ]]; then
    validate_api_root_path
    install_nginx_package
fi

install_postgresql_package
install_ufw_firewall

if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    if [[ "${ID:-}" != "ubuntu" && "${ID_LIKE:-}" != *"ubuntu"* && "${ID_LIKE:-}" != *"debian"* ]]; then
        echo "Warning: this installer is intended for Ubuntu-style systemd systems." >&2
    fi
fi

if ! getent group "${SERVICE_GROUP}" >/dev/null; then
    groupadd --system "${SERVICE_GROUP}"
fi

if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
    useradd \
        --system \
        --gid "${SERVICE_GROUP}" \
        --home-dir "${INSTALL_DIR}" \
        --shell /usr/sbin/nologin \
        --comment "Industrial Scanner Logger" \
        "${SERVICE_USER}"
fi

install -d -o root -g root -m 0755 "${INSTALL_DIR}"
INSTALL_DIR_REAL="$(cd -- "${INSTALL_DIR}" && pwd -P)"

if [[ "${INSTALL_DIR_REAL}" == "${PROJECT_ROOT}" ]]; then
    echo "Using project checkout in place as install directory: ${INSTALL_DIR_REAL}"
elif [[ "${INSTALL_DIR_REAL}/" == "${PROJECT_ROOT}/"* ]]; then
    cat >&2 <<ERROR
Install directory cannot be inside the project checkout.

Project checkout:
  ${PROJECT_ROOT}

Install directory:
  ${INSTALL_DIR_REAL}

Use the default /opt/industrial-scanner-logger install path or another directory
outside the checkout.
ERROR
    exit 1
else
    copy_project_tree "${PROJECT_ROOT}" "${INSTALL_DIR_REAL}"
fi

python3 -m venv "${INSTALL_DIR}/.venv"
if [[ -f "${INSTALL_DIR_REAL}/requirements.txt" ]]; then
    "${PYTHON_BIN}" -m pip install -r "${INSTALL_DIR_REAL}/requirements.txt"
fi
"${PYTHON_BIN}" -m pip install --no-deps "${INSTALL_DIR_REAL}"
chown -R root:root "${INSTALL_DIR}"
chmod -R u=rwX,go=rX "${INSTALL_DIR}"
configure_postgresql_database
install -d -o root -g root -m 0755 "$(dirname -- "${UPDATE_SERVICES_BIN}")"
install -o root -g root -m 0755 "${UPDATE_SERVICES_SOURCE}" "${UPDATE_SERVICES_BIN}"
install -d -o root -g root -m 0755 "$(dirname -- "${REFRESH_APP_CONFIG_BIN}")"
install -o root -g root -m 0755 "${REFRESH_APP_CONFIG_SOURCE}" "${REFRESH_APP_CONFIG_BIN}"
install -d -o root -g root -m 0755 "$(dirname -- "${REFRESH_NGINX_BIN}")"
install -o root -g root -m 0755 "${REFRESH_NGINX_SOURCE}" "${REFRESH_NGINX_BIN}"

install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" -m 0750 "${OUTPUT_DIR}"
install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" -m 0750 "${SCAN_DATA_LOG_DIR}"
install -d -o root -g root -m 0755 "$(dirname -- "${LOG_FILE}")"
touch "${LOG_FILE}"
chown "${SERVICE_USER}:${SERVICE_GROUP}" "${LOG_FILE}"
chmod 0640 "${LOG_FILE}"
install -d -o root -g root -m 0755 "$(dirname -- "${CONFIG_FILE}")"

API_ENABLED_TEXT="false"
if [[ "${API_ENABLED}" -eq 1 ]]; then
    API_ENABLED_TEXT="true"
fi

TRACKING_REPAIR_ENABLED_TEXT="false"
if [[ "${TRACKING_REPAIR_ENABLED}" -eq 1 ]]; then
    TRACKING_REPAIR_ENABLED_TEXT="true"
fi

if [[ ! -f "${CONFIG_FILE}" || "${OVERWRITE_CONFIG}" -eq 1 ]]; then
    cat >"${CONFIG_FILE}" <<CONFIG
# Runtime options for ${SERVICE_NAME}.service.
#
# Edit this file, then restart the service:
#   sudo systemctl restart ${SERVICE_NAME}

[receiver]
# TCP address the scanner receiver listens on.
# Default: 0.0.0.0. Examples: 0.0.0.0 for all interfaces, 127.0.0.1 for local-only testing.
host = ${HOST}

# TCP port the scanner receiver listens on.
# Default: 55256. Range: 1-65535. This port must also be allowed through the firewall.
port = ${PORT}

# Directory where daily CSV files are written.
# Default: /scanner-logs. Example: /data/scanner-logs. The service user must be able to write here.
output_dir = ${OUTPUT_DIR}

# Filename prefix for daily CSV output files.
# Default: Site_Shipped_Tracking. Allowed: letters, numbers, underscore, dash, and dot; must start with a letter or number.
prefix = ${PREFIX}

# Exact scanner message used when a barcode could not be read.
# Default: __NO_READ__. Matching values are recorded as failed scans and must not be longer than max_barcode_chars.
no_read_message = ${NO_READ_MESSAGE}

# Required numeric barcode length for a successful scan.
# Default: 34. Range: greater than 0 and no larger than max_barcode_chars.
success_length = ${SUCCESS_LENGTH}

# Maximum accepted scanner frame length before the scan is treated as oversized.
# Default: 256. Minimum: 64. Increase only if scanners can send longer valid data.
max_barcode_chars = ${MAX_BARCODE_CHARS}

# Maximum simultaneous scanner TCP connections.
# Default: 10. Range: greater than 0. Example: 16 for a larger conveyor system.
max_clients = ${MAX_CLIENTS}

# Seconds to wait before flushing a partial scanner frame when no line ending is received.
# Default: 0.25. Range: greater than 0. Examples: 0.25, 0.5, 1.0.
frame_idle_timeout = ${FRAME_IDLE_TIMEOUT}

# Seconds before disconnecting an idle scanner client.
# Default: 0, which disables application-level idle disconnects. Range: 0 or greater.
client_idle_timeout = ${CLIENT_IDLE_TIMEOUT}

# Seconds to wait for active scanner threads to stop during service shutdown.
# Default: 5. Range: greater than 0.
shutdown_timeout = ${SHUTDOWN_TIMEOUT}

# Enables conservative tracking-number repair for short numeric failed scans.
# Default: false. When true, a short failed scan can be repaired only if successful scans from the same day provide one unambiguous matching prefix.
# Example: false for normal strict logging, true to repair likely truncated FedEx tracking scans.
tracking_repair_enabled = ${TRACKING_REPAIR_ENABLED_TEXT}

[logging]
# Main troubleshooting log file for receiver startup, connections, and errors.
# Default: /var/log/industrial-scanner-logger.log. Raw barcode data is not written here.
log_file = ${LOG_FILE}

# Directory for daily raw scan event logs used for audit/troubleshooting.
# Default: /var/log/industrial-scanner-logger. The service user must be able to write here.
scan_data_log_dir = ${SCAN_DATA_LOG_DIR}

# Filename prefix for daily raw scan event logs.
# Default: scanner-log-data. Uses the same safe filename rules as receiver.prefix.
scan_data_log_prefix = ${SCAN_DATA_LOG_PREFIX}

[tcp_keepalive]
# Enables OS TCP keepalive on scanner sockets so dead connections are detected.
# Default: true. Values: true or false.
enabled = true

# Idle seconds before TCP keepalive probes begin.
# Default: 60. Range: greater than 0.
idle = ${TCP_KEEPALIVE_IDLE}

# Seconds between TCP keepalive probes after the idle period.
# Default: 15. Range: greater than 0.
interval = ${TCP_KEEPALIVE_INTERVAL}

# Number of failed keepalive probes before the connection is considered dead.
# Default: 4. Range: greater than 0.
probes = ${TCP_KEEPALIVE_PROBES}

[postgresql]
# PostgreSQL connection string used by the receiver and API.
# Default: postgresql:///scannerlogger?host=/var/run/postgresql&user=scannerlogger.
# Example TCP DSN: postgresql://scannerlogger:password@127.0.0.1:5432/scannerlogger
dsn = ${POSTGRESQL_DSN}

# Destination PostgreSQL table for scan events.
# Default: scanner_logger.scan_events. Format: schema.table using letters, numbers, and underscores.
table = ${POSTGRESQL_TABLE}

# Seconds to wait while opening a PostgreSQL connection.
# Default: 3. Range: greater than 0.
connect_timeout = ${POSTGRESQL_CONNECT_TIMEOUT}

# Seconds to wait before retrying PostgreSQL after a connection or write failure.
# Default: 30. Range: 0 or greater. Use 0 for immediate retry attempts.
retry_interval = ${POSTGRESQL_RETRY_INTERVAL}

[scanners]
# Scanner ID for the final outbound scanner before boxes are loaded.
# Default: blank, which disables last-scanner matching. Range when set: 0-255.
# Example: if the final scanner IP is 10.10.10.21, set last_scanner_id = 21.
last_scanner_id = ${LAST_SCANNER_ID}

# Scanner IDs that must stay connected for the health page and TV dashboard to report OK.
# Default: blank, which disables mandatory scanner warnings. Format: comma or space-separated scanner IP last octets.
# Example: mandatory_scanner_ids = 20, 21
mandatory_scanner_ids = ${MANDATORY_SCANNER_IDS}

[scanner_names]
# Optional scanner ID to friendly-name mapping.
# Default: no entries, so scanners display by ID. Add one line per scanner using the scanner IP last octet as the key.
# Format: <0-255> = <display name>. Examples:
#   20 = Lane 1 Scanner
#   21 = Last Scanner

[dashboard]
# Seconds since the last received scan before the health page Current Scan Rate indicator turns red.
# Default: 60. Range: greater than 0. Example: 300 keeps the indicator green for 5 minutes after the last scan.
current_scan_rate_stale_seconds = ${CURRENT_SCAN_RATE_STALE_SECONDS}

[api]
# Enables the REST API systemd service installed alongside the receiver.
# Default: true. Set false to disable API startup.
enabled = ${API_ENABLED_TEXT}

# REST API bind address.
# Default: 127.0.0.1 so nginx can proxy it locally. Example: 0.0.0.0 for direct network access.
host = ${API_HOST}

# REST API TCP port.
# Default: 8000. Range: 1-65535. Keep this different from receiver.port.
port = ${API_PORT}

# URL prefix where nginx exposes the API.
# Default: /api. Must start with / and should not be / when nginx is enabled. Example: /scanner-api.
root_path = ${API_ROOT_PATH}

# Uvicorn API log verbosity.
# Default: info. Common values: critical, error, warning, info, debug, trace.
log_level = ${API_LOG_LEVEL}

[nginx]
# Nginx site filename without the .conf suffix.
# Default: industrial-scanner-logger. Allowed: letters, numbers, dot, underscore, and dash.
site_name = ${NGINX_SITE_NAME}

# Nginx listen directive for this site.
# Default: 80 default_server. Use 80 when this site should share port 80 with other server blocks.
listen = ${NGINX_LISTEN}

# Hostnames accepted by this site.
# Default: _, which accepts any hostname not matched by a more specific site.
server_name = ${NGINX_SERVER_NAME}

# Document root for the installed web interface.
# Default: /var/www/scanner-site. Static files from html/ are copied here during install.
web_root = ${NGINX_WEB_ROOT}

# Removes Ubuntu's default nginx site symlink before testing this site.
# Default: true, because the default listen value also uses default_server.
disable_default_site = $([[ "${NGINX_DISABLE_DEFAULT_SITE}" -eq 1 ]] && echo "true" || echo "false")
CONFIG
    chmod 0644 "${CONFIG_FILE}"
else
    echo "Keeping existing config file: ${CONFIG_FILE}"
fi

if [[ -f "${LEGACY_ENV_FILE}" ]]; then
    rm -f "${LEGACY_ENV_FILE}"
    echo "Removed legacy service defaults file: ${LEGACY_ENV_FILE}"
fi

sed \
    -e "s|@INSTALL_DIR@|$(escape_sed_replacement "${INSTALL_DIR}")|g" \
    -e "s|@SERVICE_USER@|$(escape_sed_replacement "${SERVICE_USER}")|g" \
    -e "s|@SERVICE_GROUP@|$(escape_sed_replacement "${SERVICE_GROUP}")|g" \
    -e "s|@PYTHON_BIN@|$(escape_sed_replacement "${PYTHON_BIN}")|g" \
    "${SERVICE_TEMPLATE}" >"${UNIT_FILE}"

chmod 0644 "${UNIT_FILE}"

sed \
    -e "s|@INSTALL_DIR@|$(escape_sed_replacement "${INSTALL_DIR}")|g" \
    -e "s|@SERVICE_USER@|$(escape_sed_replacement "${SERVICE_USER}")|g" \
    -e "s|@SERVICE_GROUP@|$(escape_sed_replacement "${SERVICE_GROUP}")|g" \
    -e "s|@PYTHON_BIN@|$(escape_sed_replacement "${PYTHON_BIN}")|g" \
    "${API_SERVICE_TEMPLATE}" >"${API_UNIT_FILE}"

chmod 0644 "${API_UNIT_FILE}"

if [[ "${NGINX_ENABLED}" -eq 1 ]]; then
    install -d -o root -g root -m 0755 "${NGINX_AVAILABLE_DIR}"
    install -d -o root -g root -m 0755 "${NGINX_ENABLED_DIR}"
    install -d -o root -g root -m 0755 "${NGINX_WEB_ROOT}"
    install_html_tree "${HTML_SOURCE_DIR}" "${NGINX_WEB_ROOT}"

    sed \
        -e "s|@NGINX_LISTEN@|$(escape_sed_replacement "${NGINX_LISTEN}")|g" \
        -e "s|@NGINX_SERVER_NAME@|$(escape_sed_replacement "${NGINX_SERVER_NAME}")|g" \
        -e "s|@NGINX_WEB_ROOT@|$(escape_sed_replacement "${NGINX_WEB_ROOT}")|g" \
        -e "s|@API_ROOT_PATH@|$(escape_sed_replacement "${API_ROOT_PATH}")|g" \
        -e "s|@API_HOST@|$(escape_sed_replacement "${API_HOST}")|g" \
        -e "s|@API_PORT@|$(escape_sed_replacement "${API_PORT}")|g" \
        "${NGINX_TEMPLATE}" >"${NGINX_SITE_FILE}"

    chmod 0644 "${NGINX_SITE_FILE}"

    if [[ "${NGINX_DISABLE_DEFAULT_SITE}" -eq 1 && -L "${NGINX_DEFAULT_SITE_LINK}" ]]; then
        rm -f "${NGINX_DEFAULT_SITE_LINK}"
        echo "Disabled Ubuntu default nginx site: ${NGINX_DEFAULT_SITE_LINK}"
    fi

    ln -sfn "${NGINX_SITE_FILE}" "${NGINX_SITE_LINK}"
    nginx -t
    systemctl enable nginx
fi

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.service"

if [[ "${API_ENABLED}" -eq 1 ]]; then
    systemctl enable "${API_SERVICE_NAME}.service"
else
    systemctl disable --now "${API_SERVICE_NAME}.service" >/dev/null 2>&1 || true
fi

if [[ "${START_SERVICE}" -eq 1 ]]; then
    systemctl restart "${SERVICE_NAME}.service"

    if [[ "${API_ENABLED}" -eq 1 ]]; then
        systemctl restart "${API_SERVICE_NAME}.service"
    fi

    if [[ "${NGINX_ENABLED}" -eq 1 ]]; then
        systemctl restart nginx
    fi
fi

cat <<DONE
Installed ${SERVICE_NAME}.service

Application directory:
  ${INSTALL_DIR}

Receiver config:
  ${CONFIG_FILE}

Scanner logs:
  ${OUTPUT_DIR}

Troubleshooting log:
  ${LOG_FILE}

Daily raw scan data logs:
  ${SCAN_DATA_LOG_DIR}/${SCAN_DATA_LOG_PREFIX}-YYYY-MM-DD.log

Tracking number repair:
  $([[ "${TRACKING_REPAIR_ENABLED}" -eq 1 ]] && echo "enabled" || echo "disabled")

PostgreSQL scan logging:
  mandatory (${POSTGRESQL_TABLE})

REST API service:
  $([[ "${API_ENABLED}" -eq 1 ]] && echo "enabled (${API_SERVICE_NAME}.service on ${API_HOST}:${API_PORT}${API_ROOT_PATH})" || echo "disabled (${API_SERVICE_NAME}.service installed)")

Nginx API proxy:
  $([[ "${NGINX_ENABLED}" -eq 1 ]] && echo "enabled (${NGINX_SITE_FILE}, public path ${API_ROOT_PATH})" || echo "disabled")

Web root:
  ${NGINX_WEB_ROOT}

Update helper:
  ${UPDATE_SERVICES_BIN}

App config refresh helper:
  ${REFRESH_APP_CONFIG_BIN}

Nginx refresh helper:
  ${REFRESH_NGINX_BIN}

UFW firewall:
  enabled; incoming allow list is 22/tcp, 55256/tcp, 80/tcp, 443/tcp

Useful commands:
  sudo update-services
  sudo refresh-app-config
  sudo refresh-nginx-config
  sudo systemctl status ${SERVICE_NAME}
  sudo systemctl status ${API_SERVICE_NAME}
  sudo systemctl status nginx
  sudo journalctl -u ${SERVICE_NAME} -f
  sudo journalctl -u ${API_SERVICE_NAME} -f
  sudo tail -f ${LOG_FILE}
  sudo nano ${CONFIG_FILE}
  sudo nano ${NGINX_SITE_FILE}
  sudo systemctl restart ${SERVICE_NAME}
  sudo systemctl restart ${API_SERVICE_NAME}
  sudo systemctl reload nginx
DONE
