"""Weather MCP Server — Streamable HTTP, dữ liệu THẬT từ WeatherAPI.com.

Công cụ công bố:
    get_current_weather(city)   — thời tiết hiện tại
    get_forecast(city, days)    — dự báo 1..3 ngày (free tier)
    health_check()              — kiểm tra server sống (KHÔNG gọi WeatherAPI)

Endpoint mặc định: http://localhost:8085/mcp

Cách chạy:
    cd 04-lab/mcp-server
    uv sync
    $env:WEATHERAPI_KEY = "key-của-bạn"      # PowerShell
    uv run python weather.py

Biến môi trường:
    WEATHERAPI_KEY      (bắt buộc để có dữ liệu thật) key từ weatherapi.com
    PORT                cổng lắng nghe (mặc định 8085; Cloud Run tự set)
    HOST                interface (mặc định 0.0.0.0 — cần cho Cloud Run/Docker)
    MCP_TRANSPORT       "streamable-http" (mặc định) | "stdio" | "sse"
    WEATHERAPI_TIMEOUT  timeout giây cho mỗi request (mặc định 15)
    WEATHERAPI_BASE_URL ghi đè base URL (phục vụ test offline)

Bảo mật: API key CHỈ được đọc từ biến môi trường, không bao giờ được in ra
stdout/stderr/log, và không nằm trong image Docker.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

# Console Windows mặc định cp1252 → log tiếng Việt ra stderr sẽ UnicodeEncodeError
# khi stderr bị redirect (pipe/file). Ép UTF-8 cho stderr.
# ⚠️ KHÔNG đụng vào stdout: khi transport là stdio, stdout là kênh JSON-RPC.
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _env_candidates(module_file: Path) -> list[Path]:
    """Các vị trí `.env` sẽ thử nạp, theo thứ tự ưu tiên.

    ⚠️ Phải chịu được đường dẫn NÔNG. Trong Docker, file nằm ở `/app/weather.py`
    nên `parents` chỉ có 2 phần tử — truy cập thẳng `parents[2]` sẽ ném
    `IndexError` và làm container chết ngay khi khởi động. Đây là bug thật đã
    gặp, chỉ lộ ra khi rebuild và chạy lại image.
    """
    resolved = Path(module_file).resolve()
    candidates = [resolved.parent / ".env"]
    parents = resolved.parents
    if len(parents) > 2:  # đủ sâu để còn lên được repo root
        candidates.append(parents[2] / ".env")
    return candidates


def _load_dotenv_files() -> list[Path]:
    """Nạp `.env` cạnh file này (và ở repo root nếu có) theo mẫu `.env.example`.

    `python-dotenv` là dependency BẮC CẦU (đến từ fastmcp/mcp[cli]) nên KHÔNG
    được khai báo trong pyproject.toml. Vì vậy phải import mềm: thiếu package
    thì vẫn chạy bình thường bằng biến môi trường đã export.

    Quan trọng: nếu CÓ `.env` mà KHÔNG nạp được, phải báo rõ ra stderr — im lặng
    bỏ qua sẽ khiến người dùng tưởng key đã được đọc.
    """
    candidates = _env_candidates(Path(__file__))
    try:
        from dotenv import load_dotenv
    except ImportError:
        if any(path.is_file() for path in candidates):
            print(
                "[weather-mcp] ⚠️  Có file .env nhưng thiếu python-dotenv → KHÔNG "
                "nạp được. Hãy export biến môi trường trực tiếp.",
                file=sys.stderr,
            )
        return []

    loaded: list[Path] = []
    for candidate in candidates:
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            loaded.append(candidate)
    return loaded


LOADED_ENV_FILES = _load_dotenv_files()

# ── Cấu hình ────────────────────────────────────────────────────────────────
# Base URL / timeout đọc tại THỜI ĐIỂM GỌI (không cache lúc import) để test có
# thể trỏ sang mock server hoặc đổi timeout mà không cần reload module.
DEFAULT_WEATHERAPI_BASE = "https://api.weatherapi.com/v1"
USER_AGENT = "day26-weather-mcp/1.0"
MAX_FORECAST_DAYS = 3
SUPPORTED_TRANSPORTS = ("streamable-http", "stdio", "sse")

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8085"))

mcp = FastMCP("weather", host=HOST, port=PORT, log_level="WARNING")

TOOL_NAMES = ("get_current_weather", "get_forecast", "health_check")


# ── Tiện ích ────────────────────────────────────────────────────────────────
def _base_url() -> str:
    return (os.getenv("WEATHERAPI_BASE_URL") or "").strip() or DEFAULT_WEATHERAPI_BASE


def _request_timeout() -> float:
    try:
        return float(os.getenv("WEATHERAPI_TIMEOUT", "15"))
    except ValueError:
        return 15.0


def _api_key() -> str | None:
    """Đọc WEATHERAPI_KEY tại thời điểm gọi (không cache lúc import)."""
    raw = os.getenv("WEATHERAPI_KEY")
    if raw is None:
        return None
    key = raw.strip()
    return key or None


def _scrub(text: str) -> str:
    """Bảo hiểm cuối: không bao giờ để API key lọt vào thông báo/log."""
    key = _api_key()
    return text.replace(key, "***REDACTED***") if key else text


def _val(mapping: dict[str, Any], key: str, fallback: str = "không rõ") -> Any:
    value = mapping.get(key)
    return fallback if value in (None, "") else value


def _describe_api_error(error: object) -> str:
    if isinstance(error, dict):
        message = _val(error, "message", "không rõ")
        code = _val(error, "code", "?")
        return f"WeatherAPI trả lỗi {code}: {message}"
    return "WeatherAPI trả về lỗi không xác định"


def _describe_http_error(response: httpx.Response) -> str:
    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict) and "error" in body:
            detail = f" — {_describe_api_error(body['error'])}"
    except ValueError:
        detail = ""

    status = response.status_code
    if status in (401, 403):
        return f"WeatherAPI từ chối API key (HTTP {status}){detail}"
    if status == 400:
        return (
            f"WeatherAPI báo yêu cầu không hợp lệ (HTTP 400){detail}. "
            "Kiểm tra lại tên thành phố."
        )
    if status == 429:
        return "WeatherAPI báo vượt quota (HTTP 429)."
    if status >= 500:
        return f"WeatherAPI lỗi phía máy chủ (HTTP {status})."
    return f"WeatherAPI trả về HTTP {status}{detail}"


async def _fetch(
    endpoint: str, params: dict[str, str]
) -> tuple[dict[str, Any] | None, str | None]:
    """Gọi WeatherAPI. Trả về (data, error_message) — không bao giờ raise ra tool."""
    key = _api_key()
    if key is None:
        return None, (
            "WEATHERAPI_KEY chưa được cấu hình trên MCP server. "
            "Đặt biến môi trường WEATHERAPI_KEY (key free tại "
            "https://www.weatherapi.com/signup.aspx) rồi khởi động lại server."
        )

    url = f"{_base_url()}/{endpoint}"
    query = {**params, "key": key}
    timeout = _request_timeout()

    try:
        async with httpx.AsyncClient(
            timeout=timeout, headers={"User-Agent": USER_AGENT}
        ) as client:
            response = await client.get(url, params=query)
    except httpx.TimeoutException:
        return None, f"Timeout khi gọi WeatherAPI sau {timeout:g}s."
    except httpx.RequestError as exc:
        return None, f"Lỗi mạng khi gọi WeatherAPI ({type(exc).__name__})."

    if response.status_code != 200:
        return None, _describe_http_error(response)

    try:
        data = response.json()
    except ValueError:
        return None, "WeatherAPI trả về dữ liệu không phải JSON."

    if not isinstance(data, dict):
        return None, "WeatherAPI trả về JSON sai cấu trúc (không phải object)."
    if "error" in data:
        return None, _describe_api_error(data["error"])
    return data, None


def _format_current(data: dict[str, Any]) -> str:
    current = data.get("current")
    location = data.get("location")
    if not isinstance(current, dict) or not current:
        return "❌ WeatherAPI trả về dữ liệu thiếu mục 'current'."
    if not isinstance(location, dict):
        location = {}

    name = _val(location, "name", "?")
    region = location.get("region") or ""
    country = location.get("country") or ""
    place = ", ".join(part for part in (name, region, country) if part)
    condition = _val(current.get("condition") or {}, "text")

    return "\n".join(
        [
            f"Thời tiết hiện tại tại {place}:",
            f"- Nhiệt độ: {_val(current, 'temp_c')}°C "
            f"(cảm giác như {_val(current, 'feelslike_c')}°C)",
            f"- Tình trạng: {condition}",
            f"- Độ ẩm: {_val(current, 'humidity')}%",
            f"- Gió: {_val(current, 'wind_kph')} km/h hướng {_val(current, 'wind_dir')}",
            f"- Áp suất: {_val(current, 'pressure_mb')} mb",
            f"- Chỉ số UV: {_val(current, 'uv')}",
            f"- Tầm nhìn: {_val(current, 'vis_km')} km",
            f"- Cập nhật lúc: {_val(current, 'last_updated')} (giờ địa phương)",
        ]
    )


def _format_forecast(data: dict[str, Any], days: int) -> str:
    location = data.get("location")
    forecast = data.get("forecast")
    if not isinstance(forecast, dict) or not forecast.get("forecastday"):
        return "❌ WeatherAPI trả về dữ liệu thiếu mục 'forecast.forecastday'."
    if not isinstance(location, dict):
        location = {}

    name = _val(location, "name", "?")
    region = location.get("region") or ""
    country = location.get("country") or ""
    place = ", ".join(part for part in (name, region, country) if part)

    blocks = [f"Dự báo {days} ngày tới tại {place}:"]
    for entry in forecast["forecastday"]:
        if not isinstance(entry, dict):
            continue
        day = entry.get("day")
        if not isinstance(day, dict):
            day = {}
        condition = _val(day.get("condition") or {}, "text")
        blocks.append(
            "\n".join(
                [
                    f"\nNgày {_val(entry, 'date')}:",
                    f"- Cao nhất / thấp nhất: {_val(day, 'maxtemp_c')}°C / "
                    f"{_val(day, 'mintemp_c')}°C",
                    f"- Tình trạng: {condition}",
                    f"- Khả năng mưa: {_val(day, 'daily_chance_of_rain')}%",
                    f"- Gió mạnh nhất: {_val(day, 'maxwind_kph')} km/h",
                    f"- Chỉ số UV: {_val(day, 'uv')}",
                ]
            )
        )
    return "\n".join(blocks)


# ── Tools ───────────────────────────────────────────────────────────────────
@mcp.tool()
async def get_current_weather(city: str) -> str:
    """Lấy thời tiết hiện tại (real-time) của một thành phố.

    Args:
        city: Tên thành phố, ví dụ "Hanoi", "Danang", "Haiphong", "Tokyo".
    """
    if not isinstance(city, str) or not city.strip():
        return "❌ Tên thành phố không được để trống."

    data, error = await _fetch("current.json", {"q": city.strip(), "aqi": "no"})
    if error:
        return _scrub(f"❌ Không lấy được thời tiết hiện tại cho '{city}': {error}")
    return _format_current(data)


@mcp.tool()
async def get_forecast(city: str, days: int = 3) -> str:
    """Lấy dự báo thời tiết của một thành phố trong 1 đến 3 ngày tới.

    Args:
        city: Tên thành phố, ví dụ "Hanoi", "Danang", "Tokyo".
        days: Số ngày cần dự báo, chỉ nhận 1, 2 hoặc 3 (mặc định 3).
    """
    if not isinstance(city, str) or not city.strip():
        return "❌ Tên thành phố không được để trống."

    # Kiểm tra kiểu TRƯỚC: bool là subclass của int nên phải loại riêng.
    if isinstance(days, bool) or not isinstance(days, int):
        return (
            f"❌ Tham số 'days' phải là số nguyên từ 1 đến {MAX_FORECAST_DAYS} "
            f"(nhận được: {days!r}). Không gửi yêu cầu tới WeatherAPI."
        )
    if days < 1 or days > MAX_FORECAST_DAYS:
        return (
            f"❌ Tham số 'days' không hợp lệ: {days}. WeatherAPI free tier chỉ hỗ "
            f"trợ 1 đến {MAX_FORECAST_DAYS} ngày. Không gửi yêu cầu tới WeatherAPI "
            "(không tự ý thay bằng giá trị khác để tránh trả dữ liệu sai lệch)."
        )

    data, error = await _fetch(
        "forecast.json",
        {"q": city.strip(), "days": str(days), "aqi": "no", "alerts": "no"},
    )
    if error:
        return _scrub(f"❌ Không lấy được dự báo cho '{city}': {error}")
    return _format_forecast(data, days)


@mcp.tool()
async def health_check() -> str:
    """Kiểm tra MCP server còn sống. KHÔNG gọi WeatherAPI, không cần API key."""
    return json.dumps(
        {
            "status": "ok",
            "server": "weather-mcp",
            "transport": "streamable-http",
            "host": HOST,
            "port": PORT,
            "endpoint": f"http://{HOST}:{PORT}/mcp",
            "tools": list(TOOL_NAMES),
            "max_forecast_days": MAX_FORECAST_DAYS,
            # Chỉ công bố CÓ/KHÔNG, tuyệt đối không công bố giá trị key.
            "weatherapi_key_configured": _api_key() is not None,
        },
        ensure_ascii=False,
    )


# ── Khởi động ───────────────────────────────────────────────────────────────
def resolve_transport() -> str:
    """Chọn transport. MẶC ĐỊNH LUÔN là streamable-http.

    Trước đây server tự chuyển sang stdio khi thấy `sys.stdin.isatty()` — nghĩa
    là chạy `uv run python weather.py` trong terminal sẽ ra stdio, còn chạy qua
    Docker/Cloud Run lại ra HTTP. Hành vi phụ thuộc TTY như vậy rất khó đoán và
    là nguyên nhân điển hình của lỗi "client không kết nối được".

    Giờ đây chỉ dùng stdio khi đặt tường minh MCP_TRANSPORT=stdio (client
    spawn server làm subprocess).
    """
    requested = (os.getenv("MCP_TRANSPORT") or "").strip().lower()
    if not requested:
        return "streamable-http"
    if requested not in SUPPORTED_TRANSPORTS:
        raise SystemExit(
            f"MCP_TRANSPORT không hợp lệ: {requested!r}. "
            f"Chọn một trong: {', '.join(SUPPORTED_TRANSPORTS)}"
        )
    return requested


if __name__ == "__main__":
    transport = resolve_transport()
    # Mọi log đi ra stderr: stdout có thể là kênh JSON-RPC khi dùng stdio.
    if LOADED_ENV_FILES:
        print(
            "[weather-mcp] .env đã nạp: " + ", ".join(str(p) for p in LOADED_ENV_FILES),
            file=sys.stderr,
        )
    if transport == "stdio":
        print("[weather-mcp] transport=stdio (MCP_TRANSPORT=stdio)", file=sys.stderr)
    else:
        print(
            f"[weather-mcp] transport={transport} → http://{HOST}:{PORT}/mcp",
            file=sys.stderr,
        )
    if _api_key() is None:
        print(
            "[weather-mcp] ⚠️  WEATHERAPI_KEY chưa được đặt — các tool thời tiết "
            "sẽ trả lỗi cấu hình (health_check vẫn chạy).",
            file=sys.stderr,
        )
    mcp.run(transport=transport)  # type: ignore[arg-type]
