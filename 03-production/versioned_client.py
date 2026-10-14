"""Client test cho versioned_server.py — gọi cả tool v1, v2 và đọc server metadata.

Script chứng minh BACKWARD COMPATIBILITY:
  - client cũ gọi `get_weather(city)` (v1) vẫn chạy
  - client mới gọi `get_weather_v2(city)` với tham số optional MẶC ĐỊNH vẫn chạy
  - `server://info` công bố version + tool deprecated

Cách chạy (chạy được từ bất kỳ thư mục nào):
    pip install -r ../requirements.txt
    python 03-production/versioned_client.py
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

SERVER_PATH = Path(__file__).resolve().parent / "versioned_server.py"


def _is_error(result: object) -> bool:
    return bool(getattr(result, "is_error", getattr(result, "isError", False)))


def _text(result: object) -> str:
    return "\n".join(getattr(b, "text", "") for b in (getattr(result, "content", None) or []))


async def main() -> int:
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER_PATH)])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. Đọc server metadata
            info = await session.read_resource("server://info")
            meta = json.loads(info.contents[0].text)
            print(f"Server: {meta['name']} v{meta['version']}")
            print(f"Tools: {meta['tools']}")
            print(f"Deprecated tools: {meta['deprecated_tools']}")
            print(f"Migration: {meta['migration_guide']}\n")

            # 2. Liệt kê tools
            tools = await session.list_tools()
            print("Tools:")
            for tool in tools.tools:
                print(f"  - {tool.name}: {tool.description}")
            print()

            # 3. Gọi tool v1 (deprecated nhưng vẫn hoạt động — backward compat)
            r1 = await session.call_tool("get_weather", {"city": "Hanoi"})
            print(f"[v1] get_weather('Hanoi')  is_error={_is_error(r1)}:")
            print(f"  {_text(r1)}\n")

            # 4. Gọi v2 với ĐẦY ĐỦ tham số
            r2 = await session.call_tool(
                "get_weather_v2",
                {"city": "Hanoi", "include_forecast": True, "units": "celsius"},
            )
            print("[v2] get_weather_v2('Hanoi', forecast=True, units='celsius'):")
            print(f"  {json.dumps(json.loads(_text(r2)), indent=2, ensure_ascii=False)}\n")

            # 5. Gọi v2 CHỈ với tham số bắt buộc → chứng minh default hợp lệ
            r3 = await session.call_tool("get_weather_v2", {"city": "Danang"})
            print("[v2] get_weather_v2('Danang')  ← chỉ tham số bắt buộc (default):")
            print(f"  {_text(r3)}\n")

            # 6. Đổi đơn vị
            r4 = await session.call_tool(
                "get_weather_v2", {"city": "Hanoi", "units": "fahrenheit"}
            )
            print("[v2] get_weather_v2('Hanoi', units='fahrenheit'):")
            print(f"  {_text(r4)}\n")

            # 7. Đơn vị không hợp lệ → lỗi có kiểm soát, không sập server
            r5 = await session.call_tool(
                "get_weather_v2", {"city": "Hanoi", "units": "kelvin"}
            )
            print("[v2] get_weather_v2('Hanoi', units='kelvin')  ← cố ý sai:")
            print(f"  {_text(r5)}\n")

    print("✅ v1 và v2 cùng hoạt động — backward compatibility được giữ.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
