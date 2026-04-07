"""Xeno-canto API proxy endpoints.

Proxies search requests to the Xeno-canto recording API, hiding the API key
from the frontend. All endpoints are scoped to a project_id for access control.
"""

from __future__ import annotations

import logging
import os
import urllib.parse
from collections.abc import AsyncIterator
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse

from echoroo.core.database import DbSession
from echoroo.core.permissions import check_project_access
from echoroo.middleware.auth import CurrentUser
from echoroo.schemas.xeno_canto import XenoCantoRecording, XenoCantoSearchResponse

logger = logging.getLogger(__name__)

# Xeno-canto API v3 base URL
XENO_CANTO_BASE_URL = "https://xeno-canto.org/api/3/recordings"

# Maximum page size accepted by the Xeno-canto API
XENO_CANTO_MAX_PER_PAGE = 100

# Maximum allowed audio file size in bytes (50 MB)
AUDIO_SIZE_LIMIT_BYTES = 50 * 1024 * 1024

router = APIRouter(prefix="/projects/{project_id}/xeno-canto", tags=["xeno-canto"])


def _get_api_key() -> str:
    """Return the Xeno-canto API key from the environment.

    Falls back to "demo" for development environments where the key is not set.

    Returns:
        Xeno-canto API key string
    """
    return os.environ.get("XENO_CANTO_API_KEY", "demo")




def _parse_float(value: str) -> float | None:
    """Parse a string to float, returning None on empty or invalid input.

    Args:
        value: String value to parse

    Returns:
        Float value or None if the string is empty or not a valid number
    """
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError:
        return None


def _build_xc_query(
    query: str,
    country: str | None,
    area: str | None,
    quality_min: str | None,
    recording_type: str | None,
) -> str:
    """Assemble a Xeno-canto query string from individual filter parameters.

    Xeno-canto uses a tag-based query syntax, e.g.:
    ``"Larus fuscus cnt:japan type:song q>:B"``

    Args:
        query: Base search query (species name, etc.)
        country: Country filter value (e.g. "japan")
        area: Continent/area filter (e.g. "asia")
        quality_min: Exact quality rating filter ("A"-"E")
        recording_type: Recording type filter (e.g. "song", "call")

    Returns:
        Combined query string for the Xeno-canto q parameter
    """
    # v3 requires tagged queries; wrap the species name with sp: tag
    species = query.strip()
    parts: list[str] = [f'sp:"{species}"']

    if country:
        parts.append(f"cnt:{country.strip()}")
    if area:
        parts.append(f"area:{area.strip()}")
    if quality_min:
        # XC API v3 uses exact quality match with q: tag
        parts.append(f"q:{quality_min.strip().upper()}")
    if recording_type:
        parts.append(f"type:{recording_type.strip()}")

    return " ".join(parts)


def _transform_recording(raw: dict[str, object]) -> XenoCantoRecording | None:
    """Transform a raw Xeno-canto API recording dict into our schema.

    Returns None if the recording dict is missing required fields.

    Args:
        raw: Raw recording dict from the Xeno-canto API response

    Returns:
        XenoCantoRecording instance, or None if the record is malformed
    """
    xc_id = str(raw.get("id") or "")
    if not xc_id:
        return None

    # Build the file download URL from the "file" field
    file_field = str(raw.get("file") or "")
    file_url = file_field if file_field.startswith("http") else f"https:{file_field}"

    # Sonogram (small) URL — "sono" is a nested dict in the XC API response
    sono_obj = raw.get("sono")
    sonogram_small = ""
    if isinstance(sono_obj, dict):
        sonogram_small = str(sono_obj.get("small") or "")
    sonogram_url: str | None = None
    if sonogram_small:
        sonogram_url = (
            sonogram_small if sonogram_small.startswith("http") else f"https:{sonogram_small}"
        )

    return XenoCantoRecording(
        xc_id=xc_id,
        scientific_name=str(raw.get("gen") or "") + " " + str(raw.get("sp") or ""),
        common_name=str(raw.get("en") or ""),
        recordist=str(raw.get("rec") or ""),
        country=str(raw.get("cnt") or ""),
        location=str(raw.get("loc") or ""),
        latitude=_parse_float(str(raw.get("lat") or "")),
        longitude=_parse_float(str(raw.get("lon") or "")),
        recording_type=str(raw.get("type") or ""),
        quality=str(raw.get("q") or ""),
        length=str(raw.get("length") or ""),
        date=str(raw.get("date") or ""),
        file_url=file_url,
        sonogram_url=sonogram_url,
        license=str(raw.get("lic") or ""),
    )


