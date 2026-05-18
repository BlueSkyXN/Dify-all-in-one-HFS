#!/usr/bin/env python3
"""Small read-only operations service for the Dify all-in-one container."""

from __future__ import annotations

import html
import hmac
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


STARTED_AT = time.time()
LOG_DIR = Path(os.environ.get("OPS_LOG_DIR", "/data/logs"))
SUPERVISOR_CONFIG = "/etc/supervisor/conf.d/supervisord.conf"
MAX_CHECKS = 32

DEFAULT_SERVICE_LOGS = {
    "supervisord": "supervisord.log",
    "postgres": "postgres.log",
    "postgres.err": "postgres.err",
    "redis": "redis.log",
    "redis.err": "redis.err",
    "postgres-backup": "postgres-backup.log",
    "postgres-backup.err": "postgres-backup.err",
    "plugin-daemon": "plugin-daemon.log",
    "plugin-daemon.err": "plugin-daemon.err",
    "dify-api": "dify-api.log",
    "dify-api.err": "dify-api.err",
    "dify-worker": "dify-worker.log",
    "dify-worker.err": "dify-worker.err",
    "dify-beat": "dify-beat.log",
    "dify-beat.err": "dify-beat.err",
    "nginx": "nginx.log",
}

SAFE_CONFIG_KEYS = [
    "DIFY_VERSION",
    "DEPLOY_ENV",
    "PUBLIC_URL",
    "SPACE_HOST",
    "SPACE_ID",
    "PERSIST_MODE",
    "PERSIST_ROOT",
    "RUNTIME_ROOT",
    "REDIS_PERSISTENCE",
    "PLUGIN_CWD_PERSISTENCE",
    "POSTGRES_BUCKET_FAILURE_MODE",
    "POSTGRES_BACKUP_ENABLED",
    "POSTGRES_BACKUP_DIR",
    "POSTGRES_BACKUP_INTERVAL_SECONDS",
    "MARKETPLACE_ENABLED",
    "FORCE_VERIFYING_SIGNATURE",
    "SANDBOX_ENABLE_NETWORK",
    "VECTOR_STORE",
    "STORAGE_TYPE",
    "DB_TYPE",
    "DB_HOST",
    "DB_PORT",
    "DB_DATABASE",
    "REDIS_HOST",
    "REDIS_PORT",
    "PLUGIN_DAEMON_URL",
    "CODE_EXECUTION_ENDPOINT",
    "OPS_PORT",
    "OPS_DEFAULT_CHECKS_ENABLED",
    "OPS_LOG_DIR",
]

SECRET_KEYS = [
    "SECRET_KEY",
    "PLUGIN_DAEMON_KEY",
    "PLUGIN_DIFY_INNER_API_KEY",
    "INNER_API_KEY_FOR_PLUGIN",
    "CODE_EXECUTION_API_KEY",
    "SANDBOX_API_KEY",
    "OPS_TOKEN",
]

ERROR_PATTERNS = [
    "Permission denied",
    "failed to initialize python dependencies sandbox",
    "connect() failed",
    "exited:",
    "FATAL",
    "Traceback",
    "ERROR",
    "[error]",
]

IGNORED_ERROR_PATTERNS = [
    "FATAL:  the database system is starting up",
]


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def safe_log_filename(filename: Any) -> str | None:
    if not isinstance(filename, str) or not filename:
        return None
    path = Path(filename)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return str(path)


def load_service_logs() -> dict[str, str]:
    service_logs = dict(DEFAULT_SERVICE_LOGS)
    raw = env("OPS_LOG_SERVICES_JSON")
    if not raw:
        return service_logs
    try:
        configured = json.loads(raw)
    except json.JSONDecodeError:
        return service_logs
    if not isinstance(configured, dict):
        return service_logs
    for service, filename in configured.items():
        if not isinstance(service, str) or not service:
            continue
        safe_filename = safe_log_filename(filename)
        if safe_filename:
            service_logs[service] = safe_filename
    return service_logs


SERVICE_LOGS = load_service_logs()


def parse_int(value: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(parsed, minimum)
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed


def parse_optional_int(value: Any, minimum: int | None = None, maximum: int | None = None) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if minimum is not None and parsed < minimum:
        return None
    if maximum is not None and parsed > maximum:
        return None
    return parsed


def parse_float(value: Any, default: float, minimum: float | None = None, maximum: float | None = None) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(parsed, minimum)
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed


def parse_bool(value: str, default: bool = False) -> bool:
    if value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_json_list(name: str) -> list[Any]:
    raw = env(name)
    if not raw:
        return []
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return loaded if isinstance(loaded, list) else []


def truncate_text(value: str, limit: int = 2048) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "...<truncated>"


def run_cmd(args: list[str], timeout: float = 2.0) -> dict[str, Any]:
    started = time.time()
    try:
        completed = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": truncate_text(completed.stdout.strip()),
            "stderr": truncate_text(completed.stderr.strip()),
            "duration_ms": round((time.time() - started) * 1000),
        }
    except FileNotFoundError as exc:
        return {
            "ok": False,
            "returncode": 127,
            "stdout": "",
            "stderr": str(exc),
            "duration_ms": round((time.time() - started) * 1000),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "returncode": None,
            "stdout": truncate_text((exc.stdout or "").strip()),
            "stderr": f"timeout after {timeout}s",
            "duration_ms": round((time.time() - started) * 1000),
        }


