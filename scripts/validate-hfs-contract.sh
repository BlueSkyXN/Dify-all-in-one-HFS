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
  hfs-space-bundle.json .github/workflows/deploy-hfs-formal.yml \
  .github/workflows/publish-dify-runtime-artifact.yml \
  .github/workflows/produce-dify-runtime.yml \
  docker/entrypoint.sh docker/dify-artifact-bootstrap docker/dify_artifact_contract.py \
  docker/sandbox-artifact-launcher.c docker/dify.env.runtime docker/dify.env.demo \
  docker/supervisord.conf docker/nginx.conf docker/healthcheck.sh \
  scripts/align_hfs_runtime_dependency_assertions.py scripts/package-dify-runtime-artifact.py \
  scripts/prepare-dify-artifact-manifest.py scripts/export_hfs_space_bundle.py \
  scripts/check_hfs_visibility.py scripts/deploy_hfs_formal.py \
  scripts/tests/test_deploy_hfs_formal.py scripts/tests/test_hfs_visibility.py \
  scripts/tests/test_align_hfs_runtime_dependency_assertions.py \
  scripts/tests/test_hfs_workflow_safety.py scripts/validate-hfs-contract.sh \
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
    "space_visibility": "protected",
    "bucket_visibility": "private",
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
for key in ("standard", "project", "space_visibility", "bucket_visibility", "project_class", "sovereignty", "lane", "version_source", "secret_files", "local_only", "secrets", "optional_secrets", "variables", "dist_bucket", "seed_file", "other_objects", "deviations"):
    if candidate.get(key) != manifest.get(key):
        errors.append(f"candidate manifest {key} must match primary manifest")
if manifest.get("secret_files") != []:
    errors.append("dify preview manifest must not register structured secret files")
required_secrets = {
    "DIFY_ARTIFACT_BEARER_TOKEN", "OPS_TOKEN", "DB_PASSWORD", "REDIS_PASSWORD",
    "SECRET_KEY", "PLUGIN_DAEMON_KEY", "PLUGIN_DIFY_INNER_API_KEY",
    "CODE_EXECUTION_API_KEY", "SANDBOX_API_KEY", "DIFY_AGENT_SERVER_SECRET_KEY",
    "DIFY_AGENT_SHELLCTL_AUTH_TOKEN",
}
optional_secrets = {"ADMIN_TOKEN"}
required_variables = {
    "DIFY_ARTIFACT_MANIFEST_HF_URI", "DIFY_ARTIFACT_EXPECTED_SOURCE_REF",
    "DIFY_ARTIFACT_MAX_BYTES", "PERSIST_MODE", "POSTGRES_BUCKET_FAILURE_MODE", "ADMIN_ENABLED",
    "ADMIN_FILES_DESTRUCTIVE_ENABLED", "ADMIN_FILES_ENABLED", "ADMIN_FILES_ROOT",
    "ADMIN_FILES_WRITE_ENABLED", "AGENT_DRIVE_MANIFEST_ENABLED",
    "DEVICE_FLOW_APPROVE_RATE_LIMIT_PER_HOUR", "DIFY_AGENT_ENABLED", "ENABLE_AGENT_V2",
    "ENABLE_COLLABORATION_MODE", "ENABLE_OAUTH_BEARER", "ENABLE_WORKFLOW_RUN_CLEANUP_TASK",
    "NEXT_PUBLIC_ENABLE_AGENT_V2", "NEXT_PUBLIC_ENABLE_COLLABORATION_MODE",
    "NEXT_PUBLIC_SOCKET_URL", "OPENAPI_ENABLED", "OPENAPI_KNOWN_CLIENT_IDS",
    "OPENAPI_RATE_LIMIT_PER_TOKEN", "PLUGIN_CWD_PERSISTENCE",
    "PLUGIN_PYTHON_ENV_INIT_TIMEOUT", "PLUGIN_SSL_EOF_MAX_RETRIES", "PLUGIN_UV_CACHE_DIR",
    "SANDBOX_ENABLE_NETWORK", "SANDBOX_SELFCHECK_STRICT", "WORKFLOW_LOG_CLEANUP_ENABLED",
}
for field, expected_keys in (
    ("secrets", required_secrets),
    ("optional_secrets", optional_secrets),
    ("variables", required_variables),
):
    actual = manifest.get(field)
    if not isinstance(actual, list) or set(actual) != expected_keys:
        errors.append(f"hfs-dev.toml {field} must register exactly the approved key names")
