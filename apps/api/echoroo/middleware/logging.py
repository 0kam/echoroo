"""Request logging middleware with structured logging and correlation IDs."""

import json
import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("echoroo.requests")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for structured request/response logging.

    Logs all HTTP requests with:
    - Request method, path, and query parameters
    - Response status code and duration
    - Client IP address
    - User ID (if authenticated)
    - Correlation ID for distributed tracing
    - Structured JSON format for production environments

    Example:
        ```python
        app.add_middleware(RequestLoggingMiddleware)
        ```
    """

    # Paths to exclude from logging (health checks, metrics, etc.)
    EXCLUDED_PATHS = {"/health", "/metrics", "/favicon.ico"}

    # Sensitive headers to redact
    SENSITIVE_HEADERS = {
        "authorization",
        "x-api-key",
        "cookie",
        "x-csrf-token",
    }

    # Sensitive query parameters to redact
    SENSITIVE_PARAMS = {
        "password",
        "token",
        "api_key",
        "secret",
        "access_token",
        "refresh_token",
    }

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Any]
    ) -> Any:
        """Process request and log details.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler in chain

        Returns:
            HTTP response
        """
        # Skip logging for excluded paths
        if request.url.path in self.EXCLUDED_PATHS:
            return await call_next(request)

        # Generate correlation ID for request tracing
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        # Get client IP (handle reverse proxy headers)
        client_ip = self._get_client_ip(request)

        # Record request start time
        start_time = time.perf_counter()

        # Process request
        try:
            response = await call_next(request)
        except Exception as exc:
            # Log unhandled exceptions
            duration_ms = (time.perf_counter() - start_time) * 1000
            self._log_request(
                request=request,
                status_code=500,
                duration_ms=duration_ms,
                client_ip=client_ip,
                request_id=request_id,
                error=str(exc),
            )
            raise

        # Calculate request duration
        duration_ms = (time.perf_counter() - start_time) * 1000

        # Log request
        self._log_request(
            request=request,
            status_code=response.status_code,
            duration_ms=duration_ms,
            client_ip=client_ip,
            request_id=request_id,
        )

        # Add correlation ID to response headers
        response.headers["X-Request-ID"] = request_id

        return response

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP address from request.

        Handles reverse proxy headers (X-Forwarded-For, X-Real-IP).

        Args:
            request: HTTP request

        Returns:
            Client IP address
        """
        # Check X-Forwarded-For header (proxy/load balancer)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Get first IP in chain (original client)
            return forwarded_for.split(",")[0].strip()

        # Check X-Real-IP header
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Fallback to direct client address
        if request.client:
            return request.client.host

        return "unknown"

    def _get_user_id(self, request: Request) -> str | None:
        """Extract user ID from request state (if authenticated).

        Args:
            request: HTTP request

        Returns:
            User ID or None
        """
        # User is set in request.state by auth middleware
        user = getattr(request.state, "user", None)
        if user:
            return str(user.id)
        return None

    def _sanitize_query_params(self, request: Request) -> dict[str, str]:
        """Sanitize query parameters by redacting sensitive values.

        Args:
            request: HTTP request

        Returns:
            Sanitized query parameters
        """
        params = dict(request.query_params)
        for key in params:
            if key.lower() in self.SENSITIVE_PARAMS:
                params[key] = "***REDACTED***"
        return params

    def _sanitize_headers(self, headers: Headers) -> dict[str, str]:
        """Sanitize headers by redacting sensitive values.

        Args:
            headers: Request headers

        Returns:
            Sanitized headers
        """
        sanitized = {}
        for key, value in headers.items():
            if key.lower() in self.SENSITIVE_HEADERS:
                sanitized[key] = "***REDACTED***"
            else:
                sanitized[key] = value
        return sanitized

    def _get_log_level(self, status_code: int) -> int:
        """Determine appropriate log level based on status code.

        Args:
            status_code: HTTP status code

        Returns:
            Log level (INFO, WARNING, or ERROR)
        """
        if status_code >= 500:
            return logging.ERROR
        if status_code >= 400:
            return logging.WARNING
        return logging.INFO

    def _log_request(
        self,
        request: Request,
        status_code: int,
        duration_ms: float,
        client_ip: str,
        request_id: str,
        error: str | None = None,
    ) -> None:
        """Log request with structured format.

        Args:
            request: HTTP request
            status_code: Response status code
            duration_ms: Request processing duration in milliseconds
            client_ip: Client IP address
            request_id: Request correlation ID
            error: Error message (if any)
        """
        # Build structured log entry
        log_data = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": status_code,
            "duration_ms": round(duration_ms, 2),
            "client_ip": client_ip,
        }

        # Add query parameters if present
        if request.query_params:
            log_data["query_params"] = self._sanitize_query_params(request)

        # Add user ID if authenticated
        user_id = self._get_user_id(request)
        if user_id:
            log_data["user_id"] = user_id

        # Add error if present
        if error:
            log_data["error"] = error

        # Add user agent
        user_agent = request.headers.get("User-Agent")
        if user_agent:
            log_data["user_agent"] = user_agent

        # Determine log level based on status code
        log_level = self._get_log_level(status_code)

        # Format log message
        message = f"{request.method} {request.url.path} {status_code} {duration_ms:.2f}ms"

        # Log as JSON for structured logging
        logger.log(log_level, message, extra={"data": json.dumps(log_data)})


def configure_logging(
    log_level: str = "INFO",
    json_format: bool = True,
) -> None:
    """Configure application logging with structured format.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_format: Whether to use JSON format (recommended for production)

    Example:
        ```python
        # Development (human-readable)
        configure_logging(log_level="DEBUG", json_format=False)

        # Production (structured JSON)
        configure_logging(log_level="INFO", json_format=True)
        ```
    """
    # Create custom formatter
    if json_format:
        # JSON formatter for production/structured logging
        class JsonFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                log_obj = {
                    "timestamp": self.formatTime(record, self.datefmt),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                }

                # Add structured data if present
                data = getattr(record, "data", None)
                if data is not None:
                    log_obj["data"] = json.loads(data)

                # Add exception info if present
                if record.exc_info:
                    log_obj["exception"] = self.formatException(record.exc_info)

                return json.dumps(log_obj)

        formatter: logging.Formatter = JsonFormatter()
    else:
        # Human-readable formatter for development
        formatter = logging.Formatter(
            fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    # Configure root logger
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    # Configure echoroo loggers
    for logger_name in ["echoroo", "echoroo.requests"]:
        logger_instance = logging.getLogger(logger_name)
        logger_instance.setLevel(getattr(logging, log_level.upper()))
        logger_instance.handlers.clear()
        logger_instance.addHandler(handler)
        logger_instance.propagate = False
