FROM python:3.14-slim

ENV MQTT__HOST 127.0.0.1
ENV MQTT__PORT 1883
ENV MQTT__TOPIC_ROOT anpr2mqtt

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1

# Install system dependencies and uv
RUN apt-get -y update && \
    apt-get -y upgrade && \
    apt-get install -y tesseract-ocr-eng curl libyaml-dev mosquitto-clients

# Copy project files
WORKDIR /app

ADD uv.lock /app/uv.lock
ADD pyproject.toml /app/pyproject.toml
RUN uv sync --locked --no-install-project

ADD src /app/src
ADD scripts/healthcheck.sh /app
RUN chmod ug+x /app/healthcheck.sh
ADD README.md /app/README.md
RUN mkdir /app/.cache && chmod a+rw /app/.cache

# Install anpr2mqtt itself as a uv tool, exposing `anpr2mqtt` and `tools` as
# regular commands on PATH (/usr/local/bin) so a shell started in the container
# can call them directly, with no venv to activate.
ENV UV_TOOL_BIN_DIR=/usr/local/bin
RUN uv tool install --no-cache . && rm -rf /app/.venv

# Exec form, calling the installed command directly (not via `uv run`/a shell),
# so the app's own process is PID 1 and gets proper signal handling.
ENTRYPOINT ["anpr2mqtt"]
