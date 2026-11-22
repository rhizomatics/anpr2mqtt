# Base for the build and runtime stages, normally the pinned python-base stage below. The weekly
# rebuild in image-scan.yml overrides it with a newer digest of the same tag, once that digest has
# been out for its cooldown, to pick up fixes without waiting for a release.
ARG BASE_IMAGE=python-base

# Pinned base image, kept here in one place and updated by Dependabot, which moves the digest as well
# as the tag, after its own cooldown, so a release build is reproducible.
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS python-base

# Build stage: resolve and install the app plus its dependencies into a venv
FROM ${BASE_IMAGE} AS builder

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
FROM ${BASE_IMAGE}

# Keep this list minimal: every package here is CVE surface that only a rebuild can patch.
# tesseract-ocr is the OCR binary; tesseract-ocr-eng is only its language data, which merely
# recommends the binary, so with --no-install-recommends both must be named.
RUN apt-get -y update && \
    apt-get -y upgrade && \
    apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng && \
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