def status_ok(status: int, expected_status: int | None = None) -> bool:
    if expected_status is not None:
        return status == expected_status
    return 200 <= status < 500


def http_check(name: str, url: str, timeout: float = 2.0, expected_status: int | None = None) -> dict[str, Any]:
    started = time.time()
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "dify-aio-ops/1.0"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=timeout) as response:
            body = response.read(256).decode("utf-8", errors="replace")
            payload = {
                "name": name,
                "ok": status_ok(response.status, expected_status),
                "status": response.status,
                "duration_ms": round((time.time() - started) * 1000),
                "sample": body,
            }
            if expected_status is not None:
                payload["expected_status"] = expected_status
            return payload
    except urllib.error.HTTPError as exc:
        body = exc.read(256).decode("utf-8", errors="replace")
        payload = {
            "name": name,
            "ok": status_ok(exc.code, expected_status),
            "status": exc.code,
            "duration_ms": round((time.time() - started) * 1000),
            "sample": body,
        }
        if expected_status is not None:
            payload["expected_status"] = expected_status
        return payload
    except Exception as exc:
        return {
            "name": name,
            "ok": False,
            "status": None,
            "duration_ms": round((time.time() - started) * 1000),
            "error": str(exc),
        }


def command_check(name: str, args: list[str], expect: str = "", timeout: float = 2.0) -> dict[str, Any]:
    result = run_cmd(args, timeout=timeout)
    output = f"{result['stdout']}\n{result['stderr']}"
    result["name"] = name
    result["ok"] = result["ok"] and (not expect or expect in output)
    if expect:
        result["expect"] = expect
    return result


def tcp_check(name: str, host: str, port: int, timeout: float = 1.0) -> dict[str, Any]:
    started = time.time()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {"name": name, "ok": True, "duration_ms": round((time.time() - started) * 1000)}
    except Exception as exc:
        return {
            "name": name,
            "ok": False,
            "duration_ms": round((time.time() - started) * 1000),
            "error": str(exc),
        }


def extra_http_checks() -> list[Any]:
    checks = []
    for item in load_json_list("OPS_EXTRA_HTTP_CHECKS_JSON"):
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        url = item.get("url")
        if not isinstance(name, str) or not name or not isinstance(url, str) or not url:
            continue
        timeout = parse_float(item.get("timeout", 2.0), 2.0, minimum=0.1, maximum=30.0)
        expected_status = item.get("expected_status")
        if expected_status is not None:
            expected_status = parse_optional_int(expected_status, minimum=100, maximum=599)
        checks.append(partial(http_check, name, url, timeout, expected_status))
    return checks


def extra_tcp_checks() -> list[Any]:
    checks = []
    for item in load_json_list("OPS_EXTRA_TCP_CHECKS_JSON"):
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        host = item.get("host", "127.0.0.1")
        if not isinstance(name, str) or not name or not isinstance(host, str) or not host:
            continue
        port = parse_int(str(item.get("port", "")), 0, minimum=1, maximum=65535)
        if not port:
            continue
        timeout = parse_float(item.get("timeout", 1.0), 1.0, minimum=0.1, maximum=30.0)
        checks.append(partial(tcp_check, name, host, port, timeout))
    return checks


def extra_command_checks() -> list[Any]:
    checks = []
    for item in load_json_list("OPS_EXTRA_COMMAND_CHECKS_JSON"):
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        args = item.get("args")
        if not isinstance(name, str) or not name or not isinstance(args, list):
            continue
        safe_args = [arg for arg in args if isinstance(arg, str) and arg]
        if not safe_args or len(safe_args) != len(args):
            continue
        expect = item.get("expect", "")
        if not isinstance(expect, str):
            expect = ""
        timeout = parse_float(item.get("timeout", 2.0), 2.0, minimum=0.1, maximum=30.0)
        checks.append(partial(command_check, name, safe_args, expect, timeout))
    return checks


def supervisor_status() -> dict[str, Any]:
    result = run_cmd(["supervisorctl", "-c", SUPERVISOR_CONFIG, "status"], timeout=3.0)
    programs = []
    for line in result["stdout"].splitlines():
        parts = line.split(None, 2)
        if len(parts) >= 2:
            programs.append(
                {
                    "name": parts[0],
                    "state": parts[1],
                    "description": parts[2] if len(parts) > 2 else "",
                    "ok": parts[1] == "RUNNING",
                }
            )
    result["programs"] = programs
    result["ok"] = result["ok"] and all(program["ok"] for program in programs)
    return result


def redis_check() -> dict[str, Any]:
    args = ["redis-cli", "-h", env("REDIS_HOST", "127.0.0.1"), "-p", env("REDIS_PORT", "6379")]
    password = env("REDIS_PASSWORD")
    if password:
        args.extend(["--no-auth-warning", "-a", password])
    args.append("ping")
    result = run_cmd(args, timeout=2.0)
    return {"name": "redis", "ok": result["ok"] and "PONG" in result["stdout"], **result}


