from __future__ import annotations

import base64
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "automation"))
import automationlib as lib  # noqa: E402


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class NoopRunner:
    def shutdown(self, wait=False):
        pass


class ScriptedDesktopBackend(lib.AutomationBackend):
    def __init__(self, desktop_root, *, mismatch_pid=False):
        super().__init__(
            desktop_root=desktop_root,
            job_directory=str(Path(desktop_root).parent / "jobs"),
            runner=NoopRunner(),
        )
        self.calls = []
        self.property_calls = 0
        self.mismatch_pid = mismatch_pid
        self.current_state = "maximized"

    @staticmethod
    def _require_tool(path):
        pass

    def _desktop_tool(self, argv, *, allow_failure=False, timeout=10):
        self.calls.append(list(argv))
        if list(argv) == [lib.WMCTRL, "-lx"]:
            return lib.BoundedResult(
                0,
                b"0x01200003  0 xfce4-terminal.Xfce4-terminal host Terminal title\n",
                b"",
                False,
            )
        if list(argv) == [lib.XDOTOOL, "getactivewindow"]:
            return lib.BoundedResult(0, b"18874371\n", b"", False)
        if len(argv) > 1 and argv[0] == lib.XPROP:
            self.property_calls += 1
            pid = 222 if self.mismatch_pid and self.property_calls > 1 else 111
            state_atoms = {
                "maximized": (
                    "_NET_WM_STATE_MAXIMIZED_VERT, "
                    "_NET_WM_STATE_MAXIMIZED_HORZ"
                ),
                "minimized": "_NET_WM_STATE_HIDDEN",
                "normal": "",
            }[self.current_state]
            output = (
                'WM_CLASS(STRING) = "xfce4-terminal", "Xfce4-terminal"\n'
                "_NET_WM_PID(CARDINAL) = %d\n"
                "_NET_WM_STATE(ATOM) = %s\n"
            ) % (pid, state_atoms)
            return lib.BoundedResult(0, output.encode(), b"", False)
        if list(argv[:2]) == [lib.XDOTOOL, "windowminimize"]:
            self.current_state = "minimized"
        elif argv[0] == lib.WMCTRL and "add,maximized_vert,maximized_horz" in argv:
            self.current_state = "maximized"
        elif argv[0] == lib.WMCTRL and "remove,maximized_vert,maximized_horz" in argv:
            self.current_state = "normal"
        return lib.BoundedResult(0, b"", b"", False)


