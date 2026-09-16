"""HTTP-boundary and bounded-log tests for the first-boot setup service."""

from __future__ import annotations

import http.client
import importlib.util
import json
from importlib.machinery import SourceFileLoader
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "setup"
sys.path.insert(0, str(SETUP))


def load_script(name: str, path: Path):
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


server_module = load_script("vibestack_setup_api_tests", SETUP / "server.py")


class SetupAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = server_module.ThreadingHTTPServer(
            ("127.0.0.1", 0), server_module.Handler
        )
        cls.server.daemon_threads = True
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        self.password_status_patcher = mock.patch.object(
            server_module,
            "password_status",
            return_value={
                "password_configured": False,
                "sudo_password_required": True,
            },
        )
        self.password_status_patcher.start()
        self.state_directory = tempfile.TemporaryDirectory()
        self.old_state_dir = server_module.lib.STATE_DIR
        self.old_state_path = server_module.lib.STATE_PATH
        server_module.lib.STATE_DIR = self.state_directory.name
        server_module.lib.STATE_PATH = str(
            Path(self.state_directory.name) / "setup.json"
        )
        self.old_client_store = server_module._client_store
        server_module._client_store = server_module.WorkspaceClientStore(
            str(Path(self.state_directory.name) / "client-state")
        )
        with server_module._lock:
            server_module._job.update(
                running=False,
                log=b"",
                log_base=0,
                ok=None,
                target=[],
                phase="idle",
            )

    def tearDown(self):
        server_module.lib.STATE_DIR = self.old_state_dir
        server_module.lib.STATE_PATH = self.old_state_path
        server_module._client_store = self.old_client_store
        self.state_directory.cleanup()
        self.password_status_patcher.stop()

    def request(self, method, path, *, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            data = response.read()
            return response.status, dict(response.getheaders()), data
        finally:
            connection.close()

    def raw_post(self, headers):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.putrequest(
                "POST", "/api/skip", skip_host=True, skip_accept_encoding=True
            )
            for name, value in headers:
                connection.putheader(name, value)
            connection.endheaders(b"{}")
            response = connection.getresponse()
            payload = response.read()
            return response.status, payload
        finally:
            connection.close()

    def test_completed_state_redirects_unforced_and_force_serves_wizard(self):
        completed = {"completed": True}
        with (
            mock.patch.object(server_module.lib, "load_state", return_value=completed),
            mock.patch.object(server_module, "WEB_ROOT", str(SETUP)),
            mock.patch.object(
                server_module,
                "password_status",
                return_value={
                    "password_configured": True,
                    "sudo_password_required": True,
                },
            ),
        ):
            status, headers, raw = self.request("GET", "/")
            self.assertEqual(302, status)
            self.assertEqual("/", headers["Location"])
            self.assertEqual(b"", raw)

            status, headers, raw = self.request("GET", "/?force=1")
            self.assertEqual(200, status)
            self.assertEqual("text/html; charset=utf-8", headers["Content-Type"])
            self.assertIn(b"VibeStack", raw)

    def test_completed_component_state_does_not_bypass_missing_password(self):
        with (
            mock.patch.object(
                server_module.lib, "load_state", return_value={"completed": True}
            ),
            mock.patch.object(server_module, "WEB_ROOT", str(SETUP)),
        ):
            status, headers, raw = self.request("GET", "/")
        self.assertEqual(200, status)
        self.assertEqual("text/html; charset=utf-8", headers["Content-Type"])
        self.assertIn(b"Create your Linux password", raw)

    def test_same_origin_json_post_remains_supported(self):
        expected = {"completed": True, "selected": []}
        with mock.patch.object(
            server_module.lib, "mark_complete", return_value=expected
        ) as mutate:
            status, headers, raw = self.request(
                "POST",
                "/api/skip",
                body=b"{}",
                headers={
                    "Content-Type": "application/json",
                    "Origin": "http://127.0.0.1:%d" % self.port,
                    "Sec-Fetch-Site": "same-origin",
                },
            )
        self.assertEqual(200, status)
        self.assertEqual(expected, json.loads(raw)["state"])
        self.assertEqual("no-store", headers["Cache-Control"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        mutate.assert_called_once_with([], skipped=True)

    def test_state_exposes_only_bounded_password_configuration_status(self):
        catalog = {"version": 1, "groups": [], "presets": [], "components": []}
        configured = {
            "password_configured": True,
            "sudo_password_required": True,
        }
        with (
            mock.patch.object(server_module.lib, "load_catalog", return_value=catalog),
            mock.patch.object(server_module.lib, "installed_ids", return_value=[]),
            mock.patch.object(server_module, "password_status", return_value=configured),
        ):
            status, headers, raw = self.request("GET", "/api/state")
        self.assertEqual(200, status)
        self.assertEqual("no-store", headers["Cache-Control"])
        self.assertEqual(configured, json.loads(raw)["authentication"])
        self.assertNotIn("hash", raw.decode("utf-8").lower())

    def test_pairing_approval_listing_and_revocation_never_expose_credentials(self):
        requested = server_module._client_store.request_pairing(
            "setup test agent", ["workspace"]
        )
        status, _headers, raw = self.request("GET", "/api/clients")
        self.assertEqual(200, status)
        pending = json.loads(raw)
        self.assertEqual(
            requested["verification_code"], pending["pending"][0]["verification_code"]
        )
        self.assertNotIn(requested["polling_secret"].encode(), raw)

        status, _headers, raw = self.request(
            "POST",
            "/api/pairings/%s/approve" % requested["verification_code"],
            body=b"{}",
            headers={
                "Content-Type": "application/json",
                "Origin": "http://127.0.0.1:%d" % self.port,
                "Sec-Fetch-Site": "same-origin",
            },
        )
        self.assertEqual(200, status)
        self.assertEqual("approved", json.loads(raw)["pairing"]["status"])
        delivered = server_module._client_store.poll(
            requested["pairing_id"], requested["polling_secret"]
        )

        status, _headers, raw = self.request(
            "POST",
            "/api/clients/%s/revoke" % delivered["client_id"],
            body=b"{}",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(200, status)
        self.assertIsNotNone(json.loads(raw)["client"]["revoked_at"])
        self.assertNotIn(delivered["credential"].encode(), raw)
        self.assertFalse(server_module._client_store.authenticate(delivered["credential"]))

    def test_password_can_be_set_and_replaced_without_current_password(self):
        secret = "Local sudo passphrase 42!"
        configured = {
            "password_configured": True,
            "sudo_password_required": True,
        }
        with mock.patch.object(
            server_module, "set_linux_password", return_value=configured
        ) as update:
            for _attempt in range(2):
                status, headers, raw = self.request(
                    "POST",
                    "/api/password",
                    body=json.dumps(
                        {"password": secret, "confirmation": secret}
                    ).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "Origin": "http://127.0.0.1:%d" % self.port,
                        "Sec-Fetch-Site": "same-origin",
                    },
                )
                self.assertEqual(200, status)
                self.assertEqual("no-store", headers["Cache-Control"])
                self.assertEqual(configured, json.loads(raw)["authentication"])
                self.assertNotIn(secret.encode("utf-8"), raw)
        self.assertEqual([mock.call(secret), mock.call(secret)], update.call_args_list)
        with server_module._lock:
            self.assertNotIn(secret.encode("utf-8"), server_module._job["log"])

    def test_password_validation_rejects_bad_schema_mismatch_and_policy(self):
        cases = (
            ({"password": "long enough password"}, "invalid_request"),
            (
                {
                    "password": "long enough password",
                    "confirmation": "different password!",
                },
                "password_mismatch",
            ),
            ({"password": "short", "confirmation": "short"}, "invalid_password"),
            (
                {
                    "password": "long enough\npassword",
                    "confirmation": "long enough\npassword",
                },
                "invalid_password",
            ),
            (
                {
                    "password": "long enough password",
                    "confirmation": "long enough password",
                    "current_password": "not accepted",
                },
                "invalid_request",
            ),
        )
        with mock.patch.object(server_module, "set_linux_password") as update:
            for body, code in cases:
                with self.subTest(code=code, body=set(body)):
                    status, _headers, raw = self.request(
                        "POST",
                        "/api/password",
                        body=json.dumps(body).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    self.assertEqual(400, status)
                    self.assertEqual(code, json.loads(raw)["code"])
            update.assert_not_called()

    def test_password_helper_failure_does_not_echo_secret_or_stderr(self):
        secret = "Never echo this passphrase!"
        helper_error = server_module.PasswordBackendError(
            "Password helper request failed."
        )
        with mock.patch.object(
            server_module, "set_linux_password", side_effect=helper_error
        ):
            status, _headers, raw = self.request(
                "POST",
                "/api/password",
                body=json.dumps(
                    {"password": secret, "confirmation": secret}
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
        self.assertEqual(500, status)
        self.assertEqual("password_update_failed", json.loads(raw)["code"])
        self.assertNotIn(secret.encode("utf-8"), raw)
        with server_module._lock:
            self.assertNotIn(secret.encode("utf-8"), server_module._job["log"])

    def test_password_plaintext_is_passed_to_fixed_helper_stdin_only(self):
        secret = "Not visible in a process list!"
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=b'{"password_configured":true}\n',
            stderr=b"",
        )
        with mock.patch.object(server_module.subprocess, "run", return_value=completed) as run:
            result = server_module.set_linux_password(secret)
        self.assertTrue(result["password_configured"])
        argv = run.call_args.args[0]
        self.assertEqual(
            ["sudo", "-n", server_module.PASSWORD_HELPER, "set"], argv
        )
        self.assertNotIn(secret, " ".join(argv))
        self.assertIn(secret.encode("utf-8"), run.call_args.kwargs["input"])
        self.assertIs(subprocess.DEVNULL, run.call_args.kwargs["stderr"])

    def test_password_subprocess_exception_drops_secret_bearing_context(self):
        secret = "never retain this exception secret"
        with mock.patch.object(
            server_module.subprocess, "run", side_effect=OSError(secret)
        ):
            with self.assertRaises(server_module.PasswordBackendError) as raised:
                server_module.set_linux_password(secret)
        self.assertNotIn(secret, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

    def test_password_status_backend_failure_is_a_safe_503(self):
        catalog = {"version": 1, "groups": [], "presets": [], "components": []}
        with (
            mock.patch.object(server_module.lib, "load_catalog", return_value=catalog),
            mock.patch.object(server_module.lib, "installed_ids", return_value=[]),
            mock.patch.object(
                server_module,
                "password_status",
                side_effect=server_module.PasswordBackendError("safe failure"),
            ),
        ):
            status, _headers, raw = self.request("GET", "/api/state")
        self.assertEqual(503, status)
        self.assertEqual("password_status_unavailable", json.loads(raw)["code"])

    def test_cross_origin_and_cross_site_posts_cannot_mutate(self):
        cases = (
            {"Origin": "https://attacker.example"},
            {"Sec-Fetch-Site": "cross-site"},
            {"Sec-Fetch-Site": "same-site"},
        )
        for extra_headers in cases:
            with self.subTest(extra_headers=extra_headers), mock.patch.object(
                server_module.lib, "mark_complete"
            ) as mutate:
                status, _headers, raw = self.request(
                    "POST",
                    "/api/skip",
                    body=b"{}",
                    headers={"Content-Type": "application/json", **extra_headers},
                )
                self.assertEqual(403, status)
                self.assertEqual("cross_origin", json.loads(raw)["code"])
                mutate.assert_not_called()

    def test_cross_site_top_level_navigation_is_read_only_and_allowed(self):
        catalog = {"version": 1, "groups": [], "presets": [], "components": []}
        for destination in ("document", "empty"):
            with (
                self.subTest(destination=destination),
                mock.patch.object(server_module.lib, "load_catalog", return_value=catalog),
                mock.patch.object(server_module.lib, "installed_ids", return_value=[]),
            ):
                status, _headers, raw = self.request(
                    "GET",
                    "/api/state",
                    headers={
                        "Sec-Fetch-Site": "cross-site",
                        "Sec-Fetch-Mode": "navigate",
                        "Sec-Fetch-Dest": destination,
                    },
                )
                self.assertEqual(200, status, raw)

        status, _headers, raw = self.request(
            "GET",
            "/api/state",
            headers={
                "Sec-Fetch-Site": "cross-site",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
            },
        )
        self.assertEqual(403, status)
        self.assertEqual("cross_origin", json.loads(raw)["code"])

    def test_dns_rebound_host_is_rejected_before_reads_or_mutations(self):
        attacker = "evil.test:%d" % self.port
        status, _headers, raw = self.request(
            "GET", "/api/state", headers={"Host": attacker}
        )
        self.assertEqual(421, status)
        self.assertEqual("host_not_allowed", json.loads(raw)["code"])

        with mock.patch.object(server_module.lib, "mark_complete") as mutate:
            status, _headers, raw = self.request(
                "POST",
                "/api/skip",
                body=b"{}",
                headers={
                    "Host": attacker,
                    "Origin": "http://" + attacker,
                    "Content-Type": "application/json",
                },
            )
        self.assertEqual(421, status)
        self.assertEqual("host_not_allowed", json.loads(raw)["code"])
        mutate.assert_not_called()

    def test_backend_host_allowlist_requires_loopback_or_multilabel_magicdns(self):
        for authority in (
            "localhost",
            "127.0.0.1:7999",
            "[::1]:443",
            "vibe.example-tailnet.ts.net:9443",
        ):
            with self.subTest(authority=authority):
                host, _port = server_module._authority(authority)
                self.assertTrue(server_module._host_allowed(host))
        for authority in (
            "tailnet.ts.net",
            "bad_name.tailnet.ts.net",
            "good.tailnet.ts.net.evil",
            "localhost.evil",
        ):
            with self.subTest(authority=authority):
                host, _port = server_module._authority(authority)
                self.assertFalse(server_module._host_allowed(host))

    def test_only_json_content_type_is_accepted(self):
        for content_type in ("text/plain", "application/x-www-form-urlencoded"):
            with self.subTest(content_type=content_type), mock.patch.object(
                server_module.lib, "mark_complete"
            ) as mutate:
                status, _headers, raw = self.request(
                    "POST",
                    "/api/skip",
                    body=b"{}",
                    headers={"Content-Type": content_type},
                )
                self.assertEqual(415, status)
                self.assertEqual("unsupported_media_type", json.loads(raw)["code"])
                mutate.assert_not_called()

    def test_duplicate_sensitive_headers_are_rejected(self):
        base = [
            ("Host", "127.0.0.1:%d" % self.port),
            ("Content-Type", "application/json"),
            ("Content-Length", "2"),
        ]
        cases = {
            "host": base + [("Host", "127.0.0.1:%d" % self.port)],
            "origin": base
            + [("Origin", "http://127.0.0.1:%d" % self.port)] * 2,
            "content-type": base + [("Content-Type", "application/json")],
            "content-length": base + [("Content-Length", "2")],
            "fetch-site": base + [("Sec-Fetch-Site", "same-origin")] * 2,
        }
        for name, headers in cases.items():
            with self.subTest(header=name), mock.patch.object(
                server_module.lib, "mark_complete"
            ) as mutate:
                status, raw = self.raw_post(headers)
                self.assertIn(status, (400, 403))
                self.assertIn("code", json.loads(raw))
                mutate.assert_not_called()

    def test_trailing_or_duplicate_json_is_rejected(self):
        for body in (b"{} trailing", b'{"x":1,"x":2}'):
            with self.subTest(body=body), mock.patch.object(
                server_module.lib, "mark_complete"
            ) as mutate:
                status, _headers, raw = self.request(
                    "POST",
                    "/api/skip",
                    body=body,
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(400, status)
                self.assertEqual("invalid_json", json.loads(raw)["code"])
                mutate.assert_not_called()

    def test_body_limit_is_checked_before_reading(self):
        status, raw = self.raw_post(
            [
                ("Host", "127.0.0.1:%d" % self.port),
                ("Content-Type", "application/json"),
                ("Content-Length", str(server_module.MAX_REQUEST_BODY_BYTES + 1)),
            ]
        )
        self.assertEqual(413, status)
        self.assertEqual("request_too_large", json.loads(raw)["code"])

    def test_log_endpoint_uses_bounded_byte_cursors(self):
        with server_module._lock:
            server_module._job.update(
                log=b"x" * (server_module.MAX_LOG_PAGE_BYTES + 7),
                log_base=0,
            )
        status, _headers, raw = self.request("GET", "/api/log?offset=0")
        self.assertEqual(200, status)
        payload = json.loads(raw)
        self.assertEqual(server_module.MAX_LOG_PAGE_BYTES, len(payload["text"]))
        self.assertEqual(server_module.MAX_LOG_PAGE_BYTES, payload["offset"])
        self.assertTrue(payload["more"])

        status, _headers, raw = self.request(
            "GET", "/api/log?offset=%d" % payload["offset"]
        )
        self.assertEqual(200, status)
        second = json.loads(raw)
        self.assertEqual("x" * 7, second["text"])
        self.assertFalse(second["more"])

    def test_invalid_log_offsets_are_rejected(self):
        for query in (
            "offset=-1",
            "offset=1&offset=2",
            "offset=99999999999999999999",
            "other=1",
        ):
            with self.subTest(query=query):
                status, _headers, raw = self.request("GET", "/api/log?" + query)
                self.assertEqual(400, status)
                self.assertEqual("invalid_offset", json.loads(raw)["code"])

    def test_stale_log_cursor_reports_truncation(self):
        with server_module._lock:
            server_module._job.update(log=b"retained", log_base=500)
        status, _headers, raw = self.request("GET", "/api/log?offset=0")
        self.assertEqual(200, status)
        payload = json.loads(raw)
        self.assertEqual("retained", payload["text"])
        self.assertEqual(508, payload["offset"])
        self.assertTrue(payload["truncated"])

    def test_invalid_state_has_an_explicit_fail_closed_envelope(self):
        error = server_module.lib.StateError(
            "state_version_unsupported", "unsupported state version"
        )
        with (
            mock.patch.object(
                server_module.lib,
                "load_catalog",
                return_value={"components": []},
            ),
            mock.patch.object(server_module.lib, "installed_ids", return_value=[]),
            mock.patch.object(server_module.lib, "load_state", side_effect=error),
        ):
            status, _headers, raw = self.request("GET", "/api/state")
        self.assertEqual(200, status)
        payload = json.loads(raw)
        self.assertIs(payload["state_valid"], False)
        self.assertIsNone(payload["state"])
        self.assertEqual("state_version_unsupported", payload["state_error"]["code"])
        self.assertEqual([], payload["missing"])
        self.assertEqual([], payload["unknown_selected"])
        self.assertEqual([], payload["unsupported_selected"])
        self.assertEqual(payload["architecture"], payload["catalog"]["architecture"])

    def test_valid_state_envelope_exposes_removed_catalog_ids(self):
        state = {
            "version": 1,
            "completed": True,
            "completed_at": "2026-09-07T12:00:00Z",
            "selected": ["removed"],
            "skipped": False,
            "auto_restore": True,
        }
        with (
            mock.patch.object(
                server_module.lib,
                "load_catalog",
                return_value={"components": []},
            ),
            mock.patch.object(server_module.lib, "installed_ids", return_value=[]),
            mock.patch.object(server_module.lib, "load_state", return_value=state),
        ):
            status, _headers, raw = self.request("GET", "/api/state")
        self.assertEqual(200, status)
        payload = json.loads(raw)
        self.assertIs(payload["state_valid"], True)
        self.assertIsNone(payload["state_error"])
        self.assertEqual(["removed"], payload["missing"])
        self.assertEqual(["removed"], payload["unknown_selected"])
        self.assertEqual([], payload["unsupported_selected"])

    def test_explicit_unsupported_component_is_rejected_before_job_start(self):
        catalog = {
            "version": 1,
            "groups": [],
            "presets": [],
            "components": [
                {
                    "id": "chrome",
                    "name": "Chrome",
                    "architectures": ["amd64"],
                    "requires": [],
                    "probe": "false",
                }
            ],
        }
        with (
            mock.patch.object(server_module.lib, "load_catalog", return_value=catalog),
            mock.patch.object(
                server_module.lib, "current_architecture", return_value="arm64"
            ),
            mock.patch.object(server_module, "start_job") as start,
        ):
            status, _headers, raw = self.request(
                "POST",
                "/api/install",
                body=json.dumps({"components": ["chrome"]}).encode(),
                headers={"Content-Type": "application/json"},
            )
        self.assertEqual(409, status)
        self.assertEqual("unsupported_architecture", json.loads(raw)["code"])
        start.assert_not_called()

    def test_state_payload_keeps_saved_unsupported_component_unresolved(self):
        catalog = {
            "version": 1,
            "groups": [],
            "presets": [
                {
                    "id": "recommended",
                    "components": ["chrome"],
                }
            ],
            "components": [
                {
                    "id": "chrome",
                    "name": "Chrome",
                    "architectures": ["amd64"],
                    "requires": [],
                    "probe": "false",
                }
            ],
        }
        state = {
            "version": 1,
            "completed": True,
            "completed_at": "2026-09-07T12:00:00Z",
            "selected": ["chrome"],
            "skipped": False,
            "auto_restore": True,
        }
        with (
            mock.patch.object(server_module.lib, "load_catalog", return_value=catalog),
            mock.patch.object(server_module.lib, "load_state", return_value=state),
            mock.patch.object(
                server_module.lib, "current_architecture", return_value="arm64"
            ),
            mock.patch.object(server_module.lib, "is_installed") as probe,
        ):
            status, _headers, raw = self.request("GET", "/api/state")
        self.assertEqual(200, status)
        payload = json.loads(raw)
        component = payload["catalog"]["components"][0]
        self.assertEqual("arm64", payload["architecture"])
        self.assertFalse(component["supported"])
        self.assertIn("Unavailable on arm64", component["support_reason"])
        self.assertEqual([], payload["catalog"]["presets"][0]["components"])
        self.assertEqual(["chrome"], payload["missing"])
        self.assertEqual(["chrome"], payload["unsupported_selected"])
        probe.assert_not_called()

    def test_state_mutations_are_rejected_while_install_job_runs(self):
        entered = threading.Event()
        release = threading.Event()

        def blocked_job(_ids, _phase):
            entered.set()
            release.wait(5)
            with server_module._lock:
                server_module._job.update(running=False, ok=True)

        try:
            with mock.patch.object(server_module, "_run_job", side_effect=blocked_job):
                self.assertTrue(server_module.start_job(["node"]))
                self.assertTrue(entered.wait(2))
                for path in ("/api/skip", "/api/complete", "/api/reset"):
                    with self.subTest(path=path):
                        status, _headers, raw = self.request(
                            "POST",
                            path,
                            body=b"{}",
                            headers={"Content-Type": "application/json"},
                        )
                        self.assertEqual(409, status)
                        self.assertEqual("job_running", json.loads(raw)["code"])
        finally:
            release.set()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                with server_module._lock:
                    if not server_module._job["running"]:
                        break
                time.sleep(0.01)

    def test_state_and_log_report_an_external_cli_lease_truthfully(self):
        catalog = {"version": 1, "groups": [], "presets": [], "components": []}
        # This descriptor models the CLI. flock ownership is attached to an
        # open description, so the HTTP thread's separately opened descriptors
        # conflict with it exactly as they do across processes.
        lock_fd = server_module.lib.acquire_install_job_lock(blocking=False)
        try:
            with (
                mock.patch.object(server_module.lib, "load_catalog", return_value=catalog),
                mock.patch.object(server_module.lib, "installed_ids", return_value=[]),
            ):
                status, _headers, raw = self.request("GET", "/api/state")
                self.assertEqual(200, status)
                payload = json.loads(raw)
                self.assertTrue(payload["state_valid"])
                self.assertEqual(
                    {
                        "running": True,
                        "external": True,
                        "lease_valid": True,
                        "ok": None,
                        "phase": "external",
                        "target": [],
                        "length": 0,
                        "available_from": 0,
                    },
                    payload["job"],
                )

                status, _headers, raw = self.request("GET", "/api/log?offset=0")
                self.assertEqual(200, status)
                log_payload = json.loads(raw)
                self.assertTrue(log_payload["running"])
                self.assertTrue(log_payload["external"])
                self.assertEqual("external", log_payload["phase"])

            # Both HTTP probes used their own descriptors and must leave the
            # CLI process's lease intact.
            with self.assertRaises(server_module.lib.StateError) as raised:
                server_module.lib.acquire_install_job_lock(blocking=False)
            self.assertEqual("job_running", raised.exception.code)
        finally:
            server_module.lib.release_install_job_lock(lock_fd)

        with (
            mock.patch.object(server_module.lib, "load_catalog", return_value=catalog),
            mock.patch.object(server_module.lib, "installed_ids", return_value=[]),
        ):
            status, _headers, raw = self.request("GET", "/api/state")
        self.assertEqual(200, status)
        job = json.loads(raw)["job"]
        self.assertFalse(job["running"])
        self.assertFalse(job["external"])
        self.assertTrue(job["lease_valid"])

    def test_unsafe_install_lease_fails_the_state_envelope_closed(self):
        catalog = {"version": 1, "groups": [], "presets": [], "components": []}
        job_lock = (
            Path(server_module.lib.STATE_DIR) / server_module.lib.INSTALL_JOB_LOCK_NAME
        )
        os.mkfifo(job_lock, 0o600)
        with (
            mock.patch.object(server_module.lib, "load_catalog", return_value=catalog),
            mock.patch.object(server_module.lib, "installed_ids", return_value=[]),
        ):
            status, _headers, raw = self.request("GET", "/api/state")
        self.assertEqual(200, status)
        payload = json.loads(raw)
        self.assertFalse(payload["state_valid"])
        self.assertEqual("state_unreadable", payload["state_error"]["code"])
        self.assertFalse(payload["job"]["lease_valid"])
        self.assertIsNone(payload["job"]["external"])


class SetupLogBufferTests(unittest.TestCase):
    def setUp(self):
        with server_module._lock:
            server_module._job.update(log=b"", log_base=0)

    def test_in_memory_log_is_bounded_and_valid_utf8(self):
        with mock.patch.object(server_module.sys, "stdout"):
            server_module._append_log("\U0001f4be" * (server_module.MAX_LOG_BYTES // 2))
        with server_module._lock:
            data = server_module._job["log"]
            base = server_module._job["log_base"]
        self.assertLessEqual(len(data), server_module.MAX_LOG_BYTES)
        self.assertGreater(base, 0)
        data.decode("utf-8", "strict")

    def test_progress_is_mirrored_to_supervisor_stdout_without_controls(self):
        with mock.patch.object(server_module.sys, "stdout") as stdout:
            server_module.log_line("working\x1b[31m now\x1b[0m\x00")
        mirrored = "".join(call.args[0] for call in stdout.write.call_args_list)
        self.assertEqual("working now\ufffd\n", mirrored)
        with server_module._lock:
            self.assertEqual(mirrored.encode(), server_module._job["log"])


if __name__ == "__main__":
    unittest.main()
