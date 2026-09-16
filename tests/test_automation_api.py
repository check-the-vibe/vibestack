from __future__ import annotations

import base64
import http.client
import importlib.util
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
AUTOMATION = ROOT / "automation"
sys.path.insert(0, str(AUTOMATION))
import automationlib as lib  # noqa: E402

spec = importlib.util.spec_from_file_location("automation_http_server", AUTOMATION / "server.py")
assert spec is not None and spec.loader is not None
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


TOKEN = "t" * 43
PREFIX = "/api/v1/automation"


class CapturingAudit:
    def __init__(self):
        self.records = []
        self.lock = threading.Lock()

    def record(self, **record):
        with self.lock:
            self.records.append(record)


class AutomationHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.desktop = root / "Desktop"
        self.desktop.mkdir()
        self.projects = root / "Projects"
        self.projects.mkdir()
        self.client_store = lib.WorkspaceClientStore(str(root / "client-state"))
        self.backend = lib.AutomationBackend(
            desktop_root=str(self.desktop),
            projects_root=str(self.projects),
            job_directory=str(root / "jobs"),
            session_env_file=str(root / "no-session.env"),
            xdg_runtime_dir=str(root / "runtime"),
            client_store=self.client_store,
        )
        self.audit = CapturingAudit()
        self.server = api.create_server(
            port=0,
            backend=self.backend,
            token_provider=lib.TokenProvider(token=TOKEN, client_store=self.client_store),
            audit=self.audit,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(self, method, path, body=None, headers=None, *, authenticate=True):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=4)
        request_headers = dict(headers or {})
        if authenticate:
            request_headers.setdefault("Authorization", "Bearer " + TOKEN)
        encoded = body
        if isinstance(body, (dict, list)):
            encoded = json.dumps(body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        connection.request(method, path, body=encoded, headers=request_headers)
        response = connection.getresponse()
        raw = response.read()
        response_headers = dict(response.headers)
        content_type = response_headers.get("Content-Type", "")
        payload = json.loads(raw) if raw and content_type.startswith("application/json") else raw
        result = response.status, response_headers, payload
        connection.close()
        return result

    def test_authentication_discovery_request_ids_and_no_cors(self):
        status, headers, payload = self.request("GET", PREFIX, authenticate=False)
        self.assertEqual(401, status)
        self.assertEqual("unauthorized", payload["code"])
        self.assertIn("Bearer", headers["WWW-Authenticate"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertRegex(headers["X-Request-ID"], r"^[0-9a-f]{32}$")

        status, headers, payload = self.request(
            "GET", PREFIX, headers={"X-Request-ID": "client-request-7"}
        )
        self.assertEqual(200, status)
        self.assertEqual("client-request-7", headers["X-Request-ID"])
        self.assertEqual("no-store", headers["Cache-Control"])
        self.assertEqual("/api/v1/automation", payload["base_path"])
        self.assertEqual(4, payload["limits"]["workers"])
        self.assertEqual(
            ["start", "stop"], payload["allowlists"]["application_operations"]
        )
        self.assertEqual(
            ["minimized", "maximized", "normal"],
            payload["allowlists"]["window_states"],
        )
        self.assertEqual(
            [
                "terminal",
                "files",
                "settings",
                "chrome",
                "claude-desktop",
                "chatgpt",
                "mousepad",
                "geany",
            ],
            payload["allowlists"]["application_ids"],
        )

        status, _, payload = self.request("GET", PREFIX + "/")
        self.assertEqual((404, "not_found"), (status, payload["code"]))

    def test_public_pairing_delivers_one_revocable_client_credential(self):
        status, _, requested = self.request(
            "POST",
            PREFIX + "/pairing/requests",
            {"device_label": "test agent", "permissions": ["workspace"]},
            authenticate=False,
        )
        self.assertEqual(201, status)
        self.client_store.approve(requested["verification_code"])
        status, _, delivered = self.request(
            "POST",
            PREFIX + "/pairing/requests/%s/poll" % requested["pairing_id"],
            {"polling_secret": requested["polling_secret"]},
            authenticate=False,
        )
        self.assertEqual(200, status)
        credential = delivered["credential"]
        status, _, payload = self.request(
            "GET", PREFIX, headers={"Authorization": "Bearer " + credential}, authenticate=False
        )
        self.assertEqual(200, status)
        self.assertEqual("projects", payload["project_workflows"]["default_root"])
        self.client_store.revoke(delivered["client_id"])
        status, _, payload = self.request(
            "GET", PREFIX, headers={"Authorization": "Bearer " + credential}, authenticate=False
        )
        self.assertEqual((401, "unauthorized"), (status, payload["code"]))
        with self.assertRaises(lib.ClientAuthError):
            self.client_store.poll(requested["pairing_id"], requested["polling_secret"])
        audit = json.dumps(self.audit.records)
        self.assertNotIn(requested["polling_secret"], audit)
        self.assertNotIn(credential, audit)

    def test_host_and_origin_are_validated_on_reads_and_writes(self):
        status, _, _ = self.request(
            "GET",
            PREFIX,
            headers={
                "Host": "vibe.example-tailnet.ts.net",
                "Origin": "https://vibe.example-tailnet.ts.net",
            },
        )
        self.assertEqual(200, status)
        status, _, payload = self.request(
            "GET",
            PREFIX,
            headers={
                "Host": "vibe.example-tailnet.ts.net",
                "Origin": "https://evil.example",
            },
        )
        self.assertEqual((403, "cross_origin"), (status, payload["code"]))

        status, _, payload = self.request(
            "GET",
            PREFIX,
            headers={"Host": "evil.test", "Origin": "https://evil.test"},
        )
        self.assertEqual((421, "host_not_allowed"), (status, payload["code"]))

    def test_cross_site_top_level_navigation_reaches_auth_boundary(self):
        for destination in ("document", "empty"):
            with self.subTest(destination=destination):
                status, _, payload = self.request(
                    "GET",
                    PREFIX,
                    headers={
                        "Sec-Fetch-Site": "cross-site",
                        "Sec-Fetch-Mode": "navigate",
                        "Sec-Fetch-Dest": destination,
                    },
                )
                self.assertEqual(200, status, payload)

        status, _, payload = self.request(
            "GET",
            PREFIX,
            headers={
                "Sec-Fetch-Site": "cross-site",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
            },
        )
        self.assertEqual((403, "cross_origin"), (status, payload["code"]))

    def test_backend_host_allowlist_matches_the_edge_contract(self):
        for authority in (
            "localhost",
            "127.0.0.1:7997",
            "[::1]:443",
            "vibe.example-tailnet.ts.net:9443",
        ):
            with self.subTest(authority=authority):
                host, _port = api._authority(authority)
                self.assertTrue(api._host_allowed(host))
        for authority in (
            "tailnet.ts.net",
            "bad_name.tailnet.ts.net",
            "good.tailnet.ts.net.evil",
            "localhost.evil",
        ):
            with self.subTest(authority=authority):
                host, _port = api._authority(authority)
                self.assertFalse(api._host_allowed(host))
        for authority in ("localhost:0", "localhost:65536", "localhost."):
            with self.subTest(authority=authority), self.assertRaises(ValueError):
                api._authority(authority)

    def test_command_job_metadata_and_base64_output(self):
        secret = "command-output-value"
        status, submission_headers, payload = self.request(
            "POST",
            PREFIX + "/commands",
            {"argv": ["/usr/bin/printf", secret], "timeout_seconds": 5},
            {"X-Request-ID": "command-submission-request"},
        )
        self.assertEqual(202, status)
        job = payload["job"]
        self.assertEqual("command", job["kind"])
        self.assertNotIn("argv", job)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            status, _, payload = self.request("GET", PREFIX + "/jobs/" + job["id"])
            if payload["job"]["status"] not in ("queued", "running"):
                break
            time.sleep(0.02)
        self.assertEqual("succeeded", payload["job"]["status"])
        status, _, output = self.request(
            "GET",
            PREFIX + "/jobs/%s/output?stream=stdout&cursor=0&limit=64" % job["id"],
        )
        self.assertEqual(200, status)
        self.assertEqual(secret.encode(), base64.b64decode(output["data"]))
        self.assertEqual("base64", output["encoding"])
        self.assertTrue(output["eof"])
        self.assertNotIn(secret, json.dumps(self.audit.records))
        deadline = time.monotonic() + 2
        terminal_records = []
        while time.monotonic() < deadline:
            terminal_records = [
                record
                for record in self.audit.records
                if record["action"] == "job.terminal"
                and record.get("details", {}).get("job_id") == job["id"]
            ]
            if terminal_records:
                break
            time.sleep(0.01)
        self.assertEqual(1, len(terminal_records))
        terminal = terminal_records[0]
        self.assertEqual(submission_headers["X-Request-ID"], terminal["request_id"])
        self.assertEqual("JOB", terminal["method"])
        self.assertEqual(200, terminal["status"])
        self.assertEqual("command", terminal["details"]["kind"])
        self.assertEqual("succeeded", terminal["details"]["status"])
        self.assertEqual(0, terminal["details"]["exit_code"])
        self.assertIsNone(terminal["details"]["error_code"])
        self.assertEqual(len(secret), terminal["details"]["stdout_bytes"])
        self.assertFalse(terminal["details"]["stdout_truncated"])

    def test_cancelled_job_terminal_event_uses_submission_request_id_once(self):
        status, submission_headers, payload = self.request(
            "POST",
            PREFIX + "/commands",
            {"argv": ["/bin/sleep", "30"], "timeout_seconds": 30},
            {"X-Request-ID": "cancelled-job-submission"},
        )
        self.assertEqual(202, status)
        job_id = payload["job"]["id"]
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status, _, payload = self.request("GET", PREFIX + "/jobs/" + job_id)
            if payload["job"]["status"] == "running":
                break
            time.sleep(0.01)
        self.assertEqual("running", payload["job"]["status"])

        status, cancel_headers, _ = self.request(
            "POST",
            PREFIX + "/jobs/%s/cancel" % job_id,
            {},
            {"X-Request-ID": "cancelled-job-control"},
        )
        self.assertEqual(200, status)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            status, _, payload = self.request("GET", PREFIX + "/jobs/" + job_id)
            if payload["job"]["status"] == "cancelled":
                break
            time.sleep(0.01)
        self.assertEqual("cancelled", payload["job"]["status"])
        self.request("POST", PREFIX + "/jobs/%s/cancel" % job_id, {})

        deadline = time.monotonic() + 2
        terminal_records = []
        while time.monotonic() < deadline:
            terminal_records = [
                record
                for record in self.audit.records
                if record["action"] == "job.terminal"
                and record.get("details", {}).get("job_id") == job_id
            ]
            if terminal_records:
                break
            time.sleep(0.01)
        self.assertEqual(1, len(terminal_records))
        terminal = terminal_records[0]
        self.assertEqual(submission_headers["X-Request-ID"], terminal["request_id"])
        self.assertNotEqual(cancel_headers["X-Request-ID"], terminal["request_id"])
        self.assertEqual(499, terminal["status"])
        self.assertEqual("cancelled", terminal["details"]["status"])
        self.assertEqual("cancelled", terminal["details"]["error_code"])

    def test_raw_binary_files_etag_range_head_and_preconditions(self):
        content = b"\x00\xffabcdef"
        status, headers, payload = self.request(
            "PUT",
            PREFIX + "/files/data.bin",
            content,
            {"Content-Type": "application/octet-stream", "If-None-Match": "*"},
        )
        self.assertEqual(201, status)
        etag = payload["file"]["etag"]

        status, headers, raw = self.request("GET", PREFIX + "/files/data.bin")
        self.assertEqual((200, content), (status, raw))
        self.assertEqual(etag, headers["ETag"])
        self.assertEqual("bytes", headers["Accept-Ranges"])

        status, headers, raw = self.request(
            "GET", PREFIX + "/files/data.bin", headers={"Range": "bytes=2-5"}
        )
        self.assertEqual((206, content[2:6]), (status, raw))
        self.assertEqual("bytes 2-5/8", headers["Content-Range"])

        status, headers, raw = self.request("HEAD", PREFIX + "/files/data.bin")
        self.assertEqual(200, status)
        self.assertEqual(str(len(content)), headers["Content-Length"])
        self.assertEqual(b"", raw)

        status, _, raw = self.request(
            "GET", PREFIX + "/files/data.bin", headers={"If-None-Match": etag}
        )
        self.assertEqual((304, b""), (status, raw))
        status, not_modified_headers, raw = self.request(
            "GET", PREFIX + "/files/data.bin", headers={"If-None-Match": etag}
        )
        self.assertNotIn("Content-Length", not_modified_headers)
        status, _, payload = self.request(
            "PUT",
            PREFIX + "/files/data.bin",
            b"lost",
            {"Content-Type": "application/octet-stream", "If-Match": '"sha256-stale"'},
        )
        self.assertEqual((412, "precondition_failed"), (status, payload["code"]))
        time.sleep(0.02)
        file_records = [record for record in self.audit.records if record["action"].startswith("file.")]
        self.assertTrue(any(record.get("details", {}).get("path") == "data.bin" for record in file_records))
        self.assertNotIn(content.hex(), json.dumps(file_records))

    def test_project_files_preserve_binary_bytes_on_the_independent_root(self):
        content = b"project\x00\xffbytes"
        status, _, payload = self.request(
            "PUT",
            PREFIX + "/projects/source.bin",
            content,
            {"Content-Type": "application/octet-stream", "If-None-Match": "*"},
        )
        self.assertEqual(201, status)
        self.assertEqual("source.bin", payload["file"]["path"])
        self.assertFalse((self.desktop / "source.bin").exists())
        status, _, raw = self.request("GET", PREFIX + "/projects/source.bin")
        self.assertEqual((200, content), (status, raw))
        project_records = [
            record for record in self.audit.records if record["action"].startswith("project_file.")
        ]
        self.assertTrue(all(record.get("details", {}).get("root") == "projects" for record in project_records))

    def test_clipboard_is_plain_utf8_and_screenshot_is_png(self):
        clipboard = {"value": b""}
        self.backend.set_clipboard = lambda data: clipboard.update(value=data) or {"bytes": len(data)}
        self.backend.get_clipboard = lambda: clipboard["value"]
        status, _, payload = self.request(
            "PUT",
            PREFIX + "/clipboard",
            "hello \N{SNOWMAN}".encode(),
            {"Content-Type": "text/plain; charset=utf-8"},
        )
        self.assertEqual(200, status)
        self.assertEqual(9, payload["bytes"])
        status, headers, raw = self.request("GET", PREFIX + "/clipboard")
        self.assertEqual(200, status)
        self.assertEqual("hello \N{SNOWMAN}".encode(), raw)
        self.assertTrue(headers["Content-Type"].startswith("text/plain"))

        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        self.backend.screenshot = lambda filename=None: (png, None)
        status, headers, raw = self.request("POST", PREFIX + "/screenshot", {})
        self.assertEqual((200, png), (status, raw))
        self.assertEqual("image/png", headers["Content-Type"])

    def test_invalid_window_state_does_not_enter_audit(self):
        secret = "do-not-log-this-request-value"
        status, _, payload = self.request(
            "POST",
            PREFIX + "/windows/0x1/state",
            {"state": {"value": secret}},
        )
        self.assertEqual((400, "invalid_window_state"), (status, payload["code"]))
        time.sleep(0.02)
        self.assertNotIn(secret, json.dumps(self.audit.records))

    def test_json_schema_body_limits_and_methods_are_strict(self):
        status, _, payload = self.request(
            "POST", PREFIX + "/commands", {"argv": ["printf", "no"]}
        )
        self.assertEqual((400, "invalid_argv"), (status, payload["code"]))
        status, _, payload = self.request("DELETE", PREFIX + "/clipboard")
        self.assertEqual((405, "method_not_allowed"), (status, payload["code"]))
        status, headers, payload = self.request("OPTIONS", PREFIX)
        self.assertEqual((405, "method_not_allowed"), (status, payload["code"]))
        self.assertNotIn("Access-Control-Allow-Origin", headers)

        status, headers, payload = self.request("PROPFIND", PREFIX, authenticate=False)
        self.assertEqual((401, "unauthorized"), (status, payload["code"]))
        self.assertTrue(headers["Content-Type"].startswith("application/json"))
        status, _, payload = self.request("PROPFIND", PREFIX)
        self.assertEqual((405, "method_not_allowed"), (status, payload["code"]))


if __name__ == "__main__":
    unittest.main()
