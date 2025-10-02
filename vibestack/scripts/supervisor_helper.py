"""Supervisor helper: centralize supervisorctl access and privilege handling.

This module provides simple helpers to run supervisorctl commands without
replicating `sudo` usage across the codebase. It prefers running `supervisorctl`
as the current user; if that fails and `sudo` is available and allowed, it will
re-run the command with `sudo`.

Usage:
    from vibestack.scripts.supervisor_helper import run_supervisor_command
    run_supervisor_command(["status"])  # returns (exit_code, stdout, stderr)
"""
from __future__ import annotations

import shutil
import subprocess
from typing import List, Tuple, Optional


def _find_executable(name: str) -> bool:
    return shutil.which(name) is not None


def _run(cmd: List[str]) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as exc:  # pragma: no cover - environment dependent
        return 1, "", str(exc)


def run_supervisor_command(args: List[str]) -> Tuple[int, str, str]:
    """Run `supervisorctl` with best-effort privilege handling.

    - Try running `supervisorctl <args>` directly.
    - If it fails and `sudo` is available, try `sudo supervisorctl <args>`.
    - Return (exit_code, stdout, stderr).
    """
    if not _find_executable("supervisorctl"):
        return 1, "", "supervisorctl not found in PATH"

    direct_cmd = ["supervisorctl"] + args
    rc, out, err = _run(direct_cmd)
    if rc == 0:
        return rc, out, err

    # If direct attempt failed, and sudo exists, try sudo if available
    if _find_executable("sudo"):
        sudo_cmd = ["sudo"] + direct_cmd
        rc2, out2, err2 = _run(sudo_cmd)
        return rc2, out2, err2

    return rc, out, err


def spawn_supervisor_process(args: List[str]) -> Optional[subprocess.Popen]:
    """Spawn a supervisorctl subprocess with best-effort privilege handling.

    Returns a subprocess.Popen object if the command could be started, or
    ``None`` if it could not be spawned.
    """
    if not _find_executable("supervisorctl"):
        # If supervisorctl is not present in PATH, there's nothing to spawn.
        return None

    direct_cmd = ["supervisorctl"] + args
    try:
        proc = subprocess.Popen(direct_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return proc
    except (FileNotFoundError, PermissionError):
        # Try with sudo if available
        if _find_executable("sudo"):
            sudo_cmd = ["sudo"] + direct_cmd
            try:
                proc = subprocess.Popen(sudo_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                return proc
            except Exception:
                return None
    except Exception:
        return None

    return None
