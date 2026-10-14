# 01 — Function Calling thuần (Google Gemini SDK)

Tool `get_weather` được **định nghĩa schema thủ công** và **thực thi ngay trong app**.
Model chỉ quyết định gọi tool nào — app mới là nơi chạy.

```
User hỏi  →  Model quyết định gọi get_weather(city="Hà Nội")
                     │
                     ▼
              App TỰ THỰC THI hàm get_weather
                     │
                     ▼
              Model tổng hợp câu trả lời
```

> ⚠️ Dữ liệu thời tiết trong bài này là **MOCK**. Đây là bài học minh hoạ *cơ chế*
> function calling, không phải một weather service. Muốn dữ liệu thật, xem
> [`04-lab/`](../04-lab/).

## Cách chạy

**Windows PowerShell**

```powershell
pip install -r ..\requirements.txt
$env:GOOGLE_API_KEY = "key-cua-ban"        # hoặc GEMINI_API_KEY
python weather_function_calling.py
python weather_function_calling.py "Thời tiết Đà Nẵng thế nào?"
```

**Linux / macOS**

```bash
pip install -r ../requirements.txt
export GOOGLE_API_KEY=...
python weather_function_calling.py
```

Script cũng tự nạp `.env` ở thư mục gốc repo **nếu** `python-dotenv` có sẵn
(không bắt buộc).

**Không có API key?** Script chạy chế độ **offline**: in rõ nhãn `[OFFLINE]`, dùng
dữ liệu mock, và **không gọi model** — để không ai nhầm là Gemini đã trả lời.

## File

| File | Mô tả |
|---|---|
| `weather_function_calling.py` | Schema, thực thi tool, gọi Gemini, xử lý vòng lặp function calling |
| `../../tests/test_01_function_calling.py` | 29 unit test (không cần API key, không gọi mạng) |

## Kết quả mong đợi

```
User: Thời tiết Hà Nội và Đà Nẵng hôm nay thế nào?

  [model yêu cầu] get_weather({'city': 'Hà Nội'})
  [app thực thi]  -> {"city": "Hà Nội", "nhiệt_độ": "29°C", ...}
  [model yêu cầu] get_weather({'city': 'Đà Nẵng'})
  [app thực thi]  -> {"city": "Đà Nẵng", "nhiệt_độ": "30°C", ...}

Trả lời:
 Hà Nội 29°C, trời mưa nhẹ 🌧️ ...
 Đà Nẵng 30°C, nhiều mây 🌤️ ...
```

Không có key:

```
⚠️  Chưa có GOOGLE_API_KEY/GEMINI_API_KEY → chạy chế độ OFFLINE (dữ liệu mock, không gọi model).

Trả lời:
[OFFLINE — chưa có GOOGLE_API_KEY/GEMINI_API_KEY, không gọi Gemini]

Hà Nội: 29°C, trời mưa nhẹ 🌤️ (dữ liệu MOCK, không phải real-time). ...
```

## Chạy test

```powershell
# từ thư mục gốc repo
.\.venv\Scripts\python.exe -m pytest tests/test_01_function_calling.py -q
```

Test dùng **client Gemini giả** để kiểm tra vòng lặp function calling, nên chạy
được hoàn toàn offline.

---

## Function Calling là gì? Giải thích đơn giản

Hình dung bạn có một **trợ lý ảo** rất giỏi ngôn ngữ, nhưng **không biết gì về thế giới thật** — không biết thời tiết, không truy cập được database, không gọi được API.

Function Calling là cách bạn **dạy trợ lý ảo sử dụng công cụ**:

```
Không có Function Calling:                 Có Function Calling:

User: "Thời tiết HN?"                     User: "Thời tiết HN?"
       │                                         │
       ▼                                         ▼
   ┌────────┐                                ┌────────┐
   │ Model  │                                │ Model  │
   │        │                                │        │ ← biết có tool get_weather
   │ "Tôi   │                                │ "Hãy   │
   │ không  │                                │  gọi   │
   │ biết"  │                                │ get_   │
   │        │                                │ weather│
   └────────┘                                │("HN")  │
                                             └───┬────┘
   Model bó tay vì                               │
   không có dữ liệu                              ▼
                                             App chạy hàm
                                                  │
                                                  ▼
                                             ┌────────┐
                                             │ Model  │
                                             │ "HN:   │
                                             │ 29°C,  │
                                             │ mưa"   │
                                             └────────┘
```

**Điểm mấu chốt:** Model **KHÔNG chạy** hàm. Nó chỉ nói *"hãy gọi hàm X với tham số Y"*.

---

## Minh hoạ từng bước chi tiết

User hỏi: **"Thời tiết Hà Nội và Đà Nẵng hôm nay thế nào?"**

