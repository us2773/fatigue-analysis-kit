"""Video validation without HTTP, analysis or web-framework dependencies."""

import json
import subprocess
from pathlib import Path
from typing import Protocol

from .storage import UploadError


class VideoValidator(Protocol):
    def validate(self, video: Path) -> None: ...


class FFprobeValidator:
    def __init__(self, executable: str = "ffprobe"):
        self.executable = executable

    def validate(self, video: Path) -> None:
        try:
            result = subprocess.run(
                [
                    self.executable,
                    "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=codec_type,width,height",
                    "-of", "json",
                    "-i", str(video.resolve()),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
        except FileNotFoundError as exc:
            raise UploadError(
                "VIDEO_VALIDATOR_UNAVAILABLE", "サーバにffprobeがありません。", 503
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise UploadError(
                "VIDEO_VALIDATION_TIMEOUT", "動画の確認がタイムアウトしました。", 422
            ) from exc
        try:
            streams = json.loads(result.stdout).get("streams", [])
            valid = result.returncode == 0 and any(
                s.get("codec_type") == "video"
                and s.get("width", 0) > 0
                and s.get("height", 0) > 0
                for s in streams
            )
        except (ValueError, TypeError, AttributeError):
            valid = False
        if not valid:
            raise UploadError(
                "INVALID_VIDEO", "動画ストリームを確認できませんでした。", 422
            )
