#!/usr/bin/env bash
set -euo pipefail
IMAGE_TAG=${1:-dify-all-in-one-hf-space:1.14.1}
CONTAINER_NAME=${CONTAINER_NAME:-dify-aio-hf-demo}
PUBLIC_URL=${PUBLIC_URL:-http://localhost:8080}
PERSIST_VOLUME=${PERSIST_VOLUME:-dify-hf-demo-persist}

env_passthrough=(-e "PUBLIC_URL=$PUBLIC_URL")
for name in \
  POSTGRES_BACKUP_RETAIN_COUNT \
  OPS_TOKEN \
  ALLOW_DEMO_OPS_TOKEN \
  OPS_CACHE_TTL_SECONDS \
  OPS_SESSION_TTL_SECONDS \
  OPS_COOKIE_SECURE \
  OPS_HTTP_TIMEOUT_SECONDS \
  ADMIN_ENABLED \
  ADMIN_TOKEN \
  ADMIN_COOKIE_SECURE \
  ADMIN_HTTP_TIMEOUT_SECONDS \
  ADMIN_LOGIN_RATE_LIMIT_WINDOW_SECONDS \
  ADMIN_LOGIN_RATE_LIMIT_BLOCK_SECONDS \
  ADMIN_LOGIN_RATE_LIMIT_MAX_PER_IP \
  ADMIN_LOGIN_RATE_LIMIT_MAX_GLOBAL \
  ADMIN_FILES_ENABLED \
  ADMIN_FILES_ROOT \
  ADMIN_FILES_WRITE_ENABLED \
  ADMIN_FILES_DESTRUCTIVE_ENABLED \
  WEBSSH_ENABLED \
  WEBSSH_HOST \
  WEBSSH_PORT \
  WEBSSH_BASE_PATH \
  WEBSSH_SHELL \
  WEBSSH_MAX_CLIENTS
do
  if [ "${!name+x}" = "x" ]; then
    env_passthrough+=(-e "$name=${!name}")
  fi
done

docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

docker run -d \
  --name "$CONTAINER_NAME" \
  -p 8080:7860 \
  -v "$PERSIST_VOLUME":/persist \
  --env-file docker/dify.env.demo \
  "${env_passthrough[@]}" \
  "$IMAGE_TAG"

echo "Dify all-in-one demo started: $PUBLIC_URL"
echo "Logs: docker logs -f $CONTAINER_NAME"
