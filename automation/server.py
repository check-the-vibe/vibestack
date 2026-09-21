#!/usr/bin/env python3
"""Authenticated loopback HTTP server for VibeStack desktop automation."""

from __future__ import annotations

import json
import os
import re
import signal
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping
from urllib.parse import parse_qs, unquote_to_bytes, urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import automationlib as lib  # noqa: E402
from files import FileError, parse_range  # noqa: E402
from runner import MAX_OUTPUT_PAGE_BYTES, RunnerError  # noqa: E402
from vibestack_hosts import host_is_configured  # noqa: E402


HOST_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class RequestError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _authority(value: str) -> tuple[str, int | None]:
    if (
        not value
        or len(value) > 255
        or any(character.isspace() for character in value)
        or any(character in value for character in "/\\@,")
    ):
        raise ValueError("invalid authority")
    parsed = urlsplit("//" + value)
    if (
        not parsed.hostname
        or parsed.hostname.endswith(".")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid authority")
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("invalid authority") from None
    if port == 0:
        raise ValueError("invalid authority")
    return parsed.hostname.lower(), port


def _host_allowed(host_name: str) -> bool:
    if host_name in ("localhost", "127.0.0.1", "::1"):
        return True
    labels = host_name.split(".")
    return host_is_configured(host_name) or (
        len(labels) >= 4
        and labels[-2:] == ["ts", "net"]
        and all(HOST_LABEL_RE.fullmatch(label) for label in labels[:-2])
    )


def validate_request_source(handler: BaseHTTPRequestHandler) -> None:
    hosts = handler.headers.get_all("Host") or []
    if len(hosts) != 1:
        raise RequestError("invalid_host", "A single valid Host header is required.", 400)
    try:
        host_name, host_port = _authority(hosts[0])
    except ValueError:
        raise RequestError("invalid_host", "A single valid Host header is required.", 400) from None
    if not _host_allowed(host_name):
        raise RequestError(
            "host_not_allowed", "The request Host is not allowed.", 421
        )

    fetch_sites = handler.headers.get_all("Sec-Fetch-Site") or []
    if len(fetch_sites) > 1:
        raise RequestError("invalid_request", "Duplicate fetch metadata is not allowed.", 400)
    fetch_site = fetch_sites[0].strip().lower() if fetch_sites else ""
    if fetch_site in ("cross-site", "same-site"):
        if handler.command not in ("GET", "HEAD"):
            raise RequestError("cross_origin", "Cross-origin requests are not allowed.", 403)
        modes = handler.headers.get_all("Sec-Fetch-Mode") or []
        destinations = handler.headers.get_all("Sec-Fetch-Dest") or []
        if len(modes) != 1 or len(destinations) != 1:
            raise RequestError("invalid_request", "Safe navigation fetch metadata is required.", 400)
        if not (
            modes[0].strip().lower() == "navigate"
            and destinations[0].strip().lower() in ("document", "empty")
        ):
            raise RequestError("cross_origin", "Cross-origin requests are not allowed.", 403)
    if fetch_site not in ("", "none", "same-origin"):
        if fetch_site not in ("cross-site", "same-site"):
            raise RequestError("invalid_request", "Invalid fetch metadata.", 400)
    origins = handler.headers.get_all("Origin") or []
    if not origins:
        return
    if len(origins) != 1 or origins[0] == "null":
        raise RequestError("cross_origin", "Cross-origin requests are not allowed.", 403)
    parsed = urlsplit(origins[0])
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise RequestError("cross_origin", "Cross-origin requests are not allowed.", 403)
    try:
        origin_port = parsed.port
    except ValueError:
        raise RequestError("cross_origin", "Cross-origin requests are not allowed.", 403) from None
    default_port = 443 if parsed.scheme == "https" else 80
    effective_origin_port = origin_port or default_port
    ports_match = (
        host_port is None and (origin_port is None or origin_port == default_port)
    ) or host_port == effective_origin_port
    if parsed.hostname.lower() != host_name or not ports_match:
        raise RequestError("cross_origin", "Cross-origin requests are not allowed.", 403)


class AutomationHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

    def __init__(
        self,
        address: tuple[str, int],
        backend: lib.AutomationBackend,
        token_provider: lib.TokenProvider,
        audit: lib.AuditLogger,
    ):
        super().__init__(address, Handler)
        self.backend = backend
        self.token_provider = token_provider
        self.audit = audit

    def server_close(self) -> None:
        try:
            close = getattr(self.backend, "close", None)
            if close is not None:
                close()
        finally:
            super().server_close()


class Handler(BaseHTTPRequestHandler):
    server_version = "VibeStackAutomation/1"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    request_id = ""
    response_status = 500
    audit_action = "request"
    audit_details: dict[str, object]

    @property
    def automation_server(self) -> AutomationHTTPServer:
        return self.server  # type: ignore[return-value]

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(30)

    def __getattr__(self, name: str) -> Any:
        # BaseHTTPRequestHandler otherwise emits an unauthenticated HTML 501
        # for extension methods. Route every syntactically valid HTTP method
        # through the same auth, JSON error, request-id, and audit boundary.
        if name.startswith("do_"):
            return self._handle
        raise AttributeError(name)

    def log_message(self, fmt: str, *args: Any) -> None:
        # Avoid a duplicate, unbounded raw HTTP request line. The structured
        # audit stream records only the selected route's reviewed metadata.
        return

    def _common_headers(self) -> None:
        # Closing each upstream response avoids interpreting an unread body on
        # a rejected/GET request as a second pipelined request.
        self.close_connection = True
        self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Request-ID", self.request_id)

    def _send_json(
        self,
        status: int,
        payload: Mapping[str, Any],
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.response_status = status
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._common_headers()
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_bytes(
        self,
        status: int,
        body: bytes,
        content_type: str,
        *,
        headers: Mapping[str, str] | None = None,
        represented_length: int | None = None,
    ) -> None:
        self.response_status = status
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body) if represented_length is None else represented_length))
        self._common_headers()
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_not_modified(self, etag: str) -> None:
        self.response_status = 304
        self.send_response(304)
        self.send_header("ETag", etag)
        self._common_headers()
        self.end_headers()

    def _error(self, error: RequestError | lib.AutomationError | FileError | RunnerError) -> None:
        headers = (
            {"WWW-Authenticate": 'Bearer realm="VibeStack automation"'}
            if error.status == 401
            else None
        )
        self._send_json(
            error.status,
            {"code": error.code, "message": error.message, "request_id": self.request_id},
            headers=headers,
        )

    def _request_id(self) -> str:
        values = self.headers.get_all("X-Request-ID") or []
        if len(values) == 1 and lib.REQUEST_ID_RE.fullmatch(values[0]):
            return values[0]
        return uuid.uuid4().hex

    def _authenticate(self) -> None:
        values = self.headers.get_all("Authorization") or []
        authorization = values[0] if len(values) == 1 else None
        if not self.automation_server.token_provider.authenticate(authorization):
            raise RequestError("unauthorized", "A valid bearer token is required.", 401)

    def _handle(self) -> None:
        started = time.monotonic()
        self.request_id = self._request_id()
        self.response_status = 500
        self.audit_action = "request"
        self.audit_details = {}
        try:
            validate_request_source(self)
            if not self._is_public_pairing_request():
                self._authenticate()
            self._dispatch()
        except (RequestError, lib.AutomationError, FileError, RunnerError) as exc:
            if exc.status == 401:
                self.audit_action = "authentication"
            self._error(exc)
        except (BrokenPipeError, ConnectionResetError):
            self.response_status = 499
        except Exception as exc:  # pragma: no cover - defensive service boundary
            print(
                "[automation] internal_error request_id=%s type=%s"
                % (self.request_id, type(exc).__name__),
                file=sys.stderr,
                flush=True,
            )
            try:
                self._error(
                    RequestError("internal_error", "The automation request failed.", 500)
                )
            except (BrokenPipeError, ConnectionResetError):
                self.response_status = 499
        finally:
            self.automation_server.audit.record(
                request_id=self.request_id,
                method=self.command,
                action=self.audit_action,
                status=self.response_status,
                duration_ms=int((time.monotonic() - started) * 1000),
                details=self.audit_details,
            )

    def _is_public_pairing_request(self) -> bool:
        """Pairing bootstrap is secret-bearing but intentionally unauthenticated."""

        path = urlsplit(self.path).path
        return self.command == "POST" and (
            path == lib.API_PREFIX + "/pairing/requests"
            or re.fullmatch(
                re.escape(lib.API_PREFIX)
                + r"/pairing/requests/([0-9a-f]{32})/poll",
                path,
            )
            is not None
        )

    def _dispatch(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.fragment:
            raise RequestError("invalid_path", "The request path is invalid.", 400)
        if self.command == "GET":
            self._get(parsed.path, parsed.query)
        elif self.command == "HEAD":
            self._head(parsed.path, parsed.query)
        elif self.command == "POST":
            self._post(parsed.path, parsed.query)
        elif self.command == "PUT":
            self._put(parsed.path, parsed.query)
        else:
            self.audit_action = "method.reject"
            raise RequestError("method_not_allowed", "Method not allowed.", 405)

    @staticmethod
    def _no_query(query: str) -> None:
        if query:
            raise RequestError("invalid_query", "This endpoint takes no query.", 400)

    def _get(self, path: str, query: str) -> None:
        if path == lib.API_PREFIX:
            self._no_query(query)
            self.audit_action = "capabilities.read"
            self._send_json(200, self.automation_server.backend.capabilities())
            return
        if path == lib.API_PREFIX + "/applications":
            self._no_query(query)
            self.audit_action = "applications.list"
            self._send_json(200, self.automation_server.backend.applications())
            return
        if path == lib.API_PREFIX + "/windows":
            self._no_query(query)
            self.audit_action = "windows.list"
            self._send_json(200, self.automation_server.backend.windows())
            return
        if path == lib.API_PREFIX + "/clipboard":
            self._no_query(query)
            self.audit_action = "clipboard.read"
            data = self.automation_server.backend.get_clipboard()
            self.audit_details = {"bytes": len(data)}
            self._send_bytes(200, data, "text/plain; charset=utf-8")
            return
        if path == lib.API_PREFIX + "/ssh-keys":
            self._no_query(query)
            self.audit_action = "ssh_keys.list"
            self._send_json(200, self.automation_server.backend.list_ssh_keys())
            return
        job_match = re.fullmatch(re.escape(lib.API_PREFIX) + r"/jobs/([0-9a-f]{32})", path)
        if job_match:
            self._no_query(query)
            self.audit_action = "job.read"
            self.audit_details = {"job_id": job_match.group(1)}
            self._send_json(200, self.automation_server.backend.get_job(job_match.group(1)))
            return
        output_match = re.fullmatch(
            re.escape(lib.API_PREFIX) + r"/jobs/([0-9a-f]{32})/output", path
        )
        if output_match:
            self.audit_action = "job.output.read"
            self._job_output(output_match.group(1), query)
            return
        if path.startswith(lib.API_PREFIX + "/files/"):
            self.audit_action = "file.read"
            self._file_response(path, query, root="desktop")
            return
        if path.startswith(lib.API_PREFIX + "/projects/"):
            self.audit_action = "project_file.read"
            self._file_response(path, query, root="projects")
            return
        self.audit_action = "route.not_found"
        raise RequestError("not_found", "Endpoint not found.", 404)

    def _head(self, path: str, query: str) -> None:
        if path.startswith(lib.API_PREFIX + "/files/"):
            self.audit_action = "file.head"
            self._file_response(path, query, root="desktop")
            return
        if path.startswith(lib.API_PREFIX + "/projects/"):
            self.audit_action = "project_file.head"
            self._file_response(path, query, root="projects")
            return
        self.audit_action = "method.reject"
        raise RequestError("method_not_allowed", "Method not allowed.", 405)

    def _post(self, path: str, query: str) -> None:
        self._no_query(query)
        if path == lib.API_PREFIX + "/pairing/requests":
            self.audit_action = "pairing.request"
            body = self._json_body(8192)
            self._send_json(201, self.automation_server.backend.request_pairing(body))
            return
        pairing_poll = re.fullmatch(
            re.escape(lib.API_PREFIX) + r"/pairing/requests/([0-9a-f]{32})/poll",
            path,
        )
        if pairing_poll:
            self.audit_action = "pairing.poll"
            body = self._json_body(8192)
            self._send_json(
                200,
                self.automation_server.backend.poll_pairing(pairing_poll.group(1), body),
            )
            return
        if path in (lib.API_PREFIX + "/commands", lib.API_PREFIX + "/shell"):
            shell = path.endswith("/shell")
            self.audit_action = "shell.submit" if shell else "command.submit"
            body = self._json_body(lib.MAX_JSON_BODY_BYTES)
            payload = self.automation_server.backend.submit_command(
                body, shell=shell, request_id=self.request_id
            )
            job = payload["job"]
            self.audit_details = {"job_id": job["id"], "kind": job["kind"]}
            self._send_json(202, payload)
            return
        if path == lib.API_PREFIX + "/ssh-keys":
            self.audit_action = "ssh_key.add"
            payload = self.automation_server.backend.add_ssh_key(self._json_body(20 * 1024))
            self.audit_details = {"key_id": payload["key"]["id"], "created": payload["created"]}
            self._send_json(201 if payload["created"] else 200, payload)
            return
        ssh_remove = re.fullmatch(
            re.escape(lib.API_PREFIX) + r"/ssh-keys/([0-9a-f]{32})/remove", path
        )
        if ssh_remove:
            self.audit_action = "ssh_key.remove"
            self._require_empty_json()
            self.audit_details = {"key_id": ssh_remove.group(1)}
            self._send_json(200, self.automation_server.backend.remove_ssh_key(ssh_remove.group(1)))
            return
        if path == lib.API_PREFIX + "/screenshot":
            self.audit_action = "screenshot.capture"
            body = self._json_body(8192)
            if set(body) - {"filename"}:
                raise RequestError(
                    "invalid_screenshot", "Screenshot accepts only filename.", 400
                )
            image, stored = self.automation_server.backend.screenshot(body.get("filename"))
            self.audit_details = {"bytes": len(image), "stored": stored is not None}
            if stored is None:
                self._send_bytes(
                    200,
                    image,
                    "image/png",
                    headers={"Content-Disposition": 'inline; filename="screenshot.png"'},
                )
            else:
                self.audit_details["path"] = stored.path
                metadata = stored.metadata()
                metadata["content_type"] = "image/png"
                self._send_json(201, {"file": metadata})
            return
        cancel_match = re.fullmatch(
            re.escape(lib.API_PREFIX) + r"/jobs/([0-9a-f]{32})/cancel", path
        )
        if cancel_match:
            self.audit_action = "job.cancel"
            self._require_empty_json()
            job_id = cancel_match.group(1)
            self.audit_details = {"job_id": job_id}
            self._send_json(200, self.automation_server.backend.cancel_job(job_id))
            return
        app_match = re.fullmatch(
            re.escape(lib.API_PREFIX) + r"/applications/([a-z][a-z0-9-]{0,63})/(start|stop)",
            path,
        )
        if app_match:
            app_id, operation = app_match.groups()
            self.audit_action = "application." + operation
            self._require_empty_json()
            self.audit_details = {"application_id": app_id}
            payload = (
                self.automation_server.backend.start_application(app_id)
                if operation == "start"
                else self.automation_server.backend.stop_application(app_id)
            )
            self._send_json(200, payload)
            return
        window_match = re.fullmatch(
            re.escape(lib.API_PREFIX) + r"/windows/(0x[0-9a-fA-F]{1,16})/state", path
        )
        if window_match:
            self.audit_action = "window.state.update"
            body = self._json_body(4096)
            if set(body) != {"state"}:
                raise RequestError(
                    "invalid_window_state", "Window state requires only state.", 400
                )
            if body["state"] not in ("minimized", "maximized", "normal"):
                raise RequestError(
                    "invalid_window_state",
                    "state must be minimized, maximized, or normal.",
                    400,
                )
            xid = window_match.group(1)
            self.audit_details = {"window_id": xid.lower(), "state": body["state"]}
            self._send_json(
                200,
                self.automation_server.backend.set_window_state(xid, body["state"]),
            )
            return
        self.audit_action = "route.not_found"
        raise RequestError("not_found", "Endpoint not found.", 404)

    def _put(self, path: str, query: str) -> None:
        self._no_query(query)
        if path == lib.API_PREFIX + "/clipboard":
            self.audit_action = "clipboard.write"
            data = self._raw_body(lib.MAX_CLIPBOARD_BYTES, content_type="text/plain")
            payload = self.automation_server.backend.set_clipboard(data)
            self.audit_details = {"bytes": len(data)}
            self._send_json(200, payload)
            return
        if path.startswith(lib.API_PREFIX + "/files/"):
            self.audit_action = "file.write"
            relative = _decode_file_path(path[len(lib.API_PREFIX + "/files/") :])
            data = self._raw_body(lib.MAX_FILE_BYTES)
            value = self.automation_server.backend.files.write(
                relative,
                data,
                if_match=self._single_header("If-Match"),
                if_none_match=self._single_header("If-None-Match"),
            )
            self.audit_details = {
                "path": relative,
                "bytes": len(data),
                "created": value.created,
            }
            self._send_json(201 if value.created else 200, {"file": value.metadata()})
            return
        if path.startswith(lib.API_PREFIX + "/projects/"):
            self.audit_action = "project_file.write"
            relative = _decode_file_path(path[len(lib.API_PREFIX + "/projects/") :])
            data = self._raw_body(lib.MAX_FILE_BYTES)
            value = self.automation_server.backend.project_files.write(
                relative,
                data,
                if_match=self._single_header("If-Match"),
                if_none_match=self._single_header("If-None-Match"),
            )
            self.audit_details = {
                "path": relative,
                "root": "projects",
                "bytes": len(data),
                "created": value.created,
            }
            self._send_json(201 if value.created else 200, {"file": value.metadata()})
            return
        self.audit_action = "route.not_found"
        raise RequestError("not_found", "Endpoint not found.", 404)

    def _file_response(self, path: str, query: str, *, root: str) -> None:
        self._no_query(query)
        route = "/files/" if root == "desktop" else "/projects/"
        relative = _decode_file_path(path[len(lib.API_PREFIX + route) :])
        store = (
            self.automation_server.backend.files
            if root == "desktop"
            else self.automation_server.backend.project_files
        )
        value = store.read(relative)
        self.audit_details = {
            "path": relative,
            "root": root,
            "file_bytes": value.size,
        }
        if_none_match = self._single_header("If-None-Match")
        if if_none_match is not None:
            if not _valid_etag_condition(if_none_match):
                raise RequestError("invalid_precondition", "If-None-Match is invalid.", 400)
            if _etag_matches(if_none_match, value.etag):
                self._send_not_modified(value.etag)
                return
        range_header = self._single_header("Range")
        if_range = self._single_header("If-Range")
        if if_range is not None and if_range != value.etag:
            range_header = None
        try:
            selected = parse_range(range_header, value.size)
        except FileError as exc:
            if exc.status == 416:
                # Give well-behaved clients enough information to retry.
                self._send_json(
                    416,
                    {"code": exc.code, "message": exc.message, "request_id": self.request_id},
                    headers={"Content-Range": "bytes */%d" % value.size},
                )
                return
            raise
        headers = {"ETag": value.etag, "Accept-Ranges": "bytes"}
        if selected is None:
            body = value.data
            status = 200
        else:
            start, end = selected
            body = value.data[start : end + 1]
            status = 206
            headers["Content-Range"] = "bytes %d-%d/%d" % (start, end, value.size)
            self.audit_details["response_bytes"] = len(body)
        self._send_bytes(status, body, "application/octet-stream", headers=headers)

    def _job_output(self, job_id: str, query_string: str) -> None:
        query = parse_qs(query_string, keep_blank_values=True)
        if set(query) - {"stream", "cursor", "limit"}:
            raise RequestError("invalid_query", "Unknown output query parameter.", 400)
        stream = _one_query_string(query, "stream", "stdout")
        cursor = _one_query_integer(query, "cursor", 0)
        limit = _one_query_integer(query, "limit", 65536)
        if stream not in ("stdout", "stderr"):
            raise RequestError("invalid_stream", "stream must be stdout or stderr.", 400)
        if cursor < 0 or not 1 <= limit <= MAX_OUTPUT_PAGE_BYTES:
            raise RequestError("invalid_query", "cursor or limit is outside the allowed range.", 400)
        self.audit_details = {"job_id": job_id, "stream": stream, "cursor": cursor, "limit": limit}
        self._send_json(
            200,
            self.automation_server.backend.job_output(job_id, stream, cursor, limit),
        )

    def _require_empty_json(self) -> None:
        if self._json_body(4096):
            raise RequestError("unknown_field", "This operation accepts no request fields.", 400)

    def _json_body(self, maximum: int) -> dict[str, Any]:
        content_type = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise RequestError("unsupported_media_type", "This request requires application/json.", 415)
        raw = self._read_body(maximum)
        if not raw:
            raise RequestError("invalid_json", "The request body must be a JSON object.", 400)
        try:
            value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            raise RequestError("invalid_json", "The request body must be valid JSON.", 400) from None
        if not isinstance(value, dict):
            raise RequestError("invalid_json", "The request body must be a JSON object.", 400)
        return value

    def _raw_body(self, maximum: int, *, content_type: str | None = None) -> bytes:
        if content_type is not None:
            header = self.headers.get("Content-Type") or ""
            media_type, _, parameters = header.partition(";")
            if media_type.strip().lower() != content_type:
                raise RequestError(
                    "unsupported_media_type", "This request requires text/plain UTF-8.", 415
                )
            if parameters:
                match = re.fullmatch(r"\s*charset\s*=\s*[\"']?utf-8[\"']?\s*", parameters, re.I)
                if not match:
                    raise RequestError(
                        "unsupported_media_type", "Clipboard text must use UTF-8.", 415
                    )
        return self._read_body(maximum)

    def _read_body(self, maximum: int) -> bytes:
        if self.headers.get("Transfer-Encoding"):
            raise RequestError("length_required", "A Content-Length header is required.", 411)
        lengths = self.headers.get_all("Content-Length") or []
        if len(lengths) != 1:
            raise RequestError("length_required", "A single Content-Length header is required.", 411)
        try:
            length = int(lengths[0])
        except ValueError:
            raise RequestError("invalid_length", "Content-Length is invalid.", 400) from None
        if length < 0:
            raise RequestError("invalid_length", "Content-Length is invalid.", 400)
        if length > maximum:
            raise RequestError("body_too_large", "The request body is too large.", 413)
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise RequestError("incomplete_body", "The request body was incomplete.", 400)
        return raw

    def _single_header(self, name: str) -> str | None:
        values = self.headers.get_all(name) or []
        if len(values) > 1:
            raise RequestError("invalid_header", "%s must appear at most once." % name, 400)
        value = values[0] if values else None
        if value is not None and len(value) > 1024:
            raise RequestError("invalid_header", "%s is too long." % name, 400)
        return value

    def do_GET(self) -> None:
        self._handle()

    def do_HEAD(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def do_PUT(self) -> None:
        self._handle()

    def do_DELETE(self) -> None:
        self._handle()

    def do_PATCH(self) -> None:
        self._handle()

    def do_OPTIONS(self) -> None:
        # Deliberately no CORS negotiation.
        self._handle()

    def do_TRACE(self) -> None:
        self._handle()

    def do_CONNECT(self) -> None:
        self._handle()


def _decode_file_path(raw: str) -> str:
    if not raw or re.search(r"%(?![0-9A-Fa-f]{2})", raw):
        raise RequestError("invalid_path", "The Desktop file path is invalid.", 400)
    try:
        value = unquote_to_bytes(raw).decode("utf-8")
    except UnicodeDecodeError:
        raise RequestError("invalid_path", "The Desktop file path must be UTF-8.", 400) from None
    return lib.DesktopFileStore.require_relative_path(value)


def _one_query_string(query: dict[str, list[str]], name: str, default: str) -> str:
    values = query.get(name)
    if values is None:
        return default
    if len(values) != 1 or not values[0] or len(values[0]) > 64:
        raise RequestError("invalid_query", "%s is invalid." % name, 400)
    return values[0]


def _one_query_integer(query: dict[str, list[str]], name: str, default: int) -> int:
    value = _one_query_string(query, name, str(default))
    if not value.isdigit() or len(value) > 10:
        raise RequestError("invalid_query", "%s must be a non-negative integer." % name, 400)
    return int(value)


def _valid_etag_condition(value: str) -> bool:
    if value.strip() == "*":
        return True
    return bool(value) and len(value) <= 1024 and all(
        re.fullmatch(r'(?:W/)?"[A-Za-z0-9._:-]{1,160}"', item.strip())
        for item in value.split(",")
    )


def _etag_matches(condition: str, etag: str) -> bool:
    values = [item.strip() for item in condition.split(",")]
    return "*" in values or etag in values or "W/" + etag in values


def create_server(
    host: str = lib.DEFAULT_HOST,
    port: int = lib.DEFAULT_PORT,
    *,
    backend: lib.AutomationBackend | None = None,
    token_provider: lib.TokenProvider | None = None,
    audit: lib.AuditLogger | None = None,
) -> AutomationHTTPServer:
    selected_backend = backend or lib.AutomationBackend()
    selected_audit = audit or lib.AuditLogger()
    selected_backend.set_audit_logger(selected_audit)
    return AutomationHTTPServer(
        (host, port),
        selected_backend,
        token_provider or lib.TokenProvider(),
        selected_audit,
    )


def serve_until_stopped(server: AutomationHTTPServer) -> None:
    """Serve until interrupted, closing all separately-sessioned job groups."""
    stop_requested = threading.Event()

    def request_shutdown() -> None:
        stop_requested.wait()
        server.shutdown()

    watcher = threading.Thread(
        target=request_shutdown,
        name="automation-signal-shutdown",
        daemon=True,
    )
    watcher.start()

    previous_handlers: dict[signal.Signals, Any] = {}

    def handle_signal(_number: int, _frame: Any) -> None:
        # A pre-existing helper invokes BaseServer.shutdown(), because calling
        # it directly from the serve_forever thread would deadlock.
        stop_requested.set()

    if threading.current_thread() is threading.main_thread():
        for signal_number in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signal_number] = signal.getsignal(signal_number)
            signal.signal(signal_number, handle_signal)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        stop_requested.set()
    finally:
        stop_requested.set()
        server.server_close()
        for signal_number, previous in previous_handlers.items():
            signal.signal(signal_number, previous)


def main() -> int:
    try:
        port = int(os.environ.get("AUTOMATION_PORT", str(lib.DEFAULT_PORT)))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        print("AUTOMATION_PORT must be between 1 and 65535", file=sys.stderr)
        return 2
    token_provider = lib.TokenProvider(
        os.environ.get("AUTOMATION_TOKEN_FILE", lib.DEFAULT_TOKEN_FILE)
    )
    # Fail closed at startup and re-read on each request so an atomic token
    # rotation takes effect without a service restart.
    try:
        token_provider._read()
    except lib.AutomationError as exc:
        print("automation startup failed: %s" % exc.message, file=sys.stderr)
        return 1
    backend = lib.AutomationBackend(
        desktop_root=os.environ.get("AUTOMATION_DESKTOP_ROOT", lib.DEFAULT_DESKTOP_ROOT),
        source_project=os.environ.get("VIBESTACK_SOURCE_PROJECT") or None,
        job_directory=os.environ.get("AUTOMATION_JOB_DIR", lib.DEFAULT_JOB_DIRECTORY),
        session_env_file=os.environ.get(
            "AUTOMATION_SESSION_ENV_FILE", lib.DEFAULT_SESSION_ENV_FILE
        ),
        xdg_runtime_dir=os.environ.get(
            "AUTOMATION_XDG_RUNTIME_DIR", lib.DEFAULT_XDG_RUNTIME_DIR
        ),
        applications_file=os.environ.get("AUTOMATION_APPLICATIONS_FILE"),
    )
    audit = lib.AuditLogger(
        os.environ.get("AUTOMATION_AUDIT_LOG", lib.DEFAULT_AUDIT_LOG)
    )
    server = create_server(
        port=port,
        backend=backend,
        token_provider=token_provider,
        audit=audit,
    )
    serve_until_stopped(server)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
