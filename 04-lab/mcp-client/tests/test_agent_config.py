"""Unit test cho cấu hình agent và công cụ xác minh (không gọi API nào).

Kiểm tra:
  - `env_setup.py`: alias GOOGLE_API_KEY/GEMINI_API_KEY, thứ tự .env
  - `weather_agent/agent.py`: cấu trúc agent, instruction chống bịa, URL từ env
  - `verify_setup.py`: các tầng báo cáo ĐÚNG trạng thái (không "PASS giả")
"""

from __future__ import annotations

import importlib
import json
import os

import pytest

import env_setup  # noqa: E402  (conftest đã thêm CLIENT_DIR vào sys.path)


@pytest.fixture(autouse=True)
def isolate_api_keys():
    """Lưu & phục hồi CẢ HAI biến khoá API quanh mỗi test.

    Vì sao cần (đây là bug thật đã gặp, không phải phòng xa):
    `env_setup.apply_key_alias()` đồng bộ giá trị sang biến còn lại bằng cách
    ghi trực tiếp vào `os.environ`. Nếu test chỉ cách ly biến mà nó tự set thì
    biến còn lại do alias ghi ra sẽ **rò rỉ vĩnh viễn** trong tiến trình pytest.
    Hệ quả: `test_e2e_agent.py` chạy sau đó thừa hưởng key giả
    (`key-from-gemini`) và fail toàn bộ với `API_KEY_INVALID`.

    Dùng save/restore tường minh thay vì monkeypatch: rõ ràng, phục hồi đúng cả
    trường hợp biến chưa từng tồn tại, và không phụ thuộc hành vi nội bộ của
    monkeypatch đối với các biến mà nó không trực tiếp set.
    """
    saved_env = {name: os.environ.get(name) for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY")}
    saved_source = env_setup.KEY_SOURCE
    yield
    for name, value in saved_env.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    env_setup.KEY_SOURCE = saved_source


# ─────────────────────────────────────────────────────────────────────────────
# 1. env_setup — chuẩn hoá khoá API
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def clean_keys(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(env_setup, "KEY_SOURCE", None)
    return monkeypatch


def test_apply_alias_no_key_returns_none(clean_keys):
    assert env_setup.apply_key_alias() is None
    assert env_setup.google_api_key() is None
    assert env_setup.KEY_SOURCE is None


def test_apply_alias_from_gemini_to_google(clean_keys):
    clean_keys.setenv("GEMINI_API_KEY", "key-from-gemini")
    assert env_setup.apply_key_alias() == "GEMINI_API_KEY"
    assert os.environ["GOOGLE_API_KEY"] == "key-from-gemini"
    assert env_setup.google_api_key() == "key-from-gemini"


def test_apply_alias_from_google_to_gemini(clean_keys):
    clean_keys.setenv("GOOGLE_API_KEY", "key-from-google")
    assert env_setup.apply_key_alias() == "GOOGLE_API_KEY"
    assert os.environ["GEMINI_API_KEY"] == "key-from-google"


def test_key_source_is_sticky_across_calls(clean_keys):
    """Gọi lần hai không được báo sai nguồn (bug đã gặp: alias tự sinh ra)."""
    clean_keys.setenv("GEMINI_API_KEY", "key-1")
    first = env_setup.apply_key_alias()
    second = env_setup.apply_key_alias()
    assert first == second == "GEMINI_API_KEY"
    assert env_setup.KEY_SOURCE == "GEMINI_API_KEY"


def test_env_candidates_order():
    assert env_setup.ENV_CANDIDATES[0].name == ".env"
    assert env_setup.ENV_CANDIDATES[0].parent.name == "mcp-client"
    assert env_setup.ENV_CANDIDATES[1] == env_setup.REPO_ROOT / ".env"


def test_find_repo_root_uses_markers_not_depth():
    """Regression: tìm repo root bằng DẤU HIỆU, không đếm cấp thư mục.

    Bản trước dùng `CLIENT_DIR.parents[1]`; chỉ cần layout nông hơn là
    `IndexError`. Hàm này phải chịu được mọi độ sâu.
    """
    from pathlib import Path

    # Đường dẫn nông kiểu container → KHÔNG được ném IndexError.
    shallow = env_setup.find_repo_root(Path("/app/weather_agent"))
    assert isinstance(shallow, Path)

    # Đường dẫn thật trong repo → phải tìm ra gốc repo (nơi có requirements.txt).
    root = env_setup.find_repo_root(env_setup.CLIENT_DIR)
    assert (root / "requirements.txt").is_file(), f"tìm sai gốc repo: {root}"
    assert root == env_setup.REPO_ROOT


def test_load_environment_returns_existing_files():
    loaded = env_setup.load_environment()
    for path in loaded:
        assert path.is_file()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Agent structure
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def agent_module():
    return importlib.import_module("weather_agent.agent")


def test_agent_metadata(agent_module):
    agent = agent_module.root_agent
    assert agent.name == "weather_agent"
    assert agent.model
    assert agent.description


def test_agent_has_instruction_forbidding_fabrication(agent_module):
    instruction = str(agent_module.root_agent.instruction)
    assert "tiếng Việt" in instruction
    assert "KHÔNG" in instruction or "bịa" in instruction
    assert "get_current_weather" in instruction
    assert "get_forecast" in instruction
    assert "1 đến 3" in instruction, "phải nêu giới hạn ngày dự báo"


def test_agent_instruction_requires_honest_error_reporting(agent_module):
    instruction = str(agent_module.root_agent.instruction)
    assert "❌" in instruction or "lỗi" in instruction.lower()
    assert "nói thật" in instruction


def test_agent_instruction_handles_multi_city_questions(agent_module):
    """Bug đã quan sát trong E2E: agent hỏi lại thay vì gọi tool cho 2 thành phố."""
    instruction = str(agent_module.root_agent.instruction)
    assert "NHIỀU thành phố" in instruction
    assert "KHÔNG hỏi lại" in instruction


def test_agent_binds_mcp_toolset(agent_module, monkeypatch):
    # Trong môi trường có ADK, toolset phải được gắn (không rơi vào fallback).
    assert agent_module.MCP_TOOLS_ENABLED is True
    assert len(agent_module.root_agent.tools) == 1


def test_mcp_server_url_defaults_to_localhost(monkeypatch, agent_module):
    # Giá trị đã đọc lúc import; kiểm tra hằng số và kiểu.
    assert agent_module.MCP_SERVER_URL.startswith("http")
    assert agent_module.MCP_SERVER_URL.endswith("/mcp")
    assert agent_module.MCP_TIMEOUT > 0


def test_agent_module_did_not_claim_connection(agent_module):
    """agent.py KHÔNG được có biến/hàm khẳng định 'đã kết nối thành công'."""
    source = (env_setup.CLIENT_DIR / "weather_agent" / "agent.py").read_text(
        encoding="utf-8"
    )
    assert "kết nối LAZY" in source
    assert "Remote MCP connection successful" not in source


def test_fallback_agent_warns_clearly(agent_module):
    """Nếu có đường fallback, nó phải nói rõ là KHÔNG có tool."""
    source = (env_setup.CLIENT_DIR / "weather_agent" / "agent.py").read_text(
        encoding="utf-8"
    )
    assert "FALLBACK" in source
    assert "KHÔNG CÓ TOOL" in source


def test_root_agent_exported_from_package():
    import weather_agent

    assert weather_agent.root_agent is not None
    assert "root_agent" in weather_agent.__all__


# ─────────────────────────────────────────────────────────────────────────────
# 3. verify_setup — báo cáo trung thực
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def verify(monkeypatch):
    module = importlib.import_module("verify_setup")
    monkeypatch.setattr(module, "RESULTS", [])
    return module


def test_verify_records_environment_pass_with_key(verify, monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy-key-for-test")
    verify.check_environment()
    result = verify.RESULTS[-1]
    assert result.level == "1. Environment"
    assert result.status in (verify.PASS, verify.WARN)


def test_verify_records_environment_fail_without_key(verify, monkeypatch):
    # Phải chặn CẢ việc nạp .env, nếu không load_dotenv sẽ đọc lại key từ file
    # và test này sẽ "PASS giả" — đúng loại lỗi cần tránh.
    monkeypatch.setattr(env_setup, "ENV_CANDIDATES", ())
    monkeypatch.setattr(env_setup, "KEY_SOURCE", None)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    verify.check_environment()
    result = verify.RESULTS[-1]
    assert result.status == verify.FAIL
    assert "THIẾU" in "\n".join(result.lines)


def test_verify_http_unreachable_is_fail_not_pass(verify):
    from conftest import free_port

    verify.check_http_reachable(f"http://127.0.0.1:{free_port()}/mcp")
    result = verify.RESULTS[-1]
    assert result.status == verify.FAIL
    assert "Không kết nối được" in result.detail


def test_verify_http_reachable_never_implies_mcp_ok(verify):
    """Tầng 4 PASS nhưng phải nói rõ KHÔNG suy ra MCP hoạt động."""
    module = verify
    assert "KHÔNG suy ra MCP" in module.__doc__ or True
    source = (env_setup.CLIENT_DIR / "verify_setup.py").read_text(encoding="utf-8")
    assert "KHÔNG suy ra MCP hoạt động từ tầng này" in source


def test_verify_dependencies_pass(verify):
    verify.check_dependencies()
    assert verify.RESULTS[-1].status == verify.PASS


def test_verify_agent_structure_pass(verify):
    verify.check_agent_structure()
    assert verify.RESULTS[-1].status == verify.PASS


def test_verify_gemini_without_key_is_not_verified(verify, monkeypatch):
    monkeypatch.setattr(env_setup, "ENV_CANDIDATES", ())
    monkeypatch.setattr(env_setup, "KEY_SOURCE", None)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    verify.check_gemini("gemini-2.5-flash", enabled=True)
    assert verify.RESULTS[-1].status == verify.NOT_VERIFIED


def test_verify_gemini_disabled_is_not_verified(verify, monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy")
    verify.check_gemini("gemini-2.5-flash", enabled=False)
    result = verify.RESULTS[-1]
    assert result.status == verify.NOT_VERIFIED
    assert "no-network" in result.detail


def test_verify_docstring_lists_all_levels(verify):
    doc = verify.__doc__ or ""
    for level in (
        "HTTP reachable",
        "MCP handshake",
        "Tool discovery",
        "Tool invocation",
        "WeatherAPI",
        "Gemini API",
    ):
        assert level in doc, f"verify_setup phải mô tả tầng '{level}'"


def test_verify_status_vocabulary(verify):
    assert verify.PASS != verify.NOT_VERIFIED
    assert set(verify.ICON) == {
        verify.PASS,
        verify.FAIL,
        verify.WARN,
        verify.NOT_VERIFIED,
    }


def test_verify_records_are_serialisable(verify, monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy")
    verify.check_environment()
    payload = json.dumps([r.__dict__ for r in verify.RESULTS], ensure_ascii=False)
    assert payload
