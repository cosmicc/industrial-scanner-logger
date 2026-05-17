#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-industrial-scanner-logger}"
INSTALL_DIR="${INSTALL_DIR:-/opt/industrial-scanner-logger}"
SERVICE_USER="${SERVICE_USER:-scannerlogger}"
SERVICE_GROUP="${SERVICE_GROUP:-$SERVICE_USER}"
ENV_FILE="${ENV_FILE:-/etc/default/${SERVICE_NAME}}"
OUTPUT_DIR="${OUTPUT_DIR:-/scanner-logs}"
LOG_FILE="${LOG_FILE:-/var/log/industrial-scanner-logger.log}"
SCAN_DATA_LOG_DIR="${SCAN_DATA_LOG_DIR:-/var/log/industrial-scanner-logger}"
REMOVE_APP="${REMOVE_APP:-0}"

usage() {
    cat <<USAGE
Usage: sudo scripts/uninstall_service.sh [options]

Uninstall the Industrial Scanner Logger systemd service.

Options:
  --service-name NAME    systemd service name [${SERVICE_NAME}]
  --install-dir DIR      application install directory [${INSTALL_DIR}]
  --user USER            service user name to preserve [${SERVICE_USER}]
  --group GROUP          service group name to preserve [${SERVICE_GROUP}]
  --env-file PATH        service defaults file [${ENV_FILE}]
  --output-dir DIR       scanner CSV output directory [${OUTPUT_DIR}]
  --log-file PATH        troubleshooting log file [${LOG_FILE}]
  --scan-data-log-dir DIR daily raw scan event log directory [${SCAN_DATA_LOG_DIR}]
  --remove-app           also remove application directory [${INSTALL_DIR}]
  -h, --help             show this help

The service defaults file is always removed.
The application directory is preserved unless --remove-app is provided.
The service user and group are always preserved for future installs.
Scanner CSV logs, script logs, and raw scan data logs are always preserved.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --service-name)
            SERVICE_NAME="$2"
            ENV_FILE="/etc/default/${SERVICE_NAME}"
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
        --env-file)
            ENV_FILE="$2"
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
        --remove-app)
            REMOVE_APP=1
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
        echo "This uninstaller must run as root, and sudo was not found." >&2
        exit 1
    fi

    export SERVICE_NAME INSTALL_DIR SERVICE_USER SERVICE_GROUP ENV_FILE OUTPUT_DIR LOG_FILE
    export SCAN_DATA_LOG_DIR REMOVE_APP
    exec sudo --preserve-env=SERVICE_NAME,INSTALL_DIR,SERVICE_USER,SERVICE_GROUP,ENV_FILE,OUTPUT_DIR,LOG_FILE,SCAN_DATA_LOG_DIR,REMOVE_APP "$0"
fi

UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if command -v systemctl >/dev/null 2>&1; then
    systemctl disable --now "${SERVICE_NAME}.service" >/dev/null 2>&1 || true
fi

rm -f "${UNIT_FILE}"
rm -f "${ENV_FILE}"

if [[ "${REMOVE_APP}" -eq 1 ]]; then
    rm -rf "${INSTALL_DIR}"
fi

if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload
    systemctl reset-failed "${SERVICE_NAME}.service" >/dev/null 2>&1 || true
fi

cat <<DONE
Uninstalled ${SERVICE_NAME}.service

Removed:
  ${UNIT_FILE}
  ${ENV_FILE}
DONE

if [[ "${REMOVE_APP}" -eq 1 ]]; then
    cat <<REMOVED_APP
  ${INSTALL_DIR}
REMOVED_APP
fi

cat <<KEPT

Preserved:
  ${OUTPUT_DIR}
  ${LOG_FILE}
  ${SCAN_DATA_LOG_DIR}

KEPT

if [[ "${REMOVE_APP}" -eq 0 ]]; then
    cat <<KEPT_APP

Preserved:
  ${INSTALL_DIR}

Add --remove-app only when you also want to remove the application directory.
KEPT_APP
fi

cat <<USER_GROUP

Service identity preserved for future installs:
  user: ${SERVICE_USER}
  group: ${SERVICE_GROUP}
USER_GROUP
