#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '[dify-aio-hf] %s\n' "$*"
}

warn() {
  printf '[dify-aio-hf] WARNING: %s\n' "$*" >&2
}

shell_quote() {
  local s=${1:-}
  s=${s//\'/\'\\\'\'}
  printf "'%s'" "$s"
}

EXTERNAL_PLUGIN_STORAGE_LOCAL_ROOT=${PLUGIN_STORAGE_LOCAL_ROOT-}

source_defaults_env() {
  set -a
  # shellcheck disable=SC1091
  . /etc/dify/dify.env.runtime
  set +a
}

source_runtime_env() {
  source_defaults_env
  set -a
  if [ -f /data/config/generated.env ]; then
    # shellcheck disable=SC1091
    . /data/config/generated.env
  elif [ -f /etc/dify/generated.env ]; then
    # legacy fallback
    # shellcheck disable=SC1091
    . /etc/dify/generated.env
  fi
  set +a
}

default_plugin_storage_root() {
  local runtime_root=${RUNTIME_ROOT:-/tmp/dify-aio}
  local persist_root=${PERSIST_ROOT:-/persist}
  local active_file=${PERSIST_ACTIVE_FILE:-${runtime_root}/persist-active}
  local active=""
  if [ -f "$active_file" ]; then
    active=$(cat "$active_file" 2>/dev/null || true)
  fi
  if [ "$active" = "bucket" ] && [ -d "${persist_root}/plugin_daemon" ]; then
    printf '%s/plugin_daemon\n' "$persist_root"
  else
    printf '/data/plugin_daemon\n'
  fi
}

configure_plugin_storage_root() {
  local selected_root
  selected_root=$(default_plugin_storage_root)
  if [ -n "${EXTERNAL_PLUGIN_STORAGE_LOCAL_ROOT:-}" ]; then
    export PLUGIN_STORAGE_LOCAL_ROOT="$EXTERNAL_PLUGIN_STORAGE_LOCAL_ROOT"
    return
  fi
  if [ -z "${PLUGIN_STORAGE_LOCAL_ROOT:-}" ] || [ "${PLUGIN_STORAGE_LOCAL_ROOT:-}" = "/data/plugin_daemon" ]; then
    export PLUGIN_STORAGE_LOCAL_ROOT="$selected_root"
    if [ "$selected_root" != "/data/plugin_daemon" ]; then
      log "Using real plugin storage root ${selected_root} so plugin-daemon can list installed plugins after restart."
    fi
  fi
}

write_generated_env() {
  mkdir -p /data/config /data/secrets
  chmod 700 /data/config /data/secrets || true

  # Capture Space Settings / docker -e values first. If they are non-empty,
  # they override previously persisted generated values.
  source_defaults_env
  local provided_secret_key=${SECRET_KEY:-}
  local provided_plugin_daemon_key=${PLUGIN_DAEMON_KEY:-}
  local provided_plugin_inner_key=${PLUGIN_DIFY_INNER_API_KEY:-}
  local provided_code_execution_key=${CODE_EXECUTION_API_KEY:-}
  local provided_sandbox_key=${SANDBOX_API_KEY:-}
  local provided_agent_server_secret=${DIFY_AGENT_SERVER_SECRET_KEY:-}

  if [ -f /data/config/generated.env ]; then
    # shellcheck disable=SC1091
    . /data/config/generated.env
  fi

  local secret_key=${provided_secret_key:-${SECRET_KEY:-}}
  local plugin_daemon_key=${provided_plugin_daemon_key:-${PLUGIN_DAEMON_KEY:-}}
  local plugin_inner_key=${provided_plugin_inner_key:-${PLUGIN_DIFY_INNER_API_KEY:-}}
  local code_execution_key=${provided_code_execution_key:-${CODE_EXECUTION_API_KEY:-}}
  local sandbox_key=${provided_sandbox_key:-${SANDBOX_API_KEY:-}}
  local agent_server_secret=${provided_agent_server_secret:-${DIFY_AGENT_SERVER_SECRET_KEY:-}}

  [ -n "$secret_key" ] || secret_key="$(openssl rand -base64 42)"
  [ -n "$plugin_daemon_key" ] || plugin_daemon_key="$(openssl rand -base64 42)"
  [ -n "$plugin_inner_key" ] || plugin_inner_key="$(openssl rand -base64 42)"
  [ -n "$code_execution_key" ] || code_execution_key="$(openssl rand -base64 42)"
  [ -n "$sandbox_key" ] || sandbox_key="$code_execution_key"
  [ -n "$agent_server_secret" ] || agent_server_secret="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=')"

  cat > /data/config/generated.env <<EOF_GENERATED
export SECRET_KEY=$(shell_quote "$secret_key")
export PLUGIN_DAEMON_KEY=$(shell_quote "$plugin_daemon_key")
export PLUGIN_DIFY_INNER_API_KEY=$(shell_quote "$plugin_inner_key")
export INNER_API_KEY_FOR_PLUGIN=$(shell_quote "$plugin_inner_key")
export CODE_EXECUTION_API_KEY=$(shell_quote "$code_execution_key")
export SANDBOX_API_KEY=$(shell_quote "$sandbox_key")
export DIFY_AGENT_SERVER_SECRET_KEY=$(shell_quote "$agent_server_secret")
EOF_GENERATED
  chmod 600 /data/config/generated.env || true
}

warn_demo_defaults() {
  source_runtime_env
  if [ "${OPS_TOKEN:-}" = "dify_ops_demo_token" ]; then
    warn "OPS_TOKEN uses the demo default. Set a strong OPS_TOKEN for any shared or public Space."
  fi
  if [ "${DB_PASSWORD:-}" = "dify_demo_password" ] || [ "${REDIS_PASSWORD:-}" = "dify_redis_password" ]; then
    warn "Demo database or Redis passwords are active. Replace them outside local training demos."
  fi
}

validate_ident() {
  local name=$1
  local value=$2
  if [[ ! "$value" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    log "Invalid ${name}: '${value}'. Use a PostgreSQL-safe identifier like dify or dify_plugin."
    exit 1
  fi
}

sql_escape_literal() {
  printf "%s" "$1" | sed "s/'/''/g"
}

is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

external_postgres_enabled() {
  source_runtime_env
  is_true "${EXTERNAL_POSTGRES_ENABLED:-false}"
}

dir_has_entries() {
  [ -d "$1" ] && find "$1" -mindepth 1 -maxdepth 1 -print -quit | grep -q .
}

persist_writable() {
  local root=${PERSIST_ROOT:-/persist}
  [ -d "$root" ] || return 1
  touch "${root}/.dify-aio-writable-test" 2>/dev/null || return 1
  rm -f "${root}/.dify-aio-writable-test"
}

persist_mounted() {
  local root=${PERSIST_ROOT:-/persist}
  awk -v target="$root" '$5 == target { found = 1 } END { exit found ? 0 : 1 }' /proc/self/mountinfo
}

detect_persist_mode() {
  source_defaults_env
  case "${PERSIST_MODE:-auto}" in
    auto)
      if persist_mounted && persist_writable; then
        printf 'bucket\n'
      else
        printf 'legacy\n'
      fi
      ;;
    bucket|persist)
      if ! mkdir -p "${PERSIST_ROOT:-/persist}" 2>/dev/null; then
        log "PERSIST_MODE=${PERSIST_MODE} requires creatable or mounted PERSIST_ROOT=${PERSIST_ROOT:-/persist}."
        exit 1
      fi
      if ! persist_writable; then
        log "PERSIST_MODE=${PERSIST_MODE} requires writable PERSIST_ROOT=${PERSIST_ROOT:-/persist}."
        exit 1
      fi
      printf 'bucket\n'
      ;;
    none|legacy|data)
      printf 'legacy\n'
      ;;
    *)
      log "Invalid PERSIST_MODE=${PERSIST_MODE}. Use auto, bucket, or legacy."
      exit 1
      ;;
  esac
}

