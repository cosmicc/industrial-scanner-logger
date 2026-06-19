"""
Read-only command-line health report for Industrial Scanner Logger.

The CLI uses the same health collection code as the web dashboard, then formats
the most important operational checks for a shell session. It intentionally
prints summarized scan data only and redacts secret-looking error text.
"""

import argparse
import os
import re
import sys
from collections import OrderedDict
from typing import Optional

from industrial_scanner_logger import api
from industrial_scanner_logger.receiver import DEFAULT_CONFIG_FILE, load_receiver_config

DEFAULT_SERVICE_NAME = "industrial-scanner-logger"
DEFAULT_NGINX_SERVICE_NAME = "nginx"
DEFAULT_POSTGRESQL_SERVICE_NAME = "postgresql"
COLOR_AUTO = "auto"
COLOR_ALWAYS = "always"
COLOR_NEVER = "never"
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b((?:password|passwd|pwd|token|secret|api[_-]?key|apikey)\s*=\s*)[^\s&;]+"
)
SECRET_HEADER_RE = re.compile(
    r"(?i)\b((?:authorization:\s*bearer|x-scanner-api-key:)\s*)[^\s]+"
)
URL_USERINFO_RE = re.compile(r"([a-z][a-z0-9+.-]*://)([^/\s:@]+)(?::[^@\s/]*)?@")


def parse_args(argv: Optional[list[str]] = None):
    default_service_name = os.environ.get("SERVICE_NAME", DEFAULT_SERVICE_NAME)
    default_api_service_name = os.environ.get(
        "API_SERVICE_NAME",
        f"{default_service_name.removesuffix('.service')}-api",
    )

    parser = argparse.ArgumentParser(
        description="Print a read-only Industrial Scanner Logger health report.",
    )
    parser.add_argument(
        "--config",
        default=os.environ.get("CONFIG_FILE", DEFAULT_CONFIG_FILE),
        help=f"Path to the app config file [{DEFAULT_CONFIG_FILE}]",
    )
    parser.add_argument(
        "--service-name",
        default=default_service_name,
        help=f"Scanner receiver systemd service name [{default_service_name}]",
    )
    parser.add_argument(
        "--api-service-name",
        default=default_api_service_name,
        help=f"REST API systemd service name [{default_api_service_name}]",
    )
    parser.add_argument(
        "--nginx-service-name",
        default=os.environ.get("NGINX_SERVICE_NAME", DEFAULT_NGINX_SERVICE_NAME),
        help=f"nginx systemd service name [{DEFAULT_NGINX_SERVICE_NAME}]",
    )
    parser.add_argument(
        "--postgresql-service-name",
        default=os.environ.get("POSTGRESQL_SERVICE_NAME", DEFAULT_POSTGRESQL_SERVICE_NAME),
        help=f"PostgreSQL systemd service name [{DEFAULT_POSTGRESQL_SERVICE_NAME}]",
    )
    parser.add_argument(
        "--skip-nginx",
        action="store_true",
        help="Do not check the nginx service.",
    )
    parser.add_argument(
        "--skip-postgresql-service",
        action="store_true",
        help="Do not check the local PostgreSQL service.",
    )
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Always exit 0 after printing the report.",
    )
    parser.add_argument(
        "--color",
        choices=[COLOR_AUTO, COLOR_ALWAYS, COLOR_NEVER],
        default=COLOR_AUTO,
        help="Colorize the report: auto, always, or never [auto].",
    )
    return parser.parse_args(argv)


def service_unit_name(service_name: str) -> str:
    service_name = str(service_name or "").strip()

    if not service_name:
        raise ValueError("service name must not be blank")

    if service_name.endswith(".service"):
        return service_name

    return f"{service_name}.service"


def build_cli_health(config, args) -> dict:
    scanner_service_unit = service_unit_name(args.service_name)
    api_service_unit = service_unit_name(args.api_service_name)
    dashboard_health = api.build_dashboard_health(
        config,
        scanner_service_unit=scanner_service_unit,
        api_service_unit=api_service_unit,
    )
    service_statuses = OrderedDict()
    service_statuses["scanner"] = dashboard_health["services"]["scanner"]
    service_statuses["api"] = dashboard_health["services"]["api"]

    if not args.skip_nginx:
        service_statuses["nginx"] = api.systemd_service_status(
            service_unit_name(args.nginx_service_name),
        )

    if not args.skip_postgresql_service:
        service_statuses["postgresql"] = api.systemd_service_status(
            service_unit_name(args.postgresql_service_name),
        )

    return build_cli_payload(config, dashboard_health, service_statuses)


