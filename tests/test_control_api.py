from __future__ import annotations

import http.client
import io
import json
import socket
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "control"))
import controllib as lib  # noqa: E402
import server as control_server  # noqa: E402


class FakeBackend:
    def __init__(self) -> None:
        self.restart_calls: list[str] = []
        self.display_calls: list[str] = []
        self.log_calls: list[tuple[str, int | None, int]] = []

    def status_payload(self):
        return {
            "apiVersion": "1",
            "uptimeSeconds": 10,
            "disk": {},
            "display": {"resolution": "1920x1200"},
            "services": {},
        }

    def get_display(self):
        return {
            "resolution": "1920x1200",
            "availableResolutions": list(lib.SUPPORTED_RESOLUTIONS),
            "supportedResolutions": list(lib.SUPPORTED_RESOLUTIONS),
        }

    def set_display(self, resolution):
        self.display_calls.append(resolution)
        return {
            "resolution": resolution,
            "availableResolutions": list(lib.SUPPORTED_RESOLUTIONS),
            "supportedResolutions": list(lib.SUPPORTED_RESOLUTIONS),
        }

    def restart_service(self, service):
        self.restart_calls.append(service)
        return {"service": service, "state": "RUNNING", "restarted": True}

    def service_logs(self, service, cursor, limit):
        self.log_calls.append((service, cursor, limit))
        return {
            "service": service,
            "lines": ["one"],
            "nextCursor": 3,
            "reset": False,
            "truncated": False,
        }


class HTTPServiceTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend()
        self.server = control_server.create_server(port=0, backend=self.backend)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        request_headers = dict(headers or {})
        encoded = body
        if isinstance(body, (dict, list)):
            encoded = json.dumps(body).encode()
            request_headers.setdefault("Content-Type", "application/json")
        connection.request(method, path, body=encoded, headers=request_headers)
        response = connection.getresponse()
        raw = response.read()
        result = (
            response.status,
            dict(response.headers),
            json.loads(raw) if raw else None,
        )
        connection.close()
        return result

    def raw_request(self, method, path, headers, body=b""):
        request = ["%s %s HTTP/1.1" % (method, path)]
        request.extend("%s: %s" % pair for pair in headers)
        encoded = ("\r\n".join(request) + "\r\n\r\n").encode("ascii") + body
        connection = socket.create_connection(("127.0.0.1", self.port), timeout=2)
        try:
            connection.sendall(encoded)
            connection.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        finally:
            connection.close()
        raw = b"".join(chunks)
        head, separator, response_body = raw.partition(b"\r\n\r\n")
        self.assertTrue(separator)
        status = int(head.split(b" ", 2)[1])
        response_headers = {}
        for line in head.split(b"\r\n")[1:]:
            name, value = line.split(b":", 1)
            response_headers[name.decode("ascii")] = value.strip().decode("ascii")
        payload = json.loads(response_body) if response_body else None
        return status, response_headers, payload

    def test_read_endpoints(self):
        status, headers, payload = self.request("GET", "/api/v1/status")
        self.assertEqual(200, status)
        self.assertEqual("no-store", headers["Cache-Control"])
        self.assertEqual("1", payload["apiVersion"])

        status, _, payload = self.request("GET", "/api/v1/display")
        self.assertEqual(200, status)
        self.assertEqual("1920x1200", payload["resolution"])

        status, _, payload = self.request(
            "GET", "/api/v1/logs/vnc?cursor=12&limit=7"
        )
        self.assertEqual(200, status)
        self.assertEqual("vnc", payload["service"])
        self.assertEqual([("vnc", 12, 7)], self.backend.log_calls)

    def test_log_query_and_service_are_strictly_validated(self):
        for path, code in (
            ("/api/v1/logs/not-real", "unknown_service"),
            ("/api/v1/logs/vnc?limit=0", "invalid_query"),
            ("/api/v1/logs/vnc?limit=201", "invalid_query"),
            ("/api/v1/logs/vnc?cursor=-1", "invalid_query"),
            ("/api/v1/logs/vnc?cursor=1&cursor=2", "invalid_query"),
            ("/api/v1/logs/vnc?path=/etc/passwd", "invalid_query"),
        ):
            with self.subTest(path=path):
                status, _, payload = self.request("GET", path)
                self.assertIn(status, (400, 404))
                self.assertEqual(code, payload["code"])

    def test_https_origin_with_matching_preserved_host_is_allowed(self):
        status, _, payload = self.request(
            "PUT",
            "/api/v1/display",
            {"resolution": "1440x900"},
            {
                "Host": "vibestack.example-tailnet.ts.net",
                "Origin": "https://vibestack.example-tailnet.ts.net",
            },
        )
        self.assertEqual(200, status)
        self.assertEqual("1440x900", payload["resolution"])
        self.assertEqual(["1440x900"], self.backend.display_calls)

    def test_matching_explicit_default_https_port_is_allowed(self):
        status, _, _ = self.request(
            "POST",
            "/api/v1/services/desktop/restart",
            {},
            {
                "Host": "vibestack.example-tailnet.ts.net",
                "Origin": "https://vibestack.example-tailnet.ts.net:443",
            },
        )
        self.assertEqual(200, status)

    def test_cross_origin_and_nondefault_origin_port_are_rejected(self):
        for origin in (
            "https://evil.example",
            "https://vibestack.example-tailnet.ts.net:444",
            "null",
        ):
            with self.subTest(origin=origin):
                status, _, payload = self.request(
                    "POST",
                    "/api/v1/services/vnc/restart",
                    {},
                    {"Host": "vibestack.example-tailnet.ts.net", "Origin": origin},
                )
                self.assertEqual(403, status)
                self.assertEqual("cross_origin", payload["code"])
        self.assertEqual([], self.backend.restart_calls)

    def test_dns_rebound_host_is_rejected_before_reads_or_mutations(self):
        attacker = "evil.test:%d" % self.port
        status, _, payload = self.request(
            "GET", "/api/v1/status", headers={"Host": attacker}
        )
        self.assertEqual((421, "host_not_allowed"), (status, payload["code"]))

        status, _, payload = self.request(
            "PUT",
            "/api/v1/display",
            {"resolution": "1440x900"},
            {"Host": attacker, "Origin": "http://" + attacker},
        )
        self.assertEqual((421, "host_not_allowed"), (status, payload["code"]))
        self.assertEqual([], self.backend.display_calls)

    def test_backend_host_allowlist_requires_loopback_or_multilabel_magicdns(self):
        for authority in (
            "localhost",
            "127.0.0.1:7998",
            "[::1]:443",
            "vibe.example-tailnet.ts.net:9443",
        ):
            with self.subTest(authority=authority):
                host, _port = control_server._authority(authority)
                self.assertTrue(control_server._host_allowed(host))
        for authority in (
            "tailnet.ts.net",
            "bad_name.tailnet.ts.net",
            "good.tailnet.ts.net.evil",
            "localhost.evil",
        ):
            with self.subTest(authority=authority):
                host, _port = control_server._authority(authority)
                self.assertFalse(control_server._host_allowed(host))

    def test_restart_is_json_only_and_has_no_fields(self):
        status, _, payload = self.request(
            "POST",
            "/api/v1/services/setup/restart",
            b"{}",
            {"Content-Type": "text/plain"},
        )
        self.assertEqual(415, status)
        self.assertEqual("unsupported_media_type", payload["code"])

        status, _, payload = self.request(
            "POST", "/api/v1/services/setup/restart", {"program": "nginx"}
        )
        self.assertEqual(400, status)
        self.assertEqual("unknown_field", payload["code"])
        self.assertEqual([], self.backend.restart_calls)

        status, _, payload = self.request(
            "POST", "/api/v1/services/setup/restart", {}
        )
        self.assertEqual(200, status)
        self.assertTrue(payload["restarted"])
        self.assertEqual(["setup"], self.backend.restart_calls)

    def test_zero_length_json_mutation_is_rejected(self):
        status, _, payload = self.request(
            "POST",
            "/api/v1/services/setup/restart",
            b"",
            {"Content-Type": "application/json", "Content-Length": "0"},
        )
        self.assertEqual(400, status)
        self.assertEqual("invalid_json", payload["code"])
        self.assertEqual([], self.backend.restart_calls)

    def test_display_accepts_aligned_bounded_dimensions_only(self):
        status, _, payload = self.request(
            "PUT", "/api/v1/display", {"resolution": "1256x600"}
        )
        self.assertEqual(200, status)
        self.assertEqual("1256x600", payload["resolution"])
        self.assertEqual(["1256x600"], self.backend.display_calls)

        for body, code in (
            ({"resolution": "639x480"}, "unsupported_resolution"),
            ({"resolution": "640x478"}, "unsupported_resolution"),
            ({"resolution": "1928x1200"}, "unsupported_resolution"),
            ({"resolution": "1920x1202"}, "unsupported_resolution"),
            ({"resolution": "641x480"}, "unsupported_resolution"),
            ({"resolution": "640x481"}, "unsupported_resolution"),
            ({"resolution": "640x480;id"}, "unsupported_resolution"),
            ({"resolution": "1440x900", "output": "screen"}, "invalid_display_request"),
            ({}, "invalid_display_request"),
        ):
            with self.subTest(body=body):
                status, _, payload = self.request("PUT", "/api/v1/display", body)
                self.assertEqual(400, status)
                self.assertEqual(code, payload["code"])

    def test_body_limit_and_duplicate_keys(self):
        status, _, payload = self.request(
            "PUT",
            "/api/v1/display",
            b"{" + (b" " * control_server.MAX_BODY_BYTES) + b"}",
            {"Content-Type": "application/json"},
        )
        self.assertEqual(413, status)
        self.assertEqual("body_too_large", payload["code"])

        duplicate = b'{"resolution":"1440x900","resolution":"1920x1200"}'
        status, _, payload = self.request(
            "PUT",
            "/api/v1/display",
            duplicate,
            {"Content-Type": "application/json"},
        )
        self.assertEqual(400, status)
        self.assertEqual("invalid_json", payload["code"])

    def test_duplicate_sensitive_headers_are_rejected(self):
        authority = "127.0.0.1:%d" % self.port
        base = [
            ("Host", authority),
            ("Content-Type", "application/json"),
            ("Content-Length", "2"),
        ]
        cases = {
            "host": (base + [("Host", authority)], "invalid_host"),
            "origin": (
                base + [("Origin", "http://" + authority)] * 2,
                "cross_origin",
            ),
            "fetch-site": (
                base + [("Sec-Fetch-Site", "same-origin")] * 2,
                "invalid_request",
            ),
            "content-type": (
                base + [("Content-Type", "application/json")],
                "invalid_header",
            ),
            "content-length": (
                base + [("Content-Length", "2")],
                "invalid_header",
            ),
        }
        for name, (headers, code) in cases.items():
            with self.subTest(header=name):
                status, _, payload = self.raw_request(
                    "POST", "/api/v1/services/setup/restart", headers, b"{}"
                )
                self.assertIn(status, (400, 403))
                self.assertEqual(code, payload["code"])
        self.assertEqual([], self.backend.restart_calls)

    def test_incomplete_body_and_non_decimal_length_are_rejected(self):
        authority = "127.0.0.1:%d" % self.port
        base = [
            ("Host", authority),
            ("Content-Type", "application/json"),
        ]
        status, _, payload = self.raw_request(
            "POST",
            "/api/v1/services/setup/restart",
            base + [("Content-Length", "5")],
            b"{}",
        )
        self.assertEqual((400, "incomplete_body"), (status, payload["code"]))

        status, _, payload = self.raw_request(
            "POST",
            "/api/v1/services/setup/restart",
            base + [("Content-Length", "+2")],
            b"{}",
        )
        self.assertEqual((400, "invalid_length"), (status, payload["code"]))
        self.assertEqual([], self.backend.restart_calls)

    def test_json_media_type_encoding_and_numbers_are_strict(self):
        status, _, payload = self.request(
            "POST",
            "/api/v1/services/setup/restart",
            b"{}",
            {"Content-Type": "application/json; charset=utf-8"},
        )
        self.assertEqual(200, status)
        self.assertTrue(payload["restarted"])

        for content_type in (
            "application/json; profile=debug",
            "application/json; charset=iso-8859-1",
        ):
            with self.subTest(content_type=content_type):
                status, _, payload = self.request(
                    "POST",
                    "/api/v1/services/setup/restart",
                    b"{}",
                    {"Content-Type": content_type},
                )
                self.assertEqual(
                    (415, "unsupported_media_type"), (status, payload["code"])
                )

        status, _, payload = self.request(
            "PUT",
            "/api/v1/display",
            b'{"resolution":NaN}',
            {"Content-Type": "application/json"},
        )
        self.assertEqual((400, "invalid_json"), (status, payload["code"]))

        status, _, payload = self.request(
            "PUT",
            "/api/v1/display",
            b'\xff{"resolution":"1440x900"}',
            {"Content-Type": "application/json"},
        )
        self.assertEqual((400, "invalid_json"), (status, payload["code"]))
        self.assertEqual(["setup"], self.backend.restart_calls)
        self.assertEqual([], self.backend.display_calls)

    def test_fragment_target_is_rejected_and_raw_target_is_not_logged(self):
        status, _, payload = self.request("GET", "/api/v1/status#fragment")
        self.assertEqual((400, "invalid_path"), (status, payload["code"]))

        captured = io.StringIO()
        with mock.patch.object(control_server.sys, "stderr", captured):
            status, _, payload = self.request(
                "GET", "/api/v1/status?credential=do-not-log-this"
            )
        self.assertEqual((400, "invalid_query"), (status, payload["code"]))
        self.assertNotIn("do-not-log-this", captured.getvalue())

    def test_mutations_are_serialized(self):
        self.server.mutation_lock.acquire()
        try:
            status, _, payload = self.request(
                "POST", "/api/v1/services/terminal/restart", {}
            )
        finally:
            self.server.mutation_lock.release()
        self.assertEqual(409, status)
        self.assertEqual("mutation_in_progress", payload["code"])
        self.assertEqual([], self.backend.restart_calls)

    def test_unknown_routes_and_methods_return_structured_errors(self):
        status, _, payload = self.request("GET", "/api/v1/nope")
        self.assertEqual((404, "not_found"), (status, payload["code"]))
        status, _, payload = self.request("DELETE", "/api/v1/display")
        self.assertEqual((405, "method_not_allowed"), (status, payload["code"]))

    def test_head_trace_and_connect_return_structured_405(self):
        status, headers, payload = self.request("HEAD", "/api/v1/status")
        self.assertEqual(405, status)
        self.assertEqual("application/json; charset=utf-8", headers["Content-Type"])
        self.assertIsNone(payload)
        self.assertGreater(int(headers["Content-Length"]), 0)

        for method in ("TRACE", "CONNECT"):
            with self.subTest(method=method):
                status, _, payload = self.request(method, "/api/v1/status")
                self.assertEqual(405, status)
                self.assertEqual("method_not_allowed", payload["code"])


if __name__ == "__main__":
    unittest.main()
