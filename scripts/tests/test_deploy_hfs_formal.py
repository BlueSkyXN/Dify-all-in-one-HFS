from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

MODULE_PATH = Path(__file__).parents[1] / "deploy_hfs_formal.py"
SPEC = importlib.util.spec_from_file_location("deploy_hfs_formal_tested", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load formal HFS deployment helper")
formal = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = formal
SPEC.loader.exec_module(formal)


PREFLIGHT_SHA = "1" * 40
DEPLOYED_SHA = "2" * 40
SOURCE_REF = "3" * 40
ARTIFACT_REF = "4" * 40
OLD_ARTIFACT_REF = "5" * 40
RELEASE_TAG = "hfs-artifact-9885d17ba8f4"


class FakeApi:
    def __init__(self) -> None:
        self.current_sha = PREFLIGHT_SHA
        self.sha_responses: list[str] = []
        self.expected_paths = {"BUILD_SOURCE.json", "README.md"}
        self.create_calls: list[dict[str, object]] = []
        self.restart_calls: list[tuple[str, str, bool]] = []
        self.runtime = SimpleNamespace(stage="RUNNING", raw={"sha": DEPLOYED_SHA})
        self.variables = {
            formal.MANIFEST_URI_VARIABLE: SimpleNamespace(
                value="hf://buckets/BlueSkyXN/hfs-dist/dify-all-in-one/release/manifest.json"
            ),
            formal.EXPECTED_ARTIFACT_VARIABLE: SimpleNamespace(value=ARTIFACT_REF),
            formal.MAX_BYTES_VARIABLE: SimpleNamespace(value=str(4 * 1024**3)),
        }
        self.variable_updates: list[tuple[str, str, str]] = []
        self.manifest = {
            "schema_version": 2,
            "project": "dify-all-in-one",
            "slot": "release",
            "source_kind": "tag",
            "source_ref": RELEASE_TAG,
            "artifact_ref": ARTIFACT_REF,
            "artifact": f"dify-runtime-{ARTIFACT_REF}.tar.gz",
            "sha256": "6" * 64,
            "size_bytes": 1024,
            "unpacked_size_bytes": 2048,
            "runtime_lock_sha256": "7" * 64,
            "generated_at": "2026-07-31T00:00:00Z",
            "artifact_key": f"dify-all-in-one/release/dify-runtime-{ARTIFACT_REF}.tar.gz",
            "manifest_key": "dify-all-in-one/release/manifest.json",
        }

    def space_info(self, _space: str, *, token: str):
        del token
        if self.sha_responses:
            return SimpleNamespace(sha=self.sha_responses.pop(0))
        return SimpleNamespace(sha=self.current_sha)

    def list_repo_files(
        self,
        _space: str,
        *,
        revision: str,
        repo_type: str,
        token: str,
    ) -> list[str]:
        del repo_type, token
        self.asserted_revision = revision
        return sorted(self.expected_paths)

    def create_commit(self, **kwargs):
        self.create_calls.append(kwargs)
        self.current_sha = DEPLOYED_SHA
        return SimpleNamespace(oid=DEPLOYED_SHA)

    def restart_space(self, space: str, *, token: str, factory_reboot: bool):
        self.restart_calls.append((space, token, factory_reboot))

    def get_space_runtime(self, _space: str, *, token: str):
        del token
        return self.runtime

    def get_space_variables(self, _space: str, *, token: str):
        del token
        return dict(self.variables)

    def add_space_variable(
        self,
        space: str,
        key: str,
        value: str,
        *,
        description: str,
        token: str,
    ):
        del description, token
        self.variable_updates.append((space, key, value))
        self.variables[key] = SimpleNamespace(value=value)
        return dict(self.variables)

    def download_bucket_files(
        self,
        bucket_id: str,
        files: list[tuple[str, Path]],
        *,
        raise_on_missing_files: bool,
        token: str,
    ) -> None:
        del token
        if bucket_id != "BlueSkyXN/hfs-dist" or not raise_on_missing_files:
            raise AssertionError("unexpected formal Bucket download")
        for remote, local in files:
            if remote != "dify-all-in-one/release/manifest.json":
                raise AssertionError("unexpected formal manifest path")
            Path(local).write_text(json.dumps(self.manifest), encoding="utf-8")


class FormalDeploymentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "bundle"
        self.bundle.mkdir()
        (self.bundle / "BUILD_SOURCE.json").write_text(
            json.dumps({"wrapper_source_commit": SOURCE_REF}), encoding="utf-8"
        )
        (self.bundle / "README.md").write_text("formal bundle\n", encoding="utf-8")
        self.paths_file = self.root / "paths.txt"
        self.paths_file.write_text("BUILD_SOURCE.json\nREADME.md\n", encoding="utf-8")
        self.remote = self.root / "remote"
        self.remote.mkdir()
        for relative in ("BUILD_SOURCE.json", "README.md"):
            (self.remote / relative).write_bytes((self.bundle / relative).read_bytes())

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _download(self, *, filename: str, **_kwargs) -> Path:
        return self.remote / filename

    def test_upload_uses_preflight_revision_as_parent_and_reads_back_returned_commit(
        self,
    ) -> None:
        api = FakeApi()
        operations: list[tuple[str, Path]] = []

        deployed = formal.upload_formal_bundle(
            api,
            token="token",
            space="BlueSkyXN/dify-all-in-one",
            bundle=self.bundle,
            paths_file=self.paths_file,
            source_ref=SOURCE_REF,
            operation_factory=lambda relative, local: (
                operations.append((relative, local)) or (relative, local)
            ),
            download_file=self._download,
        )

        self.assertEqual(deployed, DEPLOYED_SHA)
        self.assertEqual(api.create_calls[0]["parent_commit"], PREFLIGHT_SHA)
        self.assertEqual(api.create_calls[0]["revision"], "main")
        self.assertEqual({relative for relative, _ in operations}, api.expected_paths)
        self.assertEqual(api.asserted_revision, DEPLOYED_SHA)

    def test_upload_rejects_unknown_remote_path_before_commit(self) -> None:
        api = FakeApi()
        api.expected_paths.add("unexpected.txt")
        with self.assertRaisesRegex(
            formal.FormalDeploymentError, "outside the formal bundle"
        ):
            formal.upload_formal_bundle(
                api,
                token="token",
                space="BlueSkyXN/dify-all-in-one",
                bundle=self.bundle,
                paths_file=self.paths_file,
                source_ref=SOURCE_REF,
                operation_factory=lambda relative, local: (relative, local),
                download_file=self._download,
            )
        self.assertFalse(api.create_calls)

    def test_upload_rejects_hash_mismatch_after_commit(self) -> None:
        api = FakeApi()
        (self.remote / "README.md").write_text("wrong\n", encoding="utf-8")
        with self.assertRaisesRegex(formal.FormalDeploymentError, "readback mismatch"):
            formal.upload_formal_bundle(
                api,
                token="token",
                space="BlueSkyXN/dify-all-in-one",
                bundle=self.bundle,
                paths_file=self.paths_file,
                source_ref=SOURCE_REF,
                operation_factory=lambda relative, local: (relative, local),
                download_file=self._download,
            )

    def test_reboot_requires_independent_exact_confirmation(self) -> None:
        api = FakeApi()
        api.current_sha = DEPLOYED_SHA
        with self.assertRaisesRegex(formal.FormalDeploymentError, "FACTORY_REBOOT"):
            formal.reboot_formal_space(
                api,
                token="token",
                space="BlueSkyXN/dify-all-in-one",
                deployed_revision=DEPLOYED_SHA,
                artifact_ref=ARTIFACT_REF,
                confirmation="PUBLISH_FORMAL",
            )
        self.assertFalse(api.restart_calls)

    def test_reboot_rejects_space_head_drift(self) -> None:
        api = FakeApi()
        with self.assertRaisesRegex(
            formal.FormalDeploymentError, "changed after verified upload"
        ):
            formal.reboot_formal_space(
                api,
                token="token",
                space="BlueSkyXN/dify-all-in-one",
                deployed_revision=DEPLOYED_SHA,
                artifact_ref=ARTIFACT_REF,
                confirmation="FACTORY_REBOOT",
            )
        self.assertFalse(api.restart_calls)

    def test_reboot_waits_for_exact_verified_runtime(self) -> None:
        api = FakeApi()
        api.current_sha = DEPLOYED_SHA
        formal.reboot_formal_space(
            api,
            token="token",
            space="BlueSkyXN/dify-all-in-one",
            deployed_revision=DEPLOYED_SHA,
            artifact_ref=ARTIFACT_REF,
            confirmation="FACTORY_REBOOT",
            monotonic=lambda: 0,
            sleep=lambda _seconds: None,
        )
        self.assertEqual(
            api.restart_calls,
            [("BlueSkyXN/dify-all-in-one", "token", True)],
        )

    def test_binding_requires_independent_confirmation_before_variable_write(
        self,
    ) -> None:
        api = FakeApi()
        api.current_sha = DEPLOYED_SHA
        with self.assertRaisesRegex(formal.FormalDeploymentError, "BIND_ARTIFACT"):
            formal.bind_formal_artifact(
                api,
                token="token",
                space="BlueSkyXN/dify-all-in-one",
                deployed_revision=DEPLOYED_SHA,
                artifact_ref=ARTIFACT_REF,
                confirmation="PUBLISH_FORMAL",
            )
        self.assertFalse(api.variable_updates)

    def test_binding_verifies_release_manifest_then_updates_and_reads_back(
        self,
    ) -> None:
        api = FakeApi()
        api.current_sha = DEPLOYED_SHA
        api.variables[formal.EXPECTED_ARTIFACT_VARIABLE] = SimpleNamespace(
            value=OLD_ARTIFACT_REF
        )
        formal.bind_formal_artifact(
            api,
            token="token",
            space="BlueSkyXN/dify-all-in-one",
            deployed_revision=DEPLOYED_SHA,
            artifact_ref=ARTIFACT_REF,
            confirmation="BIND_ARTIFACT",
        )
        self.assertEqual(
            api.variable_updates,
            [
                (
                    "BlueSkyXN/dify-all-in-one",
                    formal.EXPECTED_ARTIFACT_VARIABLE,
                    ARTIFACT_REF,
                )
            ],
        )

    def test_binding_rejects_manifest_mismatch_before_variable_write(self) -> None:
        api = FakeApi()
        api.current_sha = DEPLOYED_SHA
        api.manifest["artifact_ref"] = OLD_ARTIFACT_REF
        with self.assertRaisesRegex(
            formal.FormalDeploymentError, "runtime artifact contract"
        ):
            formal.bind_formal_artifact(
                api,
                token="token",
                space="BlueSkyXN/dify-all-in-one",
                deployed_revision=DEPLOYED_SHA,
                artifact_ref=ARTIFACT_REF,
                confirmation="BIND_ARTIFACT",
            )
        self.assertFalse(api.variable_updates)

    def test_reboot_rejects_artifact_variable_drift(self) -> None:
        api = FakeApi()
        api.current_sha = DEPLOYED_SHA
        api.variables[formal.EXPECTED_ARTIFACT_VARIABLE] = SimpleNamespace(
            value=OLD_ARTIFACT_REF
        )
        with self.assertRaisesRegex(
            formal.FormalDeploymentError, "expected artifact Variable"
        ):
            formal.reboot_formal_space(
                api,
                token="token",
                space="BlueSkyXN/dify-all-in-one",
                deployed_revision=DEPLOYED_SHA,
                artifact_ref=ARTIFACT_REF,
                confirmation="FACTORY_REBOOT",
            )
        self.assertFalse(api.restart_calls)

    def test_binding_uses_the_runtime_manifest_contract(self) -> None:
        invalid_manifests = {
            "missing generated_at": lambda payload: payload.pop("generated_at"),
            "invalid generated_at": lambda payload: payload.__setitem__(
                "generated_at", "2026-02-30T00:00:00Z"
            ),
            "excessive unpacked size": lambda payload: payload.__setitem__(
                "unpacked_size_bytes", 32 * 1024**3 + 1
            ),
        }
        for label, mutate in invalid_manifests.items():
            with self.subTest(label=label):
                api = FakeApi()
                api.current_sha = DEPLOYED_SHA
                api.variables[formal.EXPECTED_ARTIFACT_VARIABLE] = SimpleNamespace(
                    value=OLD_ARTIFACT_REF
                )
                mutate(api.manifest)
                with self.assertRaisesRegex(
                    formal.FormalDeploymentError, "runtime artifact contract"
                ):
                    formal.bind_formal_artifact(
                        api,
                        token="token",
                        space="BlueSkyXN/dify-all-in-one",
                        deployed_revision=DEPLOYED_SHA,
                        artifact_ref=ARTIFACT_REF,
                        confirmation="BIND_ARTIFACT",
                    )
                self.assertFalse(api.variable_updates)

    def test_binding_honors_the_effective_space_archive_limit(self) -> None:
        api = FakeApi()
        api.current_sha = DEPLOYED_SHA
        api.variables[formal.EXPECTED_ARTIFACT_VARIABLE] = SimpleNamespace(
            value=OLD_ARTIFACT_REF
        )
        api.variables[formal.MAX_BYTES_VARIABLE] = SimpleNamespace(value="512")
        with self.assertRaisesRegex(
            formal.FormalDeploymentError, "runtime artifact contract"
        ):
            formal.bind_formal_artifact(
                api,
                token="token",
                space="BlueSkyXN/dify-all-in-one",
                deployed_revision=DEPLOYED_SHA,
                artifact_ref=ARTIFACT_REF,
                confirmation="BIND_ARTIFACT",
            )
        self.assertFalse(api.variable_updates)

    def test_binding_rejects_a_commit_manifest_in_the_release_lane(self) -> None:
        api = FakeApi()
        api.current_sha = DEPLOYED_SHA
        api.variables[formal.EXPECTED_ARTIFACT_VARIABLE] = SimpleNamespace(
            value=OLD_ARTIFACT_REF
        )
        api.manifest["source_kind"] = "commit"
        api.manifest["source_ref"] = ARTIFACT_REF
        with self.assertRaisesRegex(formal.FormalDeploymentError, "immutable tag"):
            formal.bind_formal_artifact(
                api,
                token="token",
                space="BlueSkyXN/dify-all-in-one",
                deployed_revision=DEPLOYED_SHA,
                artifact_ref=ARTIFACT_REF,
                confirmation="BIND_ARTIFACT",
            )
        self.assertFalse(api.variable_updates)

    def test_reboot_rejects_space_head_drift_after_manifest_readback(self) -> None:
        api = FakeApi()
        api.sha_responses = [DEPLOYED_SHA, PREFLIGHT_SHA]
        with self.assertRaisesRegex(
            formal.FormalDeploymentError, "changed after verified upload"
        ):
            formal.reboot_formal_space(
                api,
                token="token",
                space="BlueSkyXN/dify-all-in-one",
                deployed_revision=DEPLOYED_SHA,
                artifact_ref=ARTIFACT_REF,
                confirmation="FACTORY_REBOOT",
            )
        self.assertFalse(api.restart_calls)

    def test_binding_rejects_space_head_drift_immediately_before_write(self) -> None:
        api = FakeApi()
        api.current_sha = DEPLOYED_SHA
        api.sha_responses = [DEPLOYED_SHA, PREFLIGHT_SHA]
        api.variables[formal.EXPECTED_ARTIFACT_VARIABLE] = SimpleNamespace(
            value=OLD_ARTIFACT_REF
        )
        with self.assertRaisesRegex(
            formal.FormalDeploymentError, "changed after verified upload"
        ):
            formal.bind_formal_artifact(
                api,
                token="token",
                space="BlueSkyXN/dify-all-in-one",
                deployed_revision=DEPLOYED_SHA,
                artifact_ref=ARTIFACT_REF,
                confirmation="BIND_ARTIFACT",
            )
        self.assertFalse(api.variable_updates)


if __name__ == "__main__":
    unittest.main()
