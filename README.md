# Day 26 — Function Calling & Model Context Protocol (MCP)

Repo bài học so sánh **Function Calling** (Google Gemini SDK) với **MCP** (Model
Context Protocol), rồi đưa MCP lên mức production: authentication, tool registry,
versioning — và kết thúc bằng một **lab thật**: agent Google ADK + MCP server lấy
dữ liệu thời tiết từ WeatherAPI.

| Phần | Nội dung | Cần API key? | Trạng thái xác minh |
|---|---|---|---|
| [`01-function-calling`](01-function-calling/) | Function Calling thuần với Gemini SDK | Gemini (tuỳ chọn) | ✅ Unit test 29/29 (offline) |
| [`02-mcp-basics`](02-mcp-basics/) | MCP server + client qua stdio | Không | ✅ Integration 12/12 (stdio thật) |
| [`03-production`](03-production/) | Auth (HTTP), Tool Registry, Versioning | Không | ✅ Auth 8/8, Registry 29/29, Versioning 18/18 |
| [`04-lab`](04-lab/) | ADK agent + WeatherMCP (Streamable HTTP) + WeatherAPI | Gemini + WeatherAPI | ✅ Server 139/139, client 43+13 skip (56 collected), **E2E 13/13 với dữ liệu THẬT** |

> **Kết quả thực nghiệm đầy đủ (kèm các phần CHƯA xác minh):**
> [`reports/test-results.md`](reports/test-results.md) ·
> [`reports/implementation-summary.md`](reports/implementation-summary.md)

---

## 1. Function Calling và MCP khác nhau ở đâu?

Hai khái niệm này ở **hai tầng khác nhau** và **bổ sung cho nhau**, không thay thế nhau.

**Function Calling** là một *khả năng của model*. Khi bạn đưa cho model danh sách
"công cụ" kèm schema tham số, nó có thể tự quyết định gọi công cụ nào và sinh ra
JSON tham số phù hợp. Model **không chạy** function — nó chỉ nói *"hãy gọi
`get_weather(city='Hanoi')`"*. Ứng dụng của bạn mới là nơi thực thi.

**MCP** là một *giao thức chuẩn*. Nó định nghĩa cách một **MCP Client** (Claude Code,
Cursor, ADK agent...) kết nối tới các **MCP Server** để khám phá và gọi tools,
resources, prompts một cách thống nhất — giống USB-C cho thế giới AI.

| Tiêu chí | Function Calling | MCP |
|---|---|---|
| Bản chất | Năng lực của model | Giao thức client–server |
| Ai định nghĩa tool? | Bạn hard-code trong từng app | Server tự công bố (self-describe) |
| Tái sử dụng | Viết lại cho mỗi app/model | Viết 1 lần, mọi MCP client dùng được |
| Nơi thực thi | Trong app | Trong MCP server |
| Chuẩn hoá | Mỗi nhà cung cấp một kiểu | Một chuẩn chung |

**Quan hệ:** MCP *dùng* Function Calling bên dưới. LLM quyết định gọi tool nào
(Function Calling), MCP lo việc kết nối và thực thi tool đó.

---

## 2. Kiến trúc tổng thể

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ 01 / 02 — Minh hoạ khái niệm (không cần API key, chạy ngay)                  │
│                                                                              │
│  01: User ─▶ Gemini ──"gọi get_weather(Hà Nội)"──▶ APP tự chạy hàm ─▶ Gemini │
│                                                                              │
│  02: weather_client.py ══[ MCP / stdio ]══ weather_server.py                 │
│      list_tools / call_tool                @mcp.tool() tự sinh schema        │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│ 03 — Production concerns                                                     │
│                                                                              │
│  3a Auth        client ──HTTP + Bearer──▶ auth_server.py  (401/403 tại tầng   │
│                                                             transport)       │
│  3b Registry    agent ─▶ registry.json (tag/keyword/version) ─▶ server đúng   │
│  3c Versioning  versioned_server.py: get_weather (v1) + get_weather_v2 +      │
│                 resource server://info                                        │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│ 04 — Lab thật: Google ADK + MCP + WeatherAPI                                 │
│                                                                              │
│  User ─▶ ADK Web UI ─▶ Gemini ──Function Calling──▶ ADK McpToolset           │
│                                                        │ Streamable HTTP     │
│                                                        ▼                     │
│                              weather.py (FastMCP, :8085/mcp)                 │
│                                                        │ HTTPS               │
│                                                        ▼                     │
│                                             api.weatherapi.com               │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Cấu trúc repo