@router.get(
    "/audio/{xc_id}",
    summary="Proxy Xeno-canto audio download",
    description=(
        "Streams an audio file from Xeno-canto, proxying the request to avoid CORS issues. "
        "Enforces a 50 MB size limit and a 30-second timeout."
    ),
)
async def proxy_audio(
    project_id: UUID,
    xc_id: str,
    current_user: CurrentUser,
    db: DbSession,
) -> StreamingResponse:
    """Stream a Xeno-canto audio file back to the client.

    Downloads the audio file from ``https://xeno-canto.org/{xc_id}/download``
    and streams it to the client so the full file is never buffered in memory.
    The httpx streaming context manager stays open for the lifetime of the
    response body generator.

    Args:
        project_id: Project UUID (path parameter, used for access control)
        xc_id: Xeno-canto recording ID (e.g. "1069474")
        current_user: Current authenticated user
        db: Database session

    Returns:
        StreamingResponse with the audio content

    Raises:
        403: Access denied to project
        404: Recording not found on Xeno-canto
        413: Audio file exceeds 50 MB limit
        502: Upstream Xeno-canto error
        504: Request to Xeno-canto timed out
    """
    await check_project_access(project_id, current_user.id, db)

    url = f"https://xeno-canto.org/{xc_id}/download"

    async def _stream_audio() -> AsyncIterator[bytes]:
        try:
            async with (
                httpx.AsyncClient(
                    timeout=30.0,
                    follow_redirects=True,
                ) as client,
                client.stream(
                    "GET",
                    url,
                    headers={"User-Agent": "Echoroo/2.0 (https://echoroo.app)"},
                ) as xc_resp,
            ):
                if xc_resp.status_code == 404:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Xeno-canto recording {xc_id} not found",
                    )
                if xc_resp.status_code != 200:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"Xeno-canto returned HTTP {xc_resp.status_code}",
                    )

                # Reject files that exceed the size limit based on Content-Length
                content_length_str = xc_resp.headers.get("content-length")
                if content_length_str is not None:
                    try:
                        content_length = int(content_length_str)
                        if content_length > AUDIO_SIZE_LIMIT_BYTES:
                            raise HTTPException(
                                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                detail="Audio file exceeds 50 MB limit",
                            )
                    except ValueError:
                        pass

                async for chunk in xc_resp.aiter_bytes(chunk_size=8192):
                    yield chunk
        except httpx.TimeoutException as exc:
            logger.warning("Xeno-canto audio proxy timed out for xc_id=%r", xc_id)
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Xeno-canto audio request timed out",
            ) from exc
        except httpx.RequestError as exc:
            logger.warning(
                "Xeno-canto audio proxy network error for xc_id=%r: %s", xc_id, exc
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Xeno-canto is unreachable",
            ) from exc

    logger.info("Proxying Xeno-canto audio: xc_id=%r", xc_id)

    return StreamingResponse(
        _stream_audio(),
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": f'inline; filename="XC{xc_id}.mp3"',
        },
    )