def build_cli_payload(config, dashboard_health: dict, service_statuses: dict) -> dict:
    required_service_keys = required_services(config, service_statuses)
    service_problems = [
        service_key
        for service_key in required_service_keys
        if not service_statuses.get(service_key, {}).get("active", False)
    ]
    database_ok = bool(dashboard_health.get("database", {}).get("active"))
    storage_ok = bool(dashboard_health.get("storage", {}).get("ok"))
    mandatory_scanners_ok = bool(dashboard_health.get("mandatory_scanners", {}).get("ok"))
    outgoing_api_ok = outgoing_api_ready(
        dashboard_health.get("outgoing_api", {}),
        dashboard_health.get("database", {}),
    )
    config_loaded = bool(getattr(config, "config_loaded", False))
    problem_count = sum(
        [
            bool(service_problems),
            not database_ok,
            not storage_ok,
            not mandatory_scanners_ok,
            not outgoing_api_ok,
            not config_loaded,
        ]
    )

    return {
        "status": "ok" if problem_count == 0 else "degraded",
        "problem_count": problem_count,
        "config_file": getattr(config, "config_file", ""),
        "config_loaded": config_loaded,
        "postgresql_table": getattr(config, "postgresql_table", ""),
        "required_service_keys": required_service_keys,
        "service_problems": service_problems,
        "services": service_statuses,
        "dashboard_health": dashboard_health,
    }


def required_services(config, service_statuses: dict) -> list[str]:
    required_service_keys = ["scanner"]

    if getattr(config, "api_enabled", True):
        if "api" in service_statuses:
            required_service_keys.append("api")
        if "nginx" in service_statuses:
            required_service_keys.append("nginx")

    return required_service_keys


def outgoing_api_ready(outgoing_api: dict, database: Optional[dict] = None) -> bool:
    if not outgoing_api.get("enabled", False):
        return True

    if outgoing_api_not_checked(outgoing_api, database or {}):
        return True

    return bool(outgoing_api.get("active", False))


def outgoing_api_not_checked(outgoing_api: dict, database: dict) -> bool:
    return (
        bool(outgoing_api.get("enabled", False))
        and str(outgoing_api.get("state", "")).strip().lower() == "unknown"
        and not bool(database.get("active", False))
        and not outgoing_api.get("error")
    )


def format_health_report(cli_health: dict, color_enabled: bool = False) -> str:
    dashboard_health = cli_health["dashboard_health"]
    colors = TerminalColors(color_enabled)
    lines = []

    lines.append(colors.title("Industrial Scanner Logger Health"))
    lines.append(
        f"{colors.label('Overall')}: "
        f"{marker_for_state(cli_health['status'], colors)} "
        f"{state_text(cli_health['status'].upper(), cli_health['status'], colors)}"
    )
    lines.append(f"{colors.label('Version')}: {colors.dim(dashboard_health.get('version', 'unknown'))}")
    lines.append(f"{colors.label('Generated')}: {colors.dim(dashboard_health.get('generated_at', 'unknown'))}")
    lines.append(
        f"{colors.label('Config')}: "
        f"{marker_for_bool(cli_health['config_loaded'], colors)} "
        f"{sanitize_message(cli_health.get('config_file') or 'unknown')}"
    )
    lines.append("")

    extend_section(lines, "Services", format_services(cli_health, colors), colors)
    extend_section(lines, "Database", format_database(cli_health, colors), colors)
    extend_section(lines, "Outgoing API", format_outgoing_api(dashboard_health, colors), colors)
    extend_section(lines, "Storage", format_storage(dashboard_health, colors), colors)
    extend_section(
        lines,
        "Scanner Connections",
        format_scanner_connections(dashboard_health, colors),
        colors,
    )
    extend_section(lines, "Today's Scan Data", format_today_scan_data(dashboard_health, colors), colors)
    extend_section(lines, "Critical Alerts", format_alerts(dashboard_health, colors), colors)
    extend_section(lines, "Logs", format_logs(dashboard_health, colors), colors)

    return "\n".join(lines).rstrip() + "\n"


