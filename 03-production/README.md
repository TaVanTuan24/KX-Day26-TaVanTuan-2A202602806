# 03 — Production (Auth, Tool Registry, Versioning)

`02-mcp-basics` chạy tốt trên máy cá nhân. Đưa vào production cần giải quyết thêm 3 vấn đề:

| Vấn đề | Demo | Production |
|---|---|---|
| **Auth** | stdio, cùng máy, ai cũng gọi | HTTP + Bearer token / OAuth |
| **Discovery** | Hard-code tool/server | Tool Registry — agent tìm tool theo task |
| **Versioning** | 1 tool duy nhất | v1 + v2 song song, deprecation notice |

## Files

| File | Vấn đề | Mô tả |
|---|---|---|
| `auth_server.py` | Auth | MCP server qua HTTP + `TokenVerifier` kiểm tra bearer token |
| `auth_client.py` | Auth | Client gửi token qua `create_mcp_http_client(headers=...)` |
| `registry.json` | Discovery | Tool Registry — danh mục tool-centric, agent tìm theo tag/keyword |
| `registry_client.py` | Discovery | Agent tra cứu registry, chọn best match, tự kết nối |
| `versioned_server.py` | Versioning | Server v2: giữ tool v1 (deprecated) + thêm v2 + resource metadata |
| `versioned_client.py` | Versioning | Client test gọi tool v1, v2 và đọc `server://info` metadata |

---

## 3a. Authentication

Server chạy qua **Streamable HTTP** thay vì stdio, kèm bearer token verification.

```powershell
# Terminal 1 — khởi động server
cd 03-production
$env:PORT = 8090        # 8000 có thể bị Docker Desktop chiếm trên Windows
..\.venv\Scripts\python.exe auth_server.py
# Server lắng nghe tại http://127.0.0.1:8090/mcp

# Terminal 2 — client kết nối kèm token
$env:MCP_SERVER_URL = "http://127.0.0.1:8090/mcp"
..\.venv\Scripts\python.exe auth_client.py
```

### ⚠️ Sửa lại tài liệu: token sai KHÔNG trả 403

Bản README trước ghi *"Thiếu token → 401, Token sai → 403"*. **Đo thực tế trên
MCP SDK v2 (mcp 2.3.0) cho kết quả khác:**

| Tình huống | Status thực tế | `WWW-Authenticate` |
|---|---|---|
| Không có token | **401** | `Bearer error="invalid_token"` |
| Token sai | **401** | `Bearer error="invalid_token"` |
| Token xác thực đúng nhưng **thiếu scope** | **403** | `Bearer error="insufficient_scope", error_description="Required scope: weather:read"` |
| Token hợp lệ | **200** | — |
| Header sai scheme (`Basic ...`) | **401** | `Bearer error="invalid_token"` |

Điều này **đúng theo RFC 6750**: token không xác minh được là lỗi *xác thực*
(401); 403 dành cho trường hợp đã xác thực nhưng *thiếu quyền*.

Vì vậy repo hiện hiện thực **cả hai** để phân biệt rõ:

```python
AuthSettings(
    issuer_url=PUBLIC_URL,
    resource_server_url=PUBLIC_URL,
    validate_token_resource=False,   # verifier tĩnh KHÔNG kiểm tra audience
    required_scopes=["weather:read"],# AUTHORIZATION: thiếu scope → 403
)
```

Token demo (chỉ dùng local):

| Token | client_id | scopes | Dùng để |
|---|---|---|---|
| `dev-token-abc123` | dev-user | `weather:read` | Ca hợp lệ (200) |
| `demo-client-key-xyz789` | service-user | `weather:read` | Ca hợp lệ (200) |
| `demo-no-scope-token` | limited-client | *(rỗng)* | Ca **403** insufficient_scope |

`auth_client.py` tự đo và in ra 4 status code thật, nên bạn thấy ngay kết quả
trên máy mình thay vì phải tin vào tài liệu.

