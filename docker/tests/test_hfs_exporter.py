from __future__ import annotations

import unittest

from scripts.export_hfs_space_bundle import BundleError, validate_dockerfile_sources


class HfsExporterTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
