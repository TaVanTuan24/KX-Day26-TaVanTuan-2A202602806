"""Chạy agent ADK cho danh sách câu hỏi và in kết quả JSON.

Được `test_e2e_agent.py` gọi như một TIẾN TRÌNH RIÊNG. Chạy riêng cũng được:

    cd 04-lab/mcp-client
    uv run python tests/e2e_runner.py '["Thời tiết Hà Nội hôm nay thế nào?"]'
    uv run python tests/e2e_runner.py @questions.json      # tránh vấn đề quoting của shell

Vì sao chạy tiến trình riêng? `weather_agent/agent.py` đọc `MCP_SERVER_URL`
tại thời điểm import, nên đổi biến môi trường sau khi import là vô nghĩa.
Một tiến trình sạch bảo đảm cấu hình đúng như người dùng thật.

Đầu ra (stdout, JSON):
    {"ok": bool, "results": [{"question", "answer", "tool_calls", "tool_responses", "errors"}]}
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

CLIENT_DIR = Path(__file__).resolve().parents[1]   # .../04-lab/mcp-client
if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))

DEFAULT_QUESTIONS = [
    "Thời tiết Hà Nội hôm nay thế nào?",
    "Dự báo Đà Nẵng trong 3 ngày tới.",
    "So sánh thời tiết Hà Nội và TP. Hồ Chí Minh.",
    "MCP Server hiện có hoạt động không?",
    "Dự báo thời tiết -2 ngày tới.",
]

# Dấu hiệu lỗi TẠM THỜI của môi trường (không phải lỗi logic của agent):
# key Gemini bị giới hạn IP, và IP egress của máy có thể đổi giữa các request.
TRANSIENT_MARKERS = (
    "ip address restriction",
    "API_KEY_IP_ADDRESS_BLOCKED",
    "RESOURCE_EXHAUSTED",
    "429",
)
MAX_ATTEMPTS = int(os.getenv("E2E_MAX_ATTEMPTS", "12"))
# Lỗi 403 IP trả về ngay lập tức, nên nghỉ ngắn để thử lại nhanh — nghỉ dài chỉ
# làm test chậm mà không tăng xác suất thành công.
RETRY_SLEEP_SECONDS = float(os.getenv("E2E_RETRY_SLEEP", "0.5"))


def _blocks_to_text(blocks) -> str:
    texts: list[str] = []
    for block in blocks or []:
        text = getattr(block, "text", None)
        if text is None and isinstance(block, dict):
            text = block.get("text")
        if text:
            texts.append(str(text))
    return "\n".join(texts)


def _extract_tool_result(response) -> tuple[str, bool]:
    """Rút (text, is_error) khỏi FunctionResponse của ADK.

    ADK bọc kết quả MCP theo nhiều dạng: `{'result': '<str>'}`, hoặc
    `{'result': <CallToolResult dict>}`, hoặc list Content. Phải xử lý hết —
    nếu trả về chuỗi rỗng hoặc JSON bọc ngoài, assertion "không bịa dữ liệu"
    sẽ VÔ NGHĨA (không phát hiện được cả trường hợp tool lỗi).
    """
    payload = getattr(response, "response", None)
    if payload is None:
        return "", False

    is_error = False
    if isinstance(payload, dict):
        if "error" in payload and "result" not in payload:
            payload = payload["error"]
            is_error = True
        elif "result" in payload:
            payload = payload["result"]

    if isinstance(payload, str):
        return payload, is_error or payload.strip().startswith("❌")

    # dict dạng {"content": [{"type":"text","text":...}], "structuredContent": ...}
    if isinstance(payload, dict):
        if isinstance(payload.get("isError"), bool):
            is_error = is_error or payload["isError"]
        elif isinstance(payload.get("is_error"), bool):
            is_error = is_error or payload["is_error"]
        text = _blocks_to_text(payload.get("content"))
        if text:
            return text, is_error or text.strip().startswith("❌")

    # đối tượng CallToolResult hoặc list Content
    content = getattr(payload, "content", None)
    if content is None and isinstance(payload, (list, tuple)):
        content = payload
    if content:
        text = _blocks_to_text(content)
        if text:
            return text, is_error or text.strip().startswith("❌")

    return json.dumps(payload, ensure_ascii=False, default=str), is_error


async def ask(runner, app_name: str, user_id: str, question: str) -> dict:
    from google.genai import types

    session = await runner.session_service.create_session(
        app_name=app_name, user_id=user_id
    )

    tool_calls: list[dict] = []
    tool_responses: list[dict] = []
    final_texts: list[str] = []
    errors: list[str] = []

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text=question)]),
    ):
        if getattr(event, "error_code", None):
            errors.append(f"{event.error_code}: {getattr(event, 'error_message', '')}")

        for call in event.get_function_calls() or []:
            tool_calls.append({"name": call.name, "args": dict(call.args or {})})
        for response in event.get_function_responses() or []:
            text, is_error = _extract_tool_result(response)
            tool_responses.append(
                {
                    "name": response.name,
                    "result": text[:600],
                    "is_error": is_error,
                    # Chẩn đoán: chứng minh việc trích xuất là thật, không rỗng giả.
                    "raw_type": type(getattr(response, "response", None)).__name__,
                }
            )

        if event.is_final_response() and event.content and event.content.parts:
            text = "".join(getattr(part, "text", "") or "" for part in event.content.parts)
            if text.strip():
                final_texts.append(text.strip())

    return {
        "question": question,
        "answer": "\n".join(final_texts).strip(),
        "tool_calls": tool_calls,
        "tool_responses": tool_responses,
        "errors": errors,
    }


def _is_transient(errors: list[str]) -> bool:
    joined = " ".join(errors).lower()
    return any(marker.lower() in joined for marker in TRANSIENT_MARKERS)


async def ask_with_retries(runner, app_name: str, user_id: str, question: str) -> dict:
    """Gọi agent, retry CHỈ khi lỗi là tạm thời (IP allow-list / quota).

    Lỗi logic (agent không gọi tool, trả lời sai...) KHÔNG được retry — nếu
    retry cả những lỗi đó thì test sẽ che mất lỗi thật.
    """
    last: dict = {}
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            last = await ask(runner, app_name, user_id, question)
        except Exception as exc:  # noqa: BLE001
            last = {
                "question": question,
                "answer": "",
                "tool_calls": [],
                "tool_responses": [],
                "errors": [f"{type(exc).__name__}: {exc}"],
            }

        if not last["errors"]:
            last["attempts"] = attempt
            return last
        if not _is_transient(last["errors"]):
            last["attempts"] = attempt
            return last

        await asyncio.sleep(RETRY_SLEEP_SECONDS)

    last["attempts"] = MAX_ATTEMPTS
    last["errors"].append(
        f"Đã thử {MAX_ATTEMPTS} lần nhưng vẫn lỗi tạm thời "
        "(key Gemini bị giới hạn IP / hết quota)."
    )
    return last


async def main() -> int:
    questions = DEFAULT_QUESTIONS
    if len(sys.argv) > 1:
        raw = sys.argv[1]
        # Hỗ trợ "@duong/dan/questions.json" để tránh shell làm hỏng dấu ngoặc kép
        # (PowerShell trên Windows rất dễ strip quote khi truyền JSON qua argv).
        # utf-8-sig: nhiều công cụ Windows ghi kèm BOM.
        if raw.startswith("@"):
            raw = Path(raw[1:]).read_text(encoding="utf-8-sig")
        questions = json.loads(raw)

    from google.adk.runners import InMemoryRunner  # noqa: PLC0415
    from weather_agent import root_agent  # noqa: PLC0415

    app_name = "weather_agent"
    runner = InMemoryRunner(agent=root_agent, app_name=app_name)

    results: list[dict] = []
    try:
        for question in questions:
            results.append(await ask_with_retries(runner, app_name, "e2e-user", question))
    finally:
        close = getattr(runner, "close", None)
        if close is not None:
            try:
                await close()
            except Exception:  # noqa: BLE001
                pass

    ok = all(not result["errors"] for result in results)
    print(json.dumps({"ok": ok, "results": results}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