class DesktopAutomationTests(unittest.TestCase):
    def test_window_parser_uses_wm_class_column_and_tracks_active_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            desktop = Path(temporary) / "Desktop"
            desktop.mkdir()
            backend = ScriptedDesktopBackend(str(desktop))
            payload = backend.windows()
            window = payload["windows"][0]
            self.assertEqual("0x01200003", window["id"])
            self.assertEqual("xfce4-terminal.Xfce4-terminal", window["wm_class"])
            self.assertEqual(111, window["pid"])
            self.assertEqual("maximized", window["state"])
            self.assertTrue(window["active"])

    def test_window_listing_retries_a_transient_wmctrl_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            desktop = Path(temporary) / "Desktop"
            desktop.mkdir()
            backend = ScriptedDesktopBackend(str(desktop))
            original = backend._desktop_tool
            listing_attempts = 0

            def transient_listing(argv, **kwargs):
                nonlocal listing_attempts
                if list(argv) == [lib.WMCTRL, "-lx"]:
                    listing_attempts += 1
                    if listing_attempts == 1:
                        return lib.BoundedResult(1, b"", b"transient", False)
                return original(argv, **kwargs)

            with (
                mock.patch.object(backend, "_desktop_tool", side_effect=transient_listing),
                mock.patch.object(lib.time, "sleep"),
            ):
                payload = backend.windows()
            self.assertEqual(2, listing_attempts)
            self.assertEqual("0x01200003", payload["windows"][0]["id"])

    def test_stop_application_and_window_state_revalidate_class_and_pid(self):
        with tempfile.TemporaryDirectory() as temporary:
            desktop = Path(temporary) / "Desktop"
            desktop.mkdir()
            backend = ScriptedDesktopBackend(str(desktop))
            stopped = backend.stop_application("terminal")
            self.assertTrue(stopped["stop_requested"])
            self.assertEqual(1, stopped["close_requests"])
            self.assertNotIn("windows_closed", stopped)
            self.assertIn([lib.WMCTRL, "-ic", "0x01200003"], backend.calls)

            backend.calls.clear()
            changed = backend.set_window_state("0x01200003", "normal")
            self.assertEqual("0x01200003", changed["window"]["id"])
            self.assertTrue(any(call[:2] == [lib.XDOTOOL, "windowmap"] for call in backend.calls))

    def test_pid_change_prevents_window_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            desktop = Path(temporary) / "Desktop"
            desktop.mkdir()
            backend = ScriptedDesktopBackend(str(desktop), mismatch_pid=True)
            with self.assertRaises(lib.AutomationError) as caught:
                backend.set_window_state("0x01200003", "minimized")
            self.assertEqual("window_changed", caught.exception.code)
            self.assertFalse(any(call[0] == lib.XDOTOOL and "windowminimize" in call for call in backend.calls))

    def test_fixed_application_catalog_does_not_expose_argv(self):
        with tempfile.TemporaryDirectory() as temporary:
            desktop = Path(temporary) / "Desktop"
            desktop.mkdir()
            backend = ScriptedDesktopBackend(str(desktop))
            payload = backend.applications()
            self.assertEqual(
                {
                    "terminal",
                    "files",
                    "settings",
                    "chrome",
                    "claude-desktop",
                    "chatgpt",
                    "mousepad",
                    "geany",
                },
                {app["id"] for app in payload["applications"]},
            )
            self.assertTrue(all("argv" not in app for app in payload["applications"]))

    def test_whitespace_bearing_chatgpt_wm_class_comes_from_xprop(self):
        with tempfile.TemporaryDirectory() as temporary:
            desktop = Path(temporary) / "Desktop"
            desktop.mkdir()
            backend = ScriptedDesktopBackend(str(desktop))

            def chatgpt_tools(argv, **_kwargs):
                if list(argv) == [lib.WMCTRL, "-lx"]:
                    return lib.BoundedResult(
                        0,
                        b"0x02800003  0 chatgpt (/home/vibe/.config/Codex).Chatgpt host ChatGPT\n",
                        b"",
                        False,
                    )
                if list(argv) == [lib.XDOTOOL, "getactivewindow"]:
                    return lib.BoundedResult(0, b"41943043\n", b"", False)
                if argv[0] == lib.XPROP:
                    return lib.BoundedResult(
                        0,
                        (
                            'WM_CLASS(STRING) = "chatgpt (/home/vibe/.config/Codex)", "Chatgpt"\n'
                            "_NET_WM_PID(CARDINAL) = 15512\n"
                            "_NET_WM_STATE(ATOM) =\n"
                        ).encode(),
                        b"",
                        False,
                    )
                raise AssertionError(argv)

            with mock.patch.object(backend, "_desktop_tool", side_effect=chatgpt_tools):
                window = backend.windows()["windows"][0]
                application = backend.applications()["applications"][5]
            self.assertEqual(
                "chatgpt (/home/vibe/.config/Codex).Chatgpt", window["wm_class"]
            )
            self.assertEqual("chatgpt", application["id"])
            self.assertTrue(application["running"])

    def test_concurrent_application_starts_share_one_pending_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            desktop = Path(temporary) / "Desktop"
            desktop.mkdir()
            backend = ScriptedDesktopBackend(str(desktop))
            backend._application("terminal")["requires"] = ["/bin/true"]
            backend._windows = mock.Mock(return_value=[])
            process = mock.Mock()
            barrier = threading.Barrier(3)
            results = []

            def launch():
                barrier.wait()
                results.append(backend.start_application("terminal"))

            threads = [threading.Thread(target=launch) for _ in range(2)]
            with mock.patch.object(lib.subprocess, "Popen", return_value=process) as popen:
                for thread in threads:
                    thread.start()
                barrier.wait()
                for thread in threads:
                    thread.join(timeout=2)

            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(1, popen.call_count)
            self.assertEqual([False, True], sorted(result["started"] for result in results))
            self.assertTrue(all(result["launch_pending"] for result in results))

    def test_immediate_stop_cancels_the_tracked_pending_launch_group(self):
        with tempfile.TemporaryDirectory() as temporary:
            desktop = Path(temporary) / "Desktop"
            desktop.mkdir()
            backend = ScriptedDesktopBackend(str(desktop))
            backend._application("terminal")["requires"] = ["/bin/true"]
            backend._windows = mock.Mock(return_value=[])
            process = mock.Mock(pid=4242)
            with mock.patch.object(lib.subprocess, "Popen", return_value=process):
                started = backend.start_application("terminal")
            self.assertTrue(started["launch_pending"])

            with (
                mock.patch.object(
                    backend,
                    "_application_group_exists",
                    side_effect=[True, False, False],
                ),
                mock.patch.object(lib.os, "killpg") as killpg,
            ):
                stopped = backend.stop_application("terminal")
            killpg.assert_called_once_with(4242, lib.signal.SIGTERM)
            self.assertTrue(stopped["stop_requested"])
            self.assertTrue(stopped["pending_launch_cancelled"])
            self.assertEqual(0, stopped["close_requests"])
            self.assertNotIn("terminal", backend._pending_applications)

    def test_pending_launch_kill_reaps_a_real_stubborn_group_leader(self):
        with tempfile.TemporaryDirectory() as temporary:
            desktop = Path(temporary) / "Desktop"
            desktop.mkdir()
            backend = ScriptedDesktopBackend(str(desktop))
            backend._windows = mock.Mock(return_value=[])
            process = subprocess.Popen(
                [
                    "/usr/bin/python3",
                    "-c",
                    "import signal,time; "
                    "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                    "print('ready', flush=True); time.sleep(30)",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
            )
            try:
                self.assertEqual("ready\n", process.stdout.readline())
                backend._pending_applications["terminal"] = (
                    process,
                    time.monotonic() + 10,
                )
                with mock.patch.object(
                    lib, "APPLICATION_STOP_GRACE_SECONDS", 0.05
                ):
                    stopped = backend.stop_application("terminal")
                self.assertTrue(stopped["pending_launch_cancelled"])
                self.assertIsNotNone(process.poll())
                self.assertFalse(Path("/proc/%d" % process.pid).exists())
            finally:
                if process.poll() is None:
                    try:
                        lib.os.killpg(process.pid, lib.signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=2)
                if process.stdout is not None:
                    process.stdout.close()

    def test_detached_pending_launch_is_not_falsely_reported_cancelled(self):
        with tempfile.TemporaryDirectory() as temporary:
            desktop = Path(temporary) / "Desktop"
            desktop.mkdir()
            backend = ScriptedDesktopBackend(str(desktop))
            backend._windows = mock.Mock(return_value=[])
            process = subprocess.Popen(
                [
                    "/usr/bin/python3",
                    "-c",
                    "import subprocess; "
                    "child=subprocess.Popen(['/bin/sleep','30'],start_new_session=True); "
                    "print(child.pid,flush=True)",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
            )
            child_pid = int(process.stdout.readline().strip())
            try:
                # Wait for the launcher to exit without reaping it. The old
                # implementation mistook this zombie for a live launch group.
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    try:
                        state = Path("/proc/%d/stat" % process.pid).read_text().split()[2]
                    except (FileNotFoundError, IndexError):
                        state = "gone"
                    if state in ("Z", "gone"):
                        break
                    time.sleep(0.01)
                backend._pending_applications["terminal"] = (
                    process,
                    time.monotonic() + 10,
                )
                with self.assertRaises(lib.AutomationError) as caught:
                    backend.stop_application("terminal")
                self.assertEqual("application_launch_pending", caught.exception.code)
                self.assertIn("terminal", backend._pending_applications)
                self.assertTrue(Path("/proc/%d" % child_pid).exists())
            finally:
                process.wait(timeout=2)
                if process.stdout is not None:
                    process.stdout.close()
                try:
                    lib.os.kill(child_pid, lib.signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_application_stop_uses_one_overall_deadline(self):
        with tempfile.TemporaryDirectory() as temporary:
            desktop = Path(temporary) / "Desktop"
            desktop.mkdir()
            backend = ScriptedDesktopBackend(str(desktop))
            windows = [
                {
                    "id": "0x%08x" % index,
                    "wm_class": "xfce4-terminal.Xfce4-terminal",
                    "pid": 100 + index,
                    "title": "Terminal",
                    "state": "normal",
                    "active": False,
                }
                for index in range(1, 4)
            ]
            with (
                mock.patch.object(backend, "_windows", return_value=windows),
                mock.patch.object(backend, "_revalidate_window") as revalidate,
                mock.patch.object(backend, "_desktop_tool") as desktop_tool,
                mock.patch.object(lib.time, "monotonic", side_effect=[100.0, 114.0, 116.0]),
            ):
                with self.assertRaises(lib.AutomationError) as caught:
                    backend.stop_application("terminal")
            self.assertEqual("application_stop_timeout", caught.exception.code)
            self.assertEqual(1.0, revalidate.call_args.kwargs["timeout"])
            desktop_tool.assert_not_called()

    def test_screenshot_validates_png_and_can_atomically_store_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            desktop = Path(temporary) / "Desktop"
            desktop.mkdir()
            backend = lib.AutomationBackend(
                desktop_root=str(desktop),
                job_directory=str(Path(temporary) / "jobs"),
                runner=NoopRunner(),
            )

            def fake_scrot(argv, **kwargs):
                self.assertEqual(["/bin/true", "--format", "png", "-"], list(argv))
                return lib.BoundedResult(0, PNG, b"", False)

            with mock.patch.object(lib, "SCROT", "/bin/true"), mock.patch.object(
                lib, "_run_bounded", fake_scrot
            ):
                # Parent directories are intentionally never created by the API.
                (desktop / "captures").mkdir()
                image, stored = backend.screenshot("captures/shot.png")
            self.assertEqual(PNG, image)
            self.assertIsNotNone(stored)
            self.assertEqual(PNG, (desktop / "captures" / "shot.png").read_bytes())
            with self.assertRaises(lib.AutomationError):
                lib._validate_png(b"not a png")

    def test_empty_clipboard_uses_a_tracked_foreground_owner(self):
        with tempfile.TemporaryDirectory() as temporary:
            desktop = Path(temporary) / "Desktop"
            desktop.mkdir()
            backend = lib.AutomationBackend(
                desktop_root=str(desktop),
                job_directory=str(Path(temporary) / "jobs"),
                runner=NoopRunner(),
            )
            process = mock.Mock(pid=4242)
            process.stdin = mock.Mock()
            process.poll.return_value = None
            process.wait.return_value = 0

            with (
                mock.patch.object(backend, "_require_tool"),
                mock.patch.object(lib.subprocess, "Popen", return_value=process) as popen,
                mock.patch.object(lib.time, "sleep"),
                mock.patch.object(lib.os, "killpg") as killpg,
            ):
                self.assertEqual({"bytes": 0}, backend.set_clipboard(b""))
                argv = popen.call_args.args[0]
                self.assertIn("-quiet", argv)
                self.assertNotIn("-silent", argv)
                process.stdin.write.assert_called_once_with(b"")
                backend.close()

            killpg.assert_called_once_with(4242, lib.signal.SIGTERM)


if __name__ == "__main__":
    unittest.main()
