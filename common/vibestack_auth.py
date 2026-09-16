"""Shared, file-backed identity and client-pairing state for a workspace.

The setup and automation services are separate processes.  This module keeps
their small shared state serialized with flock and atomic replacement.  Only
credential hashes survive delivery; the high-entropy polling secret is also
stored only as a hash.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator


PAIRING_TTL_SECONDS = 600
MAX_PENDING_PAIRINGS = 8
MAX_CLIENTS = 128
CODE_RE = re.compile(r"^[A-Z2-9]{4}-[A-Z2-9]{4}$")
ID_RE = re.compile(r"^[0-9a-f]{32}$")
LABEL_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,80}$")
PERMISSIONS = frozenset({"workspace"})


class ClientAuthError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _now() -> int:
    return int(time.time())


def _iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


class WorkspaceClientStore:
    """Persistent workspace identity, pairings, and individually revocable clients."""

    def __init__(self, root: str = "/home/vibe/.vibestack") -> None:
        self.root = os.path.realpath(os.path.abspath(root))
        self.lock_path = os.path.join(self.root, "client-auth.lock")
        self.identity_path = os.path.join(self.root, "identity")
        self.key_path = os.path.join(self.root, "pairing.key")
        self.pairings_path = os.path.join(self.root, "pairing-requests.json")
        self.clients_path = os.path.join(self.root, "client-credentials.json")

    def identity(self) -> str:
        with self._locked():
            value = self._read_secret(self.identity_path, minimum=32, maximum=64)
            if value is None:
                value = uuid.uuid4().hex
                self._atomic_text(self.identity_path, value + "\n", 0o600)
            if not ID_RE.fullmatch(value):
                raise ClientAuthError("identity_unavailable", "Workspace identity failed a safety check.", 503)
            return value

    def request_pairing(self, label: object, permissions: object) -> dict[str, Any]:
        if not isinstance(label, str) or not LABEL_RE.fullmatch(label):
            raise ClientAuthError("invalid_device_label", "device_label must be 1 to 80 printable characters.")
        if permissions != ["workspace"]:
            raise ClientAuthError("invalid_permissions", "A workspace pairing must request only workspace access.")
        now = _now()
        with self._locked():
            state = self._load(self.pairings_path, "requests")
            requests = [item for item in state["requests"] if item.get("expires_at", 0) > now and item.get("status") != "completed"]
            pending = [item for item in requests if item.get("status") == "pending"]
            if len(pending) >= MAX_PENDING_PAIRINGS:
                raise ClientAuthError("pairing_rate_limited", "Too many pairing requests are pending.", 429)
            code = self._new_code({item["code"] for item in requests})
            pairing_id = uuid.uuid4().hex
            polling_secret = secrets.token_urlsafe(32)
            request = {
                "id": pairing_id,
                "code": code,
                "device_label": label,
                "permissions": ["workspace"],
                "polling_secret_hash": _digest(polling_secret),
                "created_at": now,
                "expires_at": now + PAIRING_TTL_SECONDS,
                "status": "pending",
            }
            requests.append(request)
            self._save(self.pairings_path, "requests", requests)
        return {
            "pairing_id": pairing_id,
            "verification_code": code,
            "polling_secret": polling_secret,
            "expires_at": _iso(now + PAIRING_TTL_SECONDS),
            "interval_seconds": 2,
        }

    def poll(self, pairing_id: object, polling_secret: object) -> dict[str, Any]:
        if not isinstance(pairing_id, str) or not ID_RE.fullmatch(pairing_id):
            raise ClientAuthError("pairing_not_found", "The pairing request does not exist.", 404)
        if not isinstance(polling_secret, str) or not 32 <= len(polling_secret) <= 128:
            raise ClientAuthError("pairing_not_found", "The pairing request does not exist.", 404)
        now = _now()
        with self._locked():
            state = self._load(self.pairings_path, "requests")
            request = next((item for item in state["requests"] if item.get("id") == pairing_id), None)
            supplied = _digest(polling_secret)
            expected = request.get("polling_secret_hash", "") if request else ""
            if request is None or not hmac.compare_digest(supplied, expected):
                raise ClientAuthError("pairing_not_found", "The pairing request does not exist.", 404)
            if request["expires_at"] <= now:
                request["status"] = "expired"
                self._save(self.pairings_path, "requests", state["requests"])
                raise ClientAuthError("pairing_expired", "The pairing request expired.", 410)
            if request["status"] == "pending":
                return {"status": "pending", "expires_at": _iso(request["expires_at"])}
            if request["status"] == "completed":
                raise ClientAuthError("credential_already_delivered", "The client credential was already delivered.", 410)
            if request["status"] != "approved":
                raise ClientAuthError("pairing_denied", "The pairing request was denied.", 403)

            key = self._pairing_key()
            credential = "vsw_" + hmac.new(key, (pairing_id + ":" + polling_secret).encode("utf-8"), hashlib.sha256).hexdigest()
            clients = self._load(self.clients_path, "clients")
            if len(clients["clients"]) >= MAX_CLIENTS:
                raise ClientAuthError("client_limit_reached", "The workspace client limit was reached.", 409)
            client_id = uuid.uuid4().hex
            clients["clients"].append({
                "id": client_id,
                "device_label": request["device_label"],
                "permissions": list(request["permissions"]),
                "credential_hash": _digest(credential),
                "created_at": now,
                "revoked_at": None,
            })
            self._save(self.clients_path, "clients", clients["clients"])
            request["status"] = "completed"
            request["client_id"] = client_id
            request.pop("polling_secret_hash", None)
            self._save(self.pairings_path, "requests", state["requests"])
            return {
                "status": "approved",
                "client_id": client_id,
                "credential": credential,
                "permissions": list(request["permissions"]),
            }

    def approve(self, code: object) -> dict[str, Any]:
        if not isinstance(code, str) or not CODE_RE.fullmatch(code):
            raise ClientAuthError("pairing_not_found", "The pairing request does not exist.", 404)
        now = _now()
        with self._locked():
            state = self._load(self.pairings_path, "requests")
            request = next((item for item in state["requests"] if item.get("code") == code), None)
            if request is None:
                raise ClientAuthError("pairing_not_found", "The pairing request does not exist.", 404)
            if request["expires_at"] <= now:
                request["status"] = "expired"
                self._save(self.pairings_path, "requests", state["requests"])
                raise ClientAuthError("pairing_expired", "The pairing request expired.", 410)
            if request["status"] != "pending":
                raise ClientAuthError("pairing_not_pending", "The pairing request is no longer pending.", 409)
            request["status"] = "approved"
            request["approved_at"] = now
            self._save(self.pairings_path, "requests", state["requests"])
            return self._public_pairing(request)

    def deny(self, code: object) -> dict[str, Any]:
        if not isinstance(code, str) or not CODE_RE.fullmatch(code):
            raise ClientAuthError("pairing_not_found", "The pairing request does not exist.", 404)
        with self._locked():
            state = self._load(self.pairings_path, "requests")
            request = next((item for item in state["requests"] if item.get("code") == code), None)
            if request is None or request.get("status") != "pending":
                raise ClientAuthError("pairing_not_found", "The pending pairing request does not exist.", 404)
            request["status"] = "denied"
            request.pop("polling_secret_hash", None)
            self._save(self.pairings_path, "requests", state["requests"])
            return self._public_pairing(request)

    def authenticate(self, credential: str) -> bool:
        supplied = _digest(credential)
        try:
            with self._locked():
                clients = self._load(self.clients_path, "clients")["clients"]
        except ClientAuthError:
            return False
        matched = False
        for client in clients:
            expected = client.get("credential_hash", "") if client.get("revoked_at") is None else ""
            matched = hmac.compare_digest(supplied, expected) or matched
        return matched

    def admin_state(self) -> dict[str, Any]:
        now = _now()
        with self._locked():
            pairings = self._load(self.pairings_path, "requests")["requests"]
            clients = self._load(self.clients_path, "clients")["clients"]
        return {
            "pending": [self._public_pairing(item) for item in pairings if item.get("status") == "pending" and item.get("expires_at", 0) > now],
            "clients": [self._public_client(item) for item in clients],
        }

    def revoke(self, client_id: object) -> dict[str, Any]:
        if not isinstance(client_id, str) or not ID_RE.fullmatch(client_id):
            raise ClientAuthError("client_not_found", "The client does not exist.", 404)
        with self._locked():
            state = self._load(self.clients_path, "clients")
            client = next((item for item in state["clients"] if item.get("id") == client_id), None)
            if client is None:
                raise ClientAuthError("client_not_found", "The client does not exist.", 404)
            if client.get("revoked_at") is None:
                client["revoked_at"] = _now()
                self._save(self.clients_path, "clients", state["clients"])
            return self._public_client(client)

    @staticmethod
    def _public_pairing(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "pairing_id": item["id"],
            "verification_code": item["code"],
            "device_label": item["device_label"],
            "permissions": list(item["permissions"]),
            "status": item["status"],
            "expires_at": _iso(item["expires_at"]),
        }

    @staticmethod
    def _public_client(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "client_id": item["id"],
            "device_label": item["device_label"],
            "permissions": list(item["permissions"]),
            "created_at": _iso(item["created_at"]),
            "revoked_at": _iso(item["revoked_at"]) if item.get("revoked_at") else None,
        }

    def _pairing_key(self) -> bytes:
        value = self._read_secret(self.key_path, minimum=64, maximum=64)
        if value is None:
            value = secrets.token_hex(32)
            self._atomic_text(self.key_path, value + "\n", 0o600)
        try:
            return bytes.fromhex(value)
        except ValueError:
            raise ClientAuthError("pairing_unavailable", "Pairing state failed a safety check.", 503) from None

    @staticmethod
    def _new_code(existing: set[str]) -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        for _attempt in range(100):
            raw = "".join(secrets.choice(alphabet) for _ in range(8))
            code = raw[:4] + "-" + raw[4:]
            if code not in existing:
                return code
        raise ClientAuthError("pairing_unavailable", "A verification code could not be allocated.", 503)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        os.makedirs(self.root, mode=0o700, exist_ok=True)
        info = os.lstat(self.root)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
            raise ClientAuthError("client_state_unsafe", "Client state failed a safety check.", 503)
        flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self.lock_path, flags, 0o600)
        except OSError as exc:
            raise ClientAuthError("client_state_unavailable", "Client state is unavailable.", 503) from exc
        try:
            lock_info = os.fstat(fd)
            if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.getuid() or lock_info.st_nlink != 1 or stat.S_IMODE(lock_info.st_mode) & 0o077:
                raise ClientAuthError("client_state_unsafe", "Client state failed a safety check.", 503)
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def _load(self, path: str, key: str) -> dict[str, Any]:
        try:
            raw = self._read_regular(path, maximum=256 * 1024)
        except FileNotFoundError:
            return {"version": 1, key: []}
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ClientAuthError("client_state_invalid", "Client state is invalid.", 503) from exc
        if not isinstance(value, dict) or value.get("version") != 1 or set(value) != {"version", key} or not isinstance(value[key], list):
            raise ClientAuthError("client_state_invalid", "Client state is invalid.", 503)
        return value

    def _save(self, path: str, key: str, values: list[dict[str, Any]]) -> None:
        self._atomic_text(path, json.dumps({"version": 1, key: values}, separators=(",", ":")) + "\n", 0o600)

    def _read_secret(self, path: str, *, minimum: int, maximum: int) -> str | None:
        try:
            raw = self._read_regular(path, maximum=maximum + 2)
        except FileNotFoundError:
            return None
        try:
            value = raw.decode("ascii").strip()
        except UnicodeError as exc:
            raise ClientAuthError("client_state_unavailable", "Client state is unavailable.", 503) from exc
        if not minimum <= len(value) <= maximum:
            raise ClientAuthError("client_state_invalid", "Client state is invalid.", 503)
        return value

    @staticmethod
    def _read_regular(path: str, *, maximum: int) -> bytes:
        flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags)
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise ClientAuthError("client_state_unavailable", "Client state is unavailable.", 503) from exc
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) & 0o077
                or info.st_size > maximum
            ):
                raise ClientAuthError("client_state_unsafe", "Client state failed a safety check.", 503)
            chunks: list[bytes] = []
            remaining = maximum + 1
            while remaining:
                chunk = os.read(fd, min(remaining, 64 * 1024))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            if len(data) > maximum:
                raise ClientAuthError("client_state_unsafe", "Client state failed a safety check.", 503)
            return data
        finally:
            os.close(fd)

    def _atomic_text(self, path: str, value: str, mode: int) -> None:
        fd, temporary = tempfile.mkstemp(prefix=".vibestack-client-", dir=self.root)
        try:
            os.fchmod(fd, mode)
            data = value.encode("utf-8")
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short write")
                view = view[written:]
            os.fsync(fd)
            os.close(fd)
            fd = -1
            os.replace(temporary, path)
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if fd >= 0:
                os.close(fd)
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
