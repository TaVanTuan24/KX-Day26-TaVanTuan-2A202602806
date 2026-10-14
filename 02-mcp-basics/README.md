# 02 — MCP Basics (Server + Client)

Cùng tool `get_weather`, nhưng giờ tách ra **MCP server độc lập**. Server tự công bố
tool qua giao thức MCP; bất kỳ client nào (Claude Code, Cursor, hoặc `weather_client.py`)
cũng cắm vào dùng được — không cần biết code bên trong.

```
weather_client.py                       weather_server.py
┌─────────────┐    giao thức MCP    ┌─────────────────┐
│  list_tools │ ──────────────────▶ │ @mcp.tool()     │
│  call_tool  │ ◀────────────────── │ get_weather()   │
└─────────────┘     stdio           └─────────────────┘
```

## Cách chạy (không cần API key)

```powershell
pip install -r ..\requirements.txt
python weather_client.py     # client tự khởi động weather_server.py
```

Client dùng đường dẫn server tính từ `__file__`, nên chạy được từ **bất kỳ thư
mục nào**:

```powershell
python 02-mcp-basics\weather_client.py
```

Kết quả mong đợi:

```
✅ Bắt tay MCP thành công: weather v1.0.0
   protocolVersion: 2025-11-25

Tools server cung cấp:
  - get_weather: Lấy thời tiết hiện tại của một thành phố.
      schema tự sinh: {"properties": {"city": {"type": "string"}}, "required": ["city"], "type": "object"}

✅ call_tool get_weather(city='Hanoi'):
  -> Hanoi: 29°C, trời mưa

✅ call_tool get_weather(city='Danang'):
  -> Danang: 30°C, nhiều mây

✅ call_tool get_weather(city='Haiphong'):
  -> Haiphong: 33°C, mưa rào

--- Kiểm tra xử lý lỗi (các lỗi này là CỐ Ý) ---
  [thiếu tham số bắt buộc] is_error=True
      Error executing tool get_weather: 1 validation error for get_weatherArguments
  [sai kiểu tham số] is_error=True
      Error executing tool get_weather: 1 validation error for get_weatherArguments
  [tool không tồn tại] is_error=True
      Unknown tool: khong_ton_tai
  [vi phạm nghiệp vụ (city rỗng)] is_error=True
      Error executing tool get_weather: Tên thành phố không được để trống

✅ Tất cả lời gọi tool đều thành công.
```

## Files

| File | Mô tả |
|---|---|
| `weather_server.py` | MCP server — `@mcp.tool()` tự sinh schema từ type hints + docstring |
| `weather_client.py` | MCP client — `list_tools` + `call_tool` qua stdio transport |
| `../../tests/test_02_mcp_stdio.py` | 12 integration test (MCP server thật qua stdio) |

---

## Hai điểm dễ sai khi viết MCP server

### 1. `print()` ra stdout sẽ phá giao thức stdio

Khi transport là `stdio`, **stdout chính là kênh JSON-RPC**. Một dòng `print()`
làm client không parse được và mất kết nối. Mọi thông báo phải đi ra
`sys.stderr` (hoặc `logging`).

Repo có test khẳng định điều này — nó nói chuyện RAW bằng JSON-RPC và parse
**từng dòng** stdout:

```powershell
python -m pytest tests/test_02_mcp_stdio.py::test_stdio_stdout_carries_only_jsonrpc -q
```

### 2. Lỗi nghiệp vụ nên `raise ToolError`, không phải `ValueError`

| Cách | Client nhận được | Log server |
|---|---|---|
| `raise ToolError("...")` | `is_error=True`, thông báo gọn | Sạch |
| `raise ValueError("...")` | `is_error=True` | ERROR + traceback đầy đủ |

Cả hai đều **không** làm sập client — nhưng `ToolError`
(`mcp.server.mcpserver.exceptions.ToolError`) là cách đúng cho lỗi nghiệp vụ.

