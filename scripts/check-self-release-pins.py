#!/usr/bin/env python3
"""Validate the self GHCR release pin contract without contacting a registry."""

from __future__ import annotations

import argparse
import json
import re
import sys
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
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of human-readable output")
    args = parser.parse_args()

    pins = dockerfile_args(args.repo_root.resolve() / "Dockerfile")
    checks: list[dict[str, str | bool]] = []
    checks.append(
        check(
            "DIFY_SOURCE_REPO selects the maintained fork",
            pins.get("DIFY_SOURCE_REPO") == SOURCE_REPO,
            pins.get("DIFY_SOURCE_REPO", ""),
            SOURCE_REPO,
        )
    )
    for source_name in ("DIFY_SOURCE_MAIN_REF", "DIFY_UPSTREAM_BASE_REF"):
        source_value = pins.get(source_name, "")
        checks.append(
            check(
                f"{source_name} is an immutable Git revision",
                bool(re.fullmatch(r"[0-9a-f]{40}", source_value)),
                source_value,
                "40 lowercase hexadecimal Git SHA",
            )
        )
    for name, repository in SELF_IMAGE_ARGS.items():
        actual = pins.get(name, "")
        expected = f"{repository}@sha256:<64 lowercase hex>"
        checks.append(check(f"{name} is a digest-pinned self GHCR image", bool(re.fullmatch(re.escape(repository) + r"@sha256:[0-9a-f]{64}", actual)), actual, expected))

    checks.append(check("targeted API observability overlay is absent", "observability_service.py" not in (args.repo_root.resolve() / "Dockerfile").read_text(encoding="utf-8"), "absent", "absent"))
    checks.append(check("Agent virtualenv is copied from agent-image", "COPY --from=agent-image --chown=user:user /app/api/.venv /opt/dify-agent/.venv" in (args.repo_root.resolve() / "Dockerfile").read_text(encoding="utf-8"), "Dockerfile", "Agent venv copy"))
    checks.append(check("Agent Go binaries are copied from agent-runtime-image", "COPY --from=agent-runtime-image /usr/local/bin/shellctl /usr/local/bin/shellctl" in (args.repo_root.resolve() / "Dockerfile").read_text(encoding="utf-8"), "Dockerfile", "Agent runtime binary copy"))
    if args.require_final_digest:
        source_ref = pins.get("DIFY_SOURCE_MAIN_REF", "")
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
    payload = {
        "ok": ok,
        "checks": checks,
        "notes": [
            "The zero source revision and image digests are intentional until the root task verifies the final self release.",
            "Run with --require-final-digest only after replacing the self revision and every self image digest.",
        ],
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
