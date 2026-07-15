"""Bound Dify's OpenAI-compatible plugin SDK request failure surface.

The SDK currently sends model requests with ``timeout=(10, MAX_REQUEST_TIMEOUT)``.
During DNS/TCP/TLS setup, Requests reports the first value as a ``ReadTimeout``;
raising only the provider credential's read timeout therefore cannot fix a slow
connection setup.  This image-controlled shim changes only that exact tuple and
leaves scalar timeouts, validation calls, and unrelated request shapes alone.

An opt-in retry handles one narrowly identified TLS EOF before Requests returns
a response.  It is disabled by default because retrying a model POST can cause
duplicate inference or billing when the upstream received the first request.
"""

from __future__ import annotations

import functools
import importlib.abc
import importlib.machinery
import os
import sys
import time
from typing import Any


DEFAULT_SDK_CONNECT_TIMEOUT_SECONDS = 10
MAX_CONFIGURED_CONNECT_TIMEOUT_SECONDS = 300
DEFAULT_SSL_EOF_MAX_RETRIES = 0
MAX_SSL_EOF_MAX_RETRIES = 1
SSL_EOF_RETRY_BACKOFF_SECONDS = 0.25
SDK_OPENAI_COMPATIBLE_MODULE = "dify_plugin.interfaces.model.openai_compatible.llm"
SDK_OPENAI_COMPATIBLE_GENERATE_FUNCTION = "_generate"
_SHIM_MARKER = "__dify_plugin_connect_timeout_shim__"
_IMPORT_HOOK_MARKER = "__dify_plugin_connect_timeout_import_hook__"


def configured_connect_timeout() -> int | None:
    raw = os.environ.get("PLUGIN_CONNECT_TIMEOUT_SECONDS", "").strip()
    try:
        value = int(raw)
    except ValueError:
        return None
    if not DEFAULT_SDK_CONNECT_TIMEOUT_SECONDS <= value <= MAX_CONFIGURED_CONNECT_TIMEOUT_SECONDS:
        return None
    return value


def configured_read_timeout() -> int | None:
    raw = os.environ.get("MAX_REQUEST_TIMEOUT", "").strip()
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def configured_ssl_eof_max_retries() -> int:
    raw = os.environ.get("PLUGIN_SSL_EOF_MAX_RETRIES", str(DEFAULT_SSL_EOF_MAX_RETRIES)).strip()
    if raw not in {str(DEFAULT_SSL_EOF_MAX_RETRIES), str(MAX_SSL_EOF_MAX_RETRIES)}:
        return DEFAULT_SSL_EOF_MAX_RETRIES
    return int(raw)


def rewrite_timeout(timeout: Any) -> Any:
    connect_timeout = configured_connect_timeout()
    read_timeout = configured_read_timeout()
    if connect_timeout is None or read_timeout is None or connect_timeout <= DEFAULT_SDK_CONNECT_TIMEOUT_SECONDS:
        return timeout
    if not isinstance(timeout, tuple) or len(timeout) != 2:
        return timeout
    if timeout[0] != DEFAULT_SDK_CONNECT_TIMEOUT_SECONDS or timeout[1] != read_timeout:
        return timeout
    if connect_timeout > read_timeout:
        return timeout
    return (connect_timeout, read_timeout)


def wrapped_exceptions(error: BaseException):
    pending = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current

        for attribute in ("__cause__", "__context__", "reason"):
            nested = getattr(current, attribute, None)
            if isinstance(nested, BaseException):
                pending.append(nested)
        pending.extend(item for item in current.args if isinstance(item, BaseException))


def is_ssl_eof_error(error: BaseException) -> bool:
    # Import ssl only after the SDK module completed its gevent bootstrap.
    import ssl

    for current in wrapped_exceptions(error):
        if current is error:
            continue
        if isinstance(current, ssl.SSLEOFError):
            return True
        if "UNEXPECTED_EOF_WHILE_READING" in str(current).upper():
            return True
    return False


def is_sdk_openai_compatible_generate_request() -> bool:
    """Return whether Requests was called by the exact SDK generation method."""

    try:
        frame = sys._getframe(1)
    except (AttributeError, ValueError):
        return False

    try:
        while frame is not None:
            if (
                frame.f_globals.get("__name__") == SDK_OPENAI_COMPATIBLE_MODULE
                and frame.f_code.co_name == SDK_OPENAI_COMPATIBLE_GENERATE_FUNCTION
            ):
                return True
            frame = frame.f_back
        return False
    finally:
        del frame


def install_requests_timeout_shim() -> bool:
    try:
        import requests.sessions
    except ImportError:
        return False

    current = requests.sessions.Session.request
    if getattr(current, _SHIM_MARKER, False):
        return False

    @functools.wraps(current)
    def request_with_bounded_connect_timeout(
        self: Any,
        method: str,
        url: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        positional = list(args)
        is_target_request = is_sdk_openai_compatible_generate_request()
        if is_target_request:
            if len(positional) > 6:
                positional[6] = rewrite_timeout(positional[6])
            elif "timeout" in kwargs:
                kwargs["timeout"] = rewrite_timeout(kwargs["timeout"])

        max_retries = configured_ssl_eof_max_retries() if is_target_request else 0
        retries = 0
        while True:
            try:
                return current(self, method, url, *positional, **kwargs)
            except requests.exceptions.SSLError as error:
                if retries >= max_retries or not is_ssl_eof_error(error):
                    raise
                retries += 1
                time.sleep(SSL_EOF_RETRY_BACKOFF_SECONDS)

    setattr(request_with_bounded_connect_timeout, _SHIM_MARKER, True)
    requests.sessions.Session.request = request_with_bounded_connect_timeout
    return True


def remove_sdk_import_hook() -> None:
    sys.meta_path[:] = [
        finder
        for finder in sys.meta_path
        if not getattr(finder, _IMPORT_HOOK_MARKER, False)
    ]


class _SdkModuleLoader(importlib.abc.Loader):
    def __init__(self, delegate: importlib.abc.Loader) -> None:
        self.delegate = delegate

    def create_module(self, spec: Any) -> Any:
        create_module = getattr(self.delegate, "create_module", None)
        return create_module(spec) if create_module is not None else None

    def exec_module(self, module: Any) -> None:
        try:
            self.delegate.exec_module(module)
            install_requests_timeout_shim()
        finally:
            remove_sdk_import_hook()


class _SdkModuleFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: Any, target: Any = None) -> Any:
        del target
        if fullname != SDK_OPENAI_COMPATIBLE_MODULE:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return spec
        spec.loader = _SdkModuleLoader(spec.loader)
        return spec


def install_sdk_import_hook() -> bool:
    # Dify imports gevent and calls monkey.patch_all() from dify_plugin.__init__.
    # Importing Requests here would load ssl too early and can trigger recursive
    # late monkey-patching. Defer the Requests patch until the exact SDK module
    # has completed its normal import after the gevent bootstrap.
    if SDK_OPENAI_COMPATIBLE_MODULE in sys.modules:
        return install_requests_timeout_shim()
    if any(getattr(finder, _IMPORT_HOOK_MARKER, False) for finder in sys.meta_path):
        return False
    finder = _SdkModuleFinder()
    setattr(finder, _IMPORT_HOOK_MARKER, True)
    sys.meta_path.insert(0, finder)
    return True


install_sdk_import_hook()
