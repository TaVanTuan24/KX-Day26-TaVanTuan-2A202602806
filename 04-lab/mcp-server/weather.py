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


def _val(mapping: object, key: str, fallback: str = "không rõ") -> Any:
    """Lấy giá trị VÔ HƯỚNG từ `mapping`, an toàn với mọi kiểu dữ liệu.

    Xử lý được nested JSON sai kiểu:
      - `mapping` không phải dict (ví dụ `current` là chuỗi) → fallback.
      - giá trị là dict/list/tuple/set (lồng sâu hơn dự kiến) → fallback, KHÔNG
        đổ JSON thô vào câu trả lời cho người dùng.

    Bản cũ gọi thẳng `mapping.get(...)`, nên `_val("Cloudy", "text")` sẽ ném
    `AttributeError: 'str' object has no attribute 'get'`.
    """
    if not isinstance(mapping, dict):
        return fallback
    value = mapping.get(key)
    if value is None or value == "":
        return fallback
    if isinstance(value, (dict, list, tuple, set)):
        return fallback
    return value


def _str_or_empty(mapping: object, key: str) -> str:
    """Lấy giá trị dạng chuỗi (dùng cho field có thể vắng), sai kiểu → ""."""
    if not isinstance(mapping, dict):
        return ""
    value = mapping.get(key)
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    return str(value).strip()


def _place(location: object) -> str:
    """Ghép "name, region, country" an toàn với mọi kiểu dữ liệu.

    Bản cũ dùng `", ".join(...)` trực tiếp, nên `name` là số/list/dict sẽ ném
    `TypeError: sequence item 0: expected str instance`.
    """
    if not isinstance(location, dict):
        return "?"
    parts = [_str_or_empty(location, key) for key in ("name", "region", "country")]
    return ", ".join(part for part in parts if part) or "?"


def _condition(container: object) -> str:
    """Lấy `condition.text` an toàn.

    `condition` trong WeatherAPI là object lồng, nhưng nếu upstream trả về chuỗi
    (hoặc số, hoặc list) thì vẫn phải xử lý được. Chuỗi đi thẳng vẫn dùng được.
    """
    if not isinstance(container, dict):
        return "không rõ"
    condition = container.get("condition")
    if isinstance(condition, dict):
        return str(_val(condition, "text"))
    if isinstance(condition, str) and condition.strip():
        return condition.strip()
    return "không rõ"


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


# Các field vô hướng mà một payload `current` dùng được phải có ít nhất một cái.
_CURRENT_FIELDS = (
    "temp_c",
    "feelslike_c",
    "humidity",
    "wind_kph",
    "wind_dir",
    "pressure_mb",
    "uv",
    "vis_km",
    "last_updated",
)


def _format_current(data: object) -> str:
    """Định dạng thời tiết hiện tại. KHÔNG bao giờ crash, KHÔNG báo thành công giả."""
    if not isinstance(data, dict):
        return "❌ WeatherAPI trả về dữ liệu hiện tại sai cấu trúc (không phải object)."

    current = data.get("current")
    if not isinstance(current, dict) or not current:
        return "❌ WeatherAPI trả về dữ liệu thiếu mục 'current'."

    # Nếu không có MỘT field vô hướng nào đọc được thì payload vô dụng — phải báo
    # lỗi, không được trả về một trang toàn "không rõ" như thể thành công.
    if not any(_val(current, field, None) is not None for field in _CURRENT_FIELDS):
        return (
            "❌ WeatherAPI trả về dữ liệu hiện tại không hợp lệ "
            "(không có trường số liệu nào đọc được)."
        )

    place = _place(data.get("location"))

    return "\n".join(
        [
            f"Thời tiết hiện tại tại {place}:",
            f"- Nhiệt độ: {_val(current, 'temp_c')}°C "
            f"(cảm giác như {_val(current, 'feelslike_c')}°C)",
            f"- Tình trạng: {_condition(current)}",
            f"- Độ ẩm: {_val(current, 'humidity')}%",
            f"- Gió: {_val(current, 'wind_kph')} km/h hướng {_val(current, 'wind_dir')}",
            f"- Áp suất: {_val(current, 'pressure_mb')} mb",
            f"- Chỉ số UV: {_val(current, 'uv')}",
            f"- Tầm nhìn: {_val(current, 'vis_km')} km",
            f"- Cập nhật lúc: {_val(current, 'last_updated')} (giờ địa phương)",
        ]
    )


# Các field số liệu của một ngày dự báo. Một entry chỉ được coi là ĐỌC ĐƯỢC khi
# có ít nhất một field trong đây (hoặc một `condition` đọc được).
_NUMERIC_DAY_FIELDS = (
    "maxtemp_c",
    "mintemp_c",
    "daily_chance_of_rain",
    "maxwind_kph",
    "uv",
)


