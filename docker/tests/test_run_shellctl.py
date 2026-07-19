import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUN_SHELLCTL = ROOT / "docker" / "run-shellctl"


class RunShellctlTests(unittest.TestCase):
    def test_runs_go_shellctl_with_supported_flags_and_runtime_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            capture = root / "capture.txt"
            fake_shellctl = root / "shellctl"
            fake_shellctl.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    {
                      printf 'args='
                      printf '%q ' "$@"
                      printf '\\nstate=%s\\ntoken=%s\\n' "${SHELLCTL_STATE_DIR:-}" "${SHELLCTL_AUTH_TOKEN:-}"
                    } > "${SHELLCTL_CAPTURE}"
                    """
                ),
                encoding="utf-8",
            )
            fake_shellctl.chmod(0o755)

            env = os.environ.copy()
            env.update(
                {
                    "DIFY_AGENT_ENABLED": "true",
                    "AGENT_SHELL_ENABLED": "true",
                    "DIFY_AGENT_SHELLCTL_AUTH_TOKEN": "test-token",
                    "RUNTIME_ROOT": str(root / "runtime"),
                    "SHELLCTL_BINARY": str(fake_shellctl),
                    "SHELLCTL_CAPTURE": str(capture),
                }
            )
            result = subprocess.run(
                ["bash", str(RUN_SHELLCTL)],
                text=True,
                capture_output=True,
                check=False,
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            state_dir = root / "runtime" / "shellctl"
            self.assertTrue(state_dir.is_dir())
            captured = capture.read_text(encoding="utf-8")
            self.assertIn("args=serve --listen 127.0.0.1:5004 --state-dir", captured)
            self.assertNotIn("--runtime-dir", captured)
            self.assertIn(f"state={state_dir}", captured)
            self.assertIn("token=test-token", captured)

    def test_fails_when_go_shellctl_binary_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env = os.environ.copy()
            env.update(
                {
                    "DIFY_AGENT_ENABLED": "true",
                    "AGENT_SHELL_ENABLED": "true",
                    "SHELLCTL_BINARY": str(Path(tmpdir) / "missing-shellctl"),
                }
            )
            result = subprocess.run(
                ["bash", str(RUN_SHELLCTL)],
                text=True,
                capture_output=True,
                check=False,
                env=env,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Go shellctl binary is missing", result.stderr)


if __name__ == "__main__":
    unittest.main()
