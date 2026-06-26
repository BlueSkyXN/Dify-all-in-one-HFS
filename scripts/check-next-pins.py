#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULT_DIFY_REMOTE = "https://github.com/BlueSkyXN/dify.git"
DEFAULT_DIFY_MAIN_REF = "refs/heads/main"
DEFAULT_DIFY_AGENT_REF = "refs/heads/main"
DEFAULT_DIFY_IMAGE_TAG = "main"
DEFAULT_SANDBOX_REMOTE = "https://github.com/langgenius/dify-sandbox.git"
DOCKER_HUB_TAG_URL = "https://hub.docker.com/v2/repositories/{namespace}/{repo}/tags/{tag}"


class CheckError(RuntimeError):
    pass


def run_text(args: list[str], *, timeout: int = 45) -> str:
    proc = subprocess.run(
        args,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise CheckError(f"{' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def git_remote_head(remote: str, ref: str) -> str:
    output = run_text(["git", "ls-remote", remote, ref])
    for line in output.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == ref:
            return parts[0]
    raise CheckError(f"Unable to resolve {ref} from {remote}")


def docker_tag(namespace: str, repo: str, tag: str) -> dict[str, Any]:
    url = DOCKER_HUB_TAG_URL.format(namespace=namespace, repo=repo, tag=tag)
    # Use curl instead of urllib so the check follows the system CA bundle on macOS.
    output = run_text(["curl", "-fsSL", "--max-time", "30", url], timeout=45)
    return json.loads(output)


def docker_tag_digest(namespace: str, repo: str, tag: str) -> str:
    payload = docker_tag(namespace, repo, tag)
    digest = payload.get("digest")
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise CheckError(f"Docker Hub tag {namespace}/{repo}:{tag} did not expose a sha256 digest")
    return digest


def dockerfile_args(path: Path) -> dict[str, str]:
    pattern = re.compile(r"^ARG\s+([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
    args: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line.strip())
        if match:
            args[match.group(1)] = match.group(2).strip()
    return args


def ref_digest(image_ref: str) -> str:
    if "@sha256:" not in image_ref:
        raise CheckError(f"Image ref must be pinned by digest: {image_ref}")
    return "sha256:" + image_ref.rsplit("@sha256:", 1)[1]


def check_equal(name: str, actual: str, expected: str, checks: list[dict[str, Any]]) -> None:
    ok = actual == expected
    checks.append({"name": name, "ok": ok, "actual": actual, "expected": expected})


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check that NEXT Dockerfile pins match the maintained Dify fork and runtime image digests.",
    )
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[1], type=Path)
    parser.add_argument("--dify-remote", default=DEFAULT_DIFY_REMOTE)
    parser.add_argument("--dify-main-ref", default=DEFAULT_DIFY_MAIN_REF)
    parser.add_argument("--dify-agent-ref", default=DEFAULT_DIFY_AGENT_REF)
    parser.add_argument("--dify-image-tag", default=DEFAULT_DIFY_IMAGE_TAG)
    parser.add_argument("--sandbox-remote", default=DEFAULT_SANDBOX_REMOTE)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of human-readable output")
    args = parser.parse_args()

    root = args.repo_root.resolve()
    dockerfile = root / "Dockerfile"
    pins = dockerfile_args(dockerfile)
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    try:
        dify_main = git_remote_head(args.dify_remote, args.dify_main_ref)
        dify_agent = git_remote_head(args.dify_remote, args.dify_agent_ref)
        sandbox_main = git_remote_head(args.sandbox_remote, "refs/heads/main")

        check_equal(
            "DIFY_SOURCE_REPO tracks maintained Dify fork",
            pins.get("DIFY_SOURCE_REPO", ""),
            args.dify_remote,
            checks,
        )
        check_equal(
            "DIFY_SOURCE_MAIN_REF tracks maintained fork main",
            pins.get("DIFY_SOURCE_MAIN_REF", ""),
            dify_main,
            checks,
        )
        check_equal(
            "DIFY_AGENT_SOURCE_REF tracks maintained fork Agent source",
            pins.get("DIFY_AGENT_SOURCE_REF", ""),
            dify_agent,
            checks,
        )
        check_equal(
            "DIFY_VERSION metadata tracks maintained fork main plus Agent source",
            pins.get("DIFY_VERSION", ""),
            f"BlueSkyXN-dify-main-{dify_main}-agent-{dify_agent}",
            checks,
        )

        for image_arg, repo in [
            ("DIFY_API_IMAGE_REF", "dify-api"),
            ("DIFY_WEB_IMAGE_REF", "dify-web"),
        ]:
            pinned_digest = ref_digest(pins.get(image_arg, ""))
            image_tag_digest = docker_tag_digest("langgenius", repo, args.dify_image_tag)
            check_equal(
                f"{image_arg} matches langgenius/{repo}:{args.dify_image_tag}",
                pinned_digest,
                image_tag_digest,
                checks,
            )
            try:
                commit_digest = docker_tag_digest("langgenius", repo, dify_main)
            except CheckError as exc:
                notes.append(
                    f"langgenius/{repo}:{dify_main} commit tag unavailable; "
                    f"checked {args.dify_image_tag!r} digest instead ({exc})"
                )
            else:
                check_equal(
                    f"langgenius/{repo}:{dify_main} matches {args.dify_image_tag}",
                    commit_digest,
                    image_tag_digest,
                    checks,
                )

        plugin_digest = docker_tag_digest("langgenius", "dify-plugin-daemon", "latest-local")
        check_equal(
            "PLUGIN_DAEMON_IMAGE_REF matches langgenius/dify-plugin-daemon:latest-local",
            ref_digest(pins.get("PLUGIN_DAEMON_IMAGE_REF", "")),
            plugin_digest,
            checks,
        )

        sandbox_digest = docker_tag_digest("langgenius", "dify-sandbox", "main")
        sandbox_commit_digest = docker_tag_digest("langgenius", "dify-sandbox", sandbox_main)
        check_equal(
            "DIFY_SANDBOX_SOURCE_REF tracks langgenius/dify-sandbox main",
            pins.get("DIFY_SANDBOX_SOURCE_REF", ""),
            sandbox_main,
            checks,
        )
        check_equal(
            "SANDBOX_IMAGE_REF matches langgenius/dify-sandbox:main",
            ref_digest(pins.get("SANDBOX_IMAGE_REF", "")),
            sandbox_digest,
            checks,
        )
        check_equal(
            f"langgenius/dify-sandbox:{sandbox_main} matches :main",
            sandbox_commit_digest,
            sandbox_digest,
            checks,
        )
    except Exception as exc:  # noqa: BLE001 - print a compact failure for shell users.
        checks.append({"name": "pin check execution", "ok": False, "error": str(exc)})

    ok = all(check.get("ok") is True for check in checks)
    payload = {"ok": ok, "checks": checks, "notes": notes}

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"NEXT pin check: {'PASS' if ok else 'FAIL'}")
        for check in checks:
            status = "PASS" if check.get("ok") is True else "FAIL"
            print(f"{status} {check.get('name')}")
            if check.get("ok") is not True:
                if "actual" in check or "expected" in check:
                    print(f"  actual:   {check.get('actual')}")
                    print(f"  expected: {check.get('expected')}")
                if "error" in check:
                    print(f"  error:    {check.get('error')}")
        for note in notes:
            print(f"NOTE {note}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