> Client cũng phải chịu được lỗi tầng schema (thiếu tham số, sai kiểu) và lỗi
> giao thức (`Unknown tool`) — `weather_client.py` xử lý cả ba nhóm và **không
> sập**. Lưu ý: `call_tool` **không raise** cho các lỗi này ở MCP SDK v2; nó trả
> về `CallToolResult` với `is_error=True`. (mcp 1.x dùng tên `isError`.)

---

## MCP là gì? Giải thích đơn giản

### Phép so sánh: ổ cắm điện chuẩn

```
KHÔNG CÓ MCP (mỗi nhà 1 kiểu ổ cắm)
══════════════════════════════════════

  Quạt ──[phích A]──▶ Ổ cắm nhà 1       ← Quạt chỉ dùng được ở nhà 1
  Quạt ──[phích B]──▶ Ổ cắm nhà 2       ← Phải đổi phích cho nhà 2
  Quạt ──[phích C]──▶ Ổ cắm nhà 3       ← Lại đổi phích cho nhà 3

  Mỗi nhà 1 kiểu ổ → mua thiết bị phải xem nhà dùng ổ gì


CÓ MCP (chuẩn hoá ổ cắm)
══════════════════════════

  Quạt  ──┐                    ┌── Nhà 1
  Tivi  ──┼── ổ cắm chuẩn ──   ├── Nhà 2
  Máy lạnh┘                    └── Nhà 3

  Viết tool 1 lần → mọi AI app dùng được
  Viết client 1 lần → mọi tool server cắm vào được
```

### 3 bước MCP hoạt động

```
Bước 1 — KHÁM PHÁ: "Anh có tool gì?"
══════════════════════════════════════

  Client                          Server
    │                               │
    │── "list_tools()" ───────────▶ │
    │                               │  Server tự trả lời:
    │                               │  "Tôi có get_weather(city: str)"
    │◀── [{name, description,  ──── │  Schema SINH TỰ ĐỘNG
    │      parameters}]             │  từ type hints + docstring
    │                               │

  So sánh Function Calling:
    FC:  Developer viết schema THỦ CÔNG 15+ dòng
    MCP: @mcp.tool() → schema TỰ SINH từ type hints


Bước 2 — GỌI TOOL: "Cho tôi thời tiết HN"
═══════════════════════════════════════════

  Client                          Server
    │                               │
    │── call_tool("get_weather", ─▶ │
    │    {"city": "Hanoi"})         │
    │                               │  SERVER thực thi hàm
    │                               │  get_weather("Hanoi")
    │◀── "Hanoi: 29°C, mưa" ──────  │
    │                               │

  So sánh Function Calling:
    FC:  APP phải tự chạy hàm
    MCP: SERVER chạy — client không cần biết code bên trong


Bước 3 — TÁI SỬ DỤNG: viết 1 lần, dùng mọi nơi
═════════════════════════════════════════════════

                     ┌── Claude Code
                     │      "list_tools → get_weather"
  weather_server.py ─┼── Cursor
                     │      "list_tools → get_weather"
                     ├── Gemini CLI
                     │      "list_tools → get_weather"
                     └── App tự viết
                            "list_tools → get_weather"

  1 server phục vụ N client — không sửa dòng code nào
```

---

## So sánh code: Function Calling vs MCP

### Khai báo tool

```
Function Calling (01):                    MCP (02):
30 dòng schema viết tay                   4 dòng, tự sinh schema

types.FunctionDeclaration(                @mcp.tool()
  name="get_weather",                     def get_weather(city: str) -> str:
  description="Lấy thời tiết...",             """Lấy thời tiết..."""
  parameters=types.Schema(                    return f"{city}: 29°C"
    type=types.Type.OBJECT,
    properties={                           ✅ Schema tự sinh từ:
      "city": types.Schema(                   city: str    → type: string
        type=types.Type.STRING,               -> str       → return type
        description="Tên thành phố"           docstring    → description
      )
    },
    required=["city"],
  ),
)
```

