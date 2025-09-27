"""Streamable HTTP MCP server exposing VibeStack session controls."""
from __future__ import annotations

import contextlib
import functools
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional

import anyio
import mcp.types as types
from mcp import McpError
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

from vibestack import api as vibestack_api
from vibestack import settings as vibestack_settings

logger = logging.getLogger(__name__)

ToolHandler = Callable[[Dict[str, Any]], Awaitable[List[types.ContentBlock]]]

DEFAULT_TEMPLATE = os.environ.get("VIBESTACK_MCP_DEFAULT_TEMPLATE", "codex")


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _build_session_url(name: str, template: Optional[str]) -> str:
    base_override = os.environ.get("VIBESTACK_SESSION_FOLLOW_BASE")
    if base_override is not None:
        return vibestack_settings.build_session_ui_url(
            name,
            template=template,
            base_url=base_override,
        )
    return vibestack_settings.build_session_ui_url(name, template=template)


def _augment_session(metadata: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(metadata)
    name = payload.get("name") or ""
    template = payload.get("template")
    if name:
        payload["session_url"] = _build_session_url(name, template)
    return payload


def _augment_sessions(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [_augment_session(item) for item in items]


def _as_json(payload: Any) -> List[types.ContentBlock]:
    serialized = json.dumps(payload, indent=2, sort_keys=True)
    return [types.TextContent(type="text", text=serialized)]


def _as_text(message: str) -> List[types.ContentBlock]:
    return [types.TextContent(type="text", text=message)]


def _coerce_session_root(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return str(value)


def _coerce_enter_flag(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return default
        if normalized in {"1", "true", "yes", "on", "enter", "press", "return", "submit"}:
            return True
        if normalized in {"0", "false", "no", "off", "skip"}:
            return False
        return default
    if isinstance(value, dict):
        for key in ("value", "enter", "press"):
            if key in value:
                return _coerce_enter_flag(value[key], default=default)
        return default
    return default


async def _run_sync(func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    if kwargs:
        # functools.partial preserves argument semantics for thread offloading.
        func = functools.partial(func, *args, **kwargs)
        return await anyio.to_thread.run_sync(func)
    return await anyio.to_thread.run_sync(func, *args)


async def _handle_list_sessions(arguments: Dict[str, Any]) -> List[types.ContentBlock]:
    session_root = _coerce_session_root(arguments.get("session_root"))
    sessions = await _run_sync(vibestack_api.list_sessions, session_root=session_root)
    return _as_json(_augment_sessions(sessions))


async def _handle_get_session(arguments: Dict[str, Any]) -> List[types.ContentBlock]:
    name = arguments["name"]
    session_root = _coerce_session_root(arguments.get("session_root"))
    session = await _run_sync(vibestack_api.get_session, name, session_root=session_root)
    return _as_json(_augment_session(session) if session else None)


async def _handle_create_session(arguments: Dict[str, Any]) -> List[types.ContentBlock]:
    name = arguments["name"]
    session_root = _coerce_session_root(arguments.get("session_root"))
    metadata = await _run_sync(
        vibestack_api.create_session,
        name,
        template=arguments.get("template") or DEFAULT_TEMPLATE,
        command=arguments.get("command"),
        command_args=arguments.get("command_args"),
        working_dir=arguments.get("working_dir"),
        description=arguments.get("description"),
        session_root=session_root,
    )
    prompt = arguments.get("prompt")
    if prompt:
        await _run_sync(
            vibestack_api.send_text,
            name,
            prompt,
            enter=True,
            session_root=session_root,
        )
    return _as_json(_augment_session(metadata))


async def _handle_send_input(arguments: Dict[str, Any]) -> List[types.ContentBlock]:
    name = arguments["name"]
    session_root = _coerce_session_root(arguments.get("session_root"))
    raw_text = arguments.get("text", "")
    if isinstance(raw_text, dict):
        for candidate in ("text", "value"):
            if candidate in raw_text:
                raw_text = raw_text[candidate]
                break
    if raw_text is None:
        raw_text = ""
    text = str(raw_text)
    enter = _coerce_enter_flag(arguments.get("enter"), default=True)
    await _run_sync(
        vibestack_api.send_text,
        name,
        text,
        enter=enter,
        session_root=session_root,
    )
    return _as_text("input queued")


async def _handle_tail_log(arguments: Dict[str, Any]) -> List[types.ContentBlock]:
    name = arguments["name"]
    lines = int(arguments.get("lines", 200) or 200)
    session_root = _coerce_session_root(arguments.get("session_root"))
    log_output = await _run_sync(
        vibestack_api.tail_log,
        name,
        lines=lines,
        session_root=session_root,
    )
    return _as_json({"log": log_output})


async def _handle_kill_session(arguments: Dict[str, Any]) -> List[types.ContentBlock]:
    name = arguments["name"]
    session_root = _coerce_session_root(arguments.get("session_root"))
    await _run_sync(vibestack_api.kill_session, name, session_root=session_root)
    return _as_text("session terminated")


async def _handle_list_jobs(arguments: Dict[str, Any]) -> List[types.ContentBlock]:
    session_root = _coerce_session_root(arguments.get("session_root"))
    jobs = await _run_sync(vibestack_api.list_jobs, session_root=session_root)
    return _as_json(jobs)


async def _handle_enqueue_one_off(arguments: Dict[str, Any]) -> List[types.ContentBlock]:
    name = arguments["name"]
    command = arguments["command"]
    session_root = _coerce_session_root(arguments.get("session_root"))
    metadata = await _run_sync(
        vibestack_api.enqueue_one_off,
        name,
        command,
        template=arguments.get("template", "script"),
        description=arguments.get("description"),
        session_root=session_root,
    )
    return _as_json(_augment_session(metadata))


async def _handle_get_session_url(arguments: Dict[str, Any]) -> List[types.ContentBlock]:
    name = arguments["name"]
    session_root = _coerce_session_root(arguments.get("session_root"))
    session = await _run_sync(vibestack_api.get_session, name, session_root=session_root)
    if not session:
        raise McpError(
            types.ErrorData(code=types.INVALID_PARAMS, message=f"Session '{name}' not found"),
        )
    url = session.get("session_url") or _build_session_url(name, session.get("template"))
    return _as_json({"session_url": url})


async def _handle_list_templates(_: Dict[str, Any]) -> List[types.ContentBlock]:
    templates = await _run_sync(vibestack_api.list_templates)
    return _as_json(templates)


async def _handle_save_template(arguments: Dict[str, Any]) -> List[types.ContentBlock]:
    payload = arguments.get("payload")
    include_sources = arguments.get("include_sources")
    if payload is None:
        raise McpError(types.ErrorData(code=types.INVALID_PARAMS, message="payload is required"))
    path = await _run_sync(
        vibestack_api.save_template,
        payload,
        include_sources=include_sources,
    )
    return _as_json({"path": path})


async def _handle_delete_template(arguments: Dict[str, Any]) -> List[types.ContentBlock]:
    name = arguments["name"]
    await _run_sync(vibestack_api.delete_template, name)
    return _as_text("template deleted")


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    schema: Dict[str, Any]
    handler: ToolHandler


TOOL_DEFINITIONS: List[ToolDefinition] = [
    ToolDefinition(
        name="list_sessions",
        description="List known VibeStack sessions.",
        schema={
            "type": "object",
            "properties": {
                "session_root": {
                    "type": "string",
                    "description": "Optional override for the session root directory.",
                }
            },
        },
        handler=_handle_list_sessions,
    ),
    ToolDefinition(
        name="get_session",
        description="Fetch metadata for a session by name.",
        schema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "session_root": {
                    "type": "string",
                    "description": "Optional override for the session root directory.",
                },
            },
        },
        handler=_handle_get_session,
    ),
    ToolDefinition(
        name="get_session_url",
        description="Return the Streamlit URL for a session by name.",
        schema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "session_root": {
                    "type": "string",
                    "description": "Optional override for the session root directory.",
                },
            },
        },
        handler=_handle_get_session_url,
    ),
    ToolDefinition(
        name="create_session",
        description="Create a new session, defaulting to the Codex template.",
        schema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "template": {"type": "string"},
                "command": {"type": "string"},
                "description": {"type": "string"},
                "session_root": {"type": "string"},
                "prompt": {"type": "string"},
            },
        },
        handler=_handle_create_session,
    ),
    ToolDefinition(
        name="send_input",
        description="Send text to an existing session's terminal.",
        schema={
            "type": "object",
            "required": ["name", "text"],
            "properties": {
                "name": {"type": "string"},
                "text": {"type": "string"},
                "enter": {
                    "anyOf": [
                        {"type": "boolean"},
                        {"type": "string"},
                    ],
                    "default": True,
                    "description": "Press Enter after sending the payload; accepts booleans or truthy strings like 'press'.",
                },
                "session_root": {"type": "string"},
            },
        },
        handler=_handle_send_input,
    ),
    ToolDefinition(
        name="tail_log",
        description="Retrieve the latest log output for a session.",
        schema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "lines": {"type": "integer", "minimum": 1, "default": 200},
                "session_root": {"type": "string"},
            },
        },
        handler=_handle_tail_log,
    ),
    ToolDefinition(
        name="kill_session",
        description="Terminate a session if it is running.",
        schema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "session_root": {"type": "string"},
            },
        },
        handler=_handle_kill_session,
    ),
    ToolDefinition(
        name="list_jobs",
        description="List queued one-off jobs.",
        schema={
            "type": "object",
            "properties": {
                "session_root": {"type": "string"},
            },
        },
        handler=_handle_list_jobs,
    ),
    ToolDefinition(
        name="enqueue_one_off",
        description="Queue a one-off command using the session manager.",
        schema={
            "type": "object",
            "required": ["name", "command"],
            "properties": {
                "name": {"type": "string"},
                "command": {"type": "string"},
                "template": {"type": "string", "default": "script"},
                "description": {"type": "string"},
                "session_root": {"type": "string"},
            },
        },
        handler=_handle_enqueue_one_off,
    ),
    ToolDefinition(
        name="list_templates",
        description="List available templates.",
        schema={"type": "object", "properties": {}},
        handler=_handle_list_templates,
    ),
    ToolDefinition(
        name="save_template",
        description="Persist a template definition to disk.",
        schema={
            "type": "object",
            "required": ["payload"],
            "properties": {
                "payload": {"type": "object"},
                "include_sources": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
        handler=_handle_save_template,
    ),
    ToolDefinition(
        name="delete_template",
        description="Remove a user-provided template by name.",
        schema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
            },
        },
        handler=_handle_delete_template,
    ),
]

