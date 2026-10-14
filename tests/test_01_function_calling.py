"""Unit test cho 01-function-calling/weather_function_calling.py.

Toàn bộ test ở đây KHÔNG gọi mạng: dùng dữ liệu mock của module và một client
Gemini giả (fake) để kiểm tra vòng lặp function calling.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from google.genai import types

from .conftest import REPO_ROOT, load_module

MODULE_PATH = REPO_ROOT / "01-function-calling" / "weather_function_calling.py"


@pytest.fixture(scope="module")
def wfc():
    return load_module(MODULE_PATH, "day26_weather_function_calling")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Schema của tool
# ─────────────────────────────────────────────────────────────────────────────


def test_tool_declaration_matches_function(wfc):
    declarations = wfc.TOOLS[0].function_declarations
    assert len(declarations) == 1
    decl = declarations[0]
    assert decl.name == "get_weather"
    assert decl.description  # model cần description để quyết định gọi
    assert decl.parameters.type == types.Type.OBJECT
    assert "city" in decl.parameters.properties
    assert decl.parameters.properties["city"].type == types.Type.STRING
    assert decl.parameters.required == ["city"]


def test_dispatch_table_covers_declared_tools(wfc):
    declared = {
        d.name for tool in wfc.TOOLS for d in (tool.function_declarations or [])
    }
    assert declared == set(wfc.TOOL_FUNCTIONS)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Hàm get_weather (mock)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("city", "expected_temp"),
    [
        ("Hà Nội", "29°C"),
        ("Hanoi", "29°C"),
        ("Đà Nẵng", "30°C"),
        ("Danang", "30°C"),
        ("Hồ Chí Minh", "33°C"),
        ("TP. Hồ Chí Minh", "33°C"),
    ],
)
def test_get_weather_known_cities(wfc, city, expected_temp):
    data = json.loads(wfc.get_weather(city))
    assert data["city"] == city
    assert data["nhiệt_độ"] == expected_temp


def test_get_weather_unknown_city_returns_default(wfc):
    data = json.loads(wfc.get_weather("Atlantis"))
    assert data["city"] == "Atlantis"
    assert "không có dữ liệu chi tiết" in data["thời_tiết"]


@pytest.mark.parametrize("bad", ["", "   ", None, 123])
def test_get_weather_invalid_city_returns_error(wfc, bad):
    data = json.loads(wfc.get_weather(bad))
    assert "error" in data


# ─────────────────────────────────────────────────────────────────────────────
# 3. execute_function_call — tên hàm / tham số không hợp lệ
# ─────────────────────────────────────────────────────────────────────────────


def test_execute_function_call_happy_path(wfc):
    data = json.loads(wfc.execute_function_call("get_weather", {"city": "Hà Nội"}))
    assert data["nhiệt_độ"] == "29°C"


def test_execute_function_call_unknown_function(wfc):
    data = json.loads(wfc.execute_function_call("get_stock_price", {"ticker": "FPT"}))
    assert "không tồn tại" in data["error"]
    assert data["available_functions"] == ["get_weather"]


def test_execute_function_call_missing_required_arg(wfc):
    data = json.loads(wfc.execute_function_call("get_weather", {}))
    assert "tham số không hợp lệ" in data["error"]


def test_execute_function_call_extra_arg(wfc):
    data = json.loads(
        wfc.execute_function_call("get_weather", {"city": "Hà Nội", "x": 1})
    )
    assert "tham số không hợp lệ" in data["error"]


def test_execute_function_call_without_name(wfc):
    data = json.loads(wfc.execute_function_call(None, {}))
    assert "error" in data


def test_execute_function_call_none_args_uses_empty(wfc):
    data = json.loads(wfc.execute_function_call("get_weather", None))
    assert "tham số không hợp lệ" in data["error"]


def test_execute_function_call_tool_exception_is_caught(wfc, monkeypatch):
    def boom(**_kwargs: Any) -> str:
        raise RuntimeError("tool hỏng")

    monkeypatch.setitem(wfc.TOOL_FUNCTIONS, "get_weather", boom)
    data = json.loads(wfc.execute_function_call("get_weather", {"city": "Hà Nội"}))
    assert "tool hỏng" in data["error"]


# ─────────────────────────────────────────────────────────────────────────────
# 4. Chế độ offline (không có API key)
# ─────────────────────────────────────────────────────────────────────────────


def test_get_client_none_without_env(wfc, monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert wfc.get_client() is None


def test_offline_answer_is_labelled_and_mock(wfc):
    out = wfc.run("Thời tiết Hà Nội và Đà Nẵng thế nào?", client=None)
    assert "OFFLINE" in out
    assert "MOCK" in out
    assert "Hà Nội" in out
    assert "Đà Nẵng" in out


def test_offline_answer_defaults_to_hanoi(wfc):
    out = wfc.run("thời tiết thế nào?", client=None)
    assert "Hà Nội" in out


# ─────────────────────────────────────────────────────────────────────────────
# 5. Vòng lặp function calling — dùng client giả
# ─────────────────────────────────────────────────────────────────────────────


def _function_call_response(calls: list[tuple[str, dict[str, Any]]]):
    parts = [
        types.Part(function_call=types.FunctionCall(name=name, args=args))
        for name, args in calls
    ]
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=parts),
                finish_reason=types.FinishReason.STOP,
            )
        ]
    )


def _text_response(text: str):
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model", parts=[types.Part.from_text(text=text)]
                ),
                finish_reason=types.FinishReason.STOP,
            )
        ]
    )


class FakeModels:
    def __init__(self, responses: list[Any]):
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, *, model, contents, config):  # noqa: ARG002
        self.calls.append({"model": model, "contents": list(contents), "config": config})
        if not self._responses:
            raise AssertionError("Fake client hết response — model gọi quá nhiều lần")
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeClient:
    def __init__(self, responses: list[Any]):
        self.models = FakeModels(responses)


def test_run_executes_multiple_function_calls_in_one_turn(wfc):
    fake = FakeClient(
        [
            _function_call_response(
                [("get_weather", {"city": "Hà Nội"}), ("get_weather", {"city": "Đà Nẵng"})]
            ),
            _text_response("Hà Nội 29°C, Đà Nẵng 30°C."),
        ]
    )
    out = wfc.run("so sánh 2 thành phố", client=fake)
    assert out == "Hà Nội 29°C, Đà Nẵng 30°C."

    # Vòng 2 phải chứa kết quả của CẢ HAI tool call trong cùng một lượt.
    second_call_contents = fake.models.calls[1]["contents"]
    tool_parts = [
        part
        for content in second_call_contents
        for part in (content.parts or [])
        if part.function_response is not None
    ]
    assert len(tool_parts) == 2
    assert {p.function_response.name for p in tool_parts} == {"get_weather"}


def test_run_returns_model_text_without_tool_call(wfc):
    fake = FakeClient([_text_response("Xin chào!")])
    assert wfc.run("chào", client=fake) == "Xin chào!"
    assert len(fake.models.calls) == 1


def test_run_stops_after_max_tool_rounds(wfc):
    # Model "nghiện" gọi tool: luôn trả về function_call, không bao giờ text.
    forever = [_function_call_response([("get_weather", {"city": "Hà Nội"})])] * 3
    fake = FakeClient(forever)
    with pytest.raises(wfc.MaxToolRoundsExceeded):
        wfc.run("lặp vô hạn", client=fake, max_tool_rounds=2)
    # 1 lần gọi đầu + 2 vòng tool = 3 lần; KHÔNG gọi vô hạn.
    assert len(fake.models.calls) == 3


def test_run_reports_api_error_without_leaking_key(wfc, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-key-value")
    fake = FakeClient([RuntimeError("boom super-secret-key-value")])
    out = wfc.run("hỏi", client=fake)
    assert "Không gọi được Gemini API" in out
    assert "super-secret-key-value" not in out
    assert "***REDACTED***" in out


def test_run_handles_empty_response(wfc):
    empty = types.GenerateContentResponse(candidates=[])
    fake = FakeClient([empty])
    out = wfc.run("hỏi", client=fake)
    assert "không trả về nội dung" in out


def test_run_offline_when_client_is_none(wfc):
    assert "OFFLINE" in wfc.run("thời tiết Hà Nội", client=None)
