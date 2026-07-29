from __future__ import annotations

import contextlib
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import export_hfs_space_bundle as exporter

from scripts.export_hfs_space_bundle import (
    BundleError,
    expected_paths,
    load_config,
    validate_dockerfile_sources,
    verify_bundle,
)


ROOT = Path(__file__).resolve().parents[2]
FORMAL_WORKFLOW = ROOT / ".github" / "workflows" / "deploy-hfs-formal.yml"
SOURCE_COMMIT = subprocess.check_output(
    ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
    text=True,
).strip()
HISTORICAL_COMMIT = subprocess.check_output(
    ["git", "-C", str(ROOT), "rev-parse", "HEAD^"],
    text=True,
).strip()
TREE_OBJECT = subprocess.check_output(
    ["git", "-C", str(ROOT), "rev-parse", "HEAD^{tree}"],
    text=True,
).strip()


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class HfsExporterTests(unittest.TestCase):
    def make_bundle(self, directory: Path, source_commit: str = SOURCE_COMMIT) -> Path:
        config = load_config()
        profile = config["profiles"]["formal"]
        source_entries = []
        for source_path, bundle_path in config["source_to_bundle"].items():
            payload = exporter.blob(source_commit, source_path)
            mode = exporter.tree_mode(source_commit, source_path)
            target = directory / bundle_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            target.chmod(mode)
            source_entries.append(
                {
                    "source_path": source_path,
                    "bundle_path": bundle_path,
                    "mode": f"{mode:04o}",
                    "bytes": len(payload),
                    "sha256": sha256(payload),
                }
            )

        evidence = {
            "schema_version": 1,
            "source_kind": "git-commit",
            "wrapper_source_commit": source_commit,
            "wrapper_source_repository": config["wrapper_repository"],
            "target_space": profile["space"],
            "manifest_profile": profile["manifest"],
            "profile": "formal",
            "generated_at": "2026-07-30T00:00:00Z",
            "source_files": source_entries,
        }
        (directory / "BUILD_SOURCE.json").write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.rewrite_checksums(directory)
        return directory

    def run_verifier(self, bundle: Path, source_commit: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "export_hfs_space_bundle.py"),
                "verify",
                "--source-commit",
                source_commit,
                "--profile",
                "formal",
                "--bundle",
                str(bundle),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def rewrite_checksums(self, bundle: Path) -> None:
        expected = expected_paths(load_config())
        lines = [
            f"{sha256((bundle / relative).read_bytes())}  {relative}\n"
            for relative in sorted(expected - {"SHA256SUMS"})
        ]
        (bundle / "SHA256SUMS").write_text("".join(lines), encoding="utf-8")

    def test_dockerfile_validation_ignores_non_copy_continuations(self) -> None:
        dockerfile = """\
FROM python:3.12
RUN apt-get update \\
    && apt-get install -y curl
COPY docker/entrypoint.sh /opt/dify/entrypoint.sh
"""

        validate_dockerfile_sources(dockerfile, {"docker/entrypoint.sh"})

    def test_dockerfile_validation_rejects_unlisted_local_copy(self) -> None:
        with self.assertRaisesRegex(BundleError, "absent from the allowlist"):
            validate_dockerfile_sources(
                "COPY docker/missing.sh /opt/dify/missing.sh\n",
                {"docker/entrypoint.sh"},
            )

    def test_verify_accepts_complete_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            verify_bundle(self.make_bundle(Path(temporary)), "formal", SOURCE_COMMIT)

    def test_verify_rejects_forged_source_inventory_with_fresh_checksums(self) -> None:
        for field, forged in (
            ("sha256", "f" * 64),
            ("bytes", 0),
            ("mode", "0777"),
            ("bundle_path", "Dockerfile"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                bundle = self.make_bundle(Path(temporary))
                evidence_path = bundle / "BUILD_SOURCE.json"
                evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
                evidence["source_files"][0][field] = forged
                evidence_path.write_text(
                    json.dumps(evidence, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                self.rewrite_checksums(bundle)

                with self.assertRaisesRegex(BundleError, "source file inventory"):
                    verify_bundle(bundle, "formal", SOURCE_COMMIT)

    def test_verify_rejects_coordinated_payload_inventory_and_checksum_forgery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = self.make_bundle(Path(temporary))
            config = load_config()
            _source_path, bundle_path = next(iter(config["source_to_bundle"].items()))
            target = bundle / bundle_path
            forged_payload = target.read_bytes() + b"\nforged\n"
            target.write_bytes(forged_payload)

            evidence_path = bundle / "BUILD_SOURCE.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence["source_files"][0]["bytes"] = len(forged_payload)
            evidence["source_files"][0]["sha256"] = sha256(forged_payload)
            evidence_path.write_text(
                json.dumps(evidence, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.rewrite_checksums(bundle)

            with self.assertRaisesRegex(BundleError, "wrapper source commit"):
                verify_bundle(bundle, "formal", SOURCE_COMMIT)

    def test_verify_cli_requires_authorized_source_commit(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            exporter.parser().parse_args(
                ["verify", "--profile", "formal", "--bundle", "bundle"]
            )

    def test_verify_rejects_complete_historical_bundle_for_current_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = self.make_bundle(Path(temporary), HISTORICAL_COMMIT)
            result = self.run_verifier(bundle, SOURCE_COMMIT)

        self.assertEqual(result.returncode, 2)
        self.assertIn("wrapper source commit does not match authorized source commit", result.stderr)

    def test_verify_rejects_non_commit_authorization_objects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = self.make_bundle(Path(temporary))
            result = self.run_verifier(bundle, TREE_OBJECT)
        self.assertEqual(result.returncode, 2)
        self.assertIn("must identify a Git commit", result.stderr)

        validator = getattr(exporter, "require_commit_object", None)
        self.assertIsNotNone(validator)
        with mock.patch.object(exporter, "_git", return_value="tag\n"):
            with self.assertRaisesRegex(BundleError, "must identify a Git commit"):
                validator("b" * 40)


class WorkflowContractTests(unittest.TestCase):
    def test_formal_workflow_uses_immutable_readback_and_runtime_gate(self) -> None:
        workflow = FORMAL_WORKFLOW.read_text(encoding="utf-8")
        for required in (
            "deployed_revision = info.sha",
            "revision=deployed_revision",
            "hf_hub_download",
            'runtime.stage == "RUNNING"',
            'runtime.raw.get("sha") == deployed_revision',
            'runtime.stage in {"BUILD_ERROR", "RUNTIME_ERROR"}',
            "time.monotonic() + 1800",
        ):
            self.assertIn(required, workflow)
        verify_commands = workflow.split("export_hfs_space_bundle.py verify")[1:]
        self.assertEqual(len(verify_commands), 3)
        for command in verify_commands:
            self.assertIn('--source-commit "$SOURCE_REF"', command.split("\n\n", 1)[0])


if __name__ == "__main__":
    unittest.main()
