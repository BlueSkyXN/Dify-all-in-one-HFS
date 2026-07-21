#!/usr/bin/env python3
"""Controlled admin service for the Dify all-in-one demo container."""

from __future__ import annotations

import fnmatch
import hashlib
import hmac
import html
import http.client
import json
import mimetypes
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import uuid
import xmlrpc.client
from collections import defaultdict, deque
from dataclasses import dataclass
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import Any


STARTED_AT = time.time()
SUPERVISOR_CONFIG = "/etc/supervisor/conf.d/supervisord.conf"
SUPERVISOR_SOCKET = "/data/run/supervisor.sock"
SESSION_COOKIE = "dify_admin_session"
MAX_JSON_BYTES = 1024 * 1024
MAX_TEXT_READ_BYTES = 1024 * 1024
MAX_AUDIT_EVENTS = 500
LOGIN_FAILURES_BY_IP: dict[str, deque[float]] = defaultdict(deque)
LOGIN_FAILURES_GLOBAL: deque[float] = deque()
LOGIN_RATE_LOCK = Lock()
EXPECTED_EXITED_PROGRAMS = {"sandbox-selfcheck"}

ALLOWED_RESTART_SERVICES = [
    "dify-api",
    "dify-worker",
    "dify-beat",
    "plugin-daemon",
    "sandbox",
    "dify-web",
    "nginx",
]

PROTECTED_NAME_PATTERNS = [
    "generated.env",
    "*.pem",
    "*.key",
    "*secret*",
]

BENIGN_TOKEN_NAME_PREFIXES = (
    "tokenizer",
    "tokenization",
)

SENSITIVE_DETAIL_KEYS = (
    "authorization",
    "apikey",
    "cookie",
    "credential",
    "privatekey",
    "secret",
    "token",
    "password",
)

@dataclass
class AuthContext:
    kind: str
    csrf_token: str
    expires_at: int | None = None
    nonce: str = ""


