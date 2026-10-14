"""Unit test cho HARNESS của E2E (không gọi API nào).

Vì sao cần: assertion "agent không bịa dữ liệu khi tool lỗi" chỉ có giá trị nếu
harness trích xuất ĐÚNG kết quả tool. Đã gặp thật: bản đầu trả về chuỗi rỗng →
`startswith("❌")` luôn False → assertion **vô nghĩa nhưng vẫn PASS**.

File này chứng minh `_extract_tool_result` nhận diện đúng mọi dạng payload mà
ADK có thể bọc, kể cả trường hợp lỗi. Nhờ đó assertion E2E mới đáng tin.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from conftest import CLIENT_DIR  # noqa: F401 - đảm bảo sys.path đã được thiết lập

import importlib.util
import sys

E2E_RUNNER = CLIENT_DIR / "tests" / "e2e_runner.py"


@pytest.fixture(scope="module")
def runner_module():
    spec = importlib.util.spec_from_file_location("day26_e2e_runner", E2E_RUNNER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["day26_e2e_runner"] = module
    spec.loader.exec_module(module)
    return module


def _response(payload):
    return SimpleNamespace(response=payload, name="get_current_weather")


# ─────────────────────────────────────────────────────────────────────────────
# Dạng 1: {'result': '<chuỗi>'}
# ─────────────────────────────────────────────────────────────────────────────


def test_plain_string_result(runner_module):
    text, is_error = runner_module._extract_tool_result(
        _response({"result": "Hanoi: 29°C, trời mưa"})
    )
    assert text == "Hanoi: 29°C, trời mưa"
    assert is_error is False


def test_plain_string_error_marked_by_prefix(runner_module):
    text, is_error = runner_module._extract_tool_result(
        _response({"result": "❌ Không lấy được dữ liệu"})
    )
    assert text == "❌ Không lấy được dữ liệu"
    assert is_error is True


# ─────────────────────────────────────────────────────────────────────────────
# Dạng 2: {'result': <dict CallToolResult>}  ← dạng THỰC TẾ ADK trả về
# ─────────────────────────────────────────────────────────────────────────────


def test_mcp_call_result_dict_success(runner_module):
    payload = {
        "result": {
            "content": [{"type": "text", "text": "Hanoi: 29°C"}],
            "structuredContent": {"x": 1},
            "isError": False,
        }
    }
    text, is_error = runner_module._extract_tool_result(_response(payload))
    assert text == "Hanoi: 29°C", "phải bóc được text, KHÔNG trả JSON bọc ngoài"
    assert is_error is False


def test_mcp_call_result_dict_with_iserror_true(runner_module):
    payload = {
        "result": {
            "content": [{"type": "text", "text": "Error executing tool: boom"}],
            "isError": True,
        }
    }
    text, is_error = runner_module._extract_tool_result(_response(payload))
    assert text == "Error executing tool: boom"
    assert is_error is True, "isError=True phải được nhận diện"


def test_mcp_call_result_dict_error_detected_by_prefix_when_flag_missing(runner_module):
    payload = {"result": {"content": [{"type": "text", "text": "❌ Thiếu WEATHERAPI_KEY"}]}}
    text, is_error = runner_module._extract_tool_result(_response(payload))
    assert text == "❌ Thiếu WEATHERAPI_KEY"
    assert is_error is True


def test_mcp_call_result_snake_case_is_error(runner_module):
    payload = {
        "result": {
            "content": [{"type": "text", "text": "Unknown tool: nope"}],
            "is_error": True,
        }
    }
    _text, is_error = runner_module._extract_tool_result(_response(payload))
    assert is_error is True


def test_error_only_payload(runner_module):
    text, is_error = runner_module._extract_tool_result(_response({"error": "tool crashed"}))
    assert text == "tool crashed"
    assert is_error is True


# ─────────────────────────────────────────────────────────────────────────────
# Dạng 3: đối tượng có thuộc tính .content
# ─────────────────────────────────────────────────────────────────────────────


def test_object_with_content_attribute(runner_module):
    block = SimpleNamespace(text="29°C")
    payload = {"result": SimpleNamespace(content=[block])}
    text, is_error = runner_module._extract_tool_result(_response(payload))
    assert text == "29°C"
    assert is_error is False


def test_list_of_content_blocks(runner_module):
    payload = {"result": [{"text": "dòng 1"}, {"text": "dòng 2"}]}
    text, _is_error = runner_module._extract_tool_result(_response(payload))
    assert text == "dòng 1\ndòng 2"


# ─────────────────────────────────────────────────────────────────────────────
# Không bao giờ trả rỗng khi payload có dữ liệu
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    [
        {"result": "x"},
        {"result": {"content": [{"text": "x"}]}},
        {"result": {"weird": "shape"}},
        {"result": 42},
        {"result": [1, 2, 3]},
    ],
)
def test_extraction_never_empty_for_non_empty_payload(runner_module, payload):
    text, _is_error = runner_module._extract_tool_result(_response(payload))
    assert text.strip(), f"trích xuất rỗng cho payload {payload!r} → assertion sẽ vô nghĩa"


def test_missing_response_is_empty(runner_module):
    text, is_error = runner_module._extract_tool_result(SimpleNamespace(response=None))
    assert text == ""
    assert is_error is False


def test_transient_marker_detection(runner_module):
    assert runner_module._is_transient(
        ["ClientError: 403 ... API_KEY_IP_ADDRESS_BLOCKED ..."]
    )
    assert runner_module._is_transient(["429 RESOURCE_EXHAUSTED"])
    assert not runner_module._is_transient(["agent không gọi tool nào"])
