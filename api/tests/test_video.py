import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fatigue_analysis_api.storage import UploadError
from fatigue_analysis_api.video import FFprobeValidator


class VideoTests(unittest.TestCase):
    def test_missing_executable_is_reported_without_path(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("private-path")):
            with self.assertRaises(UploadError) as caught:
                FFprobeValidator().validate(Path("synthetic.mp4"))
        self.assertEqual(caught.exception.code, "VIDEO_VALIDATOR_UNAVAILABLE")
        self.assertNotIn("private-path", str(caught.exception))

    def test_timeout_is_reported(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ffprobe", 15)):
            with self.assertRaises(UploadError) as caught:
                FFprobeValidator().validate(Path("synthetic.mp4"))
        self.assertEqual(caught.exception.code, "VIDEO_VALIDATION_TIMEOUT")

    def test_invalid_probe_output_is_not_accepted(self):
        for output in (b"not-json", b'{}', b'{"streams":[{"codec_type":"audio"}]}'):
            result = subprocess.CompletedProcess([], 0, stdout=output)
            with self.subTest(output=output), patch("subprocess.run", return_value=result):
                with self.assertRaises(UploadError) as caught:
                    FFprobeValidator().validate(Path("synthetic.mp4"))
                self.assertEqual(caught.exception.code, "INVALID_VIDEO")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools not installed")
    def test_generated_video_and_invalid_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "synthetic.mp4"
            subprocess.run(
                ["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                 "color=c=black:s=64x64:r=5", "-t", "0.4", "-c:v", "mpeg4", str(video)],
                check=True, timeout=15,
            )
            FFprobeValidator().validate(video)
            video.write_bytes(b"not-a-video")
            with self.assertRaises(UploadError) as caught:
                FFprobeValidator().validate(video)
            self.assertEqual(caught.exception.code, "INVALID_VIDEO")
