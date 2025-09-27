from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "vibestack"
    / "assets"
    / "startup"
    / "supervisor_log_viewer.py"
)

_spec = importlib.util.spec_from_file_location("supervisor_log_viewer", MODULE_PATH)
assert _spec and _spec.loader
_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)  # type: ignore[arg-type]


def test_parse_status_output_extracts_program_names() -> None:
    payload = """
    vibestack-api               RUNNING   pid 101, uptime 0:00:10
    streamlit                   STOPPED   Not running
    """

    result = _module.parse_status_output(payload)

    assert result == ["vibestack-api", "streamlit"]


def test_tail_program_logs_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_run(args):
        calls.append(tuple(args))
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout="line1\nline2\n"
        )

    monkeypatch.setattr(_module, "_run_command", fake_run)

    result = _module.tail_program_logs("vibestack-api")

    assert calls[0][-1] == "vibestack-api"
    assert result.lines == ["line1", "line2"]
    assert result.error is None


def test_tail_program_logs_reports_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(args):
        raise subprocess.CalledProcessError(1, args, stderr="oops\n")

    monkeypatch.setattr(_module, "_run_command", fake_run)

    result = _module.tail_program_logs("streamlit")

    assert result.error == "oops"
    assert result.lines == []
