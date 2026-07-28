#!/usr/bin/env bash
set -euo pipefail

IMAGE_TAG=${1:-dify-all-in-one-hf-space:latest}

# The consumer image has no Dify product-image build args. Component provenance
# is verified from the runtime artifact manifest and runtime-lock.json. Only
# wrapper base/tool inputs remain build-time overrides.
build_args=()
for arg_name in BASE_IMAGE_REF UV_VERSION; do
  arg_value=${!arg_name-}
  if [ -n "$arg_value" ]; then
    build_args+=(--build-arg "${arg_name}=${arg_value}")
  fi
done

docker build "${build_args[@]}" -t "$IMAGE_TAG" .
