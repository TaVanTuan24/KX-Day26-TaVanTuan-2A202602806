"""Tool Registry Client — agent khám phá tool từ danh mục trung tâm.

Thay vì hard-code "server nào có tool nào", agent hỏi Tool Registry:
  "Tôi cần tool có tag 'weather'" → Registry trả về get_weather, server weather, stdio
  "Tôi cần tool có tag 'forecast'" → Registry trả về get_weather_v2, server weather-v2

Agent tự quyết định dùng tool nào, kết nối tới đúng server, và gọi tool —
tất cả tại runtime mà không cần hard-code.

Production thường dùng:
  - Tool registry tập trung (DB/API) với search full-text hoặc semantic
  - Kubernetes + CRD (Custom Resource Definition) cho MCP servers
  - API Gateway (Kong, Envoy) làm single entry point

Ví dụ này minh hoạ ý tưởng với một file JSON đơn giản.

Cách chạy:
    pip install -r ../requirements.txt     # từ thư mục gốc repo
    cd 03-production
    python registry_client.py

LƯU Ý: `registry.json` có 2 entry minh hoạ (`send_email`, `query_db`) trỏ tới
các endpoint nội bộ KHÔNG tồn tại (`internal-email`, `internal-db`). Chúng chỉ
để cho thấy registry chứa được nhiều loại tool — script này KHÔNG gọi chúng.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from packaging.version import InvalidVersion, Version

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REGISTRY_PATH = Path(__file__).parent / "registry.json"
# Đường dẫn tương đối trong registry.json được tính từ thư mục chứa file registry,
# nên script chạy đúng dù bạn đứng ở thư mục nào.
REGISTRY_DIR = REGISTRY_PATH.parent

REQUEST_TIMEOUT = 30.0

# Các server chỉ mang tính minh hoạ trong registry.json — không bao giờ gọi.
ILLUSTRATIVE_SERVERS = {"email-service", "db-gateway"}


class RegistryError(RuntimeError):
    """Lỗi khi đọc registry, chọn tool, hoặc kết nối tới server."""


class ToolRegistry:
    """Danh mục trung tâm — agent tra cứu tool theo tag, tên, hoặc mô tả."""

    def __init__(self, path: Path | str = REGISTRY_PATH) -> None:
        self.path = Path(path)
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise RegistryError(f"Không tìm thấy registry: {self.path}") from exc
        except OSError as exc:
            raise RegistryError(f"Không đọc được registry {self.path}: {exc}") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RegistryError(
                f"registry.json không phải JSON hợp lệ ({self.path}): {exc}"
            ) from exc

        self._load(data)

    @classmethod
    def from_dict(cls, data: object, source: str = "<in-memory>") -> "ToolRegistry":
        """Tạo registry từ dict (tiện cho unit test và demo xử lý lỗi)."""
        instance = cls.__new__(cls)
        instance.path = Path(source)
        instance._load(data)
        return instance

    def _load(self, data: object) -> None:
        if not isinstance(data, dict):
            raise RegistryError("registry phải là một JSON object")
        tools = data.get("tools")
        servers = data.get("servers")
        if not isinstance(tools, dict):
            raise RegistryError("registry thiếu mục 'tools' (phải là object)")
        if not isinstance(servers, dict):
            raise RegistryError("registry thiếu mục 'servers' (phải là object)")
        self.tools: dict[str, dict] = tools
        self.servers: dict[str, dict] = servers

    # ── Tìm kiếm ────────────────────────────────────────────────────────
    def search(self, *, tag: str | None = None, keyword: str | None = None) -> list[dict]:
        """Tìm tool theo tag, hoặc theo keyword trong tên/mô tả/tags.

        Chịu được entry thiếu field (dùng giá trị mặc định) để một entry hỏng
        không làm sập cả registry.

        Trả về danh sách kết quả, mỗi phần tử gồm thông tin tool + server.
        """
        results = []
        for tool_name, tool_cfg in self.tools.items():
            if not isinstance(tool_cfg, dict):
                continue

            tags = tool_cfg.get("tags") or []
            description = tool_cfg.get("description") or ""
            haystack = f"{tool_name} {description} {' '.join(map(str, tags))}".lower()

            match = False
            if tag and tag in tags:
                match = True
            if keyword and keyword.lower() in haystack:
                match = True
            if not match:
                continue

            server_name = tool_cfg.get("server")
            server_cfg = self.servers.get(server_name) if server_name else None

            results.append(
                {
                    "tool": tool_name,
                    "description": description,
                    "version": tool_cfg.get("version") or "0.0.0",
                    "deprecated": bool(tool_cfg.get("deprecated", False)),
                    "parameters": tool_cfg.get("parameters", {}),
                    "server_name": server_name,
                    "server": server_cfg or {},
                    "server_missing": server_cfg is None,
                }
            )
        return results

    @staticmethod
    def _sort_key(entry: dict) -> Version:
        try:
            return Version(str(entry["version"]))
        except (InvalidVersion, TypeError):
            # Version rác → coi như thấp nhất thay vì làm sập best_match.
            return Version("0.0.0")

    def best_match(self, *, tag: str | None = None, keyword: str | None = None) -> dict:
        """Trả về tool phù hợp nhất (ưu tiên không deprecated, rồi version cao)."""
        results = self.search(tag=tag, keyword=keyword)
        if not results:
            raise RegistryError(f"Không tìm thấy tool (tag={tag!r}, keyword={keyword!r})")
        active = [r for r in results if not r["deprecated"]]
        candidates = active or results
        # So sánh theo semantic version, không so chuỗi ("10.0.0" > "2.0.0")
        return max(candidates, key=self._sort_key)


async def connect_and_call(match: dict, tool_args: dict) -> str:
    """Kết nối tới server phù hợp và gọi tool đã tìm được."""
    server_name = match.get("server_name")
    server = match.get("server") or {}
    tool_name = match["tool"]

    if not server:
        raise RegistryError(
            f"Tool '{tool_name}' trỏ tới server '{server_name}' không có trong "
            f"mục 'servers' của registry"
        )

    transport = server.get("transport")

    if transport == "stdio":
        # "python" trong registry → dùng đúng interpreter hiện tại (tránh lỗi venv)
        command = server.get("command", "python")
        if command in ("python", "python3"):
            command = sys.executable
        args = [
            str((REGISTRY_DIR / a).resolve()) if str(a).endswith(".py") else a
            for a in server.get("args", [])
        ]
        for arg in args:
            if str(arg).endswith(".py") and not Path(arg).is_file():
                raise RegistryError(f"Server script không tồn tại: {arg}")
        params = StdioServerParameters(command=command, args=args)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, tool_args)
                return _result_text(result)

    if transport == "streamable-http":
        headers: dict[str, str] = {}
        auth_cfg = server.get("auth")
        if auth_cfg and auth_cfg.get("type") == "bearer":
            token = os.environ.get(auth_cfg["token_env"], "")
            if not token:
                raise RegistryError(
                    f"Server '{server_name}' cần bearer token nhưng biến môi "
                    f"trường {auth_cfg['token_env']} chưa được đặt"
                )
            headers["Authorization"] = f"Bearer {token}"

        async with create_mcp_http_client(headers=headers, timeout=REQUEST_TIMEOUT) as (
            http_client
        ):
            async with streamable_http_client(
                server["url"], http_client=http_client
            ) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, tool_args)
                    return _result_text(result)

    raise RegistryError(
        f"Transport không được hỗ trợ: {transport!r} (server '{server_name}')"
    )


def _result_text(result: object) -> str:
    blocks = getattr(result, "content", None) or []
    texts = [getattr(b, "text", "") for b in blocks]
    is_error = bool(getattr(result, "is_error", getattr(result, "isError", False)))
    body = "\n".join(t for t in texts if t)
    return f"[TOOL ERROR] {body}" if is_error else body


def _print_registry(registry: ToolRegistry) -> None:
    print("=== Tool Registry ===\n")
    for name, cfg in registry.tools.items():
        status = " (deprecated)" if cfg.get("deprecated") else ""
        server_name = cfg.get("server")
        note = ""
        if server_name in ILLUSTRATIVE_SERVERS:
            note = "  ⚠️ minh hoạ — KHÔNG được gọi bởi script này"
        print(f"  {name} v{cfg.get('version', '?')}{status}")
        print(f"    {cfg.get('description', '')}")
        print(f"    tags: {cfg.get('tags', [])}  →  server: {server_name}{note}")
    print()


async def main() -> int:
    try:
        registry = ToolRegistry()
    except RegistryError as exc:
        print(f"❌ {exc}")
        return 1

    # ── 1. Agent liệt kê toàn bộ tool trong registry ─────────────────
    _print_registry(registry)

    # ── 2. Agent tìm tool theo tag (giống agent nhận task "lấy thời tiết") ─
    print('--- Agent cần tool có tag "weather" ---')
    results = registry.search(tag="weather")
    print(f"Tìm thấy {len(results)} tool(s):")
    for r in results:
        print(f"  • {r['tool']} v{r['version']} (server: {r['server_name']})")

    # ── 3. Agent chọn tool phù hợp nhất và gọi ──────────────────────
    best = registry.best_match(tag="weather")
    print(f"\nBest match: {best['tool']} v{best['version']} (không deprecated, version cao nhất)")
    print(f"Kết nối tới server [{best['server_name']}] qua {best['server'].get('transport')}...")

    try:
        output = await connect_and_call(best, {"city": "Hanoi"})
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Gọi tool thất bại: {type(exc).__name__}: {exc}")
        return 1
    print(f"Kết quả: {output}\n")

    # ── 4. Agent tìm tool theo keyword ───────────────────────────────
    print('--- Agent tìm tool có keyword "forecast" ---')
    for r in registry.search(keyword="forecast"):
        print(f"  • {r['tool']}: {r['description']}")

    # ── 5. Xử lý lỗi (dùng bản sao in-memory — KHÔNG sửa registry.json) ──
    print("\n--- Xử lý lỗi ---")
    try:
        registry.best_match(tag="khong-co-tag-nay")
    except RegistryError as exc:
        print(f"  [tool không tìm thấy] {exc}")

    try:
        ToolRegistry.from_dict({"servers": {}})
    except RegistryError as exc:
        print(f"  [registry JSON lỗi]   {exc}")

    orphan = ToolRegistry.from_dict(
        {
            "tools": {
                "ghost_tool": {
                    "description": "tool trỏ tới server không tồn tại",
                    "tags": ["ghost"],
                    "server": "khong-ton-tai",
                    "version": "1.0.0",
                }
            },
            "servers": {},
        }
    )
    try:
        await connect_and_call(orphan.best_match(tag="ghost"), {})
    except RegistryError as exc:
        print(f"  [server không tồn tại] {exc}")

    print(
        "\nℹ️  Hai server minh hoạ "
        f"{sorted(ILLUSTRATIVE_SERVERS)} không được gọi — chúng trỏ tới "
        "endpoint nội bộ không tồn tại và chỉ để minh hoạ registry đa dạng."
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
