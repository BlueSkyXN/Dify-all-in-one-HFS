#!/usr/bin/env python3
"""Export and verify an exact-commit, allowlisted HFS wrapper bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "hfs-space-bundle.json"
LOWER_SHA = re.compile(r"[0-9a-f]{40}")
CHECKSUM_LINE = re.compile(r"([0-9a-f]{64})  ([^\r\n]+)")
TOKEN_LITERAL = re.compile(
    r"(?:hf_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})"
)
GENERATED_PATHS = {"BUILD_SOURCE.json", "SHA256SUMS"}


class BundleError(RuntimeError):
    """A value-safe bundle validation error."""


def _safe_relative(value: str, *, label: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise BundleError(f"{label} must be a safe relative POSIX path")
    return path.as_posix()


def load_config() -> dict[str, Any]:
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleError("hfs-space-bundle.json is not valid UTF-8 JSON") from exc
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise BundleError("hfs-space-bundle.json must use schema_version 1")
    repository = config.get("wrapper_repository")
    if not isinstance(repository, str) or not repository.startswith("https://github.com/"):
        raise BundleError("wrapper_repository must be an HTTPS GitHub repository")
    profiles = config.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise BundleError("profiles must be a non-empty object")
    for name, profile in profiles.items():
        if not isinstance(name, str) or not isinstance(profile, dict):
            raise BundleError("profiles contain an invalid entry")
        _safe_relative(str(profile.get("manifest", "")), label="profile manifest")
        space = profile.get("space")
        if not isinstance(space, str) or space.count("/") != 1:
            raise BundleError("profile space must be an owner/name id")
    mapping = config.get("source_to_bundle")
    if not isinstance(mapping, dict) or not mapping:
        raise BundleError("source_to_bundle must be a non-empty object")
    sources: set[str] = set()
    destinations: set[str] = set()
    for source, destination in mapping.items():
        source = _safe_relative(str(source), label="source path")
        destination = _safe_relative(str(destination), label="bundle path")
        if source in sources or destination in destinations or destination in GENERATED_PATHS:
            raise BundleError("source_to_bundle contains a duplicate or reserved path")
        sources.add(source)
        destinations.add(destination)
    for profile in profiles.values():
        if profile["manifest"] not in sources:
            raise BundleError("every profile manifest must be an allowlisted source")
        if mapping[profile["manifest"]] != "hfs-dev.toml":
            raise BundleError("the selected manifest must map to bundle hfs-dev.toml")
    return config


def _git(*args: str, text: bool = True) -> str | bytes:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=text,
        check=False,
    )
    if result.returncode != 0:
        raise BundleError(f"Git command failed: git {' '.join(args)}")
    return result.stdout


def require_commit_object(source_commit: str) -> None:
    if not LOWER_SHA.fullmatch(source_commit):
        raise BundleError("--source-commit must be a full lowercase Git SHA")
    object_type = str(_git("cat-file", "-t", source_commit)).strip()
    if object_type != "commit":
        raise BundleError(
            f"--source-commit must identify a Git commit; got object type {object_type or 'unknown'}"
        )


def require_source_commit(source_commit: str) -> None:
    require_commit_object(source_commit)
    if str(_git("rev-parse", "HEAD")).strip() != source_commit:
        raise BundleError("source commit must equal checkout HEAD")
    if str(_git("status", "--porcelain=v1", "--untracked-files=all")):
        raise BundleError("refusing to export a dirty checkout")


def tree_mode(source_commit: str, source_path: str) -> int:
    output = str(_git("ls-tree", source_commit, "--", source_path)).strip()
    match = re.fullmatch(r"(100644|100755) blob [0-9a-f]{40}\t(.+)", output)
    if not match or match.group(2) != source_path:
        raise BundleError(f"required tracked input is missing or unsafe: {source_path}")
    return 0o755 if match.group(1) == "100755" else 0o644


def blob(source_commit: str, source_path: str) -> bytes:
    return _git("show", f"{source_commit}:{source_path}", text=False)  # type: ignore[return-value]


def write_file(path: Path, payload: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    path.write_bytes(payload)
    path.chmod(mode)


def expected_paths(config: dict[str, Any]) -> set[str]:
    return set(config["source_to_bundle"].values()) | GENERATED_PATHS


def validate_manifest(payload: bytes, expected_space: str) -> None:
    try:
        manifest = tomllib.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise BundleError("selected manifest is not valid UTF-8 TOML") from exc
    if manifest.get("standard") != "2.0" or manifest.get("space") != expected_space:
        raise BundleError("selected manifest does not identify HFS 2.0 and the fixed profile Space")


def source_entry(source_path: str, bundle_path: str, payload: bytes, mode: int) -> dict[str, Any]:
    return {
        "source_path": source_path,
        "bundle_path": bundle_path,
        "mode": f"{mode:04o}",
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def write_checksums(bundle: Path, paths: set[str]) -> None:
    lines = []
    for relative in sorted(paths - {"SHA256SUMS"}):
        lines.append(f"{hashlib.sha256((bundle / relative).read_bytes()).hexdigest()}  {relative}\n")
    write_file(bundle / "SHA256SUMS", "".join(lines).encode("utf-8"))


def export_bundle(source_commit: str, profile_name: str, output: Path) -> None:
    config = load_config()
    profile = config["profiles"].get(profile_name)
    if not isinstance(profile, dict):
        raise BundleError("--profile is not declared by hfs-space-bundle.json")
    require_source_commit(source_commit)
    if output.is_symlink():
        raise BundleError("--output must not be a symlink")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise BundleError("--output must be new or empty")
    output.mkdir(mode=0o755, parents=True, exist_ok=True)

    source_entries = []
    selected_manifest = profile["manifest"]
    for source_path, bundle_path in config["source_to_bundle"].items():
        payload = blob(source_commit, source_path)
        mode = tree_mode(source_commit, source_path)
        if source_path == selected_manifest:
            validate_manifest(payload, profile["space"])
        write_file(output / bundle_path, payload, mode)
        source_entries.append(source_entry(source_path, bundle_path, payload, mode))

    evidence = {
        "schema_version": 1,
        "source_kind": "git-commit",
        "wrapper_source_commit": source_commit,
        "wrapper_source_repository": config["wrapper_repository"],
        "target_space": profile["space"],
        "manifest_profile": selected_manifest,
        "profile": profile_name,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_files": source_entries,
    }
    write_file(
        output / "BUILD_SOURCE.json",
        (json.dumps(evidence, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    write_checksums(output, expected_paths(config))
    verify_bundle(output, profile_name, source_commit)


def inventory(bundle: Path) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    directories: set[str] = set()
    for current, dirnames, filenames in os.walk(bundle, followlinks=False):
        root = Path(current)
        for name in dirnames:
            path = root / name
            relative = path.relative_to(bundle).as_posix()
            if path.is_symlink() or not stat.S_ISDIR(path.lstat().st_mode):
                raise BundleError(f"bundle contains a symlink or non-directory: {relative}")
            directories.add(relative)
        for name in filenames:
            path = root / name
            relative = path.relative_to(bundle).as_posix()
            if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
                raise BundleError(f"bundle contains a symlink or non-file: {relative}")
            files.add(relative)
    return files, directories


def validate_dockerfile_sources(dockerfile: str, files: set[str]) -> None:
    for number, raw_line in enumerate(dockerfile.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not re.match(r"(?i)^(?:COPY|ADD)(?:\s|$)", stripped):
            continue
        try:
            tokens = shlex.split(stripped)
        except ValueError as exc:
            raise BundleError(f"Dockerfile line {number} is not parseable") from exc
        if not tokens:
            raise BundleError(f"Dockerfile line {number} is not parseable")
        arguments = tokens[1:]
        from_stage = False
        while arguments and arguments[0].startswith("--"):
            option = arguments.pop(0)
            if option == "--from":
                if not arguments:
                    raise BundleError(f"Dockerfile line {number} has an incomplete --from")
                arguments.pop(0)
                from_stage = True
            elif option.startswith("--from="):
                from_stage = True
        if from_stage:
            continue
        if len(arguments) < 2:
            raise BundleError(f"Dockerfile line {number} has an incomplete local copy")
        for raw_source in arguments[:-1]:
            source = _safe_relative(raw_source.rstrip("/"), label="Dockerfile source")
            if source not in files and not any(path.startswith(f"{source}/") for path in files):
                raise BundleError(f"Dockerfile local source is absent from the allowlist: {source}")


def bundle_source_entries(bundle: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    entries = []
    for source_path, bundle_path in config["source_to_bundle"].items():
        path = bundle / bundle_path
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode not in {0o644, 0o755}:
            raise BundleError(f"bundle file has an unsupported mode: {bundle_path}")
        entries.append(source_entry(source_path, bundle_path, path.read_bytes(), mode))
    return entries


def git_source_entries(source_commit: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        source_entry(
            source_path,
            bundle_path,
            blob(source_commit, source_path),
            tree_mode(source_commit, source_path),
        )
        for source_path, bundle_path in config["source_to_bundle"].items()
    ]


def verify_bundle(bundle: Path, profile_name: str, source_commit: str) -> None:
    require_commit_object(source_commit)
    config = load_config()
    profile = config["profiles"].get(profile_name)
    if not isinstance(profile, dict):
        raise BundleError("--profile is not declared by hfs-space-bundle.json")
    if bundle.is_symlink() or not bundle.is_dir():
        raise BundleError("--bundle must be an existing non-symlink directory")
    bundle = bundle.resolve()
    files, directories = inventory(bundle)
    expected = expected_paths(config)
    if files != expected:
        raise BundleError(
            f"bundle path mismatch; missing={sorted(expected - files)}; extra={sorted(files - expected)}"
        )
    expected_directories = {
        parent.as_posix()
        for relative in expected
        for parent in PurePosixPath(relative).parents
        if parent.as_posix() != "."
    }
    if directories != expected_directories:
        raise BundleError("bundle directory set does not match the allowlist")

    checksums: dict[str, str] = {}
    for line in (bundle / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        match = CHECKSUM_LINE.fullmatch(line)
        if not match or match.group(2) in checksums:
            raise BundleError("SHA256SUMS contains a malformed or duplicate entry")
        checksums[match.group(2)] = match.group(1)
    if set(checksums) != expected - {"SHA256SUMS"}:
        raise BundleError("SHA256SUMS must cover every other file exactly once")
    for relative, digest in checksums.items():
        if hashlib.sha256((bundle / relative).read_bytes()).hexdigest() != digest:
            raise BundleError(f"checksum mismatch: {relative}")

    validate_manifest((bundle / "hfs-dev.toml").read_bytes(), profile["space"])
    try:
        evidence = json.loads((bundle / "BUILD_SOURCE.json").read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BundleError("BUILD_SOURCE.json is not valid JSON") from exc
    if (
        evidence.get("schema_version") != 1
        or evidence.get("source_kind") != "git-commit"
        or not LOWER_SHA.fullmatch(str(evidence.get("wrapper_source_commit", "")))
        or evidence.get("wrapper_source_repository") != config["wrapper_repository"]
        or evidence.get("target_space") != profile["space"]
        or evidence.get("manifest_profile") != profile["manifest"]
        or evidence.get("profile") != profile_name
    ):
        raise BundleError("BUILD_SOURCE.json does not match the fixed release profile")
    if evidence.get("wrapper_source_commit") != source_commit:
        raise BundleError(
            "BUILD_SOURCE.json wrapper source commit does not match authorized source commit"
        )
    committed_entries = git_source_entries(source_commit, config)
    if evidence.get("source_files") != committed_entries:
        raise BundleError("BUILD_SOURCE.json source file inventory does not match the wrapper source commit")
    if bundle_source_entries(bundle, config) != committed_entries:
        raise BundleError("bundle source files do not match the wrapper source commit bytes and modes")

    for relative in sorted(files - {"SHA256SUMS"}):
        try:
            text = (bundle / relative).read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise BundleError(f"bundle file is not UTF-8 text: {relative}") from exc
        if TOKEN_LITERAL.search(text):
            raise BundleError(f"bundle contains a token-like literal: {relative}")
    dockerfile = (bundle / "Dockerfile").read_text(encoding="utf-8")
    if re.search(r"(?mi)^\s*(?:COPY|ADD)(?:\s+--\S+)*\s+\.\s+", dockerfile):
        raise BundleError("Dockerfile must not use COPY . or ADD .")
    validate_dockerfile_sources(dockerfile, files)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("--source-commit", required=True)
    export.add_argument("--profile", required=True)
    export.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--source-commit", required=True)
    verify.add_argument("--profile", required=True)
    verify.add_argument("--bundle", type=Path, required=True)
    paths = commands.add_parser("paths")
    paths.add_argument("--profile", required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "export":
            export_bundle(args.source_commit, args.profile, args.output)
            print(f"Exported verified {args.profile} HFS bundle: {args.output}")
        elif args.command == "verify":
            verify_bundle(args.bundle, args.profile, args.source_commit)
            print(f"Verified {args.profile} HFS bundle: {args.bundle}")
        else:
            config = load_config()
            if args.profile not in config["profiles"]:
                raise BundleError("--profile is not declared by hfs-space-bundle.json")
            for path in sorted(expected_paths(config)):
                print(path)
        return 0
    except (BundleError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