def extend_section(
    lines: list[str],
    title: str,
    section_lines: list[str],
    colors: "TerminalColors",
):
    lines.append(colors.heading(title))
    lines.extend(section_lines)
    lines.append("")


def format_services(cli_health: dict, colors: "TerminalColors") -> list[str]:
    lines = []
    required_service_keys = set(cli_health.get("required_service_keys", []))

    for service_key, service_status in cli_health.get("services", {}).items():
        required_label = "required" if service_key in required_service_keys else "observed"
        service_title = service_display_name(service_key)
        active = bool(service_status.get("active", False))
        state = service_status.get("state", "unknown")
        unit = sanitize_message(service_status.get("unit", "unknown"))
        lines.append(
            f"  {marker_for_bool(active, colors)} "
            f"{colors.label(service_title)}: "
            f"{state_text(sanitize_message(state), 'ok' if active else 'fail', colors)} "
            f"{colors.dim(f'({unit}, {required_label})')}"
        )

        error = sanitize_message(service_status.get("error"))
        if error:
            lines.append(f"    {colors.fail('error')}: {error}")

    return lines or [f"  {marker_for_state('warning', colors)} no services were checked"]


def service_display_name(service_key: str) -> str:
    names = {
        "scanner": "Scanner receiver",
        "api": "REST API",
        "nginx": "nginx",
        "postgresql": "PostgreSQL",
    }
    return names.get(service_key, service_key)


def format_database(cli_health: dict, colors: "TerminalColors") -> list[str]:
    database = cli_health["dashboard_health"].get("database", {})
    active = bool(database.get("active", False))
    state = database.get("state", "unknown")
    lines = [
        f"  {marker_for_bool(active, colors)} "
        f"{colors.label('state')}: "
        f"{state_text(sanitize_message(state), 'ok' if active else 'fail', colors)}",
        f"  {colors.label('source table')}: {sanitize_message(cli_health.get('postgresql_table') or 'unknown')}",
    ]
    error = sanitize_message(database.get("error"))

    if error:
        lines.append(f"  {colors.fail('error')}: {error}")

    return lines


def format_outgoing_api(dashboard_health: dict, colors: "TerminalColors") -> list[str]:
    outgoing_api = dashboard_health.get("outgoing_api", {})
    database = dashboard_health.get("database", {})
    enabled = bool(outgoing_api.get("enabled", False))
    not_checked = outgoing_api_not_checked(outgoing_api, database)
    active = outgoing_api_ready(outgoing_api, database)
    state = outgoing_api_display_state(outgoing_api, not_checked)
    state_marker = marker_for_state("warning", colors) if not_checked else marker_for_bool(active, colors)
    state_severity = "warning" if not_checked else severity_for_state(state, active)
    lines = [
        f"  {state_marker} {colors.label('state')}: "
        f"{state_text(sanitize_message(state), state_severity, colors)}",
        f"  {colors.label('enabled')}: {colored_yes_no(enabled, colors, no_is_warning=False)}",
        f"  {colors.label('url configured')}: "
        f"{colored_yes_no(outgoing_api.get('url_configured'), colors, no_is_warning=enabled)}",
        f"  {colors.label('API key configured')}: "
        f"{colored_yes_no(outgoing_api.get('api_key_configured'), colors, no_is_warning=enabled)}",
    ]

    if not_checked:
        lines.append(
            f"  {colors.label('queue')}: "
            f"{colors.warn('unavailable until database health can be checked')}"
        )
    else:
        lines.append(
            f"  {colors.label('queue')}: "
            f"{queue_count_text(int_or_zero(outgoing_api.get('queue_count')), colors)} pending, "
            f"{queue_count_text(int_or_zero(outgoing_api.get('failed_queue_count')), colors)} failed"
        )

    optional_fields = [
        ("oldest queued", outgoing_api.get("oldest_queued_at")),
        ("last attempt", outgoing_api.get("last_attempt_at")),
        ("last HTTP status", outgoing_api.get("last_http_status")),
        ("last error", outgoing_api.get("last_error")),
        ("config error", outgoing_api.get("error")),
    ]

    for label, value in optional_fields:
        sanitized_value = sanitize_message(value)
        if sanitized_value:
            lines.append(f"  {colors.label(label)}: {sanitized_value}")

    return lines


