"""FastAPI application exposing the VibeStack Python API via REST."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, FastAPI, HTTPException, Query, Response, status
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


app = FastAPI(
    title="VibeStack REST API",
    description="HTTP interface for the VibeStack session manager",
    version="1.0.0",
)
app.include_router(router)