link_dir() {
  local source=$1
  local target=$2
  mkdir -p "$(dirname "$source")" "$target"

  if [ -L "$source" ]; then
    if [ "$(readlink "$source")" = "$target" ]; then
      return
    fi
    rm -f "$source"
  fi

  if [ -e "$source" ]; then
    if [ ! -d "$source" ]; then
      log "Cannot map ${source}: path exists and is not a directory."
      exit 1
    fi
    if dir_has_entries "$source" && ! dir_has_entries "$target"; then
      cp -a "${source}/." "$target/"
    elif dir_has_entries "$source" && dir_has_entries "$target"; then
      log "Both ${source} and ${target} contain files; using ${target} for persistence."
    fi
    rm -rf "$source"
  fi

  ln -s "$target" "$source"
}

configure_bucket_layout() {
  local persist_root=${PERSIST_ROOT:-/persist}
  local runtime_root=${RUNTIME_ROOT:-/tmp/dify-aio}
  mkdir -p \
    "$persist_root/postgres" \
    "$persist_root/config" \
    "$persist_root/dify/storage" \
    "$persist_root/plugin_daemon/plugin" \
    "$persist_root/plugin_daemon/assets" \
    "$persist_root/plugin_daemon/plugin_packages" \
    "$persist_root/postgres-backups" \
    "$runtime_root/logs" \
    "$runtime_root/run" \
    "$runtime_root/redis" \
    "$runtime_root/hf-cache" \
    "$runtime_root/plugin_cwd"

  mkdir -p /data /data/dify /data/plugin_daemon
  link_dir /data/postgres "$persist_root/postgres"
  link_dir /data/config "$persist_root/config"
  link_dir /data/dify/storage "$persist_root/dify/storage"
  link_dir /data/plugin_daemon/plugin "$persist_root/plugin_daemon/plugin"
  link_dir /data/plugin_daemon/assets "$persist_root/plugin_daemon/assets"
  link_dir /data/plugin_daemon/plugin_packages "$persist_root/plugin_daemon/plugin_packages"
  if is_true "${PLUGIN_CWD_PERSISTENCE:-false}"; then
    link_dir /data/plugin_daemon/cwd "$persist_root/plugin_daemon/cwd"
  else
    link_dir /data/plugin_daemon/cwd "$runtime_root/plugin_cwd"
  fi
  if is_true "${REDIS_PERSISTENCE:-false}"; then
    link_dir /data/redis "$persist_root/redis"
  else
    link_dir /data/redis "$runtime_root/redis"
  fi
  link_dir /data/logs "$runtime_root/logs"
  link_dir /data/run "$runtime_root/run"

  mkdir -p "$(dirname "${PERSIST_ACTIVE_FILE:-${runtime_root}/persist-active}")"
  printf 'bucket\n' > "${PERSIST_ACTIVE_FILE:-${runtime_root}/persist-active}"
  log "Using bucket-lite persistence: core state under ${persist_root}, scratch under ${runtime_root}."
}

