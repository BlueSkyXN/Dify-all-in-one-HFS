#!/usr/bin/env bash
set -euo pipefail

is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

run_placeholder() {
  local status=$1
  local message=$2
  exec python3 - "$WEBSSH_HOST" "$WEBSSH_PORT" "$status" "$message" <<'PY_PLACEHOLDER'
from __future__ import annotations

import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


host, port, status, message = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = (message + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.do_GET()


print(f"[dify-aio-webssh] placeholder listening on http://{host}:{port}: {message}", flush=True)
ThreadingHTTPServer((host, port), Handler).serve_forever()
PY_PLACEHOLDER
}

WEBSSH_HOST=${WEBSSH_HOST:-127.0.0.1}
WEBSSH_PORT=${WEBSSH_PORT:-7681}
WEBSSH_SHELL=${WEBSSH_SHELL:-/bin/bash}
WEBSSH_MAX_CLIENTS=${WEBSSH_MAX_CLIENTS:-1}

if ! is_true "${WEBSSH_ENABLED:-false}"; then
  run_placeholder 404 "web terminal is disabled"
fi

if ! command -v ttyd >/dev/null 2>&1; then
  run_placeholder 503 "WEBSSH_ENABLED=true but ttyd is not installed in this image"
fi

exec ttyd \
  --interface "$WEBSSH_HOST" \
  --port "$WEBSSH_PORT" \
  --max-clients "$WEBSSH_MAX_CLIENTS" \
  --writable \
  "$WEBSSH_SHELL"
