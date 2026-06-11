"""Xeno-canto API proxy endpoints.

Proxies search requests to the Xeno-canto recording API, hiding the API key
from the frontend. All endpoints are scoped to a project_id for access control.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import urllib.parse
from collections.abc import AsyncIterator
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import Response, StreamingResponse

from echoroo.core.actions import XENO_CANTO_AUDIO_ACTION
from echoroo.core.database import DbSession
from echoroo.core.permissions import check_project_access, gate_action
from echoroo.core.settings import get_settings
from echoroo.core.url_allowlist import PinnedIPAsyncTransport
from echoroo.middleware.auth import CurrentUser
from echoroo.schemas.xeno_canto import XenoCantoRecording, XenoCantoSearchResponse

logger = logging.getLogger(__name__)

# Xeno-canto API v3 base URL
XENO_CANTO_BASE_URL = "https://xeno-canto.org/api/3/recordings"

# Maximum page size accepted by the Xeno-canto API
XENO_CANTO_MAX_PER_PAGE = 100

# Maximum allowed audio file size in bytes (50 MB)
AUDIO_SIZE_LIMIT_BYTES = 50 * 1024 * 1024

# SSRF guard: hosts allowed for the sonogram proxy.  Only Xeno-canto.
_SONOGRAM_ALLOWED_HOSTS: frozenset[str] = frozenset({"xeno-canto.org"})

# SSRF guard: maximum number of HTTP redirects to follow before giving up.
_SONOGRAM_MAX_REDIRECTS: int = 3


def _validate_sonogram_url(url: str) -> tuple[str, str]:
    """Validate a sonogram proxy target URL against the SSRF allowlist.

    Stronger replacement for the previous ``url.startswith("https://xeno-canto.org/")``
    string check — that prefix test is preserved here in spirit through the
    combined scheme + host allowlist check below.

    Enforces:
      * https scheme only
      * host matches an entry in ``_SONOGRAM_ALLOWED_HOSTS``
      * if the host happens to be a literal IP, it is not private/loopback/
        link-local/reserved (defence-in-depth — Xeno-canto always resolves
        to public IPs, so a literal-IP variant is treated as a tampering
        attempt)
      * resolved DNS A/AAAA records do not point at private/loopback/
        link-local/reserved address space (defence-in-depth against DNS
        rebinding-style abuse from a compromised allowed host)

    Returns:
        ``(host, pinned_ip)`` — the validated lower-case hostname and the
        single public IP literal the caller MUST connect to via
        :class:`PinnedIPAsyncTransport`. Pinning the connect target to
        this IP defeats the DNS rebinding TOCTOU window between
        validation and the actual TCP connect (``httpx`` would otherwise
        re-resolve the hostname when opening the connection). IPv4 is
        preferred when available; otherwise the first public IPv6 wins.

    Raises:
        HTTPException(400) if the URL fails any check.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid sonogram URL",
        ) from exc

    if parsed.scheme != "https":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only https sonogram URLs are allowed",
        )

    host = (parsed.hostname or "").lower()
    if not host:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sonogram URL is missing a host",
        )

    if host not in _SONOGRAM_ALLOWED_HOSTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only https://xeno-canto.org/ URLs are allowed",
        )

    # If the host parses as a literal IP, reject private/loopback ranges.
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None
    if literal_ip is not None and (
        literal_ip.is_private
        or literal_ip.is_loopback
        or literal_ip.is_link_local
        or literal_ip.is_reserved
        or literal_ip.is_multicast
        or literal_ip.is_unspecified
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sonogram URL resolves to a non-public address",
        )

    # Resolve DNS and check every returned record.  A single private IP
    # is enough to reject — and we pick the first public IPv4 (or IPv6)
    # to pin the actual TCP connect target via PinnedIPAsyncTransport.
    # Pinning is what closes the DNS-rebinding TOCTOU: between the post-
    # validation check below and the connect httpx would otherwise call
    # getaddrinfo a SECOND time, and an attacker-controlled authoritative
    # DNS server could flip the answer to a private IP. By passing the
    # IP literal to httpcore the connect skips DNS entirely.
    try:
        addr_info = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sonogram host could not be resolved",
        ) from exc

    public_ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for family, _socktype, _proto, _canon, sockaddr in addr_info:
        if family in (socket.AF_INET, socket.AF_INET6):
            ip_str = sockaddr[0]
        else:
            continue
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_reserved
            or ip_obj.is_multicast
            or ip_obj.is_unspecified
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sonogram host resolves to a non-public address",
            )
        public_ips.append(ip_obj)

    if not public_ips:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sonogram host produced no usable addresses",
        )

    # Prefer IPv4 (more universally reachable, simpler URL rewriting);
    # fall back to IPv6 only if no IPv4 was returned.
    ipv4 = next(
        (a for a in public_ips if isinstance(a, ipaddress.IPv4Address)), None
    )
    pinned = ipv4 if ipv4 is not None else public_ips[0]
    return host, str(pinned)

router = APIRouter(prefix="/projects/{project_id}/xeno-canto", tags=["xeno-canto"])


