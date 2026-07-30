#!/usr/bin/env python3
"""Fail-closed readback for the HFS Protected Space and Private Buckets."""

from __future__ import annotations

import argparse
import os
import re
import tomllib
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit


class VisibilityContractError(RuntimeError):
    """Raised when a remote visibility setting does not match the HFS contract."""


_ID_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def load_manifest(path: Path) -> dict[str, Any]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise VisibilityContractError("HFS manifest must be a TOML table")
    return data


def _require_id_part(value: object, label: str) -> str:
    if not isinstance(value, str) or _ID_PART.fullmatch(value) is None:
        raise VisibilityContractError(f"invalid {label} in HFS visibility contract")
    return value


def _space_parts(space: object) -> tuple[str, str]:
    if not isinstance(space, str) or space.count("/") != 1:
        raise VisibilityContractError("Space ID must be an exact namespace/name pair")
    namespace, name = space.split("/", 1)
    return (
        _require_id_part(namespace, "Space namespace"),
        _require_id_part(name, "Space name"),
    )


def bucket_id_from_uri(uri: str) -> str:
    if uri != uri.strip() or "%" in uri:
        raise VisibilityContractError("Bucket URI must not contain whitespace or encoded path data")
    parsed = urlsplit(uri)
    if parsed.scheme != "hf" or parsed.netloc != "buckets" or parsed.query or parsed.fragment:
        raise VisibilityContractError("Bucket URI must use the exact hf://buckets surface")
    if not parsed.path.startswith("/"):
        raise VisibilityContractError("Bucket URI path is missing")
    segments = parsed.path[1:].split("/")
    if len(segments) < 2 or any(not segment for segment in segments):
        raise VisibilityContractError("Bucket URI must include an exact namespace and bucket name")
    for segment in segments:
        _require_id_part(segment, "Bucket URI segment")
    return f"{segments[0]}/{segments[1]}"


def registered_bucket_ids(manifest: Mapping[str, Any], space: str) -> set[str]:
    space_namespace, _ = _space_parts(space)
    storage_owner = _require_id_part(
        manifest.get("bucket_namespace", space_namespace), "Bucket namespace"
    )
    names: set[str] = set()
    if (
        "dist_bucket" in manifest
        or manifest.get("lane") == "artifact"
        or manifest.get("seed_file") not in (None, "")
    ):
        names.add(_require_id_part(manifest.get("dist_bucket", "hfs-dist"), "dist Bucket"))
    mount_bucket = manifest.get("mount_config_bucket")
    if mount_bucket not in (None, ""):
        names.add(_require_id_part(mount_bucket, "mount Bucket"))
    return {f"{storage_owner}/{name}" for name in names}


def token_namespace(api: Any, token: str) -> str:
    try:
        identity = api.whoami(token=token)
    except Exception as exc:
        raise VisibilityContractError(
            f"Token owner readback failed without response details: {type(exc).__name__}"
        ) from None
    name = identity.get("name") if isinstance(identity, Mapping) else None
    if not isinstance(name, str) or not name:
        raise VisibilityContractError("Token owner readback omitted the account namespace")
    return name


def exact_space_visibility(api: Any, space: str, token: str) -> str:
    namespace, _ = _space_parts(space)
    owner = token_namespace(api, token)
    kwargs: dict[str, Any] = {"token": token}
    if namespace.casefold() != owner.casefold():
        kwargs["namespace"] = namespace
    try:
        matches = [
            repo
            for repo in api.list_user_repos(**kwargs)
            if getattr(repo, "id", None) == space and getattr(repo, "type", None) == "space"
        ]
    except Exception as exc:
        raise VisibilityContractError(
            f"Space settings readback failed without response details: {type(exc).__name__}"
        ) from None
    if len(matches) != 1:
        raise VisibilityContractError(
            "Space settings readback did not return one exact repository ID with repo type space"
        )
    visibility = getattr(matches[0], "visibility", None)
    if not isinstance(visibility, str) or not visibility:
        raise VisibilityContractError("Space settings readback omitted visibility")
    return visibility


