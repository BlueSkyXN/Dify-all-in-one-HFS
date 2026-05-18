#!/usr/bin/env bash
set -euo pipefail
IMAGE_TAG=${1:-dify-all-in-one-hf-space:1.14.1}
CONTAINER_NAME=${CONTAINER_NAME:-dify-aio-hf-demo}
PUBLIC_URL=${PUBLIC_URL:-http://localhost:8080}
PERSIST_VOLUME=${PERSIST_VOLUME:-dify-hf-demo-persist}

docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

docker run -d \
  --name "$CONTAINER_NAME" \
  -p 8080:7860 \
  -v "$PERSIST_VOLUME":/persist \
  --env-file docker/dify.env.demo \
  -e PUBLIC_URL="$PUBLIC_URL" \
  "$IMAGE_TAG"

echo "Dify all-in-one demo started: $PUBLIC_URL"
echo "Logs: docker logs -f $CONTAINER_NAME"
