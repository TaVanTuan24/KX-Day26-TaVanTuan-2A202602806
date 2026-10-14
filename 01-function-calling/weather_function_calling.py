"""Minh hoạ FUNCTION CALLING thuần với Google Gemini SDK.

Tool `get_weather` được định nghĩa schema thủ công VÀ thực thi ngay trong
chính file app này. Model chỉ QUYẾT ĐỊNH gọi tool nào; app mới là nơi chạy.

Cách chạy:
    pip install -r ../requirements.txt
    export GOOGLE_API_KEY=...   # hoặc GEMINI_API_KEY=...
    python weather_function_calling.py
    python weather_function_calling.py "Thời tiết Đà Nẵng thế nào?"

Ghi chú thiết kế (không phải production):
    - Dữ liệu thời tiết là MOCK. Đây là bài học minh hoạ cơ chế function
      calling, không phải một weather service thật. Muốn dữ liệu thật xem
      `04-lab/`.
    - Không có API key thì script chạy chế độ offline (in rõ nhãn) để vẫn
      demo được vòng lặp, nhưng KHÔNG gọi model.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable

from google import genai
from google.genai import types

# Console Windows mặc định dùng cp1252 → in tiếng Việt sẽ UnicodeEncodeError.
# Ép stdout/stderr sang UTF-8 (an toàn cả khi bị pipe).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _load_dotenv_if_available() -> None:
    """Nạp `.env` ở thư mục repo nếu python-dotenv có sẵn.

    Không bắt buộc: thiếu python-dotenv thì bỏ qua và dùng biến môi trường
    đã export như bình thường.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    from pathlib import Path

    for candidate in (
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parent / ".env",
    ):
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            return


_load_dotenv_if_available()

MODEL = "gemini-2.5-flash"

# Giới hạn số vòng "model yêu cầu tool → app thực thi → trả kết quả".
# Chặn vòng lặp vô hạn khi model liên tục đòi gọi tool.
MAX_TOOL_ROUNDS = 5

SYSTEM_INSTRUCTION = (
    "Bạn là trợ lý thời tiết thân thiện, LUÔN trả lời bằng tiếng Việt tự nhiên. "
    "Dùng emoji phù hợp (🌧️ 🌤️ 💨 💧). "
    "Tóm tắt ngắn gọn, dễ hiểu, và đưa ra lời khuyên thực tế "
    "(ví dụ: mang ô, mặc áo mỏng, ...). "
    "Chỉ được dùng dữ liệu do tool get_weather trả về; TUYỆT ĐỐI không tự bịa "
    "nhiệt độ hay điều kiện thời tiết. Nếu tool báo lỗi, hãy nói thật là chưa "
    "lấy được dữ liệu."
)


def get_client() -> "genai.Client | None":
    """Khởi tạo client chỉ khi đã có API key; trả về None nếu chưa cấu hình."""
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


# 1. App tự định nghĩa schema của tool (viết tay — điểm yếu của cách này)
get_weather_declaration = types.FunctionDeclaration(
    name="get_weather",
    description="Lấy thời tiết hiện tại của một thành phố",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "city": types.Schema(
                type=types.Type.STRING,
                description="Tên thành phố, ví dụ: Hà Nội, Đà Nẵng, Hồ Chí Minh",
            )
        },
        required=["city"],
    ),
)

TOOLS = [types.Tool(function_declarations=[get_weather_declaration])]

# Dữ liệu MOCK — chỉ để minh hoạ. Key là tên chuẩn hoá (lowercase, bỏ dấu).
_MOCK_DB: dict[str, dict[str, Any]] = {
    "ha noi": {
        "nhiệt_độ": "29°C",
        "thời_tiết": "trời mưa nhẹ",
        "độ_ẩm": "82%",
        "gió": {"hướng": "Đông Nam", "tốc_độ": "12 km/h"},
    },
    "ho chi minh": {
        "nhiệt_độ": "33°C",
        "thời_tiết": "mưa rào",
        "độ_ẩm": "75%",
        "gió": {"hướng": "Tây Nam", "tốc_độ": "15 km/h"},
    },
    "da nang": {
        "nhiệt_độ": "30°C",
        "thời_tiết": "nhiều mây",
        "độ_ẩm": "78%",
        "gió": {"hướng": "Đông", "tốc_độ": "10 km/h"},
    },
}

