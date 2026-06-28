import importlib.util
import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ops_service = load_module("ops_service_under_test", ROOT / "docker" / "ops_service.py")


class OpsServicePureFunctionTests(unittest.TestCase):
    def setUp(self):
        self.original_env = os.environ.copy()
        self.original_log_dir = ops_service.LOG_DIR
        ops_service.OPS_CACHE.clear()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)
        ops_service.LOG_DIR = self.original_log_dir
        ops_service.OPS_CACHE.clear()

    def test_safe_log_filename_rejects_absolute_and_parent_paths(self):
        self.assertEqual(ops_service.safe_log_filename("nginx.log"), "nginx.log")
        self.assertEqual(ops_service.safe_log_filename("nested/app.log"), "nested/app.log")
        self.assertIsNone(ops_service.safe_log_filename("/data/logs/nginx.log"))
        self.assertIsNone(ops_service.safe_log_filename("../nginx.log"))
        self.assertIsNone(ops_service.safe_log_filename(""))
        self.assertIsNone(ops_service.safe_log_filename(None))

    def test_safe_log_filename_rejects_symlink_escape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log_dir = root / "logs"
            outside = root / "outside"
            log_dir.mkdir()
            outside.mkdir()
            (outside / "secret.log").write_text("secret", encoding="utf-8")
            (log_dir / "escape.log").symlink_to(outside / "secret.log")
            ops_service.LOG_DIR = log_dir

            self.assertEqual(ops_service.safe_log_filename("inside.log"), "inside.log")
            self.assertIsNone(ops_service.safe_log_filename("escape.log"))

    def test_tail_file_returns_requested_tail_lines(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.log"
            path.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
            self.assertEqual(ops_service.tail_file(path, 2), "three\nfour")
            self.assertEqual(ops_service.tail_file(path, 10), "one\ntwo\nthree\nfour")

    def test_tail_file_respects_max_bytes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["OPS_LOG_TAIL_MAX_BYTES"] = "32"
            path = Path(tmpdir) / "sample.log"
            path.write_text("a" * 200, encoding="utf-8")
            content = ops_service.tail_file(path, 10)
            self.assertEqual(content, "a" * 32)

    def test_version_payload_reports_digest_capable_image_refs(self):
        os.environ.update(
            {
                "DIFY_AIO_BUILD_BASE_IMAGE_REF": "python:3.12-slim-bookworm@sha256:base",
                "DIFY_AIO_BUILD_DIFY_API_IMAGE_REF": "langgenius/dify-api@sha256:api",
                "DIFY_AIO_BUILD_DIFY_WEB_IMAGE_REF": "langgenius/dify-web@sha256:web",
                "DIFY_AIO_BUILD_PLUGIN_DAEMON_IMAGE_REF": "langgenius/dify-plugin-daemon@sha256:plugin",
                "DIFY_AIO_BUILD_SANDBOX_IMAGE_REF": "langgenius/dify-sandbox@sha256:sandbox",
            }
        )

        build = ops_service.version_payload()["build"]

        self.assertEqual(build["base_image_ref"], "python:3.12-slim-bookworm@sha256:base")
        self.assertEqual(build["dify_api_image_ref"], "langgenius/dify-api@sha256:api")
        self.assertEqual(build["dify_web_image_ref"], "langgenius/dify-web@sha256:web")
        self.assertEqual(build["plugin_daemon_image_ref"], "langgenius/dify-plugin-daemon@sha256:plugin")
        self.assertEqual(build["sandbox_image_ref"], "langgenius/dify-sandbox@sha256:sandbox")
        self.assertEqual(build["dify_api_image"], build["dify_api_image_ref"])

    def test_plugin_storage_paths_resolve_relative_cache_under_root(self):
        os.environ.update(
            {
                "PLUGIN_STORAGE_LOCAL_ROOT": "/tmp/plugin-root",
                "PLUGIN_INSTALLED_PATH": "plugin",
                "PLUGIN_PACKAGE_CACHE_PATH": "plugin_packages",
                "PLUGIN_MEDIA_CACHE_PATH": "/external/assets",
                "PLUGIN_WORKING_PATH": "/tmp/plugin-cwd",
            }
        )

        paths = ops_service.plugin_storage_paths()

        self.assertEqual(paths["installed"], Path("/tmp/plugin-root/plugin"))
        self.assertEqual(paths["package_cache"], Path("/tmp/plugin-root/plugin_packages"))
        self.assertEqual(paths["media_cache"], Path("/external/assets"))
        self.assertEqual(paths["working"], Path("/tmp/plugin-cwd"))

    def test_plugin_storage_layout_flags_bucket_symlink_root(self):
        issues = ops_service.plugin_storage_layout_issues(
            "bucket",
            {
                "plugin_storage_root": {
                    "path": "/data/plugin_daemon",
                    "exists": True,
                    "is_symlink": False,
                    "real_path": "/data/plugin_daemon",
                },
                "plugin_installed": {
                    "path": "/data/plugin_daemon/plugin",
                    "exists": True,
                    "is_symlink": True,
                    "real_path": "/persist/plugin_daemon/plugin",
                },
                "plugin_package_cache": {
                    "path": "/data/plugin_daemon/plugin_packages",
                    "exists": True,
                    "is_symlink": True,
                    "real_path": "/persist/plugin_daemon/plugin_packages",
                },
            },
        )

        self.assertEqual(
            [issue["code"] for issue in issues],
            [
                "plugin_storage_root_uses_data_symlink_view",
                "plugin_installed_is_symlink_root",
                "plugin_package_cache_is_symlink_root",
            ],
        )

    def test_plugin_storage_layout_accepts_bucket_real_persist_root(self):
        issues = ops_service.plugin_storage_layout_issues(
            "bucket",
            {
                "plugin_storage_root": {
                    "path": "/persist/plugin_daemon",
                    "exists": True,
                    "is_symlink": False,
                    "real_path": "/persist/plugin_daemon",
                },
                "plugin_installed": {
                    "path": "/persist/plugin_daemon/plugin",
                    "exists": True,
                    "is_symlink": False,
                    "real_path": "/persist/plugin_daemon/plugin",
                },
                "plugin_package_cache": {
                    "path": "/persist/plugin_daemon/plugin_packages",
                    "exists": True,
                    "is_symlink": False,
                    "real_path": "/persist/plugin_daemon/plugin_packages",
                },
            },
        )

        self.assertEqual(issues, [])

    def test_collect_plugin_identifiers_flags_missing_package_and_installed_files(self):
        identifier = "langgenius/openai_api_compatible:0.0.49@abc123"
        db_payload = {
            "plugins": {
                "ok": True,
                "rows": [
                    {
                        "plugin_id": "langgenius/openai_api_compatible",
                        "plugin_unique_identifier": identifier,
                    }
                ],
            },
            "plugin_installations": {"ok": True, "rows": []},
            "api_plugin_references": {"ok": True, "rows": []},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package_dir = root / "plugin_packages"
            installed_dir = root / "plugin"
            package_dir.mkdir()
            installed_dir.mkdir()
            missing = ops_service.collect_plugin_identifiers(db_payload, package_dir, installed_dir)
            self.assertIn(identifier, missing[0]["package_candidates"])
            self.assertFalse(missing[0]["package_exists"])
            self.assertFalse(missing[0]["installed_exists"])
            self.assertEqual(missing[0]["hashed_plugin_id"], ops_service.plugin_hashed_identity(identifier))

            (package_dir / "langgenius").mkdir()
            (package_dir / identifier).write_text("pkg", encoding="utf-8")
            present = ops_service.collect_plugin_identifiers(db_payload, package_dir, installed_dir)
            self.assertTrue(present[0]["package_exists"])
            self.assertEqual(present[0]["found_package"], identifier)
            self.assertFalse(present[0]["installed_exists"])

            (installed_dir / "langgenius").mkdir()
            (installed_dir / identifier).write_text("pkg", encoding="utf-8")
            ready = ops_service.collect_plugin_identifiers(db_payload, package_dir, installed_dir)
            self.assertTrue(ready[0]["package_exists"])
            self.assertTrue(ready[0]["installed_exists"])

    def test_collect_plugin_identifiers_deduplicates_plugin_tables(self):
        identifier = "langgenius/openai_api_compatible:0.0.49@abc123"
        db_payload = {
            "plugins": {
                "ok": True,
                "rows": [
                    {
                        "plugin_id": "langgenius/openai_api_compatible",
                        "plugin_unique_identifier": identifier,
                    }
                ],
            },
            "plugin_installations": {
                "ok": True,
                "rows": [
                    {
                        "tenant_id": "tenant-a",
                        "plugin_id": "langgenius/openai_api_compatible",
                        "plugin_unique_identifier": identifier,
                    }
                ],
            },
            "api_plugin_references": {"ok": True, "rows": []},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package_dir = root / "plugin_packages"
            installed_dir = root / "plugin"
            package_dir.mkdir()
            installed_dir.mkdir()
            (package_dir / "langgenius").mkdir()
            (installed_dir / "langgenius").mkdir()
            (package_dir / identifier).write_text("pkg", encoding="utf-8")
            (installed_dir / identifier).write_text("pkg", encoding="utf-8")

            identifiers = ops_service.collect_plugin_identifiers(db_payload, package_dir, installed_dir)

        self.assertEqual(len(identifiers), 1)
        self.assertEqual(identifiers[0]["sources"], ["plugins", "plugin_installations"])
        self.assertEqual(identifiers[0]["tenant_ids"], ["tenant-a"])
        self.assertEqual(identifiers[0]["plugin_ids"], ["langgenius/openai_api_compatible"])
        self.assertTrue(identifiers[0]["package_exists"])
        self.assertTrue(identifiers[0]["installed_exists"])

    def test_runtime_state_summary_sanitizes_redis_plugin_state(self):
        identifier = "langgenius/openai_api_compatible:0.0.49@abc123"
        hashed = ops_service.plugin_hashed_identity(identifier)
        summary = ops_service.runtime_state_summary(
            identifier,
            {
                f"node-a:{hashed}": {
                    "identity": identifier,
                    "status": "active",
                    "working_path": "/data/plugin_daemon/cwd/example",
                    "verified": True,
                    "restarts": 1,
                    "scheduled_at": "2026-05-31T10:00:00Z",
                    "logs": ["not returned"],
                },
                "node-b:other": {"identity": "other", "status": "active"},
            },
        )

        self.assertEqual(summary["state_count"], 1)
        self.assertEqual(summary["states"][0]["node_id"], "node-a")
        self.assertEqual(summary["states"][0]["status"], "active")
        self.assertNotIn("logs", summary["states"][0])

    def test_persistence_payload_flags_missing_runtime_state(self):
        identifier = "langgenius/openai_api_compatible:0.0.49@abc123"
        original_plugin_storage_paths = ops_service.plugin_storage_paths
        original_plugin_db_payload = ops_service.plugin_db_payload
        original_redis_hash_scan_candidates = ops_service.redis_hash_scan_candidates
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package_dir = root / "plugin_packages"
            installed_dir = root / "plugin"
            package_dir.mkdir()
            installed_dir.mkdir()
            (package_dir / "langgenius").mkdir()
            (installed_dir / "langgenius").mkdir()
            (package_dir / identifier).write_text("pkg", encoding="utf-8")
            (installed_dir / identifier).write_text("pkg", encoding="utf-8")

            def fake_plugin_storage_paths():
                return {
                    "storage_root": root,
                    "installed": installed_dir,
                    "package_cache": package_dir,
                    "media_cache": root / "assets",
                    "working": root / "cwd",
                }

            def fake_plugin_db_payload():
                return {
                    "plugins": {
                        "ok": True,
                        "rows": [
                            {
                                "plugin_id": "langgenius/openai_api_compatible",
                                "plugin_unique_identifier": identifier,
                            }
                        ],
                    },
                    "plugin_installations": {"ok": True, "rows": []},
                    "api_plugin_references": {"ok": True, "rows": []},
                }

            try:
                ops_service.plugin_storage_paths = fake_plugin_storage_paths
                ops_service.plugin_db_payload = fake_plugin_db_payload
                ops_service.redis_hash_scan_candidates = lambda _hash_name: {
                    "ok": True,
                    "key": "plugin_daemon:plugin_state",
                    "db": 0,
                    "prefix": "plugin_daemon",
                    "checked": [],
                    "count": 0,
                    "fields": {},
                }
                payload = ops_service.persistence_payload()
            finally:
                ops_service.plugin_storage_paths = original_plugin_storage_paths
                ops_service.plugin_db_payload = original_plugin_db_payload
                ops_service.redis_hash_scan_candidates = original_redis_hash_scan_candidates

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["missing_package_files"], [])
        self.assertEqual(payload["missing_installed_files"], [])
        self.assertEqual(payload["missing_runtime_states"][0]["plugin_unique_identifier"], identifier)

    def test_persistence_payload_fails_bucket_symlink_layout(self):
        original_plugin_storage_paths = ops_service.plugin_storage_paths
        original_plugin_db_payload = ops_service.plugin_db_payload
        original_redis_hash_scan_candidates = ops_service.redis_hash_scan_candidates
        original_path_summary = ops_service.path_summary
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            active_file = root / "persist-active"
            active_file.write_text("bucket\n", encoding="utf-8")

            def fake_plugin_storage_paths():
                return {
                    "storage_root": Path("/data/plugin_daemon"),
                    "installed": Path("/data/plugin_daemon/plugin"),
                    "package_cache": Path("/data/plugin_daemon/plugin_packages"),
                    "media_cache": Path("/data/plugin_daemon/assets"),
                    "working": Path("/data/plugin_daemon/cwd"),
                }

            def fake_plugin_db_payload():
                return {
                    "plugins": {"ok": True, "rows": []},
                    "plugin_installations": {"ok": True, "rows": []},
                    "api_plugin_references": {"ok": True, "rows": []},
                }

            def fake_path_summary(path):
                summary = {"path": str(path), "exists": True, "is_symlink": False}
                if str(path) in {"/data/plugin_daemon/plugin", "/data/plugin_daemon/plugin_packages"}:
                    summary["is_symlink"] = True
                    summary["real_path"] = str(path).replace("/data", "/persist", 1)
                return summary

            try:
                os.environ["PERSIST_ACTIVE_FILE"] = str(active_file)
                ops_service.plugin_storage_paths = fake_plugin_storage_paths
                ops_service.plugin_db_payload = fake_plugin_db_payload
                ops_service.redis_hash_scan_candidates = lambda _hash_name: {
                    "ok": True,
                    "key": "plugin_daemon:plugin_state",
                    "db": 0,
                    "prefix": "plugin_daemon",
                    "checked": [],
                    "count": 0,
                    "fields": {},
                }
                ops_service.path_summary = fake_path_summary
                payload = ops_service.persistence_payload()
            finally:
                ops_service.plugin_storage_paths = original_plugin_storage_paths
                ops_service.plugin_db_payload = original_plugin_db_payload
                ops_service.redis_hash_scan_candidates = original_redis_hash_scan_candidates
                ops_service.path_summary = original_path_summary

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["persist_active"], "bucket")
        self.assertEqual(
            [issue["code"] for issue in payload["plugin_storage_layout_issues"]],
            [
                "plugin_storage_root_uses_data_symlink_view",
                "plugin_installed_is_symlink_root",
                "plugin_package_cache_is_symlink_root",
            ],
        )

    def test_persistence_payload_accepts_local_runtime_log_evidence(self):
        identifier = "langgenius/openai_api_compatible:0.0.49@abc123"
        original_plugin_storage_paths = ops_service.plugin_storage_paths
        original_plugin_db_payload = ops_service.plugin_db_payload
        original_redis_hash_scan_candidates = ops_service.redis_hash_scan_candidates
        original_path_summary = ops_service.path_summary
        original_log_dir = ops_service.LOG_DIR
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package_dir = root / "plugin_packages"
            installed_dir = root / "plugin"
            log_dir = root / "logs"
            package_dir.mkdir()
            installed_dir.mkdir()
            log_dir.mkdir()
            (package_dir / "langgenius").mkdir()
            (installed_dir / "langgenius").mkdir()
            (package_dir / identifier).write_text("pkg", encoding="utf-8")
            (installed_dir / identifier).write_text("pkg", encoding="utf-8")
            (log_dir / "plugin-daemon.log").write_text(
                f"INFO local runtime ready plugin={identifier}\n", encoding="utf-8"
            )

            def fake_plugin_storage_paths():
                return {
                    "storage_root": root,
                    "installed": installed_dir,
                    "package_cache": package_dir,
                    "media_cache": root / "assets",
                    "working": root / "cwd",
                }

            def fake_plugin_db_payload():
                return {
                    "plugins": {
                        "ok": True,
                        "rows": [
                            {
                                "plugin_id": "langgenius/openai_api_compatible",
                                "plugin_unique_identifier": identifier,
                            }
                        ],
                    },
                    "plugin_installations": {"ok": True, "rows": []},
                    "api_plugin_references": {"ok": True, "rows": []},
                }

            try:
                ops_service.LOG_DIR = log_dir
                ops_service.plugin_storage_paths = fake_plugin_storage_paths
                ops_service.plugin_db_payload = fake_plugin_db_payload
                ops_service.redis_hash_scan_candidates = lambda _hash_name: {
                    "ok": True,
                    "key": "plugin_daemon:plugin_state",
                    "db": 0,
                    "prefix": "plugin_daemon",
                    "checked": [],
                    "count": 0,
                    "fields": {},
                }
                ops_service.path_summary = lambda path: {"path": str(path), "exists": True}
                payload = ops_service.persistence_payload()
            finally:
                ops_service.LOG_DIR = original_log_dir
                ops_service.plugin_storage_paths = original_plugin_storage_paths
                ops_service.plugin_db_payload = original_plugin_db_payload
                ops_service.redis_hash_scan_candidates = original_redis_hash_scan_candidates
                ops_service.path_summary = original_path_summary

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["missing_runtime_states"], [])
        self.assertTrue(payload["plugin_runtime_state"]["identifiers"][0]["log"]["ready"])

    def test_redis_hash_scan_uses_db_and_prefix_candidates(self):
        calls = []
        original_run_cmd = ops_service.run_cmd

        def fake_run_cmd(args, timeout=2.0, extra_env=None, output_limit=200_000):
            calls.append(args)
            key = args[args.index("HSCAN") + 1]
            db = args[args.index("-n") + 1]
            if db == "1" and key == "plugin_daemon:plugin_state":
                return {
                    "ok": True,
                    "returncode": 0,
                    "stdout": '0\nnode-a:plugin\n{"status":"active"}\n',
                    "stderr": "",
                    "duration_ms": 1,
                }
            return {"ok": True, "returncode": 0, "stdout": "0\n", "stderr": "", "duration_ms": 1}

        try:
            os.environ["REDIS_DB"] = "1"
            os.environ["REDIS_KEY_PREFIX"] = ""
            ops_service.run_cmd = fake_run_cmd
            result = ops_service.redis_hash_scan_candidates("plugin_state")
        finally:
            ops_service.run_cmd = original_run_cmd

        self.assertEqual(result["db"], 1)
        self.assertEqual(result["key"], "plugin_daemon:plugin_state")
        self.assertEqual(result["count"], 1)
        self.assertIn("-n", calls[0])

    def test_redis_check_uses_redicli_auth_env(self):
        captured = {}
        original_run_cmd = ops_service.run_cmd

        def fake_run_cmd(args, timeout=2.0, extra_env=None):
            captured["args"] = args
            captured["extra_env"] = extra_env
            return {"ok": True, "returncode": 0, "stdout": "PONG", "stderr": "", "duration_ms": 1}

        try:
            os.environ["REDIS_PASSWORD"] = "test-password"
            ops_service.run_cmd = fake_run_cmd
            result = ops_service.redis_check()
        finally:
            ops_service.run_cmd = original_run_cmd

        self.assertTrue(result["ok"])
        self.assertNotIn("-a", captured["args"])
        self.assertEqual(captured["extra_env"], {"REDISCLI_AUTH": "test-password"})

    def test_process_env_summary_returns_only_safe_values(self):
        values = ops_service.parse_environ_bytes(
            b"MAX_REQUEST_TIMEOUT=300\0OPS_TOKEN=secret-token\0PLUGIN_WORKING_PATH=/data/plugin_daemon/cwd\0"
        )

        summary = ops_service.process_env_safe_summary(values)

        self.assertEqual(summary["safe_values"]["MAX_REQUEST_TIMEOUT"], "300")
        self.assertEqual(summary["safe_values"]["PLUGIN_WORKING_PATH"], "/data/plugin_daemon/cwd")
        self.assertNotIn("OPS_TOKEN", summary["safe_values"])
        self.assertTrue(summary["secret_presence"]["OPS_TOKEN"])

    def test_child_pids_reads_proc_children_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            children_path = Path(tmpdir) / "123" / "task" / "123"
            children_path.mkdir(parents=True)
            (children_path / "children").write_text("456 789\n", encoding="utf-8")

            self.assertEqual(ops_service.child_pids(123, Path(tmpdir)), [456, 789])

    def test_plugin_runtime_process_scan_filters_and_masks_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proc_root = Path(tmpdir) / "proc"
            proc_root.mkdir()
            working_root = Path(tmpdir) / "plugin_daemon" / "cwd"
            plugin_cwd = working_root / "runtime-1"
            plugin_cwd.mkdir(parents=True)
            site_packages = plugin_cwd / ".venv" / "lib" / "python3.12" / "site-packages"
            sdk_llm = site_packages / "dify_plugin" / "interfaces" / "model" / "openai_compatible"
            sdk_llm.mkdir(parents=True)
            dist_info = site_packages / "dify_plugin-0.7.4.dist-info"
            dist_info.mkdir(parents=True)
            (dist_info / "METADATA").write_text("Name: dify-plugin\nVersion: 0.7.4\n", encoding="utf-8")
            (sdk_llm / "llm.py").write_text(
                "requests.post(endpoint_url, timeout=(10, _plugin_config.MAX_REQUEST_TIMEOUT))\n",
                encoding="utf-8",
            )
            (plugin_cwd / "main.py").write_text("Plugin(DifyPluginEnv())\n", encoding="utf-8")
            plugin_llm = plugin_cwd / "models" / "llm"
            plugin_llm.mkdir(parents=True)
            (plugin_llm / "llm.py").write_text("return super()._invoke(*args)\n", encoding="utf-8")
            (plugin_cwd / ".env").write_text("MAX_REQUEST_TIMEOUT=300\nOPS_TOKEN=secret-token\n", encoding="utf-8")

            matched = proc_root / "123"
            matched.mkdir()
            (matched / "comm").write_text("python3\n", encoding="utf-8")
            (matched / "cmdline").write_bytes(b"/usr/bin/python3\0-m\0main\0")
            (matched / "environ").write_bytes(
                (
                    f"INSTALL_METHOD=local\0"
                    f"MAX_REQUEST_TIMEOUT=300\0"
                    f"PLUGIN_WORKING_PATH={working_root}\0"
                    f"VIRTUAL_ENV={plugin_cwd / '.venv'}\0"
                    f"OPS_TOKEN=secret-token\0"
                ).encode()
            )
            (matched / "status").write_text("Name:\tpython3\nPPid:\t45\n", encoding="utf-8")
            os.symlink(plugin_cwd, matched / "cwd")

            ignored = proc_root / "456"
            ignored.mkdir()
            (ignored / "comm").write_text("python3\n", encoding="utf-8")
            (ignored / "cmdline").write_bytes(b"/usr/bin/python3\0-m\0main\0")
            (ignored / "environ").write_bytes(b"INSTALL_METHOD=local\0MAX_REQUEST_TIMEOUT=300\0")
            (ignored / "status").write_text("Name:\tpython3\nPPid:\t1\n", encoding="utf-8")
            os.symlink(Path(tmpdir) / "not-plugin", ignored / "cwd")

            os.environ["PLUGIN_WORKING_PATH"] = str(working_root)
            os.environ["PLUGIN_STORAGE_LOCAL_ROOT"] = str(Path(tmpdir) / "plugin_daemon")

            result = ops_service.plugin_runtime_process_scan(proc_root=proc_root, inspect_runtime=True)

        self.assertTrue(result["ok"])
        self.assertEqual(result["match_count"], 1)
        match = result["matches"][0]
        self.assertEqual(match["pid"], 123)
        self.assertEqual(match["ppid"], 45)
        self.assertEqual(match["safe_values"]["MAX_REQUEST_TIMEOUT"], "300")
        self.assertNotIn("OPS_TOKEN", match["safe_values"])
        self.assertTrue(match["secret_presence"]["OPS_TOKEN"])
        self.assertNotIn("cmdline", match)
        self.assertNotIn("cwd", match)
        self.assertIn("cwd_under_plugin_working_path", match["match_reasons"])
        inspection = match["runtime_inspection"]
        self.assertTrue(inspection["ok"])
        self.assertEqual(inspection["dify_plugin_versions"][0]["version"], "0.7.4")
        self.assertEqual(inspection["env_file"]["safe_values"]["MAX_REQUEST_TIMEOUT"], "300")
        self.assertNotIn("OPS_TOKEN", inspection["env_file"]["safe_values"])
        self.assertTrue(inspection["sdk_openai_compatible_llm"][0]["timeout_markers"]["uses_plugin_config_max_request_timeout"])
        self.assertFalse(inspection["sdk_openai_compatible_llm"][0]["timeout_markers"]["has_hardcoded_timeout_10_10"])

    def test_encrypted_config_summary_masks_secrets_and_summarizes_gateway_url(self):
        raw = json.dumps(
            {
                "api_key": "sk-test-secret",
                "endpoint_url": "https://gateway.ai.cloudflare.com/v1/account-id/gateway/openai/chat/completions?debug=true",
                "mode": "chat",
                "read_timeout": 10,
                "nested": {"authorization": "Bearer secret"},
            }
        )

        summary = ops_service.encrypted_config_summary(raw)

        self.assertTrue(summary["present"])
        self.assertTrue(summary["json_parse_ok"])
        config = summary["json"]
        self.assertTrue(config["secret_presence"]["api_key"])
        self.assertTrue(config["secret_presence"]["nested.authorization"])
        self.assertNotIn("sk-test-secret", json.dumps(summary))
        self.assertEqual(config["safe_values"]["mode"], "chat")
        self.assertEqual(config["safe_values"]["read_timeout"], 10)
        url = config["safe_values"]["endpoint_url"]["url"]
        self.assertEqual(url["host"], "gateway.ai.cloudflare.com")
        self.assertTrue(url["known_host"]["cloudflare_ai_gateway"])
        self.assertTrue(url["path_markers"]["contains_chat"])
        self.assertNotIn("account-id", json.dumps(summary))

    def test_provider_model_summary_payload_sanitizes_config_sections(self):
        original_psql_json_rows = ops_service.psql_json_rows
        calls = []

        def fake_psql_json_rows(database, sql, timeout=5.0):
            calls.append(sql)
            if "from provider_models" in sql:
                return {
                    "ok": True,
                    "count": 1,
                    "rows": [
                        {
                            "id": "provider-model-1",
                            "tenant_id": "tenant-1",
                            "provider_name": "langgenius/openai_api_compatible/openai_api_compatible",
                            "model_name": "gpt-test",
                            "model_type": "llm",
                            "credential_id": "cred-1",
                            "is_valid": True,
                        }
                    ],
                }
            if "from provider_model_credentials" in sql:
                return {
                    "ok": True,
                    "count": 1,
                    "rows": [
                        {
                            "id": "cred-1",
                            "tenant_id": "tenant-1",
                            "provider_name": "langgenius/openai_api_compatible/openai_api_compatible",
                            "model_name": "gpt-test",
                            "model_type": "llm",
                            "credential_name": "API_KEY1",
                            "encrypted_config": json.dumps(
                                {
                                    "api_key": "secret-key",
                                    "endpoint_url": "https://gateway.ai.cloudflare.com/v1/account/gateway/openai",
                                    "read_timeout": 10,
                                }
                            ),
                        }
                    ],
                }
            if "from app_model_configs" in sql:
                return {"ok": True, "count": 0, "rows": []}
            if "from apps a" in sql:
                return {
                    "ok": True,
                    "count": 1,
                    "rows": [
                        {
                            "app_id": "app-1",
                            "tenant_id": "tenant-1",
                            "app_name": "Smoke app",
                            "mode": "advanced-chat",
                            "status": "normal",
                            "enable_api": True,
                            "workflow_id": "workflow-1",
                            "app_config_model": json.dumps(
                                {
                                    "provider": "langgenius/openai_api_compatible/openai_api_compatible",
                                    "name": "gpt-test",
                                    "api_key": "should-not-leak",
                                }
                            ),
                        }
                    ],
                }
            if "from api_tokens" in sql:
                return {
                    "ok": True,
                    "count": 1,
                    "rows": [
                        {
                            "id": "token-1",
                            "tenant_id": "tenant-1",
                            "app_id": "app-1",
                            "type": "app",
                            "token": "app-live-secret-token",
                            "last_used_at": None,
                        }
                    ],
                }
            if "from workflows" in sql:
                return {
                    "ok": True,
                    "count": 1,
                    "rows": [
                        {
                            "workflow_id": "workflow-1",
                            "tenant_id": "tenant-1",
                            "app_id": "app-1",
                            "app_name": "Smoke app",
                            "type": "chat",
                            "kind": "standard",
                            "version": "draft",
                            "graph": json.dumps(
                                {
                                    "nodes": [
                                        {
                                            "id": "llm-node",
                                            "data": {
                                                "type": "llm",
                                                "prompt_template": "do not leak this prompt",
                                                "api_key": "workflow-secret",
                                                "model": {
                                                    "provider": "langgenius/openai_api_compatible/openai_api_compatible",
                                                    "name": "gpt-test",
                                                    "mode": "chat",
                                                    "completion_params": {"temperature": 0.2, "secret_note": "hidden"},
                                                },
                                            },
                                        }
                                    ]
                                }
                            ),
                        }
                    ],
                }
            return {"ok": True, "count": 0, "rows": []}

        try:
            ops_service.psql_json_rows = fake_psql_json_rows
            payload = ops_service.provider_model_summary_payload({"limit": ["20"], "recent_limit": ["5"]})
        finally:
            ops_service.psql_json_rows = original_psql_json_rows

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["limit"], 20)
        self.assertEqual(payload["recent_limit"], 5)
        provider_credential = payload["sections"]["provider_model_credentials"]["rows"][0]
        self.assertNotIn("encrypted_config", provider_credential)
        config = provider_credential["encrypted_config_summary"]["json"]
        self.assertTrue(config["secret_presence"]["api_key"])
        self.assertEqual(config["safe_values"]["read_timeout"], 10)
        self.assertEqual(config["safe_values"]["endpoint_url"]["url"]["host"], "gateway.ai.cloudflare.com")
        app_binding = payload["sections"]["app_model_bindings"]["rows"][0]
        self.assertNotIn("app_config_model", app_binding)
        self.assertTrue(app_binding["app_config_model_summary"]["json"]["secret_presence"]["api_key"])
        api_token = payload["sections"]["api_tokens"]["rows"][0]
        self.assertNotIn("token", api_token)
        self.assertEqual(api_token["token_summary"]["prefix"], "app-")
        self.assertEqual(api_token["token_summary"]["length"], len("app-live-secret-token"))
        workflow = payload["sections"]["workflow_model_bindings"]["rows"][0]
        self.assertNotIn("graph", workflow)
        graph_summary = workflow["graph_summary"]
        self.assertEqual(graph_summary["model_binding_count"], 1)
        self.assertEqual(graph_summary["model_bindings"][0]["model"]["name"], "gpt-test")
        self.assertEqual(
            graph_summary["model_bindings"][0]["model"]["provider"],
            "langgenius/openai_api_compatible/openai_api_compatible",
        )
        readiness = payload["sections"]["app_api_readiness"]["rows"][0]
        self.assertEqual(readiness["app_id"], "app-1")
        self.assertEqual(readiness["api_token_count"], 1)
        self.assertTrue(readiness["ready_for_service_api_auth"])
        self.assertTrue(readiness["ready_for_llm_dispatch"])
        self.assertEqual(readiness["issue_codes"], [])
        self.assertEqual(readiness["model_bindings"][0]["name"], "gpt-test")
        self.assertNotIn("secret-key", json.dumps(payload))
        self.assertNotIn("should-not-leak", json.dumps(payload))
        self.assertNotIn("app-live-secret-token", json.dumps(payload))
        self.assertNotIn("workflow-secret", json.dumps(payload))
        self.assertNotIn("do not leak this prompt", json.dumps(payload))
        self.assertTrue(any("provider_model_credentials" in sql for sql in calls))

    def test_app_api_readiness_flags_enabled_app_without_token(self):
        sections = {
            "app_model_bindings": {
                "ok": True,
                "rows": [
                    {
                        "app_id": "app-1",
                        "tenant_id": "tenant-1",
                        "app_name": "Smoke app",
                        "mode": "advanced-chat",
                        "status": "normal",
                        "enable_api": True,
                        "workflow_id": "workflow-1",
                    }
                ],
            },
            "api_tokens": {"ok": True, "rows": []},
            "workflow_model_bindings": {
                "ok": True,
                "rows": [
                    {
                        "workflow_id": "workflow-1",
                        "app_id": "app-1",
                        "graph_summary": {
                            "model_bindings": [
                                {
                                    "node_id": "llm-node",
                                    "node_type": "llm",
                                    "model": {
                                        "provider": "langgenius/openai_api_compatible/openai_api_compatible",
                                        "name": "gpt-test",
                                        "mode": "chat",
                                    },
                                }
                            ]
                        },
                    }
                ],
            },
            "provider_models": {
                "ok": True,
                "rows": [
                    {
                        "provider_name": "langgenius/openai_api_compatible/openai_api_compatible",
                        "model_name": "gpt-test",
                        "is_valid": True,
                    }
                ],
            },
            "recent_conversation_model_bindings": {"ok": True, "rows": []},
        }

        payload = ops_service.app_api_readiness_section(sections)

        self.assertTrue(payload["ok"])
        row = payload["rows"][0]
        self.assertEqual(row["api_token_count"], 0)
        self.assertFalse(row["ready_for_service_api_auth"])
        self.assertTrue(row["ready_for_llm_dispatch"])
        self.assertEqual(row["issue_codes"], ["app_api_token_missing"])

    def test_cached_payload_builds_once_under_concurrency(self):
        os.environ["OPS_CACHE_TTL_SECONDS"] = "60"
        calls = 0
        calls_lock = threading.Lock()

        def builder():
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.05)
            return {"ok": True}

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: ops_service.cached_payload("concurrent", builder), range(8)))

        self.assertEqual(results, [{"ok": True}] * 8)
        self.assertEqual(calls, 1)

    def test_query_token_redirect_sets_cookie_and_cookie_auth_works(self):
        os.environ["OPS_TOKEN"] = "ops-test-token"
        os.environ["ALLOW_DEMO_OPS_TOKEN"] = "false"
        server = ThreadingHTTPServer(("127.0.0.1", 0), ops_service.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        host, port = server.server_address

        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/?token=ops-test-token")
        response = conn.getresponse()
        response.read()
        cookie = response.getheader("Set-Cookie")
        self.assertEqual(response.status, 303)
        self.assertEqual(response.getheader("Location"), "/_ops/")
        self.assertEqual(response.getheader("Referrer-Policy"), "no-referrer")
        self.assertIn("dify_ops_session=", cookie)
        conn.close()

        session_cookie = cookie.split(";", 1)[0]
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/version", headers={"Cookie": session_cookie})
        response = conn.getresponse()
        body = response.read().decode("utf-8")
        conn.close()
        self.assertEqual(response.status, 200)
        self.assertIn("dify-all-in-one-ops", body)

    def test_matched_error_pattern_ignores_known_startup_noise(self):
        self.assertIsNone(ops_service.matched_error_pattern("FATAL:  the database system is starting up"))
        self.assertEqual(ops_service.matched_error_pattern("worker Traceback happened"), "Traceback")
        self.assertEqual(ops_service.matched_error_pattern("nginx [error] connect() failed"), "connect() failed")

    def test_ops_lock_reason_requires_explicit_demo_token_escape_hatch(self):
        original_token = ops_service.os.environ.get("OPS_TOKEN")
        original_allow = ops_service.os.environ.get("ALLOW_DEMO_OPS_TOKEN")
        try:
            ops_service.os.environ["OPS_TOKEN"] = "dify_ops_demo_token"
            ops_service.os.environ.pop("ALLOW_DEMO_OPS_TOKEN", None)
            self.assertIn("default OPS_TOKEN", ops_service.ops_lock_reason())
            ops_service.os.environ["ALLOW_DEMO_OPS_TOKEN"] = "true"
            self.assertEqual(ops_service.ops_lock_reason(), "")
        finally:
            if original_token is None:
                ops_service.os.environ.pop("OPS_TOKEN", None)
            else:
                ops_service.os.environ["OPS_TOKEN"] = original_token
            if original_allow is None:
                ops_service.os.environ.pop("ALLOW_DEMO_OPS_TOKEN", None)
            else:
                ops_service.os.environ["ALLOW_DEMO_OPS_TOKEN"] = original_allow


if __name__ == "__main__":
    unittest.main()
