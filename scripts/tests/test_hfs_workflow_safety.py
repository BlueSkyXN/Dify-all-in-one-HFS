from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FORMAL_WORKFLOW = REPO_ROOT / ".github/workflows/deploy-hfs-formal.yml"
ARTIFACT_WORKFLOW = REPO_ROOT / ".github/workflows/publish-dify-runtime-artifact.yml"
PRODUCER_WORKFLOW = REPO_ROOT / ".github/workflows/produce-dify-runtime.yml"


class WorkflowSafetyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.formal = FORMAL_WORKFLOW.read_text(encoding="utf-8")
        cls.artifact = ARTIFACT_WORKFLOW.read_text(encoding="utf-8")
        cls.producer = PRODUCER_WORKFLOW.read_text(encoding="utf-8")

    def test_formal_requires_independent_factory_reboot_confirmation(self) -> None:
        self.assertIn("confirm_factory_reboot:", self.formal)
        self.assertIn(
            "CONFIRM_FACTORY_REBOOT: ${{ inputs.confirm_factory_reboot }}", self.formal
        )
        self.assertIn('[[ "$CONFIRM_FACTORY_REBOOT" == FACTORY_REBOOT ]]', self.formal)

    def test_formal_requires_verified_artifact_binding_before_reboot(self) -> None:
        self.assertIn("confirm_artifact_binding:", self.formal)
        self.assertIn('[[ "$CONFIRM_ARTIFACT_BINDING" == BIND_ARTIFACT ]]', self.formal)
        binding = self.formal.index("scripts/deploy_hfs_formal.py bind-artifact")
        reboot = self.formal.index("scripts/deploy_hfs_formal.py reboot")
        self.assertLess(binding, reboot)
        self.assertIn('--artifact-ref "$ARTIFACT_REF"', self.formal[binding:])

    def test_formal_upload_uses_cas_helper_instead_of_unconditional_cli_upload(
        self,
    ) -> None:
        self.assertIn("scripts/deploy_hfs_formal.py upload", self.formal)
        self.assertIn("scripts/deploy_hfs_formal.py bind-artifact", self.formal)
        self.assertIn("scripts/deploy_hfs_formal.py reboot", self.formal)
        self.assertNotIn("huggingface_hub.cli.hf upload", self.formal)

    def test_artifact_publication_requires_exact_main_checkout(self) -> None:
        for expected in (
            '[[ "$GITHUB_REF" == refs/heads/main ]]',
            '[[ "$(git rev-parse HEAD)" == "$GITHUB_SHA" ]]',
            '[[ "$(git rev-parse origin/main)" == "$GITHUB_SHA" ]]',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, self.artifact)

    def test_runtime_producer_is_a_pinned_reusable_workflow(self) -> None:
        self.assertIn("workflow_call:", self.producer)
        self.assertNotIn("workflow_dispatch:", self.producer)
        for input_name in (
            "source_repository:",
            "upstream_base_ref:",
            "contract_ref:",
        ):
            with self.subTest(input_name=input_name):
                self.assertIn(input_name, self.producer)
        self.assertIn("ref: ${{ inputs.contract_ref }}", self.producer)
        self.assertNotIn("secrets: inherit", self.producer)

    def test_runtime_producer_binds_caller_main_and_contract_commit(self) -> None:
        for expected in (
            "github.repository == inputs.source_repository",
            'test "$GITHUB_SHA" = "$ARTIFACT_REF"',
            'test "$(git -C consumer rev-parse HEAD)" = "$CONTRACT_REF"',
            'merge-base --is-ancestor "$DIFY_UPSTREAM_BASE_REF" "$ARTIFACT_REF"',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, self.producer)

    def test_runtime_producer_validates_before_creating_release(self) -> None:
        package = self.producer.index("Package and execute the complete consumer contract")
        release = self.producer.index("gh release create")
        readback = self.producer.index("Read back every Release asset")
        self.assertLess(package, release)
        self.assertLess(release, readback)


if __name__ == "__main__":
    unittest.main()
