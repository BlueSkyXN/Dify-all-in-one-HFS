from __future__ import annotations

import hashlib
import json
import stat
import tempfile
import unittest
from pathlib import Path

from scripts.export_hfs_space_bundle import (
    BundleError,
    expected_paths,
    load_config,
    validate_dockerfile_sources,
    verify_bundle,
)


ROOT = Path(__file__).resolve().parents[2]
FORMAL_WORKFLOW = ROOT / ".github" / "workflows" / "deploy-hfs-formal.yml"


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class HfsExporterTests(unittest.TestCase):
    def make_bundle(self, directory: Path) -> Path:
        config = load_config()
        profile = config["profiles"]["formal"]
        source_entries = []
        for source_path, bundle_path in config["source_to_bundle"].items():
            source = ROOT / source_path
            payload = source.read_bytes()
            mode = 0o755 if source.stat().st_mode & stat.S_IXUSR else 0o644
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
            "wrapper_source_commit": "a" * 40,
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
            verify_bundle(self.make_bundle(Path(temporary)), "formal")

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
                    verify_bundle(bundle, "formal")


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


if __name__ == "__main__":
    unittest.main()
