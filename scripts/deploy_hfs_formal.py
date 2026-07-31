#!/usr/bin/env python3
"""CAS upload and separately authorized factory reboot for the formal HFS Space."""

# Remote client exceptions are intentionally collapsed to their type so private
# repository responses and credentials cannot leak into Actions logs.
# ruff: noqa: BLE001

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docker"))
from dify_artifact_contract import (
    MAX_ARCHIVE_BYTES,
    ContractError,
    load_manifest,
    parse_manifest_uri,
)

GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_ARTIFACT_VARIABLE = "DIFY_ARTIFACT_EXPECTED_SOURCE_REF"
MANIFEST_URI_VARIABLE = "DIFY_ARTIFACT_MANIFEST_HF_URI"
MAX_BYTES_VARIABLE = "DIFY_ARTIFACT_MAX_BYTES"


class FormalDeploymentError(RuntimeError):
    """Raised when the formal deployment cannot preserve its exact-state contract."""


def _require_git_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or GIT_SHA_RE.fullmatch(value) is None:
        raise FormalDeploymentError(f"{label} must be a full lowercase Git SHA")
    return value


def _expected_paths(paths_file: Path, bundle: Path) -> tuple[str, ...]:
    try:
        raw_paths = paths_file.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise FormalDeploymentError(
            f"formal path allowlist could not be read: {type(exc).__name__}"
        ) from None
    if not raw_paths or len(raw_paths) != len(set(raw_paths)):
        raise FormalDeploymentError(
            "formal path allowlist must be non-empty and duplicate-free"
        )

    paths: list[str] = []
    for raw_path in raw_paths:
        path = PurePosixPath(raw_path)
        if (
            not raw_path
            or raw_path.startswith("/")
            or "\\" in raw_path
            or any(part in {"", ".", ".."} for part in path.parts)
            or path.as_posix() != raw_path
        ):
            raise FormalDeploymentError(
                "formal path allowlist contains an unsafe repository path"
            )
        local_path = bundle.joinpath(*path.parts)
        if not local_path.is_file() or local_path.is_symlink():
            raise FormalDeploymentError(
                f"formal bundle path is not a regular file: {raw_path}"
            )
        paths.append(raw_path)

    if "BUILD_SOURCE.json" not in paths:
        raise FormalDeploymentError("formal bundle must include BUILD_SOURCE.json")
    return tuple(sorted(paths))