# Alias → tên chuẩn hoá, để model gọi "Hanoi"/"Ha Noi" vẫn khớp mock data.
_CITY_ALIASES = {
    "hà nội": "ha noi",
    "ha noi": "ha noi",
    "hanoi": "ha noi",
    "hồ chí minh": "ho chi minh",
    "ho chi minh": "ho chi minh",
    "tp. hồ chí minh": "ho chi minh",
    "tp hồ chí minh": "ho chi minh",
    "sài gòn": "ho chi minh",
    "sai gon": "ho chi minh",
    "saigon": "ho chi minh",
    "hcm": "ho chi minh",
    "đà nẵng": "da nang",
    "da nang": "da nang",
    "danang": "da nang",
}


def _normalize_city(city: str) -> str:
    return _CITY_ALIASES.get(city.strip().casefold().replace("  ", " "), city.strip().casefold())


# 2. App tự thực thi tool (trong thực tế sẽ gọi API thời tiết thật)
def get_weather(city: str) -> str:
    """Trả về thời tiết (mock) của *city*. Dùng làm tool cho model."""
    if not isinstance(city, str) or not city.strip():
        return json.dumps(
            {"city": city, "error": "tên thành phố không hợp lệ"},
            ensure_ascii=False,
        )
    response = {
        "city": city,
        "nhiệt_độ": "28°C",
        "thời_tiết": "không có dữ liệu chi tiết",
        "độ_ẩm": "không rõ",
        "gió": {"hướng": "không rõ", "tốc_độ": "không rõ"},
    }
    response.update(_MOCK_DB.get(_normalize_city(city), {}))
    return json.dumps(response, ensure_ascii=False)


# 3. Bảng dispatch: model trả về TÊN hàm dạng chuỗi → app tra ra hàm thật.
TOOL_FUNCTIONS: dict[str, Callable[..., str]] = {
    "get_weather": get_weather,
}


class MaxToolRoundsExceeded(RuntimeError):
    """Model yêu cầu gọi tool quá số vòng cho phép."""


