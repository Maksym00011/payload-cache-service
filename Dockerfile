# syntax=docker/dockerfile:1

# Build stage: install dependencies from the committed lock file, so the image
# gets exactly the versions that were tested.
FROM python:3.12-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    # Use the interpreter already in the image. Left to itself uv downloads its
    # own Python, and the venv would then point at a path the runtime stage
    # does not have.
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=python3.12

RUN pip install --no-cache-dir uv==0.12.23

WORKDIR /app

# Dependencies first: editing application code must not re-resolve them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY cli ./cli
RUN uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATABASE_URL="sqlite+aiosqlite:////data/cache.db"

# A process that only serves HTTP has no reason to own its own code, so it runs
# as a non-root user and writes only to the mounted data directory.
RUN useradd --create-home --uid 1000 service \
    && mkdir -p /data \
    && chown service:service /data

WORKDIR /app
COPY --from=builder --chown=service:service /app /app

USER service
VOLUME ["/data"]
EXPOSE 8000

# The probe hits /health, which touches the database, so an unhealthy
# container really means the service cannot serve.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health').read()"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
