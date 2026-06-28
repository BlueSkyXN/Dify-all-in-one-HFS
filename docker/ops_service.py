#!/usr/bin/env python3
"""Small read-only operations service for the Dify all-in-one container."""

from __future__ import annotations

import html
import hmac
import http.client
import hashlib
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
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock
from typing import Any
import xmlrpc.client


STARTED_AT = time.time()
LOG_DIR = Path(os.environ.get("OPS_LOG_DIR", "/data/logs"))
SUPERVISOR_CONFIG = "/etc/supervisor/conf.d/supervisord.conf"
SUPERVISOR_SOCKET = "/data/run/supervisor.sock"
MAX_CHECKS = 32
DEMO_OPS_TOKEN = "dify_ops_demo_token"
OPS_SESSION_COOKIE = "dify_ops_session"
OPS_CACHE: dict[str, tuple[float, Any]] = {}
OPS_CACHE_LOCK = RLock()

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
    "DIFY_AIO_BUILD_DIFY_VERSION",
    "DIFY_AIO_BUILD_UV_VERSION",
    "DIFY_AIO_BUILD_BASE_IMAGE_REF",
    "DIFY_AIO_BUILD_DIFY_API_IMAGE_REF",
    "DIFY_AIO_BUILD_DIFY_WEB_IMAGE_REF",
    "DIFY_AIO_BUILD_PLUGIN_DAEMON_IMAGE_REF",
    "DIFY_AIO_BUILD_SANDBOX_IMAGE_REF",
    "DIFY_AIO_BUILD_DIFY_API_IMAGE",
    "DIFY_AIO_BUILD_DIFY_WEB_IMAGE",
    "DIFY_AIO_BUILD_PLUGIN_DAEMON_IMAGE",
    "DIFY_AIO_BUILD_SANDBOX_IMAGE",
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
    "POSTGRES_BACKUP_INITIAL_DELAY_SECONDS",
    "POSTGRES_BACKUP_RETAIN_COUNT",
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
    "REDIS_DB",
    "REDIS_KEY_PREFIX",
    "PLUGIN_DAEMON_URL",
    "PLUGIN_MAX_REQUEST_TIMEOUT",
    "MAX_REQUEST_TIMEOUT",
    "CODE_EXECUTION_ENDPOINT",
    "OPS_PORT",
    "OPS_CACHE_TTL_SECONDS",
    "OPS_SESSION_TTL_SECONDS",
    "OPS_COOKIE_SECURE",
    "OPS_HTTP_TIMEOUT_SECONDS",
    "ALLOW_DEMO_OPS_TOKEN",
    "OPS_DEFAULT_CHECKS_ENABLED",
    "OPS_LOG_DIR",
    "OPS_LOG_TAIL_MAX_BYTES",
    "ADMIN_ENABLED",
    "ADMIN_HOST",
    "ADMIN_PORT",
    "ADMIN_SESSION_TTL_SECONDS",
    "ADMIN_COOKIE_SECURE",
    "ADMIN_HTTP_TIMEOUT_SECONDS",
    "ADMIN_LOGIN_RATE_LIMIT_WINDOW_SECONDS",
    "ADMIN_LOGIN_RATE_LIMIT_BLOCK_SECONDS",
    "ADMIN_LOGIN_RATE_LIMIT_MAX_PER_IP",
    "ADMIN_LOGIN_RATE_LIMIT_MAX_GLOBAL",
    "ADMIN_AUDIT_LOG",
    "ADMIN_FILES_ENABLED",
    "ADMIN_FILES_ROOT",
    "ADMIN_FILES_WRITE_ENABLED",
    "ADMIN_FILES_DESTRUCTIVE_ENABLED",
    "ADMIN_FILES_MAX_UPLOAD_BYTES",
]

SANDBOX_REQUIREMENTS_PATH = Path("/dependencies/python-requirements.txt")

SECRET_KEYS = [
    "SECRET_KEY",
    "PLUGIN_DAEMON_KEY",
    "PLUGIN_DIFY_INNER_API_KEY",
    "INNER_API_KEY_FOR_PLUGIN",
    "CODE_EXECUTION_API_KEY",
    "SANDBOX_API_KEY",
    "OPS_TOKEN",
    "ADMIN_TOKEN",
    "ADMIN_CSRF_KEY",
]

PROCESS_ENV_ALLOWED_SERVICES = {
    "plugin-daemon",
    "dify-api",
    "dify-worker",
    "dify-beat",
    "sandbox",
    "ops-service",
    "admin-service",
}

PROCESS_ENV_SAFE_KEYS = [
    "INSTALL_METHOD",
    "MAX_REQUEST_TIMEOUT",
    "PLUGIN_MAX_REQUEST_TIMEOUT",
    "PLUGIN_MAX_EXECUTION_TIMEOUT",
    "PLUGIN_PYTHON_ENV_INIT_TIMEOUT",
    "PLUGIN_STORAGE_LOCAL_ROOT",
    "PLUGIN_WORKING_PATH",
    "PLUGIN_INSTALLED_PATH",
    "PLUGIN_PACKAGE_CACHE_PATH",
    "PLUGIN_IGNORE_UV_LOCK",
    "PYTHON_ENV_INIT_TIMEOUT",
    "UV_CACHE_DIR",
    "VIRTUAL_ENV",
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
    if resolve_log_path(str(path)) is None:
        return None
    return str(path)


def resolve_log_path(filename: str) -> Path | None:
    root = LOG_DIR.resolve(strict=False)
    target = (root / filename).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError:
        return None
    return target


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


def ops_session_ttl_seconds() -> int:
    return parse_int(env("OPS_SESSION_TTL_SECONDS"), 3600, minimum=60, maximum=86400)


def ops_cache_ttl_seconds() -> float:
    return parse_float(env("OPS_CACHE_TTL_SECONDS", "5"), 5.0, minimum=0.0, maximum=300.0)


def ops_log_tail_max_bytes() -> int:
    return parse_int(env("OPS_LOG_TAIL_MAX_BYTES"), 1_048_576, minimum=1, maximum=100 * 1024 * 1024)


def ops_lock_reason() -> str:
    token = env("OPS_TOKEN")
    if not token:
        return "OPS_TOKEN is not set"
    if token == DEMO_OPS_TOKEN and not parse_bool(env("ALLOW_DEMO_OPS_TOKEN", "false"), default=False):
        return "default OPS_TOKEN is locked; set OPS_TOKEN to a strong value or explicitly set ALLOW_DEMO_OPS_TOKEN=true for local demo use"
    return ""


def sign_ops_message(*parts: str) -> str:
    token = env("OPS_TOKEN")
    payload = "|".join(parts).encode("utf-8")
    return hmac.new(token.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def make_ops_session() -> tuple[str, int]:
    expires_at = int(time.time()) + ops_session_ttl_seconds()
    nonce = hashlib.sha256(f"{time.time()}:{os.urandom(16).hex()}".encode("utf-8")).hexdigest()[:32]
    signature = sign_ops_message("ops-session", str(expires_at), nonce)
    return f"{expires_at}.{nonce}.{signature}", expires_at


def parse_ops_session(cookie_value: str) -> bool:
    try:
        expires_raw, nonce, signature = cookie_value.split(".", 2)
        expires_at = int(expires_raw)
    except (ValueError, AttributeError):
        return False
    if expires_at < int(time.time()) or not nonce or not signature or not env("OPS_TOKEN"):
        return False
    expected = sign_ops_message("ops-session", str(expires_at), nonce)
    return hmac.compare_digest(signature, expected)


def cached_payload(key: str, builder: Any) -> Any:
    ttl = ops_cache_ttl_seconds()
    if ttl <= 0:
        return builder()
    with OPS_CACHE_LOCK:
        now = time.time()
        cached = OPS_CACHE.get(key)
        if cached and cached[0] > now:
            return cached[1]
        payload = builder()
        OPS_CACHE[key] = (time.time() + ttl, payload)
        return payload


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


def file_sha256(path: Path, max_bytes: int = 1_000_000) -> str | None:
    try:
        with path.open("rb") as file:
            digest = hashlib.sha256()
            read_bytes = 0
            while True:
                chunk = file.read(65536)
                if not chunk:
                    break
                read_bytes += len(chunk)
                if read_bytes > max_bytes:
                    return None
                digest.update(chunk)
            return digest.hexdigest()
    except OSError:
        return None


def read_small_text(path: Path, max_bytes: int = 4096) -> str:
    try:
        if not path.exists() or not path.is_file() or path.stat().st_size > max_bytes:
            return ""
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def requirements_summary(path: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
    }
    if not path.exists():
        return summary
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        summary["error"] = str(exc)
        return summary
    packages = [
        line.strip()
        for line in lines
        if line.strip() and not line.strip().startswith("#") and not line.strip().startswith("-")
    ]
    summary.update(
        {
            "line_count": len(lines),
            "package_count": len(packages),
            "sha256": file_sha256(path),
            "packages": packages[:200],
        }
    )
    return summary


def run_cmd(
    args: list[str],
    timeout: float = 2.0,
    extra_env: dict[str, str] | None = None,
    output_limit: int = 2048,
) -> dict[str, Any]:
    started = time.time()
    try:
        command_env = None
        if extra_env:
            command_env = os.environ.copy()
            command_env.update(extra_env)
        completed = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=command_env,
        )
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": truncate_text(completed.stdout.strip(), output_limit),
            "stderr": truncate_text(completed.stderr.strip(), output_limit),
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
            "stdout": truncate_text((exc.stdout or "").strip(), output_limit),
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


class UnixSocketHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: float = 3.0) -> None:
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.socket_path)
        self.sock = sock