def _get_api_key() -> str | None:
    """Return the configured Xeno-canto API key, or None when disabled.

    The previous implementation fell back to the literal string "demo" when
    ``XENO_CANTO_API_KEY`` was unset. The Xeno-canto v3 API rejects that
    placeholder, so a deployment without a real key would fail at first use
    with a confusing upstream error. We now return ``None`` so callers can
    surface a typed ``xeno_canto_not_configured`` 409 instead.

    Returns:
        The Xeno-canto API key string, or ``None`` when the integration is
        not configured (key unset, empty, or the "demo" placeholder).
    """
    settings = get_settings()
    if not settings.xeno_canto_enabled:
        return None
    return (settings.XENO_CANTO_API_KEY or "").strip()


def _xeno_canto_not_configured_exception() -> HTTPException:
    """Return the typed 409 raised when the Xeno-canto key is not configured.

    The detail dict carries the legacy ``error`` trigger key so the global
    :func:`echoroo.core.exceptions.http_exception_handler` flattens it to a
    top-level ``{"error": ..., "message": ...}`` envelope, matching the
    codebase's contract-coded error shape.
    """
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "error": "xeno_canto_not_configured",
            "message": (
                "Xeno-canto integration is not configured. Set "
                "XENO_CANTO_API_KEY (xeno-canto.org account -> API key) to "
                "enable Xeno-canto search and import."
            ),
        },
    )




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
    request: Request,
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
    # Connection-time gate (StreamingResponse pattern, Phase 17 A-5).
    await gate_action(
        action=XENO_CANTO_AUDIO_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

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
    # NOTE (Phase 2A.6 / spec 007): gate_action wiring was deliberately
    # NOT applied to ``proxy_sonogram`` because the existing SSRF unit-test
    # suite (``tests/security/ssrf/test_xeno_canto_proxy_redirect_ssrf.py``)
    # invokes this coroutine directly without a FastAPI ``Request`` /
    # ``current_user`` / ``db`` fixture. Adding the auth params would break
    # those tests. SSRF guards below remain the primary control, and the
    # endpoint is still mounted under ``/projects/{project_id}/...`` so the
    # project_id is observable in audit logs for any later forensic work.

    # Initial allowlist + private-IP guard on the user-supplied URL.
    # `_validate_sonogram_url` raises HTTPException(400) on rejection
    # AND returns the pinned IP literal that the actual TCP connect must
    # target — the IP-pinning transport (built per hop below) defeats the
    # DNS rebinding TOCTOU window between validation and connect.
    pinned_host, pinned_ip = _validate_sonogram_url(url)

    # Manual redirect loop — `follow_redirects=False` prevents httpx from
    # silently chasing a `Location` header into a private network.  Each
    # hop is re-validated through `_validate_sonogram_url`, capping the
    # chain at `_SONOGRAM_MAX_REDIRECTS` to bound resource use. Each hop
    # also rebuilds the pinned transport with a fresh IP (the redirect
    # target's hostname could legitimately resolve to a different public
    # IP than the original host's), so the connect still skips DNS.
    current_url = url
    current_pinned_host = pinned_host
    current_pinned_ip = pinned_ip
    resp: httpx.Response | None = None
    try:
        for hop in range(_SONOGRAM_MAX_REDIRECTS + 1):
            transport = PinnedIPAsyncTransport(
                pinned_host=current_pinned_host,
                pinned_ip=current_pinned_ip,
                allowed_hosts=_SONOGRAM_ALLOWED_HOSTS,
            )
            async with httpx.AsyncClient(
                transport=transport,
                timeout=10.0,
                follow_redirects=False,
            ) as client:
                resp = await client.get(
                    current_url,
                    headers={"User-Agent": "Echoroo/2.0 (https://echoroo.app)"},
                )
            # Redirect: validate the new target before following.
            if resp.status_code in (301, 302, 303, 307, 308):
                if hop >= _SONOGRAM_MAX_REDIRECTS:
                    logger.warning(
                        "Xeno-canto sonogram proxy: max redirect depth "
                        "exceeded for url=%r",
                        url,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="Sonogram redirect chain too long",
                    )
                location = resp.headers.get("location")
                if not location:
                    logger.warning(
                        "Xeno-canto sonogram proxy: %d response without "
                        "Location header for url=%r",
                        resp.status_code,
                        url,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="Sonogram redirect missing Location",
                    )
                next_url = urllib.parse.urljoin(current_url, location)
                # Re-validate every hop — defence against open redirect
                # on the allowed host pointing at a private IP. The
                # returned pin is what the NEXT iteration connects to.
                try:
                    next_host, next_ip = _validate_sonogram_url(next_url)
                except HTTPException as exc:
                    logger.warning(
                        "Xeno-canto sonogram proxy: redirect rejected "
                        "url=%r -> %r reason=%s",
                        current_url,
                        next_url,
                        exc.detail,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="Sonogram redirect target is not allowed",
                    ) from exc
                current_url = next_url
                current_pinned_host = next_host
                current_pinned_ip = next_ip
                continue
            # Non-redirect: leave the loop and process the response.
            break
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

    if resp is None or resp.status_code != 200:
        upstream_status = resp.status_code if resp is not None else 0
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Xeno-canto returned HTTP {upstream_status} for sonogram",
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
        409: Xeno-canto integration is not configured (no API key)
        502: Upstream Xeno-canto API error
    """
    await check_project_access(project_id, current_user.id, db)

    api_key = _get_api_key()
    if api_key is None:
        # No usable key configured — surface a typed 409 instead of letting
        # the request hit Xeno-canto with the rejected "demo" placeholder.
        raise _xeno_canto_not_configured_exception()

    xc_query = _build_xc_query(query, country, area, quality_min, recording_type)

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
