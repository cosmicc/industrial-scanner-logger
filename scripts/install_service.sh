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
MAX_CLIENTS="${MAX_CLIENTS:-8}"
FRAME_IDLE_TIMEOUT="${FRAME_IDLE_TIMEOUT:-0.25}"
CLIENT_IDLE_TIMEOUT="${CLIENT_IDLE_TIMEOUT:-0}"
SHUTDOWN_TIMEOUT="${SHUTDOWN_TIMEOUT:-5}"
TCP_KEEPALIVE_IDLE="${TCP_KEEPALIVE_IDLE:-60}"
TCP_KEEPALIVE_INTERVAL="${TCP_KEEPALIVE_INTERVAL:-15}"
TCP_KEEPALIVE_PROBES="${TCP_KEEPALIVE_PROBES:-4}"
POSTGRESQL_ENABLED="${POSTGRESQL_ENABLED:-1}"
POSTGRESQL_DSN="${POSTGRESQL_DSN:-postgresql:///scannerlogger?host=/var/run/postgresql&user=scannerlogger}"
POSTGRESQL_TABLE="${POSTGRESQL_TABLE:-scanner_logger.scan_events}"
POSTGRESQL_CONNECT_TIMEOUT="${POSTGRESQL_CONNECT_TIMEOUT:-3}"
POSTGRESQL_RETRY_INTERVAL="${POSTGRESQL_RETRY_INTERVAL:-30}"
POSTGRESQL_REQUIRED="${POSTGRESQL_REQUIRED:-0}"
API_ENABLED="${API_ENABLED:-1}"
API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"
API_LOG_LEVEL="${API_LOG_LEVEL:-info}"
START_SERVICE="${START_SERVICE:-1}"
OVERWRITE_CONFIG="${OVERWRITE_CONFIG:-0}"

usage() {
    cat <<USAGE
Usage: sudo scripts/install_service.sh [options]

Install the Industrial Scanner Logger as an Ubuntu systemd service.

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
  --tcp-keepalive-idle SEC  idle seconds before TCP keepalive probes start [${TCP_KEEPALIVE_IDLE}]
  --tcp-keepalive-interval SEC seconds between TCP keepalive probes [${TCP_KEEPALIVE_INTERVAL}]
  --tcp-keepalive-probes NUM failed probes before a socket is considered dead [${TCP_KEEPALIVE_PROBES}]
  --enable-postgresql      enable PostgreSQL scan event logging [default]
  --disable-postgresql     disable PostgreSQL scan event logging
  --postgresql-dsn DSN     PostgreSQL URI/DSN with no shell spaces [${POSTGRESQL_DSN}]
  --postgresql-table NAME  PostgreSQL table in schema.table format [${POSTGRESQL_TABLE}]
  --postgresql-connect-timeout SEC PostgreSQL connection timeout [${POSTGRESQL_CONNECT_TIMEOUT}]
  --postgresql-retry-interval SEC  retry delay after PostgreSQL failures [${POSTGRESQL_RETRY_INTERVAL}]
  --postgresql-required    stop the receiver if PostgreSQL logging is unavailable
  --enable-api             enable and start the REST API service [default]
  --disable-api            install but disable the REST API service
  --api-host HOST          REST API bind address [${API_HOST}]
  --api-port PORT          REST API TCP port [${API_PORT}]
  --api-log-level LEVEL    uvicorn log level [${API_LOG_LEVEL}]
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

escape_sed_replacement() {
    printf "%s" "$1" | sed "s/[&|]/\\\\&/g"
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
        --enable-postgresql)
            POSTGRESQL_ENABLED=1
            shift
            ;;
        --disable-postgresql)
            POSTGRESQL_ENABLED=0
            shift
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
        --postgresql-required)
            POSTGRESQL_REQUIRED=1
            shift
            ;;
        --enable-api)
            API_ENABLED=1
            shift
            ;;
        --disable-api)
            API_ENABLED=0
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
        --api-log-level)
            API_LOG_LEVEL="$2"
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

if [[ "${EUID}" -ne 0 ]]; then
    if ! command -v sudo >/dev/null 2>&1; then
        echo "This installer must run as root, and sudo was not found." >&2
        exit 1
    fi

    export SERVICE_NAME API_SERVICE_NAME INSTALL_DIR SERVICE_USER SERVICE_GROUP LEGACY_ENV_FILE
    export START_SERVICE OVERWRITE_CONFIG
    export OUTPUT_DIR LOG_FILE SCAN_DATA_LOG_DIR SCAN_DATA_LOG_PREFIX
    export HOST PORT PREFIX NO_READ_MESSAGE SUCCESS_LENGTH
    export MAX_BARCODE_CHARS MAX_CLIENTS FRAME_IDLE_TIMEOUT CLIENT_IDLE_TIMEOUT SHUTDOWN_TIMEOUT
    export TCP_KEEPALIVE_IDLE TCP_KEEPALIVE_INTERVAL TCP_KEEPALIVE_PROBES
    export POSTGRESQL_ENABLED POSTGRESQL_DSN POSTGRESQL_TABLE
    export POSTGRESQL_CONNECT_TIMEOUT POSTGRESQL_RETRY_INTERVAL POSTGRESQL_REQUIRED
    export API_ENABLED API_HOST API_PORT API_LOG_LEVEL
    exec sudo --preserve-env=SERVICE_NAME,API_SERVICE_NAME,INSTALL_DIR,SERVICE_USER,SERVICE_GROUP,LEGACY_ENV_FILE,OUTPUT_DIR,LOG_FILE,SCAN_DATA_LOG_DIR,SCAN_DATA_LOG_PREFIX,HOST,PORT,PREFIX,NO_READ_MESSAGE,SUCCESS_LENGTH,MAX_BARCODE_CHARS,MAX_CLIENTS,FRAME_IDLE_TIMEOUT,CLIENT_IDLE_TIMEOUT,SHUTDOWN_TIMEOUT,TCP_KEEPALIVE_IDLE,TCP_KEEPALIVE_INTERVAL,TCP_KEEPALIVE_PROBES,POSTGRESQL_ENABLED,POSTGRESQL_DSN,POSTGRESQL_TABLE,POSTGRESQL_CONNECT_TIMEOUT,POSTGRESQL_RETRY_INTERVAL,POSTGRESQL_REQUIRED,API_ENABLED,API_HOST,API_PORT,API_LOG_LEVEL,START_SERVICE,OVERWRITE_CONFIG "$0"
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
SERVICE_TEMPLATE="${PROJECT_ROOT}/systemd/industrial-scanner-logger.service"
API_SERVICE_TEMPLATE="${PROJECT_ROOT}/systemd/industrial-scanner-logger-api.service"
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
API_UNIT_FILE="/etc/systemd/system/${API_SERVICE_NAME}.service"
PYTHON_BIN="${INSTALL_DIR}/.venv/bin/python"

