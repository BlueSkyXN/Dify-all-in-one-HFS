from __future__ import annotations

import contextlib
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import export_hfs_space_bundle as exporter

from scripts.export_hfs_space_bundle import (
    BundleError,
    expected_paths,
    load_config,
    validate_manifest,
    validate_dockerfile_sources,
    verify_bundle,
)


ROOT = Path(__file__).resolve().parents[2]
FORMAL_WORKFLOW = ROOT / ".github" / "workflows" / "deploy-hfs-formal.yml"
SOURCE_COMMIT = subprocess.check_output(
    ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
    text=True,
).strip()


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def run_git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"Git fixture command failed: git {' '.join(args)}")
    return result.stdout.strip()


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

    def make_source_repository(self, directory: Path) -> tuple[Path, str, str, str, str]:
        repository = directory / "source-repository"
        repository.mkdir()
        run_git(repository, "init", "--quiet")
        run_git(repository, "config", "user.name", "HFS Test")
        run_git(repository, "config", "user.email", "hfs-test@example.invalid")
        run_git(repository, "config", "commit.gpgsign", "false")
        run_git(repository, "config", "tag.gpgsign", "false")
        run_git(repository, "config", "core.autocrlf", "false")

        config = load_config()
        profile = config["profiles"]["formal"]
        source_paths = set(config["source_to_bundle"]) | {profile["manifest"]}
        for source_path in sorted(source_paths):
            target = repository / source_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(exporter.blob(SOURCE_COMMIT, source_path))
            target.chmod(exporter.tree_mode(SOURCE_COMMIT, source_path))

        run_git(repository, "add", "--all")
        run_git(repository, "commit", "--quiet", "-m", "alternate wrapper source")
        alternate_commit = run_git(repository, "rev-parse", "HEAD")

        (repository / ".authorized-revision").write_text("authorized\n", encoding="utf-8")
        run_git(repository, "add", ".authorized-revision")
        run_git(repository, "commit", "--quiet", "-m", "authorized wrapper source")
        authorized_commit = run_git(repository, "rev-parse", "HEAD")
        tree_object = run_git(repository, "rev-parse", "HEAD^{tree}")
        run_git(
            repository,
            "tag",
            "-a",
            "alternate-wrapper",
            "-m",
            "alternate wrapper tag",
            alternate_commit,
        )
        tag_object = run_git(repository, "rev-parse", "refs/tags/alternate-wrapper")
        return repository, alternate_commit, authorized_commit, tree_object, tag_object

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

    def test_manifest_validation_rejects_non_preview_profile(self) -> None:
        payload = exporter.blob(SOURCE_COMMIT, "hfs-dev.toml").replace(
            b'project_class = "preview"',
            b'project_class = "production"',
            1,
        )

        with self.assertRaisesRegex(BundleError, "HFS 2.1 Preview primary profile"):
            validate_manifest(payload, "BlueSkyXN/dify-all-in-one")

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
            root = Path(temporary)
            repository, alternate, authorized, _tree, _tag = self.make_source_repository(root)
            with mock.patch.object(exporter, "REPO_ROOT", repository):
                bundle = self.make_bundle(root / "bundle", alternate)
                with self.assertRaisesRegex(
                    BundleError,
                    "wrapper source commit does not match authorized source commit",
                ):
                    verify_bundle(bundle, "formal", authorized)

    def test_verify_rejects_non_commit_authorization_objects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository, alternate, _authorized, tree_object, tag_object = self.make_source_repository(root)
            with mock.patch.object(exporter, "REPO_ROOT", repository):
                bundle = self.make_bundle(root / "bundle", alternate)
                for object_sha in (tree_object, tag_object):
                    with self.subTest(object_sha=object_sha), self.assertRaisesRegex(
                        BundleError,
                        "must identify a Git commit",
                    ):
                        verify_bundle(bundle, "formal", object_sha)


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
