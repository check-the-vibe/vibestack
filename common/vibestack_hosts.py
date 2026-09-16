"""Validated custom Host allowlisting shared by workspace HTTP services."""

from __future__ import annotations

import ipaddress
import os
import re
import sys


LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def configured_hosts(value: str | None = None) -> frozenset[str]:
    raw = os.environ.get("VIBESTACK_ALLOWED_HOSTS", "") if value is None else value
    if len(raw) > 2048:
        raise ValueError("VIBESTACK_ALLOWED_HOSTS is too long")
    result: set[str] = set()
    for item in raw.split(","):
        item = item.strip().lower()
        if not item:
            continue
        if len(result) >= 32:
            raise ValueError("VIBESTACK_ALLOWED_HOSTS has too many entries")
        try:
            parsed = ipaddress.ip_address(item)
        except ValueError:
            labels = item.split(".")
            if (
                len(item) > 253
                or len(labels) == 4 and all(label.isdecimal() for label in labels)
                or any(not LABEL_RE.fullmatch(label) for label in labels)
            ):
                raise ValueError("VIBESTACK_ALLOWED_HOSTS contains an invalid hostname") from None
            canonical = item
        else:
            canonical = parsed.compressed
            if item != canonical:
                raise ValueError("VIBESTACK_ALLOWED_HOSTS IP addresses must be canonical")
        result.add(canonical)
    return frozenset(result)


CUSTOM_HOSTS = configured_hosts()


def host_is_configured(hostname: str) -> bool:
    try:
        canonical = ipaddress.ip_address(hostname).compressed
    except ValueError:
        canonical = hostname.lower()
    return canonical in CUSTOM_HOSTS


def nginx_map(hosts: frozenset[str]) -> str:
    lines = ["# Generated from validated VIBESTACK_ALLOWED_HOSTS; do not edit.\n"]
    for host in sorted(hosts):
        escaped = re.escape(host)
        if ":" in host:
            pattern = rf"~*^\[{escaped}\](?::[0-9]{{1,5}})?$"
        else:
            pattern = rf"~*^{escaped}(?::[0-9]{{1,5}})?$"
        lines.append(f'"{pattern}" 1;\n')
    return "".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not os.path.isabs(argv[1]):
        print("usage: vibestack_hosts.py ABSOLUTE_MAP_PATH", file=sys.stderr)
        return 2
    target = argv[1]
    temporary = target + ".new"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        fd = os.open(temporary, flags, 0o644)
        try:
            data = nginx_map(configured_hosts()).encode("ascii")
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short write")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