def _space_variable_bucket_uris(
    api: Any,
    space: str,
    token: str,
    variable_names: Iterable[str],
) -> list[str]:
    names = tuple(variable_names)
    if not names:
        return []
    try:
        variables = api.get_space_variables(space, token=token)
    except Exception as exc:
        raise VisibilityContractError(
            f"Space Variable readback failed without response details: {type(exc).__name__}"
        ) from None
    values: list[str] = []
    for name in names:
        variable = variables.get(name)
        value = getattr(variable, "value", None)
        if not isinstance(value, str) or not value:
            raise VisibilityContractError(f"required formal Bucket URI Variable is missing: {name}")
        values.append(value)
    return values


def verify_visibility_contract(
    api: Any,
    manifest: Mapping[str, Any],
    token: str,
    *,
    space: str | None = None,
    bucket_uris: Iterable[str] = (),
    space_variable_uri_names: Iterable[str] = (),
    check_space: bool = True,
) -> tuple[str, set[str]]:
    manifest_space = manifest.get("space")
    selected_space = space or manifest_space
    if selected_space != manifest_space:
        raise VisibilityContractError("workflow Space ID must exactly match the HFS manifest")
    if not isinstance(selected_space, str):
        raise VisibilityContractError("HFS manifest must register an exact Space ID")
    _space_parts(selected_space)
    if manifest.get("space_visibility") != "protected":
        raise VisibilityContractError("HFS manifest must require Protected Space visibility")
    if manifest.get("bucket_visibility") != "private":
        raise VisibilityContractError("HFS manifest must require Private Bucket visibility")

    if check_space and exact_space_visibility(api, selected_space, token) != "protected":
        raise VisibilityContractError("exact Space settings readback is not Protected")

    all_bucket_uris = list(bucket_uris)
    all_bucket_uris.extend(
        _space_variable_bucket_uris(
            api,
            selected_space,
            token,
            space_variable_uri_names,
        )
    )
    bucket_ids = registered_bucket_ids(manifest, selected_space)
    bucket_ids.update(bucket_id_from_uri(uri) for uri in all_bucket_uris)
    for bucket_id in sorted(bucket_ids):
        try:
            private = getattr(api.bucket_info(bucket_id, token=token), "private", None)
        except Exception as exc:
            raise VisibilityContractError(
                f"Bucket settings readback failed without response details: {type(exc).__name__}"
            ) from None
        if private is not True:
            raise VisibilityContractError(f"registered or formal-use Bucket is not Private: {bucket_id}")
    return selected_space, bucket_ids


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--space")
    parser.add_argument("--bucket-uri", action="append", default=[])
    parser.add_argument("--space-variable-uri", action="append", default=[])
    parser.add_argument(
        "--buckets-only",
        action="store_true",
        help="Use for bucket publication jobs whose token is not a Space deployment token.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = os.environ.get("HF_TOKEN", "")
    if not token:
        raise VisibilityContractError("HF_TOKEN is required for HFS visibility readback")
    if args.buckets_only and args.space_variable_uri:
        raise VisibilityContractError("--buckets-only cannot read Space Variables")

    from huggingface_hub import HfApi

    selected_space, bucket_ids = verify_visibility_contract(
        HfApi(token=token),
        load_manifest(args.manifest),
        token,
        space=args.space,
        bucket_uris=args.bucket_uri,
        space_variable_uri_names=args.space_variable_uri,
        check_space=not args.buckets_only,
    )
    space_status = "skipped" if args.buckets_only else "protected"
    print(
        "PASS hfs-visibility: "
        f"space={selected_space} space_check={space_status} private_buckets={len(bucket_ids)}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except VisibilityContractError as exc:
        raise SystemExit(f"FAIL hfs-visibility: {exc}") from None