TOOL_REGISTRY: Dict[str, ToolDefinition] = {item.name: item for item in TOOL_DEFINITIONS}

server = Server(
    name=os.environ.get("VIBESTACK_MCP_NAME", "vibestack"),
    version=os.environ.get("VIBESTACK_MCP_VERSION"),
    instructions=(
        "Use these tools to manage VibeStack sessions. "
        "Default session creation uses the Codex template and can queue an initial prompt "
        "for the Codex CLI."
    ),
)


@server.list_tools()
async def list_tools() -> List[types.Tool]:
    return [
        types.Tool(
            name=definition.name,
            description=definition.description,
            inputSchema=definition.schema,
        )
        for definition in TOOL_DEFINITIONS
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any] | None) -> List[types.ContentBlock]:
    definition = TOOL_REGISTRY.get(name)
    if definition is None:
        raise McpError(
            types.ErrorData(
                code=types.INVALID_PARAMS,
                message=f"Unknown tool: {name}",
            )
        )
    args = arguments or {}
    return await definition.handler(args)


def _allowed_origins() -> List[str]:
    raw = os.environ.get("VIBESTACK_MCP_ALLOW_ORIGINS", "*")
    parts = [item.strip() for item in raw.split(",")]
    origins = [item for item in parts if item]
    return origins or ["*"]


