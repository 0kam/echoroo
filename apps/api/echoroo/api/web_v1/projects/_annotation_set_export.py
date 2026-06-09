"""Annotation-set CSV export BFF adapter (CamtrapDP + ToriTore).

Mirrors the detection CSV export adapter
(:mod:`echoroo.api.web_v1.projects._detection_export`): a thin endpoint on the
cookie + CSRF session boundary that fires :func:`gate_action` once with the
SAME set-view Action used by the annotation-set GET / eligibility endpoints
(``ANNOTATION_CLIP_GET_ACTION``), validates that the set exists and belongs to
the project (404 otherwise), then returns a
:class:`fastapi.responses.StreamingResponse` of the CamtrapDP observations CSV.

The CSV column shape equals the detection export's CamtrapDP + FR-086 block
plus three trailing ToriTore proficiency columns
(``annotator_species_score`` / ``annotator_total_score`` /
``annotator_test_reference``), followed by the six segment / recording offset
columns (``segment_id``, ``recording_id``, ``segment_start_sec``,
``segment_end_sec``, ``recording_start_sec``, ``recording_end_sec``). Note that
``mediaID`` now carries the SEGMENT id (the annotation set is segment-centric);
the source recording stays available via ``recording_id``. See
:mod:`echoroo.services.annotation_set_export`.

Permission guard allowlist
--------------------------
This adapter fires ``gate_action`` before streaming, so
``scripts/lint_permission_guard.py`` is satisfied with no new entry.

Response filter allowlist
-------------------------
The response is a binary ``text/csv`` stream that never names
``Recording`` / ``Detection`` / ``Site`` as a Pydantic response model, so no
``response_filter`` allowlist entry is required.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask

from echoroo.core.actions import ANNOTATION_CLIP_GET_ACTION
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.core.settings import get_settings
from echoroo.middleware.auth import CurrentUser
from echoroo.services.annotation_set_dataset_export import (
    AnnotationSetDatasetExportService,
    write_dataset_zip,
)
from echoroo.services.annotation_set_export import AnnotationSetExportService
from echoroo.services.audio import AudioService

router = APIRouter()

# Preview safety bound: refuse to build a dataset ZIP for an annotation set with
# more than this many finalized segments. Combined with temp-file streaming
# (peak RAM is O(one clip)) this is defense-in-depth against a pathological
# export pinning a worker / filling disk in the preview environment.
_MAX_DATASET_SEGMENTS = 5000


def _build_content_disposition(name: str | None, fallback_id: UUID) -> str:
    """Build an RFC 6266 ``Content-Disposition`` for a ``<name>_dataset.zip``.

    Non-ASCII set names (the norm in this Japanese app) cannot go into the raw
    header value because Starlette/uvicorn encode header values as Latin-1 — a
    Japanese name would raise ``UnicodeEncodeError`` → HTTP 500. We therefore
    emit BOTH forms per RFC 6266:

    * an ASCII-only ``filename="..."`` fallback (``[A-Za-z0-9._-]`` only; other
      characters collapsed to ``_``; the set UUID when nothing survives), and
    * a ``filename*=UTF-8''...`` percent-encoded form carrying the real name.

    The returned value is guaranteed Latin-1 encodable (``filename*`` is
    percent-encoded ASCII), so the header never triggers a 500.
    """
    original = name or str(fallback_id)

    # ASCII fallback: keep only [A-Za-z0-9._-], collapse runs of replacements,
    # strip, and fall back to the UUID when nothing usable remains.
    ascii_chars = [
        ch if (ch.isascii() and (ch.isalnum() or ch in ("-", "_", "."))) else "_"
        for ch in original
    ]
    ascii_fallback = "".join(ascii_chars).strip("_")
    while "__" in ascii_fallback:
        ascii_fallback = ascii_fallback.replace("__", "_")
    if not ascii_fallback:
        ascii_fallback = str(fallback_id)
    ascii_filename = f"{ascii_fallback}_dataset.zip"

    # UTF-8 / percent-encoded form carrying the real (possibly non-ASCII) name.
    utf8_encoded = quote(f"{original}_dataset.zip", safe="")

    header = (
        f"attachment; filename=\"{ascii_filename}\"; "
        f"filename*=UTF-8''{utf8_encoded}"
    )
    # Defense-in-depth: confirm the header is Latin-1 encodable so it can never
    # surface as a 500 at the ASGI layer.
    header.encode("latin-1")
    return header


@router.get(
    "/{project_id}/annotation-sets/{set_id}/export/csv",
    summary="Export annotation set as CSV",
    description=(
        "Export an annotation set's TimeRangeAnnotations as a CamtrapDP "
        "observations CSV (one row per annotation), including the ToriTore "
        "per-annotator proficiency columns and the six segment / recording "
        "offset columns (segment_id, recording_id, segment_start_sec, "
        "segment_end_sec, recording_start_sec, recording_end_sec). mediaID "
        "carries the segment id (was the recording id). Gated by set-view "
        "access."
    ),
)
async def export_annotation_set_csv(
    project_id: UUID,
    set_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> StreamingResponse:
    """Stream the annotation-set CamtrapDP + ToriTore CSV.

    Uses the SAME set-view gate as the annotation-set GET / eligibility
    endpoints — any member who can view the set may export it.
    """
    await gate_action(
        action=ANNOTATION_CLIP_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    service = AnnotationSetExportService(db)
    # Validate existence + project scope BEFORE streaming so the response
    # status can still be a 404 (the stream commits the status on first yield).
    try:
        anno_set = await service._require_set(set_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annotation set not found",
        ) from exc
    if anno_set.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annotation set not found",
        )

    body_iterator = service.export_csv_stream(
        project_id=project_id,
        set_id=set_id,
    )
    return StreamingResponse(
        body_iterator,
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f"attachment; filename=annotation-set-{set_id}.csv"
            )
        },
    )


def _build_audio_service() -> AudioService:
    """Build an :class:`AudioService` from settings (mirrors clips.py)."""
    settings = get_settings()
    return AudioService(
        settings.AUDIO_ROOT,
        settings.AUDIO_CACHE_DIR,
        s3_audio_cache_dir=settings.S3_AUDIO_CACHE_DIR,
    )


@router.get(
    "/{project_id}/annotation-sets/{set_id}/export/dataset",
    summary="Export annotation set as a dataset ZIP",
    description=(
        "Export an annotation set as a ZIP bundling its CamtrapDP CSV labels "
        "(annotations.csv), a per-segment manifest (segments.csv) and the "
        "audio clip for every FINALIZED segment (clips/<segment_id>.wav), so a "
        "user can validate a model on the exact annotated segment audio. "
        "Gated by set-view access (same as the CSV export)."
    ),
)
async def export_annotation_set_dataset(
    project_id: UUID,
    set_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> Response:
    """Build and return the annotation-set dataset ZIP.

    Uses the SAME set-view gate as the CSV export (``ANNOTATION_CLIP_GET``) —
    it gates audio clip access.

    The build is split so it never pins the event loop or blows up memory:
    all DB/ORM work happens up front (:meth:`prepare_plan`), and the blocking
    audio decode + ZIP DEFLATE is offloaded to a worker thread
    (:func:`asyncio.to_thread`), streaming each clip into a temp file on disk
    so peak RAM is ``O(one clip)``. The temp file is returned via
    :class:`FileResponse` and deleted after the response is sent.
    """
    await gate_action(
        action=ANNOTATION_CLIP_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    service = AnnotationSetDatasetExportService(db, _build_audio_service())
    try:
        anno_set = await service._require_set(set_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annotation set not found",
        ) from exc
    if anno_set.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annotation set not found",
        )

    # Preview safety bound: refuse pathologically large exports before touching
    # any audio (defense-in-depth alongside temp-file streaming).
    segment_count = await service.count_finalized_segments(set_id)
    if segment_count > _MAX_DATASET_SEGMENTS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Annotation set has {segment_count} finalized segments, "
                f"exceeding the export limit of {_MAX_DATASET_SEGMENTS}."
            ),
        )

    # All DB/ORM access happens here, returning an ORM-free plan that is safe to
    # hand to the blocking worker thread.
    plan = await service.prepare_plan(project_id=project_id, set_id=set_id)

    # Assemble the ZIP on disk in a worker thread so the heavy, synchronous S3
    # GET / libsndfile decode / WAV encode / DEFLATE work never blocks the
    # event loop. NamedTemporaryFile is created closed (delete=False) so the
    # thread can reopen it via the path; cleanup is deferred to the response.
    tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115 - closed below, unlinked after send
        suffix=".zip", delete=False
    )
    tmp_path = tmp.name
    tmp.close()
    try:
        await asyncio.to_thread(
            write_dataset_zip, plan, service.audio, tmp_path
        )
    except Exception:
        # Build failed before we could hand ownership to FileResponse — clean
        # up the temp file ourselves so it does not leak.
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise

    content_disposition = _build_content_disposition(anno_set.name, set_id)
    return FileResponse(
        tmp_path,
        media_type="application/zip",
        headers={"Content-Disposition": content_disposition},
        background=BackgroundTask(os.unlink, tmp_path),
    )
