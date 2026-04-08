import sys
import subprocess
import time
import socket
from pathlib import Path

import http.client
import json


def wait_port(host: str, port: int, timeout_s: float = 10.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("server did not start")


def test_analyze_endpoint():
    port = 8010
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(Path(__file__).parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_port("127.0.0.1", port)

        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request(
            "POST",
            "/analyze",
            body=json.dumps({"text": "Hello hello world!"}),
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))

        assert resp.status == 200
        assert data["words"] == 3
        assert data["letters"] >= 10
        assert data["unique_words"] == 2
    finally:
        server.terminate()
        server.wait(timeout=5)


def test_telemetry_endpoint():
    port = 8010
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(Path(__file__).parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_port("127.0.0.1", port)

        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request("GET", "/api/telemetry")
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))

        assert resp.status == 200
        assert "cpu" in data
        assert "memory" in data
        assert "disk" in data
        assert "network" in data
        assert "uptime" in data
        assert 0 <= data["cpu"]["percent"] <= 100
        assert 0 <= data["memory"]["percent"] <= 100
        assert 0 <= data["disk"]["percent"] <= 100
        assert isinstance(data["network"]["bytes_sent"], int)
        assert isinstance(data["network"]["bytes_recv"], int)
        # new fields
        assert "swap_total" in data["memory"]
        assert "alerts" in data
    finally:
        server.terminate()
        server.wait(timeout=5)


def test_processes_endpoint():
    port = 8010
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(Path(__file__).parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_port("127.0.0.1", port)

        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request("GET", "/api/processes?sort_by=cpu&limit=3")
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))

        assert resp.status == 200
        assert "processes" in data
        assert len(data["processes"]) <= 3
        assert all(k in data["processes"][0] for k in ("pid", "name", "value"))
    finally:
        server.terminate()
        server.wait(timeout=5)


def test_history_endpoint():
    port = 8010
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(Path(__file__).parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_port("127.0.0.1", port)

        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request("GET", "/api/telemetry/history?metric=cpu&limit=10")
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))

        assert resp.status == 200
        assert data["metric"] == "cpu"
        assert "data" in data
    finally:
        server.terminate()
        server.wait(timeout=5)


def test_thresholds_endpoint():
    port = 8010
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(Path(__file__).parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_port("127.0.0.1", port)

        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request("GET", "/api/thresholds")
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))

        assert resp.status == 200
        assert "cpu" in data
        assert "memory" in data
        assert "disk" in data
    finally:
        server.terminate()
        server.wait(timeout=5)


def test_k8s_probes():
    port = 8010
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(Path(__file__).parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_port("127.0.0.1", port)

        conn = http.client.HTTPConnection("127.0.0.1", port)
        for path in ("/health", "/ready", "/live"):
            conn.request("GET", path)
            resp = conn.getresponse()
            data = json.loads(resp.read().decode("utf-8"))
            assert resp.status == 200
            assert data["ok"] is True
    finally:
        server.terminate()
        server.wait(timeout=5)
    port = 8010
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(Path(__file__).parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_port("127.0.0.1", port)

        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request("GET", "/")
        resp = conn.getresponse()
        assert resp.status == 200
        body = resp.read()
        assert b"<html" in body.lower() or b"<!doctype" in body.lower()
        assert b"Server Telemetry" in body
    finally:
        server.terminate()
        server.wait(timeout=5)