require_command python3
require_command systemctl
require_command sed

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

install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" -m 0750 "${OUTPUT_DIR}"
install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" -m 0750 "${SCAN_DATA_LOG_DIR}"
install -d -o root -g root -m 0755 "$(dirname -- "${LOG_FILE}")"
touch "${LOG_FILE}"
chown "${SERVICE_USER}:${SERVICE_GROUP}" "${LOG_FILE}"
chmod 0640 "${LOG_FILE}"
install -d -o root -g root -m 0755 "$(dirname -- "${CONFIG_FILE}")"

POSTGRESQL_ENABLED_TEXT="false"
if [[ "${POSTGRESQL_ENABLED}" -eq 1 ]]; then
    POSTGRESQL_ENABLED_TEXT="true"
fi

POSTGRESQL_REQUIRED_TEXT="false"
if [[ "${POSTGRESQL_REQUIRED}" -eq 1 ]]; then
    POSTGRESQL_REQUIRED_TEXT="true"
fi

API_ENABLED_TEXT="false"
if [[ "${API_ENABLED}" -eq 1 ]]; then
    API_ENABLED_TEXT="true"
fi

if [[ ! -f "${CONFIG_FILE}" || "${OVERWRITE_CONFIG}" -eq 1 ]]; then
    cat >"${CONFIG_FILE}" <<CONFIG
# Runtime options for ${SERVICE_NAME}.service.
#
# Edit this file, then restart the service:
#   sudo systemctl restart ${SERVICE_NAME}

[receiver]
host = ${HOST}
port = ${PORT}
output_dir = ${OUTPUT_DIR}
prefix = ${PREFIX}
no_read_message = ${NO_READ_MESSAGE}
success_length = ${SUCCESS_LENGTH}
max_barcode_chars = ${MAX_BARCODE_CHARS}
max_clients = ${MAX_CLIENTS}
frame_idle_timeout = ${FRAME_IDLE_TIMEOUT}
client_idle_timeout = ${CLIENT_IDLE_TIMEOUT}
shutdown_timeout = ${SHUTDOWN_TIMEOUT}

[logging]
log_file = ${LOG_FILE}
scan_data_log_dir = ${SCAN_DATA_LOG_DIR}
scan_data_log_prefix = ${SCAN_DATA_LOG_PREFIX}

[tcp_keepalive]
enabled = true
idle = ${TCP_KEEPALIVE_IDLE}
interval = ${TCP_KEEPALIVE_INTERVAL}
probes = ${TCP_KEEPALIVE_PROBES}

[postgresql]
enabled = ${POSTGRESQL_ENABLED_TEXT}
required = ${POSTGRESQL_REQUIRED_TEXT}
dsn = ${POSTGRESQL_DSN}
table = ${POSTGRESQL_TABLE}
connect_timeout = ${POSTGRESQL_CONNECT_TIMEOUT}
retry_interval = ${POSTGRESQL_RETRY_INTERVAL}

[api]
enabled = ${API_ENABLED_TEXT}
host = ${API_HOST}
port = ${API_PORT}
log_level = ${API_LOG_LEVEL}
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

PostgreSQL scan logging:
  $([[ "${POSTGRESQL_ENABLED}" -eq 1 ]] && echo "enabled (${POSTGRESQL_TABLE})" || echo "disabled")

REST API service:
  $([[ "${API_ENABLED}" -eq 1 ]] && echo "enabled (${API_SERVICE_NAME}.service on ${API_HOST}:${API_PORT})" || echo "disabled (${API_SERVICE_NAME}.service installed)")

Useful commands:
  sudo systemctl status ${SERVICE_NAME}
  sudo systemctl status ${API_SERVICE_NAME}
  sudo journalctl -u ${SERVICE_NAME} -f
  sudo journalctl -u ${API_SERVICE_NAME} -f
  sudo tail -f ${LOG_FILE}
  sudo nano ${CONFIG_FILE}
  sudo systemctl restart ${SERVICE_NAME}
  sudo systemctl restart ${API_SERVICE_NAME}
DONE
