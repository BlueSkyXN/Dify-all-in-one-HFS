#!/usr/bin/env python3
"""Package a preassembled Dify runtime directory as an immutable HFS artifact.

This repository is a consumer/wrapper. The approved Dify fork producer assembles
its matching API, Web, Agent, Plugin Daemon, and Sandbox payload before invoking
this script. The script performs no network access and never publishes artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docker"))
from dify_artifact_contract import MAX_ARCHIVE_BYTES  # noqa: E402

PROJECT = "dify-all-in-one"
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
IMAGE_REF_RE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
SCHEMA_VERSION = 2
PRODUCER_REPOSITORY = "https://github.com/BlueSkyXN/dify.git"


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require_path(root: Path, relative: str, executable: bool = False) -> Path:
    path = root / relative
    if not path.exists():
        raise ValueError(f"runtime payload is missing {relative}")
    if executable and not os.access(path, os.X_OK):
        raise ValueError(f"runtime payload {relative} must be executable")
    return path


def validate_inputs(args: argparse.Namespace) -> None:
    if not GIT_SHA_RE.fullmatch(args.source_ref):
        raise ValueError("--source-ref must be a full lowercase Git SHA")
    if args.slot not in {"edge", "release"}:
        raise ValueError("--slot must be edge or release")
    if args.source_kind not in {"commit", "tag"}:
        raise ValueError("--source-kind must be commit or tag")
    if args.source_kind == "commit" and args.source_name != args.source_ref:
        raise ValueError("commit artifacts require --source-name equal to --source-ref")
    if args.source_kind == "tag" and (
        args.source_name in {"", "latest", "main", "edge", "release"}
        or not TAG_RE.fullmatch(args.source_name)
        or ".." in args.source_name
    ):
        raise ValueError("tag artifacts require an immutable, safe --source-name")
    if args.source_repository != PRODUCER_REPOSITORY:
        raise ValueError(f"--source-repository must be {PRODUCER_REPOSITORY}")
    for name in ("api_image_ref", "web_image_ref", "agent_image_ref", "agent_runtime_image_ref", "plugin_daemon_image_ref", "sandbox_image_ref"):
        value = getattr(args, name)
        if not IMAGE_REF_RE.fullmatch(value):
            raise ValueError(f"--{name.replace('_', '-')} must be image@sha256:<64 lowercase hex>")
    if not GIT_SHA_RE.fullmatch(args.sandbox_source_ref):
        raise ValueError("--sandbox-source-ref must be a full lowercase Git SHA")


def build_lock(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "project": PROJECT,
        "artifact_ref": args.source_ref,
        "source": {"kind": args.source_kind, "ref": args.source_name, "repository": args.source_repository},
        "components": {
            "api": {"source_ref": args.source_ref, "image_ref": args.api_image_ref},
            "web": {"source_ref": args.source_ref, "image_ref": args.web_image_ref},
            "agent": {
                "source_ref": args.source_ref,
                "image_ref": args.agent_image_ref,
                "runtime_image_ref": args.agent_runtime_image_ref,
            },
            "plugin_daemon": {"source_ref": args.plugin_daemon_image_ref, "image_ref": args.plugin_daemon_image_ref},
            "sandbox": {
                "source_ref": args.sandbox_source_ref,
                "image_ref": args.sandbox_image_ref,
                "privilege_launcher": "image-built root-owned setuid launcher",
            },
        },
    }


def populate_runtime_tree(source: Path, destination: Path, lock: dict[str, Any], args: argparse.Namespace) -> None:
    paths = (
        "app/api",
        "app/targets",
        "app/entrypoint.sh",
        "opt/dify-agent/.venv",
        "opt/dify/plugin-daemon",
        "opt/dify/sandbox/main",
        "usr/local/bin/shellctl",
        "usr/local/bin/shellctl-runner",
        "usr/local/bin/shellctl-runner-exit",
        "usr/local/bin/shellctl-sanitize-pty",
        "usr/local/bin/dify-agent",
        "usr/local/share/nltk_data",
        "conf",
        "dependencies",
    )
    executable = {
        "app/entrypoint.sh",
        "app/api/docker/entrypoint.sh",
        "opt/dify/plugin-daemon/commandline",
        "opt/dify/plugin-daemon/main",
        "opt/dify/sandbox/main",
        "usr/local/bin/shellctl",
        "usr/local/bin/shellctl-runner",
        "usr/local/bin/shellctl-runner-exit",
        "usr/local/bin/shellctl-sanitize-pty",
        "usr/local/bin/dify-agent",
    }
    for item in paths:
        source_path = require_path(source, item)
        target = destination / item
        target.parent.mkdir(parents=True, exist_ok=True)
        if source_path.is_dir():
            shutil.copytree(source_path, target, symlinks=True)
        else:
            shutil.copy2(source_path, target, follow_symlinks=False)
    for item in executable:
        require_path(destination, item, executable=True)
    require_path(destination, "app/targets/next")
    require_path(destination, "app/targets/vinext")
    for item in (
        "usr/local/share/nltk_data/tokenizers/punkt_tab",
        "usr/local/share/nltk_data/taggers/averaged_perceptron_tagger_eng",
        "usr/local/share/nltk_data/corpora/stopwords",
    ):
        resource = require_path(destination, item)
        if not resource.is_dir() or not any(path.is_file() for path in resource.rglob("*")):
            raise ValueError(f"runtime payload NLTK resource must contain regular files: {item}")
    (destination / "runtime-lock.json").write_text(json.dumps(lock, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (destination / "BUILD_INFO.txt").write_text(
        "\n".join(
            (
                "Dify all-in-one runtime artifact",
                f"source_kind={args.source_kind}",
                f"source_ref={args.source_name}",
                f"artifact_ref={args.source_ref}",
                f"source_repository={args.source_repository}",
            )
        )
        + "\n",
        encoding="utf-8",
    )


def normalized_tar(source_parent: Path, root_name: str, output: Path, epoch: int) -> None:
    with tarfile.open(output, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        for path in sorted((source_parent / root_name).rglob("*"), key=lambda item: item.as_posix()):
            arcname = path.relative_to(source_parent).as_posix()
            info = archive.gettarinfo(path, arcname)
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = epoch
            if info.isfile():
                with path.open("rb") as stream:
                    archive.addfile(info, stream)
            else:
                archive.addfile(info)


def archive_unpacked_size(artifact: Path) -> int:
    with tarfile.open(artifact, "r:gz") as archive:
        return sum(member.size for member in archive if member.isfile())


def package(args: argparse.Namespace) -> tuple[Path, Path]:
    validate_inputs(args)
    source = args.runtime_root.resolve()
    if not source.is_dir():
        raise ValueError("--runtime-root must be an existing prepared runtime directory")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    root_name = f"dify-runtime-{args.source_ref}"
    artifact = output / f"{root_name}.tar.gz"
    manifest = output / "manifest.json"
    with tempfile.TemporaryDirectory(prefix="dify-runtime-package-") as temp:
        staging_parent = Path(temp)
        staging_root = staging_parent / root_name
        lock = build_lock(args)
        populate_runtime_tree(source, staging_root, lock, args)
        normalized_tar(staging_parent, root_name, artifact, args.source_date_epoch)
        lock_sha256 = sha256_file(staging_root / "runtime-lock.json")
    if artifact.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("packaged artifact exceeds the fixed 4 GiB archive limit")
    generated_at = datetime.fromtimestamp(args.source_date_epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "project": PROJECT,
        "slot": args.slot,
        "source_kind": args.source_kind,
        "source_ref": args.source_name,
        "artifact_ref": args.source_ref,
        "artifact": artifact.name,
        "sha256": sha256_file(artifact),
        "size_bytes": artifact.stat().st_size,
        "unpacked_size_bytes": archive_unpacked_size(artifact),
        "runtime_lock_sha256": lock_sha256,
        "generated_at": generated_at,
        "artifact_key": f"{PROJECT}/{args.slot}/{artifact.name}",
        "manifest_key": f"{PROJECT}/{args.slot}/manifest.json",
    }
    manifest.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (output / "SHA256SUMS.txt").write_text(f"{payload['sha256']}  {artifact.name}\n", encoding="utf-8")
    return artifact, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--slot", choices=("edge", "release"), required=True)
    parser.add_argument("--source-kind", choices=("commit", "tag"), required=True)
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--source-repository", default="https://github.com/BlueSkyXN/dify.git")
    parser.add_argument("--source-date-epoch", type=int, required=True)
    parser.add_argument("--api-image-ref", required=True)
    parser.add_argument("--web-image-ref", required=True)
    parser.add_argument("--agent-image-ref", required=True)
    parser.add_argument("--agent-runtime-image-ref", required=True)
    parser.add_argument("--plugin-daemon-image-ref", required=True)
    parser.add_argument("--sandbox-image-ref", required=True)
    parser.add_argument("--sandbox-source-ref", required=True)
    args = parser.parse_args()
    try:
        artifact, manifest = package(args)
    except (OSError, ValueError) as exc:
        print(f"artifact packaging failed: {exc}", file=os.sys.stderr)
        return 2
    print(json.dumps({"artifact": str(artifact), "manifest": str(manifest)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