def _day_is_readable(day: dict[str, Any]) -> bool:
    """Entry dự báo có số liệu thật để hiển thị hay không."""
    if any(_val(day, field, None) is not None for field in _NUMERIC_DAY_FIELDS):
        return True
    return _condition(day) != "không rõ"


def _format_forecast(data: object, days: int) -> str:
    """Định dạng dự báo. KHÔNG crash, và KHÔNG báo thành công khi thiếu ngày.

    Bug cũ: `forecast["forecastday"]` chỉ được kiểm tra "truthy". Nếu nó là một
    dict/chuỗi (sai kiểu) thì vòng lặp chạy qua key/ký tự, mọi entry bị `continue`,
    và hàm trả về **chỉ mỗi dòng tiêu đề** — tức là báo thành công với dự báo rỗng.
    """
    if not isinstance(data, dict):
        return "❌ WeatherAPI trả về dữ liệu dự báo sai cấu trúc (không phải object)."

    forecast = data.get("forecast")
    if not isinstance(forecast, dict):
        return "❌ WeatherAPI trả về dữ liệu thiếu mục 'forecast.forecastday'."

    raw_days = forecast.get("forecastday")
    if not isinstance(raw_days, list) or not raw_days:
        return "❌ WeatherAPI trả về dữ liệu thiếu mục 'forecast.forecastday'."

    blocks = [f"Dự báo {days} ngày tới tại {_place(data.get('location'))}:"]
    for entry in raw_days:
        if not isinstance(entry, dict):
            continue
        day = entry.get("day")
        if not isinstance(day, dict):
            continue
        # Entry không có số liệu thật nào thì KHÔNG được tạo block "toàn không rõ"
        # — làm vậy là báo thành công cho dữ liệu không hợp lệ.
        if not _day_is_readable(day):
            continue
        blocks.append(
            "\n".join(
                [
                    f"\nNgày {_val(entry, 'date')}:",
                    f"- Cao nhất / thấp nhất: {_val(day, 'maxtemp_c')}°C / "
                    f"{_val(day, 'mintemp_c')}°C",
                    f"- Tình trạng: {_condition(day)}",
                    f"- Khả năng mưa: {_val(day, 'daily_chance_of_rain')}%",
                    f"- Gió mạnh nhất: {_val(day, 'maxwind_kph')} km/h",
                    f"- Chỉ số UV: {_val(day, 'uv')}",
                ]
            )
        )

    if len(blocks) == 1:
        # Không ngày nào dùng được → đây là dữ liệu KHÔNG hợp lệ, phải báo lỗi.
        return (
            "❌ WeatherAPI trả về dữ liệu dự báo không hợp lệ "
            "(không có ngày nào đọc được)."
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
    transport = current_transport()
    # Endpoint chỉ có ý nghĩa với transport HTTP. Ở chế độ stdio, báo null thay vì
    # bịa ra một URL HTTP mà server không hề mở.
    if transport == "streamable-http":
        endpoint: str | None = f"http://{HOST}:{PORT}/mcp"
    elif transport == "sse":
        endpoint = f"http://{HOST}:{PORT}/sse"
    else:
        endpoint = None

    return json.dumps(
        {
            "status": "ok",
            "server": "weather-mcp",
            # Transport THẬT đang phục vụ, không phải hằng số hard-code.
            "transport": transport,
            "host": HOST,
            "port": PORT,
            "endpoint": endpoint,
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


# Transport THỰC TẾ đang phục vụ. Đặt trong `__main__` ngay trước `mcp.run()`.
# `health_check()` đọc biến này thay vì hard-code — trước đây server chạy stdio
# vẫn báo "streamable-http", tức là health_check nói sai sự thật.
ACTIVE_TRANSPORT: str | None = None


def set_active_transport(transport: str) -> None:
    """Ghi nhận transport đang thực sự phục vụ (gọi từ `__main__`)."""
    global ACTIVE_TRANSPORT
    ACTIVE_TRANSPORT = transport


def current_transport() -> str:
    """Transport đang phục vụ; nếu chưa khởi động thì suy ra từ cấu hình."""
    if ACTIVE_TRANSPORT:
        return ACTIVE_TRANSPORT
    try:
        return resolve_transport()
    except SystemExit:
        # MCP_TRANSPORT sai → server sẽ thoát lúc khởi động, không có transport.
        return "unknown"


if __name__ == "__main__":
    transport = resolve_transport()
    set_active_transport(transport)
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
