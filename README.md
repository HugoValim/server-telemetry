# Server Telemetry Dashboard

Real-time server monitoring API with a web dashboard. Exposes system metrics (CPU, memory, disk, network) via a FastAPI backend and visualizes them in the browser.

## Quick Start

```bash
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8000
```

Open [http://localhost:8000](http://localhost:8000) for the dashboard.

## API Overview

| Endpoint | Method | Description | Auth |
|---|---|---|---|
| `/health` | GET | Liveness probe | No |
| `/ready` | GET | Readiness probe | No |
| `/live` | GET | Liveness probe | No |
| `/` | GET | Dashboard UI | No |
| `/api/telemetry` | GET | Full telemetry snapshot | Yes |
| `/api/telemetry/cpu` | GET | CPU metrics | Yes |
| `/api/telemetry/memory` | GET | Memory metrics | Yes |
| `/api/telemetry/disk` | GET | Disk metrics | Yes |
| `/api/telemetry/network` | GET | Network I/O counters | Yes |
| `/api/telemetry/history` | GET | Metric history (cpu/memory/disk) | Yes |
| `/api/processes` | GET | Top processes by CPU or memory | Yes |
| `/api/thresholds` | GET/PUT | Alert threshold configuration | Yes |
| `/ws/telemetry` | WS | Real-time telemetry stream | Yes |

Authentication is via `Authorization: Bearer <api_key>` header (or `?token=<key>` for WebSocket). The API key is generated on first startup and exposed at `GET /api/key`.

## CLI Utility

A small CLI for computing basic statistics on a list of numbers:

```bash
python app.py 1 2 3 4 5
python app.py --mode sum 1 2 3
python app.py --mode max 1 2 3
python app.py --mode min 1 2 3
```

## Running Tests

```bash
pytest test_app.py test_server.py -v
```

## Docker

```bash
docker build -t server-telemetry .
docker run -p 8000:8000 server-telemetry
```
