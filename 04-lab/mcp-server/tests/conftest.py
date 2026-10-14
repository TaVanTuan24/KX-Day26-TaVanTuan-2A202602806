"""Fixture dùng chung cho test của MCP weather server (04-lab/mcp-server).

Chạy test:
    cd 04-lab/mcp-server
    uv run --with pytest pytest tests -q

`MockWeatherAPI` là một HTTP server thật chạy trong tiến trình test, đóng vai
WeatherAPI.com. Nhờ đó ta test được ĐÚNG đường httpx thật (status code, JSON
hỏng, timeout, lỗi mạng) mà không cần API key và không gọi ra Internet.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


class MockWeatherAPI:
    """HTTP server giả WeatherAPI — cấu hình được từng route."""

    def __init__(self) -> None:
        # path -> (status, body, delay, raw_text)
        self.routes: dict[str, tuple[int, object, float, str | None]] = {}
        self.requests: list[tuple[str, dict[str, list[str]]]] = []

        outer = self
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(outer))
        self.httpd = httpd
        self.port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def set(
        self,
        path: str,
        *,
        status: int = 200,
        body: object = None,
        delay: float = 0.0,
        raw: str | None = None,
    ) -> None:
        self.routes[path] = (status, body, delay, raw)

    def request_paths(self) -> list[str]:
        return [path for path, _query in self.requests]

    def clear_requests(self) -> None:
        self.requests.clear()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def _make_handler(outer: MockWeatherAPI):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802 - tên do BaseHTTPRequestHandler quy định
            parsed = urlparse(self.path)
            outer.requests.append((parsed.path, parse_qs(parsed.query)))

            route = outer.routes.get(parsed.path)
            if route is None:
                self._respond(404, '{"error":{"code":9999,"message":"no route"}}')
                return

            status, body, delay, raw = route
            if delay:
                time.sleep(delay)
            payload = raw if raw is not None else json.dumps(body)
            self._respond(status, payload)

        def _respond(self, status: int, payload: str) -> None:
            data = payload.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                # Client (test) đã bỏ đi — ví dụ test timeout cố ý ngắt kết nối.
                # Không phải lỗi của server, không cần log ồn ào.
                pass

        def log_message(self, *_args) -> None:  # tắt log ồn ào
            return

    return Handler


@pytest.fixture(scope="session")
def mock_weather_api():
    server = MockWeatherAPI()
    yield server
    server.close()


@pytest.fixture
def weather(mock_weather_api, monkeypatch):
    """Module weather với môi trường đã trỏ sang mock WeatherAPI."""
    import importlib

    import weather as weather_module

    importlib.reload(weather_module)  # đảm bảo HOST/PORT đọc lại từ env

    monkeypatch.setenv("WEATHERAPI_KEY", "test-key-abc123")
    monkeypatch.setenv("WEATHERAPI_BASE_URL", mock_weather_api.base_url)
    monkeypatch.setenv("WEATHERAPI_TIMEOUT", "5")
    mock_weather_api.clear_requests()
    mock_weather_api.routes.clear()
    return weather_module


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


CURRENT_PAYLOAD = {
    "location": {"name": "Hanoi", "region": "Ha Noi", "country": "Vietnam"},
    "current": {
        "temp_c": 29.0,
        "temp_f": 84.2,
        "feelslike_c": 33.0,
        "feelslike_f": 91.4,
        "condition": {"text": "Light rain"},
        "humidity": 82,
        "wind_kph": 12.0,
        "wind_mph": 7.5,
        "wind_dir": "ESE",
        "pressure_mb": 1008.0,
        "uv": 3.0,
        "vis_km": 8.0,
        "last_updated": "2026-10-14 16:00",
    },
}

FORECAST_PAYLOAD = {
    "location": {"name": "Hanoi", "region": "Ha Noi", "country": "Vietnam"},
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
