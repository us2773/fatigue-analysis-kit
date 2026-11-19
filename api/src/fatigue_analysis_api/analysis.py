"""Replaceable analysis adapters, independent of HTTP and upload handling."""

from pathlib import Path
from typing import Protocol

from .models import AnalysisResult, Feature


class Analyzer(Protocol):
    version: str
    parameter_set_id: str | None
    mode: str

    def analyze(self, video: Path, pipeline: str) -> AnalysisResult: ...


class SampleAnalyzer:
    """Synthetic output for upload/display testing; no fatigue analysis is run."""

    version = "sample-v1"
    parameter_set_id = None
    mode = "sample"

    def analyze(self, video: Path, pipeline: str) -> AnalysisResult:
        return AnalysisResult(
            features=[
                Feature(id="AU02_trend_mean", label="AU02 トレンド平均", value=2.18)
            ]
        )
