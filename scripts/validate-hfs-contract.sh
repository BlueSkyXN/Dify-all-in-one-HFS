#!/usr/bin/env bash
# shellcheck disable=SC2016
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

errors=0

fail() {
  printf 'FAIL hfs-contract: %s\n' "$1" >&2
  errors=$((errors + 1))
}

require_file() {
  local path=$1
  [ -f "$path" ] || fail "missing required file: $path"
}

require_grep() {
  local pattern=$1 path=$2 message=$3
  grep -Eq -- "$pattern" "$path" || fail "$message"
}

require_absent() {
  local pattern=$1 path=$2 message=$3
  if grep -Eq -- "$pattern" "$path"; then
    fail "$message"
  fi
}

frontmatter_value() {
  local key=$1
  python3 - "$key" <<'PY'
import sys
from pathlib import Path

key = sys.argv[1]
lines = Path("README.md").read_text(encoding="utf-8").splitlines()
if not lines or lines[0] != "---":
    raise SystemExit(0)
for line in lines[1:]:
    if line == "---":
        break
    if line.startswith(f"{key}:"):
        print(line.partition(":")[2].strip())
PY
}

for path in \
  README.md Dockerfile hfs-dev.toml hfs-dev.candidate.toml .dockerignore .gitignore .env.example \
  docker/entrypoint.sh docker/dify-artifact-bootstrap docker/dify_artifact_contract.py \
  docker/sandbox-artifact-launcher.c docker/dify.env.runtime docker/dify.env.demo \
  docker/supervisord.conf docker/nginx.conf docker/healthcheck.sh \
  scripts/package-dify-runtime-artifact.py scripts/prepare-dify-artifact-manifest.py scripts/validate-hfs-contract.sh \
  scripts/static-check.sh scripts/hf-space-smoke.sh docs/hfs-alignment.md \
  docs/configuration.md docs/deployment.md docs/release-checklist.md; do
  require_file "$path"
done

python3 - "$repo_root" <<'PY'
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

root = Path(sys.argv[1])
manifest = tomllib.loads((root / "hfs-dev.toml").read_text(encoding="utf-8"))
candidate = tomllib.loads((root / "hfs-dev.candidate.toml").read_text(encoding="utf-8"))
expected = {
    "standard": "2.1",
    "project": "dify-all-in-one",
    "space": "BlueSkyXN/dify-all-in-one",
    "project_class": "preview",
    "target_role": "primary",
    "sovereignty": "fork",
    "lane": "artifact",
    "version_source": "commit",
    "env_file": ".env",
    "dist_bucket": "hfs-dist",
}
errors = [f"hfs-dev.toml {key} must be {value!r}, got {manifest.get(key)!r}" for key, value in expected.items() if manifest.get(key) != value]
candidate_expected = {
    "space": "BlueSkyXN/dify-all-in-one-v2-candidate",
    "project_class": "preview",
    "target_role": "candidate",
    "env_file": "local/hfs-targets/candidate.env",
}
for key, value in candidate_expected.items():
    if candidate.get(key) != value:
        errors.append(f"candidate manifest {key} must be {value!r}")
for key in ("standard", "project", "project_class", "sovereignty", "lane", "version_source", "secret_files", "local_only", "secrets", "variables", "dist_bucket", "seed_file", "other_objects", "deviations"):
    if candidate.get(key) != manifest.get(key):
        errors.append(f"candidate manifest {key} must match primary manifest")
if manifest.get("secret_files") != []:
    errors.append("dify preview manifest must not register structured secret files")
required_secrets = {
    "DIFY_ARTIFACT_BEARER_TOKEN", "OPS_TOKEN", "DB_PASSWORD", "REDIS_PASSWORD",
    "SECRET_KEY", "PLUGIN_DAEMON_KEY", "PLUGIN_DIFY_INNER_API_KEY",
    "CODE_EXECUTION_API_KEY", "ADMIN_TOKEN",
}
required_variables = {
    "DIFY_ARTIFACT_MANIFEST_HF_URI", "DIFY_ARTIFACT_EXPECTED_SOURCE_REF",
    "DIFY_ARTIFACT_MAX_BYTES", "PERSIST_MODE", "POSTGRES_BUCKET_FAILURE_MODE", "ADMIN_ENABLED",
}
for field, expected_keys in (("secrets", required_secrets), ("variables", required_variables)):
    actual = manifest.get(field)
    if not isinstance(actual, list) or set(actual) != expected_keys:
        errors.append(f"hfs-dev.toml {field} must register exactly the approved key names")
if manifest.get("local_only") != ["HF_TOKEN", "GH_TOKEN"]:
    errors.append("hfs-dev.toml local_only must keep control-plane credentials separate")
