"""Reference-audio streaming helper for search sessions.

W2-4 PR-B: the ``GET /sessions/{session_id}/reference-audio/{source_index}``
route was unmounted from ``/api/v1`` in favour of the ``/web-api/v1`` BFF
media-token surface. ``stream_reference_audio`` stays importable as a helper
that ``echoroo.api.web_v1.projects._search`` delegates to (it gate_action-guards
itself); no ``@router.get`` decorator is mounted here.
"""

from __future__ import annotations

import collections.abc
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from echoroo.api.v1.search.deps import AuthorizedSearchSessionServiceDep
from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentUser

logger = logging.getLogger(__name__)


async def stream_reference_audio(
    project_id: UUID,
    session_id: UUID,
    source_index: int,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    session_service: AuthorizedSearchSessionServiceDep,
    range: str | None = Header(None),
) -> StreamingResponse:
    """Stream a reference audio file stored in S3 for a search session.

    Args:
        project_id: Project UUID (path parameter)
        session_id: Session UUID (path parameter)
        source_index: Index into the session's reference_audio_keys list
        request: FastAPI request
        current_user: Authenticated caller
        db: Database session
        session_service: Authorized search session service
        range: Optional HTTP Range header for partial content streaming

    Returns:
        StreamingResponse with audio content

    Raises:
        403: Access denied to project
        404: Session not found or source_index out of bounds
        500: S3 retrieval error
    """
    import mimetypes

    from echoroo.core.actions import SEARCH_SESSION_REFERENCE_AUDIO_ACTION
    from echoroo.core.permissions import gate_action

    await gate_action(
        action=SEARCH_SESSION_REFERENCE_AUDIO_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    session = await session_service.get_session(session_id, project_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found"
        )

    if not session.reference_audio_keys or source_index >= len(session.reference_audio_keys):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reference audio source index {source_index} not found",
        )

    if source_index < 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid source index",
        )

    s3_key = session.reference_audio_keys[source_index]

    try:
        from echoroo.core.s3 import get_s3_client as _get_s3_stream_client
        from echoroo.core.settings import get_settings as _get_stream_settings

        _stream_settings = _get_stream_settings()
        _stream_client = _get_s3_stream_client()
        s3_params: dict[str, Any] = {
            "Bucket": _stream_settings.S3_BUCKET,
            "Key": s3_key,
        }
        if range:
            s3_params["Range"] = range
        s3_response = _stream_client.get_object(**s3_params)
    except Exception as exc:
        logger.exception("Failed to stream reference audio key=%s", s3_key)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve reference audio from storage",
        ) from exc

    body = s3_response["Body"]
    content_length = s3_response.get("ContentLength")

    # Determine content type from file extension
    suffix = Path(s3_key).suffix.lower()
    content_type, _ = mimetypes.guess_type(f"file{suffix}")
    if not content_type:
        content_type = "audio/wav"

    def _iter_stream() -> collections.abc.Iterator[bytes]:
        try:
            while True:
                chunk = body.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            body.close()

    response_headers: dict[str, str] = {}
    if content_length is not None:
        response_headers["Content-Length"] = str(content_length)
    response_headers["Accept-Ranges"] = "bytes"

    response_status = 206 if range else 200
    if range and "ContentRange" in s3_response:
        response_headers["Content-Range"] = s3_response["ContentRange"]

    return StreamingResponse(
        _iter_stream(),
        status_code=response_status,
        media_type=content_type,
        headers=response_headers,
    )
