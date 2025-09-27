"""VibeStack configuration helpers."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlencode, urljoin

DEFAULT_SESSION_BASE_URL = os.environ.get(
    "VIBESTACK_PUBLIC_BASE_URL",
    "https://8cf01ce6152b.ngrok.app",
)
_SETTINGS_DIR_ENV = "VIBESTACK_SETTINGS_DIR"
_SETTINGS_FILENAME = "settings.json"
_SESSION_UI_PATH = "ui/Sessions"


def _settings_dir() -> Path:
    root = os.environ.get(_SETTINGS_DIR_ENV)
    if root:
        path = Path(root).expanduser()
    else:
        path = Path.home() / ".vibestack"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _settings_path() -> Path:
    return _settings_dir() / _SETTINGS_FILENAME


def load_settings() -> Dict[str, Any]:
    path = _settings_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def save_settings(settings: Dict[str, Any]) -> None:
    path = _settings_path()
    serialized = json.dumps(settings, indent=2, sort_keys=True) + "\n"
    path.write_text(serialized, encoding="utf-8")


def get_session_base_url() -> str:
    settings = load_settings()
    stored = settings.get("session_base_url")
    if isinstance(stored, str):
        return stored.strip()
    return DEFAULT_SESSION_BASE_URL


def set_session_base_url(url: str) -> None:
    settings = load_settings()
    normalized = url.strip()
    if normalized:
        settings["session_base_url"] = normalized
    else:
        settings.pop("session_base_url", None)
    save_settings(settings)


def build_session_ui_url(name: str, *, template: Optional[str] = None, base_url: Optional[str] = None) -> str:
    base = (base_url if base_url is not None else get_session_base_url()).strip()
    if base:
        root = base if base.endswith("/") else f"{base}/"
        session_path = urljoin(root, _SESSION_UI_PATH)
    else:
        session_path = f"/{_SESSION_UI_PATH}"
    query = {"session": name}
    if template:
        query["template"] = template
    separator = "&" if "?" in session_path else "?"
    return f"{session_path}{separator}{urlencode(query)}"


__all__ = [
    "DEFAULT_SESSION_BASE_URL",
    "build_session_ui_url",
    "get_session_base_url",
    "load_settings",
    "save_settings",
    "set_session_base_url",
]
