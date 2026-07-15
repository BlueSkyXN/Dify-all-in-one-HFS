import builtins
import importlib.util
import os
import ssl
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
WITH_PLUGIN_ENV_PATH = ROOT / "docker" / "with-plugin-env"


def load_shim(name: str):
    spec = importlib.util.spec_from_file_location(name, SHIM_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def sdk_call(
    function_body: str,
    function_name: str = "_generate",
    module_name: str = "dify_plugin.interfaces.model.openai_compatible.llm",
):
    module = types.ModuleType(module_name)
    module.__dict__["requests"] = __import__("requests")
    exec(f"def {function_name}():\n{function_body}", module.__dict__)
    return module.__dict__[function_name]()


def ssl_eof_request_error() -> requests.exceptions.SSLError:
    error = requests.exceptions.SSLError("TLS request failed")
    error.__cause__ = ssl.SSLEOFError(
        8,
        "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol",
    )
    return error


def ssl_eof_marker_request_error() -> requests.exceptions.SSLError:
    error = requests.exceptions.SSLError("TLS request failed")
    error.__context__ = OSError("UNEXPECTED_EOF_WHILE_READING")
    return error


def run_with_plugin_env(retry_value: str | None):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        wrapper = root / "with-plugin-env"
        generated_env = root / "generated.env"
        legacy_generated_env = root / "legacy-generated.env"
        wrapper_text = WITH_PLUGIN_ENV_PATH.read_text(encoding="utf-8")
        wrapper_text = wrapper_text.replace(
            "/etc/dify/dify.env.runtime",
            str(ROOT / "docker" / "dify.env.runtime"),
        )
        wrapper_text = wrapper_text.replace("/data/config/generated.env", str(generated_env))
        wrapper_text = wrapper_text.replace("/etc/dify/generated.env", str(legacy_generated_env))
        wrapper.write_text(wrapper_text, encoding="utf-8")

        env = os.environ.copy()
        if retry_value is None:
            env.pop("PLUGIN_SSL_EOF_MAX_RETRIES", None)
        else:
            env["PLUGIN_SSL_EOF_MAX_RETRIES"] = retry_value
        return subprocess.run(
            ["bash", str(wrapper), "bash", "-c", 'printf "%s" "$PLUGIN_SSL_EOF_MAX_RETRIES"'],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )


class PluginRuntimeSiteCustomizeTests(unittest.TestCase):
    def setUp(self):
        self.original_env = os.environ.copy()
        self.original_request = requests.sessions.Session.request
        os.environ["PLUGIN_CONNECT_TIMEOUT_SECONDS"] = "60"
        os.environ["MAX_REQUEST_TIMEOUT"] = "300"
        os.environ["PLUGIN_SSL_EOF_MAX_RETRIES"] = "0"

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

    def test_ssl_eof_retry_succeeds_once_and_preserves_timeout(self):
        calls = []
        os.environ["PLUGIN_SSL_EOF_MAX_RETRIES"] = "1"

        def fake_request(_self, method, url, *args, **kwargs):
            calls.append((method, url, args, kwargs))
            if len(calls) == 1:
                raise ssl_eof_request_error()
            return "ok"

        requests.sessions.Session.request = fake_request
        shim = load_shim("plugin_runtime_sitecustomize_ssl_eof_success_test")
        self.assertTrue(shim.install_requests_timeout_shim())

        with patch.object(shim.time, "sleep") as sleep:
            result = sdk_call(
                "    return requests.post(\n"
                "        'https://gateway.ai.cloudflare.com/v1/example',\n"
                "        timeout=(10, 300),\n"
                "    )"
            )

        self.assertEqual(result, "ok")
        self.assertEqual(len(calls), 2)
        self.assertEqual([call[3]["timeout"] for call in calls], [(60, 300), (60, 300)])
        sleep.assert_called_once_with(shim.SSL_EOF_RETRY_BACKOFF_SECONDS)

    def test_second_ssl_eof_error_is_raised_unchanged(self):
        calls = []
        errors = [ssl_eof_request_error(), ssl_eof_request_error()]
        os.environ["PLUGIN_SSL_EOF_MAX_RETRIES"] = "1"

        def fake_request(_self, method, url, *args, **kwargs):
            del _self, method, url, args, kwargs
            error = errors[len(calls)]
            calls.append(error)
            raise error

        requests.sessions.Session.request = fake_request
        shim = load_shim("plugin_runtime_sitecustomize_ssl_eof_failure_test")
        self.assertTrue(shim.install_requests_timeout_shim())

        with patch.object(shim.time, "sleep") as sleep:
            with self.assertRaises(requests.exceptions.SSLError) as caught:
                sdk_call(
                    "    return requests.post(\n"
                    "        'https://gateway.ai.cloudflare.com/v1/example',\n"
                    "        timeout=(10, 300),\n"
                    "    )"
                )

        self.assertIs(caught.exception, errors[1])
        self.assertEqual(len(calls), 2)
        sleep.assert_called_once_with(shim.SSL_EOF_RETRY_BACKOFF_SECONDS)

    def test_ssl_eof_marker_in_exception_context_retries_once(self):
        calls = []
        os.environ["PLUGIN_SSL_EOF_MAX_RETRIES"] = "1"

        def fake_request(_self, method, url, *args, **kwargs):
            del _self, method, url, args, kwargs
            calls.append(True)
            if len(calls) == 1:
                raise ssl_eof_marker_request_error()
            return "ok"

        requests.sessions.Session.request = fake_request
        shim = load_shim("plugin_runtime_sitecustomize_ssl_eof_marker_test")
        self.assertTrue(shim.install_requests_timeout_shim())

        with patch.object(shim.time, "sleep"):
            result = sdk_call(
                "    return requests.post(\n"
                "        'https://gateway.ai.cloudflare.com/v1/example',\n"
                "        timeout=(10, 300),\n"
                "    )"
            )

        self.assertEqual(result, "ok")
        self.assertEqual(len(calls), 2)

    def test_suppressed_ssl_eof_context_is_not_traversed(self):
        error = requests.exceptions.SSLError("TLS request failed")
        error.__context__ = ssl.SSLEOFError(8, "UNEXPECTED_EOF_WHILE_READING")
        error.__suppress_context__ = True
        shim = load_shim("plugin_runtime_sitecustomize_suppressed_context_test")

        self.assertFalse(shim.is_ssl_eof_error(error))

    def test_explicit_cause_takes_precedence_over_old_ssl_eof_context(self):
        error = requests.exceptions.SSLError("TLS request failed")
        error.__cause__ = OSError("certificate verify failed")
        error.__context__ = ssl.SSLEOFError(8, "UNEXPECTED_EOF_WHILE_READING")
        error.__suppress_context__ = False
        shim = load_shim("plugin_runtime_sitecustomize_explicit_cause_test")

        self.assertFalse(shim.is_ssl_eof_error(error))

    def test_non_eof_ssl_error_is_not_retried(self):
        calls = []
        os.environ["PLUGIN_SSL_EOF_MAX_RETRIES"] = "1"

        def fake_request(_self, method, url, *args, **kwargs):
            del _self, method, url, args, kwargs
            calls.append(True)
            raise requests.exceptions.SSLError("certificate verify failed")

        requests.sessions.Session.request = fake_request
        shim = load_shim("plugin_runtime_sitecustomize_non_eof_ssl_test")
        self.assertTrue(shim.install_requests_timeout_shim())

        with patch.object(shim.time, "sleep") as sleep:
            with self.assertRaises(requests.exceptions.SSLError):
                sdk_call(
                    "    return requests.post(\n"
                    "        'https://gateway.ai.cloudflare.com/v1/example',\n"
                    "        timeout=(10, 300),\n"
                    "    )"
                )

        self.assertEqual(len(calls), 1)
        sleep.assert_not_called()

    def test_ssl_eof_text_without_nested_cause_is_not_retried(self):
        calls = []
        os.environ["PLUGIN_SSL_EOF_MAX_RETRIES"] = "1"

        def fake_request(_self, method, url, *args, **kwargs):
            del _self, method, url, args, kwargs
            calls.append(True)
            raise requests.exceptions.SSLError("UNEXPECTED_EOF_WHILE_READING")

        requests.sessions.Session.request = fake_request
        shim = load_shim("plugin_runtime_sitecustomize_top_level_eof_text_test")
        self.assertTrue(shim.install_requests_timeout_shim())

        with patch.object(shim.time, "sleep") as sleep:
            with self.assertRaises(requests.exceptions.SSLError):
                sdk_call(
                    "    return requests.post(\n"
                    "        'https://gateway.ai.cloudflare.com/v1/example',\n"
                    "        timeout=(10, 300),\n"
                    "    )"
                )

        self.assertEqual(len(calls), 1)
        sleep.assert_not_called()

    def test_validation_call_does_not_retry_ssl_eof(self):
        calls = []
        os.environ["PLUGIN_SSL_EOF_MAX_RETRIES"] = "1"

        def fake_request(_self, method, url, *args, **kwargs):
            del _self, method, url, args, kwargs
            calls.append(True)
            raise ssl_eof_request_error()

        requests.sessions.Session.request = fake_request
        shim = load_shim("plugin_runtime_sitecustomize_non_target_test")
        self.assertTrue(shim.install_requests_timeout_shim())

        with patch.object(shim.time, "sleep") as sleep:
            with self.assertRaises(requests.exceptions.SSLError):
                sdk_call(
                    "    return requests.post(\n"
                    "        'https://gateway.ai.cloudflare.com/v1/example',\n"
                    "        timeout=(10, 300),\n"
                    "    )",
                    function_name="validate_credentials",
                )

        self.assertEqual(len(calls), 1)
        sleep.assert_not_called()

    def test_non_target_sdk_module_does_not_retry_ssl_eof(self):
        calls = []
        os.environ["PLUGIN_SSL_EOF_MAX_RETRIES"] = "1"

        def fake_request(_self, method, url, *args, **kwargs):
            del _self, method, url, args, kwargs
            calls.append(True)
            raise ssl_eof_request_error()

        requests.sessions.Session.request = fake_request
        shim = load_shim("plugin_runtime_sitecustomize_non_target_module_test")
        self.assertTrue(shim.install_requests_timeout_shim())

        with patch.object(shim.time, "sleep") as sleep:
            with self.assertRaises(requests.exceptions.SSLError):
                sdk_call(
                    "    return requests.post(\n"
                    "        'https://gateway.ai.cloudflare.com/v1/example',\n"
                    "        timeout=(10, 300),\n"
                    "    )",
                    module_name="example.unrelated_provider.llm",
                )

        self.assertEqual(len(calls), 1)
        sleep.assert_not_called()

    def test_http_status_timeouts_and_connection_errors_are_not_retried(self):
        os.environ["PLUGIN_SSL_EOF_MAX_RETRIES"] = "1"

        status_calls = []

        def status_request(_self, method, url, *args, **kwargs):
            del _self, method, url, args, kwargs
            status_calls.append(True)
            return types.SimpleNamespace(status_code=503)

        requests.sessions.Session.request = status_request
        status_shim = load_shim("plugin_runtime_sitecustomize_http_status_test")
        self.assertTrue(status_shim.install_requests_timeout_shim())
        response = sdk_call(
            "    return requests.post(\n"
            "        'https://gateway.ai.cloudflare.com/v1/example',\n"
            "        timeout=(10, 300),\n"
            "    )"
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(len(status_calls), 1)

        for index, error in enumerate(
            [
                requests.exceptions.ConnectTimeout("connect timeout"),
                requests.exceptions.ReadTimeout("read timeout"),
                requests.exceptions.ConnectionError("connection reset"),
            ]
        ):
            with self.subTest(error=type(error).__name__):
                calls = []

                def failing_request(_self, method, url, *args, **kwargs):
                    del _self, method, url, args, kwargs
                    calls.append(True)
                    raise error

                requests.sessions.Session.request = failing_request
                shim = load_shim(f"plugin_runtime_sitecustomize_non_ssl_error_{index}_test")
                self.assertTrue(shim.install_requests_timeout_shim())
                with patch.object(shim.time, "sleep") as sleep:
                    with self.assertRaises(type(error)):
                        sdk_call(
                            "    return requests.post(\n"
                            "        'https://gateway.ai.cloudflare.com/v1/example',\n"
                            "        timeout=(10, 300),\n"
                            "    )"
                        )
                self.assertEqual(len(calls), 1)
                sleep.assert_not_called()

    def test_invalid_ssl_eof_retry_configuration_fails_closed(self):
        os.environ.pop("PLUGIN_SSL_EOF_MAX_RETRIES", None)
        default_shim = load_shim("plugin_runtime_sitecustomize_default_retry_test")
        self.assertEqual(default_shim.configured_ssl_eof_max_retries(), 0)

        for index, raw in enumerate(["", "invalid", "-1", "2", "01.0"]):
            with self.subTest(raw=raw):
                os.environ["PLUGIN_SSL_EOF_MAX_RETRIES"] = raw
                shim = load_shim(f"plugin_runtime_sitecustomize_invalid_retry_{index}_test")
                self.assertEqual(shim.configured_ssl_eof_max_retries(), 0)

        calls = []
        os.environ["PLUGIN_SSL_EOF_MAX_RETRIES"] = "2"

        def fake_request(_self, method, url, *args, **kwargs):
            del _self, method, url, args, kwargs
            calls.append(True)
            raise ssl_eof_request_error()

        requests.sessions.Session.request = fake_request
        shim = load_shim("plugin_runtime_sitecustomize_invalid_retry_behavior_test")
        self.assertTrue(shim.install_requests_timeout_shim())
        with self.assertRaises(requests.exceptions.SSLError):
            sdk_call(
                "    return requests.post(\n"
                "        'https://gateway.ai.cloudflare.com/v1/example',\n"
                "        timeout=(10, 300),\n"
                "    )"
            )
        self.assertEqual(len(calls), 1)

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

    def test_with_plugin_env_normalizes_ssl_eof_retry_configuration(self):
        for raw, expected, warning in [
            (None, "0", False),
            ("0", "0", False),
            ("1", "1", False),
            ("2", "0", True),
            ("invalid", "0", True),
        ]:
            with self.subTest(raw=raw):
                result = run_with_plugin_env(raw)
                self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
                self.assertEqual(result.stdout, expected)
                self.assertEqual("disabling SSL EOF retry" in result.stderr, warning)

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
                assert "ssl" not in sys.modules
                spec = importlib.util.spec_from_file_location("deferred_sitecustomize", {str(SHIM_PATH)!r})
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)
                assert "requests" not in sys.modules
                assert "ssl" not in sys.modules
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
