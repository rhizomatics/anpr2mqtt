FROM python:3.13-slim

ENV MQTT_HOST 127.0.0.1
ENV MQTT_PORT 1883
ENV MQTT_TOPIC anpr/driveway

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

ADD src /app
ADD README.md /app/README.md

RUN uv sync --locked

ENV PATH="/app/.venv/bin:$PATH"
# Use explicit path and python executable rather than `uv run` to get proper signal handling
ENTRYPOINT ["python", "-m", "anpr2mqtt"]
