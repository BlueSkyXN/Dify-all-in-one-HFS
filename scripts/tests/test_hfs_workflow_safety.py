from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FORMAL_WORKFLOW = REPO_ROOT / ".github/workflows/deploy-hfs-formal.yml"
ARTIFACT_WORKFLOW = REPO_ROOT / ".github/workflows/publish-dify-runtime-artifact.yml"


class WorkflowSafetyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.formal = FORMAL_WORKFLOW.read_text(encoding="utf-8")
        cls.artifact = ARTIFACT_WORKFLOW.read_text(encoding="utf-8")

    def test_formal_requires_independent_factory_reboot_confirmation(self) -> None:
        self.assertIn("confirm_factory_reboot:", self.formal)
        self.assertIn(
            "CONFIRM_FACTORY_REBOOT: ${{ inputs.confirm_factory_reboot }}", self.formal
        )
        self.assertIn('[[ "$CONFIRM_FACTORY_REBOOT" == FACTORY_REBOOT ]]', self.formal)

    def test_formal_upload_uses_cas_helper_instead_of_unconditional_cli_upload(
        self,
    ) -> None:
        self.assertIn("scripts/deploy_hfs_formal.py upload", self.formal)
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


if __name__ == "__main__":
    unittest.main()
