#!/usr/bin/env python3
"""Validate and safely install a manifest-selected Dify runtime artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, unquote, urlparse

PROJECT = "dify-all-in-one"
SLOTS = {"edge", "release"}
SCHEMA_VERSION = 2
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
BUCKET_NAMESPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
IMAGE_REF_RE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
MAX_ARCHIVE_MEMBER_COUNT = 100_000
MAX_ARCHIVE_BYTES = 4 * 1024 * 1024 * 1024
MAX_EXTRACTED_BYTES = 32 * 1024 * 1024 * 1024
PRODUCER_REPOSITORY = "https://github.com/BlueSkyXN/dify.git"
ALLOWED_ABSOLUTE_SYMLINKS = {
    "/usr/local/bin/python",
    "/usr/local/bin/python3",
    "/usr/local/bin/python3.12",
}
ALLOWED_EXECUTABLE_SYMLINK_PATHS = {
    "opt/dify-agent/.venv/bin/python",
}


class ContractError(ValueError):
    """The selected artifact is incomplete, unsafe, or inconsistent."""


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _required_string(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise ContractError(f"manifest requires a non-empty {name}")
    return value


def _required_positive_int(payload: dict[str, Any], name: str) -> int:
    value = payload.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ContractError(f"manifest {name} must be a positive integer")
    return value


def parse_manifest_uri(uri: str) -> tuple[str, str, str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "hf" or parsed.netloc != "buckets" or parsed.query or parsed.fragment:
        raise ContractError("DIFY_ARTIFACT_MANIFEST_HF_URI must be an hf://buckets URI without query or fragment")
    parts = [unquote(part) for part in parsed.path.strip("/").split("/")]
    if len(parts) != 5 or any(part in {"", ".", ".."} or "/" in part or "\\" in part for part in parts):
        raise ContractError("artifact manifest URI must contain five safe path segments")
    namespace, bucket, project, slot, filename = parts
    if not BUCKET_NAMESPACE_RE.fullmatch(namespace):
        raise ContractError("artifact manifest URI namespace is invalid")
    if bucket != "hfs-dist" or project != PROJECT or slot not in SLOTS or filename != "manifest.json":
        raise ContractError("artifact manifest URI must select hfs-dist/dify-all-in-one/<edge|release>/manifest.json")
    key = "/".join(parts[2:])
    return namespace, bucket, slot, f"https://huggingface.co/buckets/{quote(namespace, safe='')}/{bucket}/resolve/{quote(key, safe='')}"


def _runtime_root(source_ref: str) -> str:
    return f"dify-runtime-{source_ref}"


def _validate_source_ref(kind: str, source_ref: str, artifact_ref: str) -> None:
    if kind == "commit":
        if not GIT_SHA_RE.fullmatch(source_ref) or source_ref != artifact_ref:
            raise ContractError("commit manifest source_ref and artifact_ref must be the same full lowercase Git SHA")
    elif kind == "tag":
        if source_ref in {"", "latest", "main", "edge", "release"} or not TAG_RE.fullmatch(source_ref) or ".." in source_ref:
            raise ContractError("tag manifest source_ref must be an immutable, safe tag")
        if not GIT_SHA_RE.fullmatch(artifact_ref):
            raise ContractError("tag manifest artifact_ref must be the immutable full Git SHA behind the tag")
    else:
        raise ContractError("manifest source_kind must be commit or tag")


def load_manifest(path: Path, manifest_uri: str, expected_source_ref: str = "", max_bytes: int | None = None) -> dict[str, str]:
    namespace, bucket, uri_slot, _manifest_url = parse_manifest_uri(manifest_uri)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("artifact manifest is not valid UTF-8 JSON") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
        raise ContractError(f"artifact manifest schema_version must be {SCHEMA_VERSION}")
    if raw.get("project") != PROJECT or raw.get("slot") != uri_slot:
        raise ContractError("artifact manifest project or slot does not match its URI")

    source_kind = _required_string(raw, "source_kind")
    source_ref = _required_string(raw, "source_ref")
    artifact_ref = _required_string(raw, "artifact_ref")
    _validate_source_ref(source_kind, source_ref, artifact_ref)
    if expected_source_ref:
        if not GIT_SHA_RE.fullmatch(expected_source_ref) or expected_source_ref != artifact_ref:
            raise ContractError("DIFY_ARTIFACT_EXPECTED_SOURCE_REF must be the selected full lowercase artifact_ref")

    artifact = _required_string(raw, "artifact")
    expected_artifact = f"dify-runtime-{artifact_ref}.tar.gz"
    if artifact != expected_artifact:
        raise ContractError("artifact filename must exactly contain the immutable artifact_ref")
    artifact_sha256 = _required_string(raw, "sha256")
    if not SHA256_RE.fullmatch(artifact_sha256):
        raise ContractError("manifest sha256 must be a lowercase SHA-256 digest")
    size = _required_positive_int(raw, "size_bytes")
    if size > MAX_ARCHIVE_BYTES:
        raise ContractError("manifest artifact size exceeds the fixed 4 GiB archive limit")
    if max_bytes is not None and (max_bytes <= 0 or size > max_bytes):
        raise ContractError("manifest artifact size exceeds DIFY_ARTIFACT_MAX_BYTES")
    unpacked_size = _required_positive_int(raw, "unpacked_size_bytes")
    if unpacked_size > MAX_EXTRACTED_BYTES:
        raise ContractError("manifest unpacked_size_bytes exceeds the artifact safety limit")
    generated_at = _required_string(raw, "generated_at")
    if not TIMESTAMP_RE.fullmatch(generated_at):
        raise ContractError("manifest generated_at must be a UTC ISO-8601 timestamp")
    try:
        datetime.strptime(generated_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ContractError("manifest generated_at is not a valid timestamp") from exc

    lock_sha256 = _required_string(raw, "runtime_lock_sha256")
    if not SHA256_RE.fullmatch(lock_sha256):
        raise ContractError("manifest runtime_lock_sha256 must be a lowercase SHA-256 digest")
    prefix = f"{PROJECT}/{uri_slot}"
    if raw.get("artifact_key") != f"{prefix}/{artifact}" or raw.get("manifest_key") != f"{prefix}/manifest.json":
        raise ContractError("manifest artifact_key or manifest_key does not match the selected slot")

    return {
        "schema_version": str(SCHEMA_VERSION),
        "namespace": namespace,
        "bucket": bucket,
        "slot": uri_slot,
        "source_kind": source_kind,
        "source_ref": source_ref,
        "artifact_ref": artifact_ref,
        "artifact": artifact,
        "artifact_key": f"{prefix}/{artifact}",
        "artifact_url": f"https://huggingface.co/buckets/{quote(namespace, safe='')}/{bucket}/resolve/{quote(f'{prefix}/{artifact}', safe='')}",
        "sha256": artifact_sha256,
        "size_bytes": str(size),
        "unpacked_size_bytes": str(unpacked_size),
        "runtime_lock_sha256": lock_sha256,
        "generated_at": generated_at,
    }


def _is_safe_member_path(name: str, artifact_root: str) -> bool:
    path = PurePosixPath(name.rstrip("/"))
    return bool(path.parts) and not path.is_absolute() and ".." not in path.parts and path.parts[0] == artifact_root


def _validate_link(member: tarfile.TarInfo, artifact_root: str) -> None:
    target = member.linkname
    if not target:
        raise ContractError("artifact archive contains an empty symlink")
    if target.startswith("/"):
        if target not in ALLOWED_ABSOLUTE_SYMLINKS:
            raise ContractError("artifact archive contains a disallowed absolute symlink")
        return
    member_parent = PurePosixPath(member.name).parent
    resolved = member_parent.joinpath(target)
    normalized: list[str] = []
    for part in resolved.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not normalized:
                raise ContractError("artifact archive symlink escapes the runtime root")
            normalized.pop()
        else:
            normalized.append(part)
    if not normalized or normalized[0] != artifact_root:
        raise ContractError("artifact archive symlink escapes the runtime root")


def _validate_runtime_lock(root: Path, provenance: dict[str, str]) -> None:
    lock_path = root / "runtime-lock.json"
    if not lock_path.is_file() or sha256_file(lock_path) != provenance["runtime_lock_sha256"]:
        raise ContractError("runtime-lock.json is missing or does not match manifest provenance")
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("runtime-lock.json is not valid UTF-8 JSON") from exc
    if not isinstance(lock, dict) or lock.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("runtime-lock.json has an unsupported schema_version")
    if lock.get("project") != PROJECT or lock.get("artifact_ref") != provenance["artifact_ref"]:
        raise ContractError("runtime-lock.json provenance does not match the selected artifact")
    source = lock.get("source")
    if not isinstance(source, dict) or source != {
        "kind": provenance["source_kind"],
        "ref": provenance["source_ref"],
        "repository": PRODUCER_REPOSITORY,
    }:
        raise ContractError("runtime-lock.json source provenance does not match the selected manifest")
    components = lock.get("components")
    if not isinstance(components, dict):
        raise ContractError("runtime-lock.json components must be an object")
    required_components = {"api", "web", "agent", "plugin_daemon", "sandbox"}
    if set(components) != required_components:
        raise ContractError("runtime-lock.json must cover api, web, agent, plugin_daemon, and sandbox")

    for name in {"api", "web"}:
        item = components[name]
        if not isinstance(item, dict) or item.get("source_ref") != provenance["artifact_ref"] or not IMAGE_REF_RE.fullmatch(str(item.get("image_ref", ""))):
            raise ContractError(f"runtime-lock.json {name} must bind the artifact commit and an immutable image digest")

    agent = components["agent"]
    if (
        not isinstance(agent, dict)
        or agent.get("source_ref") != provenance["artifact_ref"]
        or not IMAGE_REF_RE.fullmatch(str(agent.get("image_ref", "")))
        or not IMAGE_REF_RE.fullmatch(str(agent.get("runtime_image_ref", "")))
    ):
        raise ContractError("runtime-lock.json agent must bind the artifact commit and immutable image digests")

    plugin = components["plugin_daemon"]
    if (
        not isinstance(plugin, dict)
        or not IMAGE_REF_RE.fullmatch(str(plugin.get("source_ref", "")))
        or plugin.get("source_ref") != plugin.get("image_ref")
    ):
        raise ContractError("runtime-lock.json plugin_daemon must bind an immutable image digest")

    sandbox = components["sandbox"]
    if (
        not isinstance(sandbox, dict)
        or not GIT_SHA_RE.fullmatch(str(sandbox.get("source_ref", "")))
        or not IMAGE_REF_RE.fullmatch(str(sandbox.get("image_ref", "")))
        or sandbox.get("privilege_launcher") != "image-built root-owned setuid launcher"
    ):
        raise ContractError("runtime-lock.json sandbox must bind immutable source/image provenance and the fixed launcher")


def _required_runtime_paths(root: Path) -> tuple[set[Path], set[Path]]:
    directories = {
        root / "app/targets/next",
        root / "app/targets/vinext",
        root / "conf",
        root / "dependencies",
    }
    executables = {
        root / "app/api/.venv/bin/flask",
        root / "app/api/docker/entrypoint.sh",
        root / "app/entrypoint.sh",
        root / "opt/dify-agent/.venv/bin/python",
        root / "usr/local/bin/shellctl",
        root / "usr/local/bin/shellctl-runner",
        root / "usr/local/bin/shellctl-runner-exit",
        root / "usr/local/bin/shellctl-sanitize-pty",
        root / "usr/local/bin/dify-agent",
        root / "opt/dify/plugin-daemon/commandline",
        root / "opt/dify/plugin-daemon/main",
        root / "opt/dify/sandbox/main",
    }
    return directories, executables


def _is_valid_runtime_executable(root: Path, path: Path) -> bool:
    if path.is_symlink():
        relative = path.relative_to(root).as_posix()
        return (
            relative in ALLOWED_EXECUTABLE_SYMLINK_PATHS
            and os.readlink(path) in ALLOWED_ABSOLUTE_SYMLINKS
        )
    return path.is_file() and os.access(path, os.X_OK)


def _validate_runtime_layout(root: Path) -> None:
    directories, executables = _required_runtime_paths(root)
    regular_files = {root / "BUILD_INFO.txt", root / "runtime-lock.json"}
    if any(not path.is_dir() or path.is_symlink() for path in directories):
        raise ContractError("artifact archive is missing required runtime directories")
    if any(not _is_valid_runtime_executable(root, path) for path in executables):
        raise ContractError("artifact archive is missing required executable runtime files")
    if any(not path.is_file() or path.is_symlink() for path in regular_files):
        raise ContractError("artifact archive is missing required regular runtime files")


def _read_validated_members(archive: tarfile.TarFile, artifact_root: str, expected_unpacked_size: int) -> list[tarfile.TarInfo]:
    members: list[tarfile.TarInfo] = []
    member_names: set[str] = set()
    total_size = 0
    for member in archive:
        if len(members) >= MAX_ARCHIVE_MEMBER_COUNT:
            raise ContractError("artifact archive contains too many members")
        if member.name in member_names:
            raise ContractError("artifact archive contains duplicate member paths")
        member_names.add(member.name)
        if not _is_safe_member_path(member.name, artifact_root):
            raise ContractError("artifact archive contains an unsafe or unexpected path")
        if member.islnk() or member.isdev() or member.isfifo():
            raise ContractError("artifact archive contains hard links, devices, or FIFOs")
        if member.issym():
            _validate_link(member, artifact_root)
        elif member.isfile():
            total_size += member.size
            if total_size > MAX_EXTRACTED_BYTES:
                raise ContractError("artifact archive exceeds the extracted-size safety limit")
        elif not member.isdir():
            raise ContractError("artifact archive contains an unsupported member type")
        members.append(member)
    if total_size != expected_unpacked_size:
        raise ContractError("artifact archive unpacked size does not match the selected manifest")
    return members


def _atomically_activate_runtime(extracted: Path, install_root: Path, provenance: dict[str, str]) -> None:
    parent = install_root.parent
    release_root = parent / f".{install_root.name}-release-{provenance['artifact_ref']}-{uuid.uuid4().hex}"
    link_path = parent / f".{install_root.name}-next-{uuid.uuid4().hex}"
    legacy_path: Path | None = None
    try:
        os.replace(extracted, release_root)
        os.symlink(release_root.name, link_path)
        if install_root.exists() or install_root.is_symlink():
            if install_root.is_symlink():
                pass
            elif install_root.is_dir():
                legacy_path = parent / f".{install_root.name}-legacy-{uuid.uuid4().hex}"
                os.replace(install_root, legacy_path)
            else:
                raise ContractError("artifact install root is not a directory or symlink")
        try:
            os.replace(link_path, install_root)
        except OSError:
            if legacy_path is not None and legacy_path.exists() and not install_root.exists():
                os.replace(legacy_path, install_root)
            raise
    except OSError as exc:
        raise ContractError("artifact runtime activation failed without replacing the active runtime") from exc
    finally:
        if link_path.exists() or link_path.is_symlink():
            link_path.unlink(missing_ok=True)


def validate_and_extract(
    manifest_path: Path,
    manifest_uri: str,
    artifact_path: Path,
    install_root: Path,
    expected_source_ref: str = "",
    max_bytes: int | None = None,
) -> dict[str, str]:
    provenance = load_manifest(manifest_path, manifest_uri, expected_source_ref, max_bytes)
    if artifact_path.stat().st_size != int(provenance["size_bytes"]):
        raise ContractError("artifact size does not match the selected manifest")
    if sha256_file(artifact_path) != provenance["sha256"]:
        raise ContractError("artifact checksum does not match the single selected manifest")

    artifact_root = _runtime_root(provenance["artifact_ref"])
    parent = install_root.parent
    stage = parent / f".{install_root.name}-stage-{uuid.uuid4().hex}"
    shutil.rmtree(stage, ignore_errors=True)
    try:
        with tarfile.open(artifact_path, "r:gz") as archive:
            members = _read_validated_members(archive, artifact_root, int(provenance["unpacked_size_bytes"]))
            stage.mkdir(mode=0o700, parents=True)
            for member in members:
                # Members were fully checked above, including each symlink target.
                archive.extract(member, stage)
        extracted = stage / artifact_root
        if not extracted.is_dir():
            raise ContractError("artifact archive root is missing")
        _validate_runtime_layout(extracted)
        _validate_runtime_lock(extracted, provenance)
        (extracted / "MANIFEST_PROVENANCE.json").write_text(
            json.dumps(provenance, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
        _atomically_activate_runtime(extracted, install_root, provenance)
    except (OSError, tarfile.TarError) as exc:
        raise ContractError("artifact archive cannot be safely extracted") from exc
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return provenance


def self_test() -> None:
    source_ref = "a" * 40
    root_name = _runtime_root(source_ref)
    uri = "hf://buckets/example/hfs-dist/dify-all-in-one/edge/manifest.json"
    with tempfile.TemporaryDirectory() as temp:
        temp_path = Path(temp)
        root = temp_path / root_name
        directories, executables = _required_runtime_paths(root)
        for path in directories:
            path.mkdir(parents=True, exist_ok=True)
        for path in executables | {root / "BUILD_INFO.txt", root / "runtime-lock.json"}:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("ok", encoding="utf-8")
            path.chmod(0o755)
        image_ref = "example.invalid/component@sha256:" + "b" * 64
        components = {
            "api": {"source_ref": source_ref, "image_ref": image_ref},
            "web": {"source_ref": source_ref, "image_ref": image_ref},
            "agent": {"source_ref": source_ref, "image_ref": image_ref, "runtime_image_ref": image_ref},
            "plugin_daemon": {"source_ref": image_ref, "image_ref": image_ref},
            "sandbox": {
                "source_ref": source_ref,
                "image_ref": image_ref,
                "privilege_launcher": "image-built root-owned setuid launcher",
            },
        }
        lock = {
            "schema_version": SCHEMA_VERSION,
            "project": PROJECT,
            "artifact_ref": source_ref,
            "source": {"kind": "commit", "ref": source_ref, "repository": PRODUCER_REPOSITORY},
            "components": components,
        }
        lock_path = root / "runtime-lock.json"
        lock_path.write_text(json.dumps(lock, sort_keys=True), encoding="utf-8")
        artifact = temp_path / f"dify-runtime-{source_ref}.tar.gz"
        with tarfile.open(artifact, "w:gz") as archive:
            archive.add(root, arcname=root_name)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "project": PROJECT,
            "slot": "edge",
            "source_kind": "commit",
            "source_ref": source_ref,
            "artifact_ref": source_ref,
            "artifact": artifact.name,
            "sha256": sha256_file(artifact),
            "size_bytes": artifact.stat().st_size,
            "unpacked_size_bytes": sum(path.stat().st_size for path in root.rglob("*") if path.is_file()),
            "runtime_lock_sha256": sha256_file(lock_path),
            "generated_at": "2026-07-26T00:00:00Z",
            "artifact_key": f"{PROJECT}/edge/{artifact.name}",
            "manifest_key": f"{PROJECT}/edge/manifest.json",
        }
        manifest_path = temp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        installed = temp_path / "installed"
        result = validate_and_extract(manifest_path, uri, artifact, installed)
        assert result["artifact_ref"] == source_ref
        assert installed.is_symlink()
        manifest["artifact"] = "dify-runtime-latest.tar.gz"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        try:
            load_manifest(manifest_path, uri)
        except ContractError:
            pass
        else:
            raise AssertionError("mutable artifact filename was accepted")
    print("PASS Dify artifact manifest and archive contract self-test")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--manifest-uri", default="")
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--install-root", type=Path)
    parser.add_argument("--expected-source-ref", default="")
    parser.add_argument("--max-bytes", type=int)
    parser.add_argument("--print-artifact-url", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
            return 0
        if not args.manifest or not args.manifest_uri:
            raise ContractError("--manifest and --manifest-uri are required")
        if args.max_bytes is not None and args.max_bytes <= 0:
            raise ContractError("--max-bytes must be a positive integer")
        provenance = load_manifest(args.manifest, args.manifest_uri, args.expected_source_ref, args.max_bytes)
        if args.print_artifact_url:
            print(provenance["artifact_url"])
            return 0
        if not args.artifact or not args.install_root:
            raise ContractError("--artifact and --install-root are required for installation")
        validate_and_extract(args.manifest, args.manifest_uri, args.artifact, args.install_root, args.expected_source_ref, args.max_bytes)
        return 0
    except ContractError as exc:
        print(f"Dify artifact bootstrap failed: {exc}", flush=True)
        return 64


if __name__ == "__main__":
    raise SystemExit(main())