```
--- Đo status code thật (không giả định) ---
  ✅ không có token: HTTP 401 (kỳ vọng 401) — AUTHENTICATION thiếu → 401
       WWW-Authenticate: Bearer error="invalid_token", ...
  ✅ token sai: HTTP 401 (kỳ vọng 401) — AUTHENTICATION sai → 401
  ✅ token hiệu lực, thiếu scope: HTTP 403 (kỳ vọng 403) — AUTHORIZATION thiếu scope → 403
       WWW-Authenticate: Bearer error="insufficient_scope", error_description="Required scope: weather:read"
  ✅ token hợp lệ: HTTP 200 (kỳ vọng 200) — hợp lệ → 200
```

### ⚠️ Điểm yếu đã biết của demo

- Token là **hằng số trong source** → ai đọc repo là có token.
- Không có expiry, không refresh, **không thu hồi được**.
- Mọi token hợp lệ có cùng quyền (chỉ tách được theo scope, không theo tool).
- Không rate-limit, không audit log.
- `validate_token_resource=False` nghĩa là **không kiểm tra audience** — token
  phát cho resource khác vẫn được chấp nhận. Việc này phải do verifier thật
  (JWT có chữ ký / OAuth introspection) đảm nhiệm.

Production thật phải dùng JWT có chữ ký + expiry, OAuth 2.1, hoặc mTLS.

---

## 3b. Tool Registry & Discovery

Agent **không hard-code** tool nào. Nó hỏi Tool Registry theo yêu cầu task:

```bash
python registry_client.py
```

Kết quả mong đợi:

```
=== Tool Registry ===

  get_weather v1.0.0
    Lấy thời tiết hiện tại của một thành phố
    tags: ['weather', 'current', 'vietnam']  →  server: weather
  get_weather_v2 v2.0.0
    Lấy thời tiết chi tiết — JSON, hỗ trợ forecast và đơn vị đo
    tags: ['weather', 'forecast', 'detailed', 'vietnam']  →  server: weather-v2
  ...

--- Agent cần tool có tag "weather" ---
Tìm thấy 2 tool(s):
  • get_weather v1.0.0 (server: weather)
  • get_weather_v2 v2.0.0 (server: weather-v2)

Best match: get_weather_v2 v2.0.0
Kết nối tới server [weather-v2]...
Kết quả: ...
```

Luồng:

```
Agent nhận task
   │
   ▼
ToolRegistry.search(tag="weather")  ← tìm tool theo capability
   │
   ├── get_weather v1.0 → server: weather
   └── get_weather_v2 v2.0 → server: weather-v2
   │
   ▼
ToolRegistry.best_match()  ← chọn version cao nhất, không deprecated
   │
   ▼
connect_and_call()  ← tự kết nối đúng transport (stdio/HTTP) + auth
```

`registry.json` là **tool-centric** — đơn vị khám phá là tool (tag, description, parameters), không phải server. Production thay JSON bằng DB/API với semantic search.

### Xử lý lỗi

`ToolRegistry` **không giả định registry luôn đúng**. Mọi nhánh lỗi đều có
exception riêng (`RegistryError`) và được test:

| Tình huống | Hành vi |
|---|---|
| File registry không tồn tại | `RegistryError: Không tìm thấy registry: ...` |
| JSON không hợp lệ | `RegistryError: registry.json không phải JSON hợp lệ (...)` |
| Thiếu mục `tools` / `servers`, hoặc sai kiểu | `RegistryError` nêu rõ mục thiếu |
| Entry tool thiếu field | Bỏ qua / dùng default (`version="0.0.0"`) — một entry hỏng không làm sập cả registry |
| `version` rác (`"not-a-version"`) | Coi như `0.0.0` thay vì crash |
| Không tìm thấy tool theo tag/keyword | `RegistryError: Không tìm thấy tool ...` |
| Tool trỏ tới server không có trong registry | `RegistryError: ... không có trong mục 'servers'` |
| Transport lạ (`"carrier-pigeon"`) | `RegistryError: Transport không được hỗ trợ` |
| Script stdio không tồn tại trên đĩa | `RegistryError: Server script không tồn tại` |
| Server HTTP thiếu biến token | `RegistryError: ... biến môi trường X chưa được đặt` |

`best_match` chọn theo **semantic version** (không so chuỗi: `10.0.0 > 9.0.0`)
và **ưu tiên tool không deprecated**.

