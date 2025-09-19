from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import ISO_FORMAT, SessionMetadata, SessionType
from .storage import SessionStorage


class SessionManager:
    """Coordinates tmux session lifecycle and persistence."""

    DEFAULT_TEMPLATES: Dict[str, Dict[str, str]] = {
        "bash": {
            "command": "",
            "label": "Bash shell",
            "default_type": SessionType.LONG_RUNNING.value,
        },
        "claude": {
            "command": "claude",
            "label": "Claude CLI",
            "default_type": SessionType.LONG_RUNNING.value,
            "include_files": [
                {"source": "CLAUDE.md", "target": "CLAUDE.md"},
                {"source": "TASKS.md", "target": "TASKS.md"}
            ],
        },
        "codex": {
            "command": "codex",
            "label": "Codex CLI",
            "default_type": SessionType.LONG_RUNNING.value,
            "include_files": [
                {"source": "AGENTS.md", "target": "AGENTS.md"},
                {"source": "TASKS.md", "target": "TASKS.md"}
            ],
        },
        "script": {
            "command": "bash --login",
            "label": "One-off script",
            "default_type": SessionType.ONE_OFF.value,
        },
    }

    def __init__(self, session_root: Optional[Path | str] = None) -> None:
        repo_root = Path(os.environ.get("VIBESTACK_HOME") or Path.cwd())
        root = Path(
            session_root
            or os.environ.get("VIBESTACK_SESSION_ROOT")
            or Path.home() / "sessions"
        )
        self.repo_root = repo_root
        self.storage = SessionStorage(root)
        default_template_dir = repo_root / "vibestack" / "templates"
        template_dir_env = os.environ.get("VIBESTACK_TEMPLATE_DIR")
        self.template_dir = Path(template_dir_env) if template_dir_env else default_template_dir
        user_template_dir_env = os.environ.get("VIBESTACK_USER_TEMPLATE_DIR")
        self.user_template_dir = Path(user_template_dir_env) if user_template_dir_env else Path.home() / ".vibestack" / "templates"
        default_asset_dir = repo_root / "vibestack" / "assets"
        asset_dir_env = os.environ.get("VIBESTACK_ASSET_DIR")
        self.asset_dir = Path(asset_dir_env) if asset_dir_env else default_asset_dir
        user_asset_dir_env = os.environ.get("VIBESTACK_USER_ASSET_DIR")
        self.user_asset_dir = Path(user_asset_dir_env) if user_asset_dir_env else Path.home() / ".vibestack" / "assets"
        self.template_dir.mkdir(parents=True, exist_ok=True)
        self.user_template_dir.mkdir(parents=True, exist_ok=True)
        self.asset_dir.mkdir(parents=True, exist_ok=True)
        self.user_asset_dir.mkdir(parents=True, exist_ok=True)
        self.template_sources: Dict[str, str] = {key: "built-in" for key in self.DEFAULT_TEMPLATES}
        self.templates = self._load_templates()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def list_sessions(self) -> List[SessionMetadata]:
        sessions = self.storage.list_sessions()
        for metadata in sessions:
            self._refresh_status(metadata)
        return sessions

    def get_session(self, name: str) -> Optional[SessionMetadata]:
        metadata = self.storage.load(name)
        if metadata:
            self._refresh_status(metadata)
        return metadata

    def list_jobs(self) -> List[Dict[str, str]]:
        return self.storage.list_jobs()

    def create_session(
        self,
        name: str,
        *,
        template: str = "bash",
        command: Optional[str] = None,
        session_type: Optional[SessionType] = None,
        description: Optional[str] = None,
        working_dir: Optional[str | Path] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> SessionMetadata:
        if self._session_exists(name):
            raise ValueError(f"tmux session '{name}' already exists")

        template_config = self.templates.get(template, {
            "command": command,
            "label": template,
            "default_type": SessionType.LONG_RUNNING.value,
        })
        if command is not None:
            resolved_command = command
        else:
            template_command = template_config.get("command")
            resolved_command = template_command if template_command is not None else ""
        default_type_value = template_config.get("default_type", SessionType.LONG_RUNNING.value)
        try:
            resolved_type = session_type or SessionType(default_type_value)
        except ValueError:
            resolved_type = session_type or SessionType.LONG_RUNNING
        resolved_working_dir = working_dir or template_config.get("working_dir")
        resolved_description = description or template_config.get("description")
        template_env = template_config.get("env") or {}
        merged_env: Dict[str, str] = {str(k): str(v) for k, v in template_env.items()} if template_env else {}
        if env:
            merged_env.update({str(k): str(v) for k, v in env.items()})

        created_at = datetime.utcnow().strftime(ISO_FORMAT)
        session_dir = self.storage.session_dir(name)
        log_path = self.storage.log_path(name)
        workspace_path = self.storage.workspace_path(name)

        metadata = SessionMetadata(
            name=name,
            command=resolved_command,
            template=template,
            session_type=resolved_type,
            status="queued",
            created_at=created_at,
            updated_at=created_at,
            log_path=str(log_path),
            workspace_path=str(workspace_path),
            description=resolved_description,
        )
        metadata.ensure_paths()
        if not resolved_working_dir:
            resolved_working_dir = metadata.workspace_path
        self._apply_template_artifacts(metadata, template_config)
        job_id = uuid.uuid4().hex
        job_record = {
            "id": job_id,
            "session": name,
            "template": template,
            "command": resolved_command,
            "status": "queued",
            "created_at": created_at,
            "updated_at": created_at,
        }
        self.storage.add_job(job_record)
        metadata.job_id = job_id
        self.storage.save(metadata)

        self._launch_session(metadata, working_dir=resolved_working_dir, extra_env=merged_env or None)
        self.storage.update_job_status(job_id, "running")
        metadata.status = "running"
        metadata.touch()
        self.storage.save(metadata)
        return metadata

    def enqueue_one_off(
        self,
        name: str,
        command: str,
        *,
        template: str = "script",
        description: Optional[str] = None,
        working_dir: Optional[str | Path] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> SessionMetadata:
        return self.create_session(
            name,
            template=template,
            command=command,
            session_type=SessionType.ONE_OFF,
            description=description,
            working_dir=working_dir,
            env=env,
        )

    def send_text(self, name: str, text: str, *, enter: bool = True) -> None:
        target = f"{name}:0.0"
        payload = [f"{text}\r"] if enter else [text]
        self._run_tmux(["send-keys", "-t", target, *payload])

    def kill_session(self, name: str) -> None:
        if not self._session_exists(name):
            return
        self._run_tmux(["kill-session", "-t", name])
        metadata = self.storage.load(name)
        if metadata:
            metadata.status = "stopped"
            metadata.touch()
            self.storage.save(metadata)
            if metadata.job_id:
                self.storage.update_job_status(metadata.job_id, "stopped")

    def tail_log(self, name: str, lines: int = 200) -> str:
        metadata = self.storage.load(name)
        if not metadata:
            raise ValueError(f"Unknown session '{name}'")
        path = Path(metadata.log_path)
        if not path.exists():
            return ""
        try:
            content = path.read_text()
        except UnicodeDecodeError:
            content = path.read_bytes().decode("utf-8", errors="replace")
        logs = content.splitlines()[-lines:]
        return "\n".join(logs)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _session_exists(self, name: str) -> bool:
        result = subprocess.run(
            ["tmux", "has-session", "-t", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0

    def _launch_session(
        self,
        metadata: SessionMetadata,
        *,
        working_dir: Optional[str | Path] = None,
        extra_env: Optional[Dict[str, str]] = None,
    ) -> None:
        env = os.environ.copy()
        if extra_env:
            env.update({str(k): str(v) for k, v in extra_env.items()})

        session_name = metadata.name
        session_dir = self.storage.session_dir(session_name)
        session_dir.mkdir(parents=True, exist_ok=True)
        log_path = Path(metadata.log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.touch(exist_ok=True)

        # Start detached session with a login shell so interactive templates still work.
        self._run_tmux(
            [
                "tmux",
                "new-session",
                "-d",
                "-s",
                session_name,
                "bash",
                "--login",
            ],
            env=env,
        )
        self._run_tmux(["set-option", "-t", session_name, "status", "off"], env=env)

        target = f"{session_name}:0.0"

        if metadata.session_type is SessionType.ONE_OFF:
            script_path = self._prepare_short_run_script(metadata, session_dir, log_path, working_dir)
            command_str = f"exec {shlex.quote(str(script_path))}"
            self._run_tmux(
                [
                    "respawn-pane",
                    "-k",
                    "-t",
                    target,
                    "bash",
                    "--login",
                    "-c",
                    command_str,
                ],
                env=env,
            )
            return

        # Attach pipe-pane to capture output
        self._run_tmux(
            [
                "pipe-pane",
                "-t",
                target,
                "-o",
                f"cat >> {shlex.quote(str(log_path))}",
            ],
            env=env,
        )
        if metadata.session_type is SessionType.ONE_OFF:
            script_path = self._prepare_short_run_script(metadata, session_dir, log_path, working_dir)
            command_str = f"exec {shlex.quote(str(script_path))}"
            self._run_tmux(
                [
                    "respawn-pane",
                    "-k",
                    "-t",
                    target,
                    "bash",
                    "--login",
                    "-c",
                    command_str,
                ],
                env=env,
            )
            return

        # Long-running sessions continue to use send-keys so users can interact afterwards.
        if working_dir:
            self._run_tmux(
                [
                    "send-keys",
                    "-t",
                    target,
                    f"cd {shlex.quote(str(Path(working_dir)))}",
                    "C-m",
                ],
                env=env,
            )

        if metadata.command and str(metadata.command).strip():
            self._run_tmux(
                [
                    "send-keys",
                    "-t",
                    target,
                    metadata.command,
                    "C-m",
                ],
                env=env,
            )

    def _prepare_short_run_script(
        self,
        metadata: SessionMetadata,
        session_dir: Path,
        log_path: Path,
        working_dir: Optional[str | Path],
    ) -> Path:
        session_dir.mkdir(parents=True, exist_ok=True)
        script_path = session_dir / "run-once.sh"
        result_path = session_dir / "result.json"
        result_path.unlink(missing_ok=True)
        result_path.parent.mkdir(parents=True, exist_ok=True)

        workdir = Path(working_dir) if working_dir else None
        cd_line = ""
        if workdir:
            cd_line = f"cd {shlex.quote(str(workdir))} || exit 1"

        script_lines = [
            "#!/usr/bin/env bash",
            "set -uo pipefail",
            f'LOG_PATH={shlex.quote(str(log_path))}',
            f'RESULT_PATH={shlex.quote(str(result_path))}',
            'START_TS=$(date -u +"%Y-%m-%dT%H:%M:%S.%3NZ")',
            'cleanup() {',
            '  local exit_code=$?',
            '  trap - EXIT',
            '  local end_ts=$(date -u +"%Y-%m-%dT%H:%M:%S.%3NZ")',
            '  printf "[vibestack] session exited with code %s at %s\\n" "$exit_code" "$end_ts" >> "$LOG_PATH"',
            '  printf \'{"exit_code": %s, "started_at": "%s", "finished_at": "%s", "message": "session exited with code %s"}\\n\' "$exit_code" "$START_TS" "$end_ts" "$exit_code" > "$RESULT_PATH"',
            '  exit "$exit_code"',
            '}',
            'trap cleanup EXIT',
        ]
        if cd_line:
            script_lines.append(cd_line)
        script_lines.append(metadata.command)

        script_content = "\n".join(script_lines) + "\n"
        script_path.write_text(script_content, encoding="utf-8")
        script_path.chmod(0o755)
        return script_path

    def _load_templates(self) -> Dict[str, Dict[str, str]]:
        templates: Dict[str, Dict[str, str]] = {key: value.copy() for key, value in self.DEFAULT_TEMPLATES.items()}
        sources: Dict[str, str] = {key: "built-in" for key in self.DEFAULT_TEMPLATES}
        candidate_dirs = [self.template_dir, self.user_template_dir]
        for template_dir in candidate_dirs:
            if not template_dir or not template_dir.exists():
                continue
            for file in sorted(template_dir.glob('*.json')):
                try:
                    payload = json.loads(file.read_text(encoding='utf-8'))
                except json.JSONDecodeError:
                    continue
                key = payload.get('name') or file.stem
                command = payload.get('command', '')
                templates[key] = {
                    'command': command,
                    'label': payload.get('label', key),
                    'default_type': payload.get('session_type', SessionType.LONG_RUNNING.value),
                    'working_dir': payload.get('working_dir'),
                    'description': payload.get('description'),
                    'env': payload.get('env'),
                    'post_create': payload.get('post_create'),
                    'include_files': payload.get('include_files'),
                }
                sources[key] = str(file)
        self.template_sources = sources
        return templates

    def _apply_template_artifacts(self, metadata: SessionMetadata, template_config: Dict[str, str]) -> None:
        workspace = Path(metadata.workspace_path)
        workspace.mkdir(parents=True, exist_ok=True)
        include_entries = []
        files_config = template_config.get('include_files')
        if isinstance(files_config, list):
            include_entries.extend(files_config)
        has_tasks = False
        for entry in include_entries:
            if isinstance(entry, str):
                target_name = Path(entry).name
            else:
                target_name = entry.get('target') or entry.get('source')
            if target_name and target_name.lower() == 'tasks.md':
                has_tasks = True
                break
        if not has_tasks:
            include_entries.append({'source': 'TASKS.md', 'target': 'TASKS.md'})
        search_roots: List[Path] = [self.asset_dir, self.user_asset_dir, self.repo_root]
        for entry in include_entries:
            if isinstance(entry, str):
                source_ref = entry
                target_name = Path(entry).name
            else:
                source_ref = entry.get('source')
                target_name = entry.get('target') or (Path(source_ref).name if source_ref else None)
            if not source_ref or not target_name:
                continue
            source_path = self._resolve_asset_file(source_ref, search_roots)
            if not source_path or not source_path.exists():
                continue
            destination = workspace / target_name
            if destination.exists():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(source_path, destination)

    def _resolve_asset_file(self, reference: str, search_roots: List[Path]) -> Optional[Path]:
        candidate = Path(reference)
        if candidate.is_absolute() and candidate.exists():
            return candidate
        for root in search_roots:
            if not root:
                continue
            potential = root / reference
            if potential.exists():
                return potential
        return None

    def list_templates(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for name, config in sorted(self.templates.items(), key=lambda item: (item[1].get('label') or item[0]).lower()):
            entry = dict(config)
            entry['name'] = name
            entry['source'] = self.template_sources.get(name, 'user')
            results.append(entry)
        return results

    def refresh_templates(self) -> None:
        self.templates = self._load_templates()

    def save_template(self, payload: Dict[str, Any], include_sources: Optional[List[Path]] = None) -> Path:
        name = payload.get('name')
        if not name:
            raise ValueError('Template name is required')

        include_entries = payload.get('include_files') or []
        processed_entries: List[Any] = []
        for entry in include_entries:
            if isinstance(entry, str):
                processed_entries.append(entry)
            elif isinstance(entry, dict):
                processed_entries.append({k: v for k, v in entry.items() if v})

        if include_sources:
            asset_root = self.user_asset_dir / name
            asset_root.mkdir(parents=True, exist_ok=True)
            for source_path in include_sources:
                if not source_path.exists() or not source_path.is_file():
                    continue
                destination = asset_root / source_path.name
                destination.write_bytes(source_path.read_bytes())
                processed_entries.append({"source": f"{name}/{source_path.name}", "target": source_path.name})

        payload = dict(payload)
        payload['include_files'] = processed_entries

        destination = self.user_template_dir / f"{name}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')
        self.refresh_templates()
        return destination

    def delete_template(self, name: str) -> None:
        source = self.template_sources.get(name)
        if not source or source == 'built-in':
            raise ValueError(f"Template '{name}' cannot be deleted (not a user template)")
        template_path = Path(source)
        if template_path.exists():
            template_path.unlink()
        self.refresh_templates()

    def _run_tmux(self, args: List[str], env: Optional[Dict[str, str]] = None) -> None:
        command = ["tmux", *args] if args and args[0] != "tmux" else args
        result = subprocess.run(command, env=env)
        if result.returncode != 0:
            raise RuntimeError(f"tmux command failed: {' '.join(command)}")

    def _refresh_status(self, metadata: SessionMetadata) -> None:
        metadata.runtime = {}
        exists = self._session_exists(metadata.name)
        if exists:
            metadata.runtime = self._collect_tmux_runtime(metadata.name)
            if metadata.status not in {"running", "starting"}:
                metadata.status = "running"
                metadata.touch()
                self.storage.save(metadata)
                if metadata.job_id:
                    self.storage.update_job_status(metadata.job_id, "running")
            return

        if metadata.session_type is SessionType.ONE_OFF:
            result_path = self.storage.session_dir(metadata.name) / "result.json"
            exit_code: Optional[int] = None
            finished_at: Optional[str] = None
            message: Optional[str] = None
            if result_path.exists():
                try:
                    payload = json.loads(result_path.read_text(encoding="utf-8"))
                    exit_code = int(payload.get("exit_code"))
                    finished_at = payload.get("finished_at")
                    message = payload.get("message")
                except (ValueError, json.JSONDecodeError, TypeError):
                    exit_code = None
            if exit_code is not None:
                metadata.exit_code = exit_code
                metadata.status = "completed" if exit_code == 0 else "failed"
                if finished_at:
                    metadata.updated_at = finished_at
                else:
                    metadata.touch()
                metadata.last_message = message or f"session exited with code {exit_code}"
                self.storage.save(metadata)
                if metadata.job_id:
                    job_status = "completed" if exit_code == 0 else "failed"
                    self.storage.update_job_status(metadata.job_id, job_status, message=metadata.last_message)
                return
            if metadata.status not in {"completed", "failed"}:
                metadata.status = "completed"
                metadata.touch()
                self.storage.save(metadata)
                if metadata.job_id:
                    self.storage.update_job_status(metadata.job_id, "completed")
            return

        if metadata.status != "stopped":
            metadata.status = "stopped"
            metadata.touch()
            self.storage.save(metadata)
            if metadata.job_id:
                self.storage.update_job_status(metadata.job_id, "stopped")

    def _capture_tmux(self, args: List[str], env: Optional[Dict[str, str]] = None) -> str:
        command = ["tmux", *args] if args and args[0] != "tmux" else args
        result = subprocess.run(
            command,
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()

    def _collect_tmux_runtime(self, session_name: str) -> Dict[str, Any]:
        runtime: Dict[str, Any] = {}

        panes_output = self._capture_tmux([
            "list-panes",
            "-t",
            session_name,
            "-F",
            "#{pane_id}\t#{pane_index}\t#{pane_active}\t#{pane_current_command}\t#{pane_current_path}",
        ])
        panes: List[Dict[str, Any]] = []
        active_pane: Optional[Dict[str, Any]] = None
        for line in panes_output.splitlines():
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 5:
                continue
            pane_id, index, active, command, path = parts
            pane_record = {
                "pane_id": pane_id,
                "pane_index": int(index) if index.isdigit() else index,
                "active": active == "1",
                "pane_current_command": command or None,
                "pane_current_path": path or None,
            }
            panes.append(pane_record)
            if pane_record["active"] and active_pane is None:
                active_pane = pane_record
        if panes:
            runtime["tmux_panes"] = panes
        if active_pane:
            runtime["active_pane_id"] = active_pane.get("pane_id")
            runtime["pane_current_command"] = active_pane.get("pane_current_command")
            runtime["pane_current_path"] = active_pane.get("pane_current_path")

        clients_output = self._capture_tmux([
            "list-clients",
            "-t",
            session_name,
            "-F",
            "#{client_tty}\t#{client_last_activity}\t#{client_width}\t#{client_height}",
        ])
        clients: List[Dict[str, Any]] = []
        latest_activity_epoch: Optional[int] = None
        for line in clients_output.splitlines():
            if not line:
                continue
            tty, last_activity, width, height = (line.split("\t") + ["", "", "", ""])[:4]
            try:
                last_activity_epoch = int(last_activity)
            except (TypeError, ValueError):
                last_activity_epoch = 0
            last_activity_iso = self._epoch_to_iso(last_activity_epoch)
            try:
                width_val = int(width)
            except (TypeError, ValueError):
                width_val = None
            try:
                height_val = int(height)
            except (TypeError, ValueError):
                height_val = None
            clients.append(
                {
                    "client_tty": tty or None,
                    "client_last_activity_epoch": last_activity_epoch or None,
                    "client_last_activity": last_activity_iso,
                    "client_width": width_val,
                    "client_height": height_val,
                }
            )
            if last_activity_epoch:
                if latest_activity_epoch is None or last_activity_epoch > latest_activity_epoch:
                    latest_activity_epoch = last_activity_epoch
        if clients:
            runtime["tmux_clients"] = clients

        session_last_attached_raw = self._capture_tmux([
            "display-message",
            "-t",
            session_name,
            "-p",
            "#{session_last_attached}",
        ])
        session_last_attached_iso = self._epoch_to_iso(session_last_attached_raw)
        if session_last_attached_iso:
            runtime["session_last_attached"] = session_last_attached_iso

        session_attached_raw = self._capture_tmux([
            "display-message",
            "-t",
            session_name,
            "-p",
            "#{session_attached}",
        ])
        if session_attached_raw:
            runtime["session_attached"] = session_attached_raw == "1"

        if latest_activity_epoch:
            runtime["client_last_activity"] = self._epoch_to_iso(latest_activity_epoch)
        elif session_last_attached_iso:
            runtime["client_last_activity"] = session_last_attached_iso

        return runtime

    @staticmethod
    def _epoch_to_iso(value: Any) -> Optional[str]:
        try:
            epoch = int(value)
        except (TypeError, ValueError):
            return None
        if epoch <= 0:
            return None
        return datetime.utcfromtimestamp(epoch).strftime(ISO_FORMAT)