class AdminError(Exception):
    def __init__(self, status: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def parse_bool(value: str, default: bool = False) -> bool:
    if value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_int(value: Any, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(parsed, minimum)
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed


def truncate_text(value: str, limit: int = 4096) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "...<truncated>"


def admin_enabled() -> bool:
    return parse_bool(env("ADMIN_ENABLED", "false"), default=False)


def admin_token() -> str:
    return env("ADMIN_TOKEN")


def admin_csrf_key() -> str:
    configured = env("ADMIN_CSRF_KEY")
    if configured:
        return configured
    secret_key = env("SECRET_KEY")
    if secret_key:
        return hmac.new(secret_key.encode("utf-8"), b"dify-aio-admin-csrf", hashlib.sha256).hexdigest()
    return admin_token()


def admin_files_enabled() -> bool:
    return parse_bool(env("ADMIN_FILES_ENABLED", "false"), default=False)


def admin_files_write_enabled() -> bool:
    return parse_bool(env("ADMIN_FILES_WRITE_ENABLED", "false"), default=False)


def admin_files_destructive_enabled() -> bool:
    return parse_bool(env("ADMIN_FILES_DESTRUCTIVE_ENABLED", "false"), default=False)


def session_ttl_seconds() -> int:
    return parse_int(env("ADMIN_SESSION_TTL_SECONDS"), 3600, minimum=60, maximum=86400)


def upload_limit_bytes() -> int:
    return parse_int(env("ADMIN_FILES_MAX_UPLOAD_BYTES"), 10 * 1024 * 1024, minimum=1, maximum=512 * 1024 * 1024)


def login_rate_limit_window_seconds() -> int:
    return parse_int(env("ADMIN_LOGIN_RATE_LIMIT_WINDOW_SECONDS"), 300, minimum=10, maximum=3600)


def login_rate_limit_block_seconds() -> int:
    return parse_int(env("ADMIN_LOGIN_RATE_LIMIT_BLOCK_SECONDS"), 300, minimum=10, maximum=3600)


def login_rate_limit_max_per_ip() -> int:
    return parse_int(env("ADMIN_LOGIN_RATE_LIMIT_MAX_PER_IP"), 5, minimum=1, maximum=1000)


def login_rate_limit_max_global() -> int:
    return parse_int(env("ADMIN_LOGIN_RATE_LIMIT_MAX_GLOBAL"), 30, minimum=1, maximum=10000)


def trusted_remote_addr(headers: Any, client_address: Any) -> str:
    real_ip = str(headers.get("X-Real-IP", "")).strip()
    if real_ip:
        return real_ip
    try:
        return str(client_address[0]) if client_address else ""
    except (IndexError, TypeError):
        return ""


def prune_failures(values: deque[float], now: float, window: int) -> None:
    while values and values[0] <= now - window:
        values.popleft()


def login_retry_after(remote_addr: str) -> int:
    now = time.time()
    window = login_rate_limit_window_seconds()
    block = login_rate_limit_block_seconds()
    with LOGIN_RATE_LOCK:
        prune_login_failure_entries(now, max(window, block))
        ip_failures = LOGIN_FAILURES_BY_IP.get(remote_addr, deque())
        prune_failures(ip_failures, now, max(window, block))
        prune_failures(LOGIN_FAILURES_GLOBAL, now, max(window, block))
        if len(ip_failures) >= login_rate_limit_max_per_ip() and now - ip_failures[-1] < block:
            return max(1, int(block - (now - ip_failures[-1])))
        if len(LOGIN_FAILURES_GLOBAL) >= login_rate_limit_max_global() and now - LOGIN_FAILURES_GLOBAL[-1] < block:
            return max(1, int(block - (now - LOGIN_FAILURES_GLOBAL[-1])))
    return 0


def record_login_failure(remote_addr: str) -> None:
    now = time.time()
    window = login_rate_limit_window_seconds()
    with LOGIN_RATE_LOCK:
        prune_login_failure_entries(now, max(window, login_rate_limit_block_seconds()))
        ip_failures = LOGIN_FAILURES_BY_IP[remote_addr]
        prune_failures(ip_failures, now, window)
        prune_failures(LOGIN_FAILURES_GLOBAL, now, window)
        ip_failures.append(now)
        LOGIN_FAILURES_GLOBAL.append(now)


def clear_login_failures(remote_addr: str) -> None:
    with LOGIN_RATE_LOCK:
        LOGIN_FAILURES_BY_IP.pop(remote_addr, None)


def prune_login_failure_entries(now: float, window: int) -> None:
    for remote_addr in list(LOGIN_FAILURES_BY_IP):
        failures = LOGIN_FAILURES_BY_IP[remote_addr]
        prune_failures(failures, now, window)
        if not failures:
            LOGIN_FAILURES_BY_IP.pop(remote_addr, None)


def sign_message(*parts: str) -> str:
    token = admin_token()
    payload = "|".join(parts).encode("utf-8")
    return hmac.new(token.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def sign_csrf_message(*parts: str) -> str:
    payload = "|".join(parts).encode("utf-8")
    return hmac.new(admin_csrf_key().encode("utf-8"), payload, hashlib.sha256).hexdigest()


def csrf_for(expires_at: int, nonce: str) -> str:
    return sign_csrf_message("csrf", str(expires_at), nonce)


def make_session() -> tuple[str, str, int]:
    expires_at = int(time.time()) + session_ttl_seconds()
    nonce = secrets.token_urlsafe(32)
    signature = sign_message("session", str(expires_at), nonce)
    cookie_value = f"{expires_at}.{nonce}.{signature}"
    return cookie_value, csrf_for(expires_at, nonce), expires_at


def parse_session(cookie_value: str) -> AuthContext | None:
    try:
        expires_raw, nonce, signature = cookie_value.split(".", 2)
        expires_at = int(expires_raw)
    except (ValueError, AttributeError):
        return None
    if expires_at < int(time.time()) or not nonce or not signature:
        return None
    expected = sign_message("session", str(expires_at), nonce)
    if not hmac.compare_digest(signature, expected):
        return None
    return AuthContext(kind="cookie", csrf_token=csrf_for(expires_at, nonce), expires_at=expires_at, nonce=nonce)


def run_cmd(args: list[str], timeout: float = 10.0, input_text: str | None = None) -> dict[str, Any]:
    started = time.time()
    try:
        completed = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            input=input_text,
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


def supervisor_process_info() -> list[dict[str, Any]]:
    proxy = xmlrpc.client.ServerProxy(
        "http://localhost/RPC2",
        transport=UnixSocketTransport(SUPERVISOR_SOCKET, timeout=3.0),
        allow_none=True,
    )
    return proxy.supervisor.getAllProcessInfo()


def supervisor_status() -> dict[str, Any]:
    started = time.time()
    try:
        info = supervisor_process_info()
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
        exitstatus = item.get("exitstatus")
        ok = state == "RUNNING" or (
            name in EXPECTED_EXITED_PROGRAMS and state == "EXITED" and exitstatus == 0
        )
        programs.append(
            {
                "name": f"{group}:{name}" if group and group != name else name,
                "state": state,
                "exitstatus": exitstatus,
                "description": str(item.get("description", "")),
                "ok": ok,
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


def status_payload(auth: AuthContext) -> dict[str, Any]:
    return {
        "ok": True,
        "service": "dify-all-in-one-admin",
        "uptime_seconds": int(time.time() - STARTED_AT),
        "dify_version": env("DIFY_VERSION"),
        "deploy_env": env("DEPLOY_ENV"),
        "public_url": env("PUBLIC_URL"),
        "auth": {
            "kind": auth.kind,
            "session_expires_at": auth.expires_at,
            "csrf_token": auth.csrf_token,
        },
        "admin": {
            "enabled": admin_enabled(),
            "host": env("ADMIN_HOST", "127.0.0.1"),
            "port": parse_int(env("ADMIN_PORT"), 8082, minimum=1, maximum=65535),
            "session_ttl_seconds": session_ttl_seconds(),
            "audit_log": str(audit_log_path()),
        },
        "files": {
            "enabled": admin_files_enabled(),
            "write_enabled": admin_files_write_enabled(),
            "destructive_enabled": admin_files_destructive_enabled(),
            "root": str(admin_files_root()),
            "max_upload_bytes": upload_limit_bytes(),
            "max_text_read_bytes": MAX_TEXT_READ_BYTES,
        },
        "supervisor": supervisor_status(),
    }


def actions_payload() -> dict[str, Any]:
    return {
        "ok": True,
        "actions": [
            {
                "id": "restart-service",
                "method": "POST",
                "path": "/_admin/api/actions/restart-service",
                "requires_confirm": True,
                "allowed_services": ALLOWED_RESTART_SERVICES,
            },
            {
                "id": "reload-nginx",
                "method": "POST",
                "path": "/_admin/api/actions/reload-nginx",
                "requires_confirm": True,
            },
            {
                "id": "run-health-checks",
                "method": "POST",
                "path": "/_admin/api/actions/run-health-checks",
                "requires_confirm": True,
            },
            {
                "id": "force-postgres-backup",
                "method": "POST",
                "path": "/_admin/api/actions/force-postgres-backup",
                "requires_confirm": True,
            },
            {
                "id": "ensure-app-api-token",
                "method": "POST",
                "path": "/_admin/api/actions/ensure-app-api-token",
                "requires_confirm": True,
                "description": "Create a Dify app service API token when the selected app has none or when a known token must be restored.",
            },
            {
                "id": "ensure-plugin-installed-from-cache",
                "method": "POST",
                "path": "/_admin/api/actions/ensure-plugin-installed-from-cache",
                "requires_confirm": True,
                "description": "Restore plugin installed package files from the local package cache for plugin identifiers already registered in the plugin database.",
            },
            {
                "id": "set-provider-model-read-timeout",
                "method": "POST",
                "path": "/_admin/api/actions/set-provider-model-read-timeout",
                "requires_confirm": True,
                "description": "Patch a Dify provider model credential JSON config with a non-secret read_timeout value. Dry-run by default.",
            },
        ],
    }


def new_action_id(action: str) -> str:
    return f"{int(time.time() * 1000)}-{action}-{secrets.token_hex(4)}"


def audit_log_path() -> Path:
    return Path(env("ADMIN_AUDIT_LOG", "/data/logs/admin-audit.jsonl"))


def audit_event(action: str, ok: bool, actor: str, target: str = "", details: dict[str, Any] | None = None) -> None:
    entry = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "action": action,
        "ok": ok,
        "actor": actor,
        "target": target,
        "details": details or {},
    }
    path = audit_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
    except OSError as exc:
        sys.stderr.write(f"[dify-aio-admin] audit write failed: {exc}\n")
        sys.stderr.flush()


def tail_lines(path: Path, lines: int) -> list[str]:
    if not path.exists():
        return []
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
        raise AdminError(500, f"unable to read audit log: {exc}") from exc
    return data.decode("utf-8", errors="replace").splitlines()[-lines:]


def redact_sensitive_details(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            key_text = str(key)
            normalized_key = key_text.lower().replace("_", "").replace("-", "")
            if any(marker in normalized_key for marker in SENSITIVE_DETAIL_KEYS):
                redacted[key_text] = "[redacted]"
            else:
                redacted[key_text] = redact_sensitive_details(item)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive_details(item) for item in value[:100]]
    if isinstance(value, str):
        return truncate_text(value, 1000)
    return value


def audit_payload(query: dict[str, list[str]]) -> dict[str, Any]:
    limit = parse_int(query.get("limit", ["100"])[0], 100, minimum=1, maximum=MAX_AUDIT_EVENTS)
    path = audit_log_path()
    if not path.exists():
        return {
            "ok": True,
            "path": str(path),
            "exists": False,
            "limit": limit,
            "returned": 0,
            "invalid_lines": 0,
            "events": [],
        }

    invalid_lines = 0
    events: list[dict[str, Any]] = []
    for line in reversed(tail_lines(path, limit * 4)):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            invalid_lines += 1
            continue
        if not isinstance(event, dict):
            invalid_lines += 1
            continue
        events.append(
            {
                "time": str(event.get("time", "")),
                "action": str(event.get("action", "")),
                "ok": bool(event.get("ok", False)),
                "actor": str(event.get("actor", "")),
                "target": str(event.get("target", "")),
                "details": redact_sensitive_details(event.get("details", {})),
            }
        )
        if len(events) >= limit:
            break

    events.reverse()
    return {
        "ok": True,
        "path": str(path),
        "exists": True,
        "limit": limit,
        "returned": len(events),
        "invalid_lines": invalid_lines,
        "events": events,
    }


def confirmed(payload: dict[str, Any]) -> bool:
    value = payload.get("confirm", False)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def restart_service(payload: dict[str, Any], auth: AuthContext) -> dict[str, Any]:
    service = payload.get("service")
    if service not in ALLOWED_RESTART_SERVICES:
        raise AdminError(400, "service is not in restart whitelist", allowed_services=ALLOWED_RESTART_SERVICES)
    if not confirmed(payload):
        raise AdminError(400, "confirm=true is required")
    action_id = new_action_id("restart-service")
    result = run_cmd(["supervisorctl", "-c", SUPERVISOR_CONFIG, "restart", service], timeout=30.0)
    response = {"ok": result["ok"], "action_id": action_id, "action": "restart-service", "service": service, "result": result}
    audit_event("restart-service", result["ok"], auth.kind, service, {"action_id": action_id, "returncode": result["returncode"]})
    return response


def reload_nginx(payload: dict[str, Any], auth: AuthContext) -> dict[str, Any]:
    if not confirmed(payload):
        raise AdminError(400, "confirm=true is required")
    action_id = new_action_id("reload-nginx")
    test_result = run_cmd(["nginx", "-t", "-c", "/etc/nginx/nginx.conf"], timeout=10.0)
    reload_result: dict[str, Any] | None = None
    ok = False
    if test_result["ok"]:
        reload_result = run_cmd(["nginx", "-s", "reload", "-c", "/etc/nginx/nginx.conf"], timeout=10.0)
        ok = reload_result["ok"]
    response = {
        "ok": ok,
        "action_id": action_id,
        "action": "reload-nginx",
        "test": test_result,
        "reload": reload_result,
    }
    audit_event("reload-nginx", ok, auth.kind, "nginx", {"action_id": action_id, "test_ok": test_result["ok"]})
    return response


def run_health_checks(payload: dict[str, Any], auth: AuthContext) -> dict[str, Any]:
    if not confirmed(payload):
        raise AdminError(400, "confirm=true is required")
    action_id = new_action_id("run-health-checks")
    result = run_cmd(["/usr/local/bin/dify-demo-healthcheck"], timeout=45.0)
    response = {"ok": result["ok"], "action_id": action_id, "action": "run-health-checks", "result": result}
    audit_event("run-health-checks", result["ok"], auth.kind, "healthcheck", {"action_id": action_id})
    return response


def force_postgres_backup(payload: dict[str, Any], auth: AuthContext) -> dict[str, Any]:
    if not confirmed(payload):
        raise AdminError(400, "confirm=true is required")
    action_id = new_action_id("force-postgres-backup")
    result = run_cmd(["/usr/local/bin/postgres-backup-loop", "--once"], timeout=300.0)
    response = {"ok": result["ok"], "action_id": action_id, "action": "force-postgres-backup", "result": result}
    audit_event(
        "force-postgres-backup",
        result["ok"],
        auth.kind,
        "postgres",
        {"action_id": action_id, "returncode": result["returncode"]},
    )
    return response

def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def psql_args(database: str | None = None) -> tuple[list[str], dict[str, str] | None]:
    args = [
        "psql",
        "-h",
        env("DB_HOST", "127.0.0.1"),
        "-p",
        env("DB_PORT", "5432"),
        "-U",
        env("DB_USERNAME", "dify"),
        "-d",
        database or env("DB_DATABASE", "dify"),
        "-At",
        "-v",
        "ON_ERROR_STOP=1",
    ]
    extra_env = {"PGPASSWORD": env("DB_PASSWORD")} if env("DB_PASSWORD") else None
    return args, extra_env


def run_psql(sql: str, timeout: float = 10.0, output_limit: int = 200_000, database: str | None = None) -> dict[str, Any]:
    args, extra_env = psql_args(database)
    started = time.time()
    try:
        completed = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            input=sql,
            timeout=timeout,
            env={**os.environ, **(extra_env or {})},
        )
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": truncate_text(completed.stdout.strip(), output_limit),
            "stderr": truncate_text(completed.stderr.strip(), output_limit),
            "duration_ms": round((time.time() - started) * 1000),
        }
    except FileNotFoundError as exc:
        return {"ok": False, "returncode": 127, "stdout": "", "stderr": str(exc), "duration_ms": round((time.time() - started) * 1000)}
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "returncode": None,
            "stdout": truncate_text((exc.stdout or "").strip(), output_limit),
            "stderr": f"timeout after {timeout}s",
            "duration_ms": round((time.time() - started) * 1000),
        }


def psql_json_rows(sql: str, timeout: float = 10.0, database: str | None = None) -> dict[str, Any]:
    wrapped_sql = f"select coalesce(json_agg(row_to_json(q)), '[]'::json)::text from ({sql}) q;"
    result = run_psql(wrapped_sql, timeout=timeout, database=database)
    if not result["ok"]:
        return {"ok": False, "error": result["stderr"] or result["stdout"], "rows": [], "count": 0}
    raw = result["stdout"].strip() or "[]"
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"failed to parse psql json output: {exc}", "rows": [], "count": 0}
    return {"ok": isinstance(rows, list), "rows": rows if isinstance(rows, list) else [], "count": len(rows) if isinstance(rows, list) else 0}


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
    }


