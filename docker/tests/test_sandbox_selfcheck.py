import importlib.machinery
import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str, path: Path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


sandbox_selfcheck = load_script("sandbox_selfcheck_under_test", ROOT / "docker" / "sandbox-selfcheck")


class SandboxSelfcheckResponseTests(unittest.TestCase):
    def test_parse_run_response_requires_zero_exit_code(self):
        response = json.dumps(
            {
                "code": 0,
                "message": "success",
                "data": {
                    "stdout": f"{sandbox_selfcheck.MARKER}\n",
                    "stderr": "",
                    "error": "process exited with code -1\nerror: signal: bad system call\n",
                    "exit_code": -1,
                },
            }
        )

        parsed = sandbox_selfcheck.parse_run_response(response)

        self.assertTrue(parsed["json_ok"])
        self.assertTrue(parsed["contains_marker"])
        self.assertEqual(parsed["exit_code"], -1)
        self.assertIn("exit_code", parsed["error"])

    def test_parse_run_response_accepts_clean_success(self):
        response = json.dumps(
            {
                "code": 0,
                "message": "success",
                "data": {
                    "stdout": f"{sandbox_selfcheck.MARKER}\n",
                    "stderr": "",
                    "error": "",
                    "exit_code": 0,
                },
            }
        )

        parsed = sandbox_selfcheck.parse_run_response(response)

        self.assertTrue(parsed["json_ok"])
        self.assertTrue(parsed["contains_marker"])
        self.assertEqual(parsed["outer_code"], 0)
        self.assertEqual(parsed["exit_code"], 0)
        self.assertEqual(parsed["sandbox_error"], "")
        self.assertNotIn("error", parsed)

    def test_parse_run_response_rejects_invalid_json(self):
        parsed = sandbox_selfcheck.parse_run_response(f"{sandbox_selfcheck.MARKER}\n")

        self.assertFalse(parsed["json_ok"])
        self.assertTrue(parsed["contains_marker"])
        self.assertIn("invalid sandbox JSON response", parsed["error"])


if __name__ == "__main__":
    unittest.main()
