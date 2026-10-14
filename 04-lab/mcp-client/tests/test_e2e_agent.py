"""End-to-end test: User → ADK Agent → MCP Server → (WeatherAPI) → MCP → Gemini → User.

BẬT/TẮT:
    Mặc định test này SKIP (không tự ý tiêu quota Gemini của bạn).
    Bật bằng biến môi trường:
        $env:DAY26_E2E=1; uv run --with pytest pytest tests/test_e2e_agent.py -q     # PowerShell
        DAY26_E2E=1 uv run --with pytest pytest tests/test_e2e_agent.py -q           # bash

CHẾ ĐỘ UPSTREAM:
    - Có WEATHERAPI_KEY trong môi trường → gọi WeatherAPI THẬT.
    - Không có → dùng MockWeatherAPI (HTTP server giả trong tiến trình test).
      Khi đó luồng ADK → MCP → parse/format dữ liệu là THẬT, nhưng DỮ LIỆU
      THỜI TIẾT KHÔNG phải real-time. Test sẽ nói rõ mode trong phần báo cáo.

Câu hỏi bắt buộc (theo yêu cầu Phase 6):
    1. "Thời tiết Hà Nội hôm nay thế nào?"
    2. "Dự báo Đà Nẵng trong 3 ngày tới."
    3. "So sánh thời tiết Hà Nội và TP. Hồ Chí Minh."
    4. "MCP Server hiện có hoạt động không?"
    5. "Dự báo thời tiết -2 ngày tới."
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import CLIENT_DIR, spawn_mcp_server

# Nhiệt độ trong kết quả tool (định dạng của weather.py: "29.0°C") và mọi con số
# trong câu trả lời (để so khớp giá trị, không phụ thuộc cách model diễn đạt).
_TEMP_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*°C")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")

E2E_ENABLED = os.getenv("DAY26_E2E", "0").strip() not in ("", "0", "false", "no")
REAL_UPSTREAM = bool(os.getenv("WEATHERAPI_KEY", "").strip())

# Lỗi TẠM THỜI của môi trường — không phải lỗi logic của agent.
TRANSIENT_MARKERS = (
    "ip address restriction",
    "API_KEY_IP_ADDRESS_BLOCKED",
    "RESOURCE_EXHAUSTED",
    "429",
)

pytestmark = pytest.mark.skipif(
    not E2E_ENABLED,
    reason=(
        "E2E bị tắt. Bật bằng DAY26_E2E=1 để chạy thật "
        "(cần GOOGLE_API_KEY còn quota)."
    ),
)

QUESTIONS = [
    "Thời tiết Hà Nội hôm nay thế nào?",
    "Dự báo Đà Nẵng trong 3 ngày tới.",
    "So sánh thời tiết Hà Nội và TP. Hồ Chí Minh.",
    "MCP Server hiện có hoạt động không?",
    "Dự báo thời tiết -2 ngày tới.",
]


@pytest.fixture(scope="module")
def e2e_results(mock_weather_api, tmp_path_factory):
    """Chạy cả 5 câu hỏi trong MỘT tiến trình runner, trả về kết quả JSON."""
    if REAL_UPSTREAM:
        server_env = {"WEATHERAPI_KEY": os.environ["WEATHERAPI_KEY"]}
    else:
        # Upstream giả + key giả: server coi như đã cấu hình và gọi mock.
        server_env = {
            "WEATHERAPI_KEY": "test-key-e2e",
            "WEATHERAPI_BASE_URL": mock_weather_api.base_url,
        }

    with spawn_mcp_server(**server_env) as (url, ready, proc):
        if not ready:
            stderr = proc.stderr.read() if proc.stderr else ""
            pytest.fail(f"MCP server không khởi động được.\n{stderr[:2000]}")

        questions_file = tmp_path_factory.mktemp("e2e") / "questions.json"
        questions_file.write_text(json.dumps(QUESTIONS, ensure_ascii=False), encoding="utf-8")

        env = {**os.environ, "MCP_SERVER_URL": url, "PYTHONIOENCODING": "utf-8"}

        # Chẩn đoán: nói rõ key nào đang được dùng (KHÔNG in giá trị).
        for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
            value = env.get(name, "")
            print(f"[E2E] {name}: {'set (len=%d)' % len(value) if value else 'KHÔNG CÓ'}")

        completed = subprocess.run(
            [sys.executable, str(CLIENT_DIR / "tests" / "e2e_runner.py"), f"@{questions_file}"],
            cwd=str(CLIENT_DIR),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
        )

    stdout = completed.stdout or ""
    json_lines = [line for line in stdout.splitlines() if line.strip().startswith("{")]
    if not json_lines:
        pytest.fail(
            "e2e_runner.py không in JSON.\n"
            f"exit={completed.returncode}\n--- stdout ---\n{stdout[-2000:]}\n"
            f"--- stderr ---\n{(completed.stderr or '')[-2000:]}"
        )

    payload = json.loads(json_lines[-1])
    payload["mode"] = "real-weatherapi" if REAL_UPSTREAM else "mock-weatherapi"
    print(f"\n[E2E] upstream mode = {payload['mode']}")
    for result in payload["results"]:
        print(f"  Q: {result['question']}")
        print(f"     tools  : {[c['name'] for c in result['tool_calls']]}")
        print(f"     results: {[r.get('result', '')[:80] for r in result['tool_responses']]}")
        print(f"     errors : {result['errors']}")
        print(f"     answer : {result['answer'][:400]}")
    return payload


def _by_index(results: dict, index: int) -> dict:
    result = results["results"][index]

    # Lỗi TẠM THỜI của môi trường (key Gemini bị giới hạn IP, hết quota) nghĩa
    # là "CHƯA XÁC MINH ĐƯỢC" — không phải PASS, mà cũng không phải lỗi logic
    # của agent. Báo SKIP để không ai đọc nhầm thành "agent chạy đúng".
    if result["errors"]:
        joined = " ".join(result["errors"]).lower()
        if any(marker.lower() in joined for marker in TRANSIENT_MARKERS):
            pytest.skip(
                f"Không xác minh được câu {index + 1} do lỗi TẠM THỜI của môi "
                f"trường ({result['attempts']} lần thử): {result['errors'][-1][:160]}"
            )
        pytest.fail(f"Câu {index + 1} lỗi hệ thống: {result['errors']}")

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 0. Không câu hỏi nào lỗi hệ thống
# ─────────────────────────────────────────────────────────────────────────────


def test_no_system_errors(e2e_results):
    broken = [r for r in e2e_results["results"] if r["errors"]]
    if not broken:
        return

    all_transient = all(
        any(marker.lower() in " ".join(r["errors"]).lower() for marker in TRANSIENT_MARKERS)
        for r in broken
    )
    detail = json.dumps(broken, ensure_ascii=False, indent=2)
    if all_transient:
        pytest.skip(
            f"{len(broken)}/{len(e2e_results['results'])} câu không xác minh được vì lỗi "
            "TẠM THỜI của môi trường (key Gemini giới hạn IP / hết quota). "
            f"Đây KHÔNG phải PASS.\n{detail[:800]}"
        )
    pytest.fail(_mask_keys(f"Có câu hỏi lỗi hệ thống:\n{detail}"))


def _mask_keys(text: str) -> str:
    """Không để lộ API key trong output test."""
    for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "WEATHERAPI_KEY"):
        value = os.getenv(name, "")
        if value:
            text = text.replace(value, "***REDACTED***")
    return text


# ─────────────────────────────────────────────────────────────────────────────
# 1..5. Từng câu hỏi: chọn đúng tool + không bịa dữ liệu
# ─────────────────────────────────────────────────────────────────────────────


def test_q1_current_weather_calls_tool_and_answers(e2e_results):
    result = _by_index(e2e_results, 0)
    called = [c["name"] for c in result["tool_calls"]]
    assert "get_current_weather" in called, f"agent không gọi tool: {result}"

    answer = result["answer"]
    assert answer, "agent phải trả lời"

    # Nếu tool THÀNH CÔNG thì câu trả lời phải dùng số liệu thật của tool
    # (so theo giá trị, không hard-code nhiệt độ của mock).
    responses = [r for r in result["tool_responses"] if r["name"] == "get_current_weather"]
    if responses and not any(r.get("is_error") for r in responses):
        tool_temps = {
            float(v)
            for r in responses
            for v in _TEMP_RE.findall(str(r.get("result", "")))
        }
        answer_numbers = {float(v) for v in _NUMBER_RE.findall(answer)}
        assert tool_temps & answer_numbers, (
            f"tool trả nhiệt độ {sorted(tool_temps)} nhưng câu trả lời không dùng: {answer!r}"
        )


def test_q2_forecast_uses_three_days(e2e_results):
    result = _by_index(e2e_results, 1)
    calls = [c for c in result["tool_calls"] if c["name"] == "get_forecast"]
    assert calls, f"agent không gọi get_forecast: {result}"
    assert calls[0]["args"].get("days") == 3, (
        f"'3 ngày tới' phải truyền days=3, nhận được {calls[0]['args']}"
    )
    assert result["answer"]


def test_q3_comparison_calls_tool_for_both_cities(e2e_results):
    result = _by_index(e2e_results, 2)
    calls = [c for c in result["tool_calls"] if c["name"] == "get_current_weather"]
    assert len(calls) >= 2, f"so sánh 2 thành phố phải gọi tool ≥2 lần: {calls}"

    cities = " ".join(str(c["args"].get("city", "")).lower() for c in calls)
    assert "ha noi" in cities or "hanoi" in cities
    assert "ho chi minh" in cities or "hcm" in cities


def test_q4_health_check_is_used(e2e_results):
    result = _by_index(e2e_results, 3)
    called = [c["name"] for c in result["tool_calls"]]
    assert "health_check" in called, f"câu hỏi về server phải gọi health_check: {result}"
    assert result["answer"]


def test_q5_negative_days_never_reaches_upstream(e2e_results):
    """Yêu cầu '-2 ngày': agent phải nói rõ giới hạn 1–3, KHÔNG gọi tool sai."""
    result = _by_index(e2e_results, 4)

    for call in result["tool_calls"]:
        if call["name"] == "get_forecast":
            days = call["args"].get("days")
            assert days is None or (isinstance(days, int) and 1 <= days <= 3), (
                f"không được gửi days={days} ra ngoài khoảng 1..3"
            )

    answer = result["answer"]
    assert answer, "agent phải trả lời"
    lowered = answer.lower()
    assert ("1" in answer and "3" in answer) or "giới hạn" in lowered or "không hợp lệ" in lowered, (
        f"agent phải giải thích giới hạn ngày dự báo: {answer!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 6. Không bao giờ bịa số liệu khi tool lỗi
# ─────────────────────────────────────────────────────────────────────────────


def test_tool_result_capture_is_not_vacuous(e2e_results):
    """Chốt chặn: nếu trích xuất kết quả tool trả về rỗng thì các assertion
    "chống bịa" ở trên sẽ VÔ NGHĨA. Test này bảo đảm harness thật sự thu được
    nội dung tool trả về."""
    results = e2e_results["results"]
    completed = [r for r in results if not r["errors"]]

    observed = 0
    for result in completed:
        for response in result["tool_responses"]:
            observed += 1
            assert str(response.get("result", "")).strip(), (
                f"kết quả tool '{response.get('name')}' rỗng "
                f"(raw_type={response.get('raw_type')}) — assertion chống bịa sẽ "
                "không kiểm tra được gì"
            )

    if observed:
        print(f"\n[E2E] đã thu {observed} kết quả tool (không rỗng)")
        return

    # observed == 0: không có gì để chốt. Nếu nguyên nhân là lỗi TẠM THỜI của môi
    # trường (key Gemini bị giới hạn IP) thì đây là "chưa xác minh được" → SKIP,
    # KHÔNG phải FAIL. Đã gặp thật: cả 5 câu đều 403 → 0 kết quả tool.
    errored = [r for r in results if r["errors"]]
    all_transient = bool(errored) and all(
        any(
            marker.lower() in " ".join(r["errors"]).lower()
            for marker in TRANSIENT_MARKERS
        )
        for r in errored
    )
    if all_transient:
        pytest.skip(
            f"mọi câu đều lỗi TẠM THỜI ({len(errored)}/{len(results)}) → không thu "
            "được kết quả tool nào để chốt. Đây KHÔNG phải PASS."
        )
    pytest.fail("không thu được kết quả tool nào dù các câu đều hoàn tất")


def test_agent_never_fabricates_when_tool_failed(e2e_results):
    """Nếu MỌI tool của một câu đều trả lỗi, câu trả lời KHÔNG được có số °C.

    Dựa trên cờ `is_error` do harness trích xuất từ KẾT QUẢ TOOL THẬT — không
    dùng heuristic từ khoá trong câu trả lời, nên không thể "pass may mắn".
    (Harness được kiểm chứng riêng trong `test_e2e_harness.py`.)
    """
    checked = 0
    for index, result in enumerate(e2e_results["results"]):
        responses = result["tool_responses"]
        if not responses:
            continue
        if not all(r.get("is_error") for r in responses):
            continue

        checked += 1
        answer = result["answer"]
        assert "°c" not in answer.lower(), (
            f"câu {index + 1}: tool trả LỖI nhưng agent vẫn đưa số liệu nhiệt độ "
            f"(dấu hiệu bịa): {answer!r}"
        )
        assert answer.strip(), f"câu {index + 1}: tool lỗi thì agent vẫn phải trả lời"

    print(f"\n[E2E] kiểm tra chống bịa: {checked} câu có tool lỗi")


def test_agent_reports_tool_failure_honestly(e2e_results):
    """Câu trả lời phải nói rõ không lấy được dữ liệu, không im lặng bỏ qua."""
    for index, result in enumerate(e2e_results["results"]):
        responses = result["tool_responses"]
        if not responses or not all(r.get("is_error") for r in responses):
            continue
        answer = result["answer"].lower()
        assert any(
            marker in answer
            for marker in (
                "không lấy được",
                "không thể",
                "chưa được cấu hình",
                "weatherapi_key",
                "lỗi",
                "xin lỗi",
            )
        ), f"câu {index + 1}: agent không báo lỗi trung thực: {result['answer']!r}"


def test_agent_uses_tool_data_when_tool_succeeded(e2e_results):
    """Chiều ngược lại: khi tool THÀNH CÔNG, dữ liệu phải chảy vào câu trả lời.

    KHÔNG kiểm tra literal "°C" — cách model diễn đạt thay đổi giữa các lần chạy
    (đã quan sát: có lần viết "29°C", có lần "29 độ C"), và test giòn như vậy sẽ
    fail ngẫu nhiên. Thay vào đó so khớp **giá trị nhiệt độ thật** lấy từ kết quả
    tool: câu trả lời phải nhắc lại ít nhất một giá trị đó.
    """
    checked = 0
    for index, result in enumerate(e2e_results["results"]):
        responses = result["tool_responses"]
        if not responses or any(r.get("is_error") for r in responses):
            continue
        if not any(
            r["name"] in ("get_current_weather", "get_forecast") for r in responses
        ):
            continue

        tool_text = " ".join(str(r.get("result", "")) for r in responses)
        tool_temps = {float(v) for v in _TEMP_RE.findall(tool_text)}
        if not tool_temps:
            continue

        checked += 1
        answer = result["answer"]
        answer_numbers = {float(v) for v in _NUMBER_RE.findall(answer)}
        assert tool_temps & answer_numbers, (
            f"câu {index + 1}: tool trả nhiệt độ {sorted(tool_temps)} nhưng câu trả lời "
            f"không dùng giá trị nào — agent có thể đã bỏ qua kết quả tool.\n"
            f"answer: {answer!r}\ntool: {tool_text[:200]!r}"
        )

    print(f"\n[E2E] kiểm tra dùng dữ liệu tool: {checked} câu")
    if e2e_results["mode"] == "mock-weatherapi":
        # Mock LUÔN thành công → 0 câu kiểm tra nghĩa là harness/agent hỏng,
        # chứ không phải "may mắn không cần kiểm tra".
        assert checked > 0, "chế độ mock mà không câu nào có tool thành công!"


def test_e2e_mode_is_reported(e2e_results):
    assert e2e_results["mode"] in ("real-weatherapi", "mock-weatherapi")
    if e2e_results["mode"] == "mock-weatherapi":
        print(
            "\n⚠️  Chế độ MOCK: luồng ADK→MCP→Gemini là thật, nhưng dữ liệu thời "
            "tiết KHÔNG phải real-time. Đặt WEATHERAPI_KEY để chạy chế độ thật."
        )


# ─────────────────────────────────────────────────────────────────────────────
# 7. Chế độ SUY GIẢM: server KHÔNG có upstream key → tool lỗi
#    Đây mới là nơi thật sự kiểm tra "không bịa dữ liệu khi tool lỗi".
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def degraded_results(tmp_path_factory):
    """Chạy 1 câu hỏi thời tiết khi MCP server có key KHÔNG hợp lệ.

    Cách ép suy giảm: truyền `WEATHERAPI_KEY` sai qua biến môi trường. Vì
    `load_dotenv(override=False)`, biến môi trường THẮNG `.env` — nên server
    chắc chắn dùng key sai, WeatherAPI trả 401, tool trả lỗi.

    (Bản trước chỉ xoá `WEATHERAPI_KEY` khỏi env, nhưng từ khi server tự nạp
    `.env` thì cách đó KHÔNG còn ép được suy giảm — bug thật đã gặp, xem
    reports/implementation-summary.md.)

    Khi đó agent BẮT BUỘC phải nói thật là không lấy được dữ liệu — tuyệt đối
    không được bịa nhiệt độ.
    """
    question = ["Thời tiết Hà Nội hôm nay thế nào?"]

    with spawn_mcp_server(WEATHERAPI_KEY="day26-invalid-key-for-degraded-test") as (
        url,
        ready,
        proc,
    ):
        if not ready:
            stderr = proc.stderr.read() if proc.stderr else ""
            pytest.fail(f"MCP server không khởi động được.\n{stderr[:2000]}")

        questions_file = tmp_path_factory.mktemp("e2e_degraded") / "q.json"
        questions_file.write_text(json.dumps(question, ensure_ascii=False), encoding="utf-8")

        env = {**os.environ, "MCP_SERVER_URL": url, "PYTHONIOENCODING": "utf-8"}
        completed = subprocess.run(
            [sys.executable, str(CLIENT_DIR / "tests" / "e2e_runner.py"), f"@{questions_file}"],
            cwd=str(CLIENT_DIR),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
        )

    lines = [
        line for line in (completed.stdout or "").splitlines() if line.strip().startswith("{")
    ]
    if not lines:
        pytest.fail(
            f"e2e_runner.py không in JSON.\nexit={completed.returncode}\n"
            f"--- stderr ---\n{(completed.stderr or '')[-2000:]}"
        )

    payload = json.loads(lines[-1])
    result = payload["results"][0]
    if result["errors"]:
        joined = " ".join(result["errors"]).lower()
        if any(marker.lower() in joined for marker in TRANSIENT_MARKERS):
            pytest.skip(
                "Không xác minh được chế độ suy giảm do lỗi TẠM THỜI của môi trường: "
                f"{result['errors'][-1][:160]}"
            )
        pytest.fail(f"Lỗi hệ thống ở chế độ suy giảm: {result['errors']}")

    print(f"\n[E2E degraded] tool results: {[r.get('result', '')[:90] for r in result['tool_responses']]}")
    print(f"[E2E degraded] is_error   : {[r.get('is_error') for r in result['tool_responses']]}")
    print(f"[E2E degraded] answer     : {result['answer'][:300]}")
    return result


def test_degraded_tool_actually_failed(degraded_results):
    """Tiền đề của test: tool PHẢI lỗi, nếu không test dưới là vô nghĩa."""
    responses = degraded_results["tool_responses"]
    assert responses, "agent phải gọi tool thời tiết"
    assert all(r.get("is_error") for r in responses), (
        f"key không hợp lệ thì tool phải lỗi, nhận được: {responses}"
    )


def test_degraded_agent_reports_honestly_and_never_fabricates(degraded_results):
    answer = degraded_results["answer"]
    lowered = answer.lower()

    assert answer.strip(), "agent phải trả lời"
    assert "°c" not in lowered, (
        f"tool LỖI nhưng agent vẫn đưa số liệu nhiệt độ — BỊA dữ liệu: {answer!r}"
    )
    assert any(
        marker in lowered
        for marker in (
            "không lấy được",
            "không thể",
            "chưa được cấu hình",
            "weatherapi_key",
            "lỗi",
            "từ chối",
        )
    ), f"agent phải báo trung thực là không lấy được dữ liệu: {answer!r}"