def postgres_check() -> dict[str, Any]:
    args = [
        "pg_isready",
        "-h",
        env("DB_HOST", "127.0.0.1"),
        "-p",
        env("DB_PORT", "5432"),
        "-U",
        env("DB_USERNAME", "dify"),
    ]
    result = run_cmd(args, timeout=2.0)
    return {"name": "postgres", **result}


def collect_checks(checks_to_run: list[Any]) -> list[dict[str, Any]]:
    if not checks_to_run:
        return []
    checks_to_run = checks_to_run[:MAX_CHECKS]
    checks: list[dict[str, Any] | None] = [None] * len(checks_to_run)
    with ThreadPoolExecutor(max_workers=min(len(checks_to_run), MAX_CHECKS)) as executor:
        futures = [(index, executor.submit(check)) for index, check in enumerate(checks_to_run)]
        for index, future in futures:
            try:
                checks[index] = future.result(timeout=31.0)
            except Exception as exc:
                checks[index] = {"name": f"check-{index}", "ok": False, "error": str(exc)}
    return [check for check in checks if check is not None]


def health_payload(public: bool = False) -> dict[str, Any]:
    checks_to_run = []
    if parse_bool(env("OPS_DEFAULT_CHECKS_ENABLED", "true"), default=True):
        checks_to_run.extend(
            [
                postgres_check,
                redis_check,
                partial(tcp_check, "plugin-daemon-tcp", "127.0.0.1", parse_int(env("PLUGIN_DAEMON_PORT"), 5002)),
                partial(tcp_check, "sandbox-tcp", "127.0.0.1", parse_int(env("SANDBOX_PORT"), 8194)),
                partial(http_check, "dify-api-health", "http://127.0.0.1:5001/health"),
                partial(http_check, "dify-web", "http://127.0.0.1:3000/apps"),
                partial(http_check, "nginx", "http://127.0.0.1:7860/nginx-health"),
                partial(http_check, "dify-setup", "http://127.0.0.1:5001/console/api/setup"),
                partial(http_check, "dify-init", "http://127.0.0.1:5001/console/api/init"),
            ]
        )
    checks_to_run.extend(extra_http_checks())
    checks_to_run.extend(extra_tcp_checks())
    checks_to_run.extend(extra_command_checks())
    checks = collect_checks(checks_to_run)

    payload: dict[str, Any] = {
        "ok": bool(checks) and all(check["ok"] for check in checks),
        "uptime_seconds": int(time.time() - STARTED_AT),
        "checks": checks,
    }
    if not checks:
        payload["error"] = "no checks configured"
    if not public:
        payload["supervisor"] = supervisor_status()
        payload["version"] = version_payload()
    return payload


def version_payload() -> dict[str, Any]:
    return {
        "service": "dify-all-in-one-ops",
        "dify_version": env("DIFY_VERSION"),
        "deploy_env": env("DEPLOY_ENV"),
        "public_url": env("PUBLIC_URL"),
        "space_host": env("SPACE_HOST"),
        "space_id": env("SPACE_ID"),
        "python": sys.version.split()[0],
        "started_at": STARTED_AT,
        "uptime_seconds": int(time.time() - STARTED_AT),
    }


def config_payload() -> dict[str, Any]:
    return {
        "safe_values": {key: env(key) for key in SAFE_CONFIG_KEYS if key in os.environ},
        "secret_presence": {key: bool(env(key)) for key in SECRET_KEYS},
        "log_services": sorted(SERVICE_LOGS),
        "extra_checks": {
            "http": [check.get("name") for check in load_json_list("OPS_EXTRA_HTTP_CHECKS_JSON") if isinstance(check, dict)],
            "tcp": [check.get("name") for check in load_json_list("OPS_EXTRA_TCP_CHECKS_JSON") if isinstance(check, dict)],
            "command": [
                check.get("name") for check in load_json_list("OPS_EXTRA_COMMAND_CHECKS_JSON") if isinstance(check, dict)
            ],
        },
    }


def bytes_from_kib(value: str) -> int:
    return int(value) * 1024


def memory_payload() -> dict[str, Any]:
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return {"ok": False, "error": "/proc/meminfo not available"}
    values: dict[str, int] = {}
    try:
        for line in meminfo.read_text(encoding="utf-8", errors="replace").splitlines():
            key, _, rest = line.partition(":")
            parts = rest.strip().split()
            if parts:
                values[key] = bytes_from_kib(parts[0])
    except OSError as exc:
        return {"ok": False, "error": str(exc)}

    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", values.get("MemFree", 0))
    used = max(total - available, 0)
    swap_total = values.get("SwapTotal", 0)
    swap_free = values.get("SwapFree", 0)
    swap_used = max(swap_total - swap_free, 0)
    return {
        "ok": total > 0,
        "total_bytes": total,
        "available_bytes": available,
        "used_bytes": used,
        "used_percent": round((used / total) * 100, 2) if total else 0,
        "swap_total_bytes": swap_total,
        "swap_used_bytes": swap_used,
        "swap_used_percent": round((swap_used / swap_total) * 100, 2) if swap_total else 0,
    }


