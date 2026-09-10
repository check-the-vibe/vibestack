"""Unit tests for the websockify reverse-proxy marker plugin."""

from __future__ import annotations

from email.message import Message
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_PATH = ROOT / "proxy" / "websockify_auth.py"
EXPECTED = "vibestack-nginx-proxy-v1"


class StubAuthenticationError(Exception):
    def __init__(
        self,
        log_msg=None,
        response_code=403,
        response_headers=None,
        response_msg=None,
    ):
        super().__init__(log_msg)
        self.code = response_code
        self.headers = response_headers or {}
        self.msg = response_msg


def load_plugin():
    package = types.ModuleType("websockify")
    auth_plugins = types.ModuleType("websockify.auth_plugins")
    auth_plugins.AuthenticationError = StubAuthenticationError
    package.auth_plugins = auth_plugins
    spec = importlib.util.spec_from_file_location("tested_websockify_auth", PLUGIN_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load websockify auth plugin")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        sys.modules,
        {"websockify": package, "websockify.auth_plugins": auth_plugins},
    ):
        spec.loader.exec_module(module)
    return module


class ProxyOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_plugin()
        cls.plugin = cls.module.ProxyOnly(EXPECTED)

    @staticmethod
    def headers(*values: str) -> Message:
        result = Message()
        for value in values:
            result["X-VibeStack-Proxy"] = value
        return result

    def assert_forbidden(self, headers: Message) -> None:
        with self.assertRaises(StubAuthenticationError) as raised:
            self.plugin.authenticate(headers, "127.0.0.1", 5900)
        self.assertEqual(403, raised.exception.code)
        self.assertEqual("Forbidden", raised.exception.msg)

    def test_missing_header_is_rejected(self) -> None:
        self.assert_forbidden(self.headers())

    def test_wrong_header_is_rejected(self) -> None:
        self.assert_forbidden(self.headers("wrong"))

    def test_duplicate_headers_are_rejected_even_if_both_match(self) -> None:
        self.assert_forbidden(self.headers(EXPECTED, EXPECTED))

    def test_one_exact_case_insensitive_header_name_is_accepted(self) -> None:
        headers = Message()
        headers["x-vibestack-proxy"] = EXPECTED
        self.assertIsNone(self.plugin.authenticate(headers, "127.0.0.1", 5900))

    def test_auth_source_is_required(self) -> None:
        for value in (None, ""):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.module.ProxyOnly(value)


if __name__ == "__main__":
    unittest.main()
