#!/usr/bin/env bash
set -euo pipefail

BASE_URL=${1:-${ADMIN_SMOKE_BASE_URL:-http://localhost:8080}}
BASE_URL=${BASE_URL%/}
ADMIN_EXPECTED_ENABLED=${ADMIN_EXPECTED_ENABLED:-${ADMIN_ENABLED:-false}}
ADMIN_FILES_EXPECTED_ENABLED=${ADMIN_FILES_EXPECTED_ENABLED:-${ADMIN_FILES_ENABLED:-false}}
ADMIN_SMOKE_ACTIONS=${ADMIN_SMOKE_ACTIONS:-false}
ADMIN_TOKEN=${ADMIN_TOKEN:-}

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

require_admin_token() {
  if [ -n "$ADMIN_TOKEN" ]; then
    return
  fi
  printf 'FAIL admin-enabled: ADMIN_TOKEN is required when ADMIN_EXPECTED_ENABLED=true\n' >&2
  exit 1
}

if [ "$ADMIN_EXPECTED_ENABLED" != "true" ]; then
  expect_status "admin-disabled-root" "404" "$BASE_URL/_admin/"
  expect_status "admin-disabled-status" "404" "$BASE_URL/_admin/api/status"
  exit 0
fi

require_admin_token

expect_status "admin-root" "200" "$BASE_URL/_admin/"
expect_status "admin-status-unauthorized" "401" "$BASE_URL/_admin/api/status"
expect_status "admin-status-bad-token" "401" -H "X-Admin-Token: invalid-admin-token" "$BASE_URL/_admin/api/status"
expect_status "admin-status" "200" -H "X-Admin-Token: $ADMIN_TOKEN" "$BASE_URL/_admin/api/status"
expect_status "admin-actions" "200" -H "X-Admin-Token: $ADMIN_TOKEN" "$BASE_URL/_admin/api/actions"
expect_status "admin-audit" "200" -H "X-Admin-Token: $ADMIN_TOKEN" "$BASE_URL/_admin/api/audit?limit=5"
expect_status "admin-action-missing-csrf" "403" \
  -X POST \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"confirm":true}' \
  "$BASE_URL/_admin/api/actions/run-health-checks"
expect_status "admin-action-missing-confirm" "400" \
  -X POST \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "X-Admin-CSRF: smoke" \
  -H "Content-Type: application/json" \
  -d '{}' \
  "$BASE_URL/_admin/api/actions/run-health-checks"

if [ "$ADMIN_SMOKE_ACTIONS" = "true" ]; then
  expect_status "admin-run-health-checks" "200" \
    -X POST \
    -H "X-Admin-Token: $ADMIN_TOKEN" \
    -H "X-Admin-CSRF: smoke" \
    -H "Content-Type: application/json" \
    -d '{"confirm":true}' \
    "$BASE_URL/_admin/api/actions/run-health-checks"
else
  printf 'SKIP admin-run-health-checks: ADMIN_SMOKE_ACTIONS is not true\n'
fi

if [ "$ADMIN_FILES_EXPECTED_ENABLED" = "true" ]; then
  expect_status "admin-files-root-escape" "400" \
    -H "X-Admin-Token: $ADMIN_TOKEN" \
    "$BASE_URL/_admin/api/files/list?path=.."
else
  expect_status "admin-files-disabled" "404" \
    -H "X-Admin-Token: $ADMIN_TOKEN" \
    "$BASE_URL/_admin/api/files/list?path=/"
fi
