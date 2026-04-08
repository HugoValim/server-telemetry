from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from datetime import datetime
from collections import deque
from itsdangerous import URLSafeTimedSerializer
import psutil
import asyncio
import os

app = FastAPI(title="Server Telemetry")

# ── Security ──────────────────────────────────────────────────────────────────

# Session signing key — change this to a random value in production
SECRET_KEY = os.environ.get("SECRET_KEY", os.environ.get("API_KEY", "dev-secret-change-me"))
session_serializer = URLSafeTimedSerializer(SECRET_KEY)

API_KEY = os.environ.get("API_KEY")
if not API_KEY:
    import secrets
    API_KEY = secrets.token_hex(16)
    print("WARNING: API_KEY not set via environment variable. Using ephemeral key:", API_KEY[:8] + "...")

API_KEY_READONLY = os.environ.get("API_KEY_READONLY")
if not API_KEY_READONLY:
    import secrets
    API_KEY_READONLY = secrets.token_hex(16)
    print("WARNING: API_KEY_READONLY not set via environment variable. Using ephemeral read-only key:", API_KEY_READONLY[:8] + "...")

# ── OAuth2 / SSO Configuration ───────────────────────────────────────────────

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
# Comma-separated list of allowed email addresses or domains (e.g. "alice@corp.com,bob@corp.com" or "corp.com")
ALLOWED_EMAILS = os.environ.get("ALLOWED_EMAILS", "")

oauth_configured = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def get_allowed_domains():
    """Parse ALLOWED_EMAILS into set of emails and domains."""
    if not ALLOWED_EMAILS:
        return set()
    entries = {e.strip().lower() for e in ALLOWED_EMAILS.split(",") if e.strip()}
    # Separate full emails from domain wildcards
    return entries


def email_allowed(email: str) -> bool:
    """Check if email is in the allowed list or domain."""
    allowed = get_allowed_domains()
    if not allowed:
        return True  # No restriction configured
    email_lower = email.lower()
    for entry in allowed:
        if "@" in entry:
            if email_lower == entry:
                return True
        else:
            # Domain wildcard
            if email_lower.endswith("@" + entry):
                return True
    return False

PROXY_COUNT = int(os.environ.get("PROXY_COUNT", "0"))

# ── Session Management ────────────────────────────────────────────────────────

SESSION_COOKIE = "session"
SESSION_MAX_AGE = 8 * 60 * 60  # 8 hours in seconds


def create_session(response: Response, data: dict):
    """Sign and set a session cookie."""
    session_data = session_serializer.dumps(data)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_data,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=False,  # Set True in production with HTTPS
        samesite="lax",
    )


def get_session(request: Request) -> dict | None:
    """Validate and decode a session cookie. Returns None if invalid."""
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        return None
    try:
        return session_serializer.loads(cookie, max_age=SESSION_MAX_AGE)
    except Exception:
        return None


def clear_session(response: Response):
    """Delete the session cookie."""
    response.set_cookie(
        key=SESSION_COOKIE,
        value="",
        max_age=0,
        httponly=True,
        secure=False,
        samesite="lax",
    )


def get_client_ip(request: Request) -> str:
    """Get real client IP, accounting for trusted reverse proxies."""
    if PROXY_COUNT > 0:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # Take the leftmost (original client) IP
            return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=get_client_ip, default_limits=["60/minute"])

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}

# CORS configuration - allow dashboard to be served from any origin in dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict to specific origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        response.headers[k] = v
    return response


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Slow down."},
        headers={"Retry-After": str(exc.detail)} if hasattr(exc, 'detail') else {},
    )


def verify_auth(request: Request) -> bool:
    """Accept any valid key (read-only or full) or a valid session cookie."""
    # API key auth (for scripts/curl)
    auth = request.headers.get("authorization", "")
    if auth:
        key = auth.removeprefix("Bearer ").strip()
        if key == API_KEY or key == API_KEY_READONLY:
            return True
    # Session cookie auth (for OAuth login)
    if get_session(request):
        return True
    return False


def verify_full_auth(request: Request) -> bool:
    """Accept only the full API_KEY (not the read-only key or session)."""
    auth = request.headers.get("authorization", "")
    key = auth.removeprefix("Bearer ").strip()
    return key == API_KEY


async def auth_check(request: Request, path: str):
    """Reject unauthenticated requests to protected paths."""
    if path.startswith("/api/") or path.startswith("/ws/"):
        if not verify_auth(request):
            raise HTTPException(status_code=401, detail="Unauthorized")


# ── WebSocket with auth ───────────────────────────────────────────────────────

