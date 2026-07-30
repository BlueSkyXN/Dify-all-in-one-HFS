#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

check_changed_file_trailing_whitespace() {
  local -a files=()
  local file
  while IFS= read -r -d '' file; do
    [ -f "$file" ] || continue
    files+=("$file")
  done < <(
    git diff --name-only -z --diff-filter=ACMR
    git diff --cached --name-only -z --diff-filter=ACMR
    git ls-files --others --exclude-standard -z
  )

  [ "${#files[@]}" -gt 0 ] || return 0

  local output status
  set +e
  if command -v rg >/dev/null 2>&1; then
    output=$(rg -n '[[:blank:]]$' -- "${files[@]}" 2>&1)
    status=$?
  else
    output=$(grep -n -E '[[:blank:]]$' -- "${files[@]}" 2>&1)
    status=$?
  fi
  set -e

  if [ "$status" -eq 0 ]; then
    printf 'Trailing whitespace found in changed or untracked files:\n%s\n' "$output" >&2
    return 1
  fi
  if [ "$status" -gt 1 ]; then
    printf 'Unable to check trailing whitespace:\n%s\n' "$output" >&2
    return "$status"
  fi
}

require_executable() {
  local path=$1
  if [ ! -x "$path" ]; then
    printf 'Expected executable script: %s\n' "$path" >&2
    return 1
  fi
}

check_python_syntax() {
  python3 -B - "$@" <<'PY'
from pathlib import Path
import sys
import warnings

warnings.simplefilter("error", SyntaxWarning)
for raw_path in sys.argv[1:]:
    path = Path(raw_path)
    compile(path.read_bytes(), str(path), "exec", dont_inherit=True)
PY
}

bash -n \
  docker/entrypoint.sh \
  docker/dify-artifact-bootstrap \
  docker/with-dify-env \
  docker/with-plugin-env \
  docker/with-sandbox-env \
  docker/run-postgres \
  docker/run-dify-agent \
  docker/run-shellctl \
  docker/wait-for-core \
  docker/healthcheck.sh \
  docker/postgres-backup-loop \
  scripts/build.sh \
  scripts/run-demo.sh \
  scripts/admin-smoke.sh \
  scripts/hf-space-smoke.sh \
  scripts/validate-hfs-contract.sh \
  scripts/static-check.sh

require_executable scripts/admin-smoke.sh
require_executable scripts/build.sh
require_executable scripts/check-self-release-pins.py
require_executable scripts/package-dify-runtime-artifact.py
require_executable scripts/prepare-dify-artifact-manifest.py
require_executable scripts/hf-space-smoke.sh
require_executable scripts/run-demo.sh
require_executable scripts/static-check.sh
require_executable scripts/validate-hfs-contract.sh
require_executable docker/run-dify-agent
require_executable docker/run-shellctl
require_executable docker/run-postgres
require_executable docker/sandbox-selfcheck

scripts/validate-hfs-contract.sh
python3 scripts/check-self-release-pins.py --require-final-digest
check_python_syntax \
  docker/ops_service.py \
  docker/admin_service.py \
  docker/dify_artifact_contract.py \
  docker/sandbox-selfcheck \
  scripts/check-self-release-pins.py \
  scripts/check_hfs_visibility.py \
  scripts/package-dify-runtime-artifact.py \
  scripts/prepare-dify-artifact-manifest.py \
  scripts/export_hfs_space_bundle.py \
  scripts/tests/test_hfs_visibility.py \
  docker/plugin_runtime_patches/sitecustomize.py
python3 -B -m unittest discover -s docker/tests -p 'test_*.py'
git diff --check
check_changed_file_trailing_whitespace
