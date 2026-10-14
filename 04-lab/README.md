# Lab 04 — Weather Agent với MCP Server từ xa

Agent thời tiết xây bằng **Google ADK**, lấy tool từ một **MCP server** qua
**Streamable HTTP**, còn dữ liệu thời tiết lấy thật từ **WeatherAPI.com**.

```
┌──────────────────┐  Streamable HTTP   ┌──────────────────┐     HTTPS      ┌──────────────────┐
│   ADK Agent      │ ─────────────────▶ │   MCP Server     │ ─────────────▶ │  WeatherAPI.com  │
│  (mcp-client)    │  localhost:8085/mcp│  (mcp-server)    │                │                  │
│  McpToolset      │ ◀───────────────── │  FastMCP         │ ◀───────────── │                  │
└──────────────────┘                    └──────────────────┘                └──────────────────┘
        ▲                                                                             
        │ Gemini API (Function Calling)                                               
        ▼                                                                             
┌──────────────────┐                                                                  
│  Google Gemini   │                                                                  
└──────────────────┘                                                                  
```

## Tools

| Tool | Tham số | Mô tả |
|---|---|---|
| `get_current_weather(city)` | `city: str` | Thời tiết hiện tại (real-time từ WeatherAPI) |
| `get_forecast(city, days)` | `city: str`, `days: int = 3` | Dự báo **1–3 ngày** (free tier) |
| `health_check()` | — | Server còn sống không (KHÔNG gọi WeatherAPI) |

> `get_forecast` **từ chối** `days` ngoài khoảng 1–3 (kể cả 0 và số âm) và
> **không** gửi request lên WeatherAPI — cố ý không tự cắt về 3 để tránh trả
> kết quả sai lệch so với yêu cầu của người dùng.

## ADK làm gì trong Lab này?

ADK đóng vai **MCP Client**:

```
1. KẾT NỐI   StreamableHTTPConnectionParams(url="http://localhost:8085/mcp")
2. KHÁM PHÁ  McpToolset.get_tools() → ADK tự hỏi server "anh có tool gì?"
             → get_current_weather, get_forecast, health_check
3. TRUYỀN    Agent(model="gemini-2.5-flash", tools=[weather_tools])
             → Gemini biết mình có 3 tool
4. ĐIỀU PHỐI User hỏi → Gemini chọn tool → ADK gọi MCP → nhận kết quả → Gemini tổng hợp
5. GIAO DIỆN adk web → http://localhost:8000
```

So với [02-mcp-basics](../02-mcp-basics/) (client tự viết bằng `mcp.ClientSession`),
ADK xử lý sẵn vòng lặp Function Calling: bạn không phải tự viết `list_tools` →
model quyết định → `call_tool` → model tổng hợp.

> ⚠️ **`McpToolset(...)` KHÔNG kết nối tới server.** Nó chỉ ghi nhớ cấu hình;
> kết nối thật xảy ra ở lần `get_tools()`/gọi tool đầu tiên. Vì vậy
> `weather_agent/agent.py` **không** in "kết nối thành công" — muốn xác minh
> thật, chạy `verify_setup.py`.

## Cài đặt

### 1. MCP Server

```powershell
cd mcp-server
uv sync --frozen

# Key free: https://www.weatherapi.com/signup.aspx
# Cách A (khuyến nghị) — server TỰ NẠP .env cạnh nó:
Copy-Item .env.example .env      # rồi điền WEATHERAPI_KEY=...
uv run python weather.py

# Cách B — export cho phiên hiện tại:
$env:WEATHERAPI_KEY = "key-cua-ban"
uv run python weather.py
# → http://localhost:8085/mcp   (transport=streamable-http)
```

Linux/macOS:

```bash
cd mcp-server
uv sync --frozen
cp .env.example .env             # rồi điền WEATHERAPI_KEY=...
uv run python weather.py
```

Server nạp `.env` theo thứ tự `mcp-server/.env` → `<repo root>/.env`, và **in ra
stderr** file nào đã được nạp. Nếu có `.env` mà thiếu `python-dotenv`, server
cảnh báo rõ thay vì im lặng bỏ qua.