@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    # Auth via session cookie (browser sends cookies during WS handshake)
    # OR via Sec-WebSocket-Protocol header (API key)
    session_cookie = websocket.cookies.get(SESSION_COOKIE)
    authenticated = False

    if session_cookie:
        try:
            session_serializer.loads(session_cookie, max_age=SESSION_MAX_AGE)
            authenticated = True
        except Exception:
            pass

    if not authenticated:
        # Fallback: subprotocol (API key) — also try session via subprotocol
        protocol = websocket.subprotocol
        if protocol and (protocol == API_KEY or protocol == API_KEY_READONLY):
            authenticated = True
        elif protocol:
            # Might be a session token in subprotocol
            try:
                session_serializer.loads(protocol, max_age=SESSION_MAX_AGE)
                authenticated = True
            except Exception:
                pass

    if not authenticated:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    try:
        while True:
            data = get_telemetry_data()
            await websocket.send_json(data)
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass


# ── Metrics history ────────────────────────────────────────────────────────────

MAX_HISTORY = 300
history = {
    "cpu": deque(maxlen=MAX_HISTORY),
    "memory": deque(maxlen=MAX_HISTORY),
    "disk": deque(maxlen=MAX_HISTORY),
}

thresholds = {
    "cpu": 80.0,
    "memory": 80.0,
    "disk": 90.0,
}


def get_telemetry_data() -> dict:
    vm = psutil.virtual_memory()
    du = psutil.disk_usage("/")
    nc = psutil.net_io_counters()
    cpu_pct = psutil.cpu_percent(interval=0.1)
    boot_time = psutil.boot_time()

    now = datetime.now().isoformat()
    history["cpu"].append({"time": now, "value": cpu_pct})
    history["memory"].append({"time": now, "value": vm.percent})
    history["disk"].append({"time": now, "value": du.percent})

    load_avg = psutil.getloadavg() if hasattr(psutil, "getloadavg") else None
    swap = psutil.swap_memory()
    temps = []
    try:
        temps = [{"label": k, "value": v} for k, v in psutil.sensors_temperatures().items()]
    except Exception:
        pass

    return {
        "cpu": {
            "percent": cpu_pct,
            "count": psutil.cpu_count(),
            "load_avg": list(load_avg) if load_avg else None,
        },
        "memory": {
            "total": vm.total,
            "available": vm.available,
            "percent": vm.percent,
            "used": vm.used,
            "swap_total": swap.total,
            "swap_used": swap.used,
            "swap_percent": swap.percent,
        },
        "disk": {
            "total": du.total,
            "used": du.used,
            "free": du.free,
            "percent": du.percent,
        },
        "network": {
            "bytes_sent": nc.bytes_sent,
            "bytes_recv": nc.bytes_recv,
            "packets_sent": nc.packets_sent,
            "packets_recv": nc.packets_recv,
        },
        "uptime": boot_time,
        "temperatures": temps,
        "alerts": {
            k: bool(v > thresholds[k]) for k, v in {
                "cpu": cpu_pct,
                "memory": vm.percent,
                "disk": du.percent,
            }.items()
        },
    }


# Public endpoints (no auth required)
@app.get("/health")
def health():
    return {"ok": True}


@app.get("/ready")
def ready():
    return {"ok": True}


@app.get("/live")
def live():
    return {"ok": True}


# ── OAuth2 / SSO Endpoints ────────────────────────────────────────────────────

@app.get("/auth/login")
def auth_login(request: Request):
    """Redirect to Google OAuth consent screen."""
    if not oauth_configured:
        return JSONResponse(
            status_code=503,
            content={"detail": "OAuth2 not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables."},
        )
    import urllib.parse
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": str(request.base_url).rstrip("/") + "/auth/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
    }
    return RedirectResponse(
        url="https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params),
        status_code=302,
    )


@app.get("/auth/callback")
async def auth_callback(request: Request, code: str | None = None, error: str | None = None):
    """Handle OAuth2 callback from Google."""
    if error:
        return JSONResponse(status_code=400, content={"detail": f"OAuth error: {error}"})

    if not code:
        return JSONResponse(status_code=400, content={"detail": "Missing authorization code"})

    # Exchange code for tokens
    import httpx
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": str(request.base_url).rstrip("/") + "/auth/callback",
                "grant_type": "authorization_code",
            },
        )

    if token_resp.status_code != 200:
        return JSONResponse(status_code=400, content={"detail": "Failed to exchange code for token"})

    token_data = token_resp.json()
    id_token = token_data.get("id_token") or token_data.get("access_token")

    # Get user info
    userinfo_resp = await client.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {id_token}"},
    )

    if userinfo_resp.status_code != 200:
        return JSONResponse(status_code=400, content={"detail": "Failed to get user info"})

    user_info = userinfo_resp.json()
    email = user_info.get("email", "")

    if not email_allowed(email):
        return JSONResponse(
            status_code=403,
            content={"detail": f"Access denied. Email '{email}' is not in the allowed list."},
        )

    # Create session
    session_data = {"email": email, "name": user_info.get("name", "")}
    response = RedirectResponse(url="/", status_code=302)
    create_session(response, session_data)
    return response


