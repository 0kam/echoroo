"""Shared mapping helpers for annotation notes.

Both :class:`~echoroo.services.annotation_segment.AnnotationSegmentService`
and :class:`~echoroo.services.time_range_annotation.TimeRangeAnnotationService`
expose ``Note`` rows attached to their respective entities, so the ORM →
schema mapping lives here to keep the two surfaces byte-identical.
"""

from __future__ import annotations

from collections.abc import Iterable

from echoroo.models.note import Note
from echoroo.schemas.annotation_set import AnnotationNoteResponse


def note_to_response(note: Note) -> AnnotationNoteResponse:
    """Map a ``Note`` ORM row onto its API response schema."""
    return AnnotationNoteResponse(
        id=note.id,
        content=note.content,
        is_issue=note.is_issue,
        is_review=note.is_review,
        created_by_id=note.created_by_id,
        created_at=note.created_at,
    )


def notes_to_responses(notes: Iterable[Note]) -> list[AnnotationNoteResponse]:
    """Map ``Note`` rows onto response schemas, oldest first.

    Callers may pass eagerly-loaded relationship collections, whose order is
    undefined; sorting here gives the API the same "oldest first" contract as
    the repository-level ``list_notes`` queries.
    """
    return [note_to_response(n) for n in sorted(notes, key=lambda n: n.created_at)]


__all__ = ["note_to_response", "notes_to_responses"]