if manifest.get("seed_file") != "" or manifest.get("other_objects") != []:
    errors.append("dify artifact lane must not declare generated runtime state as a distributable seed")
if errors:
    for error in errors:
        print(f"FAIL hfs-contract: {error}", file=sys.stderr)
    raise SystemExit(1)
PY

sdk=$(frontmatter_value sdk)
app_port=$(frontmatter_value app_port)
docker_expose=$(python3 - <<'PY'
from pathlib import Path
for line in Path("Dockerfile").read_text(encoding="utf-8").splitlines():
    fields = line.split()
    if fields and fields[0].upper() == "EXPOSE":
        print(fields[1])
        break
PY
)
nginx_listen=$(python3 - <<'PY'
import re
from pathlib import Path
match = re.search(r"^\s*listen\s+([^;\s]+)", Path("docker/nginx.conf").read_text(encoding="utf-8"), re.M)
if match:
    print(match.group(1).rsplit(":", 1)[-1])
PY
)
[ "$sdk" = "docker" ] || fail "README.md frontmatter must set sdk: docker"
[ "$app_port" = "7860" ] || fail "README.md frontmatter must set app_port: 7860"
[ "$docker_expose" = "$app_port" ] || fail "Dockerfile EXPOSE must match README.md app_port"
[ "$nginx_listen" = "$app_port" ] || fail "docker/nginx.conf listen must match README.md app_port"

# Artifact delivery must not silently retain the old image-assembly product path.
require_grep '^FROM \$\{BASE_IMAGE_REF\} AS runtime$' Dockerfile "Dockerfile must use the declared base runtime image"
require_grep 'DIFY_AIO_RUNTIME_DELIVERY=manifest-first-artifact' Dockerfile "Dockerfile must expose artifact delivery provenance"
require_grep 'dify-artifact-bootstrap' Dockerfile "Dockerfile must install the artifact bootstrap"
require_grep '/usr/local/lib/dify_artifact_contract.py' Dockerfile "Dockerfile must install the verifier at its importable module path"
require_absent '/usr/local/lib/dify-artifact-contract.py' Dockerfile "Dockerfile must not install the verifier under a non-importable hyphenated name"
require_grep 'sandbox-artifact-launcher' Dockerfile "Dockerfile must retain the fixed Sandbox privilege launcher"
require_grep 'COPY docker/sandbox-python-requirements.txt /dependencies/python-requirements.txt' Dockerfile "Dockerfile must preinstall the approved Sandbox Python environment"
require_grep 'pip install --no-cache-dir -r /dependencies/python-requirements.txt' Dockerfile "Dockerfile must install the approved Sandbox Python dependencies"
require_grep 'ln -s /opt/dify/runtime/opt/dify-agent /opt/dify-agent' Dockerfile "Dockerfile must link the artifact Agent virtualenv into its runtime path"
require_grep 'ln -s /opt/dify/runtime/usr/local/bin/shellctl /usr/local/bin/shellctl' Dockerfile "Dockerfile must link the artifact shellctl binary into its runtime path"
require_grep 'chown -R user:user /home/user /data' Dockerfile "Dockerfile must keep the runtime home writable when the base image pre-creates it"
require_absent '^FROM \$\{DIFY_' Dockerfile "Dockerfile must not select Dify business OCI images"
require_absent '^ARG DIFY_(API|WEB|AGENT|SOURCE|SANDBOX|VERSION)' Dockerfile "Dockerfile must not duplicate artifact runtime pins"
require_absent 'git fetch|git clone|dify-sandbox.git' Dockerfile "Dockerfile must not fetch Dify product source during build"
require_absent 'COPY --from=(api-image|web-builder|agent-image|agent-runtime-image|plugin-daemon-image|sandbox-image|sandbox-builder)' Dockerfile "Dockerfile must not copy product image payloads"

