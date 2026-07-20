#!/usr/bin/env bash
set -euo pipefail
IMAGE_TAG=${1:-dify-all-in-one-hf-space:latest}

build_args=()
for arg_name in \
  BASE_IMAGE_REF \
  DIFY_SOURCE_REPO \
  DIFY_SOURCE_MAIN_REF \
  DIFY_UPSTREAM_BASE_REF \
  DIFY_API_IMAGE_REF \
  DIFY_WEB_IMAGE_REF \
  DIFY_AGENT_IMAGE_REF \
  DIFY_AGENT_RUNTIME_IMAGE_REF \
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
# BASE_IMAGE_REF=python:3.12-slim-bookworm \
# DIFY_SOURCE_REPO=https://github.com/BlueSkyXN/dify.git \
# DIFY_SOURCE_MAIN_REF=<self-main-commit> \
# DIFY_UPSTREAM_BASE_REF=<merged-upstream-commit> \
# DIFY_API_IMAGE_REF=ghcr.io/blueskyxn/dify-api@sha256:<digest> \
# DIFY_WEB_IMAGE_REF=ghcr.io/blueskyxn/dify-web@sha256:<digest> \
# DIFY_AGENT_IMAGE_REF=ghcr.io/blueskyxn/dify-agent-backend@sha256:<digest> \
# DIFY_AGENT_RUNTIME_IMAGE_REF=ghcr.io/blueskyxn/dify-agent-local-sandbox@sha256:<digest> \
# PLUGIN_DAEMON_IMAGE_REF=langgenius/dify-plugin-daemon@sha256:... \
# SANDBOX_IMAGE_REF=langgenius/dify-sandbox@sha256:... \
# DIFY_SANDBOX_SOURCE_REF=<dify-sandbox-commit> \
# DIFY_VERSION=<release-metadata> \
# UV_VERSION=0.11.21 \
#   scripts/build.sh "$IMAGE_TAG"
# GHCR digest 占位值必须先由主线程替换；不要以零 digest 执行 build。
docker build "${build_args[@]}" -t "$IMAGE_TAG" .
