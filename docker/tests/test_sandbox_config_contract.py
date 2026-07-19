import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class SandboxConfigContractTests(unittest.TestCase):
    def test_uses_python_path_discovery_without_deprecated_library_path_inputs(self):
        entrypoint = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
        wrapper = (ROOT / "docker" / "with-sandbox-env").read_text(encoding="utf-8")
        runtime_env = (ROOT / "docker" / "dify.env.runtime").read_text(encoding="utf-8")

        self.assertIn('python_path: "${python_path}"', entrypoint)
        self.assertIn('export PYTHON_PATH="${SANDBOX_PYTHON_PATH:-/usr/local/bin/python3}"', wrapper)
        for content in (entrypoint, wrapper, runtime_env):
            self.assertNotIn("SANDBOX_PYTHON_LIB_PATH", content)
            self.assertNotIn("PYTHON_LIB_PATH", content)
        self.assertNotIn("python_lib_path:", entrypoint)


if __name__ == "__main__":
    unittest.main()
