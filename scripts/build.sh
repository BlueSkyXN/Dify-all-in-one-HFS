#!/usr/bin/env bash
set -euo pipefail
IMAGE_TAG=${1:-dify-all-in-one-hf-space:1.14.1}
docker build -t "$IMAGE_TAG" .