configure_legacy_layout() {
  local runtime_root=${RUNTIME_ROOT:-/tmp/dify-aio}
  rm -f "${PERSIST_ACTIVE_FILE:-${runtime_root}/persist-active}" 2>/dev/null || true
}

prepare_dirs() {
  source_defaults_env
  mkdir -p /data "${RUNTIME_ROOT:-/tmp/dify-aio}" /conf /dependencies
  local mode
  mode=$(detect_persist_mode)
  if [ "$mode" = "bucket" ]; then
    configure_bucket_layout
  else
    configure_legacy_layout
  fi

  if ! mkdir -p \
    /data/postgres \
    /data/redis \
    /data/dify/storage \
    /data/plugin_daemon/cwd \
    /data/plugin_daemon/plugin \
    /data/plugin_daemon/plugin_packages \
    /data/plugin_daemon/assets \
    /data/config \
    /data/logs \
    /data/run/postgresql \
    /data/run/nginx/client_body \
    /data/run/nginx/proxy \
    /data/run/nginx/fastcgi \
    /data/run/nginx/uwsgi \
    /data/run/nginx/scgi \
    /conf \
    /dependencies; then
    log "Cannot create runtime directories. Check /data, /tmp, or the /persist bucket mount."
    exit 1
  fi

  if ! touch /data/.writable-test 2>/dev/null; then
    log "/data is not writable by UID $(id -u). Check the image permissions or volume settings."
    exit 1
  fi
  rm -f /data/.writable-test

  mkdir -p "${HF_HOME:-${RUNTIME_ROOT:-/tmp/dify-aio}/hf-cache}" "${HF_HUB_CACHE:-${HF_HOME:-${RUNTIME_ROOT:-/tmp/dify-aio}/hf-cache}/hub}"
  touch /dependencies/python-requirements.txt /dependencies/nodejs-requirements.txt || true
  chmod 700 /data/postgres /data/redis /data/config || true
  chmod 755 \
    /data \
    /data/logs \
    /data/run \
    /data/run/postgresql \
    /data/run/nginx \
    /data/run/nginx/client_body \
    /data/run/nginx/proxy \
    /data/run/nginx/fastcgi \
    /data/run/nginx/uwsgi \
    /data/run/nginx/scgi \
    /data/dify \
    /data/dify/storage \
    /data/plugin_daemon \
    /data/plugin_daemon/cwd \
    /data/plugin_daemon/plugin \
    /data/plugin_daemon/plugin_packages \
    /data/plugin_daemon/assets || true
}

render_redis_config() {
  source_runtime_env
  cat > /data/run/redis.conf <<EOF_REDIS
bind 127.0.0.1
port ${REDIS_PORT}
dir /data/redis
appendonly yes
protected-mode yes
timeout 0
tcp-keepalive 300
pidfile /data/run/redis.pid
logfile ""
EOF_REDIS
  if [ -n "${REDIS_PASSWORD:-}" ]; then
    printf 'requirepass %s\n' "$REDIS_PASSWORD" >> /data/run/redis.conf
  fi
  chmod 600 /data/run/redis.conf || true
}

redis_cli_args() {
  source_runtime_env
  printf -- '-h\n127.0.0.1\n-p\n%s\n' "${REDIS_PORT}"
}

redis_cli() {
  if [ -n "${REDIS_PASSWORD:-}" ]; then
    REDISCLI_AUTH="${REDIS_PASSWORD}" redis-cli "$@"
  else
    redis-cli "$@"
  fi
}

start_temp_redis() {
  source_runtime_env
  log "Starting temporary Redis for initialization..."
  /usr/bin/redis-server /data/run/redis.conf \
    --daemonize yes \
    --pidfile /data/run/redis-init.pid \
    --logfile /data/logs/redis-init.log

  local -a args
  mapfile -t args < <(redis_cli_args)
  for _ in $(seq 1 30); do
    if redis_cli "${args[@]}" ping 2>/dev/null | grep -q PONG; then
      return
    fi
    sleep 1
  done

  log "Temporary Redis did not become ready."
  exit 1
}