def outgoing_api_display_state(outgoing_api: dict, not_checked: bool) -> str:
    if not_checked:
        return "not checked (database unavailable)"

    return outgoing_api.get("state", "unknown")


def format_storage(dashboard_health: dict, colors: "TerminalColors") -> list[str]:
    storage = dashboard_health.get("storage", {})
    ok = bool(storage.get("ok", False))
    storage_state = sanitize_message(storage.get("state", "unknown"))
    storage_severity = severity_for_state(storage_state, ok)
    warning_percent = float_or_zero(storage.get("warning_percent"))
    warning_bytes = int_or_zero(storage.get("warning_bytes"))
    lines = [
        f"  {marker_for_state(storage_state, colors)} {colors.label('state')}: "
        f"{state_text(storage_state, storage_severity, colors)}",
        f"  {colors.label('warning thresholds')}: <= {warning_percent:g}% free or <= {human_bytes(warning_bytes)}",
    ]

    for volume in storage.get("volumes", []):
        volume_ok = bool(volume.get("ok", False))
        volume_state = sanitize_message(volume.get("state", "ok" if volume_ok else "unknown"))
        volume_severity = severity_for_state(volume_state, volume_ok)
        label = sanitize_message(volume.get("label", "Volume"))
        path = sanitize_message(volume.get("path", "unknown"))
        checked_path = sanitize_message(volume.get("checked_path", "unknown"))
        free_percent = float_or_zero(volume.get("free_percent"))
        free_bytes = human_bytes(int_or_zero(volume.get("free_bytes")))
        lines.append(
            f"  {marker_for_state(volume_state, colors)} {colors.label(label)}: "
            f"{state_text(f'{free_percent:.2f}% free', volume_severity, colors)}, "
            f"{free_bytes} available ({path}; checked {checked_path})"
        )

        reasons = [sanitize_message(reason) for reason in volume.get("warning_reasons", [])]
        reasons = [reason for reason in reasons if reason]
        if reasons:
            lines.append(f"    {colors.warn('warning')}: {'; '.join(reasons)}")

        error = sanitize_message(volume.get("error"))
        if error:
            lines.append(f"    {colors.fail('error')}: {error}")

    return lines


def format_scanner_connections(dashboard_health: dict, colors: "TerminalColors") -> list[str]:
    mandatory_scanners = dashboard_health.get("mandatory_scanners", {})
    connected_scanners = dashboard_health.get("connected_scanners", [])
    connected_names = [
        sanitize_message(
            scanner.get("display_name") or f"Scanner {scanner.get('scanner_id')}"
        )
        for scanner in connected_scanners
    ]
    connected_required_scanner_ids = mandatory_scanners.get("connected_required_scanner_ids") or []
    required_scanner_ids = mandatory_scanners.get("required_scanner_ids") or []
    mandatory_ok = bool(mandatory_scanners.get("ok", False))
    lines = [
        f"  {colors.label('connected count')}: "
        f"{connection_count_text(int_or_zero(dashboard_health.get('connected_scanner_count')), colors)}",
        f"  {colors.label('connected scanners')}: {', '.join(connected_names) if connected_names else colors.warn('none')}",
        f"  {colors.label('mandatory scanners')}: {marker_for_bool(mandatory_ok, colors)} "
        f"{int_or_zero(len(connected_required_scanner_ids))}"
        f"/{int_or_zero(len(required_scanner_ids))} connected",
    ]

    warning = sanitize_message(mandatory_scanners.get("warning"))
    if warning:
        lines.append(f"  {colors.warn('warning')}: {warning}")

    for scanner in mandatory_scanners.get("required_scanners", []):
        connected = bool(scanner.get("connected", False))
        display_name = scanner.get("display_name") or f"Scanner {scanner.get('scanner_id')}"
        scanner_id = sanitize_message(scanner.get("scanner_id", "unknown"))
        lines.append(
            f"  {marker_for_bool(connected, colors)} {sanitize_message(display_name)} "
            f"(scanner {scanner_id})"
        )

    if not mandatory_scanners.get("configured", False):
        lines.append(f"  {colors.label('mandatory scanners configured')}: {colors.dim('no')}")

    return lines


