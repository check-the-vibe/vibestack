from __future__ import annotations

from pathlib import Path

import pytest

from vibestack.sessions import CodexConfigManager, MCPServerConfig
from vibestack.sessions import codex_config as codex_cfg


def test_ensure_default_playwright(tmp_path: Path) -> None:
    manager = CodexConfigManager(codex_home=tmp_path)
    manager.ensure_default_playwright()

    state = manager.list_servers()
    assert "playwright" in state
    entry = state["playwright"]
    assert entry["command"] == "npx"
    assert entry["args"] == ["@playwright/mcp@latest", "--browser", "chromium"]

    config_text = manager.config_path.read_text(encoding="utf-8")
    assert "[mcp_servers.playwright]" in config_text
    assert 'command = "npx"' in config_text
    assert 'args = ["@playwright/mcp@latest", "--browser", "chromium"]' in config_text


def test_ensure_server_persists_env_and_timeouts(tmp_path: Path) -> None:
    manager = CodexConfigManager(codex_home=tmp_path)
    config = MCPServerConfig(
        command="./docs-mcp",
        args=["--port", "4000"],
        env={"API_TOKEN": "abc123"},
        startup_timeout_sec=15,
        tool_timeout_sec=45,
    )

    manager.ensure_server("docs", config)
    state = manager.list_servers()

    entry = state["docs"]
    assert entry["env"] == {"API_TOKEN": "abc123"}
    assert entry["startup_timeout_sec"] == 15
    assert entry["tool_timeout_sec"] == 45

    config_text = manager.config_path.read_text(encoding="utf-8")
    assert "[mcp_servers.docs]" in config_text
    assert 'args = ["--port", "4000"]' in config_text
    assert "startup_timeout_sec = 15" in config_text
    assert "tool_timeout_sec = 45" in config_text
    assert "[mcp_servers.docs.env]" in config_text
    assert 'API_TOKEN = "abc123"' in config_text


def test_cli_add_and_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = codex_cfg.main([
        "--home",
        str(tmp_path),
        "add",
        "docs",
        "--",
        "./docs-mcp",
        "--flag",
    ])
    assert exit_code == 0

    exit_code = codex_cfg.main(["--home", str(tmp_path), "list"])
    assert exit_code == 0
    stdout = capsys.readouterr().out
    assert "docs" in stdout
    assert "./docs-mcp --flag" in stdout

    exit_code = codex_cfg.main(["--home", str(tmp_path), "remove", "docs"])
    assert exit_code == 0
    exit_code = codex_cfg.main(["--home", str(tmp_path), "list", "--json"])
    assert exit_code == 0
    stdout = capsys.readouterr().out
    assert stdout.strip() == "{}"