def execute_function_call(name: str | None, args: dict[str, Any] | None) -> str:
    """Thực thi function mà model yêu cầu, có kiểm tra tên + tham số.

    Luôn trả về CHUỖI JSON (kể cả khi lỗi) thay vì raise, để model nhận được
    thông tin lỗi và tự giải thích cho người dùng ở vòng tiếp theo.
    """
    if not name:
        return json.dumps({"error": "model không cung cấp tên function"}, ensure_ascii=False)

    func = TOOL_FUNCTIONS.get(name)
    if func is None:
        return json.dumps(
            {
                "error": f"function '{name}' không tồn tại",
                "available_functions": sorted(TOOL_FUNCTIONS),
            },
            ensure_ascii=False,
        )

    try:
        return func(**(args or {}))
    except TypeError as exc:
        # Thiếu tham số bắt buộc / thừa tham số / sai kiểu
        return json.dumps(
            {"error": f"tham số không hợp lệ cho '{name}': {exc}"},
            ensure_ascii=False,
        )
    except Exception as exc:  # noqa: BLE001 - tool của người dùng có thể lỗi bất kỳ
        return json.dumps(
            {"error": f"function '{name}' lỗi: {type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )


def _scrub_secrets(text: str) -> str:
    """Loại API key khỏi text trước khi in ra (phòng trường hợp SDK echo lại)."""
    for env_name in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
        secret = os.getenv(env_name)
        if secret:
            text = text.replace(secret, "***REDACTED***")
    return text


def _format_api_error(exc: BaseException) -> str:
    """Thông báo lỗi gọi Gemini API — không bao giờ lộ API key."""
    detail = _scrub_secrets(str(exc)).replace("\n", " ")
    if len(detail) > 300:
        detail = detail[:300] + "…"
    return (
        "❌ Không gọi được Gemini API.\n"
        f"   Loại lỗi: {type(exc).__name__}\n"
        f"   Chi tiết: {detail}\n"
        "   Kiểm tra: API key hợp lệ, đã bật Generative Language API, "
        "và máy này không bị chặn bởi hạn chế IP của key."
    )


def _extract_cities(prompt: str) -> list[str]:
    """Trích ra tên thành phố có trong prompt dựa trên dữ liệu mock."""
    normalized_prompt = prompt.casefold()
    found = []
    for alias, canonical in _CITY_ALIASES.items():
        if alias in normalized_prompt and canonical not in found:
            found.append(canonical)
    return found


def _offline_weather_answer(prompt: str) -> str:
    """Phản hồi khi KHÔNG có API key.

    Cố tình ghi rõ đây là chế độ offline + dữ liệu mock, để không ai nhầm là
    model Gemini đã trả lời.
    """
    canonical = _extract_cities(prompt) or ["ha noi"]
    display = {
        "ha noi": "Hà Nội",
        "ho chi minh": "Hồ Chí Minh",
        "da nang": "Đà Nẵng",
    }
    lines = ["[OFFLINE — chưa có GOOGLE_API_KEY/GEMINI_API_KEY, không gọi Gemini]", ""]
    for name in canonical:
        data = json.loads(get_weather(display.get(name, name)))
        advice = "mang ô" if "mưa" in data["thời_tiết"] else "mặc áo mỏng"
        lines.append(
            f"{data['city']}: {data['nhiệt_độ']}, {data['thời_tiết']} 🌤️ "
            f"(dữ liệu MOCK, không phải real-time). "
            f"Độ ẩm {data['độ_ẩm']}, gió {data['gió']['hướng']} {data['gió']['tốc_độ']}. "
            f"Khuyên nên {advice}."
        )
    return "\n".join(lines)


_UNSET = object()


def run(
    prompt: str,
    *,
    max_tool_rounds: int = MAX_TOOL_ROUNDS,
    client: Any = _UNSET,
) -> str:
    """Gửi *prompt* tới Gemini, tự xử lý function calling, trả câu trả lời cuối.

    Args:
        prompt: Câu hỏi của người dùng.
        max_tool_rounds: Số vòng gọi tool tối đa (chặn vòng lặp vô hạn).
        client: Test có thể bơm client giả. Bỏ trống → dùng client toàn cục;
            truyền `None` → ép chạy chế độ offline.
    """
    active_client = globals().get("client") if client is _UNSET else client
    if active_client is None:
        return _offline_weather_answer(prompt)

    contents: list[types.Content] = [
        types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
    ]
    config = types.GenerateContentConfig(
        tools=TOOLS,
        system_instruction=SYSTEM_INSTRUCTION,
    )

    for round_index in range(max_tool_rounds + 1):
        try:
            resp = active_client.models.generate_content(
                model=MODEL, contents=contents, config=config
            )
        except Exception as exc:  # noqa: BLE001 - lỗi mạng/quota/key đều phải báo
            return _format_api_error(exc)

        function_calls = list(resp.function_calls or [])

        # Không còn yêu cầu tool → đây là câu trả lời cuối.
        if not function_calls:
            text = getattr(resp, "text", None)
            if text:
                return text
            return (
                "❌ Model không trả về nội dung (có thể bị chặn bởi safety filter "
                "hoặc finish_reason khác STOP)."
            )

        # Đã dùng hết số vòng cho phép → dừng, không chạy tool nữa.
        if round_index >= max_tool_rounds:
            raise MaxToolRoundsExceeded(
                f"Model yêu cầu gọi tool quá {max_tool_rounds} vòng. Dừng để tránh "
                "vòng lặp vô hạn."
            )

        # Thêm phản hồi (function_call) của model vào lịch sử hội thoại.
        if resp.candidates:
            contents.append(resp.candidates[0].content)

        # APP thực thi từng function được yêu cầu — hỗ trợ NHIỀU call một lượt.
        function_responses: list[types.Part] = []
        for fc in function_calls:
            args = dict(fc.args or {})
            print(f"  [model yêu cầu] {fc.name}({args})")
            result = execute_function_call(fc.name, args)
            print(f"  [app thực thi]  -> {result}")
            function_responses.append(
                types.Part.from_function_response(
                    name=fc.name or "unknown", response={"result": result}
                )
            )

        # Gửi kết quả tool trả về cho model.
        # google-genai dùng role="user" cho function response
        # (xác nhận từ google/genai/chats.py trong SDK).
        contents.append(types.Content(role="user", parts=function_responses))

    raise MaxToolRoundsExceeded(  # pragma: no cover - phòng vệ, vòng for đã chặn
        f"Vượt quá {max_tool_rounds} vòng gọi tool."
    )


client = get_client()


if __name__ == "__main__":
    question = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "Thời tiết Hà Nội và Đà Nẵng hôm nay thế nào?"
    )
    print(f"User: {question}\n")
    if client is None:
        print(
            "⚠️  Chưa có GOOGLE_API_KEY/GEMINI_API_KEY → chạy chế độ OFFLINE "
            "(dữ liệu mock, không gọi model).\n"
        )
    try:
        print("Trả lời:\n", run(question))
    except MaxToolRoundsExceeded as exc:
        print(f"❌ {exc}")
        sys.exit(1)
