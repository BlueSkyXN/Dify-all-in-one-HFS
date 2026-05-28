#!/usr/bin/env bash
set -euo pipefail
IMAGE_TAG=${1:-dify-all-in-one-hf-space:latest}

# 自定义构建参数（示例）：
# docker build --build-arg DIFY_VERSION=1.15.0 \
#   --build-arg PLUGIN_DAEMON_IMAGE=langgenius/dify-plugin-daemon:0.6.1 \
#   --build-arg SANDBOX_IMAGE=langgenius/dify-sandbox:0.2.16 \
#   --build-arg UV_VERSION=0.8.9 -t "$IMAGE_TAG" .
docker build -t "$IMAGE_TAG" .
