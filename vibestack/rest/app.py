"""FastAPI application exposing the VibeStack Python API via REST."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from vibestack import api as vibestack_api


class SessionResponse(BaseModel):
    """Response model mirroring ``SessionMetadata.to_dict`` output."""

    schema_version: int
    name: str
    command: str
    template: str
    session_type: str
    status: str
    created_at: str
    updated_at: str
    log_path: str
    workspace_path: str
    description: Optional[str] = None
    job_id: Optional[str] = None
    exit_code: Optional[int] = None
    last_message: Optional[str] = None
    pane_current_command: Optional[str] = None
    pane_current_path: Optional[str] = None
    client_last_activity: Optional[str] = None
    session_last_attached: Optional[str] = None
    session_attached: Optional[bool] = None
    tmux_panes: Optional[List[Dict[str, Any]]] = None
    tmux_clients: Optional[List[Dict[str, Any]]] = None

    class Config:
        extra = "ignore"


class SessionCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Unique session identifier")
    template: str = Field("bash", description="Template to base the session on")
    command: Optional[str] = Field(None, description="Command override for the template")
    command_args: Optional[List[str]] = Field(
        None, description="Optional list of command arguments to append to the template command"
    )
    working_dir: Optional[str] = Field(None, description="Working directory for the session before commands run")
    description: Optional[str] = Field(None, description="Optional human readable summary")
    session_root: Optional[str] = Field(
        None,
        description="Optional override for the session root directory",
    )

    class Config:
        extra = "forbid"


class SessionTailResponse(BaseModel):
    log: str


class SessionInputRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Payload to send to the tmux session")
    enter: bool = Field(True, description="Send an enter key after the payload")

    class Config:
        extra = "forbid"


class OneOffJobRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Job identifier, used as tmux session name")
    command: str = Field(..., min_length=1, description="Command to execute")
    template: str = Field("script", description="Template used to run the one-off command")
    description: Optional[str] = Field(None, description="Optional job description")
    session_root: Optional[str] = Field(
        None,
        description="Optional override for the session root directory",
    )

    class Config:
        extra = "forbid"


class TemplateSaveRequest(BaseModel):
    payload: Dict[str, Any]
    include_sources: Optional[List[str]] = Field(
        None,
        description="Optional filesystem paths to include alongside the template",
    )

    class Config:
        extra = "forbid"


class TemplateSaveResponse(BaseModel):
    path: str


class MessageResponse(BaseModel):
    message: str


class JobRecord(BaseModel):
    id: str
    session: str
    template: str
    command: str
    status: str
    created_at: str
    updated_at: str
    message: Optional[str] = None

    class Config:
        extra = "ignore"


router = APIRouter(prefix="/api", tags=["vibestack"])
link_router = APIRouter(prefix="/link", tags=["vibestack-link"])


def _coerce_bool(value: Any, default: bool = False) -> bool:
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
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


async def _gather_request_payload(request: Request) -> Dict[str, Any]:
    payload: Dict[str, Any] = dict(request.query_params)
    if request.method in {"POST", "PUT", "PATCH"}:
        content_type = request.headers.get("content-type", "").lower()
        try:
            if "application/json" in content_type:
                body = await request.json()
                if isinstance(body, dict):
                    payload.update(body)
            elif "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
                form = await request.form()
                for key, value in form.multi_items():
                    payload[key] = value
            else:
                raw = (await request.body()).strip()
                if raw:
                    try:
                        body = json.loads(raw)
                        if isinstance(body, dict):
                            payload.update(body)
                    except json.JSONDecodeError:
                        # Ignore opaque payloads we can't parse.
                        pass
        except json.JSONDecodeError:
            pass
    return payload


@router.get("/sessions", response_model=List[SessionResponse])
def list_sessions(session_root: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
    """Return a list of known sessions."""

    return vibestack_api.list_sessions(session_root=session_root)


@router.get("/sessions/{name}", response_model=SessionResponse)
def get_session(name: str, session_root: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Return metadata for a single session."""

    session = vibestack_api.get_session(name, session_root=session_root)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


