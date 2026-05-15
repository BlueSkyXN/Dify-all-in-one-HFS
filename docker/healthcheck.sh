#!/usr/bin/env bash
set -euo pipefail
curl -fsS http://127.0.0.1:5001/health >/dev/null
curl -fsS http://127.0.0.1:7860/ >/dev/null
