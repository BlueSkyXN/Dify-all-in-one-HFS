#!/usr/bin/env bash
set -euo pipefail

BASE_URL=${1:-${HF_SPACE_URL:-https://blueskyxn-dify-all-in-one.hf.space}}
BASE_URL=${BASE_URL%/}
OPS_TOKEN=${OPS_TOKEN:-}
ADMIN_TOKEN=${ADMIN_TOKEN:-}
SMOKE_ADMIN_ENABLED=${SMOKE_ADMIN_ENABLED:-${ADMIN_ENABLED:-false}}
SMOKE_ADMIN_ACTIONS=${SMOKE_ADMIN_ACTIONS:-false}
SMOKE_WEBSSH_ENABLED=${SMOKE_WEBSSH_ENABLED:-${WEBSSH_ENABLED:-false}}
SMOKE_RETRIES=${SMOKE_RETRIES:-30}
SMOKE_DELAY=${SMOKE_DELAY:-5}

tmp_body=$(mktemp)
tmp_headers=$(mktemp)
tmp_cookie=$(mktemp)
trap 'rm -f "$tmp_body" "$tmp_headers" "$tmp_cookie"' EXIT

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

check_ops_cookie_migration() {
  local status
  if [ -z "$OPS_TOKEN" ]; then
    printf 'SKIP ops-cookie-migration: OPS_TOKEN is not set\n'
    return
  fi

  status=$(curl -sS -o "$tmp_body" -w '%{http_code}' --max-time 30 \
    -c "$tmp_cookie" \
    --get --data-urlencode "token=$OPS_TOKEN" \
    "$BASE_URL/_ops/" || true)
  if [ "$status" != "303" ]; then
    printf 'FAIL ops-cookie-query-redirect: expected HTTP 303, got %s\n' "$status" >&2
    sed -n '1,80p' "$tmp_body" >&2 || true
    exit 1
  fi

  status=$(curl -sS -o "$tmp_body" -w '%{http_code}' --max-time 30 \
    -b "$tmp_cookie" \
    "$BASE_URL/_ops/" || true)
  if [ "$status" != "200" ]; then
    printf 'FAIL ops-cookie-dashboard: expected HTTP 200, got %s\n' "$status" >&2
    sed -n '1,80p' "$tmp_body" >&2 || true
    exit 1
  fi
  if grep -Fq "$OPS_TOKEN" "$tmp_body"; then
    printf 'FAIL ops-cookie-dashboard: OPS_TOKEN is still present in dashboard HTML\n' >&2
    exit 1
  fi
  printf 'PASS ops-cookie-migration: query token redirects to cookie-backed dashboard\n'
}

check_admin() {
  local label=$1
  local path=$2
  local status
  local attempt

  if [ -z "$ADMIN_TOKEN" ]; then
    printf 'FAIL %s: ADMIN_TOKEN is not set\n' "$label" >&2
    exit 1
  fi

  for attempt in $(seq 1 "$SMOKE_RETRIES"); do
    status=$(curl -sS -o "$tmp_body" -w '%{http_code}' --max-time 30 \
      -H "X-Admin-Token: $ADMIN_TOKEN" \
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

check_admin_action() {
  local label="admin-run-health-checks"
  local status

  if [ "$SMOKE_ADMIN_ACTIONS" != "true" ]; then
    printf 'SKIP %s: SMOKE_ADMIN_ACTIONS is not true\n' "$label"
    return
  fi

  status=$(curl -sS -o "$tmp_body" -w '%{http_code}' --max-time 60 \
    -H "X-Admin-Token: $ADMIN_TOKEN" \
    -H "X-Admin-CSRF: smoke" \
    -H "Content-Type: application/json" \
    -d '{"confirm":true}' \
    "$BASE_URL/_admin/api/actions/run-health-checks" || true)

  if [ "$status" = "200" ]; then
    printf 'PASS %s: HTTP %s\n' "$label" "$status"
    return
  fi

  printf 'FAIL %s: expected HTTP 200, got %s\n' "$label" "$status" >&2
  sed -n '1,80p' "$tmp_body" >&2 || true
  exit 1
}

check_webssh() {
  local label=$1
  local expected=$2
  local token=$3
  local status
  local attempt

  for attempt in $(seq 1 "$SMOKE_RETRIES"); do
    if [ -n "$token" ]; then
      status=$(curl -sS -o "$tmp_body" -w '%{http_code}' --max-time 30 \
        -H "X-Admin-Token: $token" \
        "$BASE_URL/_admin/terminal/" || true)
    else
      status=$(curl -sS -o "$tmp_body" -w '%{http_code}' --max-time 30 \
        "$BASE_URL/_admin/terminal/" || true)
    fi
    if [ "$status" = "$expected" ]; then
      printf 'PASS %s: HTTP %s\n' "$label" "$status"
      return
    fi
    if [ "$attempt" != "$SMOKE_RETRIES" ]; then
      printf 'WAIT %s: expected HTTP %s, got %s (%s/%s)\n' \
        "$label" "$expected" "$status" "$attempt" "$SMOKE_RETRIES" >&2
      sleep "$SMOKE_DELAY"
    fi
  done

  printf 'FAIL %s: expected HTTP %s, got %s\n' "$label" "$expected" "$status" >&2
  sed -n '1,80p' "$tmp_body" >&2 || true
  exit 1
}

check_space_frame_headers() {
  local label="space-frame-headers"
  local url="$BASE_URL/apps"
  local status
  local attempt

  for attempt in $(seq 1 "$SMOKE_RETRIES"); do
    status=$(curl -sS -D "$tmp_headers" -o "$tmp_body" -w '%{http_code}' --max-time 30 "$url" || true)
    if [ "$status" = "200" ]; then
      break
    fi
    if [ "$attempt" != "$SMOKE_RETRIES" ]; then
      printf 'WAIT %s: expected HTTP 200, got %s (%s/%s)\n' "$label" "$status" "$attempt" "$SMOKE_RETRIES" >&2
      sleep "$SMOKE_DELAY"
    fi
  done

  if [ "$status" != "200" ]; then
    printf 'FAIL %s: expected HTTP 200, got %s\n' "$label" "$status" >&2
    sed -n '1,40p' "$tmp_body" >&2 || true
    exit 1
  fi

  if grep -qi '^x-frame-options:' "$tmp_headers"; then
    printf 'FAIL %s: X-Frame-Options blocks Hugging Face iframe embedding\n' "$label" >&2
    grep -i '^x-frame-options:' "$tmp_headers" >&2 || true
    exit 1
  fi

  if ! grep -qi '^content-security-policy:.*frame-ancestors' "$tmp_headers"; then
    printf 'FAIL %s: missing Content-Security-Policy frame-ancestors\n' "$label" >&2
    sed -n '1,40p' "$tmp_headers" >&2 || true
    exit 1
  fi

  if ! grep -qi '^content-security-policy:.*https://huggingface\.co' "$tmp_headers"; then
    printf 'FAIL %s: frame-ancestors must allow https://huggingface.co\n' "$label" >&2
    grep -i '^content-security-policy:' "$tmp_headers" >&2 || true
    exit 1
  fi

  printf 'PASS %s: iframe headers allow Hugging Face Space embedding\n' "$label"
}

check_status "web-root" "$BASE_URL/" "200"
check_space_frame_headers
check_status "nginx-health" "$BASE_URL/nginx-health" "200"
check_status "ops-healthz" "$BASE_URL/healthz" "200"
if [ "$SMOKE_ADMIN_ENABLED" = "true" ]; then
  check_status "admin-root" "$BASE_URL/_admin/" "200"
  check_admin "admin-status" "/_admin/api/status"
  check_admin "admin-actions" "/_admin/api/actions"
  check_admin "admin-audit" "/_admin/api/audit?limit=5"
  check_admin_action
  if [ "$SMOKE_WEBSSH_ENABLED" = "true" ]; then
    check_webssh "webssh-terminal-unauthorized" "401" ""
    check_webssh "webssh-terminal" "200" "$ADMIN_TOKEN"
  else
    check_webssh "webssh-disabled" "404" ""
  fi
else
  check_status "admin-disabled" "$BASE_URL/_admin/" "404"
  check_webssh "webssh-disabled" "404" ""
fi
check_status "setup-api" "$BASE_URL/console/api/setup" "200"
check_status "init-api" "$BASE_URL/console/api/init" "200"
check_ops "ops-health" "/_ops/health"
check_ops "ops-system" "/_ops/system"
check_ops "ops-metrics" "/_ops/metrics"
check_ops "ops-errors" "/_ops/errors"
check_ops_cookie_migration