class UnixSocketTransport(xmlrpc.client.Transport):
    def __init__(self, socket_path: str, timeout: float = 3.0) -> None:
        super().__init__()
        self.socket_path = socket_path
        self.timeout = timeout

    def make_connection(self, host: str) -> UnixSocketHTTPConnection:
        return UnixSocketHTTPConnection(self.socket_path, timeout=self.timeout)


def supervisor_status() -> dict[str, Any]:
    started = time.time()
    try:
        proxy = xmlrpc.client.ServerProxy(
            "http://localhost/RPC2",
            transport=UnixSocketTransport(SUPERVISOR_SOCKET, timeout=3.0),
            allow_none=True,
        )
        info = proxy.supervisor.getAllProcessInfo()
    except Exception as exc:
        return {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": truncate_text(str(exc)),
            "duration_ms": round((time.time() - started) * 1000),
            "programs": [],
            "socket": SUPERVISOR_SOCKET,
        }

    programs = []
    for item in info:
        state = str(item.get("statename", "UNKNOWN"))
        name = str(item.get("name", ""))
        group = str(item.get("group", ""))
        programs.append(
            {
                "name": f"{group}:{name}" if group and group != name else name,
                "state": state,
                "description": str(item.get("description", "")),
                "ok": state == "RUNNING",
            }
        )
    return {
        "ok": bool(programs) and all(program["ok"] for program in programs),
        "returncode": 0,
        "stdout": "",
        "stderr": "",
        "duration_ms": round((time.time() - started) * 1000),
        "programs": programs,
        "socket": SUPERVISOR_SOCKET,
    }


def supervisor_payload() -> dict[str, Any]:
    return cached_payload("supervisor", supervisor_status)


def redis_check() -> dict[str, Any]:
    args = ["redis-cli", "-h", env("REDIS_HOST", "127.0.0.1"), "-p", env("REDIS_PORT", "6379")]
    extra_env = None
    password = env("REDIS_PASSWORD")
    if password:
        extra_env = {"REDISCLI_AUTH": password}
    args.append("ping")
    result = run_cmd(args, timeout=2.0, extra_env=extra_env)
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
    payload = dict(cached_payload("health:checks", _health_checks_payload))
    if not public:
        payload["supervisor"] = supervisor_payload()
        payload["version"] = version_payload()
    return payload


def _health_checks_payload() -> dict[str, Any]:
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
    checks = collect_checks(checks_to_run)

    payload: dict[str, Any] = {
        "ok": bool(checks) and all(check["ok"] for check in checks),
        "uptime_seconds": int(time.time() - STARTED_AT),
        "checks": checks,
    }
    if not checks:
        payload["error"] = "no checks configured"
    return payload


def status_payload() -> dict[str, Any]:
    return cached_payload("status", _status_payload)


def _status_payload() -> dict[str, Any]:
    return {"ok": True, "supervisor": supervisor_payload(), "health": health_payload(public=True)}


def version_payload() -> dict[str, Any]:
    base_image_ref = env("DIFY_AIO_BUILD_BASE_IMAGE_REF")
    dify_api_image_ref = env("DIFY_AIO_BUILD_DIFY_API_IMAGE_REF") or env("DIFY_AIO_BUILD_DIFY_API_IMAGE")
    dify_web_image_ref = env("DIFY_AIO_BUILD_DIFY_WEB_IMAGE_REF") or env("DIFY_AIO_BUILD_DIFY_WEB_IMAGE")
    plugin_daemon_image_ref = env("DIFY_AIO_BUILD_PLUGIN_DAEMON_IMAGE_REF") or env("DIFY_AIO_BUILD_PLUGIN_DAEMON_IMAGE")
    sandbox_image_ref = env("DIFY_AIO_BUILD_SANDBOX_IMAGE_REF") or env("DIFY_AIO_BUILD_SANDBOX_IMAGE")
    return {
        "service": "dify-all-in-one-ops",
        "dify_version": env("DIFY_VERSION"),
        "deploy_env": env("DEPLOY_ENV"),
        "public_url": env("PUBLIC_URL"),
        "space_host": env("SPACE_HOST"),
        "space_id": env("SPACE_ID"),
        "python": sys.version.split()[0],
        "build": {
            "dify_version": env("DIFY_AIO_BUILD_DIFY_VERSION"),
            "uv_version": env("DIFY_AIO_BUILD_UV_VERSION"),
            "base_image_ref": base_image_ref,
            "dify_api_image_ref": dify_api_image_ref,
            "dify_web_image_ref": dify_web_image_ref,
            "plugin_daemon_image_ref": plugin_daemon_image_ref,
            "sandbox_image_ref": sandbox_image_ref,
            "dify_api_image": dify_api_image_ref,
            "dify_web_image": dify_web_image_ref,
            "plugin_daemon_image": plugin_daemon_image_ref,
            "sandbox_image": sandbox_image_ref,
        },
        "sandbox": {
            "python_path": env("SANDBOX_PYTHON_PATH"),
            "nodejs_path": env("SANDBOX_NODEJS_PATH"),
            "enable_network": env("SANDBOX_ENABLE_NETWORK"),
            "python_deps_update_interval": env("SANDBOX_PYTHON_DEPS_UPDATE_INTERVAL"),
            "requirements": requirements_summary(SANDBOX_REQUIREMENTS_PATH),
        },
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
        },
    }


