# === STEP 1 === Build User Guide

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS guide_builder

RUN mkdir /guide

WORKDIR /guide

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=back/uv.lock,target=uv.lock \
    --mount=type=bind,source=back/pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --dev --all-extras

COPY back/docs /guide/docs
COPY back/mkdocs-guide.yml /guide/mkdocs-guide.yml

RUN uv run mkdocs build -f mkdocs-guide.yml -d /guide/out/

# === STEP 2 === Build Front End

FROM node:latest AS frontend_builder

RUN mkdir /statics

WORKDIR /front

COPY front/ /front

RUN npm install

RUN npm run build

# === STEP 3 === Build echoroo

# Run the web server
# Use a Python image with uv pre-installed
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

# Install the project into `/app`
WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

# Install the project's dependencies using the lockfile and settings
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=back/uv.lock,target=uv.lock \
    --mount=type=bind,source=back/pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev --all-extras

# Then, add the rest of the project source code and install it
# Installing separately from its dependencies allows optimal layer caching
ADD back /app

# Copy the guide
COPY --from=guide_builder /guide/out/ /app/src/echoroo/user_guide/

# Copy the statics
COPY --from=frontend_builder /front/out/ /app/src/echoroo/statics/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-extras

# === STEP 4 === Final Image

# Then, use a final image without uv
FROM python:3.12-slim-bookworm

# Install system dependencies, including libexpat1 and clean up the cache
RUN apt-get update && apt-get install -y --no-install-recommends \
    libexpat1 \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Copy the application from the builder
COPY --from=builder --chown=app:app /app /app

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Create a directory for audio files
RUN mkdir /audio
RUN mkdir /data

VOLUME ["/data"]

# Set the environment variables for the audio directory and the database URL
ENV ECHOROO_AUDIO_DIR /audio
ENV ECHOROO_DB_URL "sqlite+aiosqlite:////data/echoroo.db"
ENV ECHOROO_DEV "false"
ENV ECHOROO_HOST "0.0.0.0"
ENV ECHOROO_PORT "5000"
ENV ECHOROO_LOG_LEVEL "info"
ENV ECHOROO_LOG_TO_STDOUT "true"
ENV ECHOROO_LOG_TO_FILE "false"
ENV ECHOROO_OPEN_ON_STARTUP "false"
ENV ECHOROO_DOMAIN "localhost"

# Expose the port for the web server
EXPOSE 5000

# Reset the entrypoint, don't invoke `uv`
ENTRYPOINT []

# Run the command to start the web server
CMD ["echoroo"]