```
Bước 1 — App chuẩn bị "hộp công cụ" cho model
═══════════════════════════════════════════════

    App định nghĩa schema THỦ CÔNG:
    ┌────────────────────────────────────────┐
    │  Tool: get_weather                     │
    │  Mô tả: "Lấy thời tiết thành phố"      │
    │  Tham số:                              │
    │    city: string (bắt buộc)             │
    │                                        │
    │   Schema viết TAY - 15 dòng code       │
    │     phải khớp với hàm thật             │
    └────────────────────────────────────────┘

Bước 2 — Gửi prompt + schema cho model
═══════════════════════════════════════

    App ──────────────────────────────────────────▶ Gemini
    │  "Thời tiết HN và ĐN?"                      │
    │  + schema get_weather                       │
    │                                             │
    │  Model hiểu: "À, có tool get_weather,       │
    │   tôi cần gọi nó 2 lần cho HN và ĐN"        │

Bước 3 — Model TRẢ VỀ yêu cầu gọi tool (không tự chạy!)
═════════════════════════════════════════════════════════

    Gemini ──────────────────────────────────────▶ App
    │  function_calls:                             │
    │    [                                         │
    │      get_weather(city="Hà Nội"),             │
    │      get_weather(city="Đà Nẵng")             │
    │    ]                                         │
    │                                              │
    │    Model CHỈ sinh JSON — không hề chạy       │

Bước 4 — App TỰ THI HÀNH hàm get_weather
═════════════════════════════════════════

    App nhận yêu cầu → CHẠY hàm Python:
    ┌──────────────────────────────────────────┐
    │  get_weather("Hà Nội")   → "29°C, mưa"   │ ← App chạy
    │  get_weather("Đà Nẵng")  → "30°C, mây"   │ ← App chạy
    └──────────────────────────────────────────┘

Bước 5 — Gửi kết quả lại cho model tổng hợp
════════════════════════════════════════════

    App ──────────────────────────────────────────▶ Gemini
    │  Kết quả: HN 29°C mưa, ĐN 30°C mây         │
    │                                            │
    │  Gemini: "Hà Nội 29°C, mưa nhẹ 🌧️          │
    │           nhớ mang ô nhé!                  │
    │           Đà Nẵng 30°C, nhiều mây 🌤️       │
    │           thời tiết dễ chịu!"              │
```

---

## Nhìn vào code thật

3 phần quan trọng trong `weather_function_calling.py`:

**Phần 1 — Schema viết tay** (model cần biết tool trông như thế nào):

```python
# App phải TỰ MÔ TẢ tool cho model — viết tay, dễ sai
get_weather_declaration = types.FunctionDeclaration(
    name="get_weather",
    description="Lấy thời tiết hiện tại của một thành phố",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "city": types.Schema(type=types.Type.STRING, description="Tên thành phố")
        },
        required=["city"],
    ),
)
```

**Phần 2 — Hàm thực thi** (app tự chạy khi model yêu cầu):

```python
# App phải CÓ hàm thật để chạy — model không chạy hàm này
def get_weather(city: str) -> str:
    return json.dumps({"city": city, "nhiệt_độ": "29°C", ...})
```

**Phần 3 — Vòng lặp** (nhận yêu cầu → chạy → trả lại):

```python
for round_index in range(max_tool_rounds + 1):
    resp = client.models.generate_content(model=MODEL, contents=contents, config=config)
    if not resp.function_calls:
        return resp.text                      # câu trả lời cuối
    if round_index >= max_tool_rounds:
        raise MaxToolRoundsExceeded(...)      # chặn vòng lặp vô hạn
    contents.append(resp.candidates[0].content)
    for fc in resp.function_calls:            # hỗ trợ NHIỀU call một lượt
        result = execute_function_call(fc.name, fc.args)   # ← APP chạy
    contents.append(types.Content(role="user", parts=function_responses))
```

**Xử lý lỗi & giới hạn (điểm quan trọng khi lên production):**

| Tình huống | Hành vi |
|---|---|
| Model gọi tên function không tồn tại | Trả JSON `{"error": ..., "available_functions": [...]}` để model tự sửa |
| Tham số thiếu / thừa / sai kiểu | Trả JSON `{"error": "tham số không hợp lệ..."}` (không crash) |
| Function ném exception | Bắt và trả JSON lỗi kèm tên loại exception |
| Lỗi gọi Gemini API (key/quota/mạng) | In thông báo thân thiện, **che API key** khỏi thông báo lỗi |
| Model liên tục đòi gọi tool | Dừng sau `MAX_TOOL_ROUNDS = 5` vòng, raise `MaxToolRoundsExceeded` |
| Model trả về rỗng (bị chặn) | Thông báo rõ thay vì `None` |

> Cách trả lỗi dạng `{"error": ...}` thay vì raise là **đúng quy ước của
> google-genai**: SDK tự làm y hệt trong `_extra_utils.get_function_response_parts`.
> Nhờ vậy model *đọc được* lỗi và giải thích lại cho người dùng.

---

## Luồng hoạt động

1. App định nghĩa `FunctionDeclaration` với schema viết tay (tên, tham số, kiểu)
2. App gửi prompt + danh sách tool tới Gemini
3. Model trả về `function_calls` — yêu cầu gọi `get_weather`
4. App **tự chạy** hàm `get_weather()` và đưa kết quả trả lại model
5. Model tổng hợp câu trả lời cuối cho user

## Nhược điểm

```
┌─────────────────────────────────────────────────────────────┐
│  ❌ Schema viết tay                                         │
│     FunctionDeclaration(name=..., parameters=...)           │
│     → 15+ dòng boilerplate, dễ lệch với hàm thật            │
│                                                             │
│  ❌ Tool gắn chặt trong app                                 │
│     App A có get_weather → App B muốn dùng?                 │
│     → Copy schema + hàm sang App B                          │
│     → Sửa hàm ở A? Phải nhớ sửa cả B                        │
│                                                             │
│  ❌ Mỗi provider 1 format                                   │
│     Google: FunctionDeclaration(...)                        │
│     OpenAI: {"type": "function", "function": {...}}         │
│     Anthropic: {"name": ..., "input_schema": {...}}         │
│     → Đổi model = viết lại schema                           │
└─────────────────────────────────────────────────────────────┘
```

**MCP giải quyết tất cả các vấn đề trên** → xem [02-mcp-basics/](../02-mcp-basics/)

Bước tiếp theo: [02-mcp-basics/](../02-mcp-basics/) — tách tool ra MCP server độc lập.
