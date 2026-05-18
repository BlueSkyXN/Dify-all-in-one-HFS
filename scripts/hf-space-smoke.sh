#!/usr/bin/env bash
set -euo pipefail

BASE_URL=${1:-${HF_SPACE_URL:-https://blueskyxn-dify-all-in-one.hf.space}}
BASE_URL=${BASE_URL%/}
OPS_TOKEN=${OPS_TOKEN:-}

tmp_body=$(mktemp)
trap 'rm -f "$tmp_body"' EXIT

check_status() {
  local label=$1
  local url=$2
  local expected=$3
  local status

  status=$(curl -sS -L -o "$tmp_body" -w '%{http_code}' --max-time 30 "$url" || true)
  if [ "$status" != "$expected" ]; then
    printf 'FAIL %s: expected HTTP %s, got %s\n' "$label" "$expected" "$status" >&2
    sed -n '1,40p' "$tmp_body" >&2 || true
    exit 1
  fi
  printf 'PASS %s: HTTP %s\n' "$label" "$status"
}

check_ops() {
  local label=$1
  local path=$2
  local status

  if [ -z "$OPS_TOKEN" ]; then
    printf 'SKIP %s: OPS_TOKEN is not set\n' "$label"
    return
  fi

  status=$(curl -sS -o "$tmp_body" -w '%{http_code}' --max-time 30 \
    -H "X-Ops-Token: $OPS_TOKEN" \
    "$BASE_URL$path" || true)
  if [ "$status" != "200" ]; then
    printf 'FAIL %s: expected HTTP 200, got %s\n' "$label" "$status" >&2
    sed -n '1,80p' "$tmp_body" >&2 || true
    exit 1
  fi
  printf 'PASS %s: HTTP %s\n' "$label" "$status"
}

check_status "web-root" "$BASE_URL/" "200"
check_status "nginx-health" "$BASE_URL/nginx-health" "200"
check_status "ops-healthz" "$BASE_URL/healthz" "200"
check_status "setup-api" "$BASE_URL/console/api/setup" "200"
check_status "init-api" "$BASE_URL/console/api/init" "200"
check_ops "ops-health" "/_ops/health"
check_ops "ops-errors" "/_ops/errors"