if manifest.get("local_only") != ["HF_TOKEN", "GH_TOKEN"]:
    errors.append("hfs-dev.toml local_only must keep control-plane credentials separate")
classified = {
    "local_only": set(manifest.get("local_only", [])),
    "secrets": required_secrets,
    "optional_secrets": optional_secrets,
    "variables": required_variables,
}
names = tuple(classified)
for index, left in enumerate(names):
    for right in names[index + 1:]:
        if classified[left] & classified[right]:
            errors.append(f"hfs-dev.toml {left} and {right} must not overlap")
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
require_grep 'NLTK_DATA=/opt/dify/runtime/usr/local/share/nltk_data' Dockerfile "Dockerfile must point API processes at artifact-delivered NLTK data"
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
require_grep 'punkt_tab' scripts/package-dify-runtime-artifact.py "runtime packager must include NLTK 3.10 resources"
require_grep 'averaged_perceptron_tagger_eng' docker/dify_artifact_contract.py "artifact contract must validate NLTK 3.10 tagger data"
require_grep '^export DEPLOYMENT_EDITION=\$\{DEPLOYMENT_EDITION:-COMMUNITY\}$' docker/dify.env.runtime "runtime defaults must use the current upstream Community edition contract"
require_grep '^    DEPLOYMENT_EDITION=COMMUNITY \\' Dockerfile "wrapper image must expose the current upstream Community edition contract"
require_grep '^DEPLOYMENT_EDITION=COMMUNITY$' docker/dify.env.demo "demo config must use the current upstream Community edition contract"
require_absent '(^|[^A-Z_])EDITION=(SELF_HOSTED|CLOUD)' Dockerfile "wrapper image must not use the retired EDITION contract"
require_absent '^export EDITION=' docker/dify.env.runtime "runtime defaults must not export the retired EDITION contract"
require_absent '^EDITION=' docker/dify.env.demo "demo config must not export the retired EDITION contract"
require_grep '^export DISABLE_TELEMETRY=\$\{DISABLE_TELEMETRY:-true\}$' docker/dify.env.runtime "runtime defaults must keep Community Telemetry disabled"
require_grep '^export DIFY_AGENT_RUNTIME_BACKEND=\$\{DIFY_AGENT_RUNTIME_BACKEND:-local\}$' docker/dify.env.runtime "runtime defaults must use the canonical local Agent backend"
require_grep '^export DIFY_AGENT_SANDBOX_FILES_BASE_URL=\$\{DIFY_AGENT_SANDBOX_FILES_BASE_URL:-http://127\.0\.0\.1:5001\}$' docker/dify.env.runtime "runtime defaults must bind Agent Sandbox file URLs to the same-container API"
require_grep '^  export DIFY_AGENT_SANDBOX_FILES_BASE_URL=\$\{DIFY_AGENT_SANDBOX_FILES_BASE_URL:-http://127\.0\.0\.1:5001\}$' docker/with-dify-env "Agent startup must preserve the Sandbox-reachable file API base"
require_grep 'export AGENT_BACKEND_API_TOKEN=\$\{AGENT_BACKEND_API_TOKEN:-\$\{DIFY_AGENT_API_TOKEN:-\}\}' docker/with-dify-env "API and Agent backend must share the derived loopback bearer token"
require_grep 'DIFY_ARTIFACT_MANIFEST_HF_URI' docs/configuration.md "configuration docs must list the manifest variable"
require_grep 'manifest-last' docs/release-checklist.md "release checklist must require manifest-last evidence"
require_grep 'DIFY_ARTIFACT_MANIFEST_HF_URI' scripts/run-demo.sh "local runner must pass explicit artifact controls"
require_grep 'FORMAL_SPACE: BlueSkyXN/dify-all-in-one' .github/workflows/deploy-hfs-formal.yml "formal workflow must hard-code the canonical Space"
require_grep 'environment: hfs-production' .github/workflows/deploy-hfs-formal.yml "formal workflow must use the scoped production environment"
require_grep 'PUBLISH_FORMAL' .github/workflows/deploy-hfs-formal.yml "formal workflow must require exact upload confirmation"
require_grep 'confirm_factory_reboot:' .github/workflows/deploy-hfs-formal.yml "formal workflow must expose a separate factory reboot confirmation"
require_grep 'CONFIRM_FACTORY_REBOOT.*FACTORY_REBOOT' .github/workflows/deploy-hfs-formal.yml "formal workflow must require the exact factory reboot confirmation"
require_grep 'export_hfs_space_bundle\.py export' .github/workflows/deploy-hfs-formal.yml "formal workflow must use the strict exporter"
require_grep 'source-commit "\$SOURCE_REF"' .github/workflows/deploy-hfs-formal.yml "formal workflow must authorize every verifier against the locked source commit"
require_grep 'HF_CLI_VERSION: "1\.25\.1"' .github/workflows/deploy-hfs-formal.yml "formal workflow must pin huggingface_hub 1.25.1"
require_grep 'HF_CLI_CLICK_VERSION: "8\.4\.2"' .github/workflows/deploy-hfs-formal.yml "formal workflow must pin click 8.4.2"
require_grep 'huggingface_hub==\$\{HF_CLI_VERSION\}' .github/workflows/deploy-hfs-formal.yml "formal workflow must install the pinned Hugging Face client"
require_grep 'click==\$\{HF_CLI_CLICK_VERSION\}' .github/workflows/deploy-hfs-formal.yml "formal workflow must install the direct module CLI dependency"
require_grep 'python3 -m huggingface_hub\.cli\.hf --help' .github/workflows/deploy-hfs-formal.yml "formal workflow must exercise the module CLI"
require_grep 'repos settings --help.*grep -- --protected' .github/workflows/deploy-hfs-formal.yml "formal workflow must verify Protected visibility support"
require_grep 'scripts/deploy_hfs_formal\.py upload' .github/workflows/deploy-hfs-formal.yml "formal workflow must use the CAS upload helper"
require_grep 'scripts/deploy_hfs_formal\.py reboot' .github/workflows/deploy-hfs-formal.yml "formal workflow must use the separately authorized reboot helper"
require_absent 'huggingface_hub\.cli\.hf upload' .github/workflows/deploy-hfs-formal.yml "formal workflow must not use the non-CAS upload CLI"
require_grep 'parent_commit=preflight_sha' scripts/deploy_hfs_formal.py "formal upload must bind its commit to the preflight Space revision"
require_grep 'api\.create_commit\(' scripts/deploy_hfs_formal.py "formal upload must use a structured atomic commit"
require_grep 'Space main changed after verified upload' scripts/deploy_hfs_formal.py "formal reboot must fail closed when Space main drifts"
require_grep 'space-variable-uri DIFY_ARTIFACT_MANIFEST_HF_URI' .github/workflows/deploy-hfs-formal.yml "formal workflow must check the configured artifact Bucket"
require_absent 'info\.private' .github/workflows/deploy-hfs-formal.yml "SpaceInfo.private must not stand in for exact Protected settings readback"
require_grep 'api\.whoami\(token=token\)' scripts/check_hfs_visibility.py "visibility checker must resolve the token owner"
require_grep 'namespace\.casefold\(\) != owner\.casefold\(\)' scripts/check_hfs_visibility.py "visibility checker must distinguish owner and organization namespaces"
require_grep 'kwargs\["namespace"\] = namespace' scripts/check_hfs_visibility.py "visibility checker must scope only cross-namespace repository settings reads"
require_grep 'api\.list_user_repos\(\*\*kwargs\)' scripts/check_hfs_visibility.py "visibility checker must use the repository settings surface"
require_grep 'getattr\(repo, "id", None\) == space.*getattr\(repo, "type", None\) == "space"' scripts/check_hfs_visibility.py "visibility checker must bind exact repository ID and Space type"
require_grep 'api\.bucket_info\(bucket_id, token=token\)' scripts/check_hfs_visibility.py "visibility checker must read each Bucket setting"
formal_visibility_checks=$(grep -c 'scripts/check_hfs_visibility\.py' .github/workflows/deploy-hfs-formal.yml || true)
[ "$formal_visibility_checks" -ge 2 ] || fail "formal workflow must check visibility before and after upload"
require_grep 'revision=deployed_revision' scripts/deploy_hfs_formal.py "formal helper must read back the immutable uploaded revision"
require_grep 'stage == "RUNNING" and runtime_sha == deployed_revision' scripts/deploy_hfs_formal.py "formal helper must bind a running runtime to the uploaded revision"
require_grep 'stage in \{"BUILD_ERROR", "RUNTIME_ERROR"\}' scripts/deploy_hfs_formal.py "formal helper must fail closed on Space build and runtime errors"
require_grep 'huggingface_hub==1\.25\.1' .github/workflows/publish-dify-runtime-artifact.yml "artifact workflow must pin huggingface_hub 1.25.1"
require_grep 'click==8\.4\.2' .github/workflows/publish-dify-runtime-artifact.yml "artifact workflow must pin click 8.4.2"
require_grep 'python -m huggingface_hub\.cli\.hf --help' .github/workflows/publish-dify-runtime-artifact.yml "artifact workflow must exercise the module CLI"
require_grep 'python -m huggingface_hub\.cli\.hf buckets --help' .github/workflows/publish-dify-runtime-artifact.yml "artifact workflow must exercise the buckets command"
require_grep 'repos settings --help.*grep -- --protected' .github/workflows/publish-dify-runtime-artifact.yml "artifact workflow must verify Protected visibility support"
require_grep '\[\[ "\$GITHUB_REF" == refs/heads/main \]\]' .github/workflows/publish-dify-runtime-artifact.yml "artifact workflow must reject non-main dispatch refs"
require_grep 'git rev-parse origin/main.*GITHUB_SHA' .github/workflows/publish-dify-runtime-artifact.yml "artifact workflow must bind its checkout to fresh origin/main"
require_grep '--bucket-uri "\$HF_ARTIFACT_BUCKET_URI"' .github/workflows/publish-dify-runtime-artifact.yml "artifact workflow must check the formal-use Bucket"
artifact_visibility_checks=$(grep -c 'scripts/check_hfs_visibility\.py' .github/workflows/publish-dify-runtime-artifact.yml || true)
[ "$artifact_visibility_checks" -ge 2 ] || fail "artifact workflow must check Private Buckets before and after publication"
require_grep 'workflow_call:' .github/workflows/produce-dify-runtime.yml "runtime producer must be a reusable workflow"
require_absent 'workflow_dispatch:' .github/workflows/produce-dify-runtime.yml "runtime producer must not own a second manual dispatch surface"
require_grep 'contract_ref:' .github/workflows/produce-dify-runtime.yml "runtime producer must require an immutable consumer contract ref"
require_grep 'upstream_base_ref:' .github/workflows/produce-dify-runtime.yml "runtime producer must require an exact upstream base ref"
require_grep 'ref: \$\{\{ inputs\.contract_ref \}\}' .github/workflows/produce-dify-runtime.yml "runtime producer must checkout the caller-pinned consumer contract"
require_grep 'consumer/scripts/align_hfs_runtime_dependency_assertions\.py' .github/workflows/produce-dify-runtime.yml "runtime producer must use consumer-owned alignment logic"
require_grep 'merge-base --is-ancestor "\$DIFY_UPSTREAM_BASE_REF" "\$ARTIFACT_REF"' .github/workflows/produce-dify-runtime.yml "runtime producer must enforce upstream ancestry"
require_absent 'secrets: inherit' .github/workflows/produce-dify-runtime.yml "runtime producer must not inherit caller secrets broadly"
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
python3 -B -m unittest discover -s scripts/tests -p 'test_*.py'
python3 -B - <<'PY'
from pathlib import Path
import warnings

warnings.simplefilter("error", SyntaxWarning)
for raw_path in (
    "docker/dify_artifact_contract.py",
    "scripts/package-dify-runtime-artifact.py",
    "scripts/prepare-dify-artifact-manifest.py",
    "scripts/align_hfs_runtime_dependency_assertions.py",
    "scripts/check_hfs_visibility.py",
    "scripts/deploy_hfs_formal.py",
    "scripts/tests/test_deploy_hfs_formal.py",
    "scripts/tests/test_hfs_visibility.py",
    "scripts/tests/test_align_hfs_runtime_dependency_assertions.py",
    "scripts/tests/test_hfs_workflow_safety.py",
):
    path = Path(raw_path)
    compile(path.read_bytes(), str(path), "exec", dont_inherit=True)
PY

if [ "$errors" -gt 0 ]; then
  exit 1
fi
printf 'PASS hfs-contract: Pattern A manifest-first artifact contract is structurally valid\n'