### 2. ADK Agent (Client)

```powershell
cd mcp-client
uv sync --frozen

# .env ở CHÍNH thư mục mcp-client (đã có .env.example)
Copy-Item .env.example .env
# sửa .env: GOOGLE_API_KEY=...   (và MCP_SERVER_URL nếu server không ở localhost:8085)

uv run adk web
```

Mở <http://localhost:8000>, chọn agent `weather_agent`, rồi hỏi.

### 3. Kiểm tra cấu hình trước khi chạy

```powershell
cd mcp-client
uv run python verify_setup.py
```

Script xác minh **9 tầng độc lập** và phân biệt rõ PASS / FAIL / WARN /
NOT VERIFIED (xem bảng dưới).

## Cấu hình

| Biến | Nơi dùng | Mặc định | Mô tả |
|---|---|---|---|
| `WEATHERAPI_KEY` | mcp-server | — | Key từ weatherapi.com |
| `PORT` | mcp-server | 8085 | Cổng (Cloud Run tự set 8080) |
| `HOST` | mcp-server | `0.0.0.0` | Interface |
| `MCP_TRANSPORT` | mcp-server | `streamable-http` | `streamable-http` / `stdio` / `sse` |
| `WEATHERAPI_TIMEOUT` | mcp-server | 15 | Timeout giây mỗi request |
| `WEATHERAPI_BASE_URL` | mcp-server | api.weatherapi.com/v1 | Ghi đè (dùng cho test) |
| `GOOGLE_API_KEY` | mcp-client | — | Key Gemini (nhận cả `GEMINI_API_KEY`) |
| `MCP_SERVER_URL` | mcp-client | `http://localhost:8085/mcp` | Endpoint MCP |
| `GEMINI_MODEL` | mcp-client | `gemini-2.5-flash` | Model |
| `MCP_TIMEOUT` | mcp-client | 30 | Timeout kết nối MCP (ADK mặc định chỉ 5s) |

### `.env` nằm ở đâu?

| Thứ tự | Đường dẫn | Ghi chú |
|---|---|---|
| 1 | `04-lab/mcp-client/.env` | Vị trí README yêu cầu (nạp trước) |
| 2 | `<repo root>/.env` | Tiện khi cả repo dùng chung một `.env` |

Cả `GOOGLE_API_KEY` và `GEMINI_API_KEY` đều được nhận — `env_setup.py` tự đồng
bộ alias, nên README và thực tế không thể lệch nhau.

## `verify_setup.py` — 9 tầng xác minh

| Tầng | Kiểm tra gì | Ghi chú |
|---|---|---|
| 1. Environment | `.env`, `MCP_SERVER_URL`, khoá Gemini | |
| 2. Dependencies | Các package mà code **thực sự** import | Kèm version |
| 3. Agent structure | File, `root_agent`, toolset đã gắn | **KHÔNG** chứng minh kết nối |
| 4. HTTP reachable | Chỉ tầng transport | **KHÔNG** suy ra MCP chạy |
| 5. MCP handshake | `initialize` thật qua ADK `McpToolset` | Đúng đường agent dùng |
| 6. Tool discovery | `list_tools` thật, đối chiếu 3 tool | |
| 7. Tool invocation | Gọi `health_check()` thật qua MCP | |
| 8. WeatherAPI | Gọi `get_current_weather()` | Chỉ PASS khi có dữ liệu THẬT |
| 9. Gemini API | Gọi thử model | `--no-network` để bỏ qua |

Mã thoát: `0` nếu không có FAIL. NOT VERIFIED **không** bị coi là PASS.

## Chạy test

```powershell
# Server (139 test: unit + mock WeatherAPI + MCP stdio + MCP HTTP + nested JSON + .env)
cd mcp-server
uv run --with pytest pytest tests -q

# Client (43 test unit + harness; 13 test E2E skip khi chưa bật DAY26_E2E)
cd ..\mcp-client
uv run --with pytest pytest tests -q

# E2E thật (User → Gemini → ADK → MCP → WeatherAPI → MCP → Gemini → User)
$env:DAY26_E2E = "1"
uv run --with pytest pytest tests/test_e2e_agent.py -q -s
```

