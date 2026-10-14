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
    mock_weather_api.set(
        "/v1/forecast.json",
        body={
            "location": {"name": "Hanoi"},
            "forecast": {"forecastday": [{"date": "2026-10-15"}, "rác", {"date": "2026-10-16", "day": {"maxtemp_c": 30}}]},
        },
    )

    text = asyncio.run(weather.get_forecast("Hanoi", 2))

    assert "2026-10-15" in text
    assert "Traceback" not in text


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
