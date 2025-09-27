#!/usr/bin/env python3
"""Terminal UI for browsing supervisord logs."""
from __future__ import annotations

import curses
import subprocess
from dataclasses import dataclass
from typing import List, Sequence

STATUS_COMMAND: Sequence[str] = ("sudo", "supervisorctl", "status")
TAIL_COMMAND_PREFIX: Sequence[str] = ("sudo", "supervisorctl", "tail", "-200")


@dataclass
class ProgramLogs:
    name: str
    lines: List[str]
    error: str | None = None


def _run_command(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=True)


def parse_status_output(raw: str) -> List[str]:
    programs: List[str] = []
    for line in raw.splitlines():
        normalized = line.strip()
        if not normalized:
            continue
        parts = normalized.split()
        if parts:
            programs.append(parts[0])
    return programs


def list_programs() -> List[str]:
    result = _run_command(STATUS_COMMAND)
    return parse_status_output(result.stdout)


def _format_error(exc: subprocess.CalledProcessError) -> str:
    return exc.stderr.strip() or exc.stdout.strip() or str(exc)


def tail_program_logs(program: str) -> ProgramLogs:
    try:
        result = _run_command(tuple(TAIL_COMMAND_PREFIX) + (program,))
        lines = result.stdout.rstrip("\n").splitlines()
        return ProgramLogs(name=program, lines=lines)
    except subprocess.CalledProcessError as exc:  # pragma: no cover - surfaced in UI
        return ProgramLogs(name=program, lines=[], error=_format_error(exc))


def _render_program(
    stdscr: "curses._CursesWindow", data: ProgramLogs, index: int, total: int
) -> None:
    stdscr.clear()
    height, width = stdscr.getmaxyx()
    header = (
        f"Supervisor logs ({index + 1}/{total}): {data.name}"
        if total
        else "Supervisor logs"
    )
    instructions = "←/→ switch • r refresh • R reload list • q quit"
    stdscr.addnstr(0, 0, header, width - 1)
    stdscr.addnstr(1, 0, instructions, width - 1)

    if data.error:
        stdscr.addnstr(3, 0, f"Error: {data.error}", width - 1)
        stdscr.refresh()
        return

    available_rows = height - 3
    if available_rows <= 0:
        stdscr.refresh()
        return

    start_row = 3
    lines = data.lines[-available_rows:]
    for offset, line in enumerate(lines):
        stdscr.addnstr(start_row + offset, 0, line, width - 1)
    stdscr.refresh()


def _render_empty_state(stdscr: "curses._CursesWindow", message: str) -> None:
    stdscr.clear()
    height, width = stdscr.getmaxyx()
    stdscr.addnstr(0, 0, "Supervisor logs", width - 1)
    stdscr.addnstr(1, 0, "No supervisord programs detected.", width - 1)
    stdscr.addnstr(3, 0, message, width - 1)
    stdscr.refresh()


def _cycle(current: int, total: int, direction: int) -> int:
    if total == 0:
        return 0
    return (current + direction) % total


def _main(stdscr: "curses._CursesWindow") -> None:
    try:
        curses.curs_set(0)
    except curses.error:  # pragma: no cover
        pass
    stdscr.nodelay(False)
    stdscr.keypad(True)

    try:
        programs = list_programs()
    except (
        subprocess.CalledProcessError
    ) as exc:  # pragma: no cover - surfaced interactively
        _render_empty_state(
            stdscr, f"Unable to query supervisorctl: {_format_error(exc)}"
        )
        stdscr.getch()
        return

    if not programs:
        _render_empty_state(stdscr, "Check supervisord.conf for program definitions.")
        stdscr.getch()
        return

    index = 0
    data = tail_program_logs(programs[index])
    _render_program(stdscr, data, index, len(programs))

    while True:
        ch = stdscr.getch()
        if ch in (ord("q"), ord("Q")):
            break
        if ch in (curses.KEY_RIGHT, ord("l")):
            index = _cycle(index, len(programs), 1)
            data = tail_program_logs(programs[index])
            _render_program(stdscr, data, index, len(programs))
            continue
        if ch in (curses.KEY_LEFT, ord("h")):
            index = _cycle(index, len(programs), -1)
            data = tail_program_logs(programs[index])
            _render_program(stdscr, data, index, len(programs))
            continue
        if ch in (ord("r"), ord("R")):
            if ch == ord("R"):
                try:
                    programs = list_programs()
                except subprocess.CalledProcessError as exc:  # pragma: no cover
                    data = ProgramLogs(
                        name=data.name, lines=[], error=_format_error(exc)
                    )
                    _render_program(stdscr, data, index, len(programs))
                    continue
                if not programs:
                    _render_empty_state(stdscr, "No programs available after refresh.")
                    stdscr.getch()
                    return
                index = min(index, len(programs) - 1)
            data = tail_program_logs(programs[index])
            _render_program(stdscr, data, index, len(programs))


def main() -> None:
    curses.wrapper(_main)


if __name__ == "__main__":
    main()
