# Base images are pinned by digest so a release build is reproducible, and Dependabot raises a PR
# whenever the image behind the tag is republished. Keep both python stages on the same digest.
# A manual or scheduled rebuild of a release (docker-publish.yml) strips the digests to pick up the
# current image for the tag, since the pin in an old release tag would otherwise never move.

# Build stage: resolve and install the app plus its dependencies into a venv
FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 /uv /bin/uv

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
FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f

# Keep this list minimal: every package here is CVE surface that only a rebuild can patch
RUN apt-get -y update && \
    apt-get -y upgrade && \
    apt-get install -y --no-install-recommends tesseract-ocr-eng && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
RUN mkdir /app/.cache && chmod a+rw /app/.cache

# Expose `anpr2mqtt` and `anprtools` as regular commands on PATH, so a shell
# started in the container can call them directly, with no venv to activate.
ENV PATH="/app/.venv/bin:$PATH"

# The main loop touches a heartbeat file while it runs and is connected to MQTT; no broker access needed
HEALTHCHECK --interval=60s --timeout=10s --start-period=60s --retries=3 CMD ["anprtools", "healthcheck"]

# Exec form, calling the installed command directly (not via `uv run`/a shell),
# so the app's own process is PID 1 and gets proper signal handling.
ENTRYPOINT ["anpr2mqtt"]
