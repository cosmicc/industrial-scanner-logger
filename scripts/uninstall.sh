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
NGINX_SITE_NAME="${NGINX_SITE_NAME:-industrial-scanner-logger}"
NGINX_WEB_ROOT="${NGINX_WEB_ROOT:-/var/www/industrial-scanner-logger}"

usage() {
    cat <<USAGE
Usage: sudo scripts/uninstall.sh [options]

Uninstall the Industrial Scanner Logger runtime, services, and nginx site.

Options:
  --service-name NAME    systemd service name [${SERVICE_NAME}]
  --api-service-name NAME REST API service name [${API_SERVICE_NAME}]
  --install-dir DIR      application install directory [${INSTALL_DIR}]
  --user USER            service user name to preserve [${SERVICE_USER}]
  --group GROUP          service group name to preserve [${SERVICE_GROUP}]
  --output-dir DIR       scanner CSV output directory [${OUTPUT_DIR}]
  --log-file PATH        troubleshooting log file [${LOG_FILE}]
  --scan-data-log-dir DIR daily raw scan event log directory [${SCAN_DATA_LOG_DIR}]
  --nginx-site-name NAME nginx site file name [${NGINX_SITE_NAME}]
  --nginx-web-root DIR   document root to remove if empty [${NGINX_WEB_ROOT}]
  -h, --help             show this help

The receiver config file is always removed.
The old /etc/default service defaults file is removed if present.
The installed application directory is removed.
The service user and group are always preserved for future installs.
Scanner CSV logs, script logs, and raw scan data logs are always preserved.
The nginx package is preserved because it may serve other sites.
USAGE
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
        --nginx-site-name)
            NGINX_SITE_NAME="$2"
            shift 2
            ;;
        --nginx-web-root)
            NGINX_WEB_ROOT="$2"
            shift 2
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

    export SERVICE_NAME API_SERVICE_NAME INSTALL_DIR SERVICE_USER SERVICE_GROUP LEGACY_ENV_FILE
    export OUTPUT_DIR LOG_FILE SCAN_DATA_LOG_DIR NGINX_SITE_NAME NGINX_WEB_ROOT
    exec sudo --preserve-env=SERVICE_NAME,API_SERVICE_NAME,INSTALL_DIR,SERVICE_USER,SERVICE_GROUP,LEGACY_ENV_FILE,OUTPUT_DIR,LOG_FILE,SCAN_DATA_LOG_DIR,NGINX_SITE_NAME,NGINX_WEB_ROOT "$0"
fi

UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
API_UNIT_FILE="/etc/systemd/system/${API_SERVICE_NAME}.service"
NGINX_SITE_FILE="/etc/nginx/sites-available/${NGINX_SITE_NAME}.conf"
NGINX_SITE_LINK="/etc/nginx/sites-enabled/${NGINX_SITE_NAME}.conf"

if command -v systemctl >/dev/null 2>&1; then
    systemctl disable --now "${SERVICE_NAME}.service" >/dev/null 2>&1 || true
    systemctl disable --now "${API_SERVICE_NAME}.service" >/dev/null 2>&1 || true
fi

rm -f "${NGINX_SITE_LINK}"
rm -f "${NGINX_SITE_FILE}"
rm -f "${UNIT_FILE}"
rm -f "${API_UNIT_FILE}"
rm -f "${CONFIG_FILE}"
rm -f "${LEGACY_ENV_FILE}"
rm -rf "${INSTALL_DIR}"
rmdir "${NGINX_WEB_ROOT}" >/dev/null 2>&1 || true

if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload
    systemctl reset-failed "${SERVICE_NAME}.service" >/dev/null 2>&1 || true
    systemctl reset-failed "${API_SERVICE_NAME}.service" >/dev/null 2>&1 || true

    if command -v nginx >/dev/null 2>&1; then
        nginx -t >/dev/null 2>&1 && systemctl reload nginx >/dev/null 2>&1 || true
    fi
fi

cat <<DONE
Uninstalled ${SERVICE_NAME}.service

Removed:
  ${INSTALL_DIR}
  ${UNIT_FILE}
  ${API_UNIT_FILE}
  ${CONFIG_FILE}
  ${LEGACY_ENV_FILE}
  ${NGINX_SITE_FILE}
  ${NGINX_SITE_LINK}
DONE

cat <<KEPT

Preserved:
  ${OUTPUT_DIR}
  ${LOG_FILE}
  ${SCAN_DATA_LOG_DIR}
  ${NGINX_WEB_ROOT} (if it contains files)
  nginx package
KEPT

cat <<USER_GROUP

Service identity preserved for future installs:
  user: ${SERVICE_USER}
  group: ${SERVICE_GROUP}
USER_GROUP
