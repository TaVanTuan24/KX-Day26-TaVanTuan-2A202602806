"""Fixture cho test của mcp-client (04-lab/mcp-client).

Chạy test:
    cd 04-lab/mcp-client
    uv run --with pytest pytest tests -q                    # unit (không gọi API)
    $env:DAY26_E2E=1; uv run --with pytest pytest tests -q   # bật E2E (cần Gemini key)
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

CLIENT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = CLIENT_DIR.parents[1]
SERVER_DIR = REPO_ROOT / "04-lab" / "mcp-server"
SERVER_SCRIPT = SERVER_DIR / "weather.py"

if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# ── Mock WeatherAPI ─────────────────────────────────────────────────────────
CURRENT_PAYLOAD = {
    "location": {"name": "Hanoi", "region": "Ha Noi", "country": "Vietnam"},
    "current": {
        "temp_c": 29.0,
        "feelslike_c": 33.0,
        "condition": {"text": "Light rain"},
        "humidity": 82,
        "wind_kph": 12.0,
        "wind_dir": "ESE",
        "pressure_mb": 1008.0,
        "uv": 3.0,
        "vis_km": 8.0,
        "last_updated": "2026-10-14 16:00",
    },
}

FORECAST_PAYLOAD = {
    "location": {"name": "Da Nang", "region": "Da Nang", "country": "Vietnam"},
    "forecast": {
        "forecastday": [
            {
                "date": "2026-10-15",
                "day": {
                    "maxtemp_c": 31.0,
                    "mintemp_c": 24.0,
                    "condition": {"text": "Patchy rain nearby"},
                    "daily_chance_of_rain": 71,
                    "maxwind_kph": 18.0,
                    "uv": 6.0,
                },
            },
            {
                "date": "2026-10-16",
                "day": {
                    "maxtemp_c": 33.0,
                    "mintemp_c": 25.0,
                    "condition": {"text": "Sunny"},
                    "daily_chance_of_rain": 10,
                    "maxwind_kph": 14.0,
                    "uv": 8.0,
                },
            },
        ]
    },
}


class MockWeatherAPI:
    """HTTP server giả WeatherAPI cho test E2E (upstream giả, MCP + ADK thật)."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, list[str]]]] = []

        outer = self
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler(outer))
        self.httpd = httpd
        self.port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def _handler(outer: MockWeatherAPI):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            outer.requests.append((parsed.path, parse_qs(parsed.query)))
            if parsed.path.endswith("/current.json"):
                body = CURRENT_PAYLOAD
            elif parsed.path.endswith("/forecast.json"):
                body = FORECAST_PAYLOAD
            else:
                body = {"error": {"code": 9999, "message": "no route"}}
            data = json.dumps(body).encode("utf-8")
            self.send_response(200 if "error" not in body else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_args) -> None:
            return

    return Handler


@pytest.fixture(scope="session")
def mock_weather_api():
    server = MockWeatherAPI()
    yield server
    server.close()


# ── MCP server thật (04-lab/mcp-server) chạy như tiến trình con ──────────────
@contextmanager
def spawn_mcp_server(**extra_env: str):
    port = free_port()
    url = f"http://127.0.0.1:{port}/mcp"
    env = {
        **os.environ,
        "PORT": str(port),
        "HOST": "127.0.0.1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
    }
    env.pop("WEATHERAPI_KEY", None)
    env.update(extra_env)

    server_python = SERVER_DIR / ".venv" / "Scripts" / "python.exe"
    if not server_python.is_file():  # Linux/macOS
        server_python = SERVER_DIR / ".venv" / "bin" / "python"
    if not server_python.is_file():
        server_python = Path(sys.executable)

    proc = subprocess.Popen(
        [str(server_python), str(SERVER_SCRIPT)],
        cwd=str(SERVER_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    async_ready = False
    deadline = time.time() + 45
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        try:
            with httpx.Client(timeout=5.0) as client:
                client.post(
                    url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "t", "version": "1"},
                        },
                    },
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream",
                    },
                )
            async_ready = True
            break
        except httpx.RequestError:
            time.sleep(0.5)

    try:
        yield url, async_ready, proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()
            proc.wait(timeout=10)
        for stream in (proc.stdout, proc.stderr, proc.stdin):
            if stream is not None:
                stream.close()
