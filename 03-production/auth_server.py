"""MCP Server có Authentication — minh hoạ bảo mật cho production.

Server chạy qua HTTP (Streamable HTTP) thay vì stdio, kèm bearer token
verification. Chỉ request mang token hợp lệ mới được phép khám phá và gọi tool.

Luồng hoạt động:
  Client gửi request HTTP kèm header "Authorization: Bearer <token>"
    → MCP SDK tự chạy TokenVerifier để xác minh token
    → Token hợp lệ → cho phép truy cập tool
    → Token sai / thiếu → request bị từ chối ở tầng transport

Cách chạy:
    pip install -r ../requirements.txt     # từ thư mục gốc repo
    python auth_server.py
    # Server lắng nghe tại http://127.0.0.1:8000/mcp

Biến môi trường:
    HOST              — mặc định 127.0.0.1 (CHỈ local). Đặt 0.0.0.0 nếu thật sự
                        cần expose ra mạng — chỉ làm trong môi trường có kiểm soát.
    PORT              — mặc định 8000
    MCP_PUBLIC_URL    — URL công bố trong metadata OAuth (mặc định http://localhost:<PORT>)
    MCP_AUTH_TOKEN    — token của "dev-user" (mặc định là token demo bên dưới)
    MCP_SERVICE_TOKEN — token của "service-user"

⚠️ CẢNH BÁO BẢO MẬT — ĐÂY LÀ DEMO, KHÔNG DÙNG CHO PRODUCTION:
    - Token là hằng số tĩnh nằm trong source code → ai đọc được repo là có token.
    - Không có expiry, không có refresh, không thu hồi được.
    - Không phân biệt scope theo tool (mọi token đều có cùng quyền).
    - Không rate-limit, không audit log.
    Production thật phải dùng: JWT có chữ ký + expiry, OAuth 2.1
    (authorization server + resource server tách biệt), hoặc mTLS; kèm
    scope-based authorization, rotation và audit.
"""

from __future__ import annotations

import os
import sys

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer

if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
PUBLIC_URL = os.environ.get("MCP_PUBLIC_URL", f"http://localhost:{PORT}")

# ── Token store (production: DB, Redis, hoặc verify JWT) ─────────────────
# Token demo, CHỈ dùng cho môi trường local. Có thể override bằng env var.
# Đây không phải secret thật — nhưng cũng không được coi là "an toàn".
DEV_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "dev-token-abc123")
SERVICE_TOKEN = os.environ.get("MCP_SERVICE_TOKEN", "demo-client-key-xyz789")
# Token thứ ba: xác thực ĐÚNG nhưng THIẾU scope → dùng để minh hoạ 403.
LIMITED_TOKEN = os.environ.get("MCP_LIMITED_TOKEN", "demo-no-scope-token")

# token → (client_id, scopes)
VALID_TOKENS: dict[str, tuple[str, list[str]]] = {
    DEV_TOKEN: ("dev-user", ["weather:read"]),
    SERVICE_TOKEN: ("service-user", ["weather:read"]),
    LIMITED_TOKEN: ("limited-client", []),
}

REQUIRED_SCOPES = ["weather:read"]


def _redact(token: str) -> str:
    """Rút gọn token để log/đối chiếu mà không lộ giá trị đầy đủ."""
    if not token:
        return "<empty>"
    return f"{token[:4]}…{token[-2:]}(len={len(token)})"


class StaticTokenVerifier(TokenVerifier):
    """Kiểm tra bearer token dựa trên danh sách tĩnh.

    Đây là bước AUTHENTICATION ("bạn là ai"). Việc kiểm tra scope
    (AUTHORIZATION — "bạn được phép làm gì") do `AuthSettings.required_scopes`
    của SDK thực hiện, dựa trên `scopes` trả về ở đây.

    Production nên thay bằng: JWT decode + verify signature, OAuth
    introspection, hoặc gọi identity provider (Keycloak, Auth0, Google IAM...).
    """

    async def verify_token(self, token: str) -> AccessToken | None:
        entry = VALID_TOKENS.get(token)
        if entry is None:
            # KHÔNG log giá trị token đầy đủ.
            print(f"[auth] từ chối token {_redact(token)}", file=sys.stderr)
            return None
        client_id, scopes = entry
        return AccessToken(token=token, client_id=client_id, scopes=list(scopes))


# --- MCP Server — logic tool không biết gì về auth --------------------
mcp = MCPServer(
    "weather-secure",
    version="1.0.0",
    instructions="MCP server demo có bearer-token authentication (dữ liệu MOCK).",
    auth=AuthSettings(
        issuer_url=PUBLIC_URL,
        resource_server_url=PUBLIC_URL,
        # StaticTokenVerifier KHÔNG kiểm tra audience của token, nên phải nói
        # rõ là không validate resource. Đặt True sẽ yêu cầu token có
        # `resource` khớp `resource_server_url` — việc đó phải do verifier
        # thật (JWT/OAuth introspection) đảm nhiệm.
        # Đây là một ĐIỂM YẾU ĐÃ BIẾT của demo: token phát cho resource khác
        # vẫn được chấp nhận. Xem mục Security trong README.
        validate_token_resource=False,
        # AUTHORIZATION: token phải có scope này mới gọi được tool.
        # Token xác thực đúng nhưng thiếu scope → 403 (khác 401).
        required_scopes=REQUIRED_SCOPES,
    ),
    token_verifier=StaticTokenVerifier(),
    log_level="WARNING",
)

_MOCK_DB = {
    "hanoi": "29°C, trời mưa",
    "haiphong": "33°C, mưa rào",
    "danang": "30°C, nhiều mây",
}


@mcp.tool()
def get_weather(city: str) -> str:
    """Lấy thời tiết hiện tại của một thành phố.

    Args:
        city: Tên thành phố, ví dụ Hanoi, Danang, Haiphong.
    """
    return f"{city}: {_MOCK_DB.get(city.strip().casefold(), '28°C, không có dữ liệu chi tiết')}"


if __name__ == "__main__":
    print(
        f"[auth] weather-secure nghe tại http://{HOST}:{PORT}/mcp "
        f"(public_url={PUBLIC_URL})",
        file=sys.stderr,
    )
    print(
        "[auth] ⚠️  Static token demo — chỉ dùng local, KHÔNG dùng production.",
        file=sys.stderr,
    )
    mcp.run(transport="streamable-http", host=HOST, port=PORT)
