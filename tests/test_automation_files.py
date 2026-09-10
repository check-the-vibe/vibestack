from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "automation"))
import files  # noqa: E402


class DesktopFileStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.desktop = Path(self.temporary.name) / "Desktop"
        self.desktop.mkdir()
        self.store = files.DesktopFileStore(str(self.desktop))

    def tearDown(self):
        self.temporary.cleanup()

    def test_binary_round_trip_is_atomic_and_has_etag(self):
        content = b"\x00\xffbinary\n"
        written = self.store.write("artifact.bin", content)
        self.assertTrue(written.created)
        self.assertEqual(content, written.data)
        self.assertRegex(written.etag, r'^"sha256-[0-9a-f]{64}"$')
        self.assertEqual(0o644, stat_mode(self.desktop / "artifact.bin"))

        replaced = self.store.write(
            "artifact.bin", b"next", if_match=written.etag
        )
        self.assertFalse(replaced.created)
        self.assertEqual(b"next", self.store.read("artifact.bin").data)

    def test_write_preconditions_prevent_lost_updates(self):
        current = self.store.write("note.txt", b"one")
        with self.assertRaises(files.FileError) as caught:
            self.store.write("note.txt", b"two", if_match='"sha256-wrong"')
        self.assertEqual((412, "precondition_failed"), (caught.exception.status, caught.exception.code))
        self.assertEqual(b"one", self.store.read("note.txt").data)

        with self.assertRaises(files.FileError) as caught:
            self.store.write("note.txt", b"two", if_none_match="*")
        self.assertEqual("precondition_failed", caught.exception.code)
        with self.assertRaises(files.FileError) as caught:
            self.store.write("note.txt", b"two", if_match="W/" + current.etag)
        self.assertEqual("precondition_failed", caught.exception.code)
        created = self.store.write("new.txt", b"new", if_none_match="*")
        self.assertTrue(created.created)
        self.assertNotEqual(current.etag, created.etag)

    def test_if_none_match_create_is_atomic_against_external_creator(self):
        target = self.desktop / "raced.txt"

        def race(_parent_fd, _leaf):
            target.write_bytes(b"external")

        with mock.patch.object(self.store, "_before_commit", side_effect=race):
            with self.assertRaises(files.FileError) as caught:
                self.store.write("raced.txt", b"api", if_none_match="*")
        self.assertEqual((412, "precondition_failed"), (caught.exception.status, caught.exception.code))
        self.assertEqual(b"external", target.read_bytes())

    def test_if_match_revalidates_external_change_before_replace(self):
        target = self.desktop / "raced.txt"
        original = self.store.write("raced.txt", b"original")

        def race(_parent_fd, _leaf):
            target.write_bytes(b"external update")

        with mock.patch.object(self.store, "_before_commit", side_effect=race):
            with self.assertRaises(files.FileError) as caught:
                self.store.write(
                    "raced.txt", b"api update", if_match=original.etag
                )
        self.assertEqual((412, "precondition_failed"), (caught.exception.status, caught.exception.code))
        self.assertEqual(b"external update", target.read_bytes())

    def test_nested_paths_require_existing_safe_directories(self):
        folder = self.desktop / "folder"
        folder.mkdir()
        result = self.store.write("folder/data.dat", b"ok")
        self.assertEqual(b"ok", result.data)

        with self.assertRaises(files.FileError) as caught:
            self.store.write("missing/data.dat", b"no")
        self.assertEqual("file_not_found", caught.exception.code)

    def test_traversal_symlinks_hardlinks_and_special_files_are_rejected(self):
        outside = Path(self.temporary.name) / "outside.txt"
        outside.write_bytes(b"private")
        (self.desktop / "link").symlink_to(outside)
        original = self.desktop / "original"
        original.write_bytes(b"linked")
        os.link(original, self.desktop / "hardlink")
        fifo = self.desktop / "pipe"
        os.mkfifo(fifo)

        for name in ("link", "original", "hardlink", "pipe"):
            with self.subTest(name=name), self.assertRaises(files.FileError) as caught:
                self.store.read(name)
            self.assertIn(caught.exception.code, {"unsafe_path", "unsafe_file"})
        for path in ("../outside.txt", "/etc/passwd", "folder/../outside", "a\\b"):
            with self.subTest(path=path), self.assertRaises(files.FileError):
                self.store.read(path)

    def test_root_and_components_must_match_uid(self):
        unsafe = files.DesktopFileStore(
            str(self.desktop), expected_uid=os.getuid() + 1
        )
        with self.assertRaises(files.FileError) as caught:
            unsafe.write("data", b"x")
        self.assertEqual("unsafe_desktop", caught.exception.code)

    def test_range_parser_supports_single_bounded_ranges(self):
        self.assertEqual((2, 5), files.parse_range("bytes=2-5", 10))
        self.assertEqual((7, 9), files.parse_range("bytes=-3", 10))
        self.assertEqual((0, 9), files.parse_range("bytes=-999999999", 10))
        self.assertEqual((3, 9), files.parse_range("bytes=3-", 10))
        with self.assertRaises(files.FileError) as caught:
            files.parse_range("bytes=0-%d" % files.MAX_RANGE_BYTES, files.MAX_RANGE_BYTES + 1)
        self.assertEqual("range_too_large", caught.exception.code)
        with self.assertRaises(files.FileError):
            files.parse_range("bytes=1-2,4-5", 10)

    def test_cwd_is_confined_and_rejects_symlink_components(self):
        directory = self.desktop / "work"
        directory.mkdir()
        self.assertEqual(str(directory), self.store.require_cwd("work"))
        self.assertEqual(str(self.desktop), self.store.require_cwd(None))
        (self.desktop / "work-link").symlink_to(directory, target_is_directory=True)
        with self.assertRaises(files.FileError):
            self.store.require_cwd("work-link")
        with self.assertRaises(files.FileError):
            self.store.require_cwd("/tmp")


def stat_mode(path: Path) -> int:
    return os.stat(path).st_mode & 0o777


if __name__ == "__main__":
    unittest.main()