`uv run --with pytest` dùng lớp phủ tạm thời → **không sửa `uv.lock`**.

5 câu hỏi E2E bắt buộc:

1. `Thời tiết Hà Nội hôm nay thế nào?`
2. `Dự báo Đà Nẵng trong 3 ngày tới.`
3. `So sánh thời tiết Hà Nội và TP. Hồ Chí Minh.`
4. `MCP Server hiện có hoạt động không?`
5. `Dự báo thời tiết -2 ngày tới.`  ← agent phải nói rõ giới hạn 1–3, không bịa

## Docker

```powershell
cd mcp-server
docker build -t day26-weather-mcp:local .
docker run --rm -p 8085:8080 -e WEATHERAPI_KEY="key-cua-ban" day26-weather-mcp:local
```

- Base image `ghcr.io/astral-sh/uv` + `uv sync --frozen` → build tất định theo `uv.lock`.
- Chạy bằng user không phải root.
- `.dockerignore` loại `.venv` và `.env` → **không có key trong image**.
- `HEALTHCHECK` chỉ là TCP connect (liveness của container), **không** phải kiểm tra MCP.

Deploy Cloud Run (không bắt buộc, có thể phát sinh chi phí):

```bash
gcloud run deploy weather-mcp \
  --image <IMAGE> --port 8080 --allow-unauthenticated \
  --set-secrets WEATHERAPI_KEY=weatherapi-key:latest
```

## Kết quả mong đợi

```
$ uv run python verify_setup.py
✅ [PASS        ] 1. Environment
✅ [PASS        ] 2. Dependencies
✅ [PASS        ] 3. Agent structure
✅ [PASS        ] 4. HTTP reachable
      ⚠️  KHÔNG suy ra MCP hoạt động từ tầng này. Xem tầng 5–6.
✅ [PASS        ] 5. MCP handshake
      tools nhận được: ['get_current_weather', 'get_forecast', 'health_check']
✅ [PASS        ] 6. Tool discovery
✅ [PASS        ] 7. Tool invocation
      status=ok transport=streamable-http weatherapi_key_configured=True
✅ [PASS        ] 8. WeatherAPI
      Thời tiết hiện tại tại Hanoi, Vietnam:
✅ [PASS        ] 9. Gemini API
Tổng kết: ✅ PASS=9  ❌ FAIL=0  ⚠️  WARN=0  ➖ NOT VERIFIED=0
```

Khi **chưa** có `WEATHERAPI_KEY`, tầng 8 và 9 báo `NOT VERIFIED` (không phải
PASS) và script vẫn thoát 0 nếu không có FAIL.

## Troubleshooting

| Triệu chứng | Cách xử lý |
|---|---|
| Agent không gọi được tool / `ConnectError` | Chạy MCP server trước; kiểm tra `MCP_SERVER_URL` |
| `WEATHERAPI_KEY chưa được cấu hình` | Key phải đặt cho **tiến trình server**, không phải client. Tạo `mcp-server/.env` hoặc export — xem log `[weather-mcp] .env đã nạp: ...` |
| `403 API_KEY_IP_ADDRESS_BLOCKED` (Gemini) | Key bị giới hạn IP — bỏ restriction hoặc dùng key khác |
| Agent báo "không lấy được dữ liệu" | Xem log MCP server; `verify_setup.py` tầng 8 |
| `ModuleNotFoundError: mcp.server.fastmcp` | Đang chạy Lab bằng venv của module 01–03 (mcp 2.x). Luôn dùng `uv run` trong đúng thư mục |
| Cổng 8085 bị chiếm | `$env:PORT=8086` và đặt `MCP_SERVER_URL` tương ứng |

## Giới hạn

- `adk web` chạy ở cổng **8000** — có thể trùng cổng `auth_server.py` của
  module 03. Đừng chạy đồng thời, hoặc đổi cổng.
- WeatherAPI free tier chỉ cho 3 ngày dự báo.
- Chưa deploy Cloud Run thật; image mới chỉ được build và chạy thử local.

Chi tiết kết quả kiểm thử: [`../reports/test-results.md`](../reports/test-results.md).
