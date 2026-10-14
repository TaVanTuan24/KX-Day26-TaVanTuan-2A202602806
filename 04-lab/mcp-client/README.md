# Weather Agent — Google ADK + MCP Server

Agent AI xây bằng **Google Agent Development Kit (ADK)**, lấy tool từ một **MCP
server** qua **Streamable HTTP**. Agent chỉ biết giao thức MCP — nó không biết
gì về WeatherAPI bên trong server.

```
┌──────────────────┐      ┌──────────────────┐      ┌─────────────────────┐
│   User Browser   │ ───▶ │  ADK Web UI      │ ───▶ │  Weather Agent      │
│  localhost:8000  │      │  (Google ADK)    │      │  (Agent + McpToolset)│
└──────────────────┘      └──────────────────┘      └─────────────────────┘
                                                              │
                                            Streamable HTTP   │
                                                              ▼
                                                    ┌─────────────────────┐
                                                    │  MCP Server         │
                                                    │  localhost:8085/mcp │
                                                    └─────────────────────┘
                                                              │ HTTPS
                                                              ▼
                                                    ┌─────────────────────┐
                                                    │  WeatherAPI.com     │
                                                    └─────────────────────┘
```

## Tính năng

- **MCP tool từ xa**: kết nối qua Streamable HTTP, tool được khám phá tại runtime.
- **3 tool**: `get_current_weather(city)`, `get_forecast(city, days)`,
  `health_check()`.
- **System instruction nghiêm ngặt**: chỉ dùng dữ liệu từ tool, cấm bịa số liệu,
  bắt buộc báo lỗi trung thực, luôn trả lời tiếng Việt.
- **Giao diện web** qua `adk web`.
- **`verify_setup.py`**: xác minh 9 tầng, phân biệt PASS / FAIL / NOT VERIFIED.

## Cấu trúc

```
mcp-client/
├── weather_agent/
│   ├── agent.py           # root_agent + McpToolset + system instruction
│   └── __init__.py        # export root_agent (ADK cần)
├── env_setup.py           # nguồn cấu hình .env DUY NHẤT (dùng chung verify_setup)
├── verify_setup.py        # xác minh 9 tầng
├── tests/
│   ├── conftest.py        # fixture + MockWeatherAPI + spawn MCP server
│   ├── test_agent_config.py
│   ├── test_e2e_agent.py  # 5 câu hỏi E2E (tắt mặc định)
│   └── e2e_runner.py      # chạy agent cho danh sách câu hỏi, in JSON
├── pyproject.toml / uv.lock
├── .env.example
└── README.md
```

## Bắt đầu nhanh

### 1. Khởi động MCP server

```powershell
cd ..\mcp-server
$env:WEATHERAPI_KEY = "key-cua-ban"
uv run python weather.py
```

### 2. Cấu hình môi trường

```powershell
cd ..\mcp-client
Copy-Item .env.example .env
# sửa .env:
#   GOOGLE_API_KEY=...
#   MCP_SERVER_URL=http://localhost:8085/mcp
```

### 3. Cài dependency & xác minh

```powershell
uv sync --frozen
uv run python verify_setup.py
```

### 4. Chạy agent

```powershell
uv run adk web
```

Mở <http://localhost:8000>, chọn `weather_agent`, rồi hỏi.

## Ví dụ câu hỏi

- "Thời tiết Hà Nội hôm nay thế nào?"
- "Dự báo Đà Nẵng trong 3 ngày tới."
- "So sánh thời tiết Hà Nội và TP. Hồ Chí Minh."
- "MCP Server hiện có hoạt động không?"
- "Dự báo thời tiết -2 ngày tới."  ← agent phải nói rõ giới hạn 1–3

## Cấu hình