def legacy_hashed_plugin_package_filename(plugin_unique_identifier: str) -> str:
    digest = hashlib.sha256(plugin_unique_identifier.encode("utf-8")).hexdigest()
    return f"{digest}.difypkg"


def plugin_package_candidates(plugin_unique_identifier: str) -> list[str]:
    return [
        plugin_unique_identifier,
        legacy_hashed_plugin_package_filename(plugin_unique_identifier),
    ]


def safe_plugin_relative_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise AdminError(400, "invalid plugin package path")
    return path


def validate_plugin_identifier(raw: Any) -> str:
    value = str(raw or "").strip()
    if not value:
        return ""
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-/.:@")
    if len(value) > 512 or any(char not in allowed for char in value):
        raise AdminError(400, "plugin_unique_identifier contains unsupported characters")
    safe_plugin_relative_path(value)
    return value


def plugin_db_identifiers() -> dict[str, Any]:
    return psql_json_rows(
        """
        select distinct plugin_unique_identifier
        from (
            select plugin_unique_identifier from plugins where plugin_unique_identifier is not null and plugin_unique_identifier <> ''
            union all
            select plugin_unique_identifier from plugin_installations where plugin_unique_identifier is not null and plugin_unique_identifier <> ''
        ) q
        order by plugin_unique_identifier
        limit 500
        """,
        timeout=10.0,
        database=env("DB_PLUGIN_DATABASE", "dify_plugin"),
    )


def generated_app_token() -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "app-" + "".join(secrets.choice(alphabet) for _ in range(24))


def validate_app_id(raw: Any) -> str:
    value = str(raw or "").strip()
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise AdminError(400, "app_id must be a UUID") from exc


def validate_app_token(raw: Any) -> str:
    value = str(raw or "").strip()
    if not value:
        raise AdminError(400, "token must be non-empty")
    if len(value) > 255:
        raise AdminError(400, "token is too long")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    if not value.startswith("app-") or any(char not in allowed for char in value):
        raise AdminError(400, "token must start with app- and contain only letters, digits, '_' or '-'")
    return value


def token_summary(value: str) -> dict[str, Any]:
    return {
        "prefix": value[:4],
        "length": len(value),
        "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest()[:16],
    }


def ensure_app_api_token(payload: dict[str, Any], auth: AuthContext) -> dict[str, Any]:
    if not confirmed(payload):
        raise AdminError(400, "confirm=true is required")
    app_id = validate_app_id(payload.get("app_id"))
    provided_token = payload.get("token")
    token_was_provided = isinstance(provided_token, str) and bool(provided_token.strip())
    token = validate_app_token(provided_token) if token_was_provided else generated_app_token()
    token_id = str(uuid.uuid4())
    action_id = new_action_id("ensure-app-api-token")
    app_rows = psql_json_rows(
        f"""
        select a.id::text as app_id, a.tenant_id::text as tenant_id, a.name as app_name, a.enable_api,
               (select count(*) from api_tokens t where t.app_id = a.id and t.type = 'app')::int as api_token_count,
               exists(select 1 from api_tokens t where t.app_id = a.id and t.type = 'app' and t.token = {sql_literal(token)}) as token_exists
        from apps a
        where a.id = {sql_literal(app_id)}
        limit 1
        """,
        timeout=10.0,
    )
    if not app_rows.get("ok"):
        audit_event("ensure-app-api-token", False, auth.kind, app_id, {"action_id": action_id, "error": app_rows.get("error", "query failed")})
        raise AdminError(500, "unable to read app token state", detail=app_rows.get("error", ""))
    if not app_rows["rows"]:
        audit_event("ensure-app-api-token", False, auth.kind, app_id, {"action_id": action_id, "error": "app not found"})
        raise AdminError(404, "app not found")

    app = app_rows["rows"][0]
    before_count = int(app.get("api_token_count") or 0)
    created = False
    if not app.get("token_exists"):
        insert_result = run_psql(
            f"""
            insert into api_tokens (id, app_id, tenant_id, type, token, created_at)
            values ({sql_literal(token_id)}, {sql_literal(app_id)}, {sql_literal(str(app.get("tenant_id") or ""))}, 'app', {sql_literal(token)}, current_timestamp);
            """,
            timeout=10.0,
        )
        if not insert_result["ok"]:
            audit_event(
                "ensure-app-api-token",
                False,
                auth.kind,
                app_id,
                {"action_id": action_id, "token": token_summary(token), "error": insert_result["stderr"] or insert_result["stdout"]},
            )
            raise AdminError(500, "unable to insert app API token", detail=insert_result["stderr"] or insert_result["stdout"])
        created = True

    response: dict[str, Any] = {
        "ok": True,
        "action_id": action_id,
        "action": "ensure-app-api-token",
        "app_id": app_id,
        "app_name": app.get("app_name"),
        "created": created,
        "api_token_count_before": before_count,
        "api_token_count_after": before_count + (1 if created else 0),
        "token_summary": token_summary(token),
    }
    if created and not token_was_provided:
        response["token"] = token
    audit_event(
        "ensure-app-api-token",
        True,
        auth.kind,
        app_id,
        {
            "action_id": action_id,
            "created": created,
            "api_token_count_before": before_count,
            "api_token_count_after": response["api_token_count_after"],
            "token": token_summary(token),
        },
    )
    return response


def ensure_plugin_installed_from_cache(payload: dict[str, Any], auth: AuthContext) -> dict[str, Any]:
    if not confirmed(payload):
        raise AdminError(400, "confirm=true is required")
    requested_identifier = validate_plugin_identifier(payload.get("plugin_unique_identifier"))
    restart_plugin_daemon = payload.get("restart_plugin_daemon", True)
    if isinstance(restart_plugin_daemon, str):
        restart_plugin_daemon = restart_plugin_daemon.strip().lower() in {"1", "true", "yes", "on"}
    else:
        restart_plugin_daemon = bool(restart_plugin_daemon)

    action_id = new_action_id("ensure-plugin-installed-from-cache")
    identifier_rows = plugin_db_identifiers()
    if not identifier_rows.get("ok"):
        audit_event(
            "ensure-plugin-installed-from-cache",
            False,
            auth.kind,
            requested_identifier or "all",
            {"action_id": action_id, "error": identifier_rows.get("error", "query failed")},
        )
        raise AdminError(500, "unable to read plugin metadata", detail=identifier_rows.get("error", ""))

    db_identifiers = sorted(
        {
            validate_plugin_identifier(row.get("plugin_unique_identifier"))
            for row in identifier_rows.get("rows", [])
            if row.get("plugin_unique_identifier")
        }
    )
    if requested_identifier:
        if requested_identifier not in db_identifiers:
            audit_event(
                "ensure-plugin-installed-from-cache",
                False,
                auth.kind,
                requested_identifier,
                {"action_id": action_id, "error": "plugin identifier is not registered in plugin database"},
            )
            raise AdminError(404, "plugin identifier is not registered in plugin database")
        selected_identifiers = [requested_identifier]
    else:
        selected_identifiers = db_identifiers

    paths = plugin_storage_paths()
    package_dir = paths["package_cache"]
    installed_dir = paths["installed"]
    installed_dir.mkdir(parents=True, exist_ok=True)
    copied: list[dict[str, Any]] = []
    already_installed: list[dict[str, Any]] = []
    missing_source: list[dict[str, Any]] = []

    for identifier in selected_identifiers:
        source_candidate = ""
        installed_candidate = ""
        for candidate in plugin_package_candidates(identifier):
            relative = safe_plugin_relative_path(candidate)
            if (package_dir / relative).is_file() and not source_candidate:
                source_candidate = candidate
            if (installed_dir / relative).is_file() and not installed_candidate:
                installed_candidate = candidate
        if installed_candidate:
            already_installed.append({"plugin_unique_identifier": identifier, "installed": installed_candidate})
            continue
        if not source_candidate:
            missing_source.append({"plugin_unique_identifier": identifier})
            continue
        relative = safe_plugin_relative_path(source_candidate)
        source = package_dir / relative
        target = installed_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(
            {
                "plugin_unique_identifier": identifier,
                "source": source_candidate,
                "installed": source_candidate,
                "bytes": target.stat().st_size,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest()[:16],
            }
        )

    restart_result: dict[str, Any] | None = None
    if copied and restart_plugin_daemon:
        restart_result = run_cmd(["supervisorctl", "-c", SUPERVISOR_CONFIG, "restart", "plugin-daemon"], timeout=30.0)

    ok = not missing_source and (restart_result is None or restart_result.get("ok"))
    response = {
        "ok": ok,
        "action_id": action_id,
        "action": "ensure-plugin-installed-from-cache",
        "selected_count": len(selected_identifiers),
        "copied_count": len(copied),
        "already_installed_count": len(already_installed),
        "missing_source_count": len(missing_source),
        "copied": copied,
        "already_installed": already_installed,
        "missing_source": missing_source,
        "restart_plugin_daemon": bool(copied and restart_plugin_daemon),
        "restart_result": restart_result,
    }
    audit_event(
        "ensure-plugin-installed-from-cache",
        ok,
        auth.kind,
        requested_identifier or "all",
        {
            "action_id": action_id,
            "selected_count": len(selected_identifiers),
            "copied_count": len(copied),
            "already_installed_count": len(already_installed),
            "missing_source_count": len(missing_source),
            "restart_plugin_daemon": bool(copied and restart_plugin_daemon),
            "restart_returncode": restart_result.get("returncode") if restart_result else None,
        },
    )
    if not ok:
        raise AdminError(500, "unable to restore every selected plugin installed package", **response)
    return response


