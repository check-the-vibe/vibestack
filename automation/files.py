"""Descriptor-relative access to regular files below the VibeStack Desktop."""

from __future__ import annotations

import errno
import hashlib
import os
import re
import stat
import threading
import uuid
from dataclasses import dataclass, replace
from pathlib import Path


MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_RANGE_BYTES = 8 * 1024 * 1024
READ_CHUNK_BYTES = 128 * 1024
CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x1f\x7f]")


class FileError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class FileValue:
    path: str
    data: bytes
    etag: str
    size: int
    modified_ns: int
    created: bool = False
    device: int = 0
    inode: int = 0
    changed_ns: int = 0

    def metadata(self) -> dict[str, object]:
        return {
            "path": self.path,
            "size": self.size,
            "etag": self.etag,
            "modified_ns": self.modified_ns,
        }


class DesktopFileStore:
    """Raw file operations with no path-based opens below the trusted root.

    Each component is opened relative to an already-validated directory FD
    with ``O_NOFOLLOW``. Files must be regular, owned by the service uid, on
    the Desktop's device, and have exactly one hard link.
    """

    def __init__(
        self,
        root: str = "/home/vibe/Desktop",
        *,
        expected_uid: int | None = None,
        max_bytes: int = MAX_FILE_BYTES,
    ):
        self.root = os.path.abspath(root)
        self.expected_uid = os.getuid() if expected_uid is None else expected_uid
        self.max_bytes = max_bytes
        self._lock = threading.RLock()

    @staticmethod
    def require_relative_path(value: object) -> str:
        if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 4096:
            raise FileError("invalid_path", "A Desktop-relative file path is required.", 400)
        if value.startswith(("/", "\\")) or "\\" in value:
            raise FileError("invalid_path", "The file path must be Desktop-relative.", 400)
        parts = value.split("/")
        if any(
            not part
            or part in (".", "..")
            or CONTROL_CHARACTER_RE.search(part)
            for part in parts
        ):
            raise FileError("invalid_path", "The file path is invalid.", 400)
        return "/".join(parts)

    def require_cwd(self, value: object | None) -> str:
        """Validate a command cwd and return a canonical Desktop path."""

        if value is None or value == "":
            relative_parts: list[str] = []
        elif isinstance(value, str) and os.path.isabs(value):
            root = os.path.normpath(self.root)
            normalized = os.path.normpath(value)
            try:
                common = os.path.commonpath((root, normalized))
            except ValueError:
                common = ""
            if common != root:
                raise FileError("invalid_cwd", "cwd must be within the Desktop.", 400)
            suffix = os.path.relpath(normalized, root)
            relative_parts = [] if suffix == "." else self.require_relative_path(suffix).split("/")
        elif isinstance(value, str):
            relative_parts = self.require_relative_path(value).split("/")
        else:
            raise FileError("invalid_cwd", "cwd must be a Desktop-relative path.", 400)

        fd, device = self._open_root()
        try:
            for component in relative_parts:
                next_fd = self._open_directory(fd, component, device)
                os.close(fd)
                fd = next_fd
            # /proc/self/fd resolves the exact validated directory. Commands
            # are launched soon after validation and this also rejects every
            # symlink in the requested path.
            resolved = os.path.realpath("/proc/self/fd/%d" % fd)
            if os.path.commonpath((self.root, resolved)) != self.root:
                raise FileError("invalid_cwd", "cwd must remain within the Desktop.", 400)
            return resolved
        finally:
            os.close(fd)

    def read(self, relative_path: str) -> FileValue:
        relative_path = self.require_relative_path(relative_path)
        with self._lock:
            parent_fd, leaf, device = self._open_parent(relative_path)
            try:
                return self._read_at(parent_fd, leaf, device, relative_path)
            finally:
                os.close(parent_fd)

    def write(
        self,
        relative_path: str,
        data: bytes,
        *,
        if_match: str | None = None,
        if_none_match: str | None = None,
    ) -> FileValue:
        relative_path = self.require_relative_path(relative_path)
        if len(data) > self.max_bytes:
            raise FileError("file_too_large", "The file exceeds the 16 MiB limit.", 413)
        if if_match is not None and if_none_match is not None:
            raise FileError(
                "invalid_precondition",
                "If-Match and If-None-Match cannot be combined.",
                400,
            )

        with self._lock:
            parent_fd, leaf, device = self._open_parent(relative_path)
            temporary = ".vibestack-%s.tmp" % uuid.uuid4().hex
            temporary_created = False
            fd = -1
            try:
                existing: FileValue | None
                try:
                    existing = self._read_at(parent_fd, leaf, device, relative_path)
                except FileError as exc:
                    if exc.code != "file_not_found":
                        raise
                    existing = None
                self._check_write_preconditions(existing, if_match, if_none_match)

                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
                flags |= getattr(os, "O_NOFOLLOW", 0)
                fd = os.open(temporary, flags, 0o600, dir_fd=parent_fd)
                temporary_created = True
                view = memoryview(data)
                written = 0
                while written < len(view):
                    count = os.write(fd, view[written:])
                    if count <= 0:
                        raise OSError(errno.EIO, "short write")
                    written += count
                os.fchmod(fd, 0o644)
                os.fsync(fd)
                staged_info = os.fstat(fd)
                self._require_regular(staged_info, device)

                self._before_commit(parent_fd, leaf)
                self._require_staged_identity(
                    parent_fd, temporary, staged_info, device
                )

                conditional = if_match is not None or if_none_match is not None
                if conditional and existing is None:
                    # link(2) is an atomic create-if-absent operation. It keeps
                    # If-None-Match creation from overwriting a leaf created by
                    # another Desktop writer after our initial check.
                    try:
                        os.link(
                            temporary,
                            leaf,
                            src_dir_fd=parent_fd,
                            dst_dir_fd=parent_fd,
                            follow_symlinks=False,
                        )
                    except FileExistsError:
                        raise FileError(
                            "precondition_failed",
                            "The file changed before the conditional write committed.",
                            412,
                        ) from None
                    os.unlink(temporary, dir_fd=parent_fd)
                else:
                    if conditional:
                        try:
                            current = self._read_at(
                                parent_fd, leaf, device, relative_path
                            )
                        except FileError as exc:
                            if exc.code == "file_not_found":
                                raise FileError(
                                    "precondition_failed",
                                    "The file changed before the conditional write committed.",
                                    412,
                                ) from None
                            raise
                        if not self._same_revision(existing, current):
                            raise FileError(
                                "precondition_failed",
                                "The file changed before the conditional write committed.",
                                412,
                            )
                        self._check_write_preconditions(
                            current, if_match, if_none_match
                        )
                    # Linux has no pathname CAS for replacement. This replace
                    # follows an immediate inode/content revalidation; callers
                    # needing coordination with non-API writers must arrange
                    # that coordination themselves. API writes are serialized.
                    os.replace(
                        temporary,
                        leaf,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                    )
                temporary_created = False
                os.fsync(parent_fd)
                return replace(
                    self._read_at(parent_fd, leaf, device, relative_path),
                    created=existing is None,
                )
            except FileError:
                raise
            except OSError as exc:
                raise self._os_error(exc, writing=True) from None
            finally:
                if fd >= 0:
                    os.close(fd)
                if temporary_created:
                    try:
                        os.unlink(temporary, dir_fd=parent_fd)
                    except OSError:
                        pass
                os.close(parent_fd)

    def _before_commit(self, parent_fd: int, leaf: str) -> None:
        """Test seam for deterministic external-writer race regressions."""

    def _require_staged_identity(
        self,
        parent_fd: int,
        temporary: str,
        expected: os.stat_result,
        device: int,
    ) -> None:
        try:
            current = os.stat(temporary, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as exc:
            raise self._os_error(exc, writing=True) from None
        self._require_regular(current, device)
        if (current.st_dev, current.st_ino) != (expected.st_dev, expected.st_ino):
            raise FileError("unsafe_file", "The staged file changed before commit.", 403)

    @staticmethod
    def _same_revision(before: FileValue | None, after: FileValue) -> bool:
        return before is not None and (
            before.device,
            before.inode,
            before.size,
            before.modified_ns,
            before.changed_ns,
            before.etag,
        ) == (
            after.device,
            after.inode,
            after.size,
            after.modified_ns,
            after.changed_ns,
            after.etag,
        )

    def _check_write_preconditions(
        self,
        existing: FileValue | None,
        if_match: str | None,
        if_none_match: str | None,
    ) -> None:
        if if_match is not None:
            if not _valid_etag_header(if_match):
                raise FileError("invalid_precondition", "If-Match is invalid.", 400)
            if existing is None or not _etag_list_matches(
                if_match, existing.etag, weak=False
            ):
                raise FileError("precondition_failed", "If-Match did not match.", 412)
        if if_none_match is not None:
            if not _valid_etag_header(if_none_match):
                raise FileError("invalid_precondition", "If-None-Match is invalid.", 400)
            if existing is not None and _etag_list_matches(
                if_none_match, existing.etag, weak=True
            ):
                raise FileError("precondition_failed", "If-None-Match matched.", 412)

    def _open_root(self) -> tuple[int, int]:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self.root, flags)
        except OSError as exc:
            raise self._os_error(exc) from None
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != self.expected_uid:
            os.close(fd)
            raise FileError("unsafe_desktop", "The Desktop root is not safe to access.", 503)
        return fd, info.st_dev

    def _open_directory(self, parent_fd: int, component: str, device: int) -> int:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(component, flags, dir_fd=parent_fd)
        except OSError as exc:
            raise self._os_error(exc) from None
        info = os.fstat(fd)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != self.expected_uid
            or info.st_dev != device
        ):
            os.close(fd)
            raise FileError("unsafe_path", "A Desktop path component is not safe.", 403)
        return fd

    def _open_parent(self, relative_path: str) -> tuple[int, str, int]:
        components = relative_path.split("/")
        fd, device = self._open_root()
        try:
            for component in components[:-1]:
                next_fd = self._open_directory(fd, component, device)
                os.close(fd)
                fd = next_fd
            return fd, components[-1], device
        except BaseException:
            os.close(fd)
            raise

    def _read_at(
        self, parent_fd: int, leaf: str, device: int, relative_path: str
    ) -> FileValue:
        # O_NONBLOCK prevents a FIFO or device substituted for the leaf from
        # blocking before fstat can reject it as non-regular.
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(leaf, flags, dir_fd=parent_fd)
        except OSError as exc:
            raise self._os_error(exc) from None
        try:
            before = os.fstat(fd)
            self._require_regular(before, device)
            if before.st_size > self.max_bytes:
                raise FileError("file_too_large", "The file exceeds the 16 MiB limit.", 413)
            chunks: list[bytes] = []
            total = 0
            digest = hashlib.sha256()
            while True:
                chunk = os.read(fd, min(READ_CHUNK_BYTES, self.max_bytes + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > self.max_bytes:
                    raise FileError("file_too_large", "The file exceeds the 16 MiB limit.", 413)
                digest.update(chunk)
                chunks.append(chunk)
            after = os.fstat(fd)
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise FileError("file_changed", "The file changed while it was read.", 409)
            return FileValue(
                path=relative_path,
                data=b"".join(chunks),
                etag='"sha256-%s"' % digest.hexdigest(),
                size=total,
                modified_ns=after.st_mtime_ns,
                device=after.st_dev,
                inode=after.st_ino,
                changed_ns=after.st_ctime_ns,
            )
        finally:
            os.close(fd)

    def _require_regular(self, info: os.stat_result, device: int) -> None:
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != self.expected_uid
            or info.st_dev != device
            or info.st_nlink != 1
        ):
            raise FileError(
                "unsafe_file",
                "Only single-link regular files owned by the desktop user are allowed.",
                403,
            )

    @staticmethod
    def _os_error(exc: OSError, writing: bool = False) -> FileError:
        if exc.errno == errno.ENOENT:
            return FileError("file_not_found", "The Desktop file does not exist.", 404)
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            return FileError("unsafe_path", "Symbolic links are not allowed.", 403)
        if exc.errno in (errno.EACCES, errno.EPERM):
            return FileError("file_forbidden", "The Desktop file is not accessible.", 403)
        code = "file_write_failed" if writing else "file_read_failed"
        return FileError(code, "The Desktop file operation failed.", 503)


def _valid_etag_header(header: str) -> bool:
    if not header or len(header) > 1024:
        return False
    if header.strip() == "*":
        return True
    values = [item.strip() for item in header.split(",")]
    return bool(values) and all(
        re.fullmatch(r'(?:W/)?"[A-Za-z0-9._:-]{1,160}"', value) for value in values
    )


def _etag_list_matches(header: str, current: str, *, weak: bool) -> bool:
    values = [item.strip() for item in header.split(",")]
    return "*" in values or current in values or (weak and ("W/" + current) in values)


def parse_range(value: str | None, size: int) -> tuple[int, int] | None:
    """Parse one RFC 7233 byte range and return an inclusive pair."""

    if value is None:
        return None
    if len(value) > 128 or not value.startswith("bytes=") or "," in value:
        raise FileError("invalid_range", "Only one byte range is supported.", 416)
    spec = value[6:]
    if "-" not in spec:
        raise FileError("invalid_range", "The byte range is invalid.", 416)
    first, last = spec.split("-", 1)
    if not first:
        if not last.isdigit() or int(last) <= 0 or size == 0:
            raise FileError("invalid_range", "The byte range is unsatisfiable.", 416)
        requested = int(last)
        length = min(requested, size)
        if length > MAX_RANGE_BYTES:
            raise FileError("range_too_large", "A byte range cannot exceed 8 MiB.", 416)
        return size - length, size - 1
    if not first.isdigit() or (last and not last.isdigit()):
        raise FileError("invalid_range", "The byte range is invalid.", 416)
    start = int(first)
    end = int(last) if last else size - 1
    if start >= size or end < start or size == 0:
        raise FileError("invalid_range", "The byte range is unsatisfiable.", 416)
    end = min(end, size - 1)
    if end - start + 1 > MAX_RANGE_BYTES:
        raise FileError("range_too_large", "A byte range cannot exceed 8 MiB.", 416)
    return start, end