| Biến | Mặc định | Mô tả |
|---|---|---|
| `GOOGLE_API_KEY` (hoặc `GEMINI_API_KEY`) | — | Key Gemini |
| `MCP_SERVER_URL` | `http://localhost:8085/mcp` | Endpoint MCP (đổi sang URL Cloud Run khi deploy) |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Model |
| `MCP_TIMEOUT` | 30 | Timeout kết nối MCP |
| `MCP_SSE_READ_TIMEOUT` | 300 | Timeout đọc SSE |
| `DAY26_E2E` | 0 | `1` để bật E2E test |

`.env` được nạp theo thứ tự: `mcp-client/.env` → `<repo root>/.env`.
Cả `GOOGLE_API_KEY` và `GEMINI_API_KEY` đều được nhận.

`agent.py` cấu hình:

```python
connection_params = StreamableHTTPConnectionParams(
    url=MCP_SERVER_URL,
    timeout=MCP_TIMEOUT,          # ADK mặc định chỉ 5s — quá ngắn cho Cloud Run cold start
)
toolset = McpToolset(connection_params=connection_params, errlog=sys.stderr)

root_agent = Agent(
    name="weather_agent",
    model=GEMINI_MODEL,
    instruction=INSTRUCTION,      # cấm bịa dữ liệu, bắt buộc báo lỗi trung thực
    tools=[toolset],
)
```

> ⚠️ `McpToolset(...)` **không kết nối**. Kết nối xảy ra ở lần `get_tools()` đầu
> tiên. `agent.py` không tuyên bố "đã kết nối thành công"; hãy chạy
> `verify_setup.py` để kiểm tra thật.

## Fallback mode

Nếu **tạo** `McpToolset` thất bại (lỗi cấu hình/import), `agent.py` tạo một agent
**không có tool** và log rất rõ:

```
❌ Không tạo được McpToolset: ...
⚠️  FALLBACK: agent chạy KHÔNG CÓ TOOL THỜI TIẾT.
```

Agent ở chế độ này có instruction riêng buộc phải nói rõ là không lấy được dữ
liệu thời tiết — **không** tạo cảm giác hệ thống vẫn có dữ liệu trực tiếp.

## Test

```powershell
# Unit + harness (43 test, không gọi API nào)
uv run --with pytest pytest tests -q

# E2E thật (5 câu hỏi, cần Gemini key còn quota)
$env:DAY26_E2E = "1"
uv run --with pytest pytest tests/test_e2e_agent.py -q -s
```

E2E có **ba** kết quả, không phải hai:

| Kết quả | Ý nghĩa |
|---|---|
| PASS | Agent chạy đúng, có bằng chứng |
| SKIP | Lỗi **tạm thời** của môi trường (key bị giới hạn IP / hết quota) → **CHƯA xác minh được**, không phải PASS |
| FAIL | Lỗi logic của agent (không gọi tool, bịa dữ liệu, sai tham số) |

Nếu `WEATHERAPI_KEY` có trong môi trường, E2E chạy với WeatherAPI **thật**;
nếu không, nó dùng `MockWeatherAPI` (luồng ADK→MCP là thật, dữ liệu thời tiết
**không** phải real-time — test in rõ mode).

## Troubleshooting

| Triệu chứng | Cách xử lý |
|---|---|
| `adk web` không thấy agent | Phải chạy trong `04-lab/mcp-client` (nơi có `weather_agent/`) |
| Agent không gọi được tool | Chạy MCP server trước (`cd ../mcp-server && uv run python weather.py`) |
| `403 PERMISSION_DENIED / API_KEY_IP_ADDRESS_BLOCKED` | Key Gemini bị giới hạn IP |
| Agent luôn báo thiếu `WEATHERAPI_KEY` | Key phải đặt ở **tiến trình server**, không phải client |
| `ModuleNotFoundError: No module named 'mcp.server.fastmcp'` | Bạn đang dùng venv module 01–03 (mcp 2.x). Dùng `uv run` trong `mcp-client` |
| E2E treo lâu | Retry do key bị giới hạn IP; `E2E_MAX_ATTEMPTS` để giảm số lần thử |

Chi tiết kết quả kiểm thử: [`../../reports/test-results.md`](../../reports/test-results.md).
