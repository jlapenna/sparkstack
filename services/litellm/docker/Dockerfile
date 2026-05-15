FROM ghcr.io/astral-sh/uv:latest AS uv

FROM ghcr.io/berriai/litellm:v1.83.14-stable.patch.3

COPY --from=uv /uv /bin/uv

# Install OpenTelemetry packages into the litellm virtualenv
RUN uv pip install --python /app/.venv \
    opentelemetry-api \
    opentelemetry-sdk \
    opentelemetry-exporter-otlp \
    opentelemetry-instrumentation
