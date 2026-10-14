#!/usr/bin/env python3
"""Xác minh cấu hình Weather Agent — phân tầng rõ ràng, không tô hồng kết quả.

Script này thay thế bản cũ vốn coi "HTTP GET trả về status < 500" là
"MCP server OK". Điều đó SAI: một web server bất kỳ cũng trả < 500.

Các tầng được kiểm tra ĐỘC LẬP:

    1. Environment        biến môi trường / vị trí .env
    2. Dependencies       các package mà code THỰC SỰ import
    3. Agent structure    file + import root_agent + toolset được gắn
    4. HTTP reachable     chỉ tầng transport — KHÔNG chứng minh MCP chạy
    5. MCP handshake      initialize thật qua ADK McpToolset
    6. Tool discovery     list_tools thật, đối chiếu 3 tool mong đợi
    7. Tool invocation    gọi health_check() thật qua MCP client
    8. WeatherAPI         gọi get_current_weather() — cần WEATHERAPI_KEY
    9. Gemini API         gọi thử model — cần GOOGLE_API_KEY còn hiệu lực

Mỗi tầng có 4 trạng thái: PASS / FAIL / WARN / NOT VERIFIED.
KHÔNG có chuyện "suy ra PASS" từ tầng thấp hơn.

Cách chạy:
    cd 04-lab/mcp-client
    uv run python verify_setup.py                # kiểm tra đầy đủ
    uv run python verify_setup.py --no-network   # bỏ qua tầng 9 (không gọi Gemini)

Mã thoát: 0 nếu không có FAIL; 1 nếu có ít nhất một FAIL.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

CLIENT_DIR = Path(__file__).resolve().parent            # .../04-lab/mcp-client
REPO_ROOT = CLIENT_DIR.parents[1]                       # repo root
AGENT_DIR = CLIENT_DIR / "weather_agent"

if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))

import env_setup  # noqa: E402  (cùng nguồn cấu hình với weather_agent/agent.py)

PASS, FAIL, WARN, NOT_VERIFIED = "PASS", "FAIL", "WARN", "NOT VERIFIED"
ICON = {PASS: "✅", FAIL: "❌", WARN: "⚠️ ", NOT_VERIFIED: "➖"}

EXPECTED_TOOLS = {"get_current_weather", "get_forecast", "health_check"}
VERIFY_TIMEOUT = float(os.getenv("VERIFY_TIMEOUT", "30"))


@dataclass
class Result:
    level: str
    status: str
    detail: str = ""
    lines: list[str] = field(default_factory=list)


RESULTS: list[Result] = []


def record(level: str, status: str, detail: str = "", lines: list[str] | None = None) -> Result:
    result = Result(level, status, detail, lines or [])
    RESULTS.append(result)
    return result


def load_env() -> list[Path]:
    """Cùng thứ tự ưu tiên như weather_agent/agent.py (dùng chung env_setup)."""
    return env_setup.load_environment()


# ── 1. Environment ──────────────────────────────────────────────────────────
def check_environment() -> None:
    loaded = load_env()
    google_key = env_setup.google_api_key() or ""
    server_url = os.getenv("MCP_SERVER_URL", "http://localhost:8085/mcp")

    lines = [
        f".env đã nạp: {[str(p) for p in loaded] or 'KHÔNG CÓ'}",
        f"MCP_SERVER_URL = {server_url}",
        f"Khoá Gemini = {'đã có (len=%d, nguồn: %s)' % (len(google_key), env_setup.KEY_SOURCE) if google_key else 'THIẾU'}",
    ]
    if not google_key:
        record(
            "1. Environment",
            FAIL,
            "Thiếu GOOGLE_API_KEY/GEMINI_API_KEY → agent không gọi được model",
            lines + ["   Đặt trong 04-lab/mcp-client/.env (xem .env.example)"],
        )
        return

    status = PASS if loaded else WARN
    detail = "" if loaded else "Không thấy file .env nào (đang dùng biến môi trường sẵn có)"
    record("1. Environment", status, detail, lines)


# ── 2. Dependencies ─────────────────────────────────────────────────────────
def check_dependencies() -> None:
    import importlib
    from importlib.metadata import PackageNotFoundError, version

    # Đây là những gì code THỰC SỰ import — không phải danh sách mong muốn.
    modules = [
        ("google.adk", "google-adk"),
        ("google.adk.tools.mcp_tool.mcp_toolset", "google-adk"),
        ("google.genai", "google-genai"),
        ("mcp", "mcp"),
        ("mcp.client.streamable_http", "mcp"),
        ("httpx", "httpx"),
        ("dotenv", "python-dotenv"),
    ]

    lines = [f"python: {sys.executable}", f"       {sys.version.split()[0]}"]
    failed = []
    for module_name, package in modules:
        try:
            importlib.import_module(module_name)
            try:
                lines.append(f"  ✅ {module_name} ({package}=={version(package)})")
            except PackageNotFoundError:  # pragma: no cover
                lines.append(f"  ✅ {module_name} (package {package}: không rõ version)")
        except Exception as exc:  # noqa: BLE001
            failed.append(module_name)
            lines.append(f"  ❌ {module_name}: {type(exc).__name__}: {exc}")

    if failed:
        record(
            "2. Dependencies",
            FAIL,
            f"Thiếu/không import được: {', '.join(failed)}",
            lines + ["   Cài lại: cd 04-lab/mcp-client && uv sync"],
        )
        return

    record("2. Dependencies", PASS, "Mọi package mà code import đều có mặt", lines)


# ── 3. Agent structure ──────────────────────────────────────────────────────
def check_agent_structure() -> None:
    required = [AGENT_DIR / "agent.py", AGENT_DIR / "__init__.py", CLIENT_DIR / "pyproject.toml"]
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        record("3. Agent structure", FAIL, f"Thiếu file: {missing}")
        return

    try:
        sys.path.insert(0, str(CLIENT_DIR))
        from weather_agent import root_agent  # noqa: PLC0415
        from weather_agent import agent as agent_module
    except Exception as exc:  # noqa: BLE001
        record("3. Agent structure", FAIL, f"Import root_agent lỗi: {type(exc).__name__}: {exc}")
        return

    tools = list(getattr(root_agent, "tools", []) or [])
    lines = [
        f"root_agent.name = {root_agent.name}",
        f"root_agent.model = {root_agent.model}",
        f"agent.tools = {len(tools)} phần tử",
        f"instruction: {'có' if getattr(root_agent, 'instruction', None) else 'THIẾU'}",
    ]

    if getattr(root_agent, "instruction", None) and "bịa" in str(root_agent.instruction):
        lines.append("  ✅ instruction cấm bịa số liệu thời tiết")

    if not tools:
        record(
            "3. Agent structure",
            FAIL,
            "Agent KHÔNG có tool — đang ở chế độ fallback (xem log khởi tạo)",
            lines,
        )
        return

    record(
        "3. Agent structure",
        PASS,
        "Agent import được và đã gắn McpToolset",
        lines
        + [
            "  ℹ️  Việc gắn toolset KHÔNG chứng minh kết nối — tầng 5 mới kiểm tra thật.",
        ],
    )


# ── 4. HTTP reachable (chỉ tầng transport) ──────────────────────────────────
def check_http_reachable(url: str) -> tuple[bool, str]:
    import httpx

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "verify_setup", "version": "1.0"},
        },
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=VERIFY_TIMEOUT)
    except httpx.RequestError as exc:
        record(
            "4. HTTP reachable",
            FAIL,
            f"Không kết nối được {url} ({type(exc).__name__})",
            ["   Khởi động server: cd ../mcp-server && uv run python weather.py"],
        )
        return False, ""

    if response.status_code >= 500:
        record(
            "4. HTTP reachable",
            FAIL,
            f"HTTP {response.status_code} từ {url}",
        )
        return False, response.text[:300]

    record(
        "4. HTTP reachable",
        PASS,
        f"HTTP {response.status_code} — CHỈ là tầng transport",
        [
            "  ⚠️  KHÔNG suy ra MCP hoạt động từ tầng này. Xem tầng 5–6.",
            f"  body: {response.text[:160]!r}",
        ],
    )
    return True, response.text


# ── 5+6. MCP handshake và tool discovery qua ĐÚNG đường ADK dùng ────────────
async def _adk_discover(url: str, timeout: float) -> tuple[list[str] | None, str]:
    from google.adk.tools.mcp_tool.mcp_toolset import (  # noqa: PLC0415
        McpToolset,
        StreamableHTTPConnectionParams,
    )

    toolset = McpToolset(
        connection_params=StreamableHTTPConnectionParams(url=url, timeout=timeout),
        errlog=sys.stderr,
    )
    try:
        tools = await asyncio.wait_for(toolset.get_tools(), timeout=timeout)
        return [t.name for t in tools], ""
    except asyncio.TimeoutError:
        return None, f"Timeout {timeout:g}s khi get_tools()"
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {str(exc)[:200]}"
    finally:
        try:
            await toolset.close()
        except Exception:  # noqa: BLE001, S110 - cleanup không được làm hỏng báo cáo
            pass


# ── 7+8. Gọi tool thật qua MCP client thuần ─────────────────────────────────
async def _raw_call(url: str, tool: str, args: dict, timeout: float) -> tuple[str | None, str]:
    """Gọi tool qua MCP client thuần (không qua ADK) để kiểm tra ĐỘC LẬP.

    Dùng `streamable_http_client` + `create_mcp_http_client` — API không bị
    deprecated trong mcp 1.28.1. Lưu ý: ở mcp 1.x, `create_mcp_http_client`
    nhận `httpx.Timeout` (httpx thật), KHÁC mcp 2.x vốn dùng httpx2.
    """
    import httpx  # noqa: PLC0415
    from mcp import ClientSession  # noqa: PLC0415
    from mcp.client.streamable_http import (  # noqa: PLC0415
        create_mcp_http_client,
        streamable_http_client,
    )

    http_client = create_mcp_http_client(timeout=httpx.Timeout(timeout))
    try:
        async with http_client:
            async with streamable_http_client(url, http_client=http_client) as (
                read,
                write,
                _get_session_id,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool, args)
                    is_error = bool(
                        getattr(result, "isError", getattr(result, "is_error", False))
                    )
                    text = "\n".join(
                        getattr(block, "text", "") for block in (result.content or [])
                    )
                    if is_error:
                        return None, f"tool error: {text[:200]}"
                    return text, ""
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {str(exc)[:200]}"


# ── 9. Gemini API ───────────────────────────────────────────────────────────
def check_gemini(model: str, enabled: bool) -> None:
    key = env_setup.google_api_key() or ""
    if not key:
        record("9. Gemini API", NOT_VERIFIED, "Thiếu GOOGLE_API_KEY/GEMINI_API_KEY")
        return
    if not enabled:
        record("9. Gemini API", NOT_VERIFIED, "Bỏ qua do --no-network")
        return

    try:
        from google import genai  # noqa: PLC0415

        client = genai.Client(api_key=key)
        response = client.models.generate_content(model=model, contents="Trả lời đúng một từ: OK")
        text = (getattr(response, "text", "") or "").strip()
        if not text:
            record("9. Gemini API", FAIL, "Model trả về nội dung rỗng")
            return
        record(
            "9. Gemini API",
            PASS,
            f"gọi được {model}",
            [f"  phản hồi: {text[:60]!r}"],
        )
    except Exception as exc:  # noqa: BLE001
        message = str(exc).replace(key, "***REDACTED***")
        hint = ""
        if "IP address restriction" in message:
            hint = "  → Key bị giới hạn IP; máy này không nằm trong danh sách cho phép."
        elif "API_KEY_INVALID" in message or "API key not valid" in message:
            hint = "  → Key không hợp lệ."
        elif "quota" in message.lower() or "429" in message:
            hint = "  → Hết quota / bị rate limit."
        record(
            "9. Gemini API",
            NOT_VERIFIED,
            f"Không gọi được model: {type(exc).__name__}",
            [f"  {message[:220]}"] + ([hint] if hint else []),
        )


# ── Điều phối ───────────────────────────────────────────────────────────────
async def run_checks(with_network: bool) -> int:
    print("=" * 68)
    print("Weather Agent — Verification (phân tầng, không suy diễn)")
    print("=" * 68)

    check_environment()
    check_dependencies()
    check_agent_structure()

    server_url = os.getenv("MCP_SERVER_URL", "http://localhost:8085/mcp")
    reachable, _ = check_http_reachable(server_url)

    discovered: list[str] | None = None
    if reachable:
        discovered, error = await _adk_discover(server_url, VERIFY_TIMEOUT)
        if discovered is None:
            record(
                "5. MCP handshake",
                FAIL,
                f"ADK McpToolset không bắt tay được với {server_url}",
                [f"  {error}"],
            )
            record("6. Tool discovery", NOT_VERIFIED, "Không bắt tay được nên không khám phá tool")
        else:
            record(
                "5. MCP handshake",
                PASS,
                "ADK McpToolset initialize + list_tools thành công",
                [f"  tools nhận được: {discovered}"],
            )
            missing = EXPECTED_TOOLS - set(discovered)
            if missing:
                record(
                    "6. Tool discovery",
                    FAIL,
                    f"Thiếu tool: {sorted(missing)} (mong đợi {sorted(EXPECTED_TOOLS)})",
                )
            else:
                record(
                    "6. Tool discovery",
                    PASS,
                    "Đủ 3 tool mong đợi",
                )
    else:
        record("5. MCP handshake", NOT_VERIFIED, "Server không reachable")
        record("6. Tool discovery", NOT_VERIFIED, "Server không reachable")

    # 7. Gọi tool thật
    health_text = None
    key_configured: bool | None = None
    if reachable:
        health_text, error = await _raw_call(server_url, "health_check", {}, VERIFY_TIMEOUT)
        if health_text is None:
            record("7. Tool invocation", FAIL, f"health_check() thất bại: {error}")
        else:
            try:
                payload = json.loads(health_text)
                key_configured = bool(payload.get("weatherapi_key_configured"))
                record(
                    "7. Tool invocation",
                    PASS if payload.get("status") == "ok" else FAIL,
                    "health_check() gọi được và trả JSON hợp lệ",
                    [
                        f"  status={payload.get('status')} "
                        f"transport={payload.get('transport')} "
                        f"weatherapi_key_configured={key_configured}"
                    ],
                )
            except json.JSONDecodeError:
                record(
                    "7. Tool invocation",
                    FAIL,
                    "health_check() trả về nội dung không phải JSON",
                    [f"  {health_text[:160]}"],
                )
    else:
        record("7. Tool invocation", NOT_VERIFIED, "Server không reachable")

    # 8. WeatherAPI — chỉ PASS khi có DỮ LIỆU THẬT
    if not reachable:
        record("8. WeatherAPI", NOT_VERIFIED, "Server không reachable")
    elif key_configured is False:
        record(
            "8. WeatherAPI",
            NOT_VERIFIED,
            "WEATHERAPI_KEY chưa được cấu hình trên MCP server",
            [
                "  → Đặt WEATHERAPI_KEY cho TIẾN TRÌNH SERVER rồi chạy lại.",
                "  → Không được coi là PASS: chưa có dữ liệu real-time nào được xác minh.",
            ],
        )
    else:
        text, error = await _raw_call(
            server_url, "get_current_weather", {"city": "Hanoi"}, VERIFY_TIMEOUT
        )
        if text is None:
            record("8. WeatherAPI", FAIL, f"get_current_weather() lỗi: {error}")
        elif text.strip().startswith("❌"):
            record(
                "8. WeatherAPI",
                FAIL,
                "Server KHÔNG lấy được dữ liệu thật từ WeatherAPI",
                [f"  {text.strip()[:220]}"],
            )
        else:
            record(
                "8. WeatherAPI",
                PASS,
                "Lấy được dữ liệu thời tiết THẬT qua MCP",
                [f"  {text.strip().splitlines()[0][:160]}"],
            )

    # 9. Gemini
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    check_gemini(model, with_network)

    # ── In kết quả ──────────────────────────────────────────────────────
    print()
    for result in RESULTS:
        print(f"{ICON[result.status]} [{result.status:<12}] {result.level}")
        if result.detail:
            print(f"      {result.detail}")
        for line in result.lines:
            print(f"      {line}"
                  if not line.startswith("  ") else f"    {line}")
        print()

    counts = {status: sum(1 for r in RESULTS if r.status == status) for status in ICON}
    print("=" * 68)
    print(
        "Tổng kết: "
        + "  ".join(f"{ICON[s]} {s}={counts[s]}" for s in (PASS, FAIL, WARN, NOT_VERIFIED))
    )

    not_verified = [
        r.level for r in RESULTS if r.status in (NOT_VERIFIED, WARN) 
    ]
    if not_verified:
        print("\n⚠️  Chưa xác minh / cần chú ý: " + ", ".join(not_verified))
        print("   Những tầng này KHÔNG được coi là đã PASS.")
    if counts[FAIL]:
        print("\n❌ Có tầng FAIL — xem chi tiết ở trên.")
    print("=" * 68)

    return 1 if counts[FAIL] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Xác minh Weather Agent setup")
    parser.add_argument(
        "--no-network",
        action="store_true",
        help="Không gọi Gemini API (bỏ qua tầng 9)",
    )
    args = parser.parse_args()
    return asyncio.run(run_checks(with_network=not args.no_network))


if __name__ == "__main__":
    sys.exit(main())
