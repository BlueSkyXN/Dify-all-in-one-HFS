#!/usr/bin/env bash
set -euo pipefail
curl -fsS --connect-timeout 2 --max-time 5 http://127.0.0.1:5001/health >/dev/null
curl -fsS --connect-timeout 2 --max-time 5 http://127.0.0.1:8081/healthz >/dev/null
curl -fsS --connect-timeout 2 --max-time 5 http://127.0.0.1:7860/ >/dev/null
