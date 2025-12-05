FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /code

# Install system dependencies, including libexpat1 and clean up the cache
RUN apt-get update && apt-get install -y --no-install-recommends \
    libexpat1 \
    libsndfile1 \
    gdal-bin \
    libgdal-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --dev --all-extras

ADD . /code

RUN mkdir /audio
RUN mkdir /data

VOLUME ["/data"]

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

ENV ECHOROO_AUDIO_DIR /audio
ENV ECHOROO_HOST="0.0.0.0"
ENV ECHOROO_DOMAIN="localhost"
ENV ECHOROO_DB_URL="sqlite+aiosqlite:////data/echoroo.db"
ENV PATH="/code/.venv/bin:$PATH"

# Run the command to start the web server
CMD ["echoroo"]
