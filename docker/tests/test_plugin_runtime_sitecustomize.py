import builtins
import importlib.util
import os
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import requests.sessions


ROOT = Path(__file__).resolve().parents[2]
SHIM_PATH = ROOT / "docker" / "plugin_runtime_patches" / "sitecustomize.py"


def load_shim(name: str):
    spec = importlib.util.spec_from_file_location(name, SHIM_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def sdk_call(function_body: str, function_name: str = "_generate"):
    module_name = "dify_plugin.interfaces.model.openai_compatible.llm"
    module = types.ModuleType(module_name)
    module.__dict__["requests"] = __import__("requests")
    exec(f"def {function_name}():\n{function_body}", module.__dict__)
    return module.__dict__[function_name]()


class PluginRuntimeSiteCustomizeTests(unittest.TestCase):
    def setUp(self):
        self.original_env = os.environ.copy()
        self.original_request = requests.sessions.Session.request
        os.environ["PLUGIN_CONNECT_TIMEOUT_SECONDS"] = "60"
        os.environ["MAX_REQUEST_TIMEOUT"] = "300"

    def tearDown(self):
        requests.sessions.Session.request = self.original_request
        sys.meta_path[:] = [
            finder
            for finder in sys.meta_path
            if not getattr(finder, "__dify_plugin_connect_timeout_import_hook__", False)
        ]
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_rewrites_only_the_sdk_request_timeout_tuple(self):
        shim = load_shim("plugin_runtime_sitecustomize_pure_test")

        self.assertEqual(shim.rewrite_timeout((10, 300)), (60, 300))
        self.assertEqual(shim.rewrite_timeout([10, 300]), [10, 300])
        self.assertEqual(shim.rewrite_timeout((10, 10)), (10, 10))
        self.assertEqual(shim.rewrite_timeout((15, 300)), (15, 300))
        self.assertEqual(shim.rewrite_timeout(10), 10)

    def test_session_wrapper_rewrites_keyword_timeout(self):
        calls = []

        def fake_request(_self, method, url, *args, **kwargs):
            calls.append((method, url, args, kwargs))
            return "ok"

        requests.sessions.Session.request = fake_request
        shim = load_shim("plugin_runtime_sitecustomize_keyword_test")
        self.assertTrue(shim.install_requests_timeout_shim())

        result = sdk_call(
            "    return requests.post(\n"
            "        'https://gateway.ai.cloudflare.com/v1/example',\n"
            "        timeout=(10, 300),\n"
            "    )"
        )

        self.assertEqual(result, "ok")
        self.assertEqual(calls[0][3]["timeout"], (60, 300))

    def test_session_wrapper_rewrites_positional_timeout(self):
        calls = []

        def fake_request(_self, method, url, *args, **kwargs):
            calls.append((method, url, args, kwargs))
            return "ok"

        requests.sessions.Session.request = fake_request
        shim = load_shim("plugin_runtime_sitecustomize_positional_test")
        self.assertTrue(shim.install_requests_timeout_shim())

        sdk_call(
            "    return requests.sessions.Session().request(\n"
            "        'POST',\n"
            "        'https://gateway.ai.cloudflare.com/v1/example',\n"
            "        None, None, None, None, None, None, (10, 300),\n"
            "    )"
        )

        self.assertEqual(calls[0][2][6], (60, 300))

    def test_same_validation_tuple_in_sdk_module_is_unchanged(self):
        calls = []

        def fake_request(_self, method, url, *args, **kwargs):
            calls.append((method, url, args, kwargs))
            return "ok"

        requests.sessions.Session.request = fake_request
        shim = load_shim("plugin_runtime_sitecustomize_validation_test")
        self.assertTrue(shim.install_requests_timeout_shim())

        result = sdk_call(
            "    return requests.post(\n"
            "        'https://gateway.ai.cloudflare.com/v1/example',\n"
            "        timeout=(10, 300),\n"
            "    )",
            function_name="validate_credentials",
        )

        self.assertEqual(result, "ok")
        self.assertEqual(calls[0][3]["timeout"], (10, 300))

    def test_invalid_or_overlarge_configuration_disables_rewrite(self):
        os.environ["PLUGIN_CONNECT_TIMEOUT_SECONDS"] = "invalid"
        shim = load_shim("plugin_runtime_sitecustomize_invalid_test")
        self.assertEqual(shim.rewrite_timeout((10, 300)), (10, 300))

        os.environ["PLUGIN_CONNECT_TIMEOUT_SECONDS"] = "301"
        self.assertEqual(shim.rewrite_timeout((10, 300)), (10, 300))

        os.environ["PLUGIN_CONNECT_TIMEOUT_SECONDS"] = "60"
        os.environ["MAX_REQUEST_TIMEOUT"] = "30"
        self.assertEqual(shim.rewrite_timeout((10, 30)), (10, 30))

    def test_missing_requests_dependency_fails_open(self):
        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name == "requests.sessions":
                raise ImportError("requests unavailable")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=guarded_import):
            shim = load_shim("plugin_runtime_sitecustomize_missing_requests_test")
            self.assertFalse(shim.install_requests_timeout_shim())

        self.assertIs(requests.sessions.Session.request, self.original_request)

    def test_requests_import_is_deferred_until_sdk_module_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_root = Path(tmp)
            target = package_root / "dify_plugin" / "interfaces" / "model" / "openai_compatible"
            target.mkdir(parents=True)
            for package in (
                package_root / "dify_plugin",
                package_root / "dify_plugin" / "interfaces",
                package_root / "dify_plugin" / "interfaces" / "model",
                target,
            ):
                (package / "__init__.py").write_text("", encoding="utf-8")
            (target / "llm.py").write_text("import requests\n", encoding="utf-8")

            code = textwrap.dedent(
                f"""
                import importlib
                import importlib.util
                import sys

                assert "requests" not in sys.modules
                spec = importlib.util.spec_from_file_location("deferred_sitecustomize", {str(SHIM_PATH)!r})
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)
                assert "requests" not in sys.modules
                sys.path.insert(0, {str(package_root)!r})
                importlib.import_module("dify_plugin.interfaces.model.openai_compatible.llm")
                import requests.sessions
                assert getattr(
                    requests.sessions.Session.request,
                    "__dify_plugin_connect_timeout_shim__",
                    False,
                )
                """
            )
            result = subprocess.run(
                [sys.executable, "-c", code],
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
