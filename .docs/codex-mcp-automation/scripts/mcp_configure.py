#!/usr/bin/env python3
"""Utility for composing Codex MCP configurations from reusable presets."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
PRESETS_DIR = ROOT / "mcp-presets"
TARGET_PATH = ROOT / "mcp.json"


class MCPConfigureError(Exception):
    """Raised when preset composition fails."""


def list_presets() -> List[str]:
    if not PRESETS_DIR.exists():
        return []
    return sorted(p.stem for p in PRESETS_DIR.glob("*.json"))


def load_preset(name: str) -> Tuple[Dict, Dict[str, List[str]]]:
    path = PRESETS_DIR / f"{name}.json"
    if not path.exists():
        raise MCPConfigureError(f"Preset '{name}' not found at {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    servers = data.get("mcpServers")
    if not isinstance(servers, dict) or not servers:
        raise MCPConfigureError(f"Preset '{name}' does not define any mcpServers")

    metadata: Dict[str, List[str]] = {}
    for key in ("install", "postInstall", "notes"):
        value = data.get(key)
        if value:
            if isinstance(value, list):
                metadata[key] = [str(item) for item in value]
            else:
                metadata[key] = [str(value)]
    return servers, metadata


def merge_servers(preset_servers: Dict, base: Dict) -> None:
    base_servers = base.setdefault("mcpServers", {})
    for server_id, config in preset_servers.items():
        base_servers[server_id] = config


def save_config(config: Dict) -> None:
    TARGET_PATH.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def load_existing_config() -> Dict:
    if TARGET_PATH.exists():
        with TARGET_PATH.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    return {"mcpServers": {}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("presets", nargs="*", help="Preset names to merge into mcp.json")
    parser.add_argument("--list", action="store_true", help="List available presets and exit")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Start from an empty configuration instead of merging with existing mcp.json",
    )
    args = parser.parse_args()

    if args.list:
        for preset in list_presets():
            print(preset)
        return

    if not args.presets:
        parser.error("No presets supplied (or use --list)")

    if not PRESETS_DIR.exists():
        raise MCPConfigureError(f"Preset directory missing: {PRESETS_DIR}")

    config = {"mcpServers": {}} if args.reset else load_existing_config()
    setup_messages: List[str] = []

    for preset_name in args.presets:
        servers, metadata = load_preset(preset_name)
        merge_servers(servers, config)
        for key, lines in metadata.items():
            header = key.replace("postInstall", "post-install")
            for line in lines:
                setup_messages.append(f"[{preset_name}] {header}: {line}")

    save_config(config)

    if setup_messages:
        print("Additional setup steps:")
        for line in setup_messages:
            print(f"  - {line}")


if __name__ == "__main__":
    main()
