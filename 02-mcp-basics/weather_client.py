"""MCP CLIENT minh hoạ — kết nối tới weather_server.py qua giao thức MCP.

Điểm mấu chốt: client KHÔNG hard-code tool. Nó hỏi server "anh có tool gì?"
(list_tools) tại runtime, rồi gọi tool (call_tool) để SERVER thực thi và trả
kết quả về qua MCP.

Ví dụ này không cần API key của model nào — nó cho thấy lớp giao thức MCP hoạt
động độc lập với model. (Trong thực tế, một LLM sẽ dùng Function Calling để
quyết định khi nào gọi tool đã khám phá được.)

Cách chạy (client tự khởi động server, chạy được từ bất kỳ thư mục nào):
    pip install -r ../requirements.txt
    python 02-mcp-basics/weather_client.py

Ghi chú portability:
    - Console Windows mặc định là cp1252 → ép stdout/stderr sang UTF-8 để in
      được tiếng Việt (nếu không sẽ UnicodeEncodeError).
    - Đường dẫn server lấy từ `__file__`, không phụ thuộc thư mục hiện hành.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SERVER_PATH = Path(__file__).resolve().parent / "weather_server.py"


def _is_error(result: object) -> bool:
    """mcp 2.x dùng `is_error`, mcp 1.x dùng `isError` — chấp nhận cả hai."""
    return bool(getattr(result, "is_error", getattr(result, "isError", False)))


def _result_text(result: object) -> str:
    blocks = getattr(result, "content", None) or []
    texts = []
    for block in blocks:
        text = getattr(block, "text", None)
        texts.append(text if text is not None else f"<{type(block).__name__}>")
    return "\n".join(texts) if texts else "(không có nội dung)"


def _input_schema(tool: object) -> dict:
    return getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None) or {}


async def main() -> int:
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER_PATH)])
    failures = 0

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            # 0. BẮT TAY (initialize handshake)
            init = await session.initialize()
            server_info = getattr(init, "server_info", None) or getattr(
                init, "serverInfo", None
            )
            protocol = getattr(init, "protocol_version", None) or getattr(
                init, "protocolVersion", "?"
            )
            print(f"✅ Bắt tay MCP thành công: {server_info.name} v{server_info.version}")
            print(f"   protocolVersion: {protocol}\n")

            # 1. KHÁM PHÁ tool mà server công bố (không hard-code)
            tools = await session.list_tools()
            print("Tools server cung cấp:")
            for tool in tools.tools:
                schema = _input_schema(tool)
                print(f"  - {tool.name}: {tool.description}")
                print(f"      schema tự sinh: {json.dumps(schema, ensure_ascii=False)}")
            if not tools.tools:
                print("  (không có tool nào!)")
                failures += 1

            # 2. Gọi tool — SERVER thực thi rồi trả kết quả về qua MCP
            for city in ["Hanoi", "Danang", "Haiphong"]:
                result = await session.call_tool("get_weather", {"city": city})
                if _is_error(result):
                    failures += 1
                    print(f"\n❌ get_weather(city={city!r}) trả về lỗi:")
                else:
                    print(f"\n✅ call_tool get_weather(city={city!r}):")
                print(f"  -> {_result_text(result)}")

            # 3. XỬ LÝ TOOL ERROR — client không được sập khi server báo lỗi
            print("\n--- Kiểm tra xử lý lỗi (các lỗi này là CỐ Ý) ---")
            bad_calls = [
                ("thiếu tham số bắt buộc", "get_weather", {}),
                ("sai kiểu tham số", "get_weather", {"city": 123}),
                ("tool không tồn tại", "khong_ton_tai", {}),
                ("vi phạm nghiệp vụ (city rỗng)", "get_weather", {"city": "   "}),
            ]
            for label, name, args in bad_calls:
                try:
                    result = await session.call_tool(name, args)
                    first_line = _result_text(result).strip().splitlines()[0][:110]
                    print(f"  [{label}] is_error={_is_error(result)}")
                    print(f"      {first_line}")
                except Exception as exc:  # noqa: BLE001 - lỗi giao thức cũng phải bắt
                    print(f"  [{label}] RAISED {type(exc).__name__}: {exc}")

    print()
    if failures:
        print(f"❌ Có {failures} lời gọi tool thất bại.")
        return 1
    print("✅ Tất cả lời gọi tool đều thành công.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
