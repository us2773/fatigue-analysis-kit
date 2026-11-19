"""Response contract shared by sample and future real analysis adapters."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisError(Contract):
    code: str
    message: str
    stage: str
    detail: str | None = None


class Feature(Contract):
    id: str
    label: str
    value: FiniteFloat | None
    describe: str | None = None
    error: AnalysisError | None = None


class Summary(Contract):
    message: str | None = None
    advise: str | None = None


class AnalysisResult(Contract):
    features: list[Feature]
    summary: Summary = Field(default_factory=Summary)


class Metadata(Contract):
    pipeline: str | None = None
    analysis_version: str | None = None
    parameter_set_id: str | None = None


class AnalysisResponse(Contract):
    schema_version: str = "1.0"
    analysis_id: str
    status: Literal["succeeded", "partial", "failed"]
    result: AnalysisResult | None = None
    error: AnalysisError | None = None
    metadata: Metadata = Field(default_factory=Metadata)
