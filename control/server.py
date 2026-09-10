#!/usr/bin/env python3
"""Dependency-free HTTP service for the VibeStack desktop shell."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import controllib as lib  # noqa: E402


MAX_BODY_BYTES = 4096
MUTATION_WAIT_SECONDS = 0
HOST_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class RequestError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


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
        raise ValueError("invalid authority")
    if port == 0:
        raise ValueError("invalid authority")
    return parsed.hostname.lower(), port


def _host_allowed(host_name: str) -> bool:
    if host_name in ("localhost", "127.0.0.1", "::1"):
        return True
    labels = host_name.split(".")
    return (
        len(labels) >= 4
        and labels[-2:] == ["ts", "net"]
        and all(HOST_LABEL_RE.fullmatch(label) for label in labels[:-2])
    )


def validate_request_source(handler: BaseHTTPRequestHandler) -> None:
    """Require a VibeStack Host and reject cross-origin browser requests."""

    hosts = handler.headers.get_all("Host") or []
    if len(hosts) != 1:
        raise RequestError("invalid_host", "A single valid Host header is required.", 400)
    try:
        host_name, host_port = _authority(hosts[0])
    except ValueError:
        raise RequestError("invalid_host", "A single valid Host header is required.", 400)
    if not _host_allowed(host_name):
        raise RequestError(
            "host_not_allowed", "The request Host is not allowed.", 421
        )

    fetch_sites = handler.headers.get_all("Sec-Fetch-Site") or []
    if len(fetch_sites) > 1:
        raise RequestError("invalid_request", "Duplicate fetch metadata is not allowed.", 400)
    fetch_site = fetch_sites[0].strip().lower() if fetch_sites else ""
    if fetch_site in ("cross-site", "same-site"):
        raise RequestError("cross_origin", "Cross-origin mutations are not allowed.", 403)
    if fetch_site not in ("", "none", "same-origin"):
        raise RequestError("invalid_request", "Invalid fetch metadata.", 400)

    origins = handler.headers.get_all("Origin") or []
    if not origins:
        return
    if len(origins) != 1 or origins[0] == "null":
        raise RequestError("cross_origin", "Cross-origin mutations are not allowed.", 403)

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
        raise RequestError("cross_origin", "Cross-origin mutations are not allowed.", 403)
    try:
        origin_port = parsed.port
    except ValueError:
        raise RequestError("cross_origin", "Cross-origin mutations are not allowed.", 403)
    default_port = 443 if parsed.scheme == "https" else 80
    effective_origin_port = origin_port or default_port
    names_match = parsed.hostname.lower() == host_name
    # With no Host port, both HTTP's and HTTPS's implicit default authority
    # are valid; the TLS terminator is intentionally outside this service.
    ports_match = (
        (host_port is None and (origin_port is None or origin_port == default_port))
        or host_port == effective_origin_port
    )
    if not names_match or not ports_match:
        raise RequestError("cross_origin", "Cross-origin mutations are not allowed.", 403)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


class ControlHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], backend: lib.ControlBackend):
        super().__init__(address, Handler)
        self.backend = backend
        self.mutation_lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    server_version = "VibeStackControl/1"
    sys_version = ""

    @property
    def control_server(self) -> ControlHTTPServer:
        return self.server  # type: ignore[return-value]

    def log_message(self, fmt: str, *args: Any) -> None:
        # BaseHTTPRequestHandler's default access line contains the complete,
        # unbounded request target. Query strings are not part of the control
        # service's useful diagnostics and may contain sensitive caller data.
        return

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _error(self, error: RequestError | lib.ControlError) -> None:
        self._send_json(error.status, {"code": error.code, "message": error.message})

    def _json_body(self) -> dict[str, Any]:
        content_types = self.headers.get_all("Content-Type") or []
        if len(content_types) > 1:
            raise RequestError(
                "invalid_header", "Content-Type must appear at most once.", 400
            )
        if not content_types:
            raise RequestError(
                "unsupported_media_type", "Mutation requests require application/json.", 415
            )
        content_type_parts = [part.strip() for part in content_types[0].split(";")]
        if not content_type_parts or content_type_parts[0].lower() != "application/json":
            raise RequestError(
                "unsupported_media_type", "Mutation requests require application/json.", 415
            )
        for parameter in content_type_parts[1:]:
            name, separator, value = parameter.partition("=")
            if (
                not separator
                or name.strip().lower() != "charset"
                or value.strip().strip('"').lower() not in ("utf-8", "utf8")
            ):
                raise RequestError(
                    "unsupported_media_type",
                    "Mutation JSON must use UTF-8.",
                    415,
                )

        if self.headers.get_all("Transfer-Encoding"):
            raise RequestError("length_required", "A Content-Length header is required.", 411)
        lengths = self.headers.get_all("Content-Length") or []
        if len(lengths) > 1:
            raise RequestError(
                "invalid_header", "Content-Length must appear exactly once.", 400
            )
        if not lengths:
            raise RequestError("length_required", "A Content-Length header is required.", 411)
        raw_length = lengths[0]
        try:
            if (
                not raw_length
                or not raw_length.isascii()
                or not raw_length.isdecimal()
                or len(raw_length) > 19
            ):
                raise ValueError
            length = int(raw_length, 10)
        except (TypeError, ValueError):
            raise RequestError("invalid_length", "Content-Length is invalid.", 400)
        if length > MAX_BODY_BYTES:
            raise RequestError("body_too_large", "Request body is too large.", 413)
        if length == 0:
            raise RequestError("invalid_json", "Request body must be valid JSON.", 400)
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise RequestError("incomplete_body", "The request body was incomplete.", 400)
        try:
            payload = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=lambda _value: (_ for _ in ()).throw(
                    ValueError("non-finite JSON number")
                ),
            )
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            raise RequestError("invalid_json", "Request body must be valid JSON.", 400)
        if not isinstance(payload, dict):
            raise RequestError("invalid_json", "Request body must be a JSON object.", 400)
        return payload

    @staticmethod
    def _one_query_value(
        query: dict[str, list[str]], name: str, default: int | None
    ) -> int | None:
        if name not in query:
            return default
        values = query[name]
        if len(values) != 1 or len(values[0]) > 20 or not values[0].isdigit():
            raise RequestError("invalid_query", "%s must be an integer." % name, 400)
        return int(values[0])

    def _logs(self, path: str, query_string: str) -> None:
        prefix = "/api/v1/logs/"
        service = path[len(prefix) :]
        lib.require_service(service)
        query = parse_qs(query_string, keep_blank_values=True)
        if set(query) - {"cursor", "limit"}:
            raise RequestError("invalid_query", "Unknown log query parameter.", 400)
        cursor = self._one_query_value(query, "cursor", None)
        limit_value = self._one_query_value(query, "limit", lib.DEFAULT_LOG_LIMIT)
        assert limit_value is not None
        if not 1 <= limit_value <= lib.MAX_LOG_LIMIT:
            raise RequestError(
                "invalid_query",
                "limit must be between 1 and %d." % lib.MAX_LOG_LIMIT,
                400,
            )
        self._send_json(
            200, self.control_server.backend.service_logs(service, cursor, limit_value)
        )

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        try:
            validate_request_source(self)
            if parsed.fragment:
                raise RequestError("invalid_path", "The request path is invalid.", 400)
            if parsed.path == "/api/v1/status":
                if parsed.query:
                    raise RequestError("invalid_query", "This endpoint takes no query.", 400)
                self._send_json(200, self.control_server.backend.status_payload())
            elif parsed.path == "/api/v1/display":
                if parsed.query:
                    raise RequestError("invalid_query", "This endpoint takes no query.", 400)
                self._send_json(200, self.control_server.backend.get_display())
            elif parsed.path.startswith("/api/v1/logs/"):
                self._logs(parsed.path, parsed.query)
            else:
                raise RequestError("not_found", "Endpoint not found.", 404)
        except (RequestError, lib.ControlError) as exc:
            self._error(exc)

    def _mutate(self, operation: Any) -> None:
        acquired = self.control_server.mutation_lock.acquire(
            timeout=MUTATION_WAIT_SECONDS
        )
        if not acquired:
            raise RequestError(
                "mutation_in_progress", "Another mutation is already in progress.", 409
            )
        try:
            status, payload = operation()
            self._send_json(status, payload)
        finally:
            self.control_server.mutation_lock.release()

    def do_POST(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        try:
            validate_request_source(self)
            if parsed.fragment:
                raise RequestError("invalid_path", "The request path is invalid.", 400)
            prefix = "/api/v1/services/"
            suffix = "/restart"
            if not path.startswith(prefix) or not path.endswith(suffix):
                raise RequestError("not_found", "Endpoint not found.", 404)
            if parsed.query:
                raise RequestError("invalid_query", "This endpoint takes no query.", 400)
            service = path[len(prefix) : -len(suffix)]
            lib.require_service(service)
            body = self._json_body()
            if body:
                raise RequestError(
                    "unknown_field", "Service restart does not accept request fields.", 400
                )
            self._mutate(
                lambda: (200, self.control_server.backend.restart_service(service))
            )
        except (RequestError, lib.ControlError) as exc:
            self._error(exc)

    def do_PUT(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        try:
            validate_request_source(self)
            if parsed.fragment:
                raise RequestError("invalid_path", "The request path is invalid.", 400)
            if path != "/api/v1/display":
                raise RequestError("not_found", "Endpoint not found.", 404)
            if parsed.query:
                raise RequestError("invalid_query", "This endpoint takes no query.", 400)
            body = self._json_body()
            if set(body) != {"resolution"}:
                raise RequestError(
                    "invalid_display_request",
                    "Display request must contain only resolution.",
                    400,
                )
            resolution = lib.require_resolution(body["resolution"])
            self._mutate(
                lambda: (200, self.control_server.backend.set_display(resolution))
            )
        except (RequestError, lib.ControlError) as exc:
            self._error(exc)

    def _method_not_allowed(self) -> None:
        try:
            validate_request_source(self)
        except RequestError as exc:
            self._error(exc)
            return
        self._send_json(405, {"code": "method_not_allowed", "message": "Method not allowed."})

    def do_DELETE(self) -> None:
        self._method_not_allowed()

    def do_PATCH(self) -> None:
        self._method_not_allowed()

    def do_OPTIONS(self) -> None:
        # Deliberately omit CORS headers; this API is same-origin only.
        self._method_not_allowed()

    def do_HEAD(self) -> None:
        # _send_json suppresses the body for HEAD while preserving the same
        # structured representation's Content-Length.
        self._method_not_allowed()

    def do_TRACE(self) -> None:
        self._method_not_allowed()

    def do_CONNECT(self) -> None:
        self._method_not_allowed()


def create_server(
    host: str = lib.DEFAULT_HOST,
    port: int = lib.DEFAULT_PORT,
    backend: lib.ControlBackend | None = None,
) -> ControlHTTPServer:
    return ControlHTTPServer((host, port), backend or lib.ControlBackend())


def main() -> None:
    port = int(os.environ.get("CONTROL_PORT", str(lib.DEFAULT_PORT)))
    server = create_server(port=port)
    print("[control] listening on 127.0.0.1:%d" % port, flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
