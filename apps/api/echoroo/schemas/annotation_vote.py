"""Annotation vote request and response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from echoroo.models.enums import ConsensusStatus, DetectionStatus, SignalQuality, VoteType


class VoteCastRequest(BaseModel):
    """Request body for casting a vote on a detection annotation."""

    vote: VoteType = Field(..., description="Vote value: agree, disagree, or unsure")
    signal_quality: SignalQuality | None = Field(
        None,
        description="Signal quality assessment (solo/dominant/mixed), only applicable when vote is 'agree'",
    )
    suggested_tag_id: UUID | None = Field(
        None,
        description="Suggested correct species tag when disagreeing with the current identification",
    )
    note: str | None = Field(
        None,
        max_length=2000,
        description="Optional reason or comment for this vote",
    )


class VoteUserInfo(BaseModel):
    """Minimal user info embedded in vote responses."""

    id: UUID
    email: str
    display_name: str | None = None

    model_config = {"from_attributes": True}


class VoteResponse(BaseModel):
    """Single vote record in a vote summary."""

    id: UUID
    annotation_id: UUID
    user_id: UUID
    vote: VoteType
    signal_quality: SignalQuality | None
    suggested_tag_id: UUID | None
    note: str | None
    created_at: datetime
    user: VoteUserInfo

    model_config = {"from_attributes": True}


class VoteSummaryResponse(BaseModel):
    """Vote summary for a detection annotation.

    Includes aggregate counts, the current user's vote (if any), the computed
    consensus status, and the full list of individual votes.
    """

    annotation_id: UUID = Field(..., description="Annotation UUID")
    agree_count: int = Field(..., ge=0, description="Number of agree votes")
    disagree_count: int = Field(..., ge=0, description="Number of disagree votes")
    unsure_count: int = Field(..., ge=0, description="Number of unsure votes")
    user_vote: VoteType | None = Field(
        None,
        description="Current user's vote, or null if they haven't voted",
    )
    user_signal_quality: SignalQuality | None = Field(
        None,
        description="Current user's signal quality assessment, or null if they haven't voted agree",
    )
    signal_quality_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Counts of signal quality values among agree votes (solo/dominant/mixed)",
    )
    consensus_status: DetectionStatus = Field(
        ...,
        description="Annotation review status (computed from votes)",
    )
    votes: list[VoteResponse] = Field(
        default_factory=list,
        description="Individual vote records",
    )

    model_config = {"from_attributes": True}


class DetectionVoteCounts(BaseModel):
    """Compact vote counts embedded in detection list/detail responses."""

    agree_count: int = Field(0, ge=0)
    disagree_count: int = Field(0, ge=0)
    unsure_count: int = Field(0, ge=0)
    user_vote: VoteType | None = Field(None)
    user_signal_quality: SignalQuality | None = Field(None)
    signal_quality_counts: dict[str, int] = Field(default_factory=dict)
    consensus_status: ConsensusStatus = Field(ConsensusStatus.NEEDS_VOTES)