@router.post("/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(request: SessionCreateRequest) -> Dict[str, Any]:
    """Create a new session using the configured template."""

    try:
        return vibestack_api.create_session(
            request.name,
            template=request.template,
            command=request.command,
            command_args=request.command_args,
            working_dir=request.working_dir,
            description=request.description,
            session_root=request.session_root,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/sessions/{name}")
def delete_session(name: str, session_root: Optional[str] = Query(None)) -> None:
    """Terminate an existing session."""

    session = vibestack_api.get_session(name, session_root=session_root)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    vibestack_api.kill_session(name, session_root=session_root)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sessions/{name}/input", response_model=MessageResponse)
def send_session_input(
    name: str,
    request: SessionInputRequest,
    session_root: Optional[str] = Query(None),
) -> MessageResponse:
    """Send text to the tmux session backing a VibeStack session."""

    session = vibestack_api.get_session(name, session_root=session_root)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    vibestack_api.send_text(name, request.text, enter=request.enter, session_root=session_root)
    return MessageResponse(message="input queued")


@router.get("/sessions/{name}/log", response_model=SessionTailResponse)
def tail_session_log(
    name: str,
    lines: int = Query(200, ge=1, le=2000, description="Number of log lines to retrieve"),
    session_root: Optional[str] = Query(None),
) -> SessionTailResponse:
    """Return the last ``lines`` of the session log."""

    try:
        log_output = vibestack_api.tail_log(name, lines=lines, session_root=session_root)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SessionTailResponse(log=log_output)


@router.get("/jobs", response_model=List[JobRecord])
def list_jobs(session_root: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
    """Return the current job queue."""

    return vibestack_api.list_jobs(session_root=session_root)


@router.post("/jobs", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def enqueue_one_off(request: OneOffJobRequest) -> Dict[str, Any]:
    """Enqueue a one-off job using the session manager."""

    try:
        return vibestack_api.enqueue_one_off(
            request.name,
            request.command,
            template=request.template,
            description=request.description,
            session_root=request.session_root,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/templates", response_model=List[Dict[str, Any]])
def list_templates() -> List[Dict[str, Any]]:
    """Return built-in and user-provided templates."""

    return vibestack_api.list_templates()


@router.post("/templates", response_model=TemplateSaveResponse, status_code=status.HTTP_201_CREATED)
def save_template(request: TemplateSaveRequest) -> TemplateSaveResponse:
    """Persist a template definition to the user template directory."""

    include_sources = None
    if request.include_sources:
        include_sources = request.include_sources
    try:
        path = vibestack_api.save_template(
            request.payload,
            include_sources=include_sources,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TemplateSaveResponse(path=path)


@router.delete("/templates/{name}", response_model=MessageResponse)
def delete_template(name: str) -> MessageResponse:
    """Remove a user-provided template."""

    try:
        vibestack_api.delete_template(name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return MessageResponse(message="template deleted")


@link_router.api_route("/{link_id}/tail_log", methods=["GET", "POST"], response_model=SessionTailResponse)
async def link_tail_log(link_id: str, request: Request) -> SessionTailResponse:
    """Compatibility endpoint for ChatGPT link-based log tailing."""

    payload = await _gather_request_payload(request)
    name = payload.get("name") or payload.get("session")
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name is required")
    lines = _coerce_int(payload.get("lines"), 200)
    session_root = payload.get("session_root")
    try:
        log_output = vibestack_api.tail_log(name, lines=lines, session_root=session_root)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SessionTailResponse(log=log_output)


@link_router.api_route("/{link_id}/send_input", methods=["GET", "POST"], response_model=MessageResponse)
async def link_send_input(link_id: str, request: Request) -> MessageResponse:
    """Compatibility endpoint for ChatGPT link-based terminal input."""

    payload = await _gather_request_payload(request)
    name = payload.get("name") or payload.get("session")
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name is required")
    if "text" in payload:
        text = payload.get("text")
    else:
        text = payload.get("input")
    if text is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="text is required")
    enter = _coerce_bool(payload.get("enter"), default=True)
    session_root = payload.get("session_root")
    vibestack_api.send_text(name, str(text), enter=enter, session_root=session_root)
    return MessageResponse(message="input queued")


app = FastAPI(
    title="VibeStack REST API",
    description="HTTP interface for the VibeStack session manager",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(link_router)
