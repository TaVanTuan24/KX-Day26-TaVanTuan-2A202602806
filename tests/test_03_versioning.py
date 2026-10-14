"""Integration test cho 03-production/versioned_server.py + versioned_client.py.

Chạy MCP server THẬT qua stdio và chứng minh BACKWARD COMPATIBILITY:
tool v1 cũ vẫn hoạt động y như trước, trong khi v2 có thêm tính năng.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .conftest import REPO_ROOT

SERVER_PATH = REPO_ROOT / "03-production" / "versioned_server.py"


def _text(result: object) -> str:
    return "\n".join(getattr(b, "text", "") for b in (getattr(result, "content", None) or []))


def _is_error(result: object) -> bool:
    return bool(getattr(result, "is_error", getattr(result, "isError", False)))


def run_session(scenario):
    async def runner():
        params = StdioServerParameters(command=sys.executable, args=[str(SERVER_PATH)])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await scenario(session)

    return asyncio.run(runner())


# ─────────────────────────────────────────────────────────────────────────────
# 1. Server metadata — server://info
# ─────────────────────────────────────────────────────────────────────────────


def test_server_info_resource_publishes_version_and_deprecation():
    async def scenario(session):
        info = await session.read_resource("server://info")
        return json.loads(info.contents[0].text)

    meta = run_session(scenario)
    assert meta["name"] == "weather-v2"
    assert meta["version"] == "2.0.0"
    assert meta["deprecated_tools"] == ["get_weather"]
    assert set(meta["tools"]) == {"get_weather", "get_weather_v2"}
    assert meta["migration_guide"]


def test_list_tools_exposes_both_versions():
    async def scenario(session):
        return await session.list_tools()

    tools = run_session(scenario)
    names = sorted(t.name for t in tools.tools)
    assert names == ["get_weather", "get_weather_v2"]

    v1 = next(t for t in tools.tools if t.name == "get_weather")
    v2 = next(t for t in tools.tools if t.name == "get_weather_v2")
    assert "v1" in v1.description and "Deprecated" in v1.description
    assert "v2" in v2.description

    v2_schema = getattr(v2, "input_schema", None) or getattr(v2, "inputSchema", {})
    assert v2_schema["required"] == ["city"]
    assert set(v2_schema["properties"]) == {"city", "include_forecast", "units"}


# ─────────────────────────────────────────────────────────────────────────────
# 2. Tool v1 — hợp đồng cũ không đổi
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("city", "expected"),
    [
        ("Hanoi", "Hanoi: 29°C, trời mưa"),
        ("Danang", "Danang: 30°C, nhiều mây"),
        ("hanoi", "hanoi: 29°C, trời mưa"),
    ],
)
def test_v1_output_is_unchanged_plain_string(city, expected):
    async def scenario(session):
        return await session.call_tool("get_weather", {"city": city})

    result = run_session(scenario)
    assert _is_error(result) is False
    assert _text(result) == expected


def test_v1_unknown_city_fallback_unchanged():
    async def scenario(session):
        return await session.call_tool("get_weather", {"city": "Atlantis"})

    assert _text(run_session(scenario)) == "Atlantis: 28°C, không có dữ liệu chi tiết"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Tool v2 — tham số optional có default hợp lệ
# ─────────────────────────────────────────────────────────────────────────────


def test_v2_with_only_required_argument_uses_defaults():
    async def scenario(session):
        return await session.call_tool("get_weather_v2", {"city": "Danang"})

    result = run_session(scenario)
    assert _is_error(result) is False
    payload = json.loads(_text(result))
    assert payload["api_version"] == "2.0"
    assert payload["city"] == "Danang"
    assert payload["units"] == "celsius"      # default của `units`
    assert payload["temp"] == 30
    assert "forecast" not in payload          # default của `include_forecast` là False


def test_v2_include_forecast_adds_forecast_list():
    async def scenario(session):
        return await session.call_tool(
            "get_weather_v2", {"city": "Hanoi", "include_forecast": True}
        )

    payload = json.loads(_text(run_session(scenario)))
    assert len(payload["forecast"]) == 2
    assert payload["forecast"][0]["day"] == "tomorrow"


def test_v2_fahrenheit_conversion():
    async def scenario(session):
        return await session.call_tool(
            "get_weather_v2", {"city": "Hanoi", "units": "fahrenheit"}
        )

    payload = json.loads(_text(run_session(scenario)))
    assert payload["units"] == "fahrenheit"
    assert payload["temp"] == pytest.approx(84.2, abs=0.1)  # 29°C → 84.2°F


@pytest.mark.parametrize("units", ["FAHRENHEIT", "Fahrenheit", " fahrenheit "])
def test_v2_units_is_case_and_space_insensitive(units):
    async def scenario(session):
        return await session.call_tool("get_weather_v2", {"city": "Hanoi", "units": units})

    payload = json.loads(_text(run_session(scenario)))
    assert payload["units"] == "fahrenheit"


@pytest.mark.parametrize("units", ["kelvin", "", "rankine", "C"])
def test_v2_invalid_units_returns_error_not_crash(units):
    async def scenario(session):
        return await session.call_tool("get_weather_v2", {"city": "Hanoi", "units": units})

    result = run_session(scenario)
    assert _is_error(result) is False, "đây là lỗi nghiệp vụ trong payload JSON"
    payload = json.loads(_text(result))
    assert "error" in payload
    assert payload["supported_units"] == ["celsius", "fahrenheit"]


def test_v2_unknown_city_returns_error_payload():
    async def scenario(session):
        return await session.call_tool("get_weather_v2", {"city": "Atlantis"})

    payload = json.loads(_text(run_session(scenario)))
    assert payload["error"] == "không có dữ liệu"


def test_v2_output_is_valid_json_with_expected_keys():
    async def scenario(session):
        return await session.call_tool(
            "get_weather_v2", {"city": "Hanoi", "include_forecast": True}
        )

    payload = json.loads(_text(run_session(scenario)))
    assert set(payload) >= {
        "api_version",
        "city",
        "temp",
        "units",
        "condition",
        "humidity",
        "wind_speed_kmh",
        "timestamp",
        "forecast",
    }
