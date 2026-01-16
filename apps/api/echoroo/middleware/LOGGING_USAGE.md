# Request Logging Middleware - Usage Guide

## Overview

The `RequestLoggingMiddleware` provides structured request/response logging with correlation IDs for distributed tracing. It automatically logs all HTTP requests with comprehensive details while protecting sensitive information.

## Features

- **Structured JSON logging** for production environments
- **Correlation IDs (Request IDs)** for distributed tracing
- **Automatic log levels** based on HTTP status codes (INFO for 2xx/3xx, WARNING for 4xx, ERROR for 5xx)
- **Security-focused** - automatically redacts sensitive headers and query parameters
- **User tracking** - logs authenticated user IDs
- **Performance monitoring** - tracks request duration in milliseconds
- **Client IP detection** - handles reverse proxy headers (X-Forwarded-For, X-Real-IP)

## Quick Start

### 1. Register the Middleware

Add to `main.py` in the `create_app()` function:

```python
from echoroo.middleware.logging import RequestLoggingMiddleware, configure_logging

def create_app() -> FastAPI:
    app = FastAPI(...)

    # Configure logging (before adding middleware)
    configure_logging(
        log_level="INFO",
        json_format=True  # Use False for development
    )

    # Add request logging middleware
    app.add_middleware(RequestLoggingMiddleware)

    # Other middleware...
    app.add_middleware(CORSMiddleware, ...)

    return app
```

**Important**: Add `RequestLoggingMiddleware` **before** CORS middleware to ensure proper logging order.

### 2. Configure Logging Format

**Production (JSON format for log aggregation)**:
```python
configure_logging(log_level="INFO", json_format=True)
```

Output:
```json
{
  "timestamp": "2026-01-16 08:30:45",
  "level": "INFO",
  "logger": "echoroo.requests",
  "message": "GET /api/v1/projects 200 45.23ms",
  "data": {
    "request_id": "a7b3c4d5-e6f7-8901-2345-6789abcdef01",
    "method": "GET",
    "path": "/api/v1/projects",
    "status_code": 200,
    "duration_ms": 45.23,
    "client_ip": "192.168.1.100",
    "user_id": "123e4567-e89b-12d3-a456-426614174000",
    "user_agent": "Mozilla/5.0..."
  }
}
```

**Development (human-readable format)**:
```python
configure_logging(log_level="DEBUG", json_format=False)
```

Output:
```
2026-01-16 08:30:45 - echoroo.requests - INFO - GET /api/v1/projects 200 45.23ms
```

## Log Fields

| Field | Type | Description | Always Present |
|-------|------|-------------|----------------|
| `request_id` | UUID | Correlation ID for tracing | Yes |
| `method` | string | HTTP method (GET, POST, etc.) | Yes |
| `path` | string | Request path | Yes |
| `status_code` | int | HTTP response status code | Yes |
| `duration_ms` | float | Processing time in milliseconds | Yes |
| `client_ip` | string | Client IP address (handles proxies) | Yes |
| `user_id` | UUID | Authenticated user ID | If authenticated |
| `query_params` | object | Query parameters (sanitized) | If present |
| `user_agent` | string | User agent string | If present |
| `error` | string | Error message | If exception occurred |

## Security Features

### Automatic Redaction

Sensitive data is automatically redacted from logs:

**Sensitive Headers**:
- `Authorization`
- `X-API-Key`
- `Cookie`
- `X-CSRF-Token`

**Sensitive Query Parameters**:
- `password`
- `token`
- `api_key`
- `secret`
- `access_token`
- `refresh_token`

Example:
```
# Request: GET /api/auth/reset?token=secret123&email=user@example.com
# Logged: query_params: {"token": "***REDACTED***", "email": "user@example.com"}
```

### Excluded Paths

Health check and monitoring endpoints are excluded from logging to reduce noise:
- `/health`
- `/metrics`
- `/favicon.ico`

## Log Levels

Automatic log level assignment based on response status:

| Status Code Range | Log Level | Use Case |
|-------------------|-----------|----------|
| 200-399 | INFO | Successful requests |
| 400-499 | WARNING | Client errors (bad requests, auth failures) |
| 500-599 | ERROR | Server errors |

## Correlation IDs (Request Tracing)

Every request gets a unique UUID that can be used for distributed tracing:

1. **Logged in all log entries** for that request
2. **Added to response headers** as `X-Request-ID`
3. **Available in request state** via `request.state.request_id`

### Using Correlation IDs in Your Code

```python
from fastapi import Request

@router.get("/example")
async def example_endpoint(request: Request):
    request_id = request.state.request_id
    logger.info(f"Processing request {request_id}")
    return {"request_id": request_id}
```

### Client-Side Usage

Clients can extract the request ID from response headers:

```javascript
const response = await fetch('/api/v1/projects');
const requestId = response.headers.get('X-Request-ID');
console.log('Request ID:', requestId);
```

