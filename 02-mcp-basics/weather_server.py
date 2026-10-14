"""MCP SERVER minh hoạ — công bố tool `get_weather` qua giao thức MCP.

Khác với function calling: tool nằm ở một server ĐỘC LẬP. Server tự "khai
báo" tool của mình; bất kỳ MCP client nào (Claude Code, Claude Desktop,
Cursor, hoặc weather_client.py) cũng cắm vào dùng được mà không cần biết
code bên trong.

Schema của tool được TỰ ĐỘNG sinh ra từ type hints + docstring.

Chạy trực tiếp:
    pip install -r ../requirements.txt
    python weather_server.py

Đăng ký với Claude Code (làm 1 lần, dùng mãi):
    claude mcp add weather -- python /đường/dẫn/tới/weather_server.py

⚠️ QUAN TRỌNG: khi chạy qua transport stdio, **stdout là kênh truyền
JSON-RPC**. Tuyệt đối không `print()` ra stdout trong file này — mọi thông
báo phải đi ra `sys.stderr` (hoặc dùng logging) để không làm hỏng giao thức.
"""

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

mcp = MCPServer(
    "weather",
    version="1.0.0",
    instructions="MCP server demo cho bài Day 26 — chỉ trả dữ liệu thời tiết MOCK.",
    # Giảm log INFO của SDK (log đi ra stderr, không ảnh hưởng stdout của stdio).
    log_level="WARNING",
)

# Dữ liệu MOCK — key là tên thành phố đã chuẩn hoá (casefold).
_MOCK_DB = {
    "hanoi": "29°C, trời mưa",
    "haiphong": "33°C, mưa rào",
    "danang": "30°C, nhiều mây",
}


@mcp.tool()
def get_weather(city: str) -> str:
    """Lấy thời tiết hiện tại của một thành phố.

    Args:
        city: Tên thành phố, ví dụ Hanoi, Danang, Haiphong.
    """
    if not city.strip():
        # ToolError = lỗi NGHIỆP VỤ: server báo lỗi gọn gàng qua MCP (không
        # kèm traceback), client đọc được qua `is_error`. Dùng `ValueError`
        # thường cũng chạy, nhưng SDK sẽ log ERROR + traceback đầy đủ.
        raise ToolError("Tên thành phố không được để trống")

    key = city.strip().casefold()
    return f"{city}: {_MOCK_DB.get(key, '28°C, không có dữ liệu chi tiết')}"


if __name__ == "__main__":
    mcp.run()  # mặc định chạy qua stdio
