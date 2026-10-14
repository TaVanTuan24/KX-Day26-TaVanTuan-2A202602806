"""MCP Client có Authentication — kết nối tới auth_server.py qua HTTP.

Client tạo HTTP client bằng `create_mcp_http_client(headers=...)` của MCP SDK
(đúng thư viện HTTP mà SDK dùng bên dưới, kèm timeout khuyến nghị). Header
Authorization được gắn vào mọi request HTTP (POST, GET, DELETE) tới server.

Sau khi gọi tool thành công, script còn tự đo **status code thật** cho 4 tình
huống để chứng minh phân biệt authentication (401) và authorization (403)
thay vì giả định.

Cách chạy (cần auth_server.py đang chạy ở terminal khác):
    cd 03-production
    $env:PORT=8090; python auth_server.py       # terminal 1 (PowerShell)
    $env:MCP_SERVER_URL="http://127.0.0.1:8090/mcp"; python auth_client.py  # terminal 2

Biến môi trường:
    MCP_SERVER_URL  — mặc định http://127.0.0.1:8000/mcp
    MCP_AUTH_TOKEN  — mặc định dev-token-abc123

Ghi chú: cổng 8000 mặc định có thể bị chiếm bởi Docker Desktop trên Windows —
khi đó hãy đặt PORT/MCP_SERVER_URL sang cổng khác.
"""

from __future__ import annotations

import asyncio
import os
import sys

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp")
TOKEN = os.environ.get("MCP_AUTH_TOKEN", "dev-token-abc123")
REQUEST_TIMEOUT = 30.0

_INIT_PAYLOAD = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "day26-auth-client", "version": "1.0"},
    },
}


async def run_authenticated_session() -> None:
    """Kết nối MCP kèm bearer token, khám phá và gọi tool."""
    # LƯU Ý (đã kiểm chứng bằng thực nghiệm): MCP SDK v2 dùng **httpx2**, không
    # phải httpx. Truyền `httpx.Timeout(...)` ở đây sẽ nổ
    # "TypeError: unsupported operand type(s) for +: 'float' and 'Timeout'".
    # Truyền số giây (float) hoặc httpx2.Timeout đều chạy đúng.
    http_client = create_mcp_http_client(
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=REQUEST_TIMEOUT,
    )

    async with http_client:
        async with streamable_http_client(SERVER_URL, http_client=http_client) as (
            read,
            write,
        ):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                server_info = getattr(init, "server_info", None) or getattr(
                    init, "serverInfo", None
                )
                print(f"✅ Xác thực thành công, đã bắt tay MCP: {server_info.name}")
                print(f"   (token: {TOKEN[:4]}…{TOKEN[-2:]}, không in đầy đủ)\n")

                tools = await session.list_tools()
                print("Tools (có auth):")
                for tool in tools.tools:
                    print(f"  - {tool.name}: {tool.description}")

                result = await session.call_tool("get_weather", {"city": "Hanoi"})
                text = "\n".join(
                    getattr(block, "text", "") for block in (result.content or [])
                )
                is_error = bool(
                    getattr(result, "is_error", getattr(result, "isError", False))
                )
                print(f"\n{'❌' if is_error else '✅'} call_tool get_weather('Hanoi'):")
                print(f"  -> {text}")


async def probe_status_codes() -> bool:
    """Đo status code THẬT cho từng tình huống auth/authz.

    Trả về True nếu tất cả khớp kỳ vọng.
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    cases: list[tuple[str, dict[str, str], int, str]] = [
        # (nhãn, header thêm, status kỳ vọng, ý nghĩa)
        ("không có token", {}, 401, "AUTHENTICATION thiếu → 401"),
        ("token sai", {"Authorization": "Bearer wrong-token"}, 401, "AUTHENTICATION sai → 401"),
        ("token hiệu lực, thiếu scope", {"Authorization": "Bearer demo-no-scope-token"}, 403, "AUTHORIZATION thiếu scope → 403"),
        ("token hợp lệ", {"Authorization": f"Bearer {TOKEN}"}, 200, "hợp lệ → 200"),
    ]

    ok = True
    print("\n--- Đo status code thật (không giả định) ---")
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        for label, extra, expected, meaning in cases:
            try:
                response = await client.post(
                    SERVER_URL, json=_INIT_PAYLOAD, headers={**headers, **extra}
                )
            except httpx.RequestError as exc:
                print(f"  ❓ {label}: không gọi được server ({exc})")
                ok = False
                continue

            mark = "✅" if response.status_code == expected else "❌"
            if response.status_code != expected:
                ok = False
            challenge = response.headers.get("www-authenticate") or ""
            print(f"  {mark} {label}: HTTP {response.status_code} (kỳ vọng {expected}) — {meaning}")
            if challenge:
                print(f"       WWW-Authenticate: {challenge[:110]}")
    return ok


async def main() -> int:
    print(f"Kết nối tới {SERVER_URL}\n")
    try:
        await run_authenticated_session()
    except Exception as exc:  # noqa: BLE001 - mọi lỗi kết nối đều cần hướng dẫn
        print(f"\n❌ Không kết nối được MCP server: {type(exc).__name__}: {exc}")
        print("   Kiểm tra: server đã chạy chưa? PORT/MCP_SERVER_URL có khớp không?")
        print("   Ví dụ:  cd 03-production")
        print('           $env:PORT=8090; python auth_server.py')
        print('           $env:MCP_SERVER_URL="http://127.0.0.1:8090/mcp"; python auth_client.py')
        return 1

    ok = await probe_status_codes()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
