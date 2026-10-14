"""Integration test transport cho 04-lab/mcp-server/weather.py.

Kiểm tra MCP THẬT qua cả hai transport:
  - stdio            (server do client spawn)
  - streamable-http  (server chạy như tiến trình riêng, đúng như production)

Và kiểm tra stdout của server sạch JSON-RPC (không bị print() làm hỏng).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from queue import Queue

import httpx
import pytest

from conftest import SERVER_DIR, free_port

SERVER_SCRIPT = SERVER_DIR / "weather.py"
EXPECTED_TOOLS = {"get_current_weather", "get_forecast", "health_check"}


def _base_env(**extra: str) -> dict[str, str]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    env.pop("WEATHERAPI_KEY", None)
    env.update(extra)
    return env


@contextmanager
def spawn_server(**extra_env: str):
    """Chạy weather.py như tiến trình con, tự dọn dẹp."""
    proc = subprocess.Popen(
        [sys.executable, str(SERVER_SCRIPT)],
        cwd=str(SERVER_DIR),
        env=_base_env(**extra_env),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()
            proc.wait(timeout=10)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()


def _wait_for_http(url: str, timeout: float = 45.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
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
            return True
        except httpx.RequestError:
            time.sleep(0.5)
    return False


def _tool_names(tools) -> set[str]:
    return {t.name for t in tools.tools}


def _text(result) -> str:
    return "\n".join(getattr(b, "text", "") for b in (result.content or []))


# ─────────────────────────────────────────────────────────────────────────────
# 1. Transport stdio
# ─────────────────────────────────────────────────────────────────────────────


def test_stdio_lists_tools_and_calls_health_check():
    async def scenario():
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=sys.executable,
            args=[str(SERVER_SCRIPT)],
            env=_base_env(MCP_TRANSPORT="stdio"),
            cwd=str(SERVER_DIR),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                health = await session.call_tool("health_check", {})
                return tools, health

    tools, health = asyncio.run(scenario())
    assert _tool_names(tools) == EXPECTED_TOOLS

    payload = json.loads(_text(health))
    assert payload["status"] == "ok"
    # Regression: server chạy stdio thì health_check PHẢI báo stdio, không được
    # hard-code "streamable-http".
    assert payload["transport"] == "stdio", (
        f"health_check nói sai transport khi chạy stdio: {payload['transport']}"
    )
    assert payload["endpoint"] is None, "stdio không có endpoint HTTP"
    # KHÔNG khẳng định key phải là False: server nay tự nạp `.env` nên trạng thái
    # key phụ thuộc môi trường chạy. Hành vi "không có key thì báo False" được
    # kiểm chứng riêng ở tests/test_weather_tools.py::test_health_check_without_key.
    assert isinstance(payload["weatherapi_key_configured"], bool)
    assert payload["max_forecast_days"] == 3


def test_dotenv_next_to_server_is_loaded_when_present(weather):
    """Tính năng `.env`: server nạp file `.env` cạnh nó và công bố ra LOADED_ENV_FILES."""
    from pathlib import Path

    env_path = Path(weather.__file__).resolve().parent / ".env"
    if not env_path.is_file():
        pytest.skip("không có 04-lab/mcp-server/.env để kiểm tra")

    loaded = [Path(p) for p in weather.LOADED_ENV_FILES]
    assert env_path in loaded, (
        f"có {env_path} nhưng không được nạp: {loaded}"
    )


def test_env_candidates_survive_shallow_container_path(weather):
    """Regression: trong Docker file nằm ở `/app/weather.py` (chỉ 2 parent).

    Bản đầu dùng thẳng `Path(__file__).resolve().parents[2]` → `IndexError: 2`
    → container chết ngay lúc khởi động. Bug này KHÔNG lộ ra khi chạy local vì
    đường dẫn trong repo đủ sâu.
    """
    from pathlib import Path

    candidates = weather._env_candidates(Path("/app/weather.py"))
    # KHÔNG so sánh đường dẫn tuyệt đối: trên Windows `resolve()` gắn thêm ổ đĩa
    # của thư mục hiện hành, nên `Path("/app/.env")` sẽ không bằng.
    assert len(candidates) == 1, (
        f"đường dẫn nông chỉ được có 1 ứng viên, nhận được {candidates}"
    )
    assert candidates[0].name == ".env"


def test_env_candidates_include_repo_root_when_deep_enough(weather):
    """Đường dẫn trong repo đủ sâu → phải có thêm ứng viên `.env` ở repo root."""
    from pathlib import Path

    module_file = Path(weather.__file__).resolve()
    candidates = weather._env_candidates(module_file)
    assert candidates[0] == module_file.parent / ".env"
    assert len(candidates) == 2, f"mong đợi 2 ứng viên, nhận được {candidates}"
    assert candidates[1] == module_file.parents[2] / ".env"


def test_stdio_out_of_range_days_never_calls_upstream():
    async def scenario():
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=sys.executable,
            args=[str(SERVER_SCRIPT)],
            env=_base_env(MCP_TRANSPORT="stdio", WEATHERAPI_KEY="test-key"),
            cwd=str(SERVER_DIR),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.call_tool("get_forecast", {"city": "Hanoi", "days": -2})

    text = _text(asyncio.run(scenario()))
    assert text.startswith("❌")
    assert "days" in text
    assert "WEATHERAPI" not in text  # chặn TRƯỚC khi gọi upstream


def test_stdio_stdout_is_pure_jsonrpc():
    """Nói chuyện RAW bằng JSON-RPC trên stdout: nếu server print() gì ra stdout,
    dòng đó sẽ không parse được thành JSON và test fail."""
    with spawn_server(MCP_TRANSPORT="stdio") as proc:
        assert proc.stdin and proc.stdout
        messages = [
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
        ]
        for message in messages:
            proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()

        responses: dict[int, dict] = {}
        while len(responses) < 2:
            line = _readline(proc.stdout)
            if line is None:
                break
            assert line.strip(), "stdout có dòng rỗng"
            payload = json.loads(line)  # ← nổ nếu stdout bị bẩn
            assert payload.get("jsonrpc") == "2.0"
            if "id" in payload:
                responses[payload["id"]] = payload

        assert set(responses) == {1, 2}, f"nhận được: {sorted(responses)}"
        names = {t["name"] for t in responses[2]["result"]["tools"]}
        assert names == EXPECTED_TOOLS


def _readline(stream, timeout: float = 20.0) -> str | None:
    box: Queue[str | None] = Queue()

    def reader() -> None:
        box.put(stream.readline())

    threading.Thread(target=reader, daemon=True).start()
    try:
        return box.get(timeout=timeout)
    except Exception:  # noqa: BLE001 - queue.Empty
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 2. Transport Streamable HTTP
# ─────────────────────────────────────────────────────────────────────────────


def test_http_transport_end_to_end(mock_weather_api):
    from conftest import CURRENT_PAYLOAD, FORECAST_PAYLOAD

    port = free_port()
    url = f"http://127.0.0.1:{port}/mcp"
    mock_weather_api.clear_requests()
    mock_weather_api.routes.clear()
    mock_weather_api.set("/v1/current.json", body=CURRENT_PAYLOAD)
    mock_weather_api.set("/v1/forecast.json", body=FORECAST_PAYLOAD)

    with spawn_server(
        PORT=str(port),
        HOST="127.0.0.1",
        WEATHERAPI_KEY="test-key",
        WEATHERAPI_BASE_URL=mock_weather_api.base_url,
    ) as proc:
        assert _wait_for_http(url), (
            "server không lên trong thời gian cho phép:\n" + proc.stderr.read()[:2000]
        )

        async def scenario():
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client

            async with streamable_http_client(url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    tools = await session.list_tools()
                    current = await session.call_tool(
                        "get_current_weather", {"city": "Hanoi"}
                    )
                    bad_days = await session.call_tool(
                        "get_forecast", {"city": "Hanoi", "days": -2}
                    )
                    forecast = await session.call_tool(
                        "get_forecast", {"city": "Hanoi", "days": 2}
                    )
                    health = await session.call_tool("health_check", {})
                    return init, tools, current, bad_days, forecast, health

        init, tools, current, bad_days, forecast, health = asyncio.run(scenario())

    assert init.serverInfo.name == "weather"
    assert _tool_names(tools) == EXPECTED_TOOLS

    # Dữ liệu thật (từ mock upstream) phải chảy qua MCP về client.
    current_text = _text(current)
    assert "29.0" in current_text and "Light rain" in current_text

    # days âm bị chặn tại server; upstream KHÔNG được nhận yêu cầu forecast nào
    # ngoài yêu cầu days=2 hợp lệ ở dưới.
    assert _text(bad_days).startswith("❌")
    assert "2026-10-15" in _text(forecast)
    assert "71" in _text(forecast)

    forecast_requests = [
        q for path, q in mock_weather_api.requests if path.endswith("/forecast.json")
    ]
    assert len(forecast_requests) == 1, "chỉ yêu cầu days=2 hợp lệ được gửi đi"
    assert forecast_requests[0]["days"] == ["2"]

    payload = json.loads(_text(health))
    assert payload["weatherapi_key_configured"] is True
    assert payload["transport"] == "streamable-http"
    assert payload["endpoint"].endswith("/mcp")


def test_http_endpoint_is_mcp_path_not_root():
    """Endpoint phải là /mcp (đúng như README), không phải '/'."""
    port = free_port()
    with spawn_server(PORT=str(port), HOST="127.0.0.1") as proc:
        assert _wait_for_http(f"http://127.0.0.1:{port}/mcp"), proc.stderr.read()[:1500]
        with httpx.Client(timeout=10.0) as client:
            response = client.get(f"http://127.0.0.1:{port}/")
        # '/' không phải endpoint MCP → phải là 404
        assert response.status_code == 404