## User Tracking

When a user is authenticated, their ID is automatically logged:

```python
# In auth middleware, set user in request state
request.state.user = current_user

# RequestLoggingMiddleware will automatically log user_id
```

## Client IP Detection

The middleware intelligently detects client IPs, handling reverse proxies:

1. Checks `X-Forwarded-For` header (takes first IP in chain)
2. Falls back to `X-Real-IP` header
3. Falls back to direct client address
4. Returns "unknown" if none available

## Performance Monitoring

Request duration is tracked using high-precision `time.perf_counter()`:

```json
{
  "duration_ms": 45.23,  // Rounded to 2 decimal places
  ...
}
```

Use this to identify slow endpoints:

```bash
# Find slow requests (> 100ms)
cat logs.json | jq 'select(.data.duration_ms > 100)'
```

## Environment Configuration

Recommended settings per environment:

### Development
```python
configure_logging(log_level="DEBUG", json_format=False)
```
- Human-readable format
- Verbose logging

### Staging
```python
configure_logging(log_level="INFO", json_format=True)
```
- Structured JSON
- Normal verbosity

### Production
```python
configure_logging(log_level="INFO", json_format=True)
```
- Structured JSON for log aggregation (ELK, CloudWatch, etc.)
- INFO level (reduce noise)

## Integration with Log Aggregation

The JSON format is designed for log aggregation systems:

### CloudWatch Logs
```python
# Logs are automatically structured for CloudWatch Insights queries
fields @timestamp, data.request_id, data.duration_ms
| filter data.status_code >= 500
| sort data.duration_ms desc
```

### ELK Stack
```json
// Logstash pipeline
filter {
  json {
    source => "message"
  }
}
```

### Datadog
```python
# JSON logs are automatically parsed
# Create monitors on data.duration_ms, data.status_code, etc.
```

## Troubleshooting

### Logs not appearing

Check logging configuration is called before adding middleware:
```python
configure_logging(...)  # Must be called first
app.add_middleware(RequestLoggingMiddleware)
```

### User ID not logged

Ensure auth middleware sets `request.state.user`:
```python
request.state.user = current_user
```

### Sensitive data in logs

Add to `SENSITIVE_PARAMS` or `SENSITIVE_HEADERS`:
```python
class RequestLoggingMiddleware(BaseHTTPMiddleware):
    SENSITIVE_PARAMS = {
        "password",
        "your_custom_param",  # Add here
    }
```

## Example Log Output

### Successful Request
```json
{
  "timestamp": "2026-01-16 08:30:45",
  "level": "INFO",
  "logger": "echoroo.requests",
  "message": "GET /api/v1/projects 200 45.23ms",
  "data": {
    "request_id": "a7b3c4d5-e6f7-8901-2345-6789abcdef01",
    "method": "GET",
    "path": "/api/v1/projects",
    "status_code": 200,
    "duration_ms": 45.23,
    "client_ip": "192.168.1.100",
    "user_id": "123e4567-e89b-12d3-a456-426614174000",
    "query_params": {"page": "1", "limit": "10"},
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
  }
}
```

### Authentication Failure
```json
{
  "timestamp": "2026-01-16 08:31:12",
  "level": "WARNING",
  "logger": "echoroo.requests",
  "message": "POST /api/v1/auth/login 401 12.45ms",
  "data": {
    "request_id": "b8c4d5e6-f7g8-9012-3456-789abcdef012",
    "method": "POST",
    "path": "/api/v1/auth/login",
    "status_code": 401,
    "duration_ms": 12.45,
    "client_ip": "192.168.1.100",
    "user_agent": "PostmanRuntime/7.26.8"
  }
}
```

### Server Error
```json
{
  "timestamp": "2026-01-16 08:32:00",
  "level": "ERROR",
  "logger": "echoroo.requests",
  "message": "POST /api/v1/projects 500 156.78ms",
  "data": {
    "request_id": "c9d5e6f7-g8h9-0123-4567-89abcdef0123",
    "method": "POST",
    "path": "/api/v1/projects",
    "status_code": 500,
    "duration_ms": 156.78,
    "client_ip": "192.168.1.100",
    "user_id": "123e4567-e89b-12d3-a456-426614174000",
    "error": "Database connection error",
    "user_agent": "axios/0.21.1"
  }
}
```

## Best Practices

1. **Always use JSON format in production** for log aggregation
2. **Add correlation IDs to error responses** for easier debugging
3. **Monitor request duration** to identify performance issues
4. **Set up alerts on ERROR level logs** for server errors
5. **Use request IDs in error messages** returned to clients
6. **Rotate logs regularly** to manage disk space
7. **Sanitize custom sensitive fields** by extending the middleware

## Further Reading

- [Structured Logging Best Practices](https://www.structlog.org/)
- [OpenTelemetry Tracing](https://opentelemetry.io/)
- [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)