### Nơi thực thi

```
Function Calling:                          MCP:
Mọi thứ trong 1 file                      Tách server / client

┌── weather_app.py ──────────┐             ┌── server.py ─────────┐
│                            │             │  @mcp.tool()         │
│  schema = {...}            │             │  def get_weather():  │
│  def get_weather(): ...    │             │      ...             │
│  model.generate(...)       │             └──────────────────────┘
│  result = get_weather()    │                       ▲
│                            │                       │ MCP
└────────────────────────────┘                       │
                                           ┌── client.py ─────────┐
App = schema + hàm + model                 │  list_tools()        │
    = làm hết mọi thứ                      │  call_tool()         │
                                           └──────────────────────┘

                                           Client chỉ biết giao thức
                                           Server chỉ biết logic tool
```

### Thêm tool mới

```
Function Calling:                          MCP:

  App A: thêm schema + hàm                  Server: thêm 1 hàm @mcp.tool()
  App B: copy schema + hàm                  Client A: không đổi (tự khám phá)
  App C: copy schema + hàm                  Client B: không đổi
                                            Client C: không đổi
  3 chỗ phải sửa                             1 chỗ phải sửa
```

---

## Khác biệt so với Function Calling thuần

| | 01-function-calling | 02-mcp-basics |
|---|---|---|
| Khai báo schema | Viết tay `FunctionDeclaration` | `@mcp.tool()` tự sinh |
| Nơi thực thi tool | Trong app gọi model | Trong MCP server riêng |
| Khám phá tool | Hard-code danh sách | `list_tools()` tại runtime |
| Dùng lại ở app khác | Copy code | Cắm thêm client |

---

## MCP trong thực tế: kết hợp với LLM

Ví dụ trên chỉ demo **lớp giao thức** (không cần API key). Trong production, MCP kết hợp với Function Calling:

```
┌──────────────────────────────────────────────────────────┐
│                    Luồng đầy đủ                          │
│                                                          │
│  User: "Thời tiết HN?"                                   │
│    │                                                     │
│    ▼                                                     │
│  AI Client (Claude, Cursor...)                           │
│    │                                                     │
│    ├─ 1. list_tools() ──▶ MCP Server                     │
│    │◀── "có get_weather"                                 │
│    │                                                     │
│    ├─ 2. Gửi prompt + tool list cho LLM                  │
│    │◀── LLM dùng FUNCTION CALLING:                       │
│    │    "gọi get_weather(city='HN')"                     │
│    │                                                     │
│    ├─ 3. call_tool("get_weather") ──▶ MCP Server         │
│    │◀── "HN: 29°C, mưa"                                  │
│    │                                                     │
│    ├─ 4. Gửi kết quả cho LLM tổng hợp                    │
│    │◀── "HN 29°C, mưa, nhớ mang ô!"                      │
│    │                                                     │
│    ▼                                                     │
│  User nhận câu trả lời                                   │
│                                                          │
│  Function Calling = LLM quyết định gọi tool nào (bước 2) │
│  MCP = giao thức kết nối client ↔ server (bước 1, 3)     │
│  → Chúng BỔ SUNG cho nhau, không thay thế                │
└──────────────────────────────────────────────────────────┘
```

---

## Đăng ký server với AI client

**Claude Code** (làm 1 lần, dùng mãi):

```bash
claude mcp add weather -- python /đường/dẫn/tới/weather_server.py
```

**Gemini CLI**:

```bash
# Thêm vào ~/.gemini/settings.json
"mcpServers": {
  "weather": {
    "command": "python",
    "args": ["/đường/dẫn/tới/weather_server.py"]
  }
}
```

Bước tiếp theo: [03-production/](../03-production/) — Auth, Tool Registry, Versioning.
