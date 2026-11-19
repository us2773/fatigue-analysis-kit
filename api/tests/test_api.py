import asyncio
import shutil
import subprocess
import threading
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fatigue_analysis_api.analysis import SampleAnalyzer
from fatigue_analysis_api.app import Settings, create_app
from fatigue_analysis_api.models import AnalysisError, AnalysisResult, Feature
from fatigue_analysis_api.storage import UploadError


class AcceptVideo:
    def validate(self, video):
        assert video.read_bytes() == b"synthetic-video"


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(tmp_path, max_upload_bytes=64), validator=AcceptVideo())
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def send(client, content=b"synthetic-video", pipeline="daily", content_type="video/mp4"):
    return client.post(f"/v1/analyses?pipeline={pipeline}", content=content, headers={"Content-Type": content_type})


@pytest.mark.parametrize("content_type,extension", [("video/mp4", ".mp4"), ("video/quicktime", ".mov")])
def test_upload_saves_exact_bytes_and_returns_contract(client, tmp_path, content_type, extension):
    response = send(client, content_type=content_type)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["schema_version"] == "1.0"
    assert response.headers["X-Analysis-Mode"] == "sample"
    assert response.headers["Cache-Control"] == "no-store"
    assert body["metadata"] == {"pipeline": "daily", "analysis_version": "sample-v1", "parameter_set_id": None}
    assert body["result"]["features"][0] == {"id": "AU02_trend_mean", "label": "AU02 トレンド平均", "value": 2.18, "describe": None, "error": None}
    assert body["result"]["summary"] == {"message": None, "advise": None}
    path = tmp_path / "01_raw" / "movie" / (body["analysis_id"] + extension)
    assert path.read_bytes() == b"synthetic-video"
    assert "filename" not in response.text and str(tmp_path) not in response.text


def test_repeated_uploads_have_distinct_names(client, tmp_path):
    first, second = send(client).json(), send(client).json()
    assert first["analysis_id"] != second["analysis_id"]
    assert len(list((tmp_path / "01_raw/movie").glob("*.mp4"))) == 2


@pytest.mark.parametrize("pipeline", ["other", "daily&pipeline=other", "daily&parameters=changed"])
def test_pipeline_allowlist_prevents_overrides(client, tmp_path, pipeline):
    response = send(client, pipeline=pipeline)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PIPELINE"
    assert not (tmp_path / "01_raw/movie").exists()


@pytest.mark.parametrize("content,content_type,status,code", [
    (b"", "video/mp4", 400, "EMPTY_VIDEO"),
    (b"x" * 65, "video/mp4", 413, "VIDEO_TOO_LARGE"),
    (b"x", "text/plain", 415, "UNSUPPORTED_MEDIA_TYPE"),
])
def test_invalid_uploads_return_structured_errors(client, tmp_path, content, content_type, status, code):
    response = send(client, content=content, content_type=content_type)
    assert response.status_code == status
    body = response.json()
    assert body["status"] == "failed" and body["result"] is None
    assert body["error"]["code"] == code
    assert list(tmp_path.rglob("*.part")) == []


def test_chunked_upload_limit_is_enforced(tmp_path):
    async def run():
        app = create_app(Settings(tmp_path, max_upload_bytes=4), validator=AcceptVideo())
        async def chunks():
            yield b"1234"
            yield b"5"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/v1/analyses?pipeline=daily", content=chunks(), headers={"Content-Type": "video/mp4"})
    response = asyncio.run(run())
    assert response.status_code == 413
    assert list(tmp_path.rglob("*.mp4")) == list(tmp_path.rglob("*.part")) == []


def test_invalid_video_is_removed_and_error_has_no_private_paths(tmp_path):
    class InvalidVideo:
        def validate(self, video):
            raise UploadError("INVALID_VIDEO", "動画ストリームを確認できませんでした。", 422)
    with TestClient(create_app(Settings(tmp_path), validator=InvalidVideo())) as client:
        response = send(client)
    assert response.status_code == 422
    assert response.json()["error"]["stage"] == "video_validation"
    assert not list(tmp_path.rglob("*.mp4"))
    assert str(tmp_path) not in response.text


def test_unexpected_error_does_not_expose_exception_text(tmp_path):
    class Broken(SampleAnalyzer):
        def analyze(self, video, pipeline):
            raise RuntimeError("private/path/or/identifier")
    app = create_app(Settings(tmp_path), analyzer=Broken(), validator=AcceptVideo())
    with TestClient(app) as client:
        response = send(client)
    assert response.status_code == 500
    assert response.json()["error"]["detail"] == "RuntimeError"
    assert "private/path" not in response.text


@pytest.mark.parametrize("all_failed", [False, True])
def test_partial_and_failed_results_preserve_feature_diagnostics(tmp_path, all_failed):
    class Partial(SampleAnalyzer):
        def analyze(self, video, pipeline):
            features = [] if all_failed else [Feature(id="valid", label="valid", value=0.0)]
            features.append(Feature(id="invalid", label="invalid", value=None, error=AnalysisError(code="FEATURE_FAILED", message="missing", stage="features")))
            return AnalysisResult(features=features)
    with TestClient(create_app(Settings(tmp_path), analyzer=Partial(), validator=AcceptVideo())) as client:
        body = send(client).json()
    assert body["status"] == ("failed" if all_failed else "partial")
    assert body["result"]["features"][-1]["error"]["code"] == "FEATURE_FAILED"
    assert (body["error"] is not None) == all_failed


def test_nonfinite_feature_values_are_rejected():
    for value in (float("nan"), float("inf")):
        with pytest.raises(ValidationError):
            Feature(id="invalid", label="invalid", value=value)


def test_simultaneous_request_is_rejected_without_saving_a_second_video(tmp_path):
    entered, release = threading.Event(), threading.Event()
    class Blocking(SampleAnalyzer):
        def analyze(self, video, pipeline):
            entered.set()
            assert release.wait(5)
            return super().analyze(video, pipeline)
    async def run():
        app = create_app(Settings(tmp_path), analyzer=Blocking(), validator=AcceptVideo())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            first = asyncio.create_task(client.post("/v1/analyses?pipeline=daily", content=b"synthetic-video", headers={"Content-Type": "video/mp4"}))
            try:
                assert await asyncio.to_thread(entered.wait, 5)
                second = await client.post("/v1/analyses?pipeline=daily", content=b"synthetic-video", headers={"Content-Type": "video/mp4"})
                assert second.status_code == 409
                assert second.json()["error"]["code"] == "SERVER_BUSY"
            finally:
                release.set()
            assert (await first).status_code == 200
    asyncio.run(run())
    assert len(list(tmp_path.rglob("*.mp4"))) == 1


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg tools not installed")
def test_real_video_probe_and_invalid_bytes(tmp_path):
    # Generate a plain colour clip. No camera footage or research data is used.
    clip = tmp_path / "synthetic.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=5", "-t", "0.4", "-c:v", "mpeg4", str(clip)], check=True, timeout=15)
    with TestClient(create_app(Settings(tmp_path / "server"))) as client:
        good = send(client, content=clip.read_bytes())
        bad = send(client, content=b"not-a-video")
    assert good.status_code == 200
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "INVALID_VIDEO"


def test_health_identifies_sample_backend(client):
    assert client.get("/health").json() == {"status": "ok", "analysis_mode": "sample", "pipelines": ["daily"]}
