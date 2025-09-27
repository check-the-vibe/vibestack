"""CLI entry point for startup session provisioning."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import List

from vibestack.startup.sessions import ensure_startup_sessions

DEFAULT_BASE_URL = os.environ.get("VIBESTACK_API_BASE", "http://127.0.0.1:9000")
SESSIONS_PATH = "/api/sessions"


def _wait_for_api(base_url: str, timeout: float, interval: float) -> bool:
    deadline = time.monotonic() + timeout
    url = urllib.parse.urljoin(base_url.rstrip("/"), SESSIONS_PATH)

    while True:
        try:
            with urllib.request.urlopen(url, timeout=interval) as response:
                if 200 <= response.status < 500:
                    # The API responded — that's sufficient for our purposes.
                    return True
        except (urllib.error.URLError, urllib.error.HTTPError):
            pass

        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Provision startup tmux sessions")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Base URL for the VibeStack REST API",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Seconds to wait for the API (default: 60)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Polling interval while waiting (default: 2)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON describing the sessions that were ensured",
    )
    return parser


def main(argv: List[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    print(
        f"[startup] Waiting for API at {args.base_url} (timeout {args.timeout}s, interval {args.interval}s)...",
        flush=True,
    )

    if not _wait_for_api(args.base_url, args.timeout, args.interval):
        print("[startup] API did not become ready in time", file=sys.stderr)
        return 1

    print("[startup] API ready — ensuring startup sessions...", flush=True)

    sessions = ensure_startup_sessions()

    if args.json:
        payload = [session.to_dict() for session in sessions]
        print(json.dumps(payload, indent=2))
    else:
        if sessions:
            for session in sessions:
                print(
                    f"[startup] ensured session: {session.name} ({session.template})",
                    flush=True,
                )
        else:
            print("[startup] no startup sessions configured", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