require_grep 'DIFY_ARTIFACT_MANIFEST_HF_URI' docker/dify.env.runtime "runtime defaults must register manifest URI"
require_grep 'DIFY_ARTIFACT_BEARER_TOKEN' docker/dify.env.runtime "runtime defaults must register artifact credential"
require_grep 'DIFY_ARTIFACT_MANIFEST_HF_URI=' docker/dify.env.demo "demo config must require an explicit artifact URI"
require_grep '/usr/local/bin/dify-artifact-bootstrap' docker/entrypoint.sh "entrypoint must bootstrap before Dify initialization"
require_grep 'require_env DIFY_ARTIFACT_MANIFEST_HF_URI' docker/dify-artifact-bootstrap "bootstrap must fail closed without manifest URI"
require_grep 'require_env DIFY_ARTIFACT_BEARER_TOKEN' docker/dify-artifact-bootstrap "bootstrap must fail closed without artifact credential"
require_grep '--proto-redir =https --max-redirs 5' docker/dify-artifact-bootstrap "artifact redirects must stay on bounded HTTPS hops"
require_absent '--location-trusted' docker/dify-artifact-bootstrap "artifact downloads must never forward Authorization across hosts"
require_grep "trap 'rm -rf /tmp/dify-artifact-download' EXIT" docker/dify-artifact-bootstrap "artifact cleanup must not reference function-local variables from the EXIT trap"
require_absent 'DIFY_ARTIFACT_(URL|PATH|S3_|SHA256)' docker/dify.env.runtime "runtime defaults must not permit direct artifact fallback inputs"
require_absent 'DIFY_ARTIFACT_(URL|PATH|S3_|SHA256)' docker/dify-artifact-bootstrap "bootstrap must not permit direct artifact fallback inputs"
require_absent 'DIFY_ARTIFACT_(INSTALL_ROOT|DOWNLOAD_DIR)' docker/dify.env.runtime "runtime defaults must not expose artifact filesystem controls"
require_absent 'DIFY_ARTIFACT_(INSTALL_ROOT|DOWNLOAD_DIR)' docker/dify-artifact-bootstrap "bootstrap must keep artifact filesystem controls image-owned"

require_grep '^\.env$' .dockerignore ".dockerignore must exclude the local env ledger"
require_grep '^\.env\.\*$' .dockerignore ".dockerignore must exclude named env ledgers"
require_grep '^local/$|^\*\*/local/$' .dockerignore ".dockerignore must exclude local/"
require_grep '^\*\.secret$' .dockerignore ".dockerignore must exclude *.secret"
require_grep '^\*\.key$' .dockerignore ".dockerignore must exclude *.key"
require_grep '^\*\.pem$' .dockerignore ".dockerignore must exclude *.pem"
require_grep '^/\.env$' .gitignore ".gitignore must exclude .env"
require_grep '^/\.env\.\*$' .gitignore ".gitignore must exclude named local env ledgers"
require_grep '^!\.env\.example$' .gitignore ".gitignore must retain the harmless .env.example template"

require_grep 'manifest-first' docs/hfs-alignment.md "HFS docs must describe manifest-first artifact delivery"
require_grep 'DIFY_ARTIFACT_MANIFEST_HF_URI' docs/configuration.md "configuration docs must list the manifest variable"
require_grep 'manifest-last' docs/release-checklist.md "release checklist must require manifest-last evidence"
require_grep 'DIFY_ARTIFACT_MANIFEST_HF_URI' scripts/run-demo.sh "local runner must pass explicit artifact controls"
require_grep '/nginx-health' scripts/hf-space-smoke.sh "smoke script must check /nginx-health"
require_grep '/healthz' scripts/hf-space-smoke.sh "smoke script must check /healthz"
require_grep '/_ops/health' scripts/hf-space-smoke.sh "smoke script must check /_ops/health"

python3 - <<'PY'
from __future__ import annotations

import importlib.util
from pathlib import Path

path = Path("docker/dify_artifact_contract.py")
spec = importlib.util.spec_from_file_location("dify_artifact_contract_gate", path)
if spec is None or spec.loader is None:
    raise SystemExit("FAIL hfs-contract: cannot import artifact contract")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
if module.SCHEMA_VERSION != 2 or module.MAX_EXTRACTED_BYTES != 32 * 1024 * 1024 * 1024:
    raise SystemExit("FAIL hfs-contract: artifact schema/resource guard is not the approved v2 contract")
for unsafe_uri in (
    "hf://buckets/example%2Fescape/hfs-dist/dify-all-in-one/edge/manifest.json",
    "hf://buckets/example/hfs-dist/dify-all-in-one/edge/manifest.json?fallback=1",
):
    try:
        module.parse_manifest_uri(unsafe_uri)
    except module.ContractError:
        continue
    raise SystemExit("FAIL hfs-contract: artifact URI parser accepted an unsafe path or query")
PY
python3 docker/dify_artifact_contract.py --self-test
python3 -B - <<'PY'
from pathlib import Path
import warnings

warnings.simplefilter("error", SyntaxWarning)
for raw_path in (
    "docker/dify_artifact_contract.py",
    "scripts/package-dify-runtime-artifact.py",
    "scripts/prepare-dify-artifact-manifest.py",
):
    path = Path(raw_path)
    compile(path.read_bytes(), str(path), "exec", dont_inherit=True)
PY

if [ "$errors" -gt 0 ]; then
  exit 1
fi
printf 'PASS hfs-contract: Pattern A manifest-first artifact contract is structurally valid\n'