def disk_usage(path: str) -> dict[str, Any]:
    try:
        stats = os.statvfs(path)
    except OSError as exc:
        return {"ok": False, "path": path, "error": str(exc)}
    total = stats.f_frsize * stats.f_blocks
    available = stats.f_frsize * stats.f_bavail
    used = max(total - available, 0)
    return {
        "ok": total > 0,
        "path": path,
        "total_bytes": total,
        "available_bytes": available,
        "used_bytes": used,
        "used_percent": round((used / total) * 100, 2) if total else 0,
    }


def process_count() -> int | None:
    proc = Path("/proc")
    if not proc.exists():
        return None
    try:
        return sum(1 for child in proc.iterdir() if child.name.isdigit())
    except OSError:
        return None


def system_uptime_seconds() -> int | None:
    uptime = Path("/proc/uptime")
    if not uptime.exists():
        return None
    try:
        return int(float(uptime.read_text(encoding="utf-8").split()[0]))
    except (OSError, ValueError, IndexError):
        return None


def cpu_payload() -> dict[str, Any]:
    try:
        load1, load5, load15 = os.getloadavg()
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "load1": round(load1, 2),
        "load5": round(load5, 2),
        "load15": round(load15, 2),
        "cpu_count": os.cpu_count(),
    }


def system_payload() -> dict[str, Any]:
    paths = ["/", "/data"]
    for configured in [env("PERSIST_ROOT"), env("RUNTIME_ROOT")]:
        if configured and configured not in paths:
            paths.append(configured)
    return {
        "ok": True,
        "cpu": cpu_payload(),
        "memory": memory_payload(),
        "disk": {path: disk_usage(path) for path in paths},
        "uptime_seconds": system_uptime_seconds(),
        "ops_uptime_seconds": int(time.time() - STARTED_AT),
        "process_count": process_count(),
    }


