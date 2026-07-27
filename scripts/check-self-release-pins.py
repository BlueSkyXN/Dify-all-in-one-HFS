#!/usr/bin/env python3
"""Compatibility entry point for the Dify runtime artifact provenance contract.

The former image-assembly checker kept this filename. Artifact delivery now
validates component pins in runtime-lock.json rather than Dockerfile ARGs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docker"))
from dify_artifact_contract import ContractError, load_manifest, validate_and_extract  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--manifest-uri", default="")
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--install-root", type=Path)
    parser.add_argument("--expected-source-ref", default="")
    parser.add_argument("--require-final-digest", action="store_true", help="Legacy alias; artifact SHA-256 is always required.")
    args = parser.parse_args()
    try:
        if not args.manifest:
            from dify_artifact_contract import self_test

            self_test()
            return 0
        if not args.manifest_uri or not args.artifact or not args.install_root:
            raise ContractError("--manifest, --manifest-uri, --artifact, and --install-root are required together")
        validate_and_extract(args.manifest, args.manifest_uri, args.artifact, args.install_root, args.expected_source_ref)
        return 0
    except ContractError as exc:
        print(f"Runtime artifact pin check failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
