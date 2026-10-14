"""Integration test cho 03-production/auth_server.py + auth_client.py.

Server được chạy THẬT trong một tiến trình riêng trên cổng trống, rồi test đo
**status code thực tế**. Đây là câu trả lời có bằng chứng cho yêu cầu
"kiểm tra status code thực tế thay vì giả định luôn là 401 hoặc 403".

Kết quả đo được trên MCP SDK v2 (mcp 2.3.0):
    thiếu token                          → 401  error="invalid_token"
    token sai                            → 401  error="invalid_token"
    token đúng nhưng THIẾU SCOPE         → 403  error="insufficient_scope"
    token hợp lệ                         → 200
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

from .conftest import REPO_ROOT

AUTH_SERVER = REPO_ROOT / "03-production" / "auth_server.py"

DEV_TOKEN = "dev-token-abc123"
NO_SCOPE_TOKEN = "demo-no-scope-token"
BAD_TOKEN = "wrong-token-never-valid"

INIT_PAYLOAD = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "day26-test", "version": "1.0"},
    },
}
BASE_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _post(url: str, token: str | None) -> httpx.Response:
    headers = dict(BASE_HEADERS)
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(timeout=20.0) as client:
        return client.post(url, json=INIT_PAYLOAD, headers=headers)


@pytest.fixture(scope="module")
def auth_server(tmp_path_factory):
    """Chạy auth_server.py thật trên cổng trống, chờ tới khi sẵn sàng."""
    port = _free_port()
    url = f"http://127.0.0.1:{port}/mcp"
    log_path = tmp_path_factory.mktemp("authlog") / "server.log"

    # Ghim token demo để test không phụ thuộc biến môi trường của máy chạy.
    env = {
        **os.environ,
        "PORT": str(port),
        "PYTHONIOENCODING": "utf-8",
        "MCP_AUTH_TOKEN": DEV_TOKEN,
        "MCP_LIMITED_TOKEN": NO_SCOPE_TOKEN,
    }
    with open(log_path, "w", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            [sys.executable, str(AUTH_SERVER)],
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )

    server = SimpleNamespace(url=url, port=port, proc=proc, log_path=log_path)

    deadline = time.time() + 60
    ready = False
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        try:
            if _post(url, DEV_TOKEN).status_code == 200:
                ready = True
                break
        except httpx.RequestError:
            pass
        time.sleep(0.5)

    if not ready:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        pytest.fail(
            "auth_server.py không khởi động được trên cổng "
            f"{port}.\n--- log ---\n{log_path.read_text(encoding='utf-8')}"
        )

    yield server

    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:  # pragma: no cover
        proc.kill()
        proc.wait(timeout=10)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Status code thực tế
# ─────────────────────────────────────────────────────────────────────────────


def test_missing_token_is_401(auth_server):
    response = _post(auth_server.url, None)
    assert response.status_code == 401
    challenge = response.headers.get("www-authenticate", "")
    assert "invalid_token" in challenge
    assert "resource_metadata" in challenge


def test_invalid_token_is_401_not_403(auth_server):
    """README cũ ghi 'token sai → 403'. Thực tế MCP SDK v2 trả 401.

    RFC 6750: token không xác minh được là lỗi XÁC THỰC (401); 403 dành cho
    trường hợp đã xác thực nhưng THIẾU QUYỀN.
    """
    response = _post(auth_server.url, BAD_TOKEN)
    assert response.status_code == 401
    assert "invalid_token" in response.headers.get("www-authenticate", "")


def test_valid_token_is_200(auth_server):
    response = _post(auth_server.url, DEV_TOKEN)
    assert response.status_code == 200
    assert "result" in response.text


def test_valid_token_without_scope_is_403(auth_server):
    """AUTHORIZATION khác AUTHENTICATION: token xác thực đúng nhưng thiếu scope."""
    response = _post(auth_server.url, NO_SCOPE_TOKEN)
    assert response.status_code == 403
    challenge = response.headers.get("www-authenticate", "")
    assert "insufficient_scope" in challenge
    assert "weather:read" in challenge


def test_malformed_authorization_header_is_rejected(auth_server):
    headers = {**BASE_HEADERS, "Authorization": "Basic ZGV2OnRr"}
    with httpx.Client(timeout=20.0) as client:
        response = client.post(auth_server.url, json=INIT_PAYLOAD, headers=headers)
    assert response.status_code == 401


def test_get_without_token_is_401(auth_server):
    with httpx.Client(timeout=20.0) as client:
        response = client.get(auth_server.url, headers={"Accept": "text/event-stream"})
    assert response.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# 2. Phiên MCP đầy đủ có auth (initialize → list_tools → call_tool)
# ─────────────────────────────────────────────────────────────────────────────


def test_authenticated_mcp_session_end_to_end(auth_server):
    async def scenario():
        http_client = create_mcp_http_client(
            headers={"Authorization": f"Bearer {DEV_TOKEN}"}, timeout=30.0
        )
        async with http_client:
            async with streamable_http_client(
                auth_server.url, http_client=http_client
            ) as (read, write):
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    tools = await session.list_tools()
                    result = await session.call_tool(
                        "get_weather", {"city": "Hanoi"}
                    )
                    return init, tools, result

    init, tools, result = asyncio.run(scenario())

    server_info = getattr(init, "server_info", None) or getattr(init, "serverInfo", None)
    assert server_info.name == "weather-secure"
    assert [t.name for t in tools.tools] == ["get_weather"]

    is_error = bool(getattr(result, "is_error", getattr(result, "isError", False)))
    assert is_error is False
    text = result.content[0].text
    assert text == "Hanoi: 29°C, trời mưa"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Token không được xuất hiện trong log
# ─────────────────────────────────────────────────────────────────────────────


def test_tokens_never_appear_in_server_log(auth_server):
    log = auth_server.log_path.read_text(encoding="utf-8")
    assert BAD_TOKEN not in log, "token sai bị ghi nguyên văn vào log"
    assert DEV_TOKEN not in log, "token hợp lệ bị ghi vào log"
    assert NO_SCOPE_TOKEN not in log, "token thiếu scope bị ghi vào log"
    # Nhưng phải có dấu vết ĐÃ che, để còn debug được.
    assert "từ chối token" in log
    assert "wrong" not in log  # phần đầu token sai cũng đã bị cắt