def parse_environ_bytes(data: bytes) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in data.split(b"\0"):
        if not item or b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        if not key:
            continue
        values[key.decode("utf-8", errors="replace")] = value.decode("utf-8", errors="replace")
    return values


def process_env_safe_summary(values: dict[str, str]) -> dict[str, Any]:
    return {
        "safe_values": {key: values[key] for key in PROCESS_ENV_SAFE_KEYS if key in values},
        "safe_key_presence": {key: key in values for key in PROCESS_ENV_SAFE_KEYS},
        "secret_presence": {key: bool(values.get(key)) for key in SECRET_KEYS},
    }


def read_pid_environ(pid: int) -> dict[str, Any]:
    if pid <= 0:
        return {"ok": False, "error": "process is not running"}
    path = Path("/proc") / str(pid) / "environ"
    try:
        values = parse_environ_bytes(path.read_bytes())
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "pid": pid, **process_env_safe_summary(values)}


def read_pid_comm(pid: int) -> str:
    if pid <= 0:
        return ""
    try:
        return (Path("/proc") / str(pid) / "comm").read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def child_pids(pid: int, proc_root: Path = Path("/proc")) -> list[int]:
    if pid <= 0:
        return []
    children_path = proc_root / str(pid) / "task" / str(pid) / "children"
    try:
        raw = children_path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return []
    children: list[int] = []
    for item in raw.split():
        try:
            child = int(item)
        except ValueError:
            continue
        if child > 0:
            children.append(child)
    return children


def descendant_pids(pid: int, limit: int = 20, proc_root: Path = Path("/proc")) -> list[int]:
    seen: set[int] = set()
    queue = child_pids(pid, proc_root)
    descendants: list[int] = []
    while queue and len(descendants) < limit:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        descendants.append(current)
        queue.extend(child_pids(current, proc_root))
    return descendants


def supervisor_process_infos() -> tuple[list[dict[str, Any]], str | None]:
    try:
        proxy = xmlrpc.client.ServerProxy(
            "http://localhost/RPC2",
            transport=UnixSocketTransport(SUPERVISOR_SOCKET, timeout=3.0),
            allow_none=True,
        )
        return list(proxy.supervisor.getAllProcessInfo()), None
    except Exception as exc:
        return [], str(exc)


