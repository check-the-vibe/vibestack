from __future__ import annotations

import argparse
import json
import sys

from .manager import SessionManager


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vibe", description="Manage tmux sessions for VibeStack")
    parser.add_argument("--root", help="Session root directory", default=None)

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List known sessions")

    attach_parser = subparsers.add_parser("attach", help="Attach to an existing session via tmux")
    attach_parser.add_argument("name", help="Session name")

    show_parser = subparsers.add_parser("show", help="Show metadata for a session")
    show_parser.add_argument("name", help="Session name")

    create_parser = subparsers.add_parser("create", help="Create a long-running session")
    create_parser.add_argument("name", help="Session name")
    create_parser.add_argument("--template", default="bash", help="Template key to base the command on")
    create_parser.add_argument("--command", dest="command_override", help="Override command to run in the session")
    create_parser.add_argument("--description", help="Optional description")
    create_parser.add_argument("--workdir", help="Working directory for the session")

    oneoff_parser = subparsers.add_parser("one-off", help="Run a one-off command inside tmux")
    oneoff_parser.add_argument("name", help="Session name")
    oneoff_parser.add_argument("command", help="Command to execute")
    oneoff_parser.add_argument("--workdir", help="Working directory for the session")

    send_parser = subparsers.add_parser("send", help="Send text to a session pane")
    send_parser.add_argument("name", help="Session name")
    send_parser.add_argument("text", help="Text to send")
    send_parser.add_argument("--no-enter", action="store_true", help="Do not append ENTER")

    kill_parser = subparsers.add_parser("kill", help="Terminate an active session")
    kill_parser.add_argument("name", help="Session name")

    logs_parser = subparsers.add_parser("logs", help="Tail a session log")
    logs_parser.add_argument("name", help="Session name")
    logs_parser.add_argument("--lines", type=int, default=200, help="Number of log lines")

    subparsers.add_parser("jobs", help="List queued jobs")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    manager = SessionManager(session_root=args.root)

    if args.command == "list":
        payload = [meta.to_dict() for meta in manager.list_sessions()]
        print(json.dumps(payload, indent=2))
        return 0

    if args.command == "show":
        metadata = manager.get_session(args.name)
        if not metadata:
            parser.error(f"session '{args.name}' not found")
        print(json.dumps(metadata.to_dict(), indent=2))
        return 0

    if args.command == "attach":
        try:
            manager.attach_session(args.name)
        except ValueError as exc:
            parser.error(str(exc))
        except RuntimeError as exc:
            parser.error(str(exc))
        return 0

    if args.command == "create":
        metadata = manager.create_session(
            args.name,
            template=args.template,
            command=args.command_override,
            description=args.description,
            working_dir=args.workdir,
        )
        print(json.dumps(metadata.to_dict(), indent=2))
        return 0

    if args.command == "one-off":
        metadata = manager.enqueue_one_off(
            args.name,
            args.command,
            working_dir=args.workdir,
        )
        print(json.dumps(metadata.to_dict(), indent=2))
        return 0

    if args.command == "send":
        manager.send_text(args.name, args.text, enter=not args.no_enter)
        return 0

    if args.command == "kill":
        manager.kill_session(args.name)
        return 0

    if args.command == "logs":
        print(manager.tail_log(args.name, lines=args.lines))
        return 0

    if args.command == "jobs":
        print(json.dumps(manager.list_jobs(), indent=2))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
