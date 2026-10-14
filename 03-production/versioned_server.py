"""MCP Server có Versioning — minh hoạ backward compatibility.

Khi tool thay đổi schema (thêm/bớt tham số, đổi kiểu trả về), client cũ
sẽ bị break nếu không có chiến lược versioning. Ví dụ này minh hoạ 3 kỹ thuật:

  1. Tool mới song song (get_weather_v2) — giữ tool cũ cho client legacy
  2. Tham số optional với default — thêm tính năng mà không break client cũ
  3. Server version trong metadata — client kiểm tra version trước khi gọi

Cách chạy:
    pip install -r ../requirements.txt
    python versioned_server.py

⚠️ Chạy qua stdio: stdout là kênh JSON-RPC, không `print()` ra stdout.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from mcp.server.mcpserver import MCPServer

SERVER_VERSION = "2.0.0"
SUPPORTED_UNITS = ("celsius", "fahrenheit")

mcp = MCPServer(
    "weather-v2",
    version=SERVER_VERSION,
    instructions=f"Weather MCP Server v{SERVER_VERSION}. "
    "Hỗ trợ get_weather (v1, backward compat) và get_weather_v2 (chi tiết hơn).",
    log_level="WARNING",
)

# Key đã chuẩn hoá (casefold) để "Hanoi"/"hanoi" đều khớp.
_MOCK_DB: dict[str, dict] = {
    "hanoi": {
        "temp": 29,
        "condition": "trời mưa",
        "humidity": 82,
        "wind_speed": 12,
        "forecast": [
            {"day": "tomorrow", "temp": 27, "condition": "mưa nhẹ"},
            {"day": "day_after", "temp": 31, "condition": "nắng"},
        ],
    },
    "danang": {
        "temp": 30,
        "condition": "nhiều mây",
        "humidity": 78,
        "wind_speed": 10,
        "forecast": [
            {"day": "tomorrow", "temp": 32, "condition": "nắng"},
            {"day": "day_after", "temp": 29, "condition": "mưa rào"},
        ],
    },
}

DEPRECATED_TOOLS = ["get_weather"]


def _lookup(city: str) -> dict | None:
    if not isinstance(city, str):
        return None
    return _MOCK_DB.get(city.strip().casefold())


# ── Tool v1 (giữ nguyên cho backward compatibility) ──────────────────
@mcp.tool()
def get_weather(city: str) -> str:
    """[v1] Lấy thời tiết hiện tại — trả chuỗi đơn giản. Deprecated, dùng get_weather_v2."""
    data = _lookup(city)
    if data:
        return f"{city}: {data['temp']}°C, {data['condition']}"
    return f"{city}: 28°C, không có dữ liệu chi tiết"


# ── Tool v2 (thêm tính năng, không break v1) ─────────────────────────
@mcp.tool()
def get_weather_v2(
    city: str,
    include_forecast: bool = False,
    units: str = "celsius",
) -> str:
    """[v2] Lấy thời tiết chi tiết — JSON, hỗ trợ forecast và đơn vị đo.

    Args:
        city: Tên thành phố (ví dụ: Hanoi, Danang)
        include_forecast: Có trả thêm dự báo 2 ngày tới không (mặc định: False)
        units: Đơn vị nhiệt độ — "celsius" hoặc "fahrenheit" (mặc định: celsius)
    """
    normalized_units = units.strip().lower() if isinstance(units, str) else units
    if normalized_units not in SUPPORTED_UNITS:
        return json.dumps(
            {
                "city": city,
                "error": f"units không hợp lệ: {units!r}",
                "supported_units": list(SUPPORTED_UNITS),
                "api_version": "2.0",
            },
            ensure_ascii=False,
        )

    data = _lookup(city)
    if not data:
        return json.dumps(
            {"city": city, "error": "không có dữ liệu", "api_version": "2.0"},
            ensure_ascii=False,
        )

    temp = data["temp"]
    if normalized_units == "fahrenheit":
        temp = round(temp * 9 / 5 + 32, 1)

    result: dict = {
        "api_version": "2.0",
        "city": city,
        "temp": temp,
        "units": normalized_units,
        "condition": data["condition"],
        "humidity": data["humidity"],
        "wind_speed_kmh": data["wind_speed"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if include_forecast:
        result["forecast"] = data["forecast"]

    return json.dumps(result, ensure_ascii=False)


# ── Resource: server metadata (client dùng để kiểm tra version) ──────
@mcp.resource("server://info")
def server_info() -> str:
    """Metadata của server — version, supported tools, deprecation notices."""
    return json.dumps(
        {
            "name": "weather-v2",
            "version": SERVER_VERSION,
            "tools": ["get_weather", "get_weather_v2"],
            "deprecated_tools": DEPRECATED_TOOLS,
            "migration_guide": "Chuyển từ get_weather sang get_weather_v2. "
            "Tham số 'city' giữ nguyên, thêm include_forecast và units.",
        },
        ensure_ascii=False,
    )


if __name__ == "__main__":
    mcp.run()