```
KX-Day26-TaVanTuan-2A202602806/
├── README.md                     ← bạn đang đọc
├── requirements.txt              ← deps cho module 01–03 (mcp 2.x)
├── requirements-dev.txt          ← pytest
├── pytest.ini                    ← cấu hình test suite gốc
├── .env.example                  ← mẫu cấu hình cho module 01–03
├── .github/workflows/ci.yml      ← CI offline (không cần API key)
│
├── 01-function-calling/
│   ├── README.md
│   └── weather_function_calling.py
│
├── 02-mcp-basics/
│   ├── README.md
│   ├── weather_server.py
│   └── weather_client.py
│
├── 03-production/
│   ├── README.md
│   ├── auth_server.py            auth_server.py + auth_client.py
│   ├── auth_client.py
│   ├── registry.json
│   ├── registry_client.py
│   ├── versioned_server.py
│   └── versioned_client.py
│
├── 04-lab/                       ← MÔI TRƯỜNG uv RIÊNG cho từng thư mục con
│   ├── README.md
│   ├── mcp-server/               FastMCP + WeatherAPI (Streamable HTTP)
│   │   ├── weather.py
│   │   ├── Dockerfile            .dockerignore, .env.example
│   │   ├── pyproject.toml / uv.lock
│   │   └── tests/                139 test (unit + MCP stdio + MCP HTTP)
│   └── mcp-client/               Google ADK agent (McpToolset)
│       ├── weather_agent/
│       │   ├── agent.py
│       │   └── __init__.py
│       ├── env_setup.py          nguồn cấu hình .env duy nhất
│       ├── verify_setup.py       xác minh 9 tầng
│       ├── pyproject.toml / uv.lock
│       ├── .env.example
│       └── tests/                unit + E2E (5 câu hỏi)
│
├── tests/                        ← test suite cho module 01–03
│   ├── conftest.py
│   ├── test_01_function_calling.py
│   ├── test_02_mcp_stdio.py
│   ├── test_03_auth_http.py
│   ├── test_03_registry.py
│   └── test_03_versioning.py
│
└── reports/
    ├── implementation-summary.md
    └── test-results.md
```

