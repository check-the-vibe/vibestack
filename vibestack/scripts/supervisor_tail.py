"""Small CLI to tail supervisor program logs using the centralized helper.

Usage:
    python -m vibestack.scripts.supervisor_tail --program <program_name>

This streams the last N lines and then follows the log via the centralized helper (which invokes the system supervisor control tool when necessary).
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import List

from vibestack.scripts.supervisor_helper import run_supervisor_command, spawn_supervisor_process


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tail supervisord program logs")
    parser.add_argument("--program", required=True, help="Supervisor program name to tail")
    parser.add_argument("--lines", type=int, default=200, help="Number of lines to show initially")
    args = parser.parse_args(argv)

    program = args.program
    lines = args.lines

    # Try to capture last N lines
    rc, out, err = run_supervisor_command(["tail", f"-{lines}", program])
    if rc == 0 and out:
        sys.stdout.write(out)
        sys.stdout.flush()
    else:
        # If the helper's tail failed, print stderr for diagnosis
        if err:
            sys.stderr.write(err)
            sys.stderr.flush()

    # Now follow — attempt to spawn a live supervisor tail subprocess via the helper (spawned with proper privilege handling).
    proc = spawn_supervisor_process(["tail", "-f", program])
    try:
        if proc is None:
            # Could not spawn streaming process; fall back to helper (blocking).
            rc2, out2, err2 = run_supervisor_command(["tail", "-f", program])
            if rc2 == 0 and out2:
                sys.stdout.write(out2)
                sys.stdout.flush()
            elif err2:
                sys.stderr.write(err2)
                sys.stderr.flush()
            return 0

        # Stream stdout lines until process exits or user interrupts
        while True:
            if proc.stdout is None:
                break
            line = proc.stdout.readline()
            if line:
                sys.stdout.write(line)
                sys.stdout.flush()
                continue
            # no line available; check if process ended
            if proc.poll() is not None:
                # Drain remaining stderr for diagnostics
                if proc.stderr is not None:
                    err_rem = proc.stderr.read()
                    if err_rem:
                        sys.stderr.write(err_rem)
                        sys.stderr.flush()
                break
            time.sleep(0.1)
    except KeyboardInterrupt:
        try:
            if proc is not None:
                proc.terminate()
                proc.wait(timeout=2)
        except Exception:
            pass
        return 0
    finally:
        # Ensure child process cleanup
        try:
            if proc is not None and proc.poll() is None:
                proc.terminate()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
