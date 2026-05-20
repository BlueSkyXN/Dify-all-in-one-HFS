#!/usr/bin/env bash
set -euo pipefail

BASE_URL=${1:-${WEBSSH_SMOKE_BASE_URL:-http://localhost:8080}}
BASE_URL=${BASE_URL%/}
ADMIN_EXPECTED_ENABLED=${ADMIN_EXPECTED_ENABLED:-${ADMIN_ENABLED:-false}}
WEBSSH_EXPECTED_ENABLED=${WEBSSH_EXPECTED_ENABLED:-${WEBSSH_ENABLED:-false}}
ADMIN_TOKEN=${ADMIN_TOKEN:-}
WEBSSH_SMOKE_RETRIES=${WEBSSH_SMOKE_RETRIES:-10}
WEBSSH_SMOKE_DELAY=${WEBSSH_SMOKE_DELAY:-2}

tmp_body=$(mktemp)
trap 'rm -f "$tmp_body"' EXIT

curl_status() {
  curl -sS -o "$tmp_body" -w '%{http_code}' --max-time 30 "$@" || true
}

expect_status() {
  local label=$1
  local expected=$2
  shift 2
  local status
  status=$(curl_status "$@")
  if [ "$status" = "$expected" ]; then
    printf 'PASS %s: HTTP %s\n' "$label" "$status"
    return
  fi
  printf 'FAIL %s: expected HTTP %s, got %s\n' "$label" "$expected" "$status" >&2
  sed -n '1,80p' "$tmp_body" >&2 || true
  exit 1
}

expect_status_with_retry() {
  local label=$1
  local expected=$2
  shift 2
  local status attempt

  for attempt in $(seq 1 "$WEBSSH_SMOKE_RETRIES"); do
    status=$(curl_status "$@")
    if [ "$status" = "$expected" ]; then
      printf 'PASS %s: HTTP %s\n' "$label" "$status"
      return
    fi
    if [ "$attempt" != "$WEBSSH_SMOKE_RETRIES" ]; then
      printf 'WAIT %s: expected HTTP %s, got %s (%s/%s)\n' \
        "$label" "$expected" "$status" "$attempt" "$WEBSSH_SMOKE_RETRIES" >&2
      sleep "$WEBSSH_SMOKE_DELAY"
    fi
  done

  printf 'FAIL %s: expected HTTP %s, got %s\n' "$label" "$expected" "$status" >&2
  sed -n '1,80p' "$tmp_body" >&2 || true
  exit 1
}

require_admin_token() {
  if [ -n "$ADMIN_TOKEN" ]; then
    return
  fi
  printf 'FAIL webssh-enabled: ADMIN_TOKEN is required when WEBSSH_EXPECTED_ENABLED=true\n' >&2
  exit 1
}

if [ "$WEBSSH_EXPECTED_ENABLED" != "true" ]; then
  expect_status "webssh-disabled-terminal" "404" "$BASE_URL/_admin/terminal/"
  printf 'PASS webssh-disabled-default: terminal is not externally usable\n'
  exit 0
fi

if [ "$ADMIN_EXPECTED_ENABLED" != "true" ]; then
  printf 'FAIL webssh-enabled: ADMIN_EXPECTED_ENABLED must be true\n' >&2
  exit 1
fi

require_admin_token

expect_status "webssh-auth-api-unauthorized" "401" "$BASE_URL/_admin/api/auth/terminal"
expect_status "webssh-auth-api-bad-token" "401" \
  -H "X-Admin-Token: invalid-admin-token" \
  "$BASE_URL/_admin/api/auth/terminal"
expect_status "webssh-auth-api" "204" \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  "$BASE_URL/_admin/api/auth/terminal"
expect_status "webssh-terminal-unauthorized" "401" "$BASE_URL/_admin/terminal/"
expect_status "webssh-terminal-bad-token" "401" \
  -H "X-Admin-Token: invalid-admin-token" \
  "$BASE_URL/_admin/terminal/"
expect_status_with_retry "webssh-terminal" "200" \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  "$BASE_URL/_admin/terminal/"
