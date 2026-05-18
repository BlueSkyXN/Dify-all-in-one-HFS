#!/usr/bin/env bash
set -euo pipefail

BASE_URL=${1:-${HF_SPACE_URL:-https://blueskyxn-dify-all-in-one.hf.space}}
BASE_URL=${BASE_URL%/}
OPS_TOKEN=${OPS_TOKEN:-}
SMOKE_RETRIES=${SMOKE_RETRIES:-30}
SMOKE_DELAY=${SMOKE_DELAY:-5}

tmp_body=$(mktemp)
trap 'rm -f "$tmp_body"' EXIT

check_status() {
  local label=$1
  local url=$2
  local expected=$3
  local status
  local attempt

  for attempt in $(seq 1 "$SMOKE_RETRIES"); do
    status=$(curl -sS -L -o "$tmp_body" -w '%{http_code}' --max-time 30 "$url" || true)
    if [ "$status" = "$expected" ]; then
      printf 'PASS %s: HTTP %s\n' "$label" "$status"
      return
    fi
    if [ "$attempt" != "$SMOKE_RETRIES" ]; then
      printf 'WAIT %s: expected HTTP %s, got %s (%s/%s)\n' "$label" "$expected" "$status" "$attempt" "$SMOKE_RETRIES" >&2
      sleep "$SMOKE_DELAY"
    fi
  done

  printf 'FAIL %s: expected HTTP %s, got %s\n' "$label" "$expected" "$status" >&2
  sed -n '1,40p' "$tmp_body" >&2 || true
  exit 1
}

check_ops() {
  local label=$1
  local path=$2
  local status
  local attempt

  if [ -z "$OPS_TOKEN" ]; then
    printf 'SKIP %s: OPS_TOKEN is not set\n' "$label"
    return
  fi

  for attempt in $(seq 1 "$SMOKE_RETRIES"); do
    status=$(curl -sS -o "$tmp_body" -w '%{http_code}' --max-time 30 \
      -H "X-Ops-Token: $OPS_TOKEN" \
      "$BASE_URL$path" || true)
    if [ "$status" = "200" ]; then
      printf 'PASS %s: HTTP %s\n' "$label" "$status"
      return
    fi
    if [ "$attempt" != "$SMOKE_RETRIES" ]; then
      printf 'WAIT %s: expected HTTP 200, got %s (%s/%s)\n' "$label" "$status" "$attempt" "$SMOKE_RETRIES" >&2
      sleep "$SMOKE_DELAY"
    fi
  done

  printf 'FAIL %s: expected HTTP 200, got %s\n' "$label" "$status" >&2
  sed -n '1,80p' "$tmp_body" >&2 || true
  exit 1
}

check_status "web-root" "$BASE_URL/" "200"
check_status "nginx-health" "$BASE_URL/nginx-health" "200"
check_status "ops-healthz" "$BASE_URL/healthz" "200"
check_status "setup-api" "$BASE_URL/console/api/setup" "200"
check_status "init-api" "$BASE_URL/console/api/init" "200"
check_ops "ops-health" "/_ops/health"
check_ops "ops-errors" "/_ops/errors"
