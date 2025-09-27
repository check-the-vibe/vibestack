from __future__ import annotations

from pathlib import Path

import pytest

from vibestack import settings as vibe_settings


def test_build_session_ui_url_with_custom_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIBESTACK_SETTINGS_DIR", str(tmp_path))
    vibe_settings.set_session_base_url("https://example.test")

    url = vibe_settings.build_session_ui_url("session-123")

    assert url == "https://example.test/ui/Sessions?session=session-123"


def test_build_session_ui_url_includes_template(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIBESTACK_SETTINGS_DIR", str(tmp_path))
    vibe_settings.set_session_base_url("https://example.test")

    url = vibe_settings.build_session_ui_url("session-456", template="codex")

    assert url == "https://example.test/ui/Sessions?session=session-456&template=codex"


def test_base_override_parameter() -> None:
    override = vibe_settings.build_session_ui_url(
        "local-session",
        base_url="http://localhost:8501",
    )
    assert override.startswith("http://localhost:8501/ui/Sessions")
