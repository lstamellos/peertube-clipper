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


class VideoState(BaseModel):
    video_uuid: UUID
    status: WorkflowStatus = "waiting_for_video"
    created_at: datetime
    updated_at: datetime


class CandidateCreate(BaseModel):
    anchor_start: float = Field(ge=0)
    anchor_end: float = Field(gt=0)
    suggested_start: float = Field(ge=0)
    suggested_end: float = Field(gt=0)
    canonical_transcript: str = Field(min_length=1)


class CandidateReview(BaseModel):
    status: Literal["edited", "approved", "rejected"]
    editor_start: float | None = Field(default=None, ge=0)
    editor_end: float | None = Field(default=None, gt=0)
    acted_by_user_id: int = Field(gt=0)
