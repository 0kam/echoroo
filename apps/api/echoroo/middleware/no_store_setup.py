"""No-store cache headers for setup endpoints."""

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

_SETUP_PATH = "/api/v1/setup"
_SETUP_PREFIX = f"{_SETUP_PATH}/"
_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


class NoStoreSetupMiddleware(BaseHTTPMiddleware):
    """Apply strict no-store headers to every setup API response."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        if request.url.path == _SETUP_PATH or request.url.path.startswith(_SETUP_PREFIX):
            for header_name, header_value in _CACHE_HEADERS.items():
                response.headers[header_name] = header_value
        return response