def validate_provider_model_filter(raw: Any, field: str) -> str:
    value = str(raw or "").strip()
    if not value:
        raise AdminError(400, f"{field} must be non-empty")
    if "\x00" in value or len(value) > 255:
        raise AdminError(400, f"{field} is invalid")
    return value


def validate_provider_read_timeout(raw: Any) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise AdminError(400, "read_timeout must be an integer") from None
    if value < 1 or value > 3600:
        raise AdminError(400, "read_timeout must be between 1 and 3600 seconds")
    return value


def provider_timeout_dry_run(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return True
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return bool(raw)


def provider_model_timeout_rows(provider_name: str, model_name: str, model_type: str) -> dict[str, Any]:
    return psql_json_rows(
        f"""
        select id::text as id, provider_name, model_name, model_type, credential_name,
               nullif(encrypted_config::jsonb ->> 'read_timeout', '')::int as read_timeout
        from provider_model_credentials
        where provider_name = {sql_literal(provider_name)}
          and model_name = {sql_literal(model_name)}
          and model_type = {sql_literal(model_type)}
        order by updated_at desc
        """,
        timeout=10.0,
    )


def set_provider_model_read_timeout(payload: dict[str, Any], auth: AuthContext) -> dict[str, Any]:
    if not confirmed(payload):
        raise AdminError(400, "confirm=true is required")
    provider_name = validate_provider_model_filter(payload.get("provider_name"), "provider_name")
    model_name = validate_provider_model_filter(payload.get("model_name"), "model_name")
    model_type = validate_provider_model_filter(payload.get("model_type") or "llm", "model_type")
    read_timeout = validate_provider_read_timeout(payload.get("read_timeout", 300))
    dry_run = provider_timeout_dry_run(payload.get("dry_run", True))
    action_id = new_action_id("set-provider-model-read-timeout")
    target = f"{provider_name}/{model_type}/{model_name}"

    before = provider_model_timeout_rows(provider_name, model_name, model_type)
    if not before.get("ok"):
        audit_event(
            "set-provider-model-read-timeout",
            False,
            auth.kind,
            target,
            {"action_id": action_id, "dry_run": dry_run, "read_timeout": read_timeout, "error": before.get("error", "query failed")},
        )
        raise AdminError(500, "unable to read provider model credentials", detail=before.get("error", ""))
    if not before.get("rows"):
        audit_event(
            "set-provider-model-read-timeout",
            False,
            auth.kind,
            target,
            {"action_id": action_id, "dry_run": dry_run, "read_timeout": read_timeout, "error": "credential not found"},
        )
        raise AdminError(404, "provider model credential not found")

    changed = 0
    update_result: dict[str, Any] | None = None
    if not dry_run:
        update_result = run_psql(
            f"""
            update provider_model_credentials
            set encrypted_config = jsonb_set(
                    coalesce(encrypted_config::jsonb, '{{}}'::jsonb),
                    '{{read_timeout}}',
                    to_jsonb({read_timeout}::int),
                    true
                )::text,
                updated_at = current_timestamp
            where provider_name = {sql_literal(provider_name)}
              and model_name = {sql_literal(model_name)}
              and model_type = {sql_literal(model_type)};
            """,
            timeout=10.0,
        )
        if not update_result.get("ok"):
            audit_event(
                "set-provider-model-read-timeout",
                False,
                auth.kind,
                target,
                {
                    "action_id": action_id,
                    "dry_run": dry_run,
                    "read_timeout": read_timeout,
                    "matched_count": len(before.get("rows", [])),
                    "error": update_result.get("stderr") or update_result.get("stdout"),
                },
            )
            raise AdminError(500, "unable to update provider model credential", detail=update_result.get("stderr") or update_result.get("stdout"))
        changed = len(before.get("rows", []))

    after = before if dry_run else provider_model_timeout_rows(provider_name, model_name, model_type)
    if not after.get("ok"):
        audit_event(
            "set-provider-model-read-timeout",
            False,
            auth.kind,
            target,
            {"action_id": action_id, "dry_run": dry_run, "read_timeout": read_timeout, "error": after.get("error", "query failed")},
        )
        raise AdminError(500, "unable to read provider model credentials after update", detail=after.get("error", ""))

    before_rows = [
        {
            "id": row.get("id"),
            "provider_name": row.get("provider_name"),
            "model_name": row.get("model_name"),
            "model_type": row.get("model_type"),
            "credential_name": row.get("credential_name"),
            "read_timeout": row.get("read_timeout"),
        }
        for row in before.get("rows", [])
    ]
    after_rows = [
        {
            "id": row.get("id"),
            "provider_name": row.get("provider_name"),
            "model_name": row.get("model_name"),
            "model_type": row.get("model_type"),
            "credential_name": row.get("credential_name"),
            "read_timeout": row.get("read_timeout"),
        }
        for row in after.get("rows", [])
    ]
    response = {
        "ok": True,
        "action_id": action_id,
        "action": "set-provider-model-read-timeout",
        "dry_run": dry_run,
        "provider_name": provider_name,
        "model_name": model_name,
        "model_type": model_type,
        "read_timeout": read_timeout,
        "matched_count": len(before_rows),
        "changed_count": changed,
        "before": before_rows,
        "after": after_rows,
        "update_returncode": update_result.get("returncode") if update_result else None,
    }
    audit_event(
        "set-provider-model-read-timeout",
        True,
        auth.kind,
        target,
        {
            "action_id": action_id,
            "dry_run": dry_run,
            "read_timeout": read_timeout,
            "matched_count": len(before_rows),
            "changed_count": changed,
        },
    )
    return response


def admin_files_root() -> Path:
    return Path(env("ADMIN_FILES_ROOT", "/data"))


def normalise_admin_path(raw: str | None) -> Path:
    value = raw or ""
    value = value.replace("\\", "/")
    if "\x00" in value:
        raise AdminError(400, "path contains invalid characters")
    value = value.lstrip("/")
    parts = []
    for part in value.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            raise AdminError(400, "path must stay inside ADMIN_FILES_ROOT")
        parts.append(part)
    return Path(*parts) if parts else Path()


def ensure_inside_root(target: Path, root: Path) -> None:
    try:
        common = os.path.commonpath([str(root), str(target)])
    except ValueError as exc:
        raise AdminError(400, "path must stay inside ADMIN_FILES_ROOT") from exc
    if common != str(root):
        raise AdminError(403, "path escapes ADMIN_FILES_ROOT")


def resolve_admin_path(raw: str | None) -> tuple[Path, Path, Path]:
    root = admin_files_root().resolve(strict=False)
    rel = normalise_admin_path(raw)
    target = (root / rel).resolve(strict=False)
    ensure_inside_root(target, root)
    return root, rel, target


def is_protected_path(target: Path) -> bool:
    generated = Path("/data/config/generated.env").resolve(strict=False)
    resolved = target.resolve(strict=False)
    if resolved == generated:
        return True
    for part in resolved.parts:
        lower = part.lower()
        if any(fnmatch.fnmatch(lower, pattern) for pattern in PROTECTED_NAME_PATTERNS):
            return True
        if "token" in lower and not is_benign_token_name(lower):
            return True
    return False


def is_benign_token_name(lower: str) -> bool:
    for prefix in BENIGN_TOKEN_NAME_PREFIXES:
        if lower.startswith(prefix) and "token" not in lower[len(prefix) :]:
            return True
    return False


def require_files_enabled() -> None:
    if not admin_files_enabled():
        raise AdminError(404, "file manager is disabled")


def require_files_write_enabled() -> None:
    require_files_enabled()
    if not admin_files_write_enabled():
        raise AdminError(403, "file manager write operations are disabled")


def require_files_destructive_enabled() -> None:
    require_files_write_enabled()
    if not admin_files_destructive_enabled():
        raise AdminError(403, "file manager destructive operations are disabled")


def require_unprotected(target: Path) -> None:
    if is_protected_path(target):
        raise AdminError(403, "path is protected")


def safe_download_filename(value: str) -> str:
    cleaned = []
    for char in value:
        if char in {"/", "\\", '"', ";", "\r", "\n", "\x00"} or ord(char) < 32 or ord(char) == 127:
            cleaned.append("_")
        else:
            cleaned.append(char)
    name = "".join(cleaned).strip() or "download"
    return name[:180]


def content_disposition_attachment(filename: str) -> str:
    safe_name = safe_download_filename(filename)
    fallback = []
    for char in safe_name:
        if char in {'"', ";", "\\"} or ord(char) < 32 or ord(char) >= 127:
            fallback.append("_")
        else:
            fallback.append(char)
    fallback_name = "".join(fallback).strip(" .") or "download"
    encoded_name = urllib.parse.quote(safe_name, safe="")
    return f'attachment; filename="{fallback_name}"; filename*=UTF-8\'\'{encoded_name}'


def path_display(root: Path, target: Path) -> str:
    try:
        rel = target.relative_to(root)
    except ValueError:
        return ""
    value = str(rel)
    return "/" if value == "." else f"/{value}"


def entry_payload(root: Path, entry: Path) -> dict[str, Any]:
    try:
        stat = entry.lstat()
    except OSError as exc:
        return {"name": entry.name, "ok": False, "error": str(exc)}
    resolved = entry.resolve(strict=False)
    in_root = True
    try:
        ensure_inside_root(resolved, root)
    except AdminError:
        in_root = False
    entry_type = "symlink" if entry.is_symlink() else "directory" if entry.is_dir() else "file" if entry.is_file() else "other"
    return {
        "name": entry.name,
        "path": path_display(root, entry),
        "type": entry_type,
        "size": stat.st_size,
        "modified_at": int(stat.st_mtime),
        "protected": (not in_root) or is_protected_path(entry),
    }


def files_list_payload(query: dict[str, list[str]]) -> dict[str, Any]:
    require_files_enabled()
    root, rel, target = resolve_admin_path(query.get("path", ["/"])[0])
    require_unprotected(target)
    if not target.exists():
        raise AdminError(404, "path does not exist")
    if not target.is_dir():
        raise AdminError(400, "path is not a directory")
    entries = []
    try:
        for entry in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            entries.append(entry_payload(root, entry))
    except OSError as exc:
        raise AdminError(500, f"unable to list directory: {exc}") from exc
    return {
        "ok": True,
        "root": str(root),
        "path": "/" if str(rel) == "." else f"/{rel}",
        "write_enabled": admin_files_write_enabled(),
        "destructive_enabled": admin_files_destructive_enabled(),
        "entries": entries,
    }


def read_text_payload(query: dict[str, list[str]]) -> dict[str, Any]:
    require_files_enabled()
    root, _rel, target = resolve_admin_path(query.get("path", [""])[0])
    require_unprotected(target)
    if not target.is_file():
        raise AdminError(404, "file does not exist")
    size = target.stat().st_size
    if size > MAX_TEXT_READ_BYTES:
        raise AdminError(413, "file is too large for text view", size=size, max_bytes=MAX_TEXT_READ_BYTES)
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise AdminError(500, f"unable to read file: {exc}") from exc
    return {"ok": True, "path": path_display(root, target), "size": size, "content": content}


def download_file(query: dict[str, list[str]]) -> tuple[Path, str]:
    require_files_enabled()
    _root, _rel, target = resolve_admin_path(query.get("path", [""])[0])
    require_unprotected(target)
    if not target.is_file():
        raise AdminError(404, "file does not exist")
    content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return target, content_type


def mkdir_payload(payload: dict[str, Any], auth: AuthContext) -> dict[str, Any]:
    require_files_write_enabled()
    root, _rel, target = resolve_admin_path(str(payload.get("path", "")))
    require_unprotected(target)
    parents = bool(payload.get("parents", True))
    try:
        target.mkdir(parents=parents, exist_ok=bool(payload.get("exist_ok", True)))
    except OSError as exc:
        audit_event("files.mkdir", False, auth.kind, path_display(root, target), {"error": str(exc)})
        raise AdminError(500, f"unable to create directory: {exc}") from exc
    audit_event("files.mkdir", True, auth.kind, path_display(root, target))
    return {"ok": True, "path": path_display(root, target)}


def write_text_payload(payload: dict[str, Any], auth: AuthContext) -> dict[str, Any]:
    require_files_write_enabled()
    content = payload.get("content")
    if not isinstance(content, str):
        raise AdminError(400, "content must be a string")
    data = content.encode("utf-8")
    if len(data) > upload_limit_bytes():
        raise AdminError(413, "content exceeds ADMIN_FILES_MAX_UPLOAD_BYTES", max_bytes=upload_limit_bytes())
    root, _rel, target = resolve_admin_path(str(payload.get("path", "")))
    require_unprotected(target)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        audit_event("files.write_text", False, auth.kind, path_display(root, target), {"error": str(exc)})
        raise AdminError(500, f"unable to write file: {exc}") from exc
    audit_event("files.write_text", True, auth.kind, path_display(root, target), {"bytes": len(data)})
    return {"ok": True, "path": path_display(root, target), "bytes": len(data)}


def upload_payload(raw_path: str | None, body: bytes, auth: AuthContext) -> dict[str, Any]:
    require_files_write_enabled()
    if len(body) > upload_limit_bytes():
        raise AdminError(413, "upload exceeds ADMIN_FILES_MAX_UPLOAD_BYTES", max_bytes=upload_limit_bytes())
    root, _rel, target = resolve_admin_path(raw_path)
    require_unprotected(target)
    if target.exists():
        raise AdminError(409, "target already exists")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    except OSError as exc:
        audit_event("files.upload", False, auth.kind, path_display(root, target), {"error": str(exc)})
        raise AdminError(500, f"unable to upload file: {exc}") from exc
    audit_event("files.upload", True, auth.kind, path_display(root, target), {"bytes": len(body)})
    return {"ok": True, "path": path_display(root, target), "bytes": len(body)}


def rename_payload(payload: dict[str, Any], auth: AuthContext) -> dict[str, Any]:
    require_files_destructive_enabled()
    if not confirmed(payload):
        raise AdminError(400, "confirm=true is required")
    root, _rel, source = resolve_admin_path(str(payload.get("path", "")))
    _root, _new_rel, target = resolve_admin_path(str(payload.get("new_path", "")))
    require_unprotected(source)
    require_unprotected(target)
    if not source.exists():
        raise AdminError(404, "source does not exist")
    if target.exists():
        raise AdminError(409, "target already exists")
    try:
        if not target.parent.exists() or not target.parent.is_dir():
            raise AdminError(404, "target parent does not exist")
        source.rename(target)
    except AdminError:
        raise
    except OSError as exc:
        audit_event("files.rename", False, auth.kind, path_display(root, source), {"new_path": path_display(root, target), "error": str(exc)})
        raise AdminError(500, f"unable to rename path: {exc}") from exc
    audit_event("files.rename", True, auth.kind, path_display(root, source), {"new_path": path_display(root, target)})
    return {"ok": True, "path": path_display(root, target)}


def delete_payload(payload: dict[str, Any], auth: AuthContext) -> dict[str, Any]:
    require_files_destructive_enabled()
    if not confirmed(payload):
        raise AdminError(400, "confirm=true is required")
    root, rel, target = resolve_admin_path(str(payload.get("path", "")))
    if str(rel) == ".":
        raise AdminError(400, "cannot delete ADMIN_FILES_ROOT")
    require_unprotected(target)
    if not target.exists() and not target.is_symlink():
        raise AdminError(404, "path does not exist")
    try:
        if target.is_dir() and not target.is_symlink():
            target.rmdir()
        else:
            target.unlink()
    except OSError as exc:
        audit_event("files.delete", False, auth.kind, path_display(root, target), {"error": str(exc)})
        raise AdminError(500, f"unable to delete path: {exc}") from exc
    audit_event("files.delete", True, auth.kind, path_display(root, target))
    return {"ok": True, "path": path_display(root, target)}


def html_index(authenticated: bool) -> str:
    page = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>Dify Admin</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --line: #d7dce5;
      --text: #171f2a;
      --muted: #647184;
      --ok: #177245;
      --bad: #b42318;
      --fill: #2563eb;
      --warn: #9a5b00;
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.45; }
    main { max-width: 1180px; margin: 0 auto; padding: 24px; }
    header { display: flex; justify-content: space-between; align-items: center; gap: 14px; margin-bottom: 18px; }
    h1 { margin: 0; font-size: 26px; letter-spacing: 0; }
    h2 { margin: 0 0 12px; font-size: 16px; letter-spacing: 0; }
    button, input, select, textarea {
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      font: inherit;
    }
    button, input, select { min-height: 36px; padding: 0 10px; }
    button { cursor: pointer; }
    button:disabled, input:disabled { cursor: not-allowed; opacity: 0.58; }
    textarea { width: 100%; min-height: 260px; padding: 10px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
    .toolbar, .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .field { display: grid; gap: 6px; margin: 10px 0; }
    .field label { color: var(--muted); font-size: 13px; }
    .grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 14px; }
    .panel { grid-column: span 6; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; min-width: 0; }
    .wide { grid-column: span 12; }
    .muted { color: var(--muted); }
    .ok { color: var(--ok); }
    .bad { color: var(--bad); }
    .pill { display: inline-flex; min-height: 28px; align-items: center; border: 1px solid var(--line); border-radius: 999px; padding: 0 10px; background: #fff; color: var(--muted); font-size: 13px; }
    .pill.ok { color: var(--ok); border-color: #a7d7bd; background: #eefaf3; }
    .pill.bad { color: var(--bad); border-color: #f1b5ae; background: #fff1ef; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { padding: 8px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
    th { color: var(--muted); font-weight: 600; }
    pre { max-height: 320px; overflow: auto; margin: 10px 0 0; padding: 12px; border-radius: 6px; background: #111827; color: #e5e7eb; font-size: 12px; white-space: pre-wrap; overflow-wrap: anywhere; }
    #loginPanel { max-width: 420px; margin: 10vh auto 0; }
    #loginPanel input { width: 100%; margin: 10px 0; }
    .hidden { display: none; }
    @media (max-width: 760px) {
      main { padding: 16px; }
      header { align-items: flex-start; flex-direction: column; }
      .panel { grid-column: span 12; }
      .toolbar, .row { width: 100%; }
      button, input, select { width: 100%; }
    }
  </style>
</head>
<body>
  <main>
    <section id="loginPanel" class="panel __LOGIN_CLASS__">
      <h1>Dify Admin</h1>
      <div class="toolbar" style="justify-content: flex-end;">
        <select id="loginLanguageSelect" aria-label="Language">
          <option value="en">English</option>
          <option value="zh">中文</option>
        </select>
      </div>
      <p class="muted" data-i18n="signInHint">Sign in with ADMIN_TOKEN.</p>
      <form id="loginForm">
        <div class="field">
          <label for="loginToken">ADMIN_TOKEN</label>
          <input id="loginToken" type="password" autocomplete="current-password" placeholder="ADMIN_TOKEN">
        </div>
        <button id="loginButton" type="submit" data-i18n="signIn">Sign in</button>
      </form>
      <div id="loginMessage" class="bad"></div>
    </section>

    <section id="app" class="__APP_CLASS__">
      <header>
        <div>
          <h1>Dify Admin</h1>
          <div id="runtimeLine" class="muted">Loading runtime summary...</div>
        </div>
        <div class="toolbar">
          <span id="overall" class="pill">Loading</span>
          <select id="languageSelect" aria-label="Language">
            <option value="en">English</option>
            <option value="zh">中文</option>
          </select>
          <button id="refreshButton" type="button" data-i18n="refresh">Refresh</button>
          <button id="logoutButton" type="button" data-i18n="logout">Logout</button>
        </div>
      </header>
      <section class="grid">
        <section class="panel">
          <h2 data-i18n="actions">Actions</h2>
          <div class="row">
            <select id="serviceSelect" aria-label="Service"></select>
            <button id="restartButton" type="button" data-i18n="restart">Restart</button>
          </div>
          <div class="row" style="margin-top: 8px;">
            <button id="reloadNginxButton" type="button" data-i18n="reloadNginx">Reload Nginx</button>
            <button id="healthButton" type="button" data-i18n="runHealthChecks">Run Health Checks</button>
            <button id="postgresBackupButton" type="button" data-i18n="backUpPostgres">Back Up Postgres</button>
          </div>
          <pre id="actionOutput" data-i18n="noActionYet">No action yet.</pre>
        </section>
        <section class="panel">
          <h2 data-i18n="supervisor">Supervisor</h2>
          <div id="services"></div>
        </section>
        <section class="panel wide">
          <h2 data-i18n="audit">Audit</h2>
          <div class="row">
            <input id="auditLimit" type="number" min="1" max="500" value="50" aria-label="Audit event limit">
            <button id="loadAuditButton" type="button" data-i18n="loadAudit">Load Audit</button>
          </div>
          <div id="auditEvents" style="margin-top: 10px;"></div>
        </section>
        <section class="panel wide">
          <h2 data-i18n="files">Files</h2>
          <div class="row">
            <input id="filePath" value="/" aria-label="Path">
            <button id="listFilesButton" type="button" data-i18n="list">List</button>
            <button id="newDirButton" type="button" data-i18n="newDir">New Dir</button>
            <input id="uploadFile" type="file" aria-label="Upload file">
          </div>
          <div id="files"></div>
          <textarea id="fileText" class="hidden"></textarea>
          <div class="row hidden" id="textActions">
            <button id="saveTextButton" type="button" data-i18n="save">Save</button>
            <button id="downloadButton" type="button" data-i18n="download">Download</button>
          </div>
        </section>
      </section>
    </section>
  </main>
  <script>
    let csrfToken = "";
    let writeEnabled = false;
    let currentTextPath = "";
    const I18N = {
      en: {
        signInHint: "Sign in with ADMIN_TOKEN.",
        signIn: "Sign in",
        refresh: "Refresh",
        logout: "Logout",
        actions: "Actions",
        service: "Service",
        restart: "Restart",
        reloadNginx: "Reload Nginx",
        runHealthChecks: "Run Health Checks",
        backUpPostgres: "Back Up Postgres",
        noActionYet: "No action yet.",
        supervisor: "Supervisor",
        audit: "Audit",
        loadAudit: "Load Audit",
        auditLimitLabel: "Audit event limit",
        files: "Files",
        path: "Path",
        uploadFile: "Upload file",
        list: "List",
        newDir: "New Dir",
        save: "Save",
        download: "Download",
        loadingRuntime: "Loading runtime summary...",
        loading: "Loading",
        ready: "Ready",
        unknown: "unknown",
        enabled: "enabled",
        disabled: "disabled",
        admin: "admin",
        fileManager: "files",
        fileManagerDisabled: "File manager is disabled.",
        program: "Program",
        state: "State",
        description: "Description",
        noSupervisorStatus: "No supervisor status yet.",
        name: "Name",
        type: "Type",
        size: "Size",
        open: "Open",
        text: "Text",
        protected: "protected",
        status: "Status",
        ok: "OK",
        fail: "Fail",
        time: "Time",
        action: "Action",
        actor: "Actor",
        target: "Target",
        details: "Details",
        noAuditEvents: "No audit events yet.",
        auditLogMissing: "Audit log does not exist yet.",
        unableToLoadAudit: "unable to load audit log",
        unableToList: "unable to list files",
        directoryEmpty: "Directory is empty.",
        directoryPrompt: "Directory path",
        languageLabel: "Language",
        loginFailed: "login failed"
      },
      zh: {
        signInHint: "使用 ADMIN_TOKEN 登录。",
        signIn: "登录",
        refresh: "刷新",
        logout: "退出登录",
        actions: "操作",
        service: "服务",
        restart: "重启",
        reloadNginx: "重载 Nginx",
        runHealthChecks: "运行健康检查",
        backUpPostgres: "备份 Postgres",
        noActionYet: "还没有执行操作。",
        supervisor: "Supervisor 进程",
        audit: "审计",
        loadAudit: "加载审计",
        auditLimitLabel: "审计事件数量",
        files: "文件",
        path: "路径",
        uploadFile: "上传文件",
        list: "列出",
        newDir: "新建目录",
        save: "保存",
        download: "下载",
        loadingRuntime: "正在加载运行摘要...",
        loading: "加载中",
        ready: "就绪",
        unknown: "未知",
        enabled: "已开启",
        disabled: "已关闭",
        admin: "管理面",
        fileManager: "文件",
        fileManagerDisabled: "文件管理器已关闭。",
        program: "程序",
        state: "状态",
        description: "描述",
        noSupervisorStatus: "暂无 Supervisor 状态。",
        name: "名称",
        type: "类型",
        size: "大小",
        open: "打开",
        text: "文本",
        protected: "受保护",
        status: "状态",
        ok: "成功",
        fail: "失败",
        time: "时间",
        action: "操作",
        actor: "操作者",
        target: "目标",
        details: "详情",
        noAuditEvents: "暂无审计事件。",
        auditLogMissing: "审计日志尚不存在。",
        unableToLoadAudit: "无法加载审计日志",
        unableToList: "无法列出文件",
        directoryEmpty: "目录为空。",
        directoryPrompt: "目录路径",
        languageLabel: "语言",
        loginFailed: "登录失败"
      }
    };
    let locale = detectLocale();
    const byId = (id) => document.getElementById(id);
    const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[char]));

    function detectLocale() {
      const saved = localStorage.getItem("dify_admin_locale");
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

    function syncLanguageControls() {
      ["languageSelect", "loginLanguageSelect"].forEach((id) => {
        const control = byId(id);
        if (control) {
          control.value = locale;
          control.setAttribute("aria-label", t("languageLabel"));
        }
      });
    }

    function applyI18n() {
      document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
      syncLanguageControls();
      byId("serviceSelect").setAttribute("aria-label", t("service"));
      byId("filePath").setAttribute("aria-label", t("path"));
      byId("uploadFile").setAttribute("aria-label", t("uploadFile"));
      byId("auditLimit").setAttribute("aria-label", t("auditLimitLabel"));
      document.querySelectorAll("[data-i18n]").forEach((node) => {
        node.textContent = t(node.getAttribute("data-i18n"));
      });
      if (byId("runtimeLine").textContent === "Loading runtime summary..." || byId("runtimeLine").textContent === I18N.zh.loadingRuntime) {
        byId("runtimeLine").textContent = t("loadingRuntime");
      }
      if (byId("overall").textContent === "Loading" || byId("overall").textContent === I18N.zh.loading) {
        byId("overall").textContent = t("loading");
      }
    }

    function setLocale(value) {
      locale = value === "zh" ? "zh" : "en";
      localStorage.setItem("dify_admin_locale", locale);
      applyI18n();
      if (!byId("app").classList.contains("hidden")) refresh();
    }

    function updateWriteControls() {
      byId("newDirButton").disabled = !writeEnabled;
      byId("uploadFile").disabled = !writeEnabled;
      byId("saveTextButton").disabled = !writeEnabled || !currentTextPath;
    }

    async function api(path, options = {}) {
      const headers = options.headers || {};
      if (csrfToken && options.method && options.method !== "GET") headers["X-Admin-CSRF"] = csrfToken;
      if (options.json) {
        headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(options.json);
      }
      const response = await fetch(path, {...options, headers, cache: "no-store"});
      const text = await response.text();
      let payload;
      try { payload = JSON.parse(text); } catch { payload = {ok: response.ok, body: text}; }
      payload.http_status = response.status;
      return payload;
    }

    async function login() {
      const token = byId("loginToken").value;
      const payload = await api("api/login", {method: "POST", json: {token}});
      if (!payload.ok) {
        byId("loginMessage").textContent = payload.error || t("loginFailed");
        return;
      }
      csrfToken = payload.csrf_token;
      byId("loginPanel").classList.add("hidden");
      byId("app").classList.remove("hidden");
      refresh();
    }

    async function refresh() {
      const payload = await api("api/status");
      if (!payload.ok) {
        byId("overall").textContent = payload.error || `HTTP ${payload.http_status}`;
        byId("overall").className = "pill bad";
        if (payload.http_status === 401) {
          byId("loginPanel").classList.remove("hidden");
          byId("app").classList.add("hidden");
        }
        return;
      }
      csrfToken = payload.auth.csrf_token;
      writeEnabled = payload.files.write_enabled;
      updateWriteControls();
      byId("overall").textContent = t("ready");
      byId("overall").className = "pill ok";
      byId("runtimeLine").textContent = `${payload.dify_version || t("unknown")} · ${t("admin")} ${payload.admin.enabled ? t("enabled") : t("disabled")} · ${t("fileManager")} ${payload.files.enabled ? t("enabled") : t("disabled")}`;
      renderServices(payload.supervisor.programs || []);
      const actions = await api("api/actions");
      renderActions(actions.actions || []);
      loadAudit();
      if (payload.files.enabled) {
        listFiles();
      } else {
        byId("files").innerHTML = `<p class="muted">${esc(t("fileManagerDisabled"))}</p>`;
      }
    }

    function renderActions(actions) {
      const restart = actions.find((item) => item.id === "restart-service");
      const services = restart ? restart.allowed_services : [];
      byId("serviceSelect").innerHTML = services.map((service) => `<option value="${esc(service)}">${esc(service)}</option>`).join("");
    }

    function renderServices(programs) {
      if (!programs.length) {
        byId("services").innerHTML = `<p class="muted">${esc(t("noSupervisorStatus"))}</p>`;
        return;
      }
      byId("services").innerHTML = `<table><thead><tr><th>${esc(t("program"))}</th><th>${esc(t("state"))}</th><th>${esc(t("description"))}</th></tr></thead><tbody>${programs.map((program) =>
        `<tr><td>${esc(program.name)}</td><td class="${program.ok ? "ok" : "bad"}">${esc(program.state)}</td><td>${esc(program.description)}</td></tr>`
      ).join("")}</tbody></table>`;
    }

    function renderAudit(payload) {
      const events = payload.events || [];
      if (!payload.ok) {
        byId("auditEvents").innerHTML = `<p class="bad">${esc(payload.error || t("unableToLoadAudit"))}</p>`;
        return;
      }
      if (payload.exists === false) {
        byId("auditEvents").innerHTML = `<p class="muted">${esc(t("auditLogMissing"))}</p>`;
        return;
      }
      if (!events.length) {
        byId("auditEvents").innerHTML = `<p class="muted">${esc(t("noAuditEvents"))}</p>`;
        return;
      }
      byId("auditEvents").innerHTML = `<table><thead><tr><th>${esc(t("status"))}</th><th>${esc(t("time"))}</th><th>${esc(t("action"))}</th><th>${esc(t("actor"))}</th><th>${esc(t("target"))}</th><th>${esc(t("details"))}</th></tr></thead><tbody>${events.map((event) =>
        `<tr><td class="${event.ok ? "ok" : "bad"}">${event.ok ? esc(t("ok")) : esc(t("fail"))}</td><td>${esc(event.time)}</td><td>${esc(event.action)}</td><td>${esc(event.actor)}</td><td>${esc(event.target)}</td><td>${esc(JSON.stringify(event.details || {}))}</td></tr>`
      ).join("")}</tbody></table>`;
    }

    async function loadAudit() {
      const limit = byId("auditLimit").value || "50";
      const payload = await api(`api/audit?limit=${encodeURIComponent(limit)}`);
      renderAudit(payload);
    }

    async function runAction(path, payload) {
      const result = await api(path, {method: "POST", json: {...payload, confirm: true}});
      byId("actionOutput").textContent = JSON.stringify(result, null, 2);
      refresh();
    }

    async function listFiles() {
      const path = byId("filePath").value || "/";
      const payload = await api(`api/files/list?path=${encodeURIComponent(path)}`);
      if (!payload.ok) {
        byId("files").innerHTML = `<p class="bad">${esc(payload.error || t("unableToList"))}</p>`;
        return;
      }
      byId("filePath").value = payload.path;
      if (!payload.entries.length) {
        byId("files").innerHTML = `<p class="muted">${esc(t("directoryEmpty"))}</p>`;
        return;
      }
      byId("files").innerHTML = `<table><thead><tr><th>${esc(t("name"))}</th><th>${esc(t("type"))}</th><th>${esc(t("size"))}</th><th></th></tr></thead><tbody>${payload.entries.map((entry) => {
        const open = entry.type === "directory"
          ? `<button type="button" data-dir="${esc(entry.path)}">${esc(t("open"))}</button>`
          : `<button type="button" data-text="${esc(entry.path)}" ${entry.protected ? "disabled" : ""}>${esc(t("text"))}</button>`;
        return `<tr><td>${esc(entry.name)}${entry.protected ? ` <span class='muted'>${esc(t("protected"))}</span>` : ""}</td><td>${esc(entry.type)}</td><td>${esc(entry.size)}</td><td>${open}</td></tr>`;
      }).join("")}</tbody></table>`;
      byId("files").querySelectorAll("[data-dir]").forEach((button) => button.addEventListener("click", () => {
        byId("filePath").value = button.getAttribute("data-dir");
        listFiles();
      }));
      byId("files").querySelectorAll("[data-text]").forEach((button) => button.addEventListener("click", () => loadText(button.getAttribute("data-text"))));
    }

    async function loadText(path) {
      const payload = await api(`api/files/text?path=${encodeURIComponent(path)}`);
      if (!payload.ok) {
        byId("actionOutput").textContent = JSON.stringify(payload, null, 2);
        return;
      }
      currentTextPath = path;
      byId("fileText").value = payload.content;
      byId("fileText").classList.remove("hidden");
      byId("textActions").classList.remove("hidden");
      updateWriteControls();
    }

    async function saveText() {
      if (!currentTextPath) return;
      const payload = await api("api/files/text", {method: "PUT", json: {path: currentTextPath, content: byId("fileText").value}});
      byId("actionOutput").textContent = JSON.stringify(payload, null, 2);
    }

    async function makeDir() {
      if (!writeEnabled) return;
      const name = prompt(t("directoryPrompt"));
      if (!name) return;
      const payload = await api("api/files/mkdir", {method: "POST", json: {path: name, parents: true, exist_ok: true}});
      byId("actionOutput").textContent = JSON.stringify(payload, null, 2);
      listFiles();
    }

    async function uploadFile() {
      if (!writeEnabled) return;
      const file = byId("uploadFile").files[0];
      if (!file) return;
      const base = byId("filePath").value.replace(/\\/$/, "");
      const path = `${base}/${file.name}`.replace(/^\\/+/, "/");
      const response = await fetch(`api/files/upload?path=${encodeURIComponent(path)}&overwrite=false`, {
        method: "POST",
        headers: {"X-Admin-CSRF": csrfToken, "Content-Type": "application/octet-stream"},
        body: await file.arrayBuffer(),
      });
      const payload = await response.json();
      byId("actionOutput").textContent = JSON.stringify(payload, null, 2);
      listFiles();
    }

    byId("loginForm").addEventListener("submit", (event) => {
      event.preventDefault();
      login();
    });
    byId("refreshButton").addEventListener("click", refresh);
    byId("languageSelect").addEventListener("change", () => setLocale(byId("languageSelect").value));
    byId("loginLanguageSelect").addEventListener("change", () => setLocale(byId("loginLanguageSelect").value));
    byId("logoutButton").addEventListener("click", async () => {
      await api("api/logout", {method: "POST"});
      location.reload();
    });
    byId("restartButton").addEventListener("click", () => runAction("api/actions/restart-service", {service: byId("serviceSelect").value}));
    byId("reloadNginxButton").addEventListener("click", () => runAction("api/actions/reload-nginx", {}));
    byId("healthButton").addEventListener("click", () => runAction("api/actions/run-health-checks", {}));
    byId("postgresBackupButton").addEventListener("click", () => runAction("api/actions/force-postgres-backup", {}));
    byId("loadAuditButton").addEventListener("click", loadAudit);
    byId("listFilesButton").addEventListener("click", listFiles);
    byId("newDirButton").addEventListener("click", makeDir);
    byId("saveTextButton").addEventListener("click", saveText);
    byId("downloadButton").addEventListener("click", () => { if (currentTextPath) location.href = `api/files/download?path=${encodeURIComponent(currentTextPath)}`; });
    byId("uploadFile").addEventListener("change", uploadFile);
    applyI18n();
    updateWriteControls();
    if (!byId("app").classList.contains("hidden")) refresh();
  </script>
</body>
</html>
"""
    return page.replace("__LOGIN_CLASS__", "hidden" if authenticated else "").replace("__APP_CLASS__", "" if authenticated else "hidden")


class Handler(BaseHTTPRequestHandler):
    server_version = "dify-aio-admin/1.0"

    def setup(self) -> None:
        super().setup()
        timeout = parse_int(env("ADMIN_HTTP_TIMEOUT_SECONDS"), 30, minimum=1, maximum=600)
        self.request.settimeout(timeout)

    def log_message(self, fmt: str, *args: Any) -> None:
        path = urllib.parse.urlparse(self.path).path
        message = fmt % args
        sys.stdout.write("%s - %s\n" % (self.address_string(), message.replace(self.path, path)))
        sys.stdout.flush()

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, body: str, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_security_headers()
        self.end_headers()
        self.wfile.write(data)

    def send_security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")

    def send_file(self, path: Path, content_type: str) -> None:
        size = path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", content_disposition_attachment(path.name))
        self.send_security_headers()
        self.end_headers()
        with path.open("rb") as file:
            shutil.copyfileobj(file, self.wfile)

    def send_admin_error(self, exc: AdminError) -> None:
        payload = {"ok": False, "error": exc.message}
        payload.update(exc.extra)
        self.send_json(payload, status=exc.status)

    def parsed(self) -> tuple[str, dict[str, list[str]]]:
        parsed = urllib.parse.urlparse(self.path)
        return parsed.path, urllib.parse.parse_qs(parsed.query)

    def read_bytes(self, max_bytes: int) -> bytes:
        length = parse_int(self.headers.get("Content-Length"), 0, minimum=0, maximum=max_bytes + 1)
        if length > max_bytes:
            raise AdminError(413, "request body is too large", max_bytes=max_bytes)
        return self.rfile.read(length)

    def read_json(self) -> dict[str, Any]:
        body = self.read_bytes(MAX_JSON_BYTES)
        if not body:
            return {}
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("application/x-www-form-urlencoded"):
            parsed = urllib.parse.parse_qs(body.decode("utf-8", errors="replace"))
            return {key: values[-1] if values else "" for key, values in parsed.items()}
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise AdminError(400, "request body must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise AdminError(400, "request JSON must be an object")
        return payload

    def ensure_available(self) -> bool:
        if not admin_enabled():
            self.send_json({"ok": False, "error": "not found"}, status=404)
            return False
        if not admin_token():
            self.send_json({"ok": False, "error": "ADMIN_TOKEN must be set before enabling admin service"}, status=503)
            return False
        return True

    def cookie_auth(self) -> AuthContext | None:
        raw = self.headers.get("Cookie", "")
        if not raw:
            return None
        cookie = SimpleCookie()
        try:
            cookie.load(raw)
        except Exception:
            return None
        morsel = cookie.get(SESSION_COOKIE)
        if not morsel:
            return None
        return parse_session(morsel.value)

    def header_auth(self) -> AuthContext | None:
        expected = admin_token()
        auth = self.headers.get("Authorization", "")
        provided = ""
        if auth.startswith("Bearer "):
            provided = auth.removeprefix("Bearer ").strip()
        provided = provided or self.headers.get("X-Admin-Token", "").strip()
        if expected and provided and hmac.compare_digest(provided, expected):
            return AuthContext(kind="token", csrf_token="1")
        return None

    def remote_addr(self) -> str:
        return trusted_remote_addr(self.headers, self.client_address)

    def authenticate(self) -> AuthContext | None:
        return self.header_auth() or self.cookie_auth()

    def require_auth(self) -> AuthContext | None:
        auth = self.authenticate()
        if auth:
            return auth
        self.send_json(
            {
                "ok": False,
                "error": "unauthorized",
                "hint": "Send X-Admin-Token, Authorization: Bearer <token>, or sign in at /_admin/.",
            },
            status=401,
        )
        return None

    def require_csrf(self, auth: AuthContext) -> bool:
        provided = self.headers.get("X-Admin-CSRF", "") or self.headers.get("X-CSRF-Token", "")
        if auth.kind == "token":
            return True
        elif hmac.compare_digest(provided, auth.csrf_token):
            return True
        self.send_json({"ok": False, "error": "missing or invalid CSRF header"}, status=403)
        return False

    def cookie_secure_enabled(self) -> bool:
        mode = env("ADMIN_COOKIE_SECURE", "auto").strip().lower()
        if mode in {"1", "true", "yes", "on"}:
            return True
        if mode in {"0", "false", "no", "off"}:
            return False
        proto = self.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip().lower()
        return proto == "https"

    def set_session_cookie(self, value: str, expires_at: int) -> None:
        max_age = max(expires_at - int(time.time()), 0)
        secure = "; Secure" if self.cookie_secure_enabled() else ""
        # Delete the legacy path first: libcurl otherwise applies this expiry to the active cookie too.
        self.send_header(
            "Set-Cookie",
            f"{SESSION_COOKIE}=; Path=/_admin; Max-Age=0; HttpOnly; SameSite=Lax{secure}",
        )
        self.send_header(
            "Set-Cookie",
            f"{SESSION_COOKIE}={value}; Path=/_admin/; Max-Age={max_age}; HttpOnly; SameSite=Lax{secure}",
        )

    def clear_session_cookie(self) -> None:
        secure = "; Secure" if self.cookie_secure_enabled() else ""
        self.send_header("Set-Cookie", f"{SESSION_COOKIE}=; Path=/_admin/; Max-Age=0; HttpOnly; SameSite=Lax{secure}")
        self.send_header("Set-Cookie", f"{SESSION_COOKIE}=; Path=/_admin; Max-Age=0; HttpOnly; SameSite=Lax{secure}")

    def do_GET(self) -> None:
        path, query = self.parsed()
        if not self.ensure_available():
            return
        try:
            if path in {"", "/"}:
                self.send_text(html_index(bool(self.authenticate())), content_type="text/html; charset=utf-8")
                return
            auth = self.require_auth()
            if not auth:
                return
            if path == "/api/status":
                self.send_json(status_payload(auth))
            elif path == "/api/actions":
                self.send_json(actions_payload())
            elif path == "/api/audit":
                self.send_json(audit_payload(query))
            elif path == "/api/files/list":
                self.send_json(files_list_payload(query))
            elif path == "/api/files/text":
                self.send_json(read_text_payload(query))
            elif path == "/api/files/download":
                file_path, content_type = download_file(query)
                self.send_file(file_path, content_type)
            else:
                self.send_json({"ok": False, "error": "not found"}, status=404)
        except AdminError as exc:
            self.send_admin_error(exc)
        except OSError as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=500)

    def do_POST(self) -> None:
        path, query = self.parsed()
        if not self.ensure_available():
            return
        try:
            if path == "/api/login":
                remote_addr = self.remote_addr()
                retry_after = login_retry_after(remote_addr)
                if retry_after:
                    audit_event(
                        "login",
                        False,
                        "cookie",
                        "login",
                        {"remote_addr": remote_addr, "reason": "rate-limited", "retry_after_seconds": retry_after},
                    )
                    self.send_json({"ok": False, "error": "rate limited", "retry_after_seconds": retry_after}, status=429)
                    return
                payload = self.read_json()
                token = str(payload.get("token", ""))
                if not hmac.compare_digest(token, admin_token()):
                    record_login_failure(remote_addr)
                    audit_event(
                        "login",
                        False,
                        "cookie",
                        "login",
                        {"remote_addr": remote_addr, "reason": "invalid-token"},
                    )
                    self.send_json({"ok": False, "error": "invalid token"}, status=401)
                    return
                clear_login_failures(remote_addr)
                cookie_value, csrf_token, expires_at = make_session()
                body = json.dumps({"ok": True, "csrf_token": csrf_token, "expires_at": expires_at}, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_security_headers()
                self.set_session_cookie(cookie_value, expires_at)
                self.end_headers()
                self.wfile.write(body)
                audit_event("login", True, "cookie", "login", {"remote_addr": remote_addr})
                return

            auth = self.require_auth()
            if not auth or not self.require_csrf(auth):
                return
            if path == "/api/logout":
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.clear_session_cookie()
                body = b'{"ok":true}\n'
                self.send_header("Content-Length", str(len(body)))
                self.send_security_headers()
                self.end_headers()
                self.wfile.write(body)
                audit_event("logout", True, auth.kind)
                return

            if path == "/api/files/upload":
                body = self.read_bytes(upload_limit_bytes())
                self.send_json(upload_payload(query.get("path", [""])[0], body, auth))
                return

            payload = self.read_json()
            if path == "/api/actions/restart-service":
                self.send_json(restart_service(payload, auth))
            elif path == "/api/actions/reload-nginx":
                self.send_json(reload_nginx(payload, auth))
            elif path == "/api/actions/run-health-checks":
                self.send_json(run_health_checks(payload, auth))
            elif path == "/api/actions/force-postgres-backup":
                self.send_json(force_postgres_backup(payload, auth))
            elif path == "/api/actions/ensure-app-api-token":
                self.send_json(ensure_app_api_token(payload, auth))
            elif path == "/api/actions/ensure-plugin-installed-from-cache":
                self.send_json(ensure_plugin_installed_from_cache(payload, auth))
            elif path == "/api/actions/set-provider-model-read-timeout":
                self.send_json(set_provider_model_read_timeout(payload, auth))
            elif path == "/api/files/mkdir":
                self.send_json(mkdir_payload(payload, auth))
            else:
                self.send_json({"ok": False, "error": "not found"}, status=404)
        except AdminError as exc:
            self.send_admin_error(exc)

    def do_PUT(self) -> None:
        path, _query = self.parsed()
        if not self.ensure_available():
            return
        try:
            auth = self.require_auth()
            if not auth or not self.require_csrf(auth):
                return
            payload = self.read_json()
            if path == "/api/files/text":
                self.send_json(write_text_payload(payload, auth))
            else:
                self.send_json({"ok": False, "error": "not found"}, status=404)
        except AdminError as exc:
            self.send_admin_error(exc)

    def do_PATCH(self) -> None:
        path, _query = self.parsed()
        if not self.ensure_available():
            return
        try:
            auth = self.require_auth()
            if not auth or not self.require_csrf(auth):
                return
            payload = self.read_json()
            if path == "/api/files/rename":
                self.send_json(rename_payload(payload, auth))
            else:
                self.send_json({"ok": False, "error": "not found"}, status=404)
        except AdminError as exc:
            self.send_admin_error(exc)

    def do_DELETE(self) -> None:
        path, _query = self.parsed()
        if not self.ensure_available():
            return
        try:
            auth = self.require_auth()
            if not auth or not self.require_csrf(auth):
                return
            payload = self.read_json()
            if path == "/api/files/delete":
                self.send_json(delete_payload(payload, auth))
            else:
                self.send_json({"ok": False, "error": "not found"}, status=404)
        except AdminError as exc:
            self.send_admin_error(exc)


def main() -> None:
    host = env("ADMIN_HOST", "127.0.0.1")
    port = parse_int(env("ADMIN_PORT"), 8082, minimum=1, maximum=65535)
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"[dify-aio-admin] listening on http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