def format_today_scan_data(dashboard_health: dict, colors: "TerminalColors") -> list[str]:
    daily_totals = dashboard_health.get("daily_totals", {})
    today = daily_totals.get("today", {})
    current_scan_rate = dashboard_health.get("current_scan_rate", {})
    last_received = dashboard_health.get("last_received")
    lines = [
        f"  {colors.label('totals')}: "
        f"{int_or_zero(today.get('total_scan_events'))} total, "
        f"{success_count_text(int_or_zero(today.get('successful_scans')), colors)} successful, "
        f"{warning_count_text(int_or_zero(today.get('duplicate_scans')), colors)} duplicate, "
        f"{failure_count_text(int_or_zero(today.get('failed_scans')), colors)} failed",
        f"  {colors.label('current rate')}: "
        f"{float_or_zero(current_scan_rate.get('scans_per_minute')):.2f}/minute, "
        f"{int_or_zero(current_scan_rate.get('scans_per_hour'))}/hour",
    ]

    if last_received:
        scanner_name = last_received.get("display_name") or f"Scanner {last_received.get('scanner_id')}"
        scan_status = "success" if last_received.get("is_success") else "failed"
        failure_reason = sanitize_message(last_received.get("failure_reason"))
        if failure_reason:
            scan_status = f"{scan_status}: {failure_reason}"
        scan_severity = "ok" if last_received.get("is_success") else "fail"
        lines.append(
            f"  {colors.label('last received')}: {sanitize_message(last_received.get('scan_timestamp'))} "
            f"from {sanitize_message(scanner_name)} ({state_text(scan_status, scan_severity, colors)})"
        )
    else:
        lines.append(f"  {colors.label('last received')}: {colors.warn('none')}")

    by_scanner_rows = daily_totals.get("today_by_scanner", [])
    if by_scanner_rows:
        lines.append(f"  {colors.label('by scanner')}:")
        for row in by_scanner_rows:
            display_name = row.get("display_name") or f"Scanner {row.get('scanner_id')}"
            lines.append(
                f"    {sanitize_message(display_name)}: "
                f"{int_or_zero(row.get('total_scan_events'))} total, "
                f"{success_count_text(int_or_zero(row.get('successful_scans')), colors)} successful, "
                f"{warning_count_text(int_or_zero(row.get('duplicate_scans')), colors)} duplicate, "
                f"{failure_count_text(int_or_zero(row.get('failed_scans')), colors)} failed"
            )
    else:
        lines.append(f"  {colors.label('by scanner')}: {colors.warn('no scan rows today')}")

    return lines


def format_alerts(dashboard_health: dict, colors: "TerminalColors") -> list[str]:
    duplicate_alert = dashboard_health.get("duplicate_alert")
    package_alerts = dashboard_health.get("package_alerts", [])
    lines = [
        f"  {colors.label('active package alerts')}: {warning_count_text(len(package_alerts), colors)}",
    ]

    if duplicate_alert:
        scanner_name = duplicate_alert.get("display_name") or f"Scanner {duplicate_alert.get('scanner_id')}"
        lines.append(
            f"  {colors.warn('duplicate alert')}: {sanitize_message(scanner_name)} "
            f"for {float_or_zero(duplicate_alert.get('alert_remaining_seconds')):.1f}s more"
        )
    else:
        lines.append(f"  {colors.label('duplicate alert')}: {colors.ok('none')}")

    return lines


def format_logs(dashboard_health: dict, colors: "TerminalColors") -> list[str]:
    script_log = dashboard_health.get("script_log", {})
    available = bool(script_log.get("available", False))
    lines = [
        f"  {colors.label('troubleshooting log')}: {marker_for_bool(available, colors)} "
        f"{sanitize_message(script_log.get('path', 'unknown'))}",
    ]
    error = sanitize_message(script_log.get("error"))

    if error:
        lines.append(f"  {colors.fail('error')}: {error}")

    return lines


class TerminalColors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    CYAN = "\033[36m"

    def __init__(self, enabled: bool):
        self.enabled = enabled

    def paint(self, text, code: str) -> str:
        text = str(text)

        if not self.enabled:
            return text

        return f"{code}{text}{self.RESET}"

    def title(self, text) -> str:
        return self.paint(text, f"{self.BOLD}{self.CYAN}")

    def heading(self, text) -> str:
        return self.paint(text, f"{self.BOLD}{self.CYAN}")

    def label(self, text) -> str:
        return self.paint(text, self.BOLD)

    def dim(self, text) -> str:
        return self.paint(text, self.DIM)

    def ok(self, text) -> str:
        return self.paint(text, self.GREEN)

    def warn(self, text) -> str:
        return self.paint(text, self.YELLOW)

    def fail(self, text) -> str:
        return self.paint(text, self.RED)


