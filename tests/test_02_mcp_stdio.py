"""Integration test cho 02-mcp-basics — chạy MCP server THẬT qua stdio.

Không mock gì cả: mỗi test spawn `weather_server.py` bằng chính interpreter
đang chạy test, bắt tay MCP rồi gọi tool. Đây là bằng chứng mạnh nhất cho
yêu cầu của Phase 3.
"""

from __future__ import annotations

import asyncio
import json
import queue
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .conftest import REPO_ROOT

SERVER_PATH = REPO_ROOT / "02-mcp-basics" / "weather_server.py"

EXPECTED_WEATHER = {
    "Hanoi": "Hanoi: 29°C, trời mưa",
    "Danang": "Danang: 30°C, nhiều mây",
    "Haiphong": "Haiphong: 33°C, mưa rào",
}


def _is_error(result: object) -> bool:
    return bool(getattr(result, "is_error", getattr(result, "isError", False)))


def _text(result: object) -> str:
    return "\n".join(
        getattr(block, "text", "") for block in (getattr(result, "content", None) or [])
    )


def _input_schema(tool: object) -> dict:
    return getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None) or {}


async def _with_session(scenario):
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER_PATH)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            return await scenario(session, init)


def run_session(scenario):
    """Chạy `scenario(session, init)` trong một MCP session thật."""
    return asyncio.run(_with_session(scenario))


# ─────────────────────────────────────────────────────────────────────────────
# 1. Initialize handshake
# ─────────────────────────────────────────────────────────────────────────────


def test_initialize_handshake():
    async def scenario(session, init):
        return init

    init = run_session(scenario)
    server_info = getattr(init, "server_info", None) or getattr(init, "serverInfo", None)
    assert server_info is not None
    assert server_info.name == "weather"
    assert server_info.version == "1.0.0"
    protocol = getattr(init, "protocol_version", None) or getattr(
        init, "protocolVersion", None
    )
    assert protocol, "server phải trả về protocolVersion"


# ─────────────────────────────────────────────────────────────────────────────
# 2. list_tools — schema sinh từ type hints + docstring
# ─────────────────────────────────────────────────────────────────────────────


def test_list_tools_exposes_get_weather():
    async def scenario(session, _init):
        return await session.list_tools()

    tools = run_session(scenario)
    names = [t.name for t in tools.tools]
    assert names == ["get_weather"]

    tool = tools.tools[0]
    assert "thời tiết" in tool.description.lower()

    schema = _input_schema(tool)
    assert schema["type"] == "object"
    assert schema["properties"]["city"]["type"] == "string"
    assert schema["required"] == ["city"]


# ─────────────────────────────────────────────────────────────────────────────
# 3. call_tool — 3 thành phố bắt buộc
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("city", "expected"), sorted(EXPECTED_WEATHER.items()))
def test_call_tool_returns_expected_text(city, expected):
    async def scenario(session, _init):
        return await session.call_tool("get_weather", {"city": city})

    result = run_session(scenario)
    assert _is_error(result) is False
    assert _text(result) == expected


def test_call_tool_is_case_insensitive():
    async def scenario(session, _init):
        return await session.call_tool("get_weather", {"city": "hAnOi"})

    result = run_session(scenario)
    assert _is_error(result) is False
    assert _text(result) == "hAnOi: 29°C, trời mưa"


def test_call_tool_unknown_city_falls_back():
    async def scenario(session, _init):
        return await session.call_tool("get_weather", {"city": "Atlantis"})

    result = run_session(scenario)
    assert _is_error(result) is False
    assert "không có dữ liệu chi tiết" in _text(result)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Tool error — client phải nhận được lỗi, không được crash
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("label", "tool_name", "args", "expected_fragment"),
    [
        ("thiếu tham số", "get_weather", {}, "validation error"),
        ("sai kiểu", "get_weather", {"city": 123}, "validation error"),
        ("tool lạ", "khong_ton_tai", {}, "Unknown tool"),
        ("nghiệp vụ", "get_weather", {"city": "   "}, "không được để trống"),
    ],
)
def test_tool_errors_are_reported_not_raised(label, tool_name, args, expected_fragment):
    async def scenario(session, _init):
        return await session.call_tool(tool_name, args)

    result = run_session(scenario)
    assert _is_error(result) is True, f"{label}: phải là tool error"
    assert expected_fragment.lower() in _text(result).lower()


# ─────────────────────────────────────────────────────────────────────────────
# 5. stdout của server chỉ được chứa JSON-RPC (không bị print() làm hỏng)
# ─────────────────────────────────────────────────────────────────────────────


def _readline_with_timeout(stream, timeout: float = 15.0) -> str | None:
    """Windows không select() được trên pipe → dùng thread + queue."""
    box: queue.Queue[str | None] = queue.Queue()

    def reader() -> None:
        box.put(stream.readline())

    threading.Thread(target=reader, daemon=True).start()
    try:
        return box.get(timeout=timeout)
    except queue.Empty:
        return None


def test_stdio_stdout_carries_only_jsonrpc():
    """Nói chuyện RAW bằng JSON-RPC trên stdout/stdin (không qua SDK client).

    Nếu server lỡ `print()` bất cứ thứ gì ra stdout, một dòng sẽ không parse
    được thành JSON và test này fail.
    """
    proc = subprocess.Popen(
        [sys.executable, str(SERVER_PATH)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.stdin and proc.stdout
    try:
        requests = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "day26-test", "version": "1.0"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "get_weather", "arguments": {"city": "Hanoi"}},
            },
        ]
        for message in requests:
            proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()

        responses: dict[int, dict] = {}
        raw_lines: list[str] = []
        while len(responses) < 3:
            line = _readline_with_timeout(proc.stdout)
            if line is None:
                break
            raw_lines.append(line)
            assert line.strip(), "stdout có dòng rỗng — dấu hiệu bị print() xen vào"
            payload = json.loads(line)  # ← throw nếu stdout bị bẩn
            assert payload.get("jsonrpc") == "2.0"
            if "id" in payload:
                responses[payload["id"]] = payload

        assert set(responses) == {1, 2, 3}, f"thu được: {sorted(responses)}"
        assert responses[1]["result"]["serverInfo"]["name"] == "weather"

        tool_names = [t["name"] for t in responses[2]["result"]["tools"]]
        assert tool_names == ["get_weather"]
        assert (
            responses[2]["result"]["tools"][0]["inputSchema"]["required"] == ["city"]
        )

        call_result = responses[3]["result"]
        assert call_result.get("isError", False) is False
        assert call_result["content"][0]["text"] == "Hanoi: 29°C, trời mưa"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()
            proc.wait(timeout=10)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()
