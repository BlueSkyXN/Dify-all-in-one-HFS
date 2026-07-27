#!/usr/bin/env python3
"""Create a slot manifest for a verified immutable Dify runtime archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docker"))
from dify_artifact_contract import MAX_ARCHIVE_BYTES  # noqa: E402

PROJECT = "dify-all-in-one"
SCHEMA_VERSION = 2
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def runtime_lock_hash(artifact: Path, ref: str) -> str:
    expected = f"dify-runtime-{ref}/runtime-lock.json"
    with tarfile.open(artifact, "r:gz") as archive:
        member = archive.getmember(expected)
        if member.issym() or member.islnk() or not member.isfile():
            raise ValueError("runtime-lock.json must be a regular archive member")
        stream = archive.extractfile(member)
        if stream is None:
            raise ValueError("runtime-lock.json cannot be read")
        raw = stream.read()
    lock = json.loads(raw.decode("utf-8"))
    if not isinstance(lock, dict) or lock.get("schema_version") != SCHEMA_VERSION or lock.get("project") != PROJECT or lock.get("artifact_ref") != ref:
        raise ValueError("runtime-lock.json does not bind the selected artifact ref")
    return hashlib.sha256(raw).hexdigest()


def archive_unpacked_size(artifact: Path) -> int:
    with tarfile.open(artifact, "r:gz") as archive:
        return sum(member.size for member in archive if member.isfile())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--slot", choices=("edge", "release"), required=True)
    parser.add_argument("--source-kind", choices=("commit", "tag"), required=True)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--artifact-ref", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    try:
        if not GIT_SHA_RE.fullmatch(args.artifact_ref):
            raise ValueError("--artifact-ref must be a full lowercase Git SHA")
        if args.source_kind == "commit" and args.source_ref != args.artifact_ref:
            raise ValueError("commit source-ref must equal artifact-ref")
        if args.source_kind == "tag" and (
            args.source_ref in {"", "latest", "main", "edge", "release"}
            or not TAG_RE.fullmatch(args.source_ref)
            or ".." in args.source_ref
        ):
            raise ValueError("tag source-ref must be an immutable, safe tag")
        expected_name = f"dify-runtime-{args.artifact_ref}.tar.gz"
        if args.artifact.name != expected_name:
            raise ValueError("artifact filename must exactly match artifact-ref")
        if args.artifact.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ValueError("artifact exceeds the fixed 4 GiB archive limit")
        generated_at = args.generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        datetime.strptime(generated_at, "%Y-%m-%dT%H:%M:%SZ")
        digest = sha256(args.artifact)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "project": PROJECT,
            "slot": args.slot,
            "source_kind": args.source_kind,
            "source_ref": args.source_ref,
            "artifact_ref": args.artifact_ref,
            "artifact": expected_name,
            "sha256": digest,
            "size_bytes": args.artifact.stat().st_size,
            "unpacked_size_bytes": archive_unpacked_size(args.artifact),
            "runtime_lock_sha256": runtime_lock_hash(args.artifact, args.artifact_ref),
            "generated_at": generated_at,
            "artifact_key": f"{PROJECT}/{args.slot}/{expected_name}",
            "manifest_key": f"{PROJECT}/{args.slot}/manifest.json",
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, KeyError, UnicodeDecodeError, ValueError, tarfile.TarError, json.JSONDecodeError) as exc:
        print(f"manifest preparation failed: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
