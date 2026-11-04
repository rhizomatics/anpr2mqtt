# Build stage: resolve and install the app plus its dependencies into a venv
FROM python:3.14-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Use the base image's Python, so the venv works unchanged in the runtime stage
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

ADD uv.lock /app/uv.lock
ADD pyproject.toml /app/pyproject.toml
RUN uv sync --locked --no-dev --no-install-project --no-cache

ADD src /app/src
ADD README.md /app/README.md
RUN uv sync --locked --no-dev --no-editable --no-cache

# Runtime stage: only the venv and runtime system packages, no uv or build tools
FROM python:3.14-slim

RUN apt-get -y update && \
    apt-get -y upgrade && \
    apt-get install -y --no-install-recommends tesseract-ocr-eng mosquitto-clients jq && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
ADD --chmod=755 scripts/healthcheck.sh /app/healthcheck.sh
RUN mkdir /app/.cache && chmod a+rw /app/.cache

# Expose `anpr2mqtt` and `anprtools` as regular commands on PATH, so a shell
# started in the container can call them directly, with no venv to activate.
ENV PATH="/app/.venv/bin:$PATH"

# Exec form, calling the installed command directly (not via `uv run`/a shell),
# so the app's own process is PID 1 and gets proper signal handling.
ENTRYPOINT ["anpr2mqtt"]
