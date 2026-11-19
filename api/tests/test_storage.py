"""Storage tests also run without installing web dependencies."""

import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from fatigue_analysis_api.storage import UploadError, VideoStore, media_extension


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = VideoStore(Path(self.temp.name), max_bytes=8)

    def test_streamed_bytes_are_preserved(self):
        identifier = uuid4().hex
        with self.store.begin(identifier, ".mp4") as pending:
            pending.write(b"video")
            pending.write(b"123")
            path = pending.finish()
        self.assertEqual(path.name, identifier + ".mp4")
        self.assertEqual(path.read_bytes(), b"video123")
        self.assertEqual(list(path.parent.glob("*.part")), [])

    def test_empty_and_oversized_uploads_leave_no_files(self):
        for chunks, expected in [([], "EMPTY_VIDEO"), ([b"12345678", b"9"], "VIDEO_TOO_LARGE")]:
            with self.subTest(expected=expected), self.assertRaises(UploadError) as caught:
                with self.store.begin(uuid4().hex, ".mp4") as pending:
                    for chunk in chunks:
                        pending.write(chunk)
                    pending.finish()
            self.assertEqual(caught.exception.code, expected)
            self.assertEqual(list(self.store.directory.iterdir()), [])

    def test_interrupted_write_removes_partial_file(self):
        with self.assertRaises(RuntimeError):
            with self.store.begin(uuid4().hex, ".mov") as pending:
                pending.write(b"abc")
                raise RuntimeError("disconnect")
        self.assertEqual(list(self.store.directory.iterdir()), [])

    def test_existing_video_is_never_overwritten(self):
        identifier = uuid4().hex
        with self.store.begin(identifier, ".mp4") as pending:
            pending.write(b"original")
            path = pending.finish()
        with self.assertRaises(FileExistsError):
            with self.store.begin(identifier, ".mp4") as pending:
                pending.write(b"new")
                pending.finish()
        self.assertEqual(path.read_bytes(), b"original")
        self.assertEqual(list(path.parent.glob("*.part")), [])

    def test_caller_cannot_supply_a_storage_path(self):
        with self.assertRaises(ValueError):
            self.store.begin("../../outside", ".mp4")
        with self.assertRaises(ValueError):
            self.store.begin(uuid4().hex, "/outside")

    def test_media_types(self):
        self.assertEqual(media_extension("video/mp4; charset=binary"), ".mp4")
        self.assertEqual(media_extension("video/quicktime"), ".mov")
        with self.assertRaises(UploadError):
            media_extension("application/octet-stream")


if __name__ == "__main__":
    unittest.main()