### ⚠️ Endpoint minh hoạ — KHÔNG được gọi như thể đang chạy

`registry.json` có 2 entry minh hoạ trỏ tới endpoint nội bộ **không tồn tại**:

| Tool | Server | URL |
|---|---|---|
| `send_email` | `email-service` | `http://internal-email:9000/mcp` |
| `query_db` | `db-gateway` | `http://internal-db:9100/mcp` |

Chúng chỉ để cho thấy registry chứa được nhiều loại tool. `registry_client.py`
**không gọi** chúng và in rõ cảnh báo. Nếu bạn cố gọi, nó sẽ **lỗi rõ ràng**
(`RegistryError`) chứ không âm thầm "coi như thành công" — có test khẳng định
điều này.

### Test

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_03_registry.py -q   # 29 test
```

---

## 3c. Versioning & Backward Compatibility

Server v2 dùng 3 kỹ thuật để thêm tính năng mà không break client cũ:

```bash
# Server chạy qua stdio — client tự spawn
python versioned_client.py
```

| Kỹ thuật | Mô tả |
|---|---|
| **Tool mới song song** | `get_weather_v2` tồn tại bên cạnh `get_weather` — không xoá tool cũ |
| **Tham số optional** | `include_forecast`, `units` có default → client cũ gọi `get_weather_v2(city="Hanoi")` vẫn đúng |
| **Server metadata** | Resource `server://info` công bố version, tools, deprecated tools, migration guide |

### Kiểm tra tham số

`units` **được validate** thay vì âm thầm coi như `celsius`:

```json
{"city": "Hanoi", "error": "units không hợp lệ: 'kelvin'",
 "supported_units": ["celsius", "fahrenheit"], "api_version": "2.0"}
```

`units` không phân biệt hoa/thường và bỏ khoảng trắng (`" FAHRENHEIT "` vẫn đúng).

### Test

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_03_versioning.py -q   # 18 test
```

Test chạy MCP server **thật** qua stdio và khẳng định:

- `get_weather` (v1) trả **đúng nguyên** định dạng chuỗi cũ → backward compatible
- `get_weather_v2(city)` với chỉ tham số bắt buộc dùng đúng default
- `get_weather_v2(..., include_forecast=True)` thêm danh sách forecast
- `units="fahrenheit"` đổi 29°C → 84.2°F
- `units` không hợp lệ trả **payload lỗi JSON**, server **không sập**
- `server://info` công bố `version`, `tools`, `deprecated_tools`, `migration_guide`

```
Server v2
├── get_weather(city)              ← v1, deprecated nhưng vẫn hoạt động
├── get_weather_v2(city, ...)      ← v2, thêm forecast + units
└── resource server://info         ← version + migration guide cho client
```

Kết quả mong đợi:

```
Server: weather-v2 v2.0.0
Deprecated tools: ['get_weather']
Migration: Chuyển từ get_weather sang get_weather_v2. Tham số 'city' giữ nguyên, thêm include_forecast và units.

Tools:
  - get_weather: [v1] Lấy thời tiết hiện tại — trả chuỗi đơn giản. Deprecated, dùng get_weather_v2.
  - get_weather_v2: [v2] Lấy thời tiết chi tiết — JSON, hỗ trợ forecast và đơn vị đo.

[v1] get_weather('Hanoi'):
  Hanoi: 29°C, trời mưa

[v2] get_weather_v2('Hanoi', forecast=True):
  { "api_version": "2.0", "city": "Hanoi", "temp": 29, ... }
```

Luồng:

```
versioned_client.py                     versioned_server.py
       │                                        │
       │── read_resource("server://info") ────▶ │  ← đọc metadata trước
       │◀── version, deprecated_tools ────────  │
       │                                        │
       │── list_tools() ─────────────────────▶  │  ← khám phá tool
       │◀── [get_weather, get_weather_v2] ────  │
       │                                        │
       │── call_tool("get_weather") ──────────▶ │  ← v1 deprecated, vẫn chạy
       │── call_tool("get_weather_v2") ───────▶ │  ← v2 đầy đủ tính năng
```

Client thông minh đọc `server://info` để biết tool nào deprecated, tự chọn dùng v2 nếu có, fallback v1 nếu không.
