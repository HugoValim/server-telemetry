from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, WebSocketDeniedMessage
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from datetime import datetime
from collections import deque
import psutil
import asyncio
import time
import secrets

app = FastAPI(title="Server Telemetry")

# ── Security ──────────────────────────────────────────────────────────────────

API_KEY = secrets.token_hex(16)

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


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
    auth = request.headers.get("authorization", "")
    return auth == f"Bearer {API_KEY}"


async def auth_check(request: Request, path: str):
    """Reject unauthenticated requests to protected paths."""
    if path.startswith("/api/") or path.startswith("/ws/"):
        if not verify_auth(request):
            raise HTTPException(status_code=401, detail="Unauthorized")


# ── WebSocket with auth ───────────────────────────────────────────────────────

@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    # Auth via query param ?token=<key> since headers aren't accessible on ws handshake
    token = websocket.query_params.get("token", "")
    if token != API_KEY:
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


# ── REST Endpoints ────────────────────────────────────────────────────────────

class AnalyzeIn(BaseModel):
    text: str


def compute(text: str) -> dict:
    words = [w for w in text.strip().split() if w]
    letters = sum(1 for ch in text if ch.isalpha())
    chars = len(text)
    return {
        "chars": chars,
        "letters": letters,
        "words": len(words),
        "unique_words": len({w.lower().strip(".,!?;:\"'") for w in words if w}),
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


# Auth-gated endpoints
@app.get("/api/key")
def get_api_key():
    """Returns the current API key on first request only (it's per-process)."""
    return {"api_key": API_KEY}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # Skip auth for public endpoints
    public = {"/", "/health", "/ready", "/live", "/dashboard"}
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
    thresholds["cpu"] = max(0, min(100, cpu))
    thresholds["memory"] = max(0, min(100, memory))
    thresholds["disk"] = max(0, min(100, disk))
    return thresholds


# Serve dashboard
app.mount("/dashboard", StaticFiles(directory="dashboard", html=True), name="dashboard")


@app.get("/")
def root():
    return FileResponse("dashboard/index.html")