stop_temp_redis() {
  source_runtime_env
  log "Stopping temporary Redis..."
  local -a args
  mapfile -t args < <(redis_cli_args)
  redis_cli "${args[@]}" shutdown nosave >/data/logs/redis-init-stop.log 2>&1 || true
}

render_sandbox_config() {
  source_runtime_env
  local api_key=${SANDBOX_API_KEY:-${CODE_EXECUTION_API_KEY:-}}
  local enable_network=${SANDBOX_ENABLE_NETWORK:-false}
  local python_path=${SANDBOX_PYTHON_PATH:-/usr/local/bin/python3}
  local nodejs_path=${SANDBOX_NODEJS_PATH:-/usr/bin/node}
  local debug=false
  if [ "${SANDBOX_GIN_MODE:-release}" != "release" ]; then
    debug=true
  fi

  cat > /conf/config.yaml <<EOF_SANDBOX
app:
  port: ${SANDBOX_PORT:-8194}
  debug: ${debug}
  key: "${api_key}"
max_workers: ${SANDBOX_MAX_WORKERS:-4}
max_requests: ${SANDBOX_MAX_REQUESTS:-50}
worker_timeout: ${SANDBOX_WORKER_TIMEOUT:-15}
python_path: "${python_path}"
nodejs_path: "${nodejs_path}"
python_pip_mirror_url: "${PIP_MIRROR_URL:-}"
python_deps_update_interval: "${SANDBOX_PYTHON_DEPS_UPDATE_INTERVAL:-876000h}"
enable_network: ${enable_network}
enable_preload: false
log_path: "/data/logs"
allowed_syscalls: []
proxy:
  socks5: ''
  http: '${SANDBOX_HTTP_PROXY:-}'
  https: '${SANDBOX_HTTPS_PROXY:-}'
EOF_SANDBOX
  chmod 644 /conf/config.yaml || true
}

configure_postgres_files() {
  source_runtime_env
  chmod 700 /data/postgres 2>/dev/null || true

  if ! grep -q "dify all-in-one hf demo" /data/postgres/postgresql.conf 2>/dev/null; then
    cat >> /data/postgres/postgresql.conf <<EOF_PGCONF

# dify all-in-one hf demo
listen_addresses = '127.0.0.1'
port = ${DB_PORT}
max_connections = 200
shared_buffers = '128MB'
work_mem = '4MB'
maintenance_work_mem = '64MB'
effective_cache_size = '4096MB'
unix_socket_directories = '/data/run/postgresql'
EOF_PGCONF
  fi

  if ! grep -q "dify all-in-one hf demo" /data/postgres/pg_hba.conf 2>/dev/null; then
    cat >> /data/postgres/pg_hba.conf <<'EOF_PGHBA'

# dify all-in-one hf demo
local   all             all                                     trust
host    all             all             127.0.0.1/32            md5
host    all             all             ::1/128                 md5
EOF_PGHBA
  fi
  chmod 600 /data/postgres/postgresql.conf /data/postgres/pg_hba.conf || true
}

ensure_postgres_required_dirs() {
  source_runtime_env
  [ -s /data/postgres/PG_VERSION ] || return

  # Object-store backed mounts may not preserve empty directories. PostgreSQL
  # still requires these directories to exist before it can start an existing
  # cluster.
  local -a dirs=(
    base
    global
    pg_commit_ts
    pg_dynshmem
    pg_logical
    pg_logical/mappings
    pg_logical/snapshots
    pg_multixact
    pg_multixact/members
    pg_multixact/offsets
    pg_notify
    pg_replslot
    pg_serial
    pg_snapshots
    pg_stat
    pg_stat_tmp
    pg_subtrans
    pg_tblspc
    pg_twophase
    pg_wal
    pg_wal/archive_status
    pg_xact
  )
  local dir
  for dir in "${dirs[@]}"; do
    mkdir -p "/data/postgres/${dir}"
    chmod 700 "/data/postgres/${dir}" 2>/dev/null || true
  done
}

print_postgres_failure_context() {
  source_runtime_env
  log "Temporary PostgreSQL failed to start. Last postgres-init.log lines:"
  tail -n 120 /data/logs/postgres-init.log || true
  log "PostgreSQL data directory details:"
  ls -ld /data/postgres "$(readlink -f /data/postgres 2>/dev/null || printf '%s' /data/postgres)" || true
  stat -c 'mode=%a owner=%u group=%g path=%n' /data/postgres "$(readlink -f /data/postgres 2>/dev/null || printf '%s' /data/postgres)" 2>/dev/null || true
  log "PostgreSQL data directory top-level files:"
  find /data/postgres -maxdepth 1 -mindepth 1 -printf '%M %u %g %s %p\n' 2>/dev/null | sort | sed -n '1,80p' || true
  if [ -s /data/postgres/postmaster.pid ]; then
    log "postmaster.pid contents:"
    sed -n '1,20p' /data/postgres/postmaster.pid || true
  fi
  if [ -s /data/postgres/postmaster.opts ]; then
    log "postmaster.opts contents:"
    sed -n '1,20p' /data/postgres/postmaster.opts || true
  fi
  if command -v df >/dev/null 2>&1; then
    log "Filesystem details:"
    df -hT /data/postgres /data/run /persist 2>/dev/null || df -h /data/postgres /data/run /persist 2>/dev/null || true
  fi
  if [ -x /usr/lib/postgresql/15/bin/pg_controldata ] && [ -s /data/postgres/global/pg_control ]; then
    log "pg_controldata summary:"
    /usr/lib/postgresql/15/bin/pg_controldata /data/postgres 2>&1 | sed -n '1,80p' || true
  fi
}

