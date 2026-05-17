#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '[dify-aio-hf] %s\n' "$*"
}

shell_quote() {
  local s=${1:-}
  s=${s//\'/\'\\\'\'}
  printf "'%s'" "$s"
}

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

write_generated_env() {
  mkdir -p /data/config /data/secrets
  chmod 700 /data/secrets || true

  # Capture Space Settings / docker -e values first. If they are non-empty,
  # they override previously persisted generated values.
  source_defaults_env
  local provided_secret_key=${SECRET_KEY:-}
  local provided_plugin_daemon_key=${PLUGIN_DAEMON_KEY:-}
  local provided_plugin_inner_key=${PLUGIN_DIFY_INNER_API_KEY:-}
  local provided_code_execution_key=${CODE_EXECUTION_API_KEY:-}
  local provided_sandbox_key=${SANDBOX_API_KEY:-}

  if [ -f /data/config/generated.env ]; then
    # shellcheck disable=SC1091
    . /data/config/generated.env
  fi

  local secret_key=${provided_secret_key:-${SECRET_KEY:-}}
  local plugin_daemon_key=${provided_plugin_daemon_key:-${PLUGIN_DAEMON_KEY:-}}
  local plugin_inner_key=${provided_plugin_inner_key:-${PLUGIN_DIFY_INNER_API_KEY:-}}
  local code_execution_key=${provided_code_execution_key:-${CODE_EXECUTION_API_KEY:-}}
  local sandbox_key=${provided_sandbox_key:-${SANDBOX_API_KEY:-}}

  [ -n "$secret_key" ] || secret_key="$(openssl rand -base64 42)"
  [ -n "$plugin_daemon_key" ] || plugin_daemon_key="$(openssl rand -base64 42)"
  [ -n "$plugin_inner_key" ] || plugin_inner_key="$(openssl rand -base64 42)"
  [ -n "$code_execution_key" ] || code_execution_key="$(openssl rand -base64 42)"
  [ -n "$sandbox_key" ] || sandbox_key="$code_execution_key"

  cat > /data/config/generated.env <<EOF_GENERATED
export SECRET_KEY=$(shell_quote "$secret_key")
export PLUGIN_DAEMON_KEY=$(shell_quote "$plugin_daemon_key")
export PLUGIN_DIFY_INNER_API_KEY=$(shell_quote "$plugin_inner_key")
export INNER_API_KEY_FOR_PLUGIN=$(shell_quote "$plugin_inner_key")
export CODE_EXECUTION_API_KEY=$(shell_quote "$code_execution_key")
export SANDBOX_API_KEY=$(shell_quote "$sandbox_key")
EOF_GENERATED
  chmod 600 /data/config/generated.env || true
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

prepare_dirs() {
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
    log "Cannot create runtime directories. In Hugging Face Space, attach writable storage to /data or ensure /data is writable."
    exit 1
  fi

  if ! touch /data/.writable-test 2>/dev/null; then
    log "/data is not writable by UID $(id -u). Check Hugging Face Storage settings or run locally with -v dify-demo-data:/data."
    exit 1
  fi
  rm -f /data/.writable-test

  touch /dependencies/python-requirements.txt /dependencies/nodejs-requirements.txt || true
  chmod 700 /data/config || true
  chmod 755 /data/logs /data/run /data/dify /data/plugin_daemon || true
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

render_sandbox_config() {
  source_runtime_env
  local api_key=${SANDBOX_API_KEY:-${CODE_EXECUTION_API_KEY:-}}
  local enable_network=${SANDBOX_ENABLE_NETWORK:-false}
  local python_path=${SANDBOX_PYTHON_PATH:-/usr/local/bin/python3}
  local nodejs_path=${SANDBOX_NODEJS_PATH:-/usr/bin/node}
  local python_lib_paths=${SANDBOX_PYTHON_LIB_PATH:-/usr/local/lib/python3.12,/usr/local/lib/python3.12/lib-dynload,/usr/local/lib/python3.12/site-packages,/usr/lib/x86_64-linux-gnu,/lib/x86_64-linux-gnu,/etc/ssl/certs/ca-certificates.crt,/etc/nsswitch.conf,/etc/hosts,/etc/resolv.conf,/run/systemd/resolve/stub-resolv.conf,/run/resolvconf/resolv.conf,/etc/localtime,/usr/share/zoneinfo,/etc/timezone}
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
python_deps_update_interval: "${SANDBOX_PYTHON_DEPS_UPDATE_INTERVAL:-30m}"
enable_network: ${enable_network}
enable_preload: false
log_path: "/data/logs"
allowed_syscalls: []
python_lib_path:
EOF_SANDBOX
  if [ -n "$python_lib_paths" ]; then
    IFS=',' read -r -a lib_paths <<< "$python_lib_paths"
    for lib_path in "${lib_paths[@]}"; do
      [ -n "$lib_path" ] || continue
      printf '  - "%s"\n' "$lib_path" >> /conf/config.yaml
    done
  fi
  cat >> /conf/config.yaml <<EOF_SANDBOX
proxy:
  socks5: ''
  http: '${SANDBOX_HTTP_PROXY:-}'
  https: '${SANDBOX_HTTPS_PROXY:-}'
EOF_SANDBOX
  chmod 644 /conf/config.yaml || true
}

configure_postgres_files() {
  source_runtime_env
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

start_temp_postgres() {
  source_runtime_env
  log "Starting temporary PostgreSQL for initialization..."
  /usr/lib/postgresql/15/bin/pg_ctl \
    -D /data/postgres \
    -o "-c listen_addresses='127.0.0.1' -c port=${DB_PORT} -c unix_socket_directories='/data/run/postgresql'" \
    -w start >/data/logs/postgres-init.log 2>&1
}

stop_temp_postgres() {
  log "Stopping temporary PostgreSQL..."
  /usr/lib/postgresql/15/bin/pg_ctl -D /data/postgres -m fast -w stop >/data/logs/postgres-init-stop.log 2>&1 || true
}

init_postgres() {
  source_runtime_env
  validate_ident DB_USERNAME "$DB_USERNAME"
  validate_ident DB_DATABASE "$DB_DATABASE"
  validate_ident DB_PLUGIN_DATABASE "$DB_PLUGIN_DATABASE"

  if [ ! -s /data/postgres/PG_VERSION ]; then
    log "Initializing PostgreSQL data directory at /data/postgres"
    /usr/lib/postgresql/15/bin/initdb \
      -D /data/postgres \
      --encoding=UTF8 \
      --locale=C.UTF-8 >/data/logs/postgres-initdb.log 2>&1
  else
    log "PostgreSQL data directory already exists; skipping initdb."
  fi

  configure_postgres_files
  start_temp_postgres

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
  write_generated_env
  source_runtime_env
  log "PUBLIC_URL=${PUBLIC_URL}"
  render_redis_config
  render_sandbox_config
  init_postgres
  run_dify_migration
  stop_temp_postgres

  log "Starting all services with supervisord."
  exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
}

main "$@"
