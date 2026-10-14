"""Cấu hình chung cho test suite của Day 26.

Test chạy bằng venv ở thư mục gốc repo (`.venv`) — môi trường này có
`mcp` 2.x + `google-genai` theo `requirements.txt`.

Lab 04 có test riêng trong `04-lab/*/tests/` vì dùng môi trường `uv` độc lập
(`mcp` 1.x + `google-adk`).

Quy ước: KHÔNG dùng pytest-asyncio. Test async được gói trong `asyncio.run()`
để tránh xung đột event loop với anyio của MCP SDK.
"""

from __future__ import annotations

import importlib.util
import socket
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_DIRS = [
    REPO_ROOT / "01-function-calling",
    REPO_ROOT / "02-mcp-basics",
    REPO_ROOT / "03-production",
]

for _dir in MODULE_DIRS:
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))


def load_module(path: Path, name: str) -> ModuleType:
    """Nạp một file .py bất kỳ (kể cả trong thư mục tên không hợp lệ)."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(f"Không nạp được module từ {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


def free_port() -> int:
    """Xin một cổng TCP trống từ OS (tránh trùng cổng khi chạy song song)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def venv_python() -> str:
    """Đường dẫn interpreter đang chạy test."""
    return sys.executable