def process_env_payload(query: dict[str, list[str]]) -> dict[str, Any]:
    service = query.get("service", ["plugin-daemon"])[0]
    if service not in PROCESS_ENV_ALLOWED_SERVICES:
        return {"ok": False, "error": "unknown service", "allowed_services": sorted(PROCESS_ENV_ALLOWED_SERVICES)}

    info, error = supervisor_process_infos()
    if error:
        return {"ok": False, "service": service, "error": error}

    program = None
    for item in info:
        name = str(item.get("name", ""))
        group = str(item.get("group", ""))
        full_name = f"{group}:{name}" if group and group != name else name
        if service in {name, full_name}:
            program = item
            break
    if program is None:
        return {"ok": False, "service": service, "error": "service not found"}

    pid = parse_int(str(program.get("pid", "0")), 0, minimum=0)
    process = read_pid_environ(pid)
    process["comm"] = read_pid_comm(pid)
    include_children = parse_bool(query.get("children", ["true"])[0], default=True)
    children: list[dict[str, Any]] = []
    if include_children:
        for child in descendant_pids(pid):
            child_summary = read_pid_environ(child)
            child_summary["comm"] = read_pid_comm(child)
            children.append(child_summary)

    return {
        "ok": bool(process.get("ok")),
        "service": service,
        "state": str(program.get("statename", "")),
        "pid": pid,
        "process": process,
        "children": children,
        "notes": [
            "Only fixed safe keys are returned from /proc/<pid>/environ.",
            "Secret values are never returned; secret_presence only reports whether a secret-like key is set.",
        ],
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


def path_summary(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "is_symlink": path.is_symlink(),
    }
    try:
        if path.is_symlink():
            payload["link_target"] = os.readlink(path)
        if path.exists():
            resolved = path.resolve(strict=False)
            stat = path.stat()
            payload.update(
                {
                    "real_path": str(resolved),
                    "is_dir": path.is_dir(),
                    "is_file": path.is_file(),
                    "mode": oct(stat.st_mode & 0o777),
                    "uid": stat.st_uid,
                    "gid": stat.st_gid,
                    "writable": os.access(path, os.W_OK),
                    "mountpoint": os.path.ismount(path) or os.path.ismount(resolved),
                }
            )
    except OSError as exc:
        payload["error"] = str(exc)
    return payload


def resolve_plugin_storage_path(root: Path, configured: str) -> Path:
    path = Path(configured)
    if path.is_absolute():
        return path
    return root / path


def plugin_storage_paths() -> dict[str, Path]:
    root = Path(env("PLUGIN_STORAGE_LOCAL_ROOT", "/data/plugin_daemon"))
    return {
        "storage_root": root,
        "installed": resolve_plugin_storage_path(root, env("PLUGIN_INSTALLED_PATH", "plugin")),
        "package_cache": resolve_plugin_storage_path(root, env("PLUGIN_PACKAGE_CACHE_PATH", "plugin_packages")),
        "media_cache": resolve_plugin_storage_path(root, env("PLUGIN_MEDIA_CACHE_PATH", "assets")),
        "working": Path(env("PLUGIN_WORKING_PATH", "/data/plugin_daemon/cwd")),
    }


def plugin_storage_layout_issues(persist_active: str, paths: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    if persist_active.strip() != "bucket":
        return []

    issues = []
    storage_root = paths.get("plugin_storage_root", {})
    installed = paths.get("plugin_installed", {})
    package_cache = paths.get("plugin_package_cache", {})
    storage_path = storage_root.get("path", "")

    if storage_path == "/data/plugin_daemon" or storage_path.startswith("/data/plugin_daemon/"):
        issues.append(
            {
                "code": "plugin_storage_root_uses_data_symlink_view",
                "path": storage_path,
                "message": (
                    "bucket-lite should expose PLUGIN_STORAGE_LOCAL_ROOT as the real /persist/plugin_daemon "
                    "path so plugin-daemon can enumerate installed plugins after restart"
                ),
            }
        )

    for name, summary in [("plugin_installed", installed), ("plugin_package_cache", package_cache)]:
        if summary.get("is_symlink"):
            issues.append(
                {
                    "code": f"{name}_is_symlink_root",
                    "path": summary.get("path", ""),
                    "real_path": summary.get("real_path", ""),
                    "message": (
                        "bucket-lite plugin paths should be direct /persist directories in the plugin-daemon "
                        "environment; a symlink root can hide installed plugins from Go filepath.WalkDir"
                    ),
                }
            )

    return issues


def directory_inventory(
    path: Path,
    suffix: str | None = None,
    limit: int = 100,
    recursive: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "is_dir": path.is_dir(),
        "file_count": 0,
        "dir_count": 0,
        "total_file_bytes": 0,
        "entries": [],
    }
    if not path.exists() or not path.is_dir():
        return payload
    try:
        children = path.rglob("*") if recursive else path.iterdir()
        for child in sorted(children, key=lambda item: str(item.relative_to(path)) if item != path else item.name):
            try:
                stat = child.stat()
            except OSError:
                continue
            relative_name = str(child.relative_to(path))
            if child.is_dir():
                payload["dir_count"] += 1
            elif child.is_file():
                payload["file_count"] += 1
                payload["total_file_bytes"] += stat.st_size
                if suffix and not relative_name.endswith(suffix):
                    continue
                if len(payload["entries"]) < limit:
                    payload["entries"].append(
                        {
                            "name": relative_name,
                            "bytes": stat.st_size,
                            "mtime": int(stat.st_mtime),
                        }
                    )
    except OSError as exc:
        payload["error"] = str(exc)
    return payload


def legacy_hashed_plugin_package_filename(plugin_unique_identifier: str) -> str:
    digest = hashlib.sha256(plugin_unique_identifier.encode("utf-8")).hexdigest()
    return f"{digest}.difypkg"


def plugin_package_candidates(plugin_unique_identifier: str) -> list[str]:
    # Current dify-plugin-daemon uses the plugin_unique_identifier as the package
    # bucket key. Keep the older hashed .difypkg candidate for compatibility with
    # previous experimental builds and diagnostics.
    return [
        plugin_unique_identifier,
        legacy_hashed_plugin_package_filename(plugin_unique_identifier),
    ]


def plugin_hashed_identity(plugin_unique_identifier: str) -> str:
    return hashlib.sha256(plugin_unique_identifier.encode("utf-8")).hexdigest()


def redis_cli_base_args(db: int | None = None) -> tuple[list[str], dict[str, str] | None]:
    args = ["redis-cli", "-h", env("REDIS_HOST", "127.0.0.1"), "-p", env("REDIS_PORT", "6379")]
    if db is not None:
        args.extend(["-n", str(db)])
    args.append("--raw")
    extra_env = {"REDISCLI_AUTH": env("REDIS_PASSWORD")} if env("REDIS_PASSWORD") else None
    return args, extra_env


def redis_db_candidates() -> list[int]:
    primary = parse_int(env("REDIS_DB"), 0)
    if primary is None or primary < 0:
        primary = 0
    candidates: list[int] = []
    for db in [primary, 0, 1]:
        if db not in candidates:
            candidates.append(db)
    return candidates


def redis_prefix_candidates() -> list[str]:
    configured = env("REDIS_KEY_PREFIX", "").strip()
    candidates: list[str] = []
    for prefix in [configured or "plugin_daemon", "plugin_daemon", configured, ""]:
        if prefix not in candidates:
            candidates.append(prefix)
    return candidates


def redis_hash_key(hash_name: str, prefix: str) -> str:
    return f"{prefix}:{hash_name}" if prefix else hash_name


def redis_hash_scan_json(
    hash_name: str,
    match: str = "*",
    limit: int = 500,
    prefix: str | None = None,
    db: int | None = None,
) -> dict[str, Any]:
    selected_prefix = redis_prefix_candidates()[0] if prefix is None else prefix
    selected_db = redis_db_candidates()[0] if db is None else db
    key = redis_hash_key(hash_name, selected_prefix)
    base_args, extra_env = redis_cli_base_args(selected_db)
    cursor = "0"
    fields: dict[str, Any] = {}
    invalid_values = 0
    iterations = 0
    while True:
        iterations += 1
        result = run_cmd(
            [*base_args, "HSCAN", key, cursor, "MATCH", match, "COUNT", "100"],
            timeout=5.0,
            extra_env=extra_env,
            output_limit=200_000,
        )
        if not result["ok"]:
            return {
                "ok": False,
                "key": key,
                "db": selected_db,
                "prefix": selected_prefix,
                "match": match,
                "fields": fields,
                "count": len(fields),
                "invalid_values": invalid_values,
                "error": result["stderr"] or result["stdout"],
                "returncode": result["returncode"],
                "duration_ms": result["duration_ms"],
            }

        lines = result["stdout"].splitlines()
        cursor = lines[0].strip() if lines else "0"
        values = lines[1:]
        for index in range(0, len(values), 2):
            if len(fields) >= limit:
                cursor = "0"
                break
            if index + 1 >= len(values):
                invalid_values += 1
                continue
            field = values[index]
            try:
                parsed = json.loads(values[index + 1])
            except json.JSONDecodeError:
                invalid_values += 1
                continue
            fields[field] = parsed

        if cursor == "0" or iterations >= 100:
            break

    return {
        "ok": True,
        "key": key,
        "db": selected_db,
        "prefix": selected_prefix,
        "match": match,
        "fields": fields,
        "count": len(fields),
        "invalid_values": invalid_values,
    }


def redis_hash_scan_candidates(hash_name: str, match: str = "*", limit: int = 500) -> dict[str, Any]:
    attempts = []
    first_ok: dict[str, Any] | None = None
    first_error: dict[str, Any] | None = None
    for db in redis_db_candidates():
        for prefix in redis_prefix_candidates():
            result = redis_hash_scan_json(hash_name, match=match, limit=limit, prefix=prefix, db=db)
            attempt = {
                "db": result.get("db"),
                "key": result.get("key"),
                "prefix": result.get("prefix"),
                "ok": result.get("ok"),
                "count": result.get("count", 0),
                "invalid_values": result.get("invalid_values", 0),
                "error": result.get("error", ""),
            }
            attempts.append(attempt)
            if result.get("ok") and first_ok is None:
                first_ok = result
            if not result.get("ok") and first_error is None:
                first_error = result
            if result.get("ok") and result.get("count", 0) > 0:
                result["checked"] = attempts
                return result

    selected = first_ok or first_error or {
        "ok": False,
        "key": "",
        "db": None,
        "prefix": "",
        "match": match,
        "fields": {},
        "count": 0,
        "invalid_values": 0,
        "error": "no Redis hash scan attempts were executed",
    }
    selected["checked"] = attempts
    return selected


def runtime_state_summary(plugin_unique_identifier: str, state_fields: dict[str, Any]) -> dict[str, Any]:
    hashed_identity = plugin_hashed_identity(plugin_unique_identifier)
    matches = []
    for field, state in state_fields.items():
        if not field.endswith(f":{hashed_identity}"):
            continue
        node_id = field.rsplit(":", 1)[0]
        if not isinstance(state, dict):
            continue
        matches.append(
            {
                "field": field,
                "node_id": node_id,
                "identity": str(state.get("identity", "")),
                "status": str(state.get("status", "")),
                "working_path": str(state.get("working_path", "")),
                "verified": bool(state.get("verified", False)),
                "restarts": parse_optional_int(state.get("restarts")),
                "active_at": state.get("active_at"),
                "stopped_at": state.get("stopped_at"),
                "scheduled_at": state.get("scheduled_at"),
            }
        )
    return {
        "plugin_unique_identifier": plugin_unique_identifier,
        "hashed_plugin_id": hashed_identity,
        "state_count": len(matches),
        "states": matches,
    }


def plugin_runtime_log_summary(plugin_unique_identifier: str, lines: int = 2000) -> dict[str, Any]:
    log_path = LOG_DIR / SERVICE_LOGS.get("plugin-daemon", "plugin-daemon.log")
    summary: dict[str, Any] = {
        "plugin_unique_identifier": plugin_unique_identifier,
        "log_path": str(log_path),
        "log_exists": log_path.exists(),
        "ready": False,
        "starting_count": 0,
        "scale_up_count": 0,
        "instance_ready_count": 0,
        "ready_count": 0,
        "error_count_after_last_ready": 0,
        "last_ready_line": "",
    }
    if not log_path.exists():
        return summary

    content = tail_file(log_path, lines)
    last_ready_index = -1
    for index, line in enumerate(content.splitlines()):
        if plugin_unique_identifier not in line:
            continue
        if "local runtime starting" in line:
            summary["starting_count"] += 1
        if "local runtime scale up" in line:
            summary["scale_up_count"] += 1
        if "local runtime instance ready" in line:
            summary["instance_ready_count"] += 1
        if "local runtime ready" in line:
            summary["ready"] = True
            summary["ready_count"] += 1
            summary["last_ready_line"] = line[:500]
            last_ready_index = index
        if last_ready_index >= 0 and index > last_ready_index:
            lowered = line.lower()
            if "error" in lowered or "failed" in lowered or "plugin runtime not found" in lowered or "no available node" in lowered:
                summary["error_count_after_last_ready"] += 1
    return summary


def psql_rows(database: str, columns: list[str], sql: str) -> dict[str, Any]:
    if not database:
        return {"ok": False, "error": "database name is empty", "rows": []}
    args = [
        "psql",
        "-h",
        env("DB_HOST", "127.0.0.1"),
        "-p",
        env("DB_PORT", "5432"),
        "-U",
        env("DB_USERNAME", "dify"),
        "-d",
        database,
        "-F",
        "\t",
        "-Atc",
        sql,
    ]
    extra_env = {"PGPASSWORD": env("DB_PASSWORD")} if env("DB_PASSWORD") else None
    result = run_cmd(args, timeout=5.0, extra_env=extra_env, output_limit=50_000)
    if not result["ok"]:
        return {
            "ok": False,
            "error": result["stderr"] or result["stdout"],
            "returncode": result["returncode"],
            "duration_ms": result["duration_ms"],
            "rows": [],
        }
    rows = []
    for line in result["stdout"].splitlines():
        if not line:
            continue
        values = line.split("\t")
        row = {column: values[index] if index < len(values) else "" for index, column in enumerate(columns)}
        rows.append(row)
    return {
        "ok": True,
        "duration_ms": result["duration_ms"],
        "count": len(rows),
        "rows": rows,
    }


def plugin_db_payload() -> dict[str, Any]:
    plugin_database = env("DB_PLUGIN_DATABASE", "dify_plugin")
    main_database = env("DB_DATABASE", "dify")
    return {
        "plugin_database": plugin_database,
        "main_database": main_database,
        "plugins": psql_rows(
            plugin_database,
            ["plugin_id", "plugin_unique_identifier"],
            "select plugin_id, plugin_unique_identifier from plugins limit 500",
        ),
        "plugin_installations": psql_rows(
            plugin_database,
            ["tenant_id", "plugin_id", "plugin_unique_identifier"],
            "select tenant_id, plugin_id, plugin_unique_identifier from plugin_installations limit 500",
        ),
        "api_plugin_references": psql_rows(
            main_database,
            ["source", "tenant_id", "provider_name"],
            """
            select 'providers' as source, tenant_id, provider_name from providers where provider_name like '%/%'
            union all
            select 'provider_models' as source, tenant_id, provider_name from provider_models where provider_name like '%/%'
            union all
            select 'provider_model_settings' as source, tenant_id, provider_name from provider_model_settings where provider_name like '%/%'
            union all
            select 'provider_credentials' as source, tenant_id, provider_name from provider_credentials where provider_name like '%/%'
            union all
            select 'provider_model_credentials' as source, tenant_id, provider_name from provider_model_credentials where provider_name like '%/%'
            limit 500
            """,
        ),
    }


def collect_plugin_identifiers(db_payload: dict[str, Any], package_dir: Path, installed_dir: Path) -> list[dict[str, Any]]:
    identifiers: dict[str, dict[str, Any]] = {}
    sources = {
        "plugins": ("plugin_id",),
        "plugin_installations": ("tenant_id", "plugin_id"),
    }
    for source, extra_keys in sources.items():
        section = db_payload.get(source, {})
        for row in section.get("rows", []):
            identifier = row.get("plugin_unique_identifier") or ""
            if not identifier:
                continue
            package_candidates = plugin_package_candidates(identifier)
            found_package = next((candidate for candidate in package_candidates if (package_dir / candidate).is_file()), "")
            found_installed = next((candidate for candidate in package_candidates if (installed_dir / candidate).is_file()), "")
            if identifier not in identifiers:
                identifiers[identifier] = {
                    "source": source,
                    "sources": [],
                    "plugin_unique_identifier": identifier,
                    "hashed_plugin_id": plugin_hashed_identity(identifier),
                    "package_candidates": package_candidates,
                    "found_package": found_package,
                    "package_exists": bool(found_package),
                    "found_installed": found_installed,
                    "installed_exists": bool(found_installed),
                    "tenant_ids": [],
                    "plugin_ids": [],
                }
            entry = identifiers[identifier]
            if source not in entry["sources"]:
                entry["sources"].append(source)
            if found_package and not entry["found_package"]:
                entry["found_package"] = found_package
                entry["package_exists"] = True
            if found_installed and not entry["found_installed"]:
                entry["found_installed"] = found_installed
                entry["installed_exists"] = True
            if row.get("tenant_id") and row["tenant_id"] not in entry["tenant_ids"]:
                entry["tenant_ids"].append(row["tenant_id"])
                entry.setdefault("tenant_id", row["tenant_id"])
            if row.get("plugin_id") and row["plugin_id"] not in entry["plugin_ids"]:
                entry["plugin_ids"].append(row["plugin_id"])
                entry.setdefault("plugin_id", row["plugin_id"])
            for extra_key in extra_keys:
                if row.get(extra_key) and extra_key not in ("tenant_id", "plugin_id"):
                    entry[extra_key] = row[extra_key]
    return list(identifiers.values())


def persistence_payload() -> dict[str, Any]:
    plugin_paths = plugin_storage_paths()
    package_dir = plugin_paths["package_cache"]
    installed_dir = plugin_paths["installed"]
    packages = directory_inventory(package_dir, limit=200, recursive=True)
    installed = directory_inventory(installed_dir, limit=200, recursive=True)
    db_payload = plugin_db_payload()
    identifiers = collect_plugin_identifiers(db_payload, package_dir, installed_dir)
    expected_packages = {candidate for item in identifiers for candidate in item["package_candidates"]}
    package_entries = {entry["name"] for entry in packages.get("entries", [])}
    installed_entries = {entry["name"] for entry in installed.get("entries", [])}
    missing_packages = [item for item in identifiers if not item["package_exists"]]
    missing_installed = [item for item in identifiers if not item["installed_exists"]]
    orphan_packages = sorted(package_entries - expected_packages)
    orphan_installed = sorted(installed_entries - expected_packages)
    runtime_state = redis_hash_scan_candidates("plugin_state")
    runtime_state_fields = runtime_state.get("fields", {}) if runtime_state.get("ok") else {}
    runtime_identifiers = [
        {
            **runtime_state_summary(item["plugin_unique_identifier"], runtime_state_fields),
            "log": plugin_runtime_log_summary(item["plugin_unique_identifier"]),
        }
        for item in identifiers
    ]
    missing_runtime_states = [
        item
        for item in runtime_identifiers
        if item["state_count"] == 0
        and (
            not item.get("log", {}).get("ready")
            or item.get("log", {}).get("error_count_after_last_ready", 0) > 0
        )
    ]
    persist_active = read_small_text(Path(env("PERSIST_ACTIVE_FILE", "/tmp/dify-aio/persist-active")))
    core_paths = {
        "data": path_summary(Path("/data")),
        "persist_root": path_summary(Path(env("PERSIST_ROOT", "/persist"))),
        "runtime_root": path_summary(Path(env("RUNTIME_ROOT", "/tmp/dify-aio"))),
        "app_storage": path_summary(Path(env("OPENDAL_FS_ROOT", "/data/dify/storage"))),
        "postgres": path_summary(Path("/data/postgres")),
        "redis": path_summary(Path("/data/redis")),
        "config": path_summary(Path("/data/config")),
        **{f"plugin_{name}": path_summary(path) for name, path in plugin_paths.items()},
    }
    db_sections = [db_payload["plugins"], db_payload["plugin_installations"], db_payload["api_plugin_references"]]
    db_ok = all(section.get("ok") for section in db_sections)
    paths_ok = all(
        core_paths[name].get("exists")
        for name in ["data", "plugin_storage_root", "plugin_package_cache", "plugin_installed"]
    )
    layout_issues = plugin_storage_layout_issues(persist_active, core_paths)
    return {
        "ok": bool(
            paths_ok
            and db_ok
            and not missing_packages
            and not missing_installed
            and not missing_runtime_states
            and not layout_issues
            and runtime_state.get("ok")
        ),
        "persist_mode": env("PERSIST_MODE", "auto"),
        "persist_active": persist_active,
        "plugin_storage_type": env("PLUGIN_STORAGE_TYPE", "local"),
        "paths": core_paths,
        "plugin_storage_layout_issues": layout_issues,
        "plugin_packages": packages,
        "plugin_installed": installed,
        "plugin_database": db_payload,
        "plugin_identifiers": identifiers,
        "plugin_runtime_state": {
            "ok": runtime_state.get("ok"),
            "key": runtime_state.get("key"),
            "db": runtime_state.get("db"),
            "prefix": runtime_state.get("prefix"),
            "checked": runtime_state.get("checked", []),
            "count": runtime_state.get("count", 0),
            "invalid_values": runtime_state.get("invalid_values", 0),
            "error": runtime_state.get("error", ""),
            "identifiers": runtime_identifiers,
        },
        "missing_package_files": missing_packages,
        "missing_installed_files": missing_installed,
        "missing_runtime_states": missing_runtime_states,
        "orphan_package_files": orphan_packages[:200],
        "orphan_installed_files": orphan_installed[:200],
        "notes": [
            "Current dify-plugin-daemon stores local packages by plugin_unique_identifier under PLUGIN_PACKAGE_CACHE_PATH.",
            "The local runtime watchdog launches plugins from PLUGIN_INSTALLED_PATH, while PLUGIN_PACKAGE_CACHE_PATH is the package cache used during install/reinstall.",
            "A missing package or installed file with an existing plugin DB/API reference means configuration can remain visible while local plugin runtime cannot be rebuilt.",
            "plugin_runtime_state summarizes Redis plugin_state plus plugin-daemon local-runtime log evidence; in single-container local mode the in-process runtime can be ready even when the Redis cluster hash is empty.",
            "plugin_storage_layout_issues flags bucket-lite layouts where plugin-daemon would see installed/package directories through a symlink root instead of the real /persist storage root.",
        ],
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
    return cached_payload("system", _system_payload)


def _system_payload() -> dict[str, Any]:
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
        max_bytes = ops_log_tail_max_bytes()
        with path.open("rb") as file:
            file.seek(0, os.SEEK_END)
            end = file.tell()
            block_size = 8192
            blocks = []
            newline_count = 0
            position = end
            read_bytes = 0
            while position > 0 and newline_count <= lines and read_bytes < max_bytes:
                read_size = min(block_size, position, max_bytes - read_bytes)
                position -= read_size
                file.seek(position)
                block = file.read(read_size)
                blocks.append(block)
                newline_count += block.count(b"\n")
                read_bytes += read_size
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
    path = resolve_log_path(filename)
    if path is None:
        return {"ok": False, "error": "log path escapes OPS_LOG_DIR"}
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
        path = resolve_log_path(filename)
        if path is None:
            continue
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


def html_index() -> str:
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
        <select id="languageSelect" aria-label="Language">
          <option value="en">English</option>
          <option value="zh">中文</option>
        </select>
        <label class="switch"><input type="checkbox" id="autoRefresh" checked> <span data-i18n="autoRefresh">Auto refresh</span></label>
        <button id="refreshButton" type="button" data-i18n="refresh">Refresh</button>
      </div>
    </header>

    <section class="grid">
      <section class="panel wide">
        <h2 data-i18n="overview">Overview</h2>
        <div class="summary" id="summary"></div>
      </section>

      <section class="panel">
        <h2 data-i18n="resources">Resources</h2>
        <div id="resources"></div>
      </section>

      <section class="panel">
        <h2 data-i18n="healthChecks">Health Checks</h2>
        <div id="checks"></div>
      </section>

      <section class="panel wide">
        <h2 data-i18n="services">Services</h2>
        <div id="services"></div>
      </section>

      <section class="panel wide">
        <h2 data-i18n="recentErrors">Recent Errors</h2>
        <div id="errors"></div>
      </section>

      <section class="panel wide">
        <h2 data-i18n="logs">Logs</h2>
        <div class="log-controls">
          <select id="logService" aria-label="Log service">__SERVICE_OPTIONS__</select>
          <input id="logLines" type="number" min="1" max="1000" value="120" aria-label="Log lines">
          <button id="loadLog" type="button" data-i18n="load">Load</button>
          <a id="metricsLink" href="metrics" target="_blank" rel="noreferrer" data-i18n="metrics">Metrics</a>
        </div>
        <pre id="logOutput" data-i18n="selectLog">Select a service log.</pre>
      </section>
    </section>
  </main>
  <script>
    const HEADERS = {};
    const I18N = {
      en: {
        autoRefresh: "Auto refresh",
        refresh: "Refresh",
        overview: "Overview",
        resources: "Resources",
        healthChecks: "Health Checks",
        services: "Services",
        recentErrors: "Recent Errors",
        logs: "Logs",
        load: "Load",
        metrics: "Metrics",
        selectLog: "Select a service log.",
        loadingRuntime: "Loading runtime summary...",
        loading: "Loading",
        overall: "Overall",
        healthy: "Healthy",
        unhealthy: "Unhealthy",
        checks: "Checks",
        checksPassing: "{passing}/{total} passing",
        processes: "Processes",
        uptime: "Uptime",
        runtimeSummary: "Runtime summary",
        cpuLoad: "CPU load",
        memory: "Memory",
        disk: "Disk {path}",
        noResourceData: "No resource data.",
        noChecksConfigured: "No checks configured",
        name: "Name",
        status: "Status",
        latency: "Latency",
        service: "Service",
        state: "State",
        description: "Description",
        ok: "OK",
        fail: "FAIL",
        noSupervisorStatus: "No supervisor status",
        noMatchedErrors: "No matched recent errors.",
        matches: "{count} matches",
        noGroupedErrors: "No grouped error data.",
        noLogContent: "No log content.",
        dashboard: "Dashboard",
        error: "Error",
        logServiceLabel: "Log service",
        logLinesLabel: "Log lines",
        languageLabel: "Language"
      },
      zh: {
        autoRefresh: "自动刷新",
        refresh: "刷新",
        overview: "总览",
        resources: "资源",
        healthChecks: "健康检查",
        services: "服务",
        recentErrors: "近期错误",
        logs: "日志",
        load: "加载",
        metrics: "指标",
        selectLog: "选择一个服务日志。",
        loadingRuntime: "正在加载运行摘要...",
        loading: "加载中",
        overall: "整体状态",
        healthy: "健康",
        unhealthy: "异常",
        checks: "检查项",
        checksPassing: "{passing}/{total} 通过",
        processes: "进程数",
        uptime: "运行时长",
        runtimeSummary: "运行摘要",
        cpuLoad: "CPU 负载",
        memory: "内存",
        disk: "磁盘 {path}",
        noResourceData: "暂无资源数据。",
        noChecksConfigured: "没有配置检查项",
        name: "名称",
        status: "状态",
        latency: "耗时",
        service: "服务",
        state: "状态",
        description: "描述",
        ok: "正常",
        fail: "失败",
        noSupervisorStatus: "暂无 Supervisor 状态",
        noMatchedErrors: "近期没有匹配到错误。",
        matches: "{count} 条匹配",
        noGroupedErrors: "暂无分组错误数据。",
        noLogContent: "暂无日志内容。",
        dashboard: "控制台",
        error: "错误",
        logServiceLabel: "日志服务",
        logLinesLabel: "日志行数",
        languageLabel: "语言"
      }
    };
    let timer = null;
    let locale = detectLocale();

    const byId = (id) => document.getElementById(id);
    const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    }[char]));

    function detectLocale() {
      const saved = localStorage.getItem("dify_ops_locale");
      if (saved === "zh" || saved === "en") return saved;
      return (navigator.language || "").toLowerCase().startsWith("zh") ? "zh" : "en";
    }

    function t(key, values = {}) {
      let text = (I18N[locale] && I18N[locale][key]) || I18N.en[key] || key;
      Object.entries(values).forEach(([name, value]) => {
        text = text.replaceAll(`{${name}}`, value);
      });
      return text;
    }

    function applyI18n() {
      document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
      byId("languageSelect").value = locale;
      byId("languageSelect").setAttribute("aria-label", t("languageLabel"));
      byId("logService").setAttribute("aria-label", t("logServiceLabel"));
      byId("logLines").setAttribute("aria-label", t("logLinesLabel"));
      document.querySelectorAll("[data-i18n]").forEach((node) => {
        node.textContent = t(node.getAttribute("data-i18n"));
      });
      if (byId("versionLine").textContent === "Loading runtime summary..." || byId("versionLine").textContent === I18N.zh.loadingRuntime) {
        byId("versionLine").textContent = t("loadingRuntime");
      }
      if (byId("overall").textContent === "Loading" || byId("overall").textContent === I18N.zh.loading) {
        byId("overall").textContent = t("loading");
      }
    }

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
        stat(t("overall"), health.ok ? t("healthy") : t("unhealthy"), health.ok ? "ok-text" : "bad-text"),
        stat(t("checks"), t("checksPassing", {passing: checks.length - failed, total: checks.length})),
        stat(t("processes"), system.process_count ?? "n/a"),
        stat(t("uptime"), fmtDuration(system.uptime_seconds)),
      ].join("");
      const overall = byId("overall");
      overall.textContent = health.ok ? t("healthy") : t("unhealthy");
      overall.className = `status-pill ${health.ok ? "ok" : "bad"}`;
      byId("versionLine").textContent = [
        version.version?.dify_version ? `Dify ${version.version.dify_version}` : "",
        version.version?.deploy_env || "",
        version.version?.public_url || version.version?.space_host || "",
      ].filter(Boolean).join(" · ") || t("runtimeSummary");
    }

    function renderResources(system) {
      const cpu = system.cpu || {};
      const memory = system.memory || {};
      const disk = system.disk || {};
      const rows = [];
      if (cpu.ok) rows.push(resourceBar(t("cpuLoad"), Math.min(100, (cpu.load1 / Math.max(cpu.cpu_count || 1, 1)) * 100), `1m ${cpu.load1}, 5m ${cpu.load5}, 15m ${cpu.load15}`));
      if (memory.ok) rows.push(resourceBar(t("memory"), memory.used_percent, `${fmtBytes(memory.used_bytes)} / ${fmtBytes(memory.total_bytes)}`));
      Object.values(disk).forEach((usage) => {
        if (usage.ok) rows.push(resourceBar(t("disk", {path: usage.path}), usage.used_percent, `${fmtBytes(usage.used_bytes)} / ${fmtBytes(usage.total_bytes)}`));
      });
      byId("resources").innerHTML = rows.join("") || `<div class="muted">${esc(t("noResourceData"))}</div>`;
    }

    function renderChecks(health) {
      const checks = health.checks || [];
      if (!checks.length) {
        const message = health.error === "no checks configured" ? t("noChecksConfigured") : (health.error || t("noChecksConfigured"));
        byId("checks").innerHTML = `<div class="bad-text">${esc(message)}</div>`;
        return;
      }
      byId("checks").innerHTML = `<table><thead><tr><th>${esc(t("name"))}</th><th>${esc(t("status"))}</th><th>${esc(t("latency"))}</th></tr></thead><tbody>${
        checks.map((item) => `<tr><td>${esc(item.name)}</td><td class="${item.ok ? "ok-text" : "bad-text"}">${item.ok ? esc(t("ok")) : esc(t("fail"))}</td><td>${esc(item.duration_ms ?? "")} ms</td></tr>`).join("")
      }</tbody></table>`;
    }

    function renderServices(status) {
      const programs = status.supervisor?.programs || [];
      if (!programs.length) {
        byId("services").innerHTML = `<div class="bad-text">${esc(status.supervisor?.stderr || t("noSupervisorStatus"))}</div>`;
        return;
      }
      byId("services").innerHTML = `<table><thead><tr><th>${esc(t("service"))}</th><th>${esc(t("state"))}</th><th>${esc(t("description"))}</th></tr></thead><tbody>${
        programs.map((item) => `<tr><td>${esc(item.name)}</td><td class="${item.ok ? "ok-text" : "bad-text"}">${esc(item.state)}</td><td>${esc(item.description)}</td></tr>`).join("")
      }</tbody></table>`;
    }

    function renderErrors(errors) {
      if (errors.ok) {
        byId("errors").innerHTML = `<div class="ok-text">${esc(t("noMatchedErrors"))}</div>`;
        return;
      }
      const groups = errors.groups || [];
      byId("errors").innerHTML = groups.map((group) => {
        const patterns = Object.entries(group.pattern_counts || {}).map(([key, value]) => `${esc(key)}: ${value}`).join(", ");
        const lines = (group.matches || []).map((item) => `<div class="error-line"><strong>${esc(item.pattern)}</strong> ${esc(item.line)}</div>`).join("");
        return `<div class="error-group"><strong>${esc(group.service)}</strong> <span class="muted">${esc(t("matches", {count: group.count}))} · ${patterns}</span>${lines}</div>`;
      }).join("") || `<div class="muted">${esc(t("noGroupedErrors"))}</div>`;
    }

    async function loadLog() {
      const service = byId("logService").value;
      const lines = byId("logLines").value || "120";
      const payload = await getJson(`logs?service=${encodeURIComponent(service)}&lines=${encodeURIComponent(lines)}`);
      byId("logOutput").textContent = payload.content || payload.error || t("noLogContent");
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
    byId("languageSelect").addEventListener("change", () => {
      locale = byId("languageSelect").value === "zh" ? "zh" : "en";
      localStorage.setItem("dify_ops_locale", locale);
      applyI18n();
      refreshAll();
    });
    byId("loadLog").addEventListener("click", loadLog);
    byId("metricsLink").href = "metrics";
    applyI18n();
    refreshAll().catch((error) => {
      byId("overall").textContent = t("error");
      byId("overall").className = "status-pill bad";
      byId("summary").innerHTML = stat(t("dashboard"), error.message || String(error), "bad-text");
    });
    configureTimer();
  </script>
</body>
</html>
"""
    return template.replace("__SERVICE_OPTIONS__", service_options)


class Handler(BaseHTTPRequestHandler):
    server_version = "dify-aio-ops/1.0"

    def setup(self) -> None:
        super().setup()
        timeout = parse_float(env("OPS_HTTP_TIMEOUT_SECONDS", "30"), 30.0, minimum=1.0, maximum=600.0)
        self.request.settimeout(timeout)
        self.ops_auth_source = ""

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

    def send_locked(self) -> None:
        self.send_json(
            {
                "ok": False,
                "error": "ops service is locked",
                "reason": ops_lock_reason(),
                "hint": "Set OPS_TOKEN to a strong value. For local demo only, set ALLOW_DEMO_OPS_TOKEN=true.",
            },
            status=503,
        )

    def cookie_secure_enabled(self) -> bool:
        mode = env("OPS_COOKIE_SECURE", "auto").strip().lower()
        if mode in {"1", "true", "yes", "on"}:
            return True
        if mode in {"0", "false", "no", "off"}:
            return False
        proto = self.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip().lower()
        return proto == "https"

    def session_cookie_header(self) -> str:
        value, expires_at = make_ops_session()
        max_age = max(expires_at - int(time.time()), 0)
        secure = "; Secure" if self.cookie_secure_enabled() else ""
        return f"{OPS_SESSION_COOKIE}={value}; Path=/_ops/; Max-Age={max_age}; HttpOnly; SameSite=Lax{secure}"

    def maybe_send_session_cookie(self) -> None:
        if self.ops_auth_source in {"header", "query"}:
            self.send_header("Set-Cookie", self.session_cookie_header())

    def maybe_send_query_token_headers(self) -> None:
        if self.ops_auth_source == "query":
            self.send_header("Cache-Control", "no-store")

    def send_security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")

    def send_query_redirect(self) -> None:
        self.send_response(303)
        self.send_header("Location", "/_ops/")
        self.maybe_send_session_cookie()
        self.send_security_headers()
        self.maybe_send_query_token_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.maybe_send_session_cookie()
        self.send_security_headers()
        self.maybe_send_query_token_headers()
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, body: str, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.maybe_send_session_cookie()
        self.send_security_headers()
        self.maybe_send_query_token_headers()
        self.end_headers()
        self.wfile.write(data)

    def parsed(self) -> tuple[str, dict[str, list[str]]]:
        parsed = urllib.parse.urlparse(self.path)
        return parsed.path, urllib.parse.parse_qs(parsed.query)

    def cookie_auth(self) -> bool:
        raw = self.headers.get("Cookie", "")
        if not raw:
            return False
        cookie = SimpleCookie()
        try:
            cookie.load(raw)
        except Exception:
            return False
        morsel = cookie.get(OPS_SESSION_COOKIE)
        return bool(morsel and parse_ops_session(morsel.value))

    def auth_source(self, query: dict[str, list[str]]) -> str:
        expected = env("OPS_TOKEN")
        if not expected:
            return ""
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            provided = auth.removeprefix("Bearer ").strip()
            if provided and hmac.compare_digest(provided, expected):
                return "header"
        provided = self.headers.get("X-Ops-Token", "").strip()
        if provided and hmac.compare_digest(provided, expected):
            return "header"
        provided = query.get("token", [""])[0]
        if provided and hmac.compare_digest(provided, expected):
            return "query"
        if self.cookie_auth():
            return "cookie"
        return ""

    def require_auth(self, query: dict[str, list[str]]) -> bool:
        if ops_lock_reason():
            self.send_locked()
            return False
        self.ops_auth_source = self.auth_source(query)
        if self.ops_auth_source:
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
            if ops_lock_reason():
                self.send_locked()
                return
            payload = health_payload(public=True)
            self.send_json(payload, status=200 if payload["ok"] else 503)
            return

        if not self.require_auth(query):
            return

        if path in {"/", ""} and self.ops_auth_source == "query":
            self.send_query_redirect()
            return

        if path in {"/", ""}:
            self.send_text(html_index(), content_type="text/html; charset=utf-8")
        elif path == "/health":
            payload = health_payload(public=False)
            self.send_json(payload, status=200 if payload["ok"] else 503)
        elif path == "/status":
            self.send_json(status_payload())
        elif path == "/system":
            self.send_json({"ok": True, "system": system_payload()})
        elif path == "/persistence":
            payload = persistence_payload()
            self.send_json(payload, status=200 if payload["ok"] else 503)
        elif path == "/config":
            self.send_json({"ok": True, "config": config_payload()})
        elif path == "/process-env":
            payload = process_env_payload(query)
            self.send_json(payload, status=200 if payload["ok"] else 404)
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
