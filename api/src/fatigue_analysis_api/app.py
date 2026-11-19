"""Single-worker video API. Run with: uvicorn fatigue_analysis_api.app:app."""

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect

from .analysis import Analyzer, SampleAnalyzer
from .models import AnalysisError, AnalysisResponse, Metadata
from .storage import UploadError, VideoStore, media_extension
from .video import FFprobeValidator, VideoValidator

logger = logging.getLogger("fatigue_analysis_api")


async def run_adapter(func, *args):
    # Cancelling an HTTP request does not stop a thread. Keep the single-request
    # lock until the adapter actually stops using the input file.
    work = asyncio.create_task(asyncio.to_thread(func, *args))
    try:
        return await asyncio.shield(work)
    except asyncio.CancelledError:
        try:
            await work
        finally:
            raise


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    max_upload_bytes: int = 256 * 1024 * 1024
    ffprobe: str = "ffprobe"

    def __post_init__(self):
        if self.max_upload_bytes <= 0:
            raise ValueError("max_upload_bytes must be positive")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            data_dir=Path(os.environ.get("FF_API_DATA_DIR", "data")).resolve(),
            max_upload_bytes=int(os.environ.get("FF_API_MAX_UPLOAD_BYTES", 256 * 1024 * 1024)),
            ffprobe=os.environ.get("FF_API_FFPROBE", "ffprobe"),
        )


def create_app(
    settings: Settings | None = None,
    analyzer: Analyzer | None = None,
    validator: VideoValidator | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    analyzer = analyzer or SampleAnalyzer()
    validator = validator or FFprobeValidator(settings.ffprobe)
    store = VideoStore(settings.data_dir, settings.max_upload_bytes)
    busy = asyncio.Lock()
    app = FastAPI(title="Fatigue analysis API (sample backend)", version="0.1.0")

    @app.get("/health")
    async def health():
        return {"status": "ok", "analysis_mode": analyzer.mode, "pipelines": ["daily"]}

    @app.post("/v1/analyses", response_model=AnalysisResponse)
    async def analyze(request: Request):
        analysis_id = uuid4().hex
        metadata = Metadata(
            analysis_version=analyzer.version,
            parameter_set_id=analyzer.parameter_set_id,
        )
        headers = {"X-Analysis-Mode": analyzer.mode, "Cache-Control": "no-store"}

        def fail(code, message, http_status, stage, detail=None):
            # Log server-generated IDs/codes only, never filenames, bodies or exception text.
            logger.warning("analysis_id=%s code=%s stage=%s", analysis_id, code, stage)
            response = AnalysisResponse(
                analysis_id=analysis_id,
                status="failed",
                metadata=metadata,
                error=AnalysisError(
                    code=code, message=message, stage=stage, detail=detail
                ),
            )
            return JSONResponse(
                response.model_dump(mode="json"),
                status_code=http_status,
                headers=headers,
            )

        params = request.query_params
        if set(params) != {"pipeline"} or params.getlist("pipeline") != ["daily"]:
            return fail(
                "INVALID_PIPELINE",
                "pipeline=daily のみ指定できます。パラメータの上書きはできません。",
                400,
                "request",
            )
        try:
            extension = media_extension(request.headers.get("content-type", ""))
            length = request.headers.get("content-length")
            if length is not None:
                try:
                    length = int(length)
                except ValueError as exc:
                    raise UploadError(
                        "INVALID_CONTENT_LENGTH", "Content-Lengthが不正です。"
                    ) from exc
                if length < 0:
                    raise UploadError("INVALID_CONTENT_LENGTH", "Content-Lengthが不正です。")
                if length > settings.max_upload_bytes:
                    raise UploadError("VIDEO_TOO_LARGE", "動画の容量が上限を超えています。", 413)
        except UploadError as exc:
            return fail(exc.code, str(exc), exc.http_status, "request")

        if busy.locked():
            return fail(
                "SERVER_BUSY", "別の動画を処理中です。完了後に再試行してください。",
                409, "request",
            )

        async with busy:
            stage = "upload"
            video = None
            validated = False
            try:
                with store.begin(analysis_id, extension) as pending:
                    async for chunk in request.stream():
                        pending.write(chunk)
                    video = pending.finish()
                stage = "video_validation"
                await run_adapter(validator.validate, video)
                validated = True
                metadata.pipeline = "daily"
                stage = "analysis"
                result = await run_adapter(analyzer.analyze, video, "daily")
                available = sum(feature.value is not None for feature in result.features)
                if not available:
                    status = "failed"
                elif available < len(result.features):
                    status = "partial"
                else:
                    status = "succeeded"
                error = None
                if not available:
                    error = AnalysisError(
                        code="NO_VALID_FEATURES",
                        message="算出できた特徴量がありません。",
                        stage="analysis",
                    )
                response = AnalysisResponse(
                    analysis_id=analysis_id,
                    status=status,
                    result=result,
                    metadata=metadata,
                    error=error,
                )
                logger.info("analysis_id=%s status=%s mode=%s", analysis_id, status, analyzer.mode)
                return JSONResponse(response.model_dump(mode="json"), headers=headers)
            except UploadError as exc:
                return fail(exc.code, str(exc), exc.http_status, stage)
            except ClientDisconnect:
                return fail("UPLOAD_INTERRUPTED", "動画の送信が中断されました。", 400, stage)
            except Exception as exc:
                # A class name helps debugging without disclosing paths or raw data.
                return fail("INTERNAL_ERROR", "サーバ処理に失敗しました。", 500, stage, type(exc).__name__)
            finally:
                if video is not None and not validated:
                    try:
                        video.unlink(missing_ok=True)
                    except OSError:
                        logger.error("analysis_id=%s code=UPLOAD_CLEANUP_FAILED", analysis_id)

    return app


app = create_app()
