"""Bounded, atomic management of the vibe user's OpenSSH public keys."""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
import stat
import tempfile
import threading
from typing import Any


MAX_KEYS = 64
MAX_FILE_BYTES = 128 * 1024
MAX_KEY_BYTES = 16 * 1024
ALLOWED_KEY_TYPES = frozenset(
    {
        "ssh-ed25519",
        "ecdsa-sha2-nistp256",
        "ecdsa-sha2-nistp384",
        "ecdsa-sha2-nistp521",
        "sk-ssh-ed25519@openssh.com",
        "sk-ecdsa-sha2-nistp256@openssh.com",
        "ssh-rsa",
    }
)
COMMENT_RE = re.compile(r"^[^\x00-\x1f\x7f]{0,256}$")


class SSHKeyError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class SSHKeyStore:
    def __init__(self, home: str = "/home/vibe", persistent_directory: str = "/data/ssh") -> None:
        self.home = os.path.realpath(home)
        home_directory = os.path.join(self.home, ".ssh")
        persistent_directory = os.path.realpath(persistent_directory)
        # vibestack-persist creates this one deliberate link. Resolve only that
        # exact target so a user-created link cannot redirect API-managed keys.
        if os.path.islink(home_directory) and os.path.realpath(home_directory) == persistent_directory:
            self.directory = persistent_directory
        else:
            self.directory = home_directory
        # Keep API-managed keys separate so an existing user-authored
        # authorized_keys file (including options and comments) is preserved.
        self.path = os.path.join(self.directory, "vibestack_authorized_keys")
        self._lock = threading.RLock()

    def list(self) -> dict[str, Any]:
        with self._lock:
            return {"keys": [self._public(item) for item in self._read()]}

    def add(self, value: object) -> dict[str, Any]:
        parsed = self._parse(value)
        with self._lock:
            keys = self._read()
            if any(item["id"] == parsed["id"] for item in keys):
                return {"key": self._public(parsed), "created": False}
            if len(keys) >= MAX_KEYS:
                raise SSHKeyError("ssh_key_limit", "The SSH public-key limit was reached.", 409)
            keys.append(parsed)
            self._write(keys)
            return {"key": self._public(parsed), "created": True}

    def remove(self, key_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{32}", key_id):
            raise SSHKeyError("ssh_key_not_found", "The SSH public key does not exist.", 404)
        with self._lock:
            keys = self._read()
            retained = [item for item in keys if item["id"] != key_id]
            if len(retained) == len(keys):
                raise SSHKeyError("ssh_key_not_found", "The SSH public key does not exist.", 404)
            self._write(retained)
            return {"removed": key_id}

    def _read(self) -> list[dict[str, str]]:
        self._ensure_directory()
        flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self.path, flags)
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise SSHKeyError("ssh_key_state_unavailable", "SSH public-key state is unavailable.", 503) from exc
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) & 0o077
                or info.st_size > MAX_FILE_BYTES
            ):
                raise SSHKeyError("ssh_key_state_unsafe", "SSH public-key state failed a safety check.", 503)
            data = bytearray()
            while len(data) <= MAX_FILE_BYTES:
                chunk = os.read(fd, min(64 * 1024, MAX_FILE_BYTES + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            if len(data) > MAX_FILE_BYTES:
                raise SSHKeyError("ssh_key_state_unsafe", "SSH public-key state failed a safety check.", 503)
            lines = bytes(data).decode("utf-8").splitlines()
        except UnicodeError as exc:
            raise SSHKeyError("ssh_key_state_unavailable", "SSH public-key state is unavailable.", 503) from exc
        finally:
            os.close(fd)
        keys = [self._parse(line) for line in lines if line]
        if len(keys) > MAX_KEYS:
            raise SSHKeyError("ssh_key_state_invalid", "SSH public-key state is invalid.", 503)
        return keys

    def _parse(self, value: object) -> dict[str, str]:
        if not isinstance(value, str) or not value or len(value.encode("utf-8")) > MAX_KEY_BYTES or "\n" in value or "\r" in value:
            raise SSHKeyError("invalid_ssh_public_key", "One bounded OpenSSH public key is required.")
        parts = value.strip().split(None, 2)
        if len(parts) < 2 or parts[0] not in ALLOWED_KEY_TYPES:
            raise SSHKeyError("invalid_ssh_public_key", "The OpenSSH public key type is not supported.")
        comment = parts[2] if len(parts) == 3 else ""
        if not COMMENT_RE.fullmatch(comment):
            raise SSHKeyError("invalid_ssh_public_key", "The SSH public-key comment is invalid.")
        try:
            blob = base64.b64decode(parts[1], validate=True)
        except (binascii.Error, ValueError):
            raise SSHKeyError("invalid_ssh_public_key", "The SSH public-key encoding is invalid.") from None
        if not 16 <= len(blob) <= 8192:
            raise SSHKeyError("invalid_ssh_public_key", "The SSH public-key body is invalid.")
        prefix_length = int.from_bytes(blob[:4], "big")
        embedded = blob[4 : 4 + prefix_length]
        if embedded.decode("ascii", "ignore") != parts[0]:
            raise SSHKeyError("invalid_ssh_public_key", "The SSH public-key type does not match its body.")
        digest = hashlib.sha256(blob).digest()
        fingerprint = "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")
        return {
            "id": hashlib.sha256(blob).hexdigest()[:32],
            "type": parts[0],
            "body": parts[1],
            "comment": comment,
            "fingerprint": fingerprint,
        }

    @staticmethod
    def _public(item: dict[str, str]) -> dict[str, str]:
        return {key: item[key] for key in ("id", "type", "comment", "fingerprint")}

    def _ensure_directory(self) -> None:
        os.makedirs(self.directory, mode=0o700, exist_ok=True)
        info = os.lstat(self.directory)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise SSHKeyError("ssh_key_state_unsafe", "The SSH directory failed a safety check.", 503)

    def _write(self, keys: list[dict[str, str]]) -> None:
        self._ensure_directory()
        body = "".join(
            item["type"] + " " + item["body"] + (" " + item["comment"] if item["comment"] else "") + "\n"
            for item in keys
        ).encode("utf-8")
        fd, temporary = tempfile.mkstemp(prefix=".vibestack-authorized-keys-", dir=self.directory)
        try:
            os.fchmod(fd, 0o600)
            view = memoryview(body)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short write")
                view = view[written:]
            os.fsync(fd)
            os.close(fd)
            fd = -1
            os.replace(temporary, self.path)
            directory = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
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
