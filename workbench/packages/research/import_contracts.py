"""Typed historical import input shared by HTTP validation and saved manifests."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class HistoricalImportRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_record_id: str = Field(min_length=1, max_length=200)
    bid_id: UUID
    actual_document_version_id: UUID
    submitted_at: datetime
    evidence_ref: UUID
    explanation: str = Field(min_length=1, max_length=4000)
    score_kind: Literal["technical_total", "comprehensive_total", "unknown"]
    value: str | None = Field(pattern=r"^(0|[1-9][0-9]*)(\.[0-9]+)?$")
    maximum: str | None = Field(pattern=r"^(0|[1-9][0-9]*)(\.[0-9]+)?$")
    source_version_id: UUID | None
    known_at: datetime | None


class HistoricalImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    records: list[HistoricalImportRecord] = Field(min_length=1, max_length=1000)
