from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


WorkflowStatus = Literal[
    "waiting_for_video",
    "waiting_for_transcript",
    "ready_for_analysis",
    "analyzing",
    "pending_review",
    "reviewed",
    "rendering",
    "clips_ready",
    "partial_failure",
]

CandidateStatus = Literal[
    "suggested",
    "edited",
    "approved",
    "rejected",
    "render_queued",
    "rendering",
    "rendered",
    "published",
    "failed",
]

CandidateCategory = Literal[
    "quote",
    "argument",
    "revelation",
    "context",
    "conflict",
    "explanation",
    "other",
]

AnalysisRunStatus = Literal[
    "queued",
    "analyzing",
    "complete",
    "failed",
    "stale",
]


class VideoState(BaseModel):
    video_uuid: UUID
    status: WorkflowStatus = "waiting_for_video"
    created_at: datetime
    updated_at: datetime


class VideoStatusUpdate(BaseModel):
    status: WorkflowStatus


class CandidateCreate(BaseModel):
    anchor_start: float = Field(ge=0)
    anchor_end: float = Field(gt=0)
    suggested_start: float = Field(ge=0)
    suggested_end: float = Field(gt=0)
    canonical_transcript: str = Field(min_length=1)
    category: CandidateCategory | None = None
    analysis_reason: str | None = Field(default=None, max_length=500)


class CandidateReview(BaseModel):
    status: Literal["edited", "approved", "rejected"]
    editor_start: float | None = Field(default=None, ge=0)
    editor_end: float | None = Field(default=None, gt=0)
    acted_by_user_id: int = Field(gt=0)


class AnalysisRunClaim(BaseModel):
    caption_language: str = Field(min_length=1, max_length=64)
    caption_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    analyzer_version: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=200)
    prompt_version: str = Field(min_length=1, max_length=200)


class AnalysisRunUpdate(BaseModel):
    status: AnalysisRunStatus
    error: str | None = Field(default=None, max_length=4000)