@app.get("/auth/logout")
def auth_logout():
    """Clear session and redirect to home."""
    response = RedirectResponse(url="/", status_code=302)
    clear_session(response)
    return response


@app.get("/auth/me")
def auth_me(request: Request):
    """Return current user info from session."""
    session = get_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="Not logged in")
    return session


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # Skip auth for public endpoints
    public = {"/", "/health", "/ready", "/live", "/dashboard", "/auth/"}
    if any(path.startswith(p) for p in public):
        return await call_next(request)
    if path.startswith("/api/") or path.startswith("/ws/"):
        await auth_check(request, path)
    return await call_next(request)


@app.get("/api/telemetry")
@limiter.limit("60/minute")
def get_telemetry(request: Request):
    return get_telemetry_data()


@app.get("/api/telemetry/cpu")
@limiter.limit("60/minute")
def get_cpu(request: Request):
    return {
        "percent": psutil.cpu_percent(interval=0.1),
        "count": psutil.cpu_count(),
        "load_avg": list(psutil.getloadavg()) if hasattr(psutil, "getloadavg") else None,
    }


@app.get("/api/telemetry/memory")
@limiter.limit("60/minute")
def get_memory(request: Request):
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return {
        "total": vm.total,
        "available": vm.available,
        "percent": vm.percent,
        "used": vm.used,
        "swap_total": swap.total,
        "swap_used": swap.used,
        "swap_percent": swap.percent,
    }


@app.get("/api/telemetry/disk")
@limiter.limit("60/minute")
def get_disk(request: Request):
    du = psutil.disk_usage("/")
    return {
        "total": du.total,
        "used": du.used,
        "free": du.free,
        "percent": du.percent,
    }


@app.get("/api/telemetry/network")
@limiter.limit("60/minute")
def get_network(request: Request):
    nc = psutil.net_io_counters()
    return {
        "bytes_sent": nc.bytes_sent,
        "bytes_recv": nc.bytes_recv,
        "packets_sent": nc.packets_sent,
        "packets_recv": nc.packets_recv,
    }


@app.get("/api/telemetry/uptime")
@limiter.limit("60/minute")
def get_uptime(request: Request):
    return {"uptime": psutil.boot_time()}


@app.get("/api/telemetry/history")
@limiter.limit("30/minute")
def get_history(request: Request, metric: str = "cpu", limit: int = 100):
    if metric not in history:
        raise HTTPException(400, f"Unknown metric: {metric}")
    limit = max(1, min(limit, MAX_HISTORY))
    data = list(history[metric])
    return {"metric": metric, "data": data[-limit:]}


@app.get("/api/processes")
@limiter.limit("30/minute")
def get_processes(request: Request, sort_by: str = "cpu", limit: int = 5):
    if sort_by not in ("cpu", "memory"):
        raise HTTPException(400, "sort_by must be 'cpu' or 'memory'")
    processes = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            proc = p.as_dict(attrs=["pid", "name"])
            if sort_by == "cpu":
                proc["value"] = p.cpu_percent(interval=0.05)
            else:
                proc["value"] = p.memory_percent()
            processes.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    processes.sort(key=lambda x: x["value"], reverse=True)
    return {"processes": processes[:limit]}


@app.get("/api/thresholds")
@limiter.limit("30/minute")
def get_thresholds(request: Request):
    return thresholds


@app.post("/api/thresholds")
@limiter.limit("30/minute")
def set_thresholds(request: Request, cpu: float = 80.0, memory: float = 80.0, disk: float = 90.0):
    # Require full API_KEY, not read-only key
    if not verify_full_auth(request):
        raise HTTPException(status_code=403, detail="Read-only key cannot modify thresholds")
    thresholds["cpu"] = max(0, min(100, cpu))
    thresholds["memory"] = max(0, min(100, memory))
    thresholds["disk"] = max(0, min(100, disk))
    return thresholds


# Serve dashboard
app.mount("/dashboard", StaticFiles(directory="dashboard", html=True), name="dashboard")


@app.get("/")
def root():
    return FileResponse("dashboard/index.html")
