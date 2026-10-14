"""Weather Agent — Google ADK + MCP Server (Streamable HTTP).

Agent này KHÔNG hard-code tool nào. Nó cấu hình `McpToolset` trỏ tới MCP
server; ADK sẽ tự `list_tools` tại runtime và đưa danh sách tool cho Gemini.

⚠️ LƯU Ý QUAN TRỌNG VỀ KẾT NỐI (đã kiểm chứng):
    `McpToolset(...)` KHÔNG kết nối tới server. Nó chỉ ghi nhớ cấu hình;
    kết nối thật xảy ra khi ADK gọi `get_tools()` / chạy tool lần đầu.
    Vì vậy file này KHÔNG in "kết nối thành công" — làm vậy là nói dối.
    Muốn xác minh kết nối thật, chạy: `uv run python verify_setup.py`.

Cách chạy:
    cd 04-lab/mcp-client
    uv sync
    # .env cần GOOGLE_API_KEY (và MCP_SERVER_URL nếu server không ở localhost:8085)
    uv run adk web         # rồi mở http://localhost:8000
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Console Windows mặc định cp1252 → ép UTF-8 trước khi log tiếng Việt / import ADK.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

# ⚠️ `parents[N]` cố định rất dễ vỡ nếu layout thay đổi (IndexError). Dùng
# `parents[1]` ở đây là an toàn trong repo này (agent.py luôn nằm trong
# mcp-client/weather_agent/), nhưng REPO_ROOT thì lấy từ `env_setup` — nơi tìm
# gốc repo bằng DẤU HIỆU thay vì đếm cấp thư mục.
CLIENT_DIR = Path(__file__).resolve().parents[1]

# `env_setup.py` nằm ở gốc mcp-client (dùng chung với verify_setup.py).
if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))

import env_setup  # noqa: E402
from env_setup import google_api_key, load_environment  # noqa: E402

REPO_ROOT = env_setup.REPO_ROOT
LOADED_ENV_FILES = load_environment()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("weather_agent")

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8085/mcp")
MCP_TIMEOUT = float(os.getenv("MCP_TIMEOUT", "30"))
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

INSTRUCTION = """Bạn là trợ lý thời tiết, LUÔN trả lời bằng tiếng Việt.

QUY TẮC BẮT BUỘC:
1. Mọi số liệu thời tiết (nhiệt độ, độ ẩm, gió, dự báo, tình trạng) CHỈ được
   lấy từ kết quả của các tool MCP: get_current_weather, get_forecast.
   TUYỆT ĐỐI không tự bịa, không đoán, không lấy từ trí nhớ.
2. Khi người dùng hỏi về thời tiết hiện tại hoặc dự báo, PHẢI gọi tool trước
   rồi mới trả lời.
3. Nếu tool trả về lỗi (bắt đầu bằng ❌) hoặc không có dữ liệu, hãy nói thật
   là chưa lấy được dữ liệu, nêu ngắn gọn lý do, và KHÔNG đưa ra con số thay thế.
4. `get_forecast` chỉ hỗ trợ 1 đến 3 ngày. Nếu người dùng yêu cầu số ngày
   ngoài khoảng đó (kể cả 0 hoặc số âm), hãy giải thích giới hạn này; không tự
   đổi thành số ngày khác.
5. Dùng `health_check` khi người dùng hỏi server/MCP còn hoạt động không.
6. Nếu người dùng hỏi về NHIỀU thành phố cùng lúc (ví dụ "so sánh thời tiết Hà Nội
   và TP. Hồ Chí Minh"), hãy gọi tool cho TỪNG thành phố đã được nêu tên rồi so
   sánh kết quả. KHÔNG hỏi lại khi tên thành phố đã rõ ràng trong câu hỏi.
7. Trình bày ngắn gọn, dễ đọc; có thể dùng emoji. Nêu rõ tên thành phố và
   thời điểm dữ liệu được cập nhật khi có.
"""


def _build_toolset():
    """Tạo McpToolset. Lỗi ở đây là lỗi CẤU HÌNH, không phải lỗi kết nối."""
    from google.adk.tools.mcp_tool.mcp_toolset import (
        McpToolset,
        StreamableHTTPConnectionParams,
    )

    connection_params = StreamableHTTPConnectionParams(
        url=MCP_SERVER_URL,
        # Mặc định của ADK là 5s — quá ngắn cho Cloud Run cold start.
        timeout=MCP_TIMEOUT,
        sse_read_timeout=float(os.getenv("MCP_SSE_READ_TIMEOUT", "300")),
    )
    return McpToolset(connection_params=connection_params, errlog=sys.stderr)


def _log_startup() -> None:
    logger.info("Khởi tạo weather agent")
    if LOADED_ENV_FILES:
        for path in LOADED_ENV_FILES:
            logger.info("  .env đã nạp: %s", path)
    else:
        logger.warning(
            "  Không tìm thấy .env nào (đã thử %s và %s)",
            CLIENT_DIR / ".env",
            REPO_ROOT / ".env",
        )
    logger.info("  MCP server: %s (timeout %.0fs)", MCP_SERVER_URL, MCP_TIMEOUT)
    logger.info("  Model: %s", GEMINI_MODEL)
    logger.info(
        "  GOOGLE_API_KEY: %s",
        f"đã có (nguồn: {env_setup.KEY_SOURCE})" if google_api_key() else "THIẾU",
    )


_log_startup()


def create_agent():
    """Tạo root_agent. Trả về (agent, mcp_enabled)."""
    from google.adk import Agent

    try:
        toolset = _build_toolset()
    except Exception as exc:  # noqa: BLE001 - lỗi cấu hình/import của ADK
        logger.error("❌ Không tạo được McpToolset: %s: %s", type(exc).__name__, exc)
        logger.warning(
            "⚠️  FALLBACK: agent chạy KHÔNG CÓ TOOL THỜI TIẾT. "
            "Agent sẽ không thể lấy dữ liệu thời tiết và phải nói rõ điều đó."
        )
        fallback_instruction = (
            "Bạn là trợ lý thời tiết, trả lời bằng tiếng Việt.\n"
            "HỆ THỐNG ĐANG KHÔNG CÓ TOOL THỜI TIẾT (kết nối MCP thất bại khi khởi tạo).\n"
            "Bạn PHẢI nói rõ là hiện không lấy được dữ liệu thời tiết và đề nghị người "
            "dùng kiểm tra MCP server. TUYỆT ĐỐI không bịa số liệu thời tiết."
        )
        return (
            Agent(
                name="weather_agent",
                model=GEMINI_MODEL,
                description="Trợ lý thời tiết (CHẾ ĐỘ FALLBACK — không có tool).",
                instruction=fallback_instruction,
            ),
            False,
        )

    logger.info(
        "✅ McpToolset đã được cấu hình (kết nối LAZY — tool chỉ được khám phá "
        "khi ADK dùng lần đầu). Chưa xác minh server đang chạy; chạy "
        "`uv run python verify_setup.py` để kiểm tra thật."
    )
    agent = Agent(
        name="weather_agent",
        model=GEMINI_MODEL,
        description="Trợ lý thời tiết dùng tool từ MCP server qua Streamable HTTP.",
        instruction=INSTRUCTION,
        tools=[toolset],
    )
    return agent, True


root_agent, MCP_TOOLS_ENABLED = create_agent()
