"""Nạp cấu hình môi trường cho Weather Agent — MỘT nguồn sự thật duy nhất.

Vấn đề thực tế đã gặp: `.env` của repo đặt tên khoá là `GEMINI_API_KEY`
(giống module 01), nhưng Google ADK và google-genai chỉ đọc `GOOGLE_API_KEY`.
Nếu không chuẩn hoá, agent khởi động với "GOOGLE_API_KEY: THIẾU" dù người dùng
đã điền key — đúng kiểu lỗi cấu hình âm thầm.

Module này được cả `weather_agent/agent.py` và `verify_setup.py` dùng chung,
nên README và thực tế không thể lệch nhau về vị trí `.env`.

Thứ tự ưu tiên (cái nạp TRƯỚC thắng, vì load_dotenv dùng override=False):
    1. 04-lab/mcp-client/.env      ← vị trí README yêu cầu
    2. <repo root>/.env            ← tiện khi cả repo dùng chung một .env
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

CLIENT_DIR = Path(__file__).resolve().parent          # .../04-lab/mcp-client


def find_repo_root(start: Path) -> Path:
    """Tìm thư mục gốc repo bằng DẤU HIỆU, không đếm số cấp thư mục.

    Đếm cấp (`parents[3]`) rất dễ vỡ: chỉ cần chạy ở layout nông hơn là ném
    `IndexError`. Cách này chịu được mọi độ sâu.
    """
    for candidate in (start, *start.parents):
        if (candidate / "requirements.txt").is_file() or (candidate / ".git").exists():
            return candidate
    return start


REPO_ROOT = find_repo_root(CLIENT_DIR)
ENV_CANDIDATES = (CLIENT_DIR / ".env", REPO_ROOT / ".env")

# Các tên hợp lệ cho cùng một khoá Gemini API.
KEY_ALIASES = ("GOOGLE_API_KEY", "GEMINI_API_KEY")

# Tên biến đã cung cấp khoá API (để log minh bạch nguồn cấu hình).
KEY_SOURCE: str | None = None


def apply_key_alias() -> str | None:
    """Đồng bộ alias khoá API. Trả về tên biến đã cung cấp khoá (hoặc None).

    Idempotent: gọi nhiều lần vẫn cho cùng `KEY_SOURCE`. Nếu không "ghim"
    nguồn gốc, lần gọi thứ hai sẽ thấy GOOGLE_API_KEY (do chính alias tạo ra)
    và báo sai nguồn cấu hình.
    """
    global KEY_SOURCE
    present = [name for name in KEY_ALIASES if (os.getenv(name) or "").strip()]
    if not present:
        KEY_SOURCE = None
        return None

    value = os.environ[present[0]].strip()
    for other in KEY_ALIASES:
        if other not in present:
            os.environ[other] = value

    if KEY_SOURCE is None:
        KEY_SOURCE = present[0]
    return KEY_SOURCE


def load_environment() -> list[Path]:
    """Nạp .env theo thứ tự ưu tiên rồi chuẩn hoá alias khoá API.

    Trả về danh sách file .env đã nạp.
    """
    loaded: list[Path] = []
    for candidate in ENV_CANDIDATES:
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            loaded.append(candidate)
    apply_key_alias()
    return loaded


def google_api_key() -> str | None:
    """Khoá Gemini hiện có (đã chuẩn hoá), hoặc None."""
    for name in KEY_ALIASES:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return None
