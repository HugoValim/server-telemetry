FROM python:3.11-slim

LABEL org.opencontainers.image.title="Server Telemetry Dashboard"
LABEL org.opencontainers.image.description="Real-time server monitoring API with web dashboard"
LABEL org.opencontainers.image.source="https://github.com/your-org/server-telemetry"

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run with both keys:
#   docker run -e API_KEY=$(openssl rand -hex 16) -e API_KEY_READONLY=$(openssl rand -hex 16) -p 8000:8000 server-telemetry
# Use the read-only key in dashboards; keep the full key for admin threshold changes
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