def metric_escape(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def metric_bool(value: Any) -> int:
    return 1 if bool(value) else 0


def metrics_payload() -> str:
    health = health_payload(public=True)
    system = system_payload()
    lines = [
        "# HELP dify_aio_ops_up Whether the ops service is running.",
        "# TYPE dify_aio_ops_up gauge",
        "dify_aio_ops_up 1",
        "# HELP dify_aio_ops_health_ok Whether all configured health checks are passing.",
        "# TYPE dify_aio_ops_health_ok gauge",
        f"dify_aio_ops_health_ok {metric_bool(health.get('ok'))}",
        "# HELP dify_aio_ops_check_ok Individual health check status.",
        "# TYPE dify_aio_ops_check_ok gauge",
    ]
    for check in health.get("checks", []):
        name = metric_escape(check.get("name", "unknown"))
        lines.append(f'dify_aio_ops_check_ok{{check="{name}"}} {metric_bool(check.get("ok"))}')
        if isinstance(check.get("duration_ms"), int | float):
            lines.append(f'dify_aio_ops_check_duration_ms{{check="{name}"}} {check["duration_ms"]}')

    lines.extend(
        [
            "# HELP dify_aio_ops_uptime_seconds Ops service uptime in seconds.",
            "# TYPE dify_aio_ops_uptime_seconds gauge",
            f"dify_aio_ops_uptime_seconds {system['ops_uptime_seconds']}",
        ]
    )
    if system.get("uptime_seconds") is not None:
        lines.extend(
            [
                "# HELP dify_aio_system_uptime_seconds Container system uptime in seconds.",
                "# TYPE dify_aio_system_uptime_seconds gauge",
                f"dify_aio_system_uptime_seconds {system['uptime_seconds']}",
            ]
        )
    if system.get("process_count") is not None:
        lines.extend(
            [
                "# HELP dify_aio_system_process_count Number of processes visible in /proc.",
                "# TYPE dify_aio_system_process_count gauge",
                f"dify_aio_system_process_count {system['process_count']}",
            ]
        )

    cpu = system.get("cpu", {})
    if cpu.get("ok"):
        lines.extend(
            [
                "# HELP dify_aio_system_load System load average.",
                "# TYPE dify_aio_system_load gauge",
                f'dify_aio_system_load{{window="1m"}} {cpu["load1"]}',
                f'dify_aio_system_load{{window="5m"}} {cpu["load5"]}',
                f'dify_aio_system_load{{window="15m"}} {cpu["load15"]}',
            ]
        )

    memory = system.get("memory", {})
    if memory.get("ok"):
        lines.extend(
            [
                "# HELP dify_aio_system_memory_bytes Memory usage in bytes.",
                "# TYPE dify_aio_system_memory_bytes gauge",
                f'dify_aio_system_memory_bytes{{type="total"}} {memory["total_bytes"]}',
                f'dify_aio_system_memory_bytes{{type="available"}} {memory["available_bytes"]}',
                f'dify_aio_system_memory_bytes{{type="used"}} {memory["used_bytes"]}',
                "# HELP dify_aio_system_memory_used_percent Memory used percent.",
                "# TYPE dify_aio_system_memory_used_percent gauge",
                f"dify_aio_system_memory_used_percent {memory['used_percent']}",
            ]
        )

    lines.extend(
        [
            "# HELP dify_aio_system_disk_bytes Disk usage in bytes.",
            "# TYPE dify_aio_system_disk_bytes gauge",
        ]
    )
    for path, usage in system.get("disk", {}).items():
        if not usage.get("ok"):
            continue
        label = metric_escape(path)
        lines.append(f'dify_aio_system_disk_bytes{{path="{label}",type="total"}} {usage["total_bytes"]}')
        lines.append(f'dify_aio_system_disk_bytes{{path="{label}",type="available"}} {usage["available_bytes"]}')
        lines.append(f'dify_aio_system_disk_bytes{{path="{label}",type="used"}} {usage["used_bytes"]}')
        lines.append(f'dify_aio_system_disk_used_percent{{path="{label}"}} {usage["used_percent"]}')
    lines.append("")
    return "\n".join(lines)


def tail_file(path: Path, lines: int) -> str:
    if not path.exists():
        return ""
    try:
        with path.open("rb") as file:
            file.seek(0, os.SEEK_END)
            end = file.tell()
            block_size = 8192
            blocks = []
            newline_count = 0
            position = end
            while position > 0 and newline_count <= lines:
                read_size = min(block_size, position)
                position -= read_size
                file.seek(position)
                block = file.read(read_size)
                blocks.append(block)
                newline_count += block.count(b"\n")
        data = b"".join(reversed(blocks))
    except OSError as exc:
        return f"unable to read log: {exc}"
    chunks = data.splitlines()[-lines:]
    return b"\n".join(chunks).decode("utf-8", errors="replace")


def logs_payload(query: dict[str, list[str]]) -> dict[str, Any]:
    service = query.get("service", ["supervisord"])[0]
    max_lines = parse_int(env("OPS_LOG_LINES_MAX"), 1000, minimum=1, maximum=10000)
    requested_lines = parse_int(query.get("lines", ["200"])[0], 200)
    lines = min(max(requested_lines, 1), max_lines)
    filename = SERVICE_LOGS.get(service)
    if not filename:
        return {"ok": False, "error": "unknown service", "allowed_services": sorted(SERVICE_LOGS)}
    path = LOG_DIR / filename
    return {
        "ok": path.exists(),
        "service": service,
        "path": str(path),
        "lines": lines,
        "content": tail_file(path, lines),
    }


def matched_error_pattern(line: str) -> str | None:
    if any(pattern in line for pattern in IGNORED_ERROR_PATTERNS):
        return None
    for pattern in ERROR_PATTERNS:
        if pattern in line:
            return pattern
    return None


def errors_payload(query: dict[str, list[str]]) -> dict[str, Any]:
    max_lines = parse_int(env("OPS_LOG_LINES_MAX"), 1000, minimum=1, maximum=10000)
    requested_lines = parse_int(query.get("lines", ["300"])[0], 300, minimum=1, maximum=max_lines)
    requested_lines = min(requested_lines, 1000)
    match_limit = parse_int(query.get("limit", ["200"])[0], 200, minimum=1, maximum=500)
    per_service_limit = parse_int(query.get("per_service_limit", ["50"])[0], 50, minimum=1, maximum=200)
    matches: list[dict[str, Any]] = []
    groups: dict[str, dict[str, Any]] = {}
    total_matches = 0

    for service, filename in SERVICE_LOGS.items():
        path = LOG_DIR / filename
        if not path.exists():
            continue
        for line in tail_file(path, requested_lines).splitlines():
            pattern = matched_error_pattern(line)
            if not pattern:
                continue
            total_matches += 1
            entry = {
                "service": service,
                "pattern": pattern,
                "line": truncate_text(line, 1000),
            }
            matches.append(entry)
            group = groups.setdefault(
                service,
                {
                    "service": service,
                    "count": 0,
                    "pattern_counts": {},
                    "matches": [],
                },
            )
            group["count"] += 1
            group["pattern_counts"][pattern] = group["pattern_counts"].get(pattern, 0) + 1
            group["matches"].append({"pattern": pattern, "line": truncate_text(line, 1000)})

    for group in groups.values():
        group["matches"] = group["matches"][-per_service_limit:]

    matches = matches[-match_limit:]
    grouped = sorted(groups.values(), key=lambda item: item["service"])
    return {
        "ok": total_matches == 0,
        "line_limit": requested_lines,
        "match_limit": match_limit,
        "per_service_limit": per_service_limit,
        "count": total_matches,
        "returned": len(matches),
        "patterns": ERROR_PATTERNS,
        "ignored_patterns": IGNORED_ERROR_PATTERNS,
        "groups": grouped,
        "matches": matches,
    }


def html_index(token: str) -> str:
    service_options = "\n".join(
        f'<option value="{html.escape(service)}">{html.escape(service)}</option>' for service in sorted(SERVICE_LOGS)
    )
    template = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>Dify OPS</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --line: #d9dee7;
      --text: #17202a;
      --muted: #657386;
      --ok: #177245;
      --warn: #9a5b00;
      --bad: #b42318;
      --fill: #2f6fed;
      --soft: #eef3ff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }
    main { max-width: 1240px; margin: 0 auto; padding: 24px; }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 18px;
    }
    h1 { margin: 0; font-size: 28px; letter-spacing: 0; }
    h2 { margin: 0 0 12px; font-size: 16px; letter-spacing: 0; }
    a { color: var(--fill); text-decoration: none; }
    .toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
    button, select, input {
      min-height: 36px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--text);
      border-radius: 6px;
      padding: 0 10px;
      font: inherit;
    }
    button { cursor: pointer; }
    .switch { display: inline-flex; align-items: center; gap: 8px; color: var(--muted); }
    .switch input { min-height: auto; }
    .status-pill {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      border-radius: 999px;
      padding: 0 10px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--muted);
      font-size: 13px;
    }
    .status-pill.ok { color: var(--ok); border-color: #a7d7bd; background: #eefaf3; }
    .status-pill.bad { color: var(--bad); border-color: #f1b5ae; background: #fff1ef; }
    .grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 14px; }
    .panel {
      grid-column: span 6;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      min-width: 0;
    }
    .panel.wide { grid-column: span 12; }
    .summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
    .stat {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      background: #fbfcfe;
      min-width: 0;
    }
    .label { color: var(--muted); font-size: 12px; }
    .value { margin-top: 4px; font-size: 20px; font-weight: 650; overflow-wrap: anywhere; }
    .resource { margin: 10px 0; }
    .bar {
      height: 10px;
      border-radius: 999px;
      background: #e8edf5;
      overflow: hidden;
      margin-top: 5px;
    }
    .bar > span { display: block; height: 100%; background: var(--fill); width: 0%; }
    .bar > span.warn { background: var(--warn); }
    .bar > span.bad { background: var(--bad); }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { padding: 8px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
    th { color: var(--muted); font-weight: 600; }
    .ok-text { color: var(--ok); }
    .bad-text { color: var(--bad); }
    .muted { color: var(--muted); }
    .error-group { border-top: 1px solid var(--line); padding: 10px 0; }
    .error-group:first-child { border-top: 0; padding-top: 0; }
    .error-line {
      margin: 6px 0 0;
      padding: 8px;
      border-radius: 6px;
      background: #fff7ed;
      color: #5f3100;
      overflow-wrap: anywhere;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
    }
    .log-controls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    pre {
      min-height: 240px;
      max-height: 520px;
      overflow: auto;
      margin: 12px 0 0;
      padding: 12px;
      border-radius: 6px;
      background: #111827;
      color: #e5e7eb;
      font-size: 12px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    @media (max-width: 860px) {
      main { padding: 16px; }
      header { align-items: flex-start; flex-direction: column; }
      .panel, .panel.wide { grid-column: span 12; }
      .summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 520px) {
      .summary { grid-template-columns: 1fr; }
      .toolbar, .log-controls { width: 100%; }
      button, select, input { width: 100%; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Dify OPS</h1>
        <div class="muted" id="versionLine">Loading runtime summary...</div>
      </div>
      <div class="toolbar">
        <span class="status-pill" id="overall">Loading</span>
        <label class="switch"><input type="checkbox" id="autoRefresh" checked> Auto refresh</label>
        <button id="refreshButton" type="button">Refresh</button>
      </div>
    </header>

    <section class="grid">
      <section class="panel wide">
        <h2>Overview</h2>
        <div class="summary" id="summary"></div>
      </section>

      <section class="panel">
        <h2>Resources</h2>
        <div id="resources"></div>
      </section>

      <section class="panel">
        <h2>Health Checks</h2>
        <div id="checks"></div>
      </section>

      <section class="panel wide">
        <h2>Services</h2>
        <div id="services"></div>
      </section>

      <section class="panel wide">
        <h2>Recent Errors</h2>
        <div id="errors"></div>
      </section>

      <section class="panel wide">
        <h2>Logs</h2>
        <div class="log-controls">
          <select id="logService">__SERVICE_OPTIONS__</select>
          <input id="logLines" type="number" min="1" max="1000" value="120">
          <button id="loadLog" type="button">Load</button>
          <a id="metricsLink" href="metrics" target="_blank" rel="noreferrer">Metrics</a>
        </div>
        <pre id="logOutput">Select a service log.</pre>
      </section>
    </section>
  </main>
  <script>
    const TOKEN = __TOKEN_JSON__;
    const HEADERS = {"X-Ops-Token": TOKEN};
    let timer = null;

    const byId = (id) => document.getElementById(id);
    const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    }[char]));

    function fmtBytes(value) {
      if (!Number.isFinite(value)) return "n/a";
      const units = ["B", "KiB", "MiB", "GiB", "TiB"];
      let size = value;
      let index = 0;
      while (size >= 1024 && index < units.length - 1) {
        size /= 1024;
        index += 1;
      }
      return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
    }

    function fmtDuration(seconds) {
      if (!Number.isFinite(seconds)) return "n/a";
      const days = Math.floor(seconds / 86400);
      const hours = Math.floor((seconds % 86400) / 3600);
      const minutes = Math.floor((seconds % 3600) / 60);
      if (days) return `${days}d ${hours}h`;
      if (hours) return `${hours}h ${minutes}m`;
      return `${minutes}m`;
    }

    async function getJson(path) {
      const response = await fetch(path, {headers: HEADERS, cache: "no-store"});
      const text = await response.text();
      try {
        const payload = JSON.parse(text);
        payload.http_status = response.status;
        return payload;
      } catch {
        return {ok: false, http_status: response.status, error: text || response.statusText};
      }
    }

    function stat(label, value, className = "") {
      return `<div class="stat"><div class="label">${esc(label)}</div><div class="value ${className}">${esc(value)}</div></div>`;
    }

    function resourceBar(label, percent, detail) {
      const safe = Math.max(0, Math.min(100, Number(percent || 0)));
      const tone = safe >= 90 ? "bad" : safe >= 75 ? "warn" : "";
      return `<div class="resource">
        <div><strong>${esc(label)}</strong> <span class="muted">${esc(detail)}</span></div>
        <div class="bar"><span class="${tone}" style="width:${safe}%"></span></div>
      </div>`;
    }

    function renderSummary(health, system, version) {
      const checks = health.checks || [];
      const failed = checks.filter((item) => !item.ok).length;
      byId("summary").innerHTML = [
        stat("Overall", health.ok ? "Healthy" : "Unhealthy", health.ok ? "ok-text" : "bad-text"),
        stat("Checks", `${checks.length - failed}/${checks.length} passing`),
        stat("Processes", system.process_count ?? "n/a"),
        stat("Uptime", fmtDuration(system.uptime_seconds)),
      ].join("");
      const overall = byId("overall");
      overall.textContent = health.ok ? "Healthy" : "Unhealthy";
      overall.className = `status-pill ${health.ok ? "ok" : "bad"}`;
      byId("versionLine").textContent = [
        version.version?.dify_version ? `Dify ${version.version.dify_version}` : "",
        version.version?.deploy_env || "",
        version.version?.public_url || version.version?.space_host || "",
      ].filter(Boolean).join(" · ") || "Runtime summary";
    }

    function renderResources(system) {
      const cpu = system.cpu || {};
      const memory = system.memory || {};
      const disk = system.disk || {};
      const rows = [];
      if (cpu.ok) rows.push(resourceBar("CPU load", Math.min(100, (cpu.load1 / Math.max(cpu.cpu_count || 1, 1)) * 100), `1m ${cpu.load1}, 5m ${cpu.load5}, 15m ${cpu.load15}`));
      if (memory.ok) rows.push(resourceBar("Memory", memory.used_percent, `${fmtBytes(memory.used_bytes)} / ${fmtBytes(memory.total_bytes)}`));
      Object.values(disk).forEach((usage) => {
        if (usage.ok) rows.push(resourceBar(`Disk ${usage.path}`, usage.used_percent, `${fmtBytes(usage.used_bytes)} / ${fmtBytes(usage.total_bytes)}`));
      });
      byId("resources").innerHTML = rows.join("") || '<div class="muted">No resource data.</div>';
    }

    function renderChecks(health) {
      const checks = health.checks || [];
      if (!checks.length) {
        byId("checks").innerHTML = `<div class="bad-text">${esc(health.error || "No checks configured")}</div>`;
        return;
      }
      byId("checks").innerHTML = `<table><thead><tr><th>Name</th><th>Status</th><th>Latency</th></tr></thead><tbody>${
        checks.map((item) => `<tr><td>${esc(item.name)}</td><td class="${item.ok ? "ok-text" : "bad-text"}">${item.ok ? "OK" : "FAIL"}</td><td>${esc(item.duration_ms ?? "")} ms</td></tr>`).join("")
      }</tbody></table>`;
    }

    function renderServices(status) {
      const programs = status.supervisor?.programs || [];
      if (!programs.length) {
        byId("services").innerHTML = `<div class="bad-text">${esc(status.supervisor?.stderr || "No supervisor status")}</div>`;
        return;
      }
      byId("services").innerHTML = `<table><thead><tr><th>Service</th><th>State</th><th>Description</th></tr></thead><tbody>${
        programs.map((item) => `<tr><td>${esc(item.name)}</td><td class="${item.ok ? "ok-text" : "bad-text"}">${esc(item.state)}</td><td>${esc(item.description)}</td></tr>`).join("")
      }</tbody></table>`;
    }

    function renderErrors(errors) {
      if (errors.ok) {
        byId("errors").innerHTML = '<div class="ok-text">No matched recent errors.</div>';
        return;
      }
      const groups = errors.groups || [];
      byId("errors").innerHTML = groups.map((group) => {
        const patterns = Object.entries(group.pattern_counts || {}).map(([key, value]) => `${esc(key)}: ${value}`).join(", ");
        const lines = (group.matches || []).map((item) => `<div class="error-line"><strong>${esc(item.pattern)}</strong> ${esc(item.line)}</div>`).join("");
        return `<div class="error-group"><strong>${esc(group.service)}</strong> <span class="muted">${group.count} matches · ${patterns}</span>${lines}</div>`;
      }).join("") || '<div class="muted">No grouped error data.</div>';
    }

    async function loadLog() {
      const service = byId("logService").value;
      const lines = byId("logLines").value || "120";
      const payload = await getJson(`logs?service=${encodeURIComponent(service)}&lines=${encodeURIComponent(lines)}`);
      byId("logOutput").textContent = payload.content || payload.error || "No log content.";
    }

    async function refreshAll() {
      const [health, status, system, errors, version] = await Promise.all([
        getJson("health"),
        getJson("status"),
        getJson("system"),
        getJson("errors?lines=300&limit=100&per_service_limit=8"),
        getJson("version"),
      ]);
      renderSummary(health, system.system || system, version);
      renderResources(system.system || system);
      renderChecks(health);
      renderServices(status);
      renderErrors(errors);
    }

    function configureTimer() {
      if (timer) clearInterval(timer);
      timer = null;
      if (byId("autoRefresh").checked) timer = setInterval(refreshAll, 10000);
    }

    byId("refreshButton").addEventListener("click", refreshAll);
    byId("autoRefresh").addEventListener("change", configureTimer);
    byId("loadLog").addEventListener("click", loadLog);
    byId("metricsLink").href = `metrics?token=${encodeURIComponent(TOKEN)}`;
    refreshAll().catch((error) => {
      byId("overall").textContent = "Error";
      byId("overall").className = "status-pill bad";
      byId("summary").innerHTML = stat("Dashboard", error.message || String(error), "bad-text");
    });
    configureTimer();
  </script>
</body>
</html>
"""
    return template.replace("__TOKEN_JSON__", json.dumps(token)).replace("__SERVICE_OPTIONS__", service_options)


class Handler(BaseHTTPRequestHandler):
    server_version = "dify-aio-ops/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        message = fmt % args
        sanitized_path = urllib.parse.urlparse(self.path).path
        message = message.replace(self.path, sanitized_path)
        sys.stdout.write("%s - %s\n" % (self.address_string(), message))
        sys.stdout.flush()

    def log_request(self, code: str | int = "-", size: str | int = "-") -> None:
        path = urllib.parse.urlparse(self.path).path
        sys.stdout.write(
            '%s - "%s %s %s" %s %s\n'
            % (self.address_string(), self.command, path, self.request_version, code, size)
        )
        sys.stdout.flush()

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, body: str, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def parsed(self) -> tuple[str, dict[str, list[str]]]:
        parsed = urllib.parse.urlparse(self.path)
        return parsed.path, urllib.parse.parse_qs(parsed.query)

    def is_authorized(self, query: dict[str, list[str]]) -> bool:
        expected = env("OPS_TOKEN")
        if not expected:
            return False
        auth = self.headers.get("Authorization", "")
        provided = ""
        if auth.startswith("Bearer "):
            provided = auth.removeprefix("Bearer ").strip()
        provided = provided or self.headers.get("X-Ops-Token", "").strip()
        provided = provided or query.get("token", [""])[0]
        return hmac.compare_digest(provided, expected)

    def require_auth(self, query: dict[str, list[str]]) -> bool:
        if self.is_authorized(query):
            return True
        self.send_json(
            {
                "ok": False,
                "error": "unauthorized",
                "hint": "Send X-Ops-Token, Authorization: Bearer <token>, or ?token=<token>.",
            },
            status=401,
        )
        return False

    def do_GET(self) -> None:
        path, query = self.parsed()
        if path in {"/healthz", "/readyz"}:
            payload = health_payload(public=True)
            self.send_json(payload, status=200 if payload["ok"] else 503)
            return

        if not self.require_auth(query):
            return

        if path in {"/", ""}:
            self.send_text(html_index(env("OPS_TOKEN")), content_type="text/html; charset=utf-8")
        elif path == "/health":
            payload = health_payload(public=False)
            self.send_json(payload, status=200 if payload["ok"] else 503)
        elif path == "/status":
            self.send_json({"ok": True, "supervisor": supervisor_status(), "health": health_payload(public=True)})
        elif path == "/system":
            self.send_json({"ok": True, "system": system_payload()})
        elif path == "/config":
            self.send_json({"ok": True, "config": config_payload()})
        elif path == "/version":
            self.send_json({"ok": True, "version": version_payload()})
        elif path == "/metrics":
            self.send_text(metrics_payload(), content_type="text/plain; version=0.0.4; charset=utf-8")
        elif path == "/logs":
            payload = logs_payload(query)
            self.send_json(payload, status=200 if payload["ok"] else 404)
        elif path == "/errors":
            self.send_json(errors_payload(query))
        else:
            self.send_json({"ok": False, "error": "not found"}, status=404)


def main() -> None:
    host = env("OPS_HOST", "127.0.0.1")
    port = parse_int(env("OPS_PORT"), 8081, minimum=1, maximum=65535)
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"[dify-aio-ops] listening on http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
