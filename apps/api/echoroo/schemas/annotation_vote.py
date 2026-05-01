"""Annotation vote request and response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from echoroo.models.enums import (
    AnnotationVoteSource,
    ConsensusStatus,
    DetectionStatus,
    ProjectMemberRole,
    SignalQuality,
    VoteType,
)


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
    """Single vote record in a vote summary.

    FR-039: ``user_id`` is masked to ``None`` (and ``user`` is omitted) for
    non-Owner / non-Admin viewers when the vote's ``source`` is
    ``guest_authenticated`` or ``trusted_user``. The vote itself, its
    ``source``, and ``project_role_at_vote`` remain visible (vote visibility
    is preserved).
    """

    id: UUID
    annotation_id: UUID
    user_id: UUID | None = Field(
        None,
        description=(
            "Voter UUID. Masked to ``null`` for non-member / Trusted votes when"
            " the viewer is not Owner / Admin (FR-039)."
        ),
    )
    vote: VoteType
    signal_quality: SignalQuality | None
    suggested_tag_id: UUID | None
    note: str | None
    created_at: datetime
    user: VoteUserInfo | None = Field(
        None,
        description=(
            "Voter info embed. Omitted (``null``) when ``user_id`` is masked"
            " (FR-039)."
        ),
    )
    source: AnnotationVoteSource = Field(
        ...,
        description="Voter relationship at vote-creation time (FR-037, immutable)",
    )
    project_role_at_vote: ProjectMemberRole | None = Field(
        None,
        description=(
            "Voter's project role at vote-creation time. Null when source is"
            " not ``member`` (FR-037, immutable snapshot)."
        ),
    )

    model_config = {"from_attributes": True}


class VoteSummaryResponse(BaseModel):
    """Vote summary for a detection annotation.

    Includes aggregate counts, the current user's vote (if any), the computed
    consensus status, and the full list of individual votes (``voters[]``,
    matching ``VoteAggregateResponse`` in ``contracts/detections.yaml``).
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
    voters: list[VoteResponse] = Field(
        default_factory=list,
        description=(
            "Individual vote records. Field name matches ``VoteAggregateResponse.voters``"
            " in ``contracts/detections.yaml`` (FR-038 / FR-039)."
        ),
    )
    # FR-038: per-source aggregate counts. Member / guest_authenticated /
    # trusted_user counts are exposed independently so the UI can show the
    # 3-source breakdown required by US2 acceptance scenario #3.
    member_agree: int = Field(
        0, ge=0, description="Agree votes from project members (FR-038)",
    )
    member_disagree: int = Field(
        0, ge=0, description="Disagree votes from project members (FR-038)",
    )
    guest_authenticated_agree: int = Field(
        0, ge=0, description="Agree votes from authenticated non-members (FR-038)",
    )
    guest_authenticated_disagree: int = Field(
        0, ge=0, description="Disagree votes from authenticated non-members (FR-038)",
    )
    trusted_user_agree: int = Field(
        0, ge=0, description="Agree votes from active Trusted users (FR-038)",
    )
    trusted_user_disagree: int = Field(
        0, ge=0, description="Disagree votes from active Trusted users (FR-038)",
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
