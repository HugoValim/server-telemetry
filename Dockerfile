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

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
