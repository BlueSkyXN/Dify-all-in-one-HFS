#!/usr/bin/env bash
set -euo pipefail
IMAGE_TAG=${1:-dify-all-in-one-hf-space:latest}

build_args=()
for arg_name in \
  BASE_IMAGE_REF \
  DIFY_API_IMAGE_REF \
  DIFY_WEB_IMAGE_REF \
  PLUGIN_DAEMON_IMAGE_REF \
  SANDBOX_IMAGE_REF \
  DIFY_SANDBOX_SOURCE_REF \
  DIFY_VERSION \
  UV_VERSION; do
  arg_value=${!arg_name-}
  if [ -n "$arg_value" ]; then
    build_args+=(--build-arg "${arg_name}=${arg_value}")
  fi
done

# 自定义构建参数可通过同名环境变量透传，例如：
# DIFY_API_IMAGE_REF=langgenius/dify-api@sha256:... \
# DIFY_WEB_IMAGE_REF=langgenius/dify-web@sha256:... \
# PLUGIN_DAEMON_IMAGE_REF=langgenius/dify-plugin-daemon@sha256:... \
# SANDBOX_IMAGE_REF=langgenius/dify-sandbox@sha256:... \
# DIFY_SANDBOX_SOURCE_REF=<dify-sandbox-commit> \
# BASE_IMAGE_REF=python:3.12-slim-bookworm \
# DIFY_VERSION=main-<commit> \
# UV_VERSION=0.11.21 \
#   scripts/build.sh "$IMAGE_TAG"
# NEXT 构建默认已 pin 到 main digest set；覆盖时也应使用 image@sha256 digest ref。
docker build "${build_args[@]}" -t "$IMAGE_TAG" .
