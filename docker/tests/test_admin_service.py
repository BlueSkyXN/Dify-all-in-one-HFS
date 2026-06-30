import importlib.util
import hashlib
import hmac
import json
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
        self.original_env = os.environ.copy()
        admin_service.LOGIN_FAILURES_BY_IP.clear()
        admin_service.LOGIN_FAILURES_GLOBAL.clear()
        os.environ["ADMIN_TOKEN"] = "test-admin-token"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)
        admin_service.LOGIN_FAILURES_BY_IP.clear()
        admin_service.LOGIN_FAILURES_GLOBAL.clear()

    def test_parse_session_accepts_signed_session_and_rejects_tampering(self):
        cookie_value, _csrf, expires_at = admin_service.make_session()
        parsed = admin_service.parse_session(cookie_value)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.kind, "cookie")
        self.assertEqual(parsed.expires_at, expires_at)
        self.assertGreaterEqual(len(parsed.nonce), 43)
        self.assertIsNone(admin_service.parse_session(cookie_value + "tampered"))

    def test_csrf_key_prefers_admin_csrf_key_then_secret_key(self):
        os.environ["ADMIN_CSRF_KEY"] = "csrf-key"
        cookie_value, csrf_token, _expires_at = admin_service.make_session()
        expires_raw, nonce, _signature = cookie_value.split(".", 2)
        expected = hmac.new(
            b"csrf-key",
            f"csrf|{expires_raw}|{nonce}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(csrf_token, expected)

        os.environ.pop("ADMIN_CSRF_KEY")
        os.environ["SECRET_KEY"] = "runtime-secret"
        cookie_value, csrf_token, _expires_at = admin_service.make_session()
        expires_raw, nonce, _signature = cookie_value.split(".", 2)
        derived_key = hmac.new(b"runtime-secret", b"dify-aio-admin-csrf", hashlib.sha256).hexdigest()
        expected = hmac.new(
            derived_key.encode("utf-8"),
            f"csrf|{expires_raw}|{nonce}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(csrf_token, expected)

    def test_require_csrf_rejects_bad_cookie_session_token(self):
        class FakeHandler:
            headers = {"X-Admin-CSRF": "wrong"}
            sent = None

            def send_json(self, payload, status=200):
                self.sent = (payload, status)

        fake = FakeHandler()
        auth = admin_service.AuthContext(kind="cookie", csrf_token="expected")
        self.assertFalse(admin_service.Handler.require_csrf(fake, auth))
        self.assertEqual(fake.sent[1], 403)

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
        self.assertTrue(admin_service.is_protected_path(Path("/data/config/access_token.json")))
        self.assertTrue(admin_service.is_protected_path(Path("/data/config/github-token-backup.txt")))
        self.assertTrue(admin_service.is_protected_path(Path("/data/config/access_token_backup.json")))
        self.assertTrue(admin_service.is_protected_path(Path("/data/config/mytoken.txt")))
        self.assertTrue(admin_service.is_protected_path(Path("/data/config/private.pem")))
        self.assertTrue(admin_service.is_protected_path(Path("/data/config/service-secret.txt")))
        self.assertTrue(admin_service.is_protected_path(Path("/data/dependencies/tokenizer-token.txt")))
        self.assertFalse(admin_service.is_protected_path(Path("/data/dependencies/tokenizer.json")))
        self.assertFalse(admin_service.is_protected_path(Path("/data/dependencies/tokenizer_config.json")))
        self.assertFalse(admin_service.is_protected_path(Path("/data/dependencies/tokenization_report.txt")))
        self.assertFalse(admin_service.is_protected_path(Path("/data/uploads/plain.txt")))

    def test_content_disposition_attachment_sanitizes_filename_header(self):
        header = admin_service.content_disposition_attachment('bad"\r\nX-Test: yes-报告.txt')

        self.assertNotIn("\r", header)
        self.assertNotIn("\n", header)
        self.assertIn('filename="bad___X-Test: yes-__.txt"', header)
        self.assertIn("filename*=UTF-8''bad___X-Test%3A%20yes-%E6%8A%A5%E5%91%8A.txt", header)

    def test_login_retry_after_prunes_expired_ip_entries_without_creating_new_ones(self):
        now = time.time()
        os.environ["ADMIN_LOGIN_RATE_LIMIT_WINDOW_SECONDS"] = "10"
        os.environ["ADMIN_LOGIN_RATE_LIMIT_BLOCK_SECONDS"] = "10"
        admin_service.LOGIN_FAILURES_BY_IP["old"].append(now - 100)
        self.assertEqual(admin_service.login_retry_after("new"), 0)
        self.assertNotIn("old", admin_service.LOGIN_FAILURES_BY_IP)
        self.assertNotIn("new", admin_service.LOGIN_FAILURES_BY_IP)

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

    def test_ensure_app_api_token_requires_confirm(self):
        with self.assertRaises(admin_service.AdminError) as ctx:
            admin_service.ensure_app_api_token(
                {"app_id": "d3e5efe9-0897-4659-ad70-8fe97459cd2e"},
                admin_service.AuthContext(kind="token", csrf_token="1"),
            )

        self.assertEqual(ctx.exception.status, 400)

    def test_ensure_app_api_token_inserts_requested_token_without_echoing_raw_token(self):
        original_psql_json_rows = admin_service.psql_json_rows
        original_run_psql = admin_service.run_psql
        captured = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["ADMIN_AUDIT_LOG"] = str(Path(tmpdir) / "admin-audit.jsonl")

            def fake_psql_json_rows(sql, timeout=10.0):
                captured["select_sql"] = sql
                return {
                    "ok": True,
                    "count": 1,
                    "rows": [
                        {
                            "app_id": "d3e5efe9-0897-4659-ad70-8fe97459cd2e",
                            "tenant_id": "3cb20998-caac-4467-8ca5-7c7caacb31ab",
                            "app_name": "Test",
                            "enable_api": True,
                            "api_token_count": 0,
                            "token_exists": False,
                        }
                    ],
                }

            def fake_run_psql(sql, timeout=10.0, output_limit=200_000):
                captured["insert_sql"] = sql
                return {"ok": True, "returncode": 0, "stdout": "", "stderr": "", "duration_ms": 1}

            try:
                admin_service.psql_json_rows = fake_psql_json_rows
                admin_service.run_psql = fake_run_psql
                response = admin_service.ensure_app_api_token(
                    {
                        "confirm": True,
                        "app_id": "d3e5efe9-0897-4659-ad70-8fe97459cd2e",
                        "token": "app-testToken1234567890",
                    },
                    admin_service.AuthContext(kind="token", csrf_token="1"),
                )
            finally:
                admin_service.psql_json_rows = original_psql_json_rows
                admin_service.run_psql = original_run_psql

        self.assertTrue(response["ok"])
        self.assertTrue(response["created"])
        self.assertNotIn("token", response)
        self.assertEqual(response["api_token_count_after"], 1)
        self.assertEqual(response["token_summary"]["prefix"], "app-")
        self.assertIn("api_tokens", captured["insert_sql"])

    def test_ensure_app_api_token_returns_generated_token_once(self):
        original_psql_json_rows = admin_service.psql_json_rows
        original_run_psql = admin_service.run_psql

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["ADMIN_AUDIT_LOG"] = str(Path(tmpdir) / "admin-audit.jsonl")

            def fake_psql_json_rows(sql, timeout=10.0):
                return {
                    "ok": True,
                    "count": 1,
                    "rows": [
                        {
                            "app_id": "d3e5efe9-0897-4659-ad70-8fe97459cd2e",
                            "tenant_id": "3cb20998-caac-4467-8ca5-7c7caacb31ab",
                            "app_name": "Test",
                            "enable_api": True,
                            "api_token_count": 0,
                            "token_exists": False,
                        }
                    ],
                }

            try:
                admin_service.psql_json_rows = fake_psql_json_rows
                admin_service.run_psql = lambda sql, timeout=10.0, output_limit=200_000: {
                    "ok": True,
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                    "duration_ms": 1,
                }
                response = admin_service.ensure_app_api_token(
                    {"confirm": True, "app_id": "d3e5efe9-0897-4659-ad70-8fe97459cd2e"},
                    admin_service.AuthContext(kind="token", csrf_token="1"),
                )
            finally:
                admin_service.psql_json_rows = original_psql_json_rows
                admin_service.run_psql = original_run_psql

        self.assertTrue(response["ok"])
        self.assertTrue(response["created"])
        self.assertRegex(response["token"], r"^app-[A-Za-z0-9]{24}$")
        self.assertEqual(response["token_summary"]["length"], len(response["token"]))

    def test_ensure_plugin_installed_from_cache_requires_confirm(self):
        with self.assertRaises(admin_service.AdminError) as ctx:
            admin_service.ensure_plugin_installed_from_cache(
                {},
                admin_service.AuthContext(kind="token", csrf_token="1"),
            )

        self.assertEqual(ctx.exception.status, 400)

    def test_ensure_plugin_installed_from_cache_copies_registered_package_and_restarts(self):
        original_plugin_db_identifiers = admin_service.plugin_db_identifiers
        original_run_cmd = admin_service.run_cmd
        calls = []
        identifier = "langgenius/openai_api_compatible:0.0.49@abc123"

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "plugin_daemon"
            package_file = root / "plugin_packages" / "langgenius" / "openai_api_compatible:0.0.49@abc123"
            package_file.parent.mkdir(parents=True)
            package_file.write_bytes(b"plugin package")
            os.environ["PLUGIN_STORAGE_LOCAL_ROOT"] = str(root)
            os.environ["ADMIN_AUDIT_LOG"] = str(Path(tmpdir) / "admin-audit.jsonl")

            def fake_plugin_db_identifiers():
                return {
                    "ok": True,
                    "count": 1,
                    "rows": [{"plugin_unique_identifier": identifier}],
                }

            def fake_run_cmd(args, timeout=10.0, extra_env=None, output_limit=200_000):
                calls.append((args, timeout))
                return {"ok": True, "returncode": 0, "stdout": "ok", "stderr": "", "duration_ms": 1}

            try:
                admin_service.plugin_db_identifiers = fake_plugin_db_identifiers
                admin_service.run_cmd = fake_run_cmd
                response = admin_service.ensure_plugin_installed_from_cache(
                    {"confirm": True, "plugin_unique_identifier": identifier},
                    admin_service.AuthContext(kind="token", csrf_token="1"),
                )
            finally:
                admin_service.plugin_db_identifiers = original_plugin_db_identifiers
                admin_service.run_cmd = original_run_cmd

            installed_file = root / "plugin" / "langgenius" / "openai_api_compatible:0.0.49@abc123"
            self.assertTrue(installed_file.is_file())
            self.assertEqual(installed_file.read_bytes(), b"plugin package")

        self.assertTrue(response["ok"])
        self.assertEqual(response["copied_count"], 1)
        self.assertEqual(response["missing_source_count"], 0)
        self.assertEqual(response["copied"][0]["plugin_unique_identifier"], identifier)
        self.assertNotIn(str(root), json.dumps(response))
        self.assertEqual(calls[0][0][-1], "plugin-daemon")

    def test_ensure_plugin_installed_from_cache_rejects_unregistered_identifier(self):
        original_plugin_db_identifiers = admin_service.plugin_db_identifiers
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["ADMIN_AUDIT_LOG"] = str(Path(tmpdir) / "admin-audit.jsonl")
            try:
                admin_service.plugin_db_identifiers = lambda: {
                    "ok": True,
                    "count": 1,
                    "rows": [{"plugin_unique_identifier": "langgenius/openai:0.4.0@abc"}],
                }
                with self.assertRaises(admin_service.AdminError) as ctx:
                    admin_service.ensure_plugin_installed_from_cache(
                        {
                            "confirm": True,
                            "plugin_unique_identifier": "langgenius/openai_api_compatible:0.0.49@abc123",
                        },
                        admin_service.AuthContext(kind="token", csrf_token="1"),
                    )
            finally:
                admin_service.plugin_db_identifiers = original_plugin_db_identifiers

        self.assertEqual(ctx.exception.status, 404)


if __name__ == "__main__":
    unittest.main()
