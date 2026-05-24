import importlib.util
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


admin_service = load_module("admin_service_under_test", ROOT / "docker" / "admin_service.py")


class AdminServicePureFunctionTests(unittest.TestCase):
    def setUp(self):
        self.original_admin_token = os.environ.get("ADMIN_TOKEN")
        os.environ["ADMIN_TOKEN"] = "test-admin-token"

    def tearDown(self):
        if self.original_admin_token is None:
            os.environ.pop("ADMIN_TOKEN", None)
        else:
            os.environ["ADMIN_TOKEN"] = self.original_admin_token

    def test_parse_session_accepts_signed_session_and_rejects_tampering(self):
        cookie_value, _csrf, expires_at = admin_service.make_session()
        parsed = admin_service.parse_session(cookie_value)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.kind, "cookie")
        self.assertEqual(parsed.expires_at, expires_at)
        self.assertIsNone(admin_service.parse_session(cookie_value + "tampered"))

    def test_parse_session_rejects_expired_session(self):
        nonce = "nonce"
        expires_at = int(time.time()) - 1
        signature = admin_service.sign_message("session", str(expires_at), nonce)
        self.assertIsNone(admin_service.parse_session(f"{expires_at}.{nonce}.{signature}"))

    def test_normalise_admin_path_rejects_escape(self):
        self.assertEqual(admin_service.normalise_admin_path("/logs/app.log"), Path("logs/app.log"))
        with self.assertRaises(admin_service.AdminError):
            admin_service.normalise_admin_path("../generated.env")
        with self.assertRaises(admin_service.AdminError):
            admin_service.normalise_admin_path("bad\0path")

    def test_ensure_inside_root_rejects_paths_outside_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            admin_service.ensure_inside_root(root / "subdir" / "file.txt", root)
            with self.assertRaises(admin_service.AdminError):
                admin_service.ensure_inside_root(root.parent / "outside.txt", root)

    def test_is_protected_path_matches_generated_env_and_sensitive_names(self):
        self.assertTrue(admin_service.is_protected_path(Path("/data/config/generated.env")))
        self.assertTrue(admin_service.is_protected_path(Path("/data/config/api-token.txt")))
        self.assertTrue(admin_service.is_protected_path(Path("/data/config/private.pem")))
        self.assertFalse(admin_service.is_protected_path(Path("/data/uploads/plain.txt")))

    def test_destructive_file_operations_default_off(self):
        original_enabled = os.environ.get("ADMIN_FILES_ENABLED")
        original_write = os.environ.get("ADMIN_FILES_WRITE_ENABLED")
        original_destructive = os.environ.get("ADMIN_FILES_DESTRUCTIVE_ENABLED")
        try:
            os.environ["ADMIN_FILES_ENABLED"] = "true"
            os.environ["ADMIN_FILES_WRITE_ENABLED"] = "true"
            os.environ.pop("ADMIN_FILES_DESTRUCTIVE_ENABLED", None)
            with self.assertRaises(admin_service.AdminError):
                admin_service.require_files_destructive_enabled()
            os.environ["ADMIN_FILES_DESTRUCTIVE_ENABLED"] = "true"
            admin_service.require_files_destructive_enabled()
        finally:
            if original_enabled is None:
                os.environ.pop("ADMIN_FILES_ENABLED", None)
            else:
                os.environ["ADMIN_FILES_ENABLED"] = original_enabled
            if original_write is None:
                os.environ.pop("ADMIN_FILES_WRITE_ENABLED", None)
            else:
                os.environ["ADMIN_FILES_WRITE_ENABLED"] = original_write
            if original_destructive is None:
                os.environ.pop("ADMIN_FILES_DESTRUCTIVE_ENABLED", None)
            else:
                os.environ["ADMIN_FILES_DESTRUCTIVE_ENABLED"] = original_destructive

    def test_trusted_remote_addr_ignores_spoofed_x_forwarded_for(self):
        headers = {"X-Forwarded-For": "203.0.113.99", "X-Real-IP": "198.51.100.10"}
        self.assertEqual(
            admin_service.trusted_remote_addr(headers, ("127.0.0.1", 12345)),
            "198.51.100.10",
        )
        self.assertEqual(
            admin_service.trusted_remote_addr(
                {"X-Forwarded-For": "203.0.113.99"},
                ("127.0.0.1", 12345),
            ),
            "127.0.0.1",
        )


if __name__ == "__main__":
    unittest.main()
