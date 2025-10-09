#!/usr/bin/env python3
"""Minimal smoke test for the VibeStack MCP server (streamable HTTP transport)."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from typing import Any

import mcp
import mcp.types as types
from mcp.client.streamable_http import streamablehttp_client

# Nginx terminates MCP traffic; inside the container it lives on :80,
# externally reachable at http://localhost:3000/mcp when using startup.sh.
DEFAULT_URL = "http://localhost:3000/mcp"
MCP_URL = os.environ.get("VIBESTACK_MCP_URL", DEFAULT_URL)


def _unpack_result(result: types.CallToolResult) -> Any:
    if result.structuredContent is not None:
        return result.structuredContent

    payload: list[Any] = []
    for block in result.content:
        if isinstance(block, types.TextContent):
            try:
                payload.append(json.loads(block.text))
            except json.JSONDecodeError:
                payload.append(block.text)
        else:
            payload.append(block)

    if not payload:
        return None
    return payload[0] if len(payload) == 1 else payload


async def main() -> None:
    async with streamablehttp_client(MCP_URL) as (read_stream, write_stream, get_session_id):
        async with mcp.ClientSession(read_stream, write_stream) as session:
            initialize_result = await session.initialize()
            print("Connected to:", initialize_result.serverInfo)
            print("Session ID:", get_session_id() or "<unavailable>")

            templates = _unpack_result(await session.call_tool("list_templates"))
            print("Available templates:\n", json.dumps(templates, indent=2))

            session_name = f"mcp-demo-{uuid.uuid4().hex[:8]}"
            created = _unpack_result(
                await session.call_tool(
                    "create_session",
                    {
                        "name": session_name,
                        "template": "codex",
                        "description": "Created via MCP runner",
                    },
                )
            )
            print("Created session:\n", json.dumps(created, indent=2))

            sessions = _unpack_result(await session.call_tool("list_sessions"))
            print("Sessions:\n", json.dumps(sessions, indent=2))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