SESSION_MANAGER = StreamableHTTPSessionManager(
    app=server,
    event_store=None,
    json_response=_env_bool("VIBESTACK_MCP_JSON_RESPONSE", False),
    stateless=_env_bool("VIBESTACK_MCP_STATELESS", False),
)


async def _handle_streamable_http(scope: Scope, receive: Receive, send: Send) -> None:
    scope_type = scope.get("type")
    if scope_type != "http":
        logger.debug("Ignoring unsupported ASGI scope %s", scope_type)
        if scope_type == "websocket":
            await send({"type": "websocket.close", "code": 1000})
        else:
            await send(
                {
                    "type": "http.response.start",
                    "status": 404,
                    "headers": [(b"content-length", b"0")],
                }
            )
            await send({"type": "http.response.body", "body": b"", "more_body": False})
        return
    await SESSION_MANAGER.handle_request(scope, receive, send)


@contextlib.asynccontextmanager
async def _lifespan(_: Starlette):
    async with SESSION_MANAGER.run():
        logger.info("VibeStack MCP server ready (streamable-http)")
        yield
        logger.info("VibeStack MCP server shutting down")


_routes = [Mount("/", app=_handle_streamable_http)]

_starlette_app = Starlette(debug=_env_bool("VIBESTACK_MCP_DEBUG", False), routes=_routes, lifespan=_lifespan)

app = CORSMiddleware(
    _starlette_app,
    allow_origins=_allowed_origins(),
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id"],
)


def main() -> None:
    import uvicorn

    uvicorn.run(
        "vibestack.mcp.server:app",
        host=os.environ.get("VIBESTACK_MCP_HOST", "0.0.0.0"),
        port=_env_int("VIBESTACK_MCP_PORT", 9100),
        factory=False,
    )


if __name__ == "__main__":
    main()
