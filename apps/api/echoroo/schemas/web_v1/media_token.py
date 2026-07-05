"""Scoped media-token request / response schemas (spec/009 PR D0, W2-4 PR-C).

Request / response bodies for the ``/web-api/v1/projects`` media-token
endpoints. Extracted from :mod:`echoroo.api.web_v1.projects._media` so
the router keeps only its BFF adapter handlers. Also consumed by the
project search router for the search-result media-token endpoint.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from echoroo.core.auth import MediaTokenScope


class MediaTokenRequest(BaseModel):
    """Request body for issuing a scoped recording media token."""

    scope: MediaTokenScope


class MediaTokenResponse(BaseModel):
    """Scoped media token response for native browser media/image elements."""

    token: str
    expires_in: int


class ClipMediaTokenRequest(BaseModel):
    """Request body for issuing a scoped clip media token.

    Clip playback / spectrogram ride recording-level tokens (they reuse the
    recording streaming BFF with clip start/end bounds), so the only clip-bound
    scope is ``"download"``.
    """

    scope: Literal["download"] = "download"


__all__ = [
    "ClipMediaTokenRequest",
    "MediaTokenRequest",
    "MediaTokenResponse",
]
