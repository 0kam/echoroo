# ============================================
# Stage 1: Build stage - Install dependencies
# ============================================
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /code

# Install build dependencies (only needed for compilation)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only dependency files first for better layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies (cached if pyproject.toml and uv.lock unchanged)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev --all-extras

# Copy source code and README (required by hatchling for build)
COPY README.md ./
COPY src/ ./src/

# Install the project itself
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-extras

# ============================================
# Stage 2: Runtime stage - Minimal final image
# ============================================
FROM python:3.12-slim-bookworm AS runtime

WORKDIR /code

# Install only runtime dependencies (no build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libexpat1 \
    libsndfile1 \
    gdal-bin \
    libgdal32 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /audio /data

# Copy the virtual environment from builder
COPY --from=builder /code/.venv /code/.venv

# Copy application source
COPY --from=builder /code/src /code/src
COPY --from=builder /code/pyproject.toml /code/

VOLUME ["/data"]

# Environment configuration
ENV ECHOROO_AUDIO_DIR=/audio \
    ECHOROO_HOST="0.0.0.0" \
    ECHOROO_DOMAIN="localhost" \
    ECHOROO_DB_URL="sqlite+aiosqlite:////data/echoroo.db" \
    PATH="/code/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Run the command to start the web server
CMD ["echoroo"]
