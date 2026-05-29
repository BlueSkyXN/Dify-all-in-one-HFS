#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

errors=0

fail() {
  printf 'FAIL hfs-contract: %s\n' "$1" >&2
  errors=$((errors + 1))
}

require_file() {
  local path=$1
  if [ ! -f "$path" ]; then
    fail "missing required file: $path"
  fi
}

require_grep() {
  local pattern=$1
  local path=$2
  local message=$3
  if ! grep -Eq "$pattern" "$path"; then
    fail "$message"
  fi
}

frontmatter_value() {
  local key=$1
  awk -v key="$key" '
    NR == 1 && $0 == "---" { in_yaml = 1; next }
    in_yaml && $0 == "---" { exit }
    in_yaml {
      split($0, parts, ":")
      if (parts[1] == key) {
        sub("^[^:]+:[[:space:]]*", "", $0)
        print $0
      }
    }
  ' README.md | tail -n 1
}

require_file README.md
require_file Dockerfile
require_file docker/nginx.conf
require_file docker/entrypoint.sh
require_file docker/supervisord.conf
require_file docker/ops_service.py
require_file docker/admin_service.py
require_file docker/healthcheck.sh
require_file scripts/hf-space-smoke.sh
require_file docs/hfs-alignment.md
require_file hfs-dev.toml

python3 - "$repo_root" <<'PY'
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

root = Path(sys.argv[1])
manifest = tomllib.loads((root / "hfs-dev.toml").read_text(encoding="utf-8"))

expected = {
    "schema_version": 1,
    "standard": "hfs-dev",
    "pattern": "A",
    "runtime_mode": "image-assembly",
    "space_root_mode": "repo-root",
    "hfs_dir": ".",
    "public_port": 7860,
    "release_pin_required": True,
}

failures: list[str] = []
for key, value in expected.items():
    if manifest.get(key) != value:
        failures.append(f"hfs-dev.toml {key} must be {value!r}, got {manifest.get(key)!r}")

release_pin_surfaces = manifest.get("release_pin_surfaces")
if not isinstance(release_pin_surfaces, list) or not release_pin_surfaces:
    failures.append("hfs-dev.toml release_pin_surfaces must be a non-empty list")

required_files = manifest.get("required_files")
if not isinstance(required_files, list) or not required_files:
    failures.append("hfs-dev.toml required_files must be a non-empty list")
else:
    for rel_path in required_files:
        if not isinstance(rel_path, str) or not (root / rel_path).exists():
            failures.append(f"hfs-dev.toml required file is missing: {rel_path!r}")

if failures:
    for failure in failures:
        print(f"FAIL hfs-contract: {failure}", file=sys.stderr)
    raise SystemExit(1)
PY

sdk=$(frontmatter_value sdk)
app_port=$(frontmatter_value app_port)
if [ "$sdk" != "docker" ]; then
  fail "README.md frontmatter must set sdk: docker"
fi
if [ -z "$app_port" ]; then
  fail "README.md frontmatter must set app_port"
fi

docker_expose=$(awk 'toupper($1) == "EXPOSE" { print $2; exit }' Dockerfile)
nginx_listen=$(awk '
  $1 == "listen" {
    value = $2
    gsub(";", "", value)
    split(value, parts, ":")
    print parts[length(parts)]
    exit
  }
' docker/nginx.conf)

if [ -n "$app_port" ] && [ "$docker_expose" != "$app_port" ]; then
  fail "Dockerfile EXPOSE ($docker_expose) must match README.md app_port ($app_port)"
fi
if [ -n "$app_port" ] && [ "$nginx_listen" != "$app_port" ]; then
  fail "docker/nginx.conf listen ($nginx_listen) must match README.md app_port ($app_port)"
fi

if [ -f cloud/hfs/README.md ] || [ -f cloud/hfs/Dockerfile ]; then
  fail "Pattern A repo must keep Space root at repo root, not cloud/hfs/"
fi

require_grep 'Pattern A: HFS Port Repository' docs/hfs-alignment.md \
  "docs/hfs-alignment.md must declare Pattern A"
require_grep 'Runtime mode: image-assembly' docs/hfs-alignment.md \
  "docs/hfs-alignment.md must declare image-assembly runtime mode"
require_grep 'Space root: repo root' docs/hfs-alignment.md \
  "docs/hfs-alignment.md must declare repo root as Space root"

require_grep '^ARG DIFY_VERSION=' Dockerfile \
  "Dockerfile must expose DIFY_VERSION build input"
require_grep '^ARG DIFY_API_IMAGE=' Dockerfile \
  "Dockerfile must expose DIFY_API_IMAGE build input"
require_grep '^ARG DIFY_WEB_IMAGE=' Dockerfile \
  "Dockerfile must expose DIFY_WEB_IMAGE build input"
require_grep '^ARG PLUGIN_DAEMON_IMAGE=' Dockerfile \
  "Dockerfile must expose PLUGIN_DAEMON_IMAGE build input"
require_grep '^ARG SANDBOX_IMAGE=' Dockerfile \
  "Dockerfile must expose SANDBOX_IMAGE build input"

require_grep '^local/$|^\*\*/local/$' .dockerignore \
  ".dockerignore must exclude local/ from Docker build context"
require_grep '^\.env\.local$' .dockerignore \
  ".dockerignore must exclude .env.local"
require_grep '^\*\.secret$' .dockerignore \
  ".dockerignore must exclude *.secret"
require_grep '^\*\.key$' .dockerignore \
  ".dockerignore must exclude *.key"
require_grep '^\*\.pem$' .dockerignore \
  ".dockerignore must exclude *.pem"

require_grep '/nginx-health' scripts/hf-space-smoke.sh \
  "smoke script must check /nginx-health"
require_grep '/healthz' scripts/hf-space-smoke.sh \
  "smoke script must check /healthz"
require_grep '/_ops/health' scripts/hf-space-smoke.sh \
  "smoke script must check /_ops/health"
require_grep 'web-root' scripts/hf-space-smoke.sh \
  "smoke script must check the web root"

if [ "$errors" -gt 0 ]; then
  exit 1
fi

printf 'PASS hfs-contract: Pattern A image-assembly contract is structurally valid\n'
