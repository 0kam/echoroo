"""Annotation-set dataset ZIP export (CSV labels + per-segment audio clips).

This bundles an annotation set's CamtrapDP labels together with the audio
clip for every FINALIZED segment so a user can validate a model's accuracy
on the exact segment audio that was annotated. The export universe is the
SAME finalized-segment predicate the evaluation worker uses
(``AnnotationSegment.status == AnnotationSegmentStatus.ANNOTATED``), which
includes confirmed-empty (``is_empty=True``) segments as NEGATIVES.

ZIP layout::

    annotations.csv         CamtrapDP + ToriTore rows (one per finalized
                            TimeRangeAnnotation; reuses
                            AnnotationSetExportService so the column shape is
                            identical to the CSV-only export).
    segments.csv            One row per finalized segment, including
                            confirmed-empty negatives, with a ``clip_path``
                            pointing into ``clips/`` (empty when the clip could
                            not be extracted).
    clips/<segment_id>.wav  16-bit PCM WAV slice of the segment audio.

The CSV labels reuse :class:`AnnotationSetExportService` rather than
duplicating the column logic, so the two exports stay consistent.

Concurrency / memory model
---------------------------
The async path (:meth:`AnnotationSetDatasetExportService.prepare_plan`) does
ALL database / ORM access up front and returns a plain, ORM-free
:class:`DatasetExportPlan` (the rendered ``annotations.csv`` text plus a flat
list of :class:`SegmentClipSpec`). The blocking work — S3 GET, libsndfile
decode, WAV encode, DEFLATE — is then offloaded to a worker thread via
:func:`asyncio.to_thread` (:func:`write_dataset_zip`), which NEVER touches the
session and streams each clip straight into a temp file on disk so peak memory
stays ``O(one clip)`` rather than ``O(whole dataset)``.
"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from echoroo.models.annotation_set import (
    AnnotationSegment,
    AnnotationSet,
)
from echoroo.models.enums import AnnotationSegmentStatus
from echoroo.services.annotation_set_export import AnnotationSetExportService

if TYPE_CHECKING:  # pragma: no cover - typing only
    from echoroo.services.audio import AudioService

logger = logging.getLogger(__name__)

# segments.csv manifest columns. ``clip_path`` is relative to the ZIP root and
# is left blank when the clip failed to extract so negatives stay explicit and
# missing-audio segments are unambiguous for model validation.
_SEGMENT_COLUMNS = [
    "segment_id",
    "recording_id",
    "clip_path",
    "recording_start_sec",
    "recording_end_sec",
    "duration_sec",
    "status",
    "is_empty",
    "n_annotations",
]


def _format_float(value: float | None) -> str:
    """Render a nullable float, blank when ``None``."""
    if value is None:
        return ""
    return f"{value:.4f}"


@dataclass(slots=True)
class SegmentClipSpec:
    """One finalized segment's plain, ORM-free export descriptor.

    Built in the async path from eager-loaded ORM rows so the sync ZIP-assembly
    thread can extract the clip and render ``segments.csv`` WITHOUT touching the
    database session (no lazy attribute access). All fields are plain values.
    """

    segment_id: UUID
    recording_id: UUID
    recording_path: str | None
    start_sec: float
    end_sec: float
    channel: int | None
    duration_sec: float
    status: str
    is_empty: bool
    n_annotations: int


@dataclass(slots=True)
class DatasetExportPlan:
    """All data needed to assemble the dataset ZIP, captured ORM-free.

    Produced by the async path (:meth:`prepare_plan`) and consumed by the sync
    :func:`write_dataset_zip` thread. ``annotations_csv`` is the already
    rendered CamtrapDP + ToriTore CSV text (no audio dependency); ``segments``
    is the flat per-segment manifest.
    """

    annotations_csv: str
    segments: list[SegmentClipSpec] = field(default_factory=list)


def _render_segments_csv(
    segments: list[SegmentClipSpec],
    extracted: set[UUID],
) -> str:
    """Render the per-segment manifest, exposing negatives + missing clips.

    ``clip_path`` is blank when the segment's clip is NOT in ``extracted``
    (extraction failed); otherwise ``clips/<segment_id>.wav``. ``n_annotations``
    is 0 for confirmed-empty negatives.
    """
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_SEGMENT_COLUMNS)
    writer.writeheader()
    for spec in segments:
        has_clip = spec.segment_id in extracted
        writer.writerow(
            {
                "segment_id": str(spec.segment_id),
                "recording_id": str(spec.recording_id),
                "clip_path": (
                    f"clips/{spec.segment_id}.wav" if has_clip else ""
                ),
                "recording_start_sec": _format_float(spec.start_sec),
                "recording_end_sec": _format_float(spec.end_sec),
                "duration_sec": _format_float(spec.duration_sec),
                "status": spec.status,
                "is_empty": "true" if spec.is_empty else "false",
                "n_annotations": str(spec.n_annotations),
            }
        )
    return buf.getvalue()


def write_dataset_zip(
    plan: DatasetExportPlan,
    audio_service: AudioService,
    out_path: str,
) -> None:
    """Assemble the dataset ZIP on disk from a plan (BLOCKING — run in a thread).

    This is the heavy, synchronous half of the export: it performs the blocking
    S3 GET (``ensure_file_local``), libsndfile decode (``read_audio``) and WAV
    encode (``audio_to_wav_bytes``), then DEFLATE-compresses each clip straight
    into ``out_path`` so peak memory stays ``O(one clip)``. It MUST NOT touch
    the database session — every value it needs is already on ``plan``.

    The source recording is localised ONCE per distinct ``recording_path``
    (clips that share a recording reuse the cached file). A per-clip failure
    (missing source / decode error) is logged and swallowed so a single bad
    segment never aborts the whole export; that clip's ``clip_path`` is then
    left blank in ``segments.csv``.

    Designed to be invoked via ``await asyncio.to_thread(write_dataset_zip, ...)``.
    """
    # Group clip specs by distinct recording so the (potentially S3-backed)
    # source file is localised ONCE per recording, not once per clip.
    by_recording: dict[str, list[SegmentClipSpec]] = defaultdict(list)
    no_source: list[SegmentClipSpec] = []
    for spec in plan.segments:
        if not spec.recording_path:
            no_source.append(spec)
            continue
        by_recording[spec.recording_path].append(spec)

    for spec in no_source:
        logger.warning(
            "Dataset export: segment %s has no source recording/path; "
            "skipping clip",
            spec.segment_id,
        )

    extracted: set[UUID] = set()

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for recording_path, recording_segments in by_recording.items():
            try:
                audio_service.ensure_file_local(recording_path)
            except Exception:  # noqa: BLE001 - missing source must not abort
                logger.warning(
                    "Dataset export: could not localise recording path=%s; "
                    "skipping %d clip(s)",
                    recording_path,
                    len(recording_segments),
                    exc_info=True,
                )
                continue
            for spec in recording_segments:
                try:
                    data, samplerate = audio_service.read_audio(
                        recording_path,
                        start=spec.start_sec,
                        end=spec.end_sec,
                        channel=spec.channel,
                    )
                    wav_bytes = audio_service.audio_to_wav_bytes(
                        data, samplerate
                    )
                except Exception:  # noqa: BLE001 - one bad clip must not abort
                    logger.warning(
                        "Dataset export: failed to extract clip for segment %s "
                        "(recording=%s, %.3f-%.3f); leaving clip_path empty",
                        spec.segment_id,
                        spec.recording_id,
                        spec.start_sec,
                        spec.end_sec,
                        exc_info=True,
                    )
                    continue
                # Write the clip immediately so only one clip's bytes are held
                # in memory at a time (peak RAM is O(one clip)).
                zf.writestr(f"clips/{spec.segment_id}.wav", wav_bytes)
                extracted.add(spec.segment_id)

        # CSVs reflect ACTUAL extraction success: clip_path is blank for any
        # segment whose clip could not be extracted above.
        zf.writestr("annotations.csv", plan.annotations_csv)
        zf.writestr(
            "segments.csv", _render_segments_csv(plan.segments, extracted)
        )


class AnnotationSetDatasetExportService:
    """Assemble an annotation set's CSV labels + segment clips into a ZIP.

    Split into an async planning phase (:meth:`prepare_plan`, all DB/ORM work)
    and a sync assembly phase (:func:`write_dataset_zip`, all blocking audio +
    ZIP work, run off the event loop) so the export never pins the event loop.
    """

    def __init__(self, db: AsyncSession, audio_service: AudioService) -> None:
        """Initialise with an async session and an :class:`AudioService`."""
        self.db = db
        self.audio = audio_service
        self._csv = AnnotationSetExportService(db)

    async def _require_set(self, set_id: UUID) -> AnnotationSet:
        """Load the set (no relationships) — caller validates project scope."""
        result = await self.db.execute(
            select(AnnotationSet).where(AnnotationSet.id == set_id)
        )
        anno_set: AnnotationSet | None = result.scalar_one_or_none()
        if anno_set is None:
            msg = f"Annotation set not found: {set_id}"
            raise ValueError(msg)
        return anno_set

    async def _fetch_finalized_segments(
        self, set_id: UUID
    ) -> list[AnnotationSegment]:
        """Load every finalized segment (the export universe) with relations.

        Eager-loads ``recording`` (for ``recording.path`` / the clip source)
        and ``annotations`` (for the per-segment ``n_annotations`` count). The
        predicate matches the evaluation worker's finalized universe
        (``status == ANNOTATED``), which includes confirmed-empty negatives.
        """
        result = await self.db.execute(
            select(AnnotationSegment)
            .where(AnnotationSegment.annotation_set_id == set_id)
            .where(AnnotationSegment.status == AnnotationSegmentStatus.ANNOTATED)
            .options(
                selectinload(AnnotationSegment.recording),
                selectinload(AnnotationSegment.annotations),
            )
            .order_by(
                AnnotationSegment.recording_id,
                AnnotationSegment.start_time_sec,
            )
        )
        return list(result.scalars().all())

    async def count_finalized_segments(self, set_id: UUID) -> int:
        """Return the number of finalized (``ANNOTATED``) segments in the set.

        Used by the endpoint's preview safety guard to reject oversized exports
        BEFORE any audio is touched. Counts the SAME finalized universe the ZIP
        export bundles.
        """
        from sqlalchemy import func

        result = await self.db.execute(
            select(func.count())
            .select_from(AnnotationSegment)
            .where(AnnotationSegment.annotation_set_id == set_id)
            .where(AnnotationSegment.status == AnnotationSegmentStatus.ANNOTATED)
        )
        return int(result.scalar_one())

    async def prepare_plan(
        self, *, project_id: UUID, set_id: UUID
    ) -> DatasetExportPlan:
        """Do ALL async DB/ORM work and return an ORM-free export plan.

        Renders ``annotations.csv`` (CamtrapDP + ToriTore, scoped to the
        finalized universe so every label row's segment also has a clip) and a
        flat, lazy-attribute-free per-segment manifest. The returned
        :class:`DatasetExportPlan` is safe to hand to the sync
        :func:`write_dataset_zip` thread (it captures no ORM rows / session).

        Raises :class:`ValueError` if the set does not exist (caller maps 404).
        """
        await self._require_set(set_id)

        # CamtrapDP label rows, scoped to the finalized universe so every
        # annotation row's segment also has a clip in the bundle. Reuses the
        # CSV export's column logic verbatim and renders to text up front so the
        # sync thread has no audio-independent work left to do.
        annotation_rows = await self._csv.build_csv_rows(
            project_id=project_id,
            set_id=set_id,
            finalized_only=True,
        )
        annotations_csv = AnnotationSetExportService.render_csv(annotation_rows)

        segments = await self._fetch_finalized_segments(set_id)

        specs: list[SegmentClipSpec] = []
        for seg in segments:
            recording = seg.recording
            n_annotations = (
                len(seg.annotations) if seg.annotations is not None else 0
            )
            specs.append(
                SegmentClipSpec(
                    segment_id=seg.id,
                    recording_id=seg.recording_id,
                    recording_path=recording.path if recording else None,
                    start_sec=seg.start_time_sec,
                    end_sec=seg.end_time_sec,
                    # AnnotationSegment has no channel column → read all
                    # channels (mirrors AudioService.read_audio default).
                    channel=None,
                    duration_sec=seg.end_time_sec - seg.start_time_sec,
                    status=seg.status.value,
                    is_empty=bool(seg.is_empty),
                    n_annotations=n_annotations,
                )
            )

        return DatasetExportPlan(
            annotations_csv=annotations_csv,
            segments=specs,
        )
