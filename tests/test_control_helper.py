from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "control"))
import controllib as lib  # noqa: E402


XRANDR = """\
Screen 0: minimum 320 x 200, current 1440 x 900, maximum 1920 x 1200
screen connected 1440x900+0+0 0mm x 0mm
   1920x1200    60.00
   1600x1200    60.00
   1600x900     60.00
   1440x900     60.00*
   1368x768     60.00
   1280x800     60.00
"""


def completed(argv, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


class ScriptedRunner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class DisplayTests(unittest.TestCase):
    def test_parse_xrandr_finds_connected_output_current_and_modes(self):
        state = lib.parse_xrandr(XRANDR)
        self.assertEqual("screen", state.output)
        self.assertEqual("1440x900", state.resolution)
        self.assertEqual(1920, state.maximum_width)
        self.assertEqual(1200, state.maximum_height)
        self.assertEqual(set(lib.SUPPORTED_RESOLUTIONS), set(state.advertised_resolutions))
        self.assertEqual(
            {
                "minWidth": 640,
                "minHeight": 480,
                "maxWidth": 1920,
                "maxHeight": 1200,
                "widthStep": 8,
                "heightStep": 2,
            },
            state.payload()["bounds"],
        )

    def test_parse_xrandr_requires_maximum_framebuffer_dimensions(self):
        missing_maximum = XRANDR.replace(", maximum 1920 x 1200", "")
        with self.assertRaises(lib.ControlError) as caught:
            lib.parse_xrandr(missing_maximum)
        self.assertEqual("display_probe_failed", caught.exception.code)

    def test_set_display_uses_only_validated_output_and_exact_mode(self):
        changed = XRANDR.replace("1440x900+0+0", "1280x800+0+0").replace(
            "1440x900     60.00*", "1440x900     60.00"
        ).replace("1280x800     60.00", "1280x800     60.00*")
        runner = ScriptedRunner(
            [
                completed([], stdout=XRANDR),
                completed([], stdout=""),
                completed([], stdout=changed),
            ]
        )
        backend = lib.ControlBackend(runner=runner)
        payload = backend.set_display("1280x800")
        self.assertEqual("1280x800", payload["resolution"])
        self.assertEqual(
            [lib.XRANDR, "--output", "screen", "--mode", "1280x800"],
            runner.calls[1][0],
        )
        self.assertNotIn("shell", runner.calls[1][1])

    def test_set_display_creates_bounded_unadvertised_mode(self):
        changed = XRANDR.replace(
            "Screen 0: minimum 320 x 200, current 1440 x 900, maximum 1920 x 1200",
            "Screen 0: minimum 320 x 200, current 1256 x 600, maximum 1920 x 1200",
        ).replace("screen connected 1440x900+0+0", "screen connected 1256x600+0+0")
        changed = changed.replace("1440x900     60.00*", "1440x900     60.00")
        changed += "   1256x600     59.80*\n"
        modeline = (
            'Modeline "1256x600_60.00" 61.50 1256 1328 1456 1656 '
            "600 603 613 622 -hsync +vsync\n"
        )
        runner = ScriptedRunner(
            [
                completed([], stdout=XRANDR),
                completed([], stdout=modeline),
                completed([]),
                completed([]),
                completed([]),
                completed([], stdout=changed),
            ]
        )
        backend = lib.ControlBackend(runner=runner)
        payload = backend.set_display("1256x600")
        self.assertEqual("1256x600", payload["resolution"])
        self.assertTrue(payload["dynamicResize"])
        self.assertEqual([lib.CVT, "1256", "600", "60"], runner.calls[1][0])
        self.assertEqual(
            [lib.XRANDR, "--addmode", "screen", "1256x600"],
            runner.calls[3][0],
        )
        self.assertEqual(
            [lib.XRANDR, "--output", "screen", "--mode", "1256x600"],
            runner.calls[4][0],
        )
        self.assertTrue(all("shell" not in call[1] for call in runner.calls))

    def test_set_display_rejects_resolution_above_xrandr_framebuffer_maximum(self):
        constrained = XRANDR.replace(
            "maximum 1920 x 1200", "maximum 1600 x 900"
        )
        runner = ScriptedRunner([completed([], stdout=constrained)])
        backend = lib.ControlBackend(runner=runner)

        with self.assertRaises(lib.ControlError) as caught:
            backend.set_display("1600x1200")

        self.assertEqual("display_mode_unavailable", caught.exception.code)
        self.assertEqual(409, caught.exception.status)
        self.assertEqual([[lib.XRANDR, "--query"]], [call[0] for call in runner.calls])

    def test_set_display_removes_prior_dynamic_mode_after_confirmed_switch(self):
        before = XRANDR.replace(
            "Screen 0: minimum 320 x 200, current 1440 x 900, maximum 1920 x 1200",
            "Screen 0: minimum 320 x 200, current 1256 x 600, maximum 1920 x 1200",
        ).replace("screen connected 1440x900+0+0", "screen connected 1256x600+0+0")
        before = before.replace("1440x900     60.00*", "1440x900     60.00")
        before += "   1256x600     59.80*\n"
        after = XRANDR.replace("1440x900+0+0", "1280x800+0+0").replace(
            "1440x900     60.00*", "1440x900     60.00"
        ).replace("1280x800     60.00", "1280x800     60.00*")
        runner = ScriptedRunner(
            [
                completed([], stdout=before),
                completed([]),
                completed([], stdout=after),
                completed([]),
                completed([]),
            ]
        )

        backend = lib.ControlBackend(runner=runner)
        backend._generated_display_modes.add("1256x600")
        payload = backend.set_display("1280x800")

        self.assertEqual("1280x800", payload["resolution"])
        self.assertEqual(
            [
                [lib.XRANDR, "--query"],
                [lib.XRANDR, "--output", "screen", "--mode", "1280x800"],
                [lib.XRANDR, "--query"],
                [lib.XRANDR, "--delmode", "screen", "1256x600"],
                [lib.XRANDR, "--rmmode", "1256x600"],
            ],
            [call[0] for call in runner.calls],
        )
        self.assertTrue(all("shell" not in call[1] for call in runner.calls))

    def test_dynamic_resolution_validation_is_bounded_and_aligned(self):
        for resolution in ("640x480", "768x1024", "1256x600", "1920x1200"):
            with self.subTest(resolution=resolution):
                self.assertEqual(resolution, lib.require_resolution(resolution))
        for resolution in (
            "632x480",
            "640x478",
            "641x480",
            "1928x1200",
            "1920x1202",
            "1256x600;touch /tmp/no",
            None,
        ):
            with self.subTest(resolution=resolution):
                with self.assertRaises(lib.ControlError) as caught:
                    lib.require_resolution(resolution)
                self.assertEqual("unsupported_resolution", caught.exception.code)

    def test_dynamic_resolution_validation_canonicalizes_leading_zeroes(self):
        self.assertEqual("640x480", lib.require_resolution("0640x0480"))
        self.assertEqual("800x600", lib.require_resolution("0800x0600"))

    def test_dynamic_resolution_validation_rejects_oversized_digit_strings(self):
        with self.assertRaises(lib.ControlError) as caught:
            lib.require_resolution("9" * 10_000 + "x" + "9" * 10_000)
        self.assertEqual("unsupported_resolution", caught.exception.code)

    def test_set_display_preserves_untracked_custom_mode(self):
        before = XRANDR.replace(
            "Screen 0: minimum 320 x 200, current 1440 x 900, maximum 1920 x 1200",
            "Screen 0: minimum 320 x 200, current 1256 x 600, maximum 1920 x 1200",
        ).replace("screen connected 1440x900+0+0", "screen connected 1256x600+0+0")
        before = before.replace("1440x900     60.00*", "1440x900     60.00")
        before += "   1256x600     59.80*\n"
        after = XRANDR.replace("1440x900+0+0", "1280x800+0+0").replace(
            "1440x900     60.00*", "1440x900     60.00"
        ).replace("1280x800     60.00", "1280x800     60.00*")
        runner = ScriptedRunner(
            [completed([], stdout=before), completed([]), completed([], stdout=after)]
        )

        payload = lib.ControlBackend(runner=runner).set_display("1280x800")

        self.assertEqual("1280x800", payload["resolution"])
        self.assertEqual(3, len(runner.calls))

    def test_modeline_parser_rejects_non_timing_tokens(self):
        with self.assertRaises(lib.ControlError) as caught:
            lib.parse_modeline('Modeline "safe" 1 2 3 4 5 6 7 8 9 --output')
        self.assertEqual("display_mode_generation_failed", caught.exception.code)

    def test_parse_xrandr_rejects_untrusted_output_name(self):
        malicious = "Screen 0: current 1920 x 1200\nbad;name connected 1920x1200+0+0\n"
        with self.assertRaises(lib.ControlError):
            lib.parse_xrandr(malicious)


class HelperBoundaryTests(unittest.TestCase):
    def test_service_names_have_fixed_program_and_log_mappings(self):
        self.assertEqual(
            {"desktop", "vnc", "terminal", "setup"}, set(lib.SERVICE_PROGRAMS)
        )
        self.assertEqual(set(lib.SERVICE_PROGRAMS), set(lib.SERVICE_LOGS))
        for path in lib.SERVICE_LOGS.values():
            self.assertTrue(path.startswith("/data/logs/vibestack/services/"))
            self.assertNotIn("..", path)

    def test_helper_status_invokes_fixed_supervisor_program(self):
        runner = ScriptedRunner(
            [completed([], stdout="x11vnc RUNNING pid 42, uptime 0:01:00\n")]
        )
        payload = lib.helper_status("vnc", runner=runner)
        self.assertEqual("RUNNING", payload["state"])
        self.assertEqual(
            [
                lib.SUPERVISORCTL,
                "-c",
                lib.SUPERVISOR_CONFIG,
                "status",
                "x11vnc",
            ],
            runner.calls[0][0],
        )
        self.assertEqual("/", runner.calls[0][1]["cwd"])
        self.assertEqual(dict(lib.SUPERVISOR_ENV), runner.calls[0][1]["env"])

    def test_helper_restart_invokes_only_fixed_commands(self):
        runner = ScriptedRunner(
            [
                completed([], stdout="x11vnc: stopped\nx11vnc: started\n"),
                completed([], stdout="x11vnc RUNNING pid 43, uptime 0:00:01\n"),
            ]
        )
        payload = lib.helper_restart("vnc", runner=runner)
        self.assertTrue(payload["restarted"])
        self.assertEqual(
            [
                [
                    lib.SUPERVISORCTL,
                    "-c",
                    lib.SUPERVISOR_CONFIG,
                    "restart",
                    "x11vnc",
                ],
                [
                    lib.SUPERVISORCTL,
                    "-c",
                    lib.SUPERVISOR_CONFIG,
                    "status",
                    "x11vnc",
                ],
            ],
            [call[0] for call in runner.calls],
        )
        self.assertTrue(all("shell" not in call[1] for call in runner.calls))
        self.assertEqual(
            lib.SUPERVISOR_RESTART_TIMEOUT_SECONDS,
            runner.calls[0][1]["timeout"],
        )
        self.assertEqual(lib.COMMAND_TIMEOUT_SECONDS, runner.calls[1][1]["timeout"])

    def test_malicious_user_cwd_cannot_select_supervisor_plugins(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            malicious_cwd = root / "desktop-home"
            malicious_cwd.mkdir()
            sentinel = root / "plugin-ran"
            (malicious_cwd / "supervisord.conf").write_text(
                "[ctlplugin:attacker]\n"
                "supervisor.ctl_factory=attacker:make_controller\n",
                encoding="utf-8",
            )
            fake_supervisorctl = root / "supervisorctl"
            fake_supervisorctl.write_text(
                "#!/bin/sh\n"
                f"sentinel={str(sentinel)!r}\n"
                'if [ "$PWD" != / ] || [ "$1" != -c ] || '
                f'[ "$2" != {lib.SUPERVISOR_CONFIG!r} ]; then\n'
                '  : > "$sentinel"\n'
                "fi\n"
                "printf 'x11vnc RUNNING pid 42, uptime 0:01:00\\n'\n",
                encoding="utf-8",
            )
            fake_supervisorctl.chmod(0o755)
            previous_cwd = Path.cwd()
            try:
                os.chdir(malicious_cwd)
                with patch.object(lib, "SUPERVISORCTL", str(fake_supervisorctl)):
                    payload = lib.helper_status("vnc")
            finally:
                os.chdir(previous_cwd)

            self.assertEqual("RUNNING", payload["state"])
            self.assertFalse(sentinel.exists())

    def test_helper_restart_requires_running_postcondition(self):
        runner = ScriptedRunner(
            [
                completed([], stdout="ttyd: stopped\nttyd: started\n"),
                completed([], stdout="ttyd BACKOFF Exited too quickly\n"),
            ]
        )
        with self.assertRaises(lib.ControlError) as caught:
            lib.helper_restart("terminal", runner=runner)
        self.assertEqual("service_restart_failed", caught.exception.code)

    def test_unknown_service_never_runs_a_command(self):
        runner = ScriptedRunner([])
        with self.assertRaises(lib.ControlError) as caught:
            lib.helper_restart("nginx", runner=runner)
        self.assertEqual("unknown_service", caught.exception.code)
        self.assertEqual([], runner.calls)

    def test_backend_helper_argv_is_bounded_and_uses_sudo_noninteractive(self):
        body = json.dumps(
            {
                "service": "desktop",
                "lines": [],
                "nextCursor": 5,
                "reset": False,
                "truncated": False,
            }
        )
        runner = ScriptedRunner([completed([], stdout=body)])
        backend = lib.ControlBackend(runner=runner)
        backend.service_logs("desktop", 5, 20)
        self.assertEqual(
            [
                "/usr/bin/sudo",
                "-n",
                lib.CONTROL_HELPER,
                "logs",
                "desktop",
                "--limit",
                "20",
                "--cursor",
                "5",
            ],
            runner.calls[0][0],
        )

    def test_backend_allows_restart_helper_to_outlive_program_start_grace(self):
        body = json.dumps({"service": "desktop", "state": "RUNNING", "restarted": True})
        runner = ScriptedRunner([completed([], stdout=body)])
        backend = lib.ControlBackend(runner=runner)
        backend.restart_service("desktop")
        self.assertEqual(lib.HELPER_RESTART_TIMEOUT_SECONDS, runner.calls[0][1]["timeout"])

    def test_cli_parser_rejects_unknown_service_before_helper_code(self):
        loader = SourceFileLoader(
            "vibestack_control_cli", str(ROOT / "bin" / "vibestack-control")
        )
        spec = importlib.util.spec_from_loader("vibestack_control_cli", loader)
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        with self.assertRaises(SystemExit) as caught:
            module.build_parser().parse_args(["restart", "nginx"])
        self.assertEqual(2, caught.exception.code)


class LogPaginationTests(unittest.TestCase):
    def test_initial_page_returns_tail_and_end_cursor(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "service.log"
            path.write_bytes(b"one\ntwo\nthree\n")
            payload = lib.read_log_page(str(path), None, 2)
        self.assertEqual(["two", "three"], payload["lines"])
        self.assertEqual(14, payload["nextCursor"])
        self.assertTrue(payload["truncated"])

    def test_cursor_page_is_bounded_and_rotation_resets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "service.log"
            path.write_bytes(b"one\ntwo\nthree\n")
            payload = lib.read_log_page(str(path), 4, 1)
            rotated = lib.read_log_page(str(path), 999, 10)
        self.assertEqual(["two"], payload["lines"])
        self.assertEqual(8, payload["nextCursor"])
        self.assertTrue(payload["truncated"])
        self.assertTrue(rotated["reset"])
        self.assertEqual(["one", "two", "three"], rotated["lines"])

    def test_log_lines_strip_ansi_and_escape_control_characters(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "service.log"
            path.write_bytes(b"\x1b[31mred\x1b[0m\x00<script>\n")
            payload = lib.read_log_page(str(path), None, 10)
        self.assertEqual(["red\\u0000<script>"], payload["lines"])

    def test_sanitized_lines_are_capped_by_utf8_bytes_after_expansion(self):
        controls = lib._sanitize_log_line(b"\x00" * 4096)
        unicode_text = lib._sanitize_log_line(("\U0001faa9" * 4096).encode())
        self.assertLessEqual(len(controls.encode("utf-8")), lib.MAX_LOG_LINE_BYTES)
        self.assertLessEqual(len(unicode_text.encode("utf-8")), lib.MAX_LOG_LINE_BYTES)
        self.assertTrue(controls.endswith("\\u0000"))
        self.assertEqual(0, len(unicode_text.encode("utf-8")) % 4)

    def test_control_heavy_pages_stay_bounded_and_cursor_does_not_skip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "service.log"
            records = [
                ("line-%03d:" % index).encode() + (b"\x00" * 1024) + b"\n"
                for index in range(200)
            ]
            path.write_bytes(b"".join(records))
            cursor = 0
            seen: list[str] = []
            while cursor < path.stat().st_size:
                payload = lib.read_log_page(str(path), cursor, lib.MAX_LOG_LIMIT)
                response = {**payload, "service": "desktop"}
                encoded = json.dumps(
                    response, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
                self.assertLessEqual(len(encoded), lib.MAX_LOG_PAGE_BYTES)
                self.assertTrue(payload["lines"])
                self.assertGreater(payload["nextCursor"], cursor)
                self.assertTrue(
                    all(
                        len(line.encode("utf-8")) <= lib.MAX_LOG_LINE_BYTES
                        for line in payload["lines"]
                    )
                )
                seen.extend(line.split(":", 1)[0] for line in payload["lines"])
                cursor = payload["nextCursor"]
        self.assertEqual(["line-%03d" % index for index in range(200)], seen)


if __name__ == "__main__":
    unittest.main()