def _verify_provenance(bundle: Path, source_ref: str) -> None:
    try:
        payload = json.loads((bundle / "BUILD_SOURCE.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FormalDeploymentError(
            f"formal wrapper provenance could not be read: {type(exc).__name__}"
        ) from None
    if (
        not isinstance(payload, dict)
        or payload.get("wrapper_source_commit") != source_ref
    ):
        raise FormalDeploymentError(
            "formal wrapper provenance does not match exact GitHub main input"
        )


def _sha256(path: Path) -> bytes:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").digest()


def _space_variable_value(variables: object, name: str) -> str:
    if not isinstance(variables, dict):
        raise FormalDeploymentError("Space Variable readback returned an invalid shape")
    variable = variables.get(name)
    value = getattr(variable, "value", None)
    if not isinstance(value, str) or not value:
        raise FormalDeploymentError(f"required Space Variable is missing: {name}")
    return value


def _artifact_max_bytes(variables: object) -> int:
    value = _space_variable_value(variables, MAX_BYTES_VARIABLE)
    if re.fullmatch(r"[0-9]+", value) is None:
        raise FormalDeploymentError(
            "DIFY_ARTIFACT_MAX_BYTES must be an ASCII positive integer"
        )
    max_bytes = int(value)
    if not 0 < max_bytes <= MAX_ARCHIVE_BYTES:
        raise FormalDeploymentError(
            "DIFY_ARTIFACT_MAX_BYTES exceeds the runtime artifact safety boundary"
        )
    return max_bytes


def _current_space_sha(api: Any, *, token: str, space: str, label: str) -> str:
    try:
        return _require_git_sha(
            getattr(api.space_info(space, token=token), "sha", None),
            label,
        )
    except FormalDeploymentError:
        raise
    except Exception as exc:
        raise FormalDeploymentError(
            f"Space revision readback failed without response details: {type(exc).__name__}"
        ) from None


def _artifact_manifest(
    api: Any, *, token: str, space: str, artifact_ref: str
) -> tuple[dict[str, str], str, int]:
    try:
        variables = api.get_space_variables(space, token=token)
        manifest_uri = _space_variable_value(variables, MANIFEST_URI_VARIABLE)
        max_bytes = _artifact_max_bytes(variables)
        namespace, bucket, slot, _manifest_url = parse_manifest_uri(manifest_uri)
        if slot != "release":
            raise FormalDeploymentError(
                "formal artifact manifest Variable must select the exact Private release lane"
            )
        bucket_id = f"{namespace}/{bucket}"
        remote_path = "dify-all-in-one/release/manifest.json"
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = Path(temporary) / "manifest.json"
            api.download_bucket_files(
                bucket_id,
                [(remote_path, manifest_path)],
                raise_on_missing_files=True,
                token=token,
            )
            provenance = load_manifest(
                manifest_path,
                manifest_uri,
                expected_source_ref=artifact_ref,
                max_bytes=max_bytes,
            )
            if provenance["source_kind"] != "tag":
                raise FormalDeploymentError(
                    "formal release manifest must select an immutable tag"
                )
    except FormalDeploymentError:
        raise
    except ContractError:
        raise FormalDeploymentError(
            "formal release manifest does not satisfy the runtime artifact contract"
        ) from None
    except Exception as exc:
        raise FormalDeploymentError(
            f"formal artifact manifest readback failed without response details: {type(exc).__name__}"
        ) from None

    return provenance, manifest_uri, max_bytes


def _variables_after_manifest(
    api: Any,
    *,
    token: str,
    space: str,
    manifest_uri: str,
    max_bytes: int,
) -> dict[str, Any]:
    try:
        variables = api.get_space_variables(space, token=token)
        if (
            _space_variable_value(variables, MANIFEST_URI_VARIABLE) != manifest_uri
            or _artifact_max_bytes(variables) != max_bytes
        ):
            raise FormalDeploymentError(
                "artifact selection Variables changed during manifest verification"
            )
        return variables
    except FormalDeploymentError:
        raise
    except Exception as exc:
        raise FormalDeploymentError(
            f"artifact binding readback failed without response details: {type(exc).__name__}"
        ) from None


def _require_space_revision(
    api: Any,
    *,
    token: str,
    space: str,
    deployed_revision: str,
    action: str,
) -> None:
    if (
        _current_space_sha(
            api,
            token=token,
            space=space,
            label="current Space revision",
        )
        != deployed_revision
    ):
        raise FormalDeploymentError(
            f"Space main changed after verified upload; refusing {action}"
        )


def verify_formal_artifact_binding(
    api: Any,
    *,
    token: str,
    space: str,
    deployed_revision: str,
    artifact_ref: str,
) -> None:
    deployed_revision = _require_git_sha(deployed_revision, "deployed_revision")
    artifact_ref = _require_git_sha(artifact_ref, "artifact_ref")
    _require_space_revision(
        api,
        token=token,
        space=space,
        deployed_revision=deployed_revision,
        action="artifact binding or reboot",
    )
    _provenance, manifest_uri, max_bytes = _artifact_manifest(
        api, token=token, space=space, artifact_ref=artifact_ref
    )
    variables = _variables_after_manifest(
        api,
        token=token,
        space=space,
        manifest_uri=manifest_uri,
        max_bytes=max_bytes,
    )
    expected_ref = _space_variable_value(variables, EXPECTED_ARTIFACT_VARIABLE)
    if expected_ref != artifact_ref:
        raise FormalDeploymentError(
            "Space expected artifact Variable does not match the verified release manifest"
        )
    _require_space_revision(
        api,
        token=token,
        space=space,
        deployed_revision=deployed_revision,
        action="artifact binding or reboot",
    )


def bind_formal_artifact(
    api: Any,
    *,
    token: str,
    space: str,
    deployed_revision: str,
    artifact_ref: str,
    confirmation: str,
) -> None:
    deployed_revision = _require_git_sha(deployed_revision, "deployed_revision")
    artifact_ref = _require_git_sha(artifact_ref, "artifact_ref")
    if confirmation != "BIND_ARTIFACT":
        raise FormalDeploymentError(
            "artifact Variable update requires the exact BIND_ARTIFACT confirmation"
        )
    _require_space_revision(
        api,
        token=token,
        space=space,
        deployed_revision=deployed_revision,
        action="artifact binding",
    )
    _provenance, manifest_uri, max_bytes = _artifact_manifest(
        api, token=token, space=space, artifact_ref=artifact_ref
    )
    variables = _variables_after_manifest(
        api,
        token=token,
        space=space,
        manifest_uri=manifest_uri,
        max_bytes=max_bytes,
    )
    current_ref = _space_variable_value(variables, EXPECTED_ARTIFACT_VARIABLE)
    if current_ref != artifact_ref:
        # Cross-resource atomicity is unavailable. Re-validate the mutable
        # manifest/settings and Space HEAD immediately before the one Variable write.
        _provenance, manifest_uri, max_bytes = _artifact_manifest(
            api, token=token, space=space, artifact_ref=artifact_ref
        )
        variables = _variables_after_manifest(
            api,
            token=token,
            space=space,
            manifest_uri=manifest_uri,
            max_bytes=max_bytes,
        )
        _require_space_revision(
            api,
            token=token,
            space=space,
            deployed_revision=deployed_revision,
            action="artifact binding",
        )
        if _space_variable_value(variables, EXPECTED_ARTIFACT_VARIABLE) != artifact_ref:
            try:
                api.add_space_variable(
                    space,
                    EXPECTED_ARTIFACT_VARIABLE,
                    artifact_ref,
                    description="Exact Dify runtime artifact commit selected by the formal release manifest.",
                    token=token,
                )
            except Exception as exc:
                raise FormalDeploymentError(
                    f"artifact binding update failed without response details: {type(exc).__name__}"
                ) from None
    verify_formal_artifact_binding(
        api,
        token=token,
        space=space,
        deployed_revision=deployed_revision,
        artifact_ref=artifact_ref,
    )


def upload_formal_bundle(
    api: Any,
    *,
    token: str,
    space: str,
    bundle: Path,
    paths_file: Path,
    source_ref: str,
    operation_factory: Callable[[str, Path], Any],
    download_file: Callable[..., str | Path],
) -> str:
    source_ref = _require_git_sha(source_ref, "source_ref")
    paths = _expected_paths(paths_file, bundle)
    _verify_provenance(bundle, source_ref)

    try:
        preflight_sha = _require_git_sha(
            getattr(api.space_info(space, token=token), "sha", None),
            "preflight Space revision",
        )
        actual_before = set(
            api.list_repo_files(
                space,
                revision=preflight_sha,
                repo_type="space",
                token=token,
            )
        )
    except FormalDeploymentError:
        raise
    except Exception as exc:
        raise FormalDeploymentError(
            f"formal Space preflight failed without response details: {type(exc).__name__}"
        ) from None

    unexpected = actual_before - set(paths)
    if unexpected:
        raise FormalDeploymentError(
            "canonical Space contains a path outside the formal bundle allowlist"
        )

    operations = [
        operation_factory(path, bundle.joinpath(*PurePosixPath(path).parts))
        for path in paths
    ]
    try:
        result = api.create_commit(
            repo_id=space,
            repo_type="space",
            revision="main",
            parent_commit=preflight_sha,
            operations=operations,
            commit_message=f"Deploy verified formal wrapper {source_ref}",
            token=token,
        )
        deployed_revision = _require_git_sha(
            getattr(result, "oid", None), "deployed Space revision"
        )
    except FormalDeploymentError:
        raise
    except Exception as exc:
        raise FormalDeploymentError(
            f"formal Space CAS commit failed without response details: {type(exc).__name__}"
        ) from None

    try:
        actual_after = set(
            api.list_repo_files(
                space,
                revision=deployed_revision,
                repo_type="space",
                token=token,
            )
        )
        if actual_after != set(paths):
            raise FormalDeploymentError(
                "canonical repository path readback does not match the formal allowlist"
            )
        for relative in paths:
            downloaded = Path(
                download_file(
                    repo_id=space,
                    filename=relative,
                    revision=deployed_revision,
                    repo_type="space",
                    token=token,
                )
            )
            if _sha256(downloaded) != _sha256(
                bundle.joinpath(*PurePosixPath(relative).parts)
            ):
                raise FormalDeploymentError(f"canonical readback mismatch: {relative}")
    except FormalDeploymentError:
        raise
    except Exception as exc:
        raise FormalDeploymentError(
            f"formal Space readback failed without response details: {type(exc).__name__}"
        ) from None

    return deployed_revision


def reboot_formal_space(
    api: Any,
    *,
    token: str,
    space: str,
    deployed_revision: str,
    artifact_ref: str,
    confirmation: str,
    timeout_seconds: float = 1800,
    poll_seconds: float = 15,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    deployed_revision = _require_git_sha(deployed_revision, "deployed_revision")
    artifact_ref = _require_git_sha(artifact_ref, "artifact_ref")
    if confirmation != "FACTORY_REBOOT":
        raise FormalDeploymentError(
            "factory reboot requires the exact FACTORY_REBOOT confirmation"
        )

    verify_formal_artifact_binding(
        api,
        token=token,
        space=space,
        deployed_revision=deployed_revision,
        artifact_ref=artifact_ref,
    )

    try:
        api.restart_space(space, token=token, factory_reboot=True)
    except Exception as exc:
        raise FormalDeploymentError(
            f"factory reboot request failed without response details: {type(exc).__name__}"
        ) from None

    deadline = monotonic() + timeout_seconds
    while True:
        try:
            runtime = api.get_space_runtime(space, token=token)
        except Exception as exc:
            raise FormalDeploymentError(
                f"runtime readback failed without response details: {type(exc).__name__}"
            ) from None
        stage = getattr(runtime, "stage", None)
        stage = getattr(stage, "value", stage)
        raw = getattr(runtime, "raw", None)
        runtime_sha = raw.get("sha") if isinstance(raw, dict) else None
        if stage == "RUNNING" and runtime_sha == deployed_revision:
            return
        if stage in {"BUILD_ERROR", "RUNTIME_ERROR"}:
            raise FormalDeploymentError(f"canonical Space failed after deploy: {stage}")
        if monotonic() >= deadline:
            raise FormalDeploymentError(
                "canonical runtime did not converge to the verified deployed revision"
            )
        sleep(poll_seconds)


def _write_github_output(path: Path | None, deployed_revision: str) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"deployed_revision={deployed_revision}\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    upload = subparsers.add_parser(
        "upload", help="CAS-upload and read back a verified formal bundle"
    )
    upload.add_argument("--space", required=True)
    upload.add_argument("--bundle", type=Path, required=True)
    upload.add_argument("--paths-file", type=Path, required=True)
    upload.add_argument("--source-ref", required=True)
    upload.add_argument("--github-output", type=Path)

    reboot = subparsers.add_parser(
        "reboot", help="Factory-reboot an unchanged verified revision"
    )
    reboot.add_argument("--space", required=True)
    reboot.add_argument("--deployed-revision", required=True)
    reboot.add_argument("--artifact-ref", required=True)
    reboot.add_argument("--confirm-factory-reboot", required=True)
    reboot.add_argument("--timeout-seconds", type=float, default=1800)
    reboot.add_argument("--poll-seconds", type=float, default=15)

    bind = subparsers.add_parser(
        "bind-artifact",
        help="Verify the release manifest and bind its exact artifact before reboot",
    )
    bind.add_argument("--space", required=True)
    bind.add_argument("--deployed-revision", required=True)
    bind.add_argument("--artifact-ref", required=True)
    bind.add_argument("--confirm-artifact-binding", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = os.environ.get("HF_TOKEN", "")
    if not token:
        raise FormalDeploymentError("HF_TOKEN is required for formal HFS deployment")

    from huggingface_hub import HfApi, hf_hub_download
    from huggingface_hub.hf_api import CommitOperationAdd

    api = HfApi(token=token)
    if args.command == "upload":
        deployed_revision = upload_formal_bundle(
            api,
            token=token,
            space=args.space,
            bundle=args.bundle,
            paths_file=args.paths_file,
            source_ref=args.source_ref,
            operation_factory=lambda relative, local: CommitOperationAdd(
                path_in_repo=relative, path_or_fileobj=local
            ),
            download_file=hf_hub_download,
        )
        _write_github_output(args.github_output, deployed_revision)
        print(f"PASS formal upload: deployed_revision={deployed_revision}")
        return 0

    if args.command == "bind-artifact":
        bind_formal_artifact(
            api,
            token=token,
            space=args.space,
            deployed_revision=args.deployed_revision,
            artifact_ref=args.artifact_ref,
            confirmation=args.confirm_artifact_binding,
        )
        print(f"PASS formal artifact binding: artifact_ref={args.artifact_ref}")
        return 0

    reboot_formal_space(
        api,
        token=token,
        space=args.space,
        deployed_revision=args.deployed_revision,
        artifact_ref=args.artifact_ref,
        confirmation=args.confirm_factory_reboot,
        timeout_seconds=args.timeout_seconds,
        poll_seconds=args.poll_seconds,
    )
    print(f"PASS formal reboot: runtime_sha={args.deployed_revision}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FormalDeploymentError as exc:
        raise SystemExit(f"FAIL formal deployment: {exc}") from None