def marker_for_bool(value: bool, colors: Optional[TerminalColors] = None) -> str:
    colors = colors or TerminalColors(False)
    return colors.ok("[OK]") if value else colors.fail("[FAIL]")


def marker_for_state(state: str, colors: Optional[TerminalColors] = None) -> str:
    colors = colors or TerminalColors(False)
    normalized_state = str(state or "").strip().lower()

    if normalized_state in {"ok", "active", "disabled"}:
        return colors.ok("[OK]")

    if normalized_state in {"degraded", "low", "pending", "unknown", "warning", "warn"}:
        return colors.warn("[WARN]")

    return colors.fail("[FAIL]")


def state_text(text: str, severity: str, colors: TerminalColors) -> str:
    severity = str(severity or "").strip().lower()

    if severity in {"ok", "active", "disabled", "success"}:
        return colors.ok(text)

    if severity in {"warning", "warn", "degraded", "low", "pending", "unknown"}:
        return colors.warn(text)

    return colors.fail(text)


def severity_for_state(state: str, active: bool) -> str:
    normalized_state = str(state or "").strip().lower()

    if active or normalized_state in {"ok", "active", "disabled"}:
        return "ok"

    if normalized_state in {"degraded", "low", "pending", "unknown"}:
        return "warning"

    return "fail"


def colored_yes_no(value, colors: TerminalColors, no_is_warning: bool = True) -> str:
    if bool(value):
        return colors.ok("yes")

    if no_is_warning:
        return colors.warn("no")

    return colors.dim("no")


def success_count_text(value: int, colors: TerminalColors) -> str:
    return colors.ok(value) if value > 0 else str(value)


def warning_count_text(value: int, colors: TerminalColors) -> str:
    return colors.warn(value) if value > 0 else str(value)


def failure_count_text(value: int, colors: TerminalColors) -> str:
    return colors.fail(value) if value > 0 else str(value)


def queue_count_text(value: int, colors: TerminalColors) -> str:
    return colors.warn(value) if value > 0 else colors.ok(value)


def connection_count_text(value: int, colors: TerminalColors) -> str:
    return colors.ok(value) if value > 0 else colors.warn(value)


def sanitize_message(value, max_chars: int = 240) -> str:
    if value is None:
        return ""

    text = str(value).replace("\r", " ").replace("\n", " ")
    text = URL_USERINFO_RE.sub(r"\1[redacted]@", text)
    text = SECRET_ASSIGNMENT_RE.sub(r"\1[redacted]", text)
    text = SECRET_HEADER_RE.sub(r"\1[redacted]", text)
    text = " ".join(text.split())

    if len(text) <= max_chars:
        return text

    omitted_count = len(text) - max_chars
    return f"{text[:max_chars]}...[truncated {omitted_count} chars]"


def int_or_zero(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def float_or_zero(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def yes_no(value) -> str:
    return "yes" if bool(value) else "no"


def human_bytes(byte_count: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    value = float(byte_count)

    for unit in units:
        if abs(value) < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"

        value /= 1024

    return f"{byte_count} B"


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)

    try:
        config = load_receiver_config(args.config)
        cli_health = build_cli_health(config, args)
    except Exception as exc:
        print(f"industrial-scanner-health: {sanitize_message(exc)}", file=sys.stderr)
        return 2

    print(
        format_health_report(
            cli_health,
            color_enabled=should_use_color(args.color, sys.stdout),
        ),
        end="",
    )

    if args.no_fail:
        return 0

    return 0 if cli_health["status"] == "ok" else 1


def should_use_color(color_mode: str, output_stream) -> bool:
    if color_mode == COLOR_ALWAYS:
        return True

    if color_mode == COLOR_NEVER:
        return False

    if os.environ.get("NO_COLOR"):
        return False

    return bool(getattr(output_stream, "isatty", lambda: False)())


if __name__ == "__main__":
    raise SystemExit(main())
