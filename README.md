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

## Authentication

The API supports two authentication methods:

### API Key (for scripts/curl)
```bash
# Full access
curl -H "Authorization: Bearer $API_KEY" http://localhost:8000/api/telemetry

# Read-only access
curl -H "Authorization: Bearer $API_KEY_READONLY" http://localhost:8000/api/telemetry
```

API keys are generated on first startup and printed to stdout. Set `API_KEY` and `API_KEY_READONLY` environment variables to persist them across restarts.

### Google OAuth (for the dashboard)
The dashboard uses OAuth2 session-based auth. When `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are set, users are redirected to Google's consent screen instead of needing an API key.

## Google OAuth Setup

### 1. Create a Google Cloud project
Go to [console.cloud.google.com](https://console.cloud.google.com) and create a new project (or select an existing one).

### 2. Configure the OAuth consent screen
1. Navigate to **APIs & Services > OAuth consent screen**
2. Choose **External** and click **Create**
3. Fill in the required fields (app name, user support email, developer contact)
4. For **Scopes**, add: `openid`, `email`, `profile`
5. Add your test users under **Test users** (required unless app is verified)

### 3. Create OAuth 2.0 credentials
1. Navigate to **APIs & Services > Credentials**
2. Click **Create Credentials > OAuth client ID**
3. Application type: **Web application**
4. Add an **Authorized redirect URI**:
   ```
   http://localhost:8000/auth/callback
   ```
   (add production URL when deploying)
5. Copy the **Client ID** and **Client Secret**

### 4. Configure the server
```bash
export GOOGLE_CLIENT_ID="your-client-id.apps.googleusercontent.com"
export GOOGLE_CLIENT_SECRET="your-client-secret"
export ALLOWED_EMAILS="alice@example.com,bob@example.com,example.com"
```
- `ALLOWED_EMAILS`: Comma-separated list of allowed email addresses or domains (e.g. `corp.com` allows anyone with `@corp.com` email)

### 5. (Docker)
```bash
docker run -p 8000:8000 \
  -e GOOGLE_CLIENT_ID="your-client-id.apps.googleusercontent.com" \
  -e GOOGLE_CLIENT_SECRET="your-client-secret" \
  -e ALLOWED_EMAILS="example.com" \
  server-telemetry
```

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `API_KEY` | Full-access API key | Auto-generated |
| `API_KEY_READONLY` | Read-only API key | Auto-generated |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID | (not set) |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret | (not set) |
| `ALLOWED_EMAILS` | Allowed emails/domains for OAuth | (all allowed) |
| `SECRET_KEY` | Session signing key | `API_KEY` or `dev-secret-change-me` |
| `PROXY_COUNT` | Number of reverse proxies (for real IP detection) | `0` |

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
