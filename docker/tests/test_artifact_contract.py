from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_REF = "a" * 40
IMAGE_REF = "example.invalid/component@sha256:" + "b" * 64


class ArtifactContractTest(unittest.TestCase):
    def _runtime_tree(self, root: Path) -> None:
        files = {
            "app/api/.venv/bin/flask",
            "app/api/.venv/bin/python",
            "app/api/docker/entrypoint.sh",
            "app/entrypoint.sh",
            "opt/dify-agent/.venv/bin/python",
            "usr/local/bin/shellctl",
            "usr/local/bin/shellctl-runner",
            "usr/local/bin/shellctl-runner-exit",
            "usr/local/bin/shellctl-sanitize-pty",
            "usr/local/bin/dify-agent",
            "opt/dify/plugin-daemon/commandline",
            "opt/dify/plugin-daemon/main",
            "opt/dify/sandbox/main",
        }
        directories = {"app/targets/next", "app/targets/vinext", "conf", "dependencies"}
        for directory in directories:
            (root / directory).mkdir(parents=True, exist_ok=True)
        for relative in files:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
            path.chmod(0o755)
        agent_python = root / "opt/dify-agent/.venv/bin/python"
        agent_python.unlink()
        agent_python.symlink_to("/usr/local/bin/python3")

    def test_pack_prepare_and_validate_manifest_selected_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            runtime = temporary_path / "runtime"
            output = temporary_path / "output"
            self._runtime_tree(runtime)
            package = [
                sys.executable,
                str(REPO_ROOT / "scripts/package-dify-runtime-artifact.py"),
                "--runtime-root", str(runtime),
                "--output-dir", str(output),
                "--slot", "edge",
                "--source-kind", "commit",
                "--source-name", SOURCE_REF,
                "--source-ref", SOURCE_REF,
                "--source-date-epoch", "0",
                "--api-image-ref", IMAGE_REF,
                "--web-image-ref", IMAGE_REF,
                "--agent-image-ref", IMAGE_REF,
                "--agent-runtime-image-ref", IMAGE_REF,
                "--plugin-daemon-image-ref", IMAGE_REF,
                "--sandbox-image-ref", IMAGE_REF,
                "--sandbox-source-ref", SOURCE_REF,
            ]
            subprocess.run(package, check=True, capture_output=True, text=True)
            artifact = output / f"dify-runtime-{SOURCE_REF}.tar.gz"
            manifest = output / "manifest.json"
            self.assertTrue(artifact.is_file())
            self.assertTrue(manifest.is_file())

            prepared = temporary_path / "prepared-manifest.json"
            subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts/prepare-dify-artifact-manifest.py"),
                    "--artifact", str(artifact),
                    "--slot", "edge",
                    "--source-kind", "commit",
                    "--source-ref", SOURCE_REF,
                    "--artifact-ref", SOURCE_REF,
                    "--generated-at", "2026-07-26T00:00:00Z",
                    "--output", str(prepared),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            install_root = temporary_path / "installed"
            install_root.mkdir()
            (install_root / "legacy-runtime-marker").write_text("legacy", encoding="utf-8")
            subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "docker/dify_artifact_contract.py"),
                    "--manifest", str(prepared),
                    "--manifest-uri", "hf://buckets/example/hfs-dist/dify-all-in-one/edge/manifest.json",
                    "--artifact", str(artifact),
                    "--install-root", str(install_root),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertTrue(install_root.is_symlink())
            self.assertTrue((install_root / "MANIFEST_PROVENANCE.json").is_file())
            prepared_payload = json.loads(prepared.read_text(encoding="utf-8"))
            self.assertEqual(prepared_payload["artifact_ref"], SOURCE_REF)

            release_manifest = temporary_path / "release-manifest.json"
            release_tag = "hfs-runtime-" + SOURCE_REF[:12]
            subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts/prepare-dify-artifact-manifest.py"),
                    "--artifact", str(artifact),
                    "--slot", "release",
                    "--source-kind", "tag",
                    "--source-ref", release_tag,
                    "--artifact-ref", SOURCE_REF,
                    "--generated-at", "2026-07-26T00:00:00Z",
                    "--output", str(release_manifest),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            release_install_root = temporary_path / "release-installed"
            subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "docker/dify_artifact_contract.py"),
                    "--manifest", str(release_manifest),
                    "--manifest-uri", "hf://buckets/example/hfs-dist/dify-all-in-one/release/manifest.json",
                    "--artifact", str(artifact),
                    "--install-root", str(release_install_root),
                    "--expected-source-ref", SOURCE_REF,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            release_provenance = json.loads((release_install_root / "MANIFEST_PROVENANCE.json").read_text(encoding="utf-8"))
            self.assertEqual(release_provenance["source_kind"], "tag")
            self.assertEqual(release_provenance["source_ref"], release_tag)
            self.assertEqual(release_provenance["artifact_ref"], SOURCE_REF)

            over_limit = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "docker/dify_artifact_contract.py"),
                    "--manifest", str(prepared),
                    "--manifest-uri", "hf://buckets/example/hfs-dist/dify-all-in-one/edge/manifest.json",
                    "--max-bytes", "1",
                    "--print-artifact-url",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(over_limit.returncode, 0)
            prepared_payload = json.loads(prepared.read_text(encoding="utf-8"))
            prepared_payload["size_bytes"] = 4 * 1024 * 1024 * 1024 + 1
            prepared.write_text(json.dumps(prepared_payload), encoding="utf-8")
            fixed_limit = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "docker/dify_artifact_contract.py"),
                    "--manifest", str(prepared),
                    "--manifest-uri", "hf://buckets/example/hfs-dist/dify-all-in-one/edge/manifest.json",
                    "--max-bytes", str(5 * 1024 * 1024 * 1024),
                    "--print-artifact-url",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(fixed_limit.returncode, 0)
            prepared_payload["size_bytes"] = artifact.stat().st_size
            prepared.write_text(json.dumps(prepared_payload), encoding="utf-8")
            active_target = install_root.resolve()
            prepared_payload["unpacked_size_bytes"] += 1
            prepared.write_text(json.dumps(prepared_payload), encoding="utf-8")
            mismatch = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "docker/dify_artifact_contract.py"),
                    "--manifest", str(prepared),
                    "--manifest-uri", "hf://buckets/example/hfs-dist/dify-all-in-one/edge/manifest.json",
                    "--artifact", str(artifact),
                    "--install-root", str(install_root),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(mismatch.returncode, 0)
            self.assertEqual(install_root.resolve(), active_target)

    def test_rejects_archive_path_traversal_before_installation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            archive = temporary_path / "unsafe.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                payload = temporary_path / "payload"
                payload.write_text("unsafe", encoding="utf-8")
                tar.add(payload, arcname="../escape")
            manifest = {
                "schema_version": 2,
                "project": "dify-all-in-one",
                "slot": "edge",
                "source_kind": "commit",
                "source_ref": SOURCE_REF,
                "artifact_ref": SOURCE_REF,
                "artifact": f"dify-runtime-{SOURCE_REF}.tar.gz",
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "size_bytes": archive.stat().st_size,
                "unpacked_size_bytes": payload.stat().st_size,
                "runtime_lock_sha256": "0" * 64,
                "generated_at": "2026-07-26T00:00:00Z",
                "artifact_key": f"dify-all-in-one/edge/dify-runtime-{SOURCE_REF}.tar.gz",
                "manifest_key": "dify-all-in-one/edge/manifest.json",
            }
            manifest_path = temporary_path / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            install_root = temporary_path / "installed"
            install_root.mkdir()
            sentinel = install_root / "preexisting-runtime"
            sentinel.write_text("keep", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "docker/dify_artifact_contract.py"),
                    "--manifest", str(manifest_path),
                    "--manifest-uri", "hf://buckets/example/hfs-dist/dify-all-in-one/edge/manifest.json",
                    "--artifact", str(archive),
                    "--install-root", str(install_root),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
