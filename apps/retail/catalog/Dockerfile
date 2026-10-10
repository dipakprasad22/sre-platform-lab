# syntax=docker/dockerfile:1

# ============ Stage 1: build (has tools, thrown away later) ============
FROM python:3.13-slim AS builder

# Bring in the uv tool from its official image
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Install dependencies first. This layer is reused until pyproject.toml or uv.lock change.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# Copy the app code last, because it changes most often.
COPY app ./app

# ============ Stage 2: runtime (only what is needed to run) ============
FROM python:3.13-slim

# Create a normal user with a fixed ID, so the app never runs as root.
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home app

WORKDIR /app
COPY --from=builder --chown=app:app /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER 10001
EXPOSE 8000

# Exec form (a JSON list), so uvicorn receives the stop signal directly.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]