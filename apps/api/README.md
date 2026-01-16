# Echoroo API

Backend API for Echoroo - Bird sound recognition and analysis platform.

## Technology Stack

- **Framework**: FastAPI
- **Database**: PostgreSQL with pgvector extension
- **ORM**: SQLAlchemy 2.0
- **Task Queue**: Celery + Redis
- **Authentication**: JWT with Argon2 password hashing
- **Validation**: Pydantic v2

## Project Structure

```
apps/api/
├── echoroo/              # Main application package
│   ├── models/           # SQLAlchemy database models
│   ├── schemas/          # Pydantic schemas for validation
│   ├── services/         # Business logic services
│   ├── repositories/     # Data access layer
│   ├── api/              # API route handlers
│   │   └── v1/           # API version 1 endpoints
│   ├── core/             # Core configuration and utilities
│   └── middleware/       # Custom middleware components
├── tests/                # Test suite
│   ├── contract/         # Contract tests (OpenAPI compliance)
│   ├── integration/      # Integration tests
│   └── unit/             # Unit tests
├── alembic/              # Database migrations
│   └── versions/         # Migration scripts
├── pyproject.toml        # Project dependencies and configuration
└── README.md             # This file
```

## Development Setup

### Prerequisites

- Python 3.11+
- PostgreSQL 15+ with pgvector extension
- Redis 7+

### Installation

```bash
# Install dependencies using uv (recommended)
uv sync

# Or using pip
pip install -e ".[dev]"
```

### Running the Development Server

```bash
# Using uv
uv run uvicorn echoroo.main:app --reload

# Or using uvicorn directly
uvicorn echoroo.main:app --reload --host 0.0.0.0 --port 8000
```

### Database Migrations

```bash
# Create a new migration
uv run alembic revision --autogenerate -m "Description of changes"

# Apply migrations
uv run alembic upgrade head

# Rollback migration
uv run alembic downgrade -1
```

## Testing

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=echoroo --cov-report=html

# Run specific test type
uv run pytest tests/unit/
uv run pytest tests/integration/
uv run pytest tests/contract/
```

## Code Quality

```bash
# Lint with ruff
uv run ruff check .

# Format with ruff
uv run ruff format .

# Type check with mypy
uv run mypy .
```

## API Documentation

Once the server is running, access the interactive API documentation at:

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- OpenAPI JSON: http://localhost:8000/openapi.json

## Architecture

This API follows a layered architecture:

1. **API Layer** (`api/`): HTTP request handling and route definitions
2. **Service Layer** (`services/`): Business logic and orchestration
3. **Repository Layer** (`repositories/`): Data access and persistence
4. **Model Layer** (`models/`): Database models and relationships
5. **Schema Layer** (`schemas/`): Request/response validation

## Key Features

- **Authentication**: JWT-based authentication with refresh tokens
- **Rate Limiting**: Redis-backed rate limiting for API endpoints
- **Email Notifications**: Using Resend for transactional emails
- **CAPTCHA Verification**: Server-side CAPTCHA validation
- **Async Support**: Fully async/await for high performance
- **Type Safety**: Strict type checking with mypy and Pydantic
- **Test Coverage**: >80% test coverage requirement

## Environment Variables

See `.env.example` in the project root for required environment variables.

## License

See LICENSE file in the project root.
