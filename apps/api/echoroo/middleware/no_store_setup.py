"""No-store cache headers for setup endpoints."""

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

# Both the legacy ``/api/v1/setup`` mount and its W2-2-A BFF mirror
# ``/web-api/v1/setup`` must carry no-store headers (the latter so the
# ``GET /setup/status`` probe is never cached either — the legacy handler
# only sets the headers inline on ``POST /initialize``).
_SETUP_PATHS = ("/api/v1/setup", "/web-api/v1/setup")
_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _is_setup_path(path: str) -> bool:
    return any(
        path == base or path.startswith(f"{base}/") for base in _SETUP_PATHS
    )


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
        if _is_setup_path(request.url.path):
            for header_name, header_value in _CACHE_HEADERS.items():
                response.headers[header_name] = header_value
        return response