> ⚠️ **Hai môi trường KHÔNG trộn lẫn.** Module 01–03 dùng **MCP SDK v2** (mcp 2.x,
  `mcp.server.mcpserver.MCPServer`). Lab 04 dùng **mcp 1.x** (`mcp.server.fastmcp.FastMCP`,
  do ADK yêu cầu). API của hai bản KHÁC nhau — xem [Troubleshooting](#11-troubleshooting).

---

## 4. Yêu cầu hệ thống

| Thành phần | Phiên bản đã kiểm thử |
|---|---|
| Python | 3.12.13 (>= 3.10) |
| pip | 25.x |
| uv | 0.11.x — cần cho Lab 04 |
| Docker | 29.8.2 — chỉ cần nếu build image Lab 04 |
| OS đã kiểm thử | Windows 11 + PowerShell 5.1 |
| OS hỗ trợ | Linux / macOS (lệnh activate khác, xem dưới) |

---

## 5. Cài đặt

### 5.1. Windows PowerShell (đã kiểm thử)

```powershell
# Module 01–03
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt

# Lab 04 — môi trường riêng, KHÔNG cài vào .venv ở trên
cd 04-lab\mcp-server;  uv sync --frozen
cd ..\mcp-client;      uv sync --frozen
cd ..\..
```

### 5.2. Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

cd 04-lab/mcp-server && uv sync --frozen && cd ../..
cd 04-lab/mcp-client && uv sync --frozen && cd ../..
```

---

## 6. API key & cấu hình `.env`

`.env` đã được `.gitignore` — **không bao giờ commit key**. Mỗi chỗ đều có
`.env.example` để copy.

### 6.1. Gemini API key (module 01, và Lab 04)

Lấy miễn phí: <https://aistudio.google.com/apikey>

Cả hai tên đều được chấp nhận: `GOOGLE_API_KEY` **hoặc** `GEMINI_API_KEY`.
Module 01 nhận cả hai; Lab 04 tự đồng bộ alias (`04-lab/mcp-client/env_setup.py`).

```powershell
# Cách A — file .env ở thư mục gốc repo (đã có .env.example)
Copy-Item .env.example .env
notepad .env

# Cách B — export tạm trong phiên PowerShell
$env:GOOGLE_API_KEY = "key-cua-ban"
```

> ⚠️ Nếu key của bạn bị **giới hạn IP** (Google Cloud key restriction), request từ
> máy khác sẽ nhận `403 PERMISSION_DENIED / API_KEY_IP_ADDRESS_BLOCKED`.
> Đây là lỗi cấu hình phía Google, không phải lỗi code.

### 6.2. WeatherAPI key (chỉ Lab 04)

Đăng ký miễn phí: <https://www.weatherapi.com/signup.aspx>
Free tier: 1 triệu request/tháng, dự báo tối đa **3 ngày**.
Key có dạng 31–32 ký tự hex.

```powershell
# Cách A (khuyến nghị) — MCP server TỰ NẠP .env cạnh nó
Copy-Item 04-lab\mcp-server\.env.example 04-lab\mcp-server\.env
notepad 04-lab\mcp-server\.env      # điền WEATHERAPI_KEY=...

# Cách B — export cho phiên hiện tại
$env:WEATHERAPI_KEY = "key-cua-ban"
```

> Server nạp `.env` theo thứ tự: `04-lab/mcp-server/.env` → `<repo root>/.env`.
> Nếu `.env` có mà thiếu `python-dotenv`, server in cảnh báo ra **stderr** chứ
> không im lặng bỏ qua. Xem log khởi động để biết file nào đã được nạp.

### 6.3. Bảng biến môi trường

| Biến | Nơi dùng | Mặc định | Ý nghĩa |
|---|---|---|---|
| `GOOGLE_API_KEY` / `GEMINI_API_KEY` | 01, 04-client | — | Khoá Gemini |
| `MCP_SERVER_URL` | 03a client, 04-client | `http://localhost:8085/mcp` (04) / `http://127.0.0.1:8000/mcp` (03a) | URL MCP endpoint |
| `WEATHERAPI_KEY` | 04-server | — | Khoá WeatherAPI (server tự nạp `.env`) |
| `PORT` | 03a, 04-server | 8000 / 8085 | Cổng lắng nghe |
| `HOST` | 03a, 04-server | 127.0.0.1 / 0.0.0.0 | Interface |
| `MCP_TRANSPORT` | 04-server | `streamable-http` | `streamable-http` / `stdio` / `sse` |
| `WEATHERAPI_TIMEOUT` | 04-server | 15 | Timeout giây |
| `MCP_AUTH_TOKEN` | 03a | `dev-token-abc123` | Token demo (KHÔNG phải secret thật) |
| `GEMINI_MODEL` | 04-client | `gemini-2.5-flash` | Model ADK dùng |
| `MCP_TIMEOUT` | 04-client | 30 | Timeout kết nối MCP |
| `DAY26_E2E` | test | `0` | `1` để bật E2E test |

---

## 7. Cách chạy từng phần

### 7.1. 01 — Function Calling

```powershell
cd 01-function-calling
..\.venv\Scripts\python.exe weather_function_calling.py
# hoặc hỏi câu khác:
..\.venv\Scripts\python.exe weather_function_calling.py "Thời tiết Đà Nẵng thế nào?"
```

Không có API key → chạy chế độ **offline** (in rõ nhãn `[OFFLINE]`, dùng dữ liệu
MOCK, KHÔNG gọi model). Có key → model gọi tool thật rồi tổng hợp câu trả lời.

### 7.2. 02 — MCP Basics (không cần key)

```powershell
cd 02-mcp-basics
..\.venv\Scripts\python.exe weather_client.py
```

Client tự spawn `weather_server.py` qua stdio, bắt tay MCP, `list_tools`, rồi
`call_tool` cho **Hanoi / Danang / Haiphong**, cuối cùng demo xử lý 4 loại tool error.

### 7.3. 03a — Authentication (cần 2 terminal)

```powershell
# Terminal 1
cd 03-production
$env:PORT = 8090            # 8000 có thể bị Docker Desktop chiếm trên Windows
..\.venv\Scripts\python.exe auth_server.py

# Terminal 2
cd 03-production
$env:MCP_SERVER_URL = "http://127.0.0.1:8090/mcp"
..\.venv\Scripts\python.exe auth_client.py
```

`auth_client.py` in ra **status code thật** cho 4 tình huống (xem mục 9).

### 7.4. 03b — Tool Registry (không cần server ngoài)

```powershell
cd 03-production; ..\.venv\Scripts\python.exe registry_client.py
```

### 7.5. 03c — Versioning

```powershell
cd 03-production; ..\.venv\Scripts\python.exe versioned_client.py
```

### 7.6. 04 — Lab: MCP Weather Server

```powershell
cd 04-lab\mcp-server
$env:WEATHERAPI_KEY = "key-cua-ban"

# Cách A (khuyến nghị) — đúng như README Lab và Docker/Cloud Run
uv run python weather.py
# → Server nghe tại http://localhost:8085/mcp  (transport=streamable-http)

# Cách B — nếu client sẽ spawn server làm subprocess
$env:MCP_TRANSPORT = "stdio"; uv run python weather.py
```

Server **luôn** chạy Streamable HTTP trừ khi bạn đặt tường minh
`MCP_TRANSPORT=stdio`. (Trước đây server tự chuyển sang stdio khi thấy TTY — hành
vi phụ thuộc terminal đó đã bị bỏ.)

### 7.7. 04 — Lab: ADK Agent (adk web)

```powershell
cd 04-lab\mcp-client
Copy-Item .env.example .env      # rồi điền GOOGLE_API_KEY
uv run adk web                   # mở http://localhost:8000, chọn agent weather_agent
```

Hoặc chạy không cần UI, chỉ để kiểm tra cấu hình:

```powershell
uv run python verify_setup.py                 # xác minh 9 tầng
uv run python verify_setup.py --no-network    # không gọi Gemini
```

### 7.8. 04 — Docker build (không cần deploy)

```powershell
cd 04-lab\mcp-server
docker build -t day26-weather-mcp:local .
docker run --rm -p 8085:8080 -e WEATHERAPI_KEY="key-cua-ban" day26-weather-mcp:local
# → http://localhost:8085/mcp
```

---

## 8. Chạy test

```powershell
# Module 01–03 (venv gốc)
.\.venv\Scripts\python.exe -m pytest -q

# Lab 04 — mỗi thư mục tự chạy với môi trường uv của nó
cd 04-lab\mcp-server; uv run --with pytest pytest tests -q; cd ..\..
cd 04-lab\mcp-client; uv run --with pytest pytest tests -q; cd ..\..

# E2E Lab 04 (gọi Gemini thật — tự tắt mặc định để không tiêu quota)
cd 04-lab\mcp-client
$env:DAY26_E2E = "1"; uv run --with pytest pytest tests/test_e2e_agent.py -q -s
```

`uv run --with pytest` cài pytest vào lớp phủ tạm thời → **không sửa `uv.lock`**.

---

## 9. Kết quả mong đợi (đã chạy thật)

### 02 — MCP Basics

```
✅ Bắt tay MCP thành công: weather v1.0.0
   protocolVersion: 2025-11-25

Tools server cung cấp:
  - get_weather: Lấy thời tiết hiện tại của một thành phố.
      schema tự sinh: {"properties": {"city": {"type": "string"}}, "required": ["city"], "type": "object"}

✅ call_tool get_weather(city='Hanoi'):
  -> Hanoi: 29°C, trời mưa
...
--- Kiểm tra xử lý lỗi (các lỗi này là CỐ Ý) ---
  [thiếu tham số bắt buộc] is_error=True
  [sai kiểu tham số] is_error=True
  [tool không tồn tại] is_error=True
  [vi phạm nghiệp vụ (city rỗng)] is_error=True
```

### 03a — Auth: status code đo được thực tế

```
✅ không có token: HTTP 401 (kỳ vọng 401) — AUTHENTICATION thiếu → 401
     WWW-Authenticate: Bearer error="invalid_token" ...
✅ token sai: HTTP 401 (kỳ vọng 401) — AUTHENTICATION sai → 401
✅ token hiệu lực, thiếu scope: HTTP 403 (kỳ vọng 403) — AUTHORIZATION thiếu scope → 403
     WWW-Authenticate: Bearer error="insufficient_scope", error_description="Required scope: weather:read"
✅ token hợp lệ: HTTP 200 (kỳ vọng 200) — hợp lệ → 200
```

> **Sửa so với README cũ:** README trước ghi *"Token sai → 403"*. Đo thực tế trên
> MCP SDK v2: token sai trả **401** (`invalid_token`). **403** dành cho trường hợp
> đã xác thực nhưng **thiếu scope** (`insufficient_scope`) — đúng theo RFC 6750.
> Repo này hiện hiện thực cả hai để phân biệt rõ authentication vs authorization.

### 04 — verify_setup.py

```
✅ [PASS        ] 1. Environment
✅ [PASS        ] 2. Dependencies
✅ [PASS        ] 3. Agent structure
✅ [PASS        ] 4. HTTP reachable
✅ [PASS        ] 5. MCP handshake      tools nhận được: [get_current_weather, get_forecast, health_check]
✅ [PASS        ] 6. Tool discovery
✅ [PASS        ] 7. Tool invocation    status=ok transport=streamable-http weatherapi_key_configured=True
✅ [PASS        ] 8. WeatherAPI         Lấy được dữ liệu thời tiết THẬT qua MCP
✅ [PASS        ] 9. Gemini API         phản hồi: 'OK'

Tổng kết: ✅ PASS=9  ❌ FAIL=0  ⚠️  WARN=0  ➖ NOT VERIFIED=0
```

Khi **chưa** có `WEATHERAPI_KEY`, tầng 8/9 sẽ báo `NOT VERIFIED` (không phải PASS)
và script vẫn thoát 0 nếu không có FAIL.

---

## 10. Bảo mật

- **Không hard-code secret.** Mọi key đọc từ biến môi trường; `.env` đã gitignore;
  `.dockerignore` loại `.env` khỏi image; Dockerfile không chứa key.
- **Không log token.** `auth_server.py` chỉ log dạng đã che
  (`wron…en(len=11)`); test khẳng định token không xuất hiện trong log.
- **Chống rò rỉ key qua thông báo lỗi.** `weather.py` có `_scrub()` che key nếu
  upstream echo lại; module 01 cũng có `_scrub_secrets()`.
- **Mặc định nghe local.** `auth_server.py` bind `127.0.0.1` (đặt `HOST=0.0.0.0`
  mới expose). Lab server bind `0.0.0.0` vì cần cho Docker/Cloud Run.
- **Static token chỉ là DEMO.** `dev-token-abc123` nằm trong source, không có
  expiry/rotation, không phân quyền theo tool. Production phải dùng JWT có chữ ký
  + expiry, OAuth 2.1, hoặc mTLS.
- **`validate_token_resource=False` được đặt tường minh** vì `StaticTokenVerifier`
  không kiểm tra audience — đây là điểm yếu đã biết của demo, không phải hành vi
  ngầm định.

---

## 11. Troubleshooting

| Triệu chứng | Nguyên nhân thật | Cách xử lý |
|---|---|---|
| `ModuleNotFoundError: No module named 'mcp.server.fastmcp'` | Đang dùng mcp **2.x** cho code viết cho mcp **1.x** (hoặc ngược lại) | Lab 04 phải chạy trong môi trường uv riêng (`uv run ...`). Module 01–03 phải chạy trong `.venv` gốc |
| `ImportError: cannot import name 'MCPServer'` | Đang dùng mcp **1.x** cho code 01–03 | `pip install -r requirements.txt` (mcp 2.x) |
| `TypeError: unsupported operand type(s) for +: 'float' and 'Timeout'` | Truyền `httpx.Timeout` cho SDK v2 (SDK v2 dùng **httpx2**) | Truyền số giây (float) hoặc `httpx2.Timeout` |
| `UnicodeEncodeError: 'charmap' codec can't encode...` | Console Windows dùng cp1252 khi stdout bị pipe | Đã sửa trong code (`reconfigure(encoding="utf-8")`). Nếu tự viết script: thêm dòng đó |
| `[Errno 10048] only one usage of each socket address` khi chạy `auth_server.py` | Cổng 8000 bị chiếm (rất thường gặp: Docker Desktop) | `$env:PORT=8090` và đặt `MCP_SERVER_URL` tương ứng |
| Client báo `ConnectError` tới `localhost:8085/mcp` | MCP server chưa chạy | Chạy `uv run python weather.py` ở `04-lab/mcp-server` trước |
| Agent trả lời "không lấy được dữ liệu" / `WEATHERAPI_KEY chưa được cấu hình` | Key đặt sai tiến trình (đặt ở client thay vì server) | Export `WEATHERAPI_KEY` **trong shell chạy server**, hoặc tạo `04-lab/mcp-server/.env` (server tự nạp). Kiểm tra log `[weather-mcp] .env đã nạp: ...` |
| Gemini trả `403 PERMISSION_DENIED ... API_KEY_IP_ADDRESS_BLOCKED` | Key Gemini bị giới hạn IP | Bỏ restriction trong Google Cloud Console, hoặc dùng key khác |
| `json.decoder.JSONDecodeError: Unexpected UTF-8 BOM` khi truyền JSON qua argv | PowerShell ghi BOM | `e2e_runner.py` đã đọc bằng `utf-8-sig`; hoặc dùng `@file.json` |
| ADK báo không thấy `GOOGLE_API_KEY` dù `.env` đã có | `.env` dùng tên `GEMINI_API_KEY` | Đã tự đồng bộ alias trong `env_setup.py`; cả hai tên đều chạy |
| `adk web` không thấy agent | Chạy sai thư mục | Phải chạy trong `04-lab/mcp-client` (nơi có `weather_agent/`) |

---

## 12. Giới hạn đã biết

1. **Dữ liệu thời tiết của module 01 và 02 là MOCK.** Chúng minh hoạ *cơ chế*,
   không phải weather service. Muốn dữ liệu thật → Lab 04.
2. **WeatherAPI free tier giới hạn 3 ngày dự báo.** `get_forecast` chủ động **từ
   chối** `days` ngoài khoảng 1–3 (kể cả 0 và số âm) và **không** gửi request lên
   upstream, thay vì âm thầm cắt về 3.
3. **Auth demo dùng static token trong source** — không dùng được cho production.
4. **`registry.json` có 2 entry minh hoạ** (`send_email`, `query_db`) trỏ tới
   endpoint nội bộ không tồn tại. Script không gọi chúng; nếu gọi sẽ lỗi rõ ràng.
5. **`tests/test_e2e_agent.py` mặc định TẮT** (`DAY26_E2E=0`) để không tiêu quota
   Gemini ngoài ý muốn.
6. **Không deploy Cloud Run.** Dockerfile đã được build và chạy thử local; deploy
   thật cần tài khoản GCP và có thể phát sinh chi phí.

---

## 13. Kết quả xác minh thực tế

Môi trường: Windows 11, Python 3.12.13, mcp 2.3.0 (01–03) / mcp 1.28.1 + ADK 2.3.0
(04), Docker 29.8.2.

| Nhóm test | Số test thu thập | Kết quả (E2E tắt / không cần key) |
|---|---|---|
| `tests/` (01–03) | **96** | ✅ **96 passed** |
| `04-lab/mcp-server/tests/` | **139** | ✅ **139 passed** |
| `04-lab/mcp-client/tests/` | **56** | ✅ **43 passed, 13 skipped** (13 test E2E tự tắt) |
| **Tổng** | **291** | ✅ **278 passed, 13 skipped, 0 FAIL** |

| Kiểm tra cần key/quota | Kết quả |
|---|---|
| `04-lab/mcp-client/tests/` với `DAY26_E2E=1` | ✅ cả 56 chạy; E2E 13/13 **với dữ liệu THẬT** (đã xác minh trước đó) |
| `verify_setup.py` (server + WeatherAPI key thật) | ✅ **PASS=9, FAIL=0, NOT VERIFIED=0** |
| `verify_setup.py --no-network` (không có key, như CI) | ✅ **PASS=7, FAIL=0, NOT VERIFIED=2**, exit 0 |
| Docker build + chạy container + MCP handshake | ✅ thành công; container có key thật trả **Hà Nội 29.9°C / Cloudy**; không có secret trong image |
| **WeatherAPI dữ liệu THẬT** | ✅ **VERIFIED** — Hà Nội **31.6°C / Cloudy** (ngoài container), **29.9°C** (trong container), Đà Nẵng **3 ngày** dự báo thật |
| **E2E toàn chuỗi (User→Gemini→ADK→MCP→WeatherAPI→Gemini→User)** | ✅ **VERIFIED** — 13/13, `mode=real-weatherapi`, Hà Nội 31.6°C vs HCM 29.5°C |
| Gemini API | ✅ VERIFIED (key bị giới hạn IP → độ ổn định thay đổi theo IP egress) |
| GitHub Actions (`.github/workflows/ci.yml`) | ⚠️ **CHƯA CHẠY ĐƯỢC** — chỉ xác thực YAML hợp lệ và mô phỏng từng bước ở local; chưa push nên chưa có lần chạy thật trên GitHub |

> **Vì sao số test tăng qua các lần?** Không có test nào bị xoá — chỉ **thêm** regression
> test. MCP Server: `65 → 66` (thêm test nạp `.env`) `→ 68` (2 test đường dẫn nông Docker)
> `→ **139**` (71 test cho nested JSON sai kiểu + `health_check` transport).
> MCP Client: `55 → **56**` (thêm `test_find_repo_root_uses_markers_not_depth`).

**Các mục chưa xác minh:** chạy GitHub Actions thật trên GitHub (chưa push), Cloud Run
deploy (không deploy để tránh phát sinh chi phí) và tương tác thủ công trên UI `adk web`
(E2E chạy qua `InMemoryRunner` cùng `root_agent`).
Chi tiết đầy đủ: [`reports/test-results.md`](reports/test-results.md).

---

## 14. Đọc tiếp

- [01 — Function Calling](01-function-calling/README.md)
- [02 — MCP Basics](02-mcp-basics/README.md)
- [03 — Production](03-production/README.md)
- [04 — Lab](04-lab/README.md)
- [Báo cáo triển khai](reports/implementation-summary.md)
- [Báo cáo kiểm thử](reports/test-results.md)