clear_stale_postgres_runtime_files() {
  source_runtime_env
  local pid_file=/data/postgres/postmaster.pid
  local pid=
  if [ -s "$pid_file" ]; then
    pid=$(sed -n '1p' "$pid_file" | tr -dc '0-9')
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      local cmdline=
      if [ -r "/proc/${pid}/cmdline" ]; then
        cmdline=$(tr '\0' ' ' < "/proc/${pid}/cmdline")
      fi
      if printf '%s' "$cmdline" | grep -q 'postgres' \
        && printf '%s' "$cmdline" | grep -q '/data/postgres'; then
        log "PostgreSQL appears to be running for /data/postgres as PID ${pid}; leaving postmaster.pid in place."
        return
      fi
    fi
    log "Removing stale PostgreSQL postmaster.pid from a previous container."
    rm -f "$pid_file"
  fi

  rm -f \
    "/data/run/postgresql/.s.PGSQL.${DB_PORT}" \
    "/data/run/postgresql/.s.PGSQL.${DB_PORT}.lock"
}

clear_uninitialized_postgres_runtime_files() {
  source_runtime_env
  [ ! -s /data/postgres/PG_VERSION ] || return
  rm -f \
    /data/postgres/postmaster.pid \
    /data/postgres/postmaster.opts \
    "/data/run/postgresql/.s.PGSQL.${DB_PORT}" \
    "/data/run/postgresql/.s.PGSQL.${DB_PORT}.lock"
}

start_temp_postgres() {
  source_runtime_env
  log "Starting temporary PostgreSQL for initialization..."
  if ! /usr/lib/postgresql/15/bin/pg_ctl \
    -D /data/postgres \
    -o "-c listen_addresses='127.0.0.1' -c port=${DB_PORT} -c unix_socket_directories='/data/run/postgresql'" \
    -w start >/data/logs/postgres-init.log 2>&1; then
    print_postgres_failure_context
    return 1
  fi
}

postgres_on_bucket_path() {
  local persist_pg="${PERSIST_ROOT:-/persist}/postgres"
  local actual=
  actual=$(readlink -f /data/postgres 2>/dev/null || printf '%s' /data/postgres)
  [ "$actual" = "$persist_pg" ]
}

postgres_bucket_fallback_enabled() {
  case "${POSTGRES_BUCKET_FAILURE_MODE:-fallback-to-runtime}" in
    fallback-to-runtime|runtime|fallback)
      return 0
      ;;
    exit|fail|disabled|false|FALSE|0)
      return 1
      ;;
    *)
      log "Invalid POSTGRES_BUCKET_FAILURE_MODE=${POSTGRES_BUCKET_FAILURE_MODE}. Use fallback-to-runtime or exit."
      exit 1
      ;;
  esac
}

canonicalize_path() {
  python3 - "$1" <<'PY'
import os
import sys

print(os.path.realpath(sys.argv[1]))
PY
}

