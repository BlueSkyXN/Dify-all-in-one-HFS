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
  DIFY_VERSION \
  UV_VERSION; do
  arg_value=${!arg_name-}
  if [ -n "$arg_value" ]; then
    build_args+=(--build-arg "${arg_name}=${arg_value}")
  fi
done

# 自定义构建参数可通过同名环境变量透传，例如：
# DIFY_API_IMAGE_REF=langgenius/dify-api:1.14.2 \
# DIFY_WEB_IMAGE_REF=langgenius/dify-web:1.14.2 \
# PLUGIN_DAEMON_IMAGE_REF=langgenius/dify-plugin-daemon:0.6.1-local \
# SANDBOX_IMAGE_REF=langgenius/dify-sandbox:0.2.15 \
# BASE_IMAGE_REF=python:3.12-slim-bookworm \
# DIFY_VERSION=1.14.2 \
# UV_VERSION=0.11.16 \
#   scripts/build.sh "$IMAGE_TAG"
# 发布构建应把 *_IMAGE_REF 和 BASE_IMAGE_REF 换成 image@sha256 digest ref。
docker build "${build_args[@]}" -t "$IMAGE_TAG" .
