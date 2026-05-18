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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


STARTED_AT = time.time()
LOG_DIR = Path("/data/logs")
SUPERVISOR_CONFIG = "/etc/supervisor/conf.d/supervisord.conf"

SERVICE_LOGS = {
    "supervisord": "supervisord.log",
    "postgres": "postgres.log",
    "postgres.err": "postgres.err",
    "redis": "redis.log",
    "redis.err": "redis.err",
    "plugin-daemon": "plugin-daemon.log",
    "plugin-daemon.err": "plugin-daemon.err",
    "dify-api": "dify-api.log",
    "dify-api.err": "dify-api.err",
    "dify-worker": "dify-worker.log",
    "dify-worker.err": "dify-worker.err",
    "dify-beat": "dify-beat.log",
    "dify-beat.err": "dify-beat.err",
    "nginx": "nginx.log",
    "ops-service": "ops-service.log",
    "ops-service.err": "ops-service.err",
}

SAFE_CONFIG_KEYS = [
    "DIFY_VERSION",
    "DEPLOY_ENV",
    "PUBLIC_URL",
    "SPACE_HOST",
    "SPACE_ID",
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


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


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


def run_cmd(args: list[str], timeout: float = 3.0) -> dict[str, Any]:
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
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
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
            "stdout": (exc.stdout or "").strip(),
            "stderr": f"timeout after {timeout}s",
            "duration_ms": round((time.time() - started) * 1000),
        }


def http_check(name: str, url: str, timeout: float = 3.0) -> dict[str, Any]:
    started = time.time()
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "dify-aio-ops/1.0"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=timeout) as response:
            body = response.read(256).decode("utf-8", errors="replace")
            return {
                "name": name,
                "ok": 200 <= response.status < 500,
                "status": response.status,
                "duration_ms": round((time.time() - started) * 1000),
                "sample": body,
            }
    except urllib.error.HTTPError as exc:
        body = exc.read(256).decode("utf-8", errors="replace")
        return {
            "name": name,
            "ok": exc.code < 500,
            "status": exc.code,
            "duration_ms": round((time.time() - started) * 1000),
            "sample": body,
        }
    except Exception as exc:
        return {
            "name": name,
            "ok": False,
            "status": None,
            "duration_ms": round((time.time() - started) * 1000),
            "error": str(exc),
        }


def tcp_check(name: str, host: str, port: int, timeout: float = 2.0) -> dict[str, Any]:
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


def supervisor_status() -> dict[str, Any]:
    result = run_cmd(["supervisorctl", "-c", SUPERVISOR_CONFIG, "status"], timeout=5.0)
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
    result = run_cmd(args, timeout=3.0)
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
    result = run_cmd(args, timeout=3.0)
    return {"name": "postgres", **result}


def health_payload(public: bool = False) -> dict[str, Any]:
    checks = [
        postgres_check(),
        redis_check(),
        tcp_check("plugin-daemon-tcp", "127.0.0.1", parse_int(env("PLUGIN_DAEMON_PORT"), 5002)),
        tcp_check("sandbox-tcp", "127.0.0.1", parse_int(env("SANDBOX_PORT"), 8194)),
        http_check("dify-api-health", "http://127.0.0.1:5001/health"),
        http_check("dify-web", "http://127.0.0.1:3000/apps"),
        http_check("nginx", "http://127.0.0.1:7860/nginx-health"),
    ]
    setup = http_check("dify-setup", "http://127.0.0.1:5001/console/api/setup")
    init = http_check("dify-init", "http://127.0.0.1:5001/console/api/init")
    checks.extend([setup, init])

    payload: dict[str, Any] = {
        "ok": all(check["ok"] for check in checks),
        "uptime_seconds": int(time.time() - STARTED_AT),
        "checks": checks,
    }
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
    }


def tail_file(path: Path, lines: int) -> str:
    if not path.exists():
        return ""
    try:
        data = path.read_bytes()
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


def errors_payload() -> dict[str, Any]:
    matches = []
    for service, filename in SERVICE_LOGS.items():
        path = LOG_DIR / filename
        if not path.exists():
            continue
        for line in tail_file(path, 300).splitlines():
            if any(pattern in line for pattern in ERROR_PATTERNS):
                matches.append({"service": service, "line": line})
    return {"ok": not matches, "matches": matches[-200:]}


def html_index(token: str) -> str:
    token_qs = urllib.parse.urlencode({"token": token})
    links = [
        ("Health", f"health?{token_qs}"),
        ("Supervisor Status", f"status?{token_qs}"),
        ("Config Summary", f"config?{token_qs}"),
        ("Version", f"version?{token_qs}"),
        ("Recent Errors", f"errors?{token_qs}"),
        ("API Logs", f"logs?service=dify-api&lines=120&token={urllib.parse.quote(token)}"),
    ]
    items = "\n".join(f'<li><a href="{html.escape(url)}">{html.escape(label)}</a></li>' for label, url in links)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Dify All-in-One Ops</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; line-height: 1.5; }}
    code {{ background: #f3f4f6; padding: 2px 4px; border-radius: 4px; }}
    li {{ margin: 8px 0; }}
  </style>
</head>
<body>
  <h1>Dify All-in-One Ops</h1>
  <p>This is a read-only diagnostics surface for the local all-in-one runtime.</p>
  <ul>{items}</ul>
  <p>For CLI use, prefer <code>X-Ops-Token</code> or <code>Authorization: Bearer ...</code> instead of query tokens.</p>
</body>
</html>
"""


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
        elif path == "/config":
            self.send_json({"ok": True, "config": config_payload()})
        elif path == "/version":
            self.send_json({"ok": True, "version": version_payload()})
        elif path == "/logs":
            payload = logs_payload(query)
            self.send_json(payload, status=200 if payload["ok"] else 404)
        elif path == "/errors":
            self.send_json(errors_payload())
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
