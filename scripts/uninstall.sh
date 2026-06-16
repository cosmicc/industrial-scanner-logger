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
NGINX_WEB_ROOT="${NGINX_WEB_ROOT:-/var/www/scanner-site}"
UPDATE_SERVICES_BIN="${UPDATE_SERVICES_BIN:-/usr/local/bin/update-services}"
REFRESH_APP_CONFIG_BIN="${REFRESH_APP_CONFIG_BIN:-/usr/local/bin/refresh-app-config}"
REFRESH_NGINX_BIN="${REFRESH_NGINX_BIN:-/usr/local/bin/refresh-nginx-config}"

usage() {
    cat <<USAGE
Usage: sudo scripts/uninstall.sh [options]

Uninstall the Industrial Scanner Logger service startup integration.

Options:
  --service-name NAME    systemd service name [${SERVICE_NAME}]
  --api-service-name NAME REST API service name [${API_SERVICE_NAME}]
  --install-dir DIR      application install directory to preserve [${INSTALL_DIR}]
  --user USER            service user name to preserve [${SERVICE_USER}]
  --group GROUP          service group name to preserve [${SERVICE_GROUP}]
  --output-dir DIR       scanner CSV output directory to preserve [${OUTPUT_DIR}]
  --log-file PATH        troubleshooting log file to preserve [${LOG_FILE}]
  --scan-data-log-dir DIR daily raw scan event log directory to preserve [${SCAN_DATA_LOG_DIR}]
  --nginx-site-name NAME nginx site file name to remove [${NGINX_SITE_NAME}]
  --nginx-web-root DIR   document root to preserve [${NGINX_WEB_ROOT}]
  --refresh-app-config-bin PATH app config refresh helper path to preserve [${REFRESH_APP_CONFIG_BIN}]
  --refresh-nginx-bin PATH nginx refresh helper path to preserve [${REFRESH_NGINX_BIN}]
  -h, --help             show this help

The receiver config file is always preserved.
The old /etc/default service defaults file is removed if present.
The installed application directory is preserved.
The service user and group are preserved so existing files keep valid owners.
Scanner CSV logs, script logs, raw scan data logs, helper scripts, and web files are preserved.
PostgreSQL, PostgreSQL roles, databases, schemas, and scan data are preserved.
The nginx package is preserved because it may serve other sites, but the app nginx site is removed.
The UFW firewall package and host firewall state are preserved.
USAGE
}

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Missing required command: $1" >&2
        exit 1
    fi
}

load_existing_app_config() {
    if [[ ! -f "${CONFIG_FILE}" ]]; then
        return
    fi

    echo "Reading preserved app config for uninstall metadata: ${CONFIG_FILE}"

    # The config file is preserved. Its path values are used only for accurate
    # reporting and for finding the app nginx site name to remove.
    eval "$(
        python3 - "${CONFIG_FILE}" <<'PY'
import configparser
import shlex
import sys


config_path = sys.argv[1]
config = configparser.ConfigParser(interpolation=None)
config.read(config_path)


def emit(name: str, value: str):
    print(f"{name}={shlex.quote(str(value))}")


def emit_option(section: str, option: str, variable: str):
    if config.has_option(section, option):
        emit(variable, config.get(section, option, raw=True))


emit_option("receiver", "output_dir", "OUTPUT_DIR")
emit_option("logging", "log_file", "LOG_FILE")
emit_option("logging", "scan_data_log_dir", "SCAN_DATA_LOG_DIR")
emit_option("nginx", "site_name", "NGINX_SITE_NAME")
emit_option("nginx", "web_root", "NGINX_WEB_ROOT")
PY
    )"
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
        --refresh-app-config-bin)
            REFRESH_APP_CONFIG_BIN="$2"
            shift 2
            ;;
        --refresh-nginx-bin)
            REFRESH_NGINX_BIN="$2"
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
    echo "This uninstaller must be run as root. Re-run it with sudo." >&2
    exit 1
fi

require_command python3
load_existing_app_config

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
rm -f "${LEGACY_ENV_FILE}"

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
  ${UNIT_FILE}
  ${API_UNIT_FILE}
  ${LEGACY_ENV_FILE}
  ${NGINX_SITE_FILE}
  ${NGINX_SITE_LINK}
DONE

cat <<KEPT

Preserved:
  ${CONFIG_FILE}
  ${INSTALL_DIR}
  ${OUTPUT_DIR}
  ${LOG_FILE}
  ${SCAN_DATA_LOG_DIR}
  ${NGINX_WEB_ROOT}
  ${UPDATE_SERVICES_BIN}
  ${REFRESH_APP_CONFIG_BIN}
  ${REFRESH_NGINX_BIN}
  service user/group: ${SERVICE_USER}:${SERVICE_GROUP}
  PostgreSQL package/service
  PostgreSQL roles, databases, schemas, and scan data
  nginx package
  UFW firewall package and host firewall state
KEPT
