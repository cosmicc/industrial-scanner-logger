#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-industrial-scanner-logger}"
INSTALL_DIR="${INSTALL_DIR:-/opt/industrial-scanner-logger}"
SERVICE_USER="${SERVICE_USER:-scannerlogger}"
SERVICE_GROUP="${SERVICE_GROUP:-$SERVICE_USER}"
ENV_FILE="${ENV_FILE:-/etc/default/${SERVICE_NAME}}"
OUTPUT_DIR="${OUTPUT_DIR:-/scanner-logs}"
LOG_FILE="${LOG_FILE:-/var/log/industrial-scanner-logger.log}"
PURGE="${PURGE:-0}"

usage() {
    cat <<USAGE
Usage: sudo scripts/uninstall_service.sh [options]

Uninstall the Industrial Scanner Logger systemd service.

Options:
  --service-name NAME    systemd service name [${SERVICE_NAME}]
  --install-dir DIR      application install directory [${INSTALL_DIR}]
  --user USER            service user to remove with --purge [${SERVICE_USER}]
  --group GROUP          service group to remove with --purge [${SERVICE_GROUP}]
  --env-file PATH        service defaults file [${ENV_FILE}]
  --output-dir DIR       scanner CSV output directory [${OUTPUT_DIR}]
  --log-file PATH        troubleshooting log file [${LOG_FILE}]
  --purge                also remove defaults file, log directory, and service user/group
  -h, --help             show this help

Without --purge, scanner CSV logs and service defaults are preserved.
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
        --purge)
            PURGE=1
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

    export SERVICE_NAME INSTALL_DIR SERVICE_USER SERVICE_GROUP ENV_FILE OUTPUT_DIR LOG_FILE PURGE
    exec sudo --preserve-env=SERVICE_NAME,INSTALL_DIR,SERVICE_USER,SERVICE_GROUP,ENV_FILE,OUTPUT_DIR,LOG_FILE,PURGE "$0"
fi

UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if command -v systemctl >/dev/null 2>&1; then
    systemctl disable --now "${SERVICE_NAME}.service" >/dev/null 2>&1 || true
fi

rm -f "${UNIT_FILE}"
rm -rf "${INSTALL_DIR}"

if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload
    systemctl reset-failed "${SERVICE_NAME}.service" >/dev/null 2>&1 || true
fi

if [[ "${PURGE}" -eq 1 ]]; then
    rm -f "${ENV_FILE}"
    rm -f "${LOG_FILE}"
    rm -rf "${OUTPUT_DIR}"

    if id -u "${SERVICE_USER}" >/dev/null 2>&1; then
        userdel "${SERVICE_USER}" >/dev/null 2>&1 || true
    fi

    if getent group "${SERVICE_GROUP}" >/dev/null; then
        groupdel "${SERVICE_GROUP}" >/dev/null 2>&1 || true
    fi
fi

cat <<DONE
Uninstalled ${SERVICE_NAME}.service

Removed:
  ${UNIT_FILE}
  ${INSTALL_DIR}
DONE

if [[ "${PURGE}" -eq 0 ]]; then
    cat <<KEPT

Preserved:
  ${ENV_FILE}
  ${OUTPUT_DIR}
  ${LOG_FILE}

Run again with --purge to remove preserved config, logs, and the service user/group.
KEPT
fi
