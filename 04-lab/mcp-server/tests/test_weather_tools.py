"""Unit test cho 04-lab/mcp-server/weather.py.

Dùng MockWeatherAPI (HTTP server thật trong tiến trình test) nên đường httpx,
status code, JSON hỏng và timeout đều được kiểm tra thật — không mock httpx.
Không cần WEATHERAPI_KEY thật, không gọi ra Internet.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from conftest import CURRENT_PAYLOAD, FORECAST_PAYLOAD, free_port


# ─────────────────────────────────────────────────────────────────────────────
# 1. get_current_weather — happy path và định dạng
# ─────────────────────────────────────────────────────────────────────────────


def test_current_weather_formats_real_payload(weather, mock_weather_api):
    mock_weather_api.set("/v1/current.json", body=CURRENT_PAYLOAD)

    text = asyncio.run(weather.get_current_weather("Hanoi"))

    assert "Hanoi" in text
    assert "29.0" in text
    assert "Light rain" in text
    assert "82" in text
    assert not text.startswith("❌")

    # API key phải được gửi dưới dạng query param `key`.
    _path, query = mock_weather_api.requests[-1]
    assert query["key"] == ["test-key-abc123"]
    assert query["q"] == ["Hanoi"]


def test_current_weather_missing_key_does_not_call_api(weather, mock_weather_api, monkeypatch):
    monkeypatch.delenv("WEATHERAPI_KEY", raising=False)

    text = asyncio.run(weather.get_current_weather("Hanoi"))

    assert text.startswith("❌")
    assert "WEATHERAPI_KEY" in text
    assert mock_weather_api.requests == [], "không được gọi WeatherAPI khi thiếu key"


@pytest.mark.parametrize("city", ["", "   ", None, 123])
def test_current_weather_invalid_city(weather, mock_weather_api, city):
    text = asyncio.run(weather.get_current_weather(city))
    assert text.startswith("❌")
    assert mock_weather_api.requests == []


def test_current_weather_scrubs_api_key_from_errors(weather, mock_weather_api, monkeypatch):
    """Nếu upstream echo lại key, nó phải bị che trước khi trả cho client."""
    monkeypatch.setenv("WEATHERAPI_KEY", "super-secret-key")
    mock_weather_api.set(
        "/v1/current.json",
        status=400,
        body={"error": {"code": 1006, "message": "Key super-secret-key is bad"}},
    )

    text = asyncio.run(weather.get_current_weather("Hanoi"))

    assert "super-secret-key" not in text
    assert "REDACTED" in text


# ─────────────────────────────────────────────────────────────────────────────
# 2. get_forecast — validate `days` TRƯỚC khi gọi API
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("days", [-5, -2, -1, 0, 4, 5, 10, 100])
def test_forecast_rejects_out_of_range_days_without_calling_api(
    weather, mock_weather_api, days
):
    text = asyncio.run(weather.get_forecast("Hanoi", days))

    assert text.startswith("❌")
    assert "days" in text
    assert mock_weather_api.requests == [], (
        f"days={days} phải bị chặn tại server, KHÔNG được gửi tới WeatherAPI"
    )


@pytest.mark.parametrize("days", ["2", 2.5, None, True, [2]])
def test_forecast_rejects_wrong_type_days(weather, mock_weather_api, days):
    text = asyncio.run(weather.get_forecast("Hanoi", days))
    assert text.startswith("❌")
    assert mock_weather_api.requests == []


@pytest.mark.parametrize("days", [1, 2, 3])
def test_forecast_accepts_supported_range(weather, mock_weather_api, days):
    mock_weather_api.set("/v1/forecast.json", body=FORECAST_PAYLOAD)

    text = asyncio.run(weather.get_forecast("Hanoi", days))

    assert not text.startswith("❌")
    _path, query = mock_weather_api.requests[-1]
    assert query["days"] == [str(days)], "chỉ được gửi số ngày trong khoảng hỗ trợ"


def test_forecast_default_is_three_days(weather, mock_weather_api):
    mock_weather_api.set("/v1/forecast.json", body=FORECAST_PAYLOAD)

    asyncio.run(weather.get_forecast("Hanoi"))

    _path, query = mock_weather_api.requests[-1]
    assert query["days"] == ["3"]


def test_forecast_formats_days(weather, mock_weather_api):
    mock_weather_api.set("/v1/forecast.json", body=FORECAST_PAYLOAD)

    text = asyncio.run(weather.get_forecast("Hanoi", 2))

    assert "2026-10-15" in text
    assert "2026-10-16" in text
    assert "Patchy rain nearby" in text
    assert "71" in text


def test_forecast_invalid_city(weather, mock_weather_api):
    text = asyncio.run(weather.get_forecast("", 2))
    assert text.startswith("❌")
    assert mock_weather_api.requests == []


# ─────────────────────────────────────────────────────────────────────────────
# 3. Ánh xạ lỗi HTTP / JSON hỏng / timeout / lỗi mạng
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("status", "body", "fragment"),
    [
        (401, {"error": {"code": 2006, "message": "API key is invalid."}}, "từ chối API key"),
        (403, {"error": {"code": 2006, "message": "forbidden"}}, "từ chối API key"),
        (400, {"error": {"code": 1006, "message": "No matching location found."}}, "không hợp lệ"),
        (429, {"error": {"code": 2007, "message": "quota"}}, "quota"),
        (500, {"error": {"code": 9999, "message": "boom"}}, "máy chủ"),
        (502, {"error": {"code": 9999, "message": "bad gateway"}}, "máy chủ"),
    ],
)
def test_http_errors_map_to_friendly_messages(weather, mock_weather_api, status, body, fragment):
    mock_weather_api.set("/v1/current.json", status=status, body=body)

    text = asyncio.run(weather.get_current_weather("Hanoi"))

    assert text.startswith("❌")
    assert fragment in text
    assert str(status) in text


def test_non_json_body_is_handled(weather, mock_weather_api):
    mock_weather_api.set("/v1/current.json", body=None, raw="<html>not json</html>")

    text = asyncio.run(weather.get_current_weather("Hanoi"))

    assert text.startswith("❌")
    assert "không phải JSON" in text


def test_json_array_body_is_handled(weather, mock_weather_api):
    mock_weather_api.set("/v1/current.json", body=[1, 2, 3])

    text = asyncio.run(weather.get_current_weather("Hanoi"))

    assert text.startswith("❌")
    assert "sai cấu trúc" in text


def test_error_field_in_200_body_is_handled(weather, mock_weather_api):
    mock_weather_api.set(
        "/v1/current.json",
        status=200,
        body={"error": {"code": 1006, "message": "No matching location found."}},
    )

    text = asyncio.run(weather.get_current_weather("Atlantis"))

    assert text.startswith("❌")
    assert "1006" in text


def test_timeout_is_reported(weather, mock_weather_api, monkeypatch):
    monkeypatch.setenv("WEATHERAPI_TIMEOUT", "0.5")
    mock_weather_api.set("/v1/current.json", body=CURRENT_PAYLOAD, delay=3.0)

    text = asyncio.run(weather.get_current_weather("Hanoi"))

    assert text.startswith("❌")
    assert "Timeout" in text


def test_network_error_is_reported(weather, monkeypatch):
    # Cổng đã đóng → httpx.ConnectError (RequestError).
    monkeypatch.setenv("WEATHERAPI_BASE_URL", f"http://127.0.0.1:{free_port()}/v1")

    text = asyncio.run(weather.get_current_weather("Hanoi"))

    assert text.startswith("❌")
    assert "Lỗi mạng" in text


# ─────────────────────────────────────────────────────────────────────────────
# 4. Payload thiếu trường / sai cấu trúc
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"location": {"name": "Hanoi"}},
        {"current": None},
        {"current": "nope"},
        {"location": "nope", "current": {}},
    ],
)
def test_current_weather_missing_fields(weather, mock_weather_api, payload):
    mock_weather_api.set("/v1/current.json", body=payload)

    text = asyncio.run(weather.get_current_weather("Hanoi"))

    # Không được crash; hoặc báo lỗi rõ, hoặc hiển thị "không rõ" cho field thiếu.
    assert isinstance(text, str) and text
    assert "Traceback" not in text
    if "current" not in payload or not isinstance(payload.get("current"), dict):
        assert text.startswith("❌")


def test_current_weather_partial_current_uses_placeholder(weather, mock_weather_api):
    mock_weather_api.set(
        "/v1/current.json",
        body={"location": {"name": "Hanoi"}, "current": {"temp_c": 30.0}},
    )

    text = asyncio.run(weather.get_current_weather("Hanoi"))

    assert "30.0" in text
    assert "không rõ" in text  # các field thiếu không được in ra "None"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"forecast": {}},
        {"forecast": {"forecastday": []}},
        {"forecast": {"forecastday": None}},
        {"location": {"name": "Hanoi"}, "forecast": "nope"},
    ],
)
def test_forecast_missing_fields(weather, mock_weather_api, payload):
    mock_weather_api.set("/v1/forecast.json", body=payload)

    text = asyncio.run(weather.get_forecast("Hanoi", 2))

    assert text.startswith("❌")
    assert "forecastday" in text


def test_forecast_tolerates_malformed_day_entries(weather, mock_weather_api):
    """Entry hỏng bị BỎ QUA, không crash, và KHÔNG tạo block 'toàn không rõ'.

    Hành vi này siết hơn bản trước: entry chỉ có `date` mà không có số liệu thì
    không được hiển thị như thể ta có dự báo của ngày đó.
    """
    mock_weather_api.set(
        "/v1/forecast.json",
        body={
            "location": {"name": "Hanoi"},
            "forecast": {
                "forecastday": [
                    {"date": "2026-10-15"},  # thiếu hẳn `day` → bỏ qua
                    "rác",                    # không phải dict → bỏ qua
                    {"date": "2026-10-16", "day": {"maxtemp_c": 30}},  # hợp lệ
                ]
            },
        },
    )

    text = asyncio.run(weather.get_forecast("Hanoi", 2))

    assert not text.startswith("❌"), "vẫn còn 1 ngày hợp lệ nên phải thành công"
    assert "2026-10-16" in text
    assert "2026-10-15" not in text, "entry không có số liệu KHÔNG được tạo block giả"
    assert "Traceback" not in text


# ─────────────────────────────────────────────────────────────────────────────
# 4b. Nested JSON SAI KIỂU — regression: không crash, không báo thành công giả
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    [
        # `condition` là chuỗi thay vì object lồng → bản cũ: AttributeError
        {"current": {"temp_c": 30, "condition": "Cloudy"}, "location": {"name": "Hanoi"}},
        # `name` là số, `region` là dict → bản cũ: TypeError ở ", ".join
        {"current": {"temp_c": 30}, "location": {"name": 123, "region": {"a": 1}}},
        {"current": {"temp_c": 30}, "location": {"name": ["x"], "country": {"a": 1}}},
        # giá trị lồng sâu sai kiểu
        {"current": {"temp_c": {"v": 1}, "humidity": [1]}, "location": {"name": "Hanoi"}},
        {"current": {"temp_c": 30, "wind_dir": {"deg": 90}}, "location": None},
        # `current` bị bọc thêm một tầng
        {"current": {"current": {"temp_c": 30}}, "location": {"name": "Hanoi"}},
        # `location` là kiểu vô hướng
        {"current": {"temp_c": 30}, "location": "Hanoi"},
    ],
)
def test_current_weather_never_crashes_on_wrong_types(weather, mock_weather_api, payload):
    mock_weather_api.set("/v1/current.json", body=payload)

    text = asyncio.run(weather.get_current_weather("Hanoi"))

    assert isinstance(text, str) and text
    for marker in ("Traceback", "AttributeError", "TypeError", "KeyError", "IndexError"):
        assert marker not in text, f"{marker} lọt ra ngoài: {text!r}"


def test_current_weather_uses_condition_string_when_not_nested(weather, mock_weather_api):
    """`condition` là chuỗi vẫn dùng được, không cần là object lồng."""
    mock_weather_api.set(
        "/v1/current.json",
        body={"current": {"temp_c": 30, "condition": "Cloudy"}, "location": {"name": "Hanoi"}},
    )

    text = asyncio.run(weather.get_current_weather("Hanoi"))

    assert "Cloudy" in text
    assert not text.startswith("❌")


def test_current_weather_wrong_types_yield_error_not_fake_success(weather, mock_weather_api):
    """`current` chỉ toàn giá trị sai kiểu → phải báo lỗi, không trả trang 'không rõ'."""
    mock_weather_api.set(
        "/v1/current.json",
        body={
            "current": {"temp_c": {"nested": 1}, "humidity": [1, 2], "condition": {"a": 1}},
            "location": {"name": "Hanoi"},
        },
    )

    text = asyncio.run(weather.get_current_weather("Hanoi"))

    assert text.startswith("❌")
    assert "không hợp lệ" in text


def test_current_weather_non_string_location_is_safe(weather, mock_weather_api):
    mock_weather_api.set(
        "/v1/current.json",
        body={"current": {"temp_c": 30}, "location": {"name": {"x": 1}, "region": [1]}},
    )

    text = asyncio.run(weather.get_current_weather("Hanoi"))

    assert not text.startswith("❌")
    assert "Thời tiết hiện tại tại ?" in text


@pytest.mark.parametrize(
    "forecastday",
    [
        {"a": 1},          # dict → bản cũ lặp qua KEY rồi trả về "thành công rỗng"
        "abc",             # chuỗi → bản cũ lặp qua từng KÝ TỰ
        123,               # số
        [1, "x", None],    # list toàn rác
        [{}],              # entry rỗng, không có `day`
        [{"date": "d"}],   # có `date` nhưng không có số liệu nào
        [{"date": "d", "day": "nope"}],   # `day` sai kiểu
        [{"date": "d", "day": {}}],       # `day` rỗng
    ],
)
def test_forecast_never_reports_success_without_usable_days(
    weather, mock_weather_api, forecastday
):
    """Regression: dữ liệu dự báo không đọc được PHẢI trả lỗi, không được trả về
    chỉ mỗi dòng tiêu đề như thể thành công."""
    mock_weather_api.set("/v1/forecast.json", body={"forecast": {"forecastday": forecastday}})

    text = asyncio.run(weather.get_forecast("Hanoi", 3))

    assert text.startswith("❌"), f"phải báo lỗi, không được 'thành công rỗng': {text!r}"
    assert "Dự báo 3 ngày tới tại" not in text, "không được in tiêu đề dự báo rỗng"


@pytest.mark.parametrize(
    "entry",
    [
        {"date": "2026-10-15", "day": {"maxtemp_c": 30}},
        {"date": "2026-10-15", "day": {"uv": 5}},
        {"date": "2026-10-15", "day": {"condition": "Sunny"}},
        {"date": "2026-10-15", "day": {"condition": {"text": "Sunny"}}},
    ],
)
def test_forecast_day_is_usable_with_any_readable_field(weather, mock_weather_api, entry):
    mock_weather_api.set("/v1/forecast.json", body={"forecast": {"forecastday": [entry]}})

    text = asyncio.run(weather.get_forecast("Hanoi", 3))

    assert not text.startswith("❌")
    assert "2026-10-15" in text


@pytest.mark.parametrize(
    "entry",
    [
        {"date": "2026-10-15", "day": {"maxtemp_c": 30, "condition": "Sunny"}},
        {"date": "2026-10-15", "day": {"maxtemp_c": {"v": 1}, "condition": 5}},
        {"date": {"a": 1}, "day": {"mintemp_c": 20}},
        {"day": {"maxwind_kph": [1]}},
    ],
)
def test_forecast_day_never_crashes_on_wrong_types(weather, mock_weather_api, entry):
    mock_weather_api.set("/v1/forecast.json", body={"forecast": {"forecastday": [entry]}})

    text = asyncio.run(weather.get_forecast("Hanoi", 3))

    assert isinstance(text, str) and text
    for marker in ("Traceback", "AttributeError", "TypeError", "KeyError", "IndexError"):
        assert marker not in text, f"{marker} lọt ra ngoài: {text!r}"


def test_forecast_mixed_valid_and_invalid_entries(weather, mock_weather_api):
    """Chỉ những ngày có số liệu thật mới xuất hiện."""
    mock_weather_api.set(
        "/v1/forecast.json",
        body={
            "location": {"name": "Da Nang"},
            "forecast": {
                "forecastday": [
                    {"date": "2026-10-14"},
                    {"date": "2026-10-15", "day": {"maxtemp_c": 31, "mintemp_c": 24}},
                    {"date": "2026-10-16", "day": "rác"},
                    {"date": "2026-10-17", "day": {"daily_chance_of_rain": 80}},
                ]
            },
        },
    )

    text = asyncio.run(weather.get_forecast("Da Nang", 3))

    assert "2026-10-15" in text
    assert "2026-10-17" in text
    assert "2026-10-14" not in text
    assert "2026-10-16" not in text


# ── Helper thuần: _val / _place / _condition / _day_is_readable ──────────────


@pytest.mark.parametrize(
    ("mapping", "expected"),
    [
        ({"k": "v"}, "v"),
        ({"k": 0}, 0),
        ({"k": None}, "không rõ"),
        ({"k": ""}, "không rõ"),
        ({"k": {}}, "không rõ"),
        ({"k": []}, "không rõ"),
        ({}, "không rõ"),
        ("không phải dict", "không rõ"),
        (None, "không rõ"),
        (123, "không rõ"),
    ],
)
def test_val_is_type_safe(weather, mapping, expected):
    assert weather._val(mapping, "k") == expected


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ({"name": "Hanoi", "region": "Ha Noi", "country": "Vietnam"}, "Hanoi, Ha Noi, Vietnam"),
        ({"name": "Hanoi"}, "Hanoi"),
        ({"name": 123}, "123"),
        ({"name": {"x": 1}}, "?"),
        ({"name": ""}, "?"),
        ({}, "?"),
        (None, "?"),
        ("Hanoi", "?"),
        ([1], "?"),
    ],
)
def test_place_is_type_safe(weather, location, expected):
    assert weather._place(location) == expected


@pytest.mark.parametrize(
    ("container", "expected"),
    [
        ({"condition": {"text": "Sunny"}}, "Sunny"),
        ({"condition": "Cloudy"}, "Cloudy"),
        ({"condition": "  Rain  "}, "Rain"),
        ({"condition": ""}, "không rõ"),
        ({"condition": 5}, "không rõ"),
        ({"condition": ["x"]}, "không rõ"),
        ({"condition": {"text": None}}, "không rõ"),
        ({}, "không rõ"),
        ("nope", "không rõ"),
        (None, "không rõ"),
    ],
)
def test_condition_is_type_safe(weather, container, expected):
    assert weather._condition(container) == expected


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        ({"maxtemp_c": 30}, True),
        ({"uv": 0}, True),
        ({"daily_chance_of_rain": 0}, True),
        ({"condition": "Sunny"}, True),
        ({"condition": {"text": "Sunny"}}, True),
        ({}, False),
        ({"date": "2026-10-15"}, False),
        ({"maxtemp_c": {"v": 1}}, False),
        ({"condition": {"other": 1}}, False),
    ],
)
def test_day_is_readable(weather, day, expected):
    assert weather._day_is_readable(day) is expected


# ─────────────────────────────────────────────────────────────────────────────
# 5. health_check
# ─────────────────────────────────────────────────────────────────────────────


def test_health_check_reports_key_state(weather, mock_weather_api, monkeypatch):
    payload = json.loads(asyncio.run(weather.health_check()))
    assert payload["status"] == "ok"
    assert payload["weatherapi_key_configured"] is True
    assert set(payload["tools"]) == {"get_current_weather", "get_forecast", "health_check"}
    assert mock_weather_api.requests == [], "health_check KHÔNG được gọi WeatherAPI"


def test_health_check_without_key(weather, monkeypatch):
    monkeypatch.delenv("WEATHERAPI_KEY", raising=False)
    payload = json.loads(asyncio.run(weather.health_check()))
    assert payload["status"] == "ok"
    assert payload["weatherapi_key_configured"] is False


def test_health_check_never_leaks_key(weather):
    payload = asyncio.run(weather.health_check())
    assert "test-key-abc123" not in payload


# ── health_check phải phản ánh transport THẬT (không hard-code) ─────────────


def test_health_check_reports_stdio_and_no_http_endpoint(weather, monkeypatch):
    """Regression: chạy stdio nhưng health_check báo 'streamable-http' là NÓI SAI."""
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    weather.set_active_transport("stdio")

    payload = json.loads(asyncio.run(weather.health_check()))

    assert payload["transport"] == "stdio"
    assert payload["endpoint"] is None, "stdio không có endpoint HTTP"


def test_health_check_reports_streamable_http_with_endpoint(weather, monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    weather.set_active_transport("streamable-http")

    payload = json.loads(asyncio.run(weather.health_check()))

    assert payload["transport"] == "streamable-http"
    assert payload["endpoint"].endswith("/mcp")


def test_health_check_reports_sse_with_sse_path(weather, monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "sse")
    weather.set_active_transport("sse")

    payload = json.loads(asyncio.run(weather.health_check()))
    assert payload["transport"] == "sse"
    assert payload["endpoint"].endswith("/sse")


def test_health_check_transport_follows_env_when_not_started(weather, monkeypatch):
    """Chưa chạy `__main__` → suy ra từ cấu hình, không hard-code."""
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    weather.ACTIVE_TRANSPORT = None

    assert json.loads(asyncio.run(weather.health_check()))["transport"] == "stdio"

    monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    assert (
        json.loads(asyncio.run(weather.health_check()))["transport"]
        == "streamable-http"
    )


def test_health_check_transport_unknown_when_env_invalid(weather, monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "carrier-pigeon")
    weather.ACTIVE_TRANSPORT = None

    payload = json.loads(asyncio.run(weather.health_check()))

    assert payload["transport"] == "unknown"
    assert payload["endpoint"] is None


def test_set_active_transport_overrides_env(weather, monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    weather.set_active_transport("streamable-http")
    assert weather.current_transport() == "streamable-http"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Chọn transport khi khởi động
# ─────────────────────────────────────────────────────────────────────────────


def test_transport_defaults_to_streamable_http(weather, monkeypatch):
    monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    assert weather.resolve_transport() == "streamable-http"


def test_transport_ignores_tty_and_behaves_the_same(weather, monkeypatch):
    """Bug cũ: server tự chuyển sang stdio khi stdin là TTY."""
    monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    assert weather.resolve_transport() == "streamable-http"


@pytest.mark.parametrize("value", ["stdio", "sse", "streamable-http", " STDIO "])
def test_transport_env_override(weather, monkeypatch, value):
    monkeypatch.setenv("MCP_TRANSPORT", value)
    assert weather.resolve_transport() == value.strip().lower()


def test_transport_invalid_value_exits(weather, monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "carrier-pigeon")
    with pytest.raises(SystemExit):
        weather.resolve_transport()


def test_scrub_redacts_key(weather, monkeypatch):
    monkeypatch.setenv("WEATHERAPI_KEY", "top-secret")
    assert "top-secret" not in weather._scrub("lỗi với top-secret")