paths_overlap() {
  local first=$1
  local second=$2
  case "$first" in
    "$second"|"$second"/*) return 0 ;;
  esac
  case "$second" in
    "$first"|"$first"/*) return 0 ;;
  esac
  return 1
}

recreate_runtime_postgres_fallback_dir() {
  local runtime_root=${RUNTIME_ROOT:-/tmp/dify-aio}
  local persist_root=${PERSIST_ROOT:-/persist}
  local runtime_pg="${runtime_root%/}/postgres"

  if [ -L "$runtime_pg" ]; then
    log "Cannot recreate PostgreSQL fallback: ${runtime_pg} must not be a symlink."
    return 1
  fi
  if [ -e "$runtime_pg" ] && [ ! -d "$runtime_pg" ]; then
    log "Cannot recreate PostgreSQL fallback: ${runtime_pg} exists and is not a directory."
    return 1
  fi

  local canonical_runtime_root canonical_runtime_pg canonical_persist_root expected_runtime_pg
  canonical_runtime_root=$(canonicalize_path "$runtime_root") || return 1
  canonical_runtime_pg=$(canonicalize_path "$runtime_pg") || return 1
  canonical_persist_root=$(canonicalize_path "$persist_root") || return 1
  expected_runtime_pg="${canonical_runtime_root%/}/postgres"

  if [ -z "$canonical_runtime_root" ] || [ "$canonical_runtime_root" = "/" ]; then
    log "Cannot recreate PostgreSQL fallback: unsafe RUNTIME_ROOT=${runtime_root}."
    return 1
  fi
  if [ "$canonical_runtime_pg" != "$expected_runtime_pg" ]; then
    log "Cannot recreate PostgreSQL fallback: ${runtime_pg} resolved outside ${runtime_root}."
    return 1
  fi
  if paths_overlap "$canonical_runtime_pg" "$canonical_persist_root"; then
    log "Cannot recreate PostgreSQL fallback: ${runtime_pg} overlaps persistent storage ${persist_root}."
    return 1
  fi

  log "Recreating runtime PostgreSQL fallback directory at ${runtime_pg}; persistent PGDATA remains untouched."
  rm -rf -- "$runtime_pg"
  install -d -m 700 "$runtime_pg"
}

switch_postgres_to_runtime_fallback() {
  source_runtime_env
  local runtime_root=${RUNTIME_ROOT:-/tmp/dify-aio}
  local runtime_pg="${runtime_root%/}/postgres"
  log "Falling back to runtime PostgreSQL data directory at ${runtime_pg}; bucket dump backups remain under ${POSTGRES_BACKUP_DIR}."
  recreate_runtime_postgres_fallback_dir || exit 1
  if [ -L /data/postgres ]; then
    rm -f /data/postgres
  elif [ -e /data/postgres ]; then
    log "Cannot switch PostgreSQL fallback: /data/postgres exists and is not a symlink."
    exit 1
  fi
  ln -s "$runtime_pg" /data/postgres
}

find_timestamped_backup_for_sha() {
  local expected_sha=$1
  local sha_path sha dump_path found
  local had_nullglob=0
  if shopt -q nullglob; then
    had_nullglob=1
  fi
  shopt -s nullglob
  for sha_path in "${POSTGRES_BACKUP_DIR}"/[0-9]*T[0-9]*Z.sha256; do
    [ -s "$sha_path" ] || continue
    sha=$(awk '{print $1; exit}' "$sha_path")
    dump_path="${sha_path%.sha256}.sql.gz"
    if [ "$sha" = "$expected_sha" ] && [ -s "$dump_path" ]; then
      found=$dump_path
      break
    fi
  done
  if [ "$had_nullglob" -eq 0 ]; then
    shopt -u nullglob
  fi
  if [ -n "${found:-}" ]; then
    printf '%s\n' "$found"
    return 0
  fi
  return 1
}

restore_postgres_backup_if_needed() {
  source_runtime_env
  local backup="${POSTGRES_BACKUP_DIR}/latest.sql.gz"
  if [ ! -s "$backup" ]; then
    return
  fi
  if psql -h /data/run/postgresql -p "$DB_PORT" -U user -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_DATABASE}'" | grep -q 1; then
    return
  fi

  local sha_file="${POSTGRES_BACKUP_DIR}/latest.sha256"
  if [ -s "$sha_file" ]; then
    local expected_sha actual_sha
    expected_sha=$(awk '{print $1; exit}' "$sha_file")
    actual_sha=$(sha256sum "$backup" | awk '{print $1}')
    if [ -z "$expected_sha" ] || [ "$actual_sha" != "$expected_sha" ]; then
      local matching_timestamped_backup
      matching_timestamped_backup=$(find_timestamped_backup_for_sha "$actual_sha" || true)
      if [ -n "$matching_timestamped_backup" ]; then
        warn "PostgreSQL latest.sha256 does not match ${backup}, but ${backup} matches timestamped backup ${matching_timestamped_backup}; continuing restore after crash-window recovery."
      else
        log "PostgreSQL dump ${backup} failed sha256 validation against ${sha_file}."
        exit 1
      fi
    fi
  else
    warn "PostgreSQL dump ${backup} has no latest.sha256; treating it as a legacy backup and continuing with gzip validation."
  fi

  if ! gzip -t "$backup" >/dev/null 2>&1; then
    log "PostgreSQL dump ${backup} failed gzip validation."
    exit 1
  fi
  local backup_bytes
  backup_bytes=$(gzip -dc "$backup" | wc -c | tr -d ' ')
  if [ "${backup_bytes:-0}" -le 0 ]; then
    log "PostgreSQL dump ${backup} is empty after decompression."
    exit 1
  fi

  log "Restoring PostgreSQL dump from ${backup} before creating demo databases."
  if ! gzip -dc "$backup" \
    | sed -E '/^(CREATE|ALTER) ROLE "user"/d' \
    | psql -h /data/run/postgresql -p "$DB_PORT" -U user -d postgres -v ON_ERROR_STOP=1 >/data/logs/postgres-restore.log 2>&1; then
    log "PostgreSQL dump restore failed. Last postgres-restore.log lines:"
    tail -n 120 /data/logs/postgres-restore.log || true
    exit 1
  fi
}

stop_temp_postgres() {
  source_runtime_env
  log "Stopping temporary PostgreSQL..."
  /usr/lib/postgresql/15/bin/pg_ctl -D /data/postgres -m fast -w -t 30 stop >/data/logs/postgres-init-stop.log 2>&1 || true

  local pid_file=/data/postgres/postmaster.pid
  local pid=
  if [ -s "$pid_file" ]; then
    pid=$(sed -n '1p' "$pid_file" | tr -dc '0-9')
  fi
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    local cmdline=
    if [ -r "/proc/${pid}/cmdline" ]; then
      cmdline=$(tr '\0' ' ' < "/proc/${pid}/cmdline")
    fi
    if printf '%s' "$cmdline" | grep -q 'postgres'; then
      log "Temporary PostgreSQL still running as PID ${pid}; sending TERM before continuing."
      kill "$pid" 2>/dev/null || true
      local waited=0
      while [ "$waited" -lt 30 ]; do
        kill -0 "$pid" 2>/dev/null || break
        waited=$((waited + 1))
        sleep 1
      done
      if kill -0 "$pid" 2>/dev/null; then
        log "Temporary PostgreSQL PID ${pid} did not stop after TERM; sending KILL."
        kill -9 "$pid" 2>/dev/null || true
        local kill_waited=0
        while [ "$kill_waited" -lt 5 ]; do
          kill -0 "$pid" 2>/dev/null || break
          kill_waited=$((kill_waited + 1))
          sleep 1
        done
        if kill -0 "$pid" 2>/dev/null; then
          log "Temporary PostgreSQL PID ${pid} is still alive after KILL; refusing to switch PGDATA."
          return 1
        fi
      fi
    fi
  fi

  rm -f \
    "/data/run/postgresql/.s.PGSQL.${DB_PORT}" \
    "/data/run/postgresql/.s.PGSQL.${DB_PORT}.lock"
}

init_postgres() {
  source_runtime_env
  validate_ident DB_USERNAME "$DB_USERNAME"
  validate_ident DB_DATABASE "$DB_DATABASE"
  validate_ident DB_PLUGIN_DATABASE "$DB_PLUGIN_DATABASE"

  if [ ! -s /data/postgres/PG_VERSION ]; then
    clear_uninitialized_postgres_runtime_files
    log "Initializing PostgreSQL data directory at /data/postgres"
    /usr/lib/postgresql/15/bin/initdb \
      -D /data/postgres \
      --encoding=UTF8 \
      --locale=C.UTF-8 >/data/logs/postgres-initdb.log 2>&1
  else
    log "PostgreSQL data directory already exists; skipping initdb."
  fi

  ensure_postgres_required_dirs
  configure_postgres_files
  clear_stale_postgres_runtime_files
  if ! start_temp_postgres; then
    if postgres_on_bucket_path && postgres_bucket_fallback_enabled; then
      if ! stop_temp_postgres; then
        log "Temporary PostgreSQL did not stop cleanly; refusing runtime fallback."
        exit 1
      fi
      switch_postgres_to_runtime_fallback
      log "Initializing fresh fallback PostgreSQL data directory at /data/postgres"
      if ! /usr/lib/postgresql/15/bin/initdb \
        -D /data/postgres \
        --encoding=UTF8 \
        --locale=C.UTF-8 >/data/logs/postgres-initdb.log 2>&1; then
        log "Fallback PostgreSQL initdb failed. Last postgres-initdb.log lines:"
        tail -n 120 /data/logs/postgres-initdb.log || true
        exit 1
      fi
      ensure_postgres_required_dirs
      configure_postgres_files
      clear_stale_postgres_runtime_files
      start_temp_postgres || exit 1
    else
      exit 1
    fi
  fi

  restore_postgres_backup_if_needed

  local pass_sql
  pass_sql=$(sql_escape_literal "$DB_PASSWORD")

  log "Creating/updating PostgreSQL role and databases..."
  if ! psql -h /data/run/postgresql -p "$DB_PORT" -U user -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USERNAME}'" | grep -q 1; then
    psql -h /data/run/postgresql -p "$DB_PORT" -U user -d postgres -v ON_ERROR_STOP=1 \
      -c "CREATE ROLE ${DB_USERNAME} LOGIN PASSWORD '${pass_sql}';"
  else
    psql -h /data/run/postgresql -p "$DB_PORT" -U user -d postgres -v ON_ERROR_STOP=1 \
      -c "ALTER ROLE ${DB_USERNAME} WITH LOGIN PASSWORD '${pass_sql}';"
  fi

  if ! psql -h /data/run/postgresql -p "$DB_PORT" -U user -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_DATABASE}'" | grep -q 1; then
    createdb -h /data/run/postgresql -p "$DB_PORT" -U user -O "$DB_USERNAME" "$DB_DATABASE"
  fi

  if ! psql -h /data/run/postgresql -p "$DB_PORT" -U user -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_PLUGIN_DATABASE}'" | grep -q 1; then
    createdb -h /data/run/postgresql -p "$DB_PORT" -U user -O "$DB_USERNAME" "$DB_PLUGIN_DATABASE"
  fi

  psql -h /data/run/postgresql -p "$DB_PORT" -U user -d "$DB_DATABASE" -v ON_ERROR_STOP=1 \
    -c "CREATE EXTENSION IF NOT EXISTS vector;"
  psql -h /data/run/postgresql -p "$DB_PORT" -U user -d "$DB_PLUGIN_DATABASE" -v ON_ERROR_STOP=1 \
    -c "CREATE EXTENSION IF NOT EXISTS vector;" || true
}

psql_external() {
  local database=$1
  shift
  PGPASSWORD="${DB_PASSWORD:-}" PGSSLMODE="${DB_SSL_MODE:-disable}" \
    psql -h "${DB_HOST:-127.0.0.1}" -p "${DB_PORT:-5432}" -U "${DB_USERNAME:-dify}" -d "$database" "$@"
}

wait_external_postgres() {
  source_runtime_env
  local timeout=${EXTERNAL_POSTGRES_WAIT_SECONDS:-120}
  if ! [[ "$timeout" =~ ^[0-9]+$ ]] || [ "$timeout" -lt 1 ]; then
    timeout=120
  fi
  local waited=0
  until PGPASSWORD="${DB_PASSWORD:-}" PGSSLMODE="${DB_SSL_MODE:-disable}" \
    pg_isready -h "${DB_HOST:-127.0.0.1}" -p "${DB_PORT:-5432}" -U "${DB_USERNAME:-dify}" >/dev/null 2>&1; do
    if [ "$waited" -ge "$timeout" ]; then
      log "External PostgreSQL did not become ready within ${timeout}s at ${DB_HOST}:${DB_PORT}."
      exit 1
    fi
    waited=$((waited + 1))
    sleep 1
  done
}

prepare_external_postgres() {
  source_runtime_env
  validate_ident DB_DATABASE "$DB_DATABASE"
  validate_ident DB_PLUGIN_DATABASE "$DB_PLUGIN_DATABASE"
  log "EXTERNAL_POSTGRES_ENABLED=true; using PostgreSQL at ${DB_HOST}:${DB_PORT}."
  wait_external_postgres

  if ! psql_external "$DB_DATABASE" -tAc "SELECT 1" >/dev/null 2>&1; then
    log "Cannot connect to external DB_DATABASE=${DB_DATABASE}. Create it first and grant access to ${DB_USERNAME}."
    exit 1
  fi
  if ! psql_external "$DB_PLUGIN_DATABASE" -tAc "SELECT 1" >/dev/null 2>&1; then
    log "Cannot connect to external DB_PLUGIN_DATABASE=${DB_PLUGIN_DATABASE}. Create it first and grant access to ${DB_USERNAME}."
    exit 1
  fi

  if is_true "${EXTERNAL_POSTGRES_REQUIRE_VECTOR:-true}"; then
    if ! psql_external "$DB_DATABASE" -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS vector;" >/data/logs/postgres-external-vector.log 2>&1; then
      log "External DB_DATABASE=${DB_DATABASE} is missing usable pgvector extension. Last postgres-external-vector.log lines:"
      tail -n 80 /data/logs/postgres-external-vector.log || true
      exit 1
    fi
    if ! psql_external "$DB_PLUGIN_DATABASE" -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS vector;" >/data/logs/postgres-external-vector-plugin.log 2>&1; then
      log "External DB_PLUGIN_DATABASE=${DB_PLUGIN_DATABASE} is missing usable pgvector extension. Last postgres-external-vector-plugin.log lines:"
      tail -n 80 /data/logs/postgres-external-vector-plugin.log || true
      exit 1
    fi
  fi
}

run_dify_migration() {
  source_runtime_env
  if [ "${MIGRATION_ENABLED:-true}" != "true" ]; then
    log "MIGRATION_ENABLED is not true; skipping Dify DB migration."
    return
  fi

  log "Running Dify API database migration..."
  /usr/local/bin/with-dify-env bash -c \
    'cd /app/api && MODE=migration MIGRATION_ENABLED=true ./docker/entrypoint.sh'
}

main() {
  prepare_dirs
  # Product code is deliberately installed only from one manifest-selected,
  # immutable runtime artifact. This must complete before any Dify wrapper,
  # migration, service, or health probe can access application paths.
  /usr/local/bin/dify-artifact-bootstrap
  configure_plugin_storage_root
  write_generated_env
  source_runtime_env
  log "PUBLIC_URL=${PUBLIC_URL}"
  warn_demo_defaults
  render_redis_config
  render_sandbox_config
  if external_postgres_enabled; then
    prepare_external_postgres
  else
    init_postgres
  fi
  start_temp_redis
  run_dify_migration
  stop_temp_redis
  if ! external_postgres_enabled; then
    stop_temp_postgres
  fi

  log "Starting all services with supervisord."
  exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