@router.get(
    "/sonogram",
    summary="Proxy a Xeno-canto sonogram image",
    description=(
        "Fetches a Xeno-canto sonogram image and returns it from the same origin, "
        "avoiding Chrome ORB (Opaque Response Blocking) for cross-origin images. "
        "Only URLs under https://xeno-canto.org/ are accepted."
    ),
)
async def proxy_sonogram(
    project_id: UUID,
    url: str = Query(..., description="Full xeno-canto.org sonogram URL to proxy"),
) -> Response:
    """Proxy a Xeno-canto sonogram image to avoid cross-origin ORB blocking.

    No authentication required — sonograms are publicly available data from
    xeno-canto.org.  The project_id path parameter is kept for URL consistency
    but is not validated.

    Args:
        project_id: Project UUID (path parameter, kept for URL structure)
        url: Full xeno-canto.org image URL to proxy

    Returns:
        Response with the image content and a 1-day Cache-Control header

    Raises:
        400: URL is not a xeno-canto.org URL
        502: Upstream Xeno-canto error
        504: Request to Xeno-canto timed out
    """

    if not url.startswith("https://xeno-canto.org/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only https://xeno-canto.org/ URLs are allowed",
        )

    try:
        async with httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=True,
        ) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "Echoroo/2.0 (https://echoroo.app)"},
            )
    except httpx.TimeoutException as exc:
        logger.warning("Xeno-canto sonogram proxy timed out for url=%r", url)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Xeno-canto sonogram request timed out",
        ) from exc
    except httpx.RequestError as exc:
        logger.warning("Xeno-canto sonogram proxy network error for url=%r: %s", url, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Xeno-canto is unreachable",
        ) from exc

    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Xeno-canto returned HTTP {resp.status_code} for sonogram",
        )

    content_type = resp.headers.get("content-type", "image/png")
    logger.debug("Proxying Xeno-canto sonogram: url=%r content_type=%r", url, content_type)

    return Response(
        content=resp.content,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get(
    "/search",
    response_model=XenoCantoSearchResponse,
    summary="Search Xeno-canto recordings",
    description=(
        "Proxy search to the Xeno-canto v3 API. "
        "Hides the API key and returns a cleaned response. "
        "Supports species, country, area, quality, and recording type filters."
    ),
)
async def search_xeno_canto(
    project_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    query: str = Query(..., min_length=1, description="Search query (species name, etc.)"),
    country: str | None = Query(default=None, description="Country filter (e.g. 'japan')"),
    area: str | None = Query(
        default=None,
        description="Continent filter: africa, america, asia, australia, europe",
    ),
    quality_min: str | None = Query(
        default=None,
        description="Exact quality rating filter (A=best, E=worst)",
    ),
    recording_type: str | None = Query(
        default=None,
        description="Recording type filter (e.g. 'song', 'call', 'alarm call')",
    ),
    page: int = Query(default=1, ge=1, description="Result page number (1-indexed)"),
    per_page: int = Query(
        default=25,
        ge=1,
        le=XENO_CANTO_MAX_PER_PAGE,
        description="Results per page (max 100)",
    ),
) -> XenoCantoSearchResponse:
    """Proxy a Xeno-canto recording search to hide the API key.

    Builds the Xeno-canto tag-based query string from the individual filter
    parameters, fetches the results, and transforms them into a cleaner schema
    for the frontend.

    Args:
        project_id: Project UUID (path parameter, used for access control)
        current_user: Current authenticated user
        db: Database session
        query: Base search query string
        country: Optional country filter
        area: Optional continent/area filter
        quality_min: Optional exact quality rating filter ("A"-"E")
        recording_type: Optional recording type filter
        page: Page number for pagination
        per_page: Number of results per page

    Returns:
        XenoCantoSearchResponse with transformed recording data

    Raises:
        403: Access denied to project
        502: Upstream Xeno-canto API error
    """
    await check_project_access(project_id, current_user.id, db)

    xc_query = _build_xc_query(query, country, area, quality_min, recording_type)
    api_key = _get_api_key()

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                XENO_CANTO_BASE_URL,
                params={
                    "query": xc_query,
                    "page": page,
                    "key": api_key,
                },
                headers={"User-Agent": "Echoroo/2.0 (https://echoroo.app)"},
            )
            resp.raise_for_status()
            data: dict[str, object] = resp.json()
    except httpx.TimeoutException as exc:
        logger.warning("Xeno-canto API request timed out for query=%r", xc_query)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Xeno-canto API request timed out",
        ) from exc
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Xeno-canto API returned HTTP %s for query=%r",
            exc.response.status_code,
            xc_query,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Xeno-canto API error: HTTP {exc.response.status_code}",
        ) from exc
    except httpx.RequestError as exc:
        logger.warning("Xeno-canto API network error for query=%r: %s", xc_query, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Xeno-canto API is unreachable",
        ) from exc

    # Parse pagination metadata from the API response
    # data.get() returns object, so we str() first then int() to satisfy mypy
    try:
        total_recordings = int(str(data.get("numRecordings") or 0))
        total_species = int(str(data.get("numSpecies") or 0))
        current_page = int(str(data.get("page") or page))
        total_pages = int(str(data.get("numPages") or 1))
    except (ValueError, TypeError):
        total_recordings = 0
        total_species = 0
        current_page = page
        total_pages = 1

    # Transform raw recording list; silently skip malformed entries
    raw_list = data.get("recordings")
    raw_recordings: list[dict[str, object]] = raw_list if isinstance(raw_list, list) else []
    recordings: list[XenoCantoRecording] = []
    for raw in raw_recordings:
        if not isinstance(raw, dict):
            continue
        parsed = _transform_recording(raw)
        if parsed is not None:
            recordings.append(parsed)

    # Apply per_page slicing client-side (XC paginates by its own page size)
    recordings = recordings[:per_page]

    # Rewrite sonogram URLs to go through our proxy (avoids ORB blocking in Chrome)
    for rec in recordings:
        if rec.sonogram_url:
            proxied = (
                f"/api/v1/projects/{project_id}/xeno-canto/sonogram"
                f"?url={urllib.parse.quote(rec.sonogram_url, safe='')}"
            )
            rec.sonogram_url = proxied

    logger.info(
        "Xeno-canto search: query=%r page=%d total=%d species=%d returned=%d",
        xc_query,
        current_page,
        total_recordings,
        total_species,
        len(recordings),
    )

    return XenoCantoSearchResponse(
        total_recordings=total_recordings,
        total_species=total_species,
        page=current_page,
        total_pages=total_pages,
        recordings=recordings,
    )
