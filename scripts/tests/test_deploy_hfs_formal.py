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


class FakeApi:
    def __init__(self) -> None:
        self.current_sha = PREFLIGHT_SHA
        self.expected_paths = {"BUILD_SOURCE.json", "README.md"}
        self.create_calls: list[dict[str, object]] = []
        self.restart_calls: list[tuple[str, str, bool]] = []
        self.runtime = SimpleNamespace(stage="RUNNING", raw={"sha": DEPLOYED_SHA})

    def space_info(self, _space: str, *, token: str):
        del token
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
            confirmation="FACTORY_REBOOT",
            monotonic=lambda: 0,
            sleep=lambda _seconds: None,
        )
        self.assertEqual(
            api.restart_calls,
            [("BlueSkyXN/dify-all-in-one", "token", True)],
        )


if __name__ == "__main__":
    unittest.main()
