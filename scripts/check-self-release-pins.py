#!/usr/bin/env python3
"""Validate the self GHCR release pin contract without contacting a registry."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path


PLACEHOLDER_DIGEST = "sha256:" + "0" * 64
SELF_IMAGE_ARGS = {
    "DIFY_API_IMAGE_REF": "ghcr.io/blueskyxn/dify-api",
    "DIFY_WEB_IMAGE_REF": "ghcr.io/blueskyxn/dify-web",
    "DIFY_AGENT_IMAGE_REF": "ghcr.io/blueskyxn/dify-agent-backend",
    "DIFY_AGENT_RUNTIME_IMAGE_REF": "ghcr.io/blueskyxn/dify-agent-local-sandbox",
}
SOURCE_REPO = "https://github.com/BlueSkyXN/dify.git"
ZERO_SOURCE_REF = "0" * 40
FROZEN_UPSTREAM_REF = "ef0115d34030eb496a1bc761b842e3bcd8f5598d"
SANDBOX_SOURCE_REF = "97c8097d51d0f46238bb720b1e9e9439ce68784d"
EXTERNAL_IMAGE_ARGS = ("PLUGIN_DAEMON_IMAGE_REF", "SANDBOX_IMAGE_REF")
REQUIRED_HFS_PINS = {
    "DIFY_SOURCE_REPO",
    "DIFY_SOURCE_MAIN_REF",
    "DIFY_UPSTREAM_BASE_REF",
    *SELF_IMAGE_ARGS,
    *EXTERNAL_IMAGE_ARGS,
    "DIFY_SANDBOX_SOURCE_REF",
}


def dockerfile_args(path: Path) -> dict[str, str]:
    pattern = re.compile(r"^ARG\s+([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
    args: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line.strip())
        if match:
            args[match.group(1)] = match.group(2).strip()
    return args


def check(name: str, ok: bool, actual: str, expected: str) -> dict[str, str | bool]:
    return {"name": name, "ok": ok, "actual": actual, "expected": expected}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check the self GHCR release pin contract and reject placeholders as release-ready."
    )
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[1], type=Path)
    parser.add_argument("--require-final-digest", action="store_true", help="Fail while the intentional placeholder remains.")
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        help="Validate downloaded self image digest JSON artifacts against the selected source SHA and image refs.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of human-readable output")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    dockerfile_text = (repo_root / "Dockerfile").read_text(encoding="utf-8")
    pins = dockerfile_args(repo_root / "Dockerfile")
    checks: list[dict[str, str | bool]] = []
    checks.append(
        check(
            "DIFY_SOURCE_REPO selects the maintained fork",
            pins.get("DIFY_SOURCE_REPO") == SOURCE_REPO,
            pins.get("DIFY_SOURCE_REPO", ""),
            SOURCE_REPO,
        )
    )
    for source_name in ("DIFY_SOURCE_MAIN_REF", "DIFY_UPSTREAM_BASE_REF", "DIFY_SANDBOX_SOURCE_REF"):
        source_value = pins.get(source_name, "")
        checks.append(
            check(
                f"{source_name} is an immutable Git revision",
                bool(re.fullmatch(r"[0-9a-f]{40}", source_value)),
                source_value,
                "40 lowercase hexadecimal Git SHA",
            )
        )
    checks.append(
        check(
            "DIFY_UPSTREAM_BASE_REF preserves the frozen upstream intake",
            pins.get("DIFY_UPSTREAM_BASE_REF") == FROZEN_UPSTREAM_REF,
            pins.get("DIFY_UPSTREAM_BASE_REF", ""),
            FROZEN_UPSTREAM_REF,
        )
    )
    checks.append(
        check(
            "DIFY_SANDBOX_SOURCE_REF preserves the HFS patch source pin",
            pins.get("DIFY_SANDBOX_SOURCE_REF") == SANDBOX_SOURCE_REF,
            pins.get("DIFY_SANDBOX_SOURCE_REF", ""),
            SANDBOX_SOURCE_REF,
        )
    )
    for name, repository in SELF_IMAGE_ARGS.items():
        actual = pins.get(name, "")
        expected = f"{repository}@sha256:<64 lowercase hex>"
        checks.append(check(f"{name} is a digest-pinned self GHCR image", bool(re.fullmatch(re.escape(repository) + r"@sha256:[0-9a-f]{64}", actual)), actual, expected))

    for name in EXTERNAL_IMAGE_ARGS:
        actual = pins.get(name, "")
        checks.append(
            check(
                f"{name} remains immutable",
                bool(re.fullmatch(r"[^@\s]+@sha256:[0-9a-f]{64}", actual)),
                actual,
                "immutable image@sha256:<64 lowercase hex>",
            )
        )

    source_ref = pins.get("DIFY_SOURCE_MAIN_REF", "")
    checks.append(
        check(
            "DIFY_VERSION records the selected self revision",
            pins.get("DIFY_VERSION") == f"BlueSkyXN-dify-main-{source_ref}",
            pins.get("DIFY_VERSION", ""),
            f"BlueSkyXN-dify-main-{source_ref}",
        )
    )
    revision_gate = 'RUN test "${COMMIT_SHA}" = "${DIFY_SOURCE_MAIN_REF}"'
    checks.append(
        check(
            "all four self image stages enforce the common OCI revision",
            dockerfile_text.count(revision_gate) == 4,
            str(dockerfile_text.count(revision_gate)),
            "4",
        )
    )
    checks.append(check("targeted API observability overlay is absent", "observability_service.py" not in dockerfile_text, "absent", "absent"))
    checks.append(check("Agent virtualenv is copied from agent-image", "COPY --from=agent-image --chown=user:user /app/api/.venv /opt/dify-agent/.venv" in dockerfile_text, "Dockerfile", "Agent venv copy"))
    checks.append(check("Agent Go binaries are copied from agent-runtime-image", "COPY --from=agent-runtime-image /usr/local/bin/shellctl /usr/local/bin/shellctl" in dockerfile_text, "Dockerfile", "Agent runtime binary copy"))
    checks.append(check("API virtualenv validates its own sys.prefix", 'assert sys.prefix == "/app/api/.venv"' in dockerfile_text, "Dockerfile", "API sys.prefix assertion"))
    checks.append(check("Agent virtualenv validates its own sys.prefix", 'assert sys.prefix == "/opt/dify-agent/.venv"' in dockerfile_text, "Dockerfile", "Agent sys.prefix assertion"))
    checks.append(check("API virtualenv runs uv pip check", "uv pip check --python /app/api/.venv/bin/python" in dockerfile_text, "Dockerfile", "API uv pip check"))
    checks.append(check("Agent virtualenv runs uv pip check", "uv pip check --python /opt/dify-agent/.venv/bin/python" in dockerfile_text, "Dockerfile", "Agent uv pip check"))

    manifest = tomllib.loads((repo_root / "hfs-dev.toml").read_text(encoding="utf-8"))
    manifest_pins = {item.get("name", "") for item in manifest.get("release_pins", [])}
    missing_manifest_pins = sorted(REQUIRED_HFS_PINS - manifest_pins)
    checks.append(
        check(
            "hfs-dev.toml declares the complete self release pin surface",
            not missing_manifest_pins,
            ",".join(missing_manifest_pins) or "complete",
            "complete",
        )
    )

    if args.artifact_dir:
        artifact_payloads: dict[str, dict[str, object]] = {}
        for artifact_path in args.artifact_dir.resolve().glob("**/*.json"):
            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
            image = payload.get("image")
            if isinstance(image, str):
                artifact_payloads[image] = payload
        for name, repository in SELF_IMAGE_ARGS.items():
            payload = artifact_payloads.get(repository, {})
            selected_digest = pins.get(name, "").partition("@")[2]
            checks.extend(
                [
                    check(
                        f"{name} artifact digest matches the Dockerfile pin",
                        payload.get("digest") == selected_digest,
                        str(payload.get("digest", "missing")),
                        selected_digest,
                    ),
                    check(
                        f"{name} artifact commit_sha matches DIFY_SOURCE_MAIN_REF",
                        payload.get("commit_sha") == source_ref,
                        str(payload.get("commit_sha", "missing")),
                        source_ref,
                    ),
                    check(
                        f"{name} artifact OCI revision matches DIFY_SOURCE_MAIN_REF",
                        payload.get("oci_revision") == source_ref,
                        str(payload.get("oci_revision", "missing")),
                        source_ref,
                    ),
                ]
            )
    if args.require_final_digest:
        checks.append(
            check(
                "DIFY_SOURCE_MAIN_REF has been replaced",
                source_ref != ZERO_SOURCE_REF,
                source_ref,
                "non-placeholder self release SHA",
            )
        )
        for name in SELF_IMAGE_ARGS:
            actual = pins.get(name, "")
            checks.append(check(f"{name} has been replaced", not actual.endswith("@" + PLACEHOLDER_DIGEST), actual, "non-placeholder sha256 digest"))

    ok = all(item["ok"] is True for item in checks)
    has_placeholders = source_ref == ZERO_SOURCE_REF or any(
        pins.get(name, "").endswith("@" + PLACEHOLDER_DIGEST) for name in SELF_IMAGE_ARGS
    )
    notes = []
    if has_placeholders:
        notes.append("The zero source revision and image digests are intentional only until the root task verifies the final self release.")
    else:
        notes.append("The selected self revision and image digests are final release pins, not placeholders.")
    if args.artifact_dir:
        notes.append("Downloaded digest artifacts were checked against the Dockerfile source revision and image refs.")
    else:
        notes.append("Pass --artifact-dir to include downloaded digest artifact commit_sha and OCI revision checks.")
    payload = {
        "ok": ok,
        "checks": checks,
        "notes": notes,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Self release pin check: {'PASS' if ok else 'FAIL'}")
        for item in checks:
            print(f"{'PASS' if item['ok'] else 'FAIL'} {item['name']}")
            if not item["ok"]:
                print(f"  actual:   {item['actual']}")
                print(f"  expected: {item['expected']}")
        for note in payload["notes"]:
            print(f"NOTE {note}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
