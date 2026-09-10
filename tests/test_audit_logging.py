from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "automation"))
import automationlib as lib  # noqa: E402


class AuditLoggerTests(unittest.TestCase):
    def test_records_structured_metadata_with_secure_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "logs" / "automation-audit.jsonl"
            logger = lib.AuditLogger(str(path))
            logger.record(
                request_id="request-1",
                method="PUT",
                action="file.write",
                status=201,
                duration_ms=4,
                details={"path": "result.bin", "bytes": 5},
            )
            record = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("automation", record["service"])
            self.assertEqual("result.bin", record["details"]["path"])
            self.assertEqual(0o640, os.stat(path).st_mode & 0o777)

    def test_rotation_bounds_the_active_log_and_keeps_three_backups(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            lib, "MAX_AUDIT_BYTES", 300
        ):
            path = Path(temporary) / "automation-audit.jsonl"
            logger = lib.AuditLogger(str(path))
            for index in range(20):
                logger.record(
                    request_id="request-%d" % index,
                    method="GET",
                    action="capabilities.read",
                    status=200,
                    duration_ms=1,
                )
            self.assertLessEqual(path.stat().st_size, 300)
            self.assertTrue(Path(str(path) + ".1").is_file())
            self.assertTrue(Path(str(path) + ".3").is_file())
            self.assertFalse(Path(str(path) + ".4").exists())

    def test_symlink_log_is_not_followed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.write_text("unchanged", encoding="utf-8")
            path = root / "audit.jsonl"
            path.symlink_to(target)
            lib.AuditLogger(str(path)).record(
                request_id="request",
                method="GET",
                action="capabilities.read",
                status=200,
                duration_ms=1,
            )
            self.assertEqual("unchanged", target.read_text(encoding="utf-8"))

    def test_maximum_multibyte_relative_path_is_not_dropped_or_ascii_expanded(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "audit.jsonl"
            relative = "\N{ROCKET}" * 1024  # exactly 4096 UTF-8 bytes
            lib.AuditLogger(str(path)).record(
                request_id="request",
                method="PUT",
                action="file.write",
                status=201,
                duration_ms=1,
                details={"path": relative, "bytes": 0},
            )
            record = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(relative, record["details"]["path"])
            self.assertLess(path.stat().st_size, 8192)


if __name__ == "__main__":
    unittest.main()
