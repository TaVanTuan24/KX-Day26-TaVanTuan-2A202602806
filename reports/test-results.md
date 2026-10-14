# Test Results — Day 26

**Ngày chạy:** 2026-10-14
**Máy:** Windows 11 · PowerShell 5.1 · Python 3.12.13 · Docker 29.8.2 (linux/x86_64)

> Mọi số liệu dưới đây là kết quả **chạy thật** trên máy này. Những gì KHÔNG
> chạy được đều được ghi rõ là **NOT VERIFIED** kèm lý do cụ thể — không có số
> liệu nào được suy diễn hay làm tròn cho đẹp.

---

## 1. Tổng hợp

| # | Nhóm test | Lệnh | Kết quả |
|---|---|---|---|
| 1 | Module 01–03 (repo root) | `.\.venv\Scripts\python.exe -m pytest -q` | ✅ **96 passed** |
| 2 | Lab 04 — MCP server | `uv run --frozen --with pytest python -m pytest tests -q` | ✅ **68 passed** |
| 3 | Lab 04 — MCP client (E2E tắt) | như trên, trong `04-lab/mcp-client` | ✅ **43 passed, 13 skipped** |
| 4 | Lab 04 — E2E **dữ liệu THẬT** (`DAY26_E2E=1`) | `uv run --frozen --with pytest python -m pytest tests -q` | ✅ **55 passed** (0 FAIL) ở lần chạy sạch; **47 passed + 9 skipped, 0 FAIL** khi key bị chặn IP |
| 5 | Docker build + chạy container + MCP handshake | `docker build` / `docker run` | ✅ thành công, **kèm xác minh dữ liệu THẬT trong container** |
| 6 | `verify_setup.py` (server chạy, WeatherAPI key thật) | `uv run python verify_setup.py` | ✅ **PASS=9, FAIL=0, ➖ NOT VERIFIED=0** |

**Tổng test tự động: 96 + 68 + 55 = 219.**

> **Không bao giờ có FAIL giả.** Khi key Gemini bị chặn IP, các test E2E chuyển
> thành **SKIPPED** kèm dòng *"Đây KHÔNG phải PASS"* — số pass giảm nhưng số FAIL
> vẫn là **0**.

### Chi tiết theo file (module 01–03) — 96 passed

| File | Số test | Nội dung |
|---|---|---|
| `tests/test_01_function_calling.py` | 29 | Schema, mock weather, dispatch function, chế độ offline, vòng lặp + giới hạn, lỗi API |
| `tests/test_02_mcp_stdio.py` | 12 | MCP server thật qua stdio: handshake, list_tools, call_tool 3 thành phố, 4 loại tool error, stdout sạch JSON-RPC |
| `tests/test_03_auth_http.py` | 8 | Auth HTTP thật: 401/401/403/200, phiên MCP đầy đủ, không lộ token trong log |
| `tests/test_03_registry.py` | 29 | Registry: tag/keyword, best match, semantic version, 10 nhánh lỗi, endpoint minh hoạ lỗi rõ ràng |
| `tests/test_03_versioning.py` | 18 | v1 backward compat, v2 default, forecast, fahrenheit, units sai, `server://info` |

### Chi tiết theo file (Lab 04) — 68 + 55

| File | Số test | Nội dung |
|---|---|---|
| `04-lab/mcp-server/tests/test_weather_tools.py` | 60 | Validate `days` 1–3 (chặn trước khi gọi upstream), ánh xạ 401/400/429/5xx, JSON hỏng, timeout, lỗi mạng, payload thiếu trường, `health_check`, che key, chọn transport |
| `04-lab/mcp-server/tests/test_mcp_transports.py` | 8 | MCP thật qua stdio + Streamable HTTP, stdout sạch, endpoint `/mcp`, **nạp `.env`**, **regression đường dẫn nông kiểu Docker** |
| `04-lab/mcp-client/tests/test_agent_config.py` | 27 | `env_setup` alias, `find_repo_root`, cấu trúc agent, instruction chống bịa, các tầng `verify_setup` báo cáo đúng |
| `04-lab/mcp-client/tests/test_e2e_harness.py` | 16 | Trích xuất kết quả tool (chống assertion vô nghĩa), nhận diện lỗi tạm thời |
| `04-lab/mcp-client/tests/test_e2e_agent.py` | 13 | 5 câu hỏi bắt buộc + chế độ suy giảm + các chốt chống "PASS giả" |

---

## 2. Bằng chứng theo Phase

### Phase 3 — MCP Basics (không cần API key)

```powershell
cd 02-mcp-basics
..\.venv\Scripts\python.exe weather_client.py
```

```
✅ Bắt tay MCP thành công: weather v1.0.0
   protocolVersion: 2025-11-25

Tools server cung cấp:
  - get_weather: Lấy thời tiết hiện tại của một thành phố.
      schema tự sinh: {"properties": {"city": {"title": "City", "type": "string"}}, "required": ["city"], "type": "object", "title": "get_weatherArguments"}

✅ call_tool get_weather(city='Hanoi'):     -> Hanoi: 29°C, trời mưa
✅ call_tool get_weather(city='Danang'):    -> Danang: 30°C, nhiều mây
✅ call_tool get_weather(city='Haiphong'):  -> Haiphong: 33°C, mưa rào

--- Kiểm tra xử lý lỗi (các lỗi này là CỐ Ý) ---
  [thiếu tham số bắt buộc] is_error=True   Error executing tool get_weather: 1 validation error ...
  [sai kiểu tham số] is_error=True         Error executing tool get_weather: 1 validation error ...
  [tool không tồn tại] is_error=True       Unknown tool: khong_ton_tai
  [vi phạm nghiệp vụ (city rỗng)] is_error=True  Error executing tool get_weather: Tên thành phố không được để trống

✅ Tất cả lời gọi tool đều thành công.
```

### Phase 4a — Authentication: status code **đo được**

```
--- Đo status code thật (không giả định) ---
  ✅ không có token: HTTP 401 (kỳ vọng 401) — AUTHENTICATION thiếu → 401
       WWW-Authenticate: Bearer error="invalid_token", error_description="Authentication required", ...
  ✅ token sai: HTTP 401 (kỳ vọng 401) — AUTHENTICATION sai → 401
       WWW-Authenticate: Bearer error="invalid_token", ...
  ✅ token hiệu lực, thiếu scope: HTTP 403 (kỳ vọng 403) — AUTHORIZATION thiếu scope → 403
       WWW-Authenticate: Bearer error="insufficient_scope", error_description="Required scope: weather:read", ...
  ✅ token hợp lệ: HTTP 200 (kỳ vọng 200) — hợp lệ → 200
```

**Kết luận có bằng chứng:** README cũ ghi *"token sai → 403"* là **SAI**.
MCP SDK v2 trả **401** cho token sai; **403** dành cho token hợp lệ nhưng thiếu
scope. `tests/test_03_auth_http.py` khẳng định đúng hành động này (8/8 pass).

### Phase 4b/4c — Registry & Versioning

```
Best match: get_weather_v2 v2.0.0 (không deprecated, version cao nhất)
Kết quả: {"api_version": "2.0", "city": "Hanoi", "temp": 29, "units": "celsius", ...}

--- Xử lý lỗi ---
  [tool không tìm thấy]   Không tìm thấy tool (tag='khong-co-tag-nay', keyword=None)
  [registry JSON lỗi]     registry thiếu mục 'tools' (phải là object)
  [server không tồn tại]  Tool 'ghost_tool' trỏ tới server 'khong-ton-tai' không có trong mục 'servers'

[v1] get_weather('Hanoi')            -> Hanoi: 29°C, trời mưa          (hợp đồng cũ KHÔNG đổi)
[v2] get_weather_v2('Danang')        -> {"units": "celsius", ...}      (default hợp lệ)
[v2] get_weather_v2('Hanoi', units='fahrenheit') -> "temp": 84.2
[v2] get_weather_v2('Hanoi', units='kelvin')     -> {"error": "units không hợp lệ: 'kelvin'", "supported_units": [...]}
✅ v1 và v2 cùng hoạt động — backward compatibility được giữ.
```

### Phase 5.4 — `verify_setup.py` (9 tầng, WeatherAPI key THẬT)

```
✅ [PASS        ] 1. Environment
✅ [PASS        ] 2. Dependencies       google-adk==2.3.0, mcp==1.28.1, google-genai==2.10.0, httpx==0.28.1
✅ [PASS        ] 3. Agent structure    root_agent.name=weather_agent, model=gemini-2.5-flash, tools=1
✅ [PASS        ] 4. HTTP reachable     ⚠️  KHÔNG suy ra MCP hoạt động từ tầng này. Xem tầng 5–6.
✅ [PASS        ] 5. MCP handshake      tools nhận được: ['get_current_weather', 'get_forecast', 'health_check']
✅ [PASS        ] 6. Tool discovery
✅ [PASS        ] 7. Tool invocation    status=ok transport=streamable-http weatherapi_key_configured=True
✅ [PASS        ] 8. WeatherAPI         Lấy được dữ liệu thời tiết THẬT qua MCP
✅ [PASS        ] 9. Gemini API         phản hồi: 'OK'

Tổng kết: ✅ PASS=9  ❌ FAIL=0  ⚠️  WARN=0  ➖ NOT VERIFIED=0
```

### Phase 5.5 — Docker

| Bước | Kết quả |
|---|---|
| `docker build -t day26-weather-mcp:local .` | ✅ thành công (429 MB) |
| Kiểm tra secret trong image | ✅ `WEATHERAPI_KEY = None`; `/app` chỉ có `.venv`, `pyproject.toml`, `uv.lock`, `weather.py`; grep key material → không thấy |
| `docker run -d -p <free>:8080` | ✅ `Up (healthy)` — HEALTHCHECK TCP hoạt động |
| MCP `initialize` + `tools/list` + `health_check` từ host | ✅ `initialize OK: weather`; tools = 3; `{"status": "ok", ...}` |
| Chạy non-root | ✅ `USER appuser` (UID 10001) |
| **Không truyền key** | ✅ server vẫn chạy; `health_check` ok; `get_current_weather` trả lỗi cấu hình; `days=-2` bị chặn |
| **Truyền key THẬT qua `-e`** | ✅ `get_current_weather('Hanoi')` → **`29.9°C, Cloudy, độ ẩm 59%, gió 17.6 km/h SSE`** — dữ liệu THẬT qua container |

> ⚠️ **Bug thật chỉ lộ ra ở bước này.** Sau khi thêm tính năng nạp `.env`, việc
> rebuild + chạy lại container phát hiện `IndexError: 2` làm container chết ngay
> khi khởi động: `weather.py` trong container nằm ở `/app/weather.py` nên
> `Path(...).parents[2]` không tồn tại. Chạy local **không** lộ bug vì đường dẫn
> trong repo đủ sâu. Đã sửa (`_env_candidates()` + 2 regression test) và image
> được rebuild, chạy lại thành công. Chi tiết: `implementation-summary.md` C2b #26.

### Phase 6 — End-to-End với **DỮ LIỆU THẬT** ✅

`DAY26_E2E=1` + `WEATHERAPI_KEY` hợp lệ → `mode = real-weatherapi`.
Kết quả: **13 passed, 0 failed, exit 0**.

| # | Câu hỏi | Tool agent gọi | Kết quả tool (THẬT) | Câu trả lời |
|---|---|---|---|---|
| 1 | Thời tiết Hà Nội hôm nay thế nào? | `get_current_weather(city="Hanoi")` | `Hanoi, Vietnam: Nhiệt độ 31.6°C (cảm giác 34.5°C), Cloudy, độ ẩm 54%, gió 15.5 km/h SE` | *"Thời tiết hiện tại tại Hanoi, Vietnam (cập nhật lúc 17:15 ngày 14/10/2026)"* — dùng đúng 31.6°C |
| 2 | Dự báo Đà Nẵng trong 3 ngày tới. | `get_forecast(city="Da Nang", days=3)` | 3 ngày thật: 14/10 (27.3/21.4°C, Fog, mưa 86%), 15/10 (28.9/20.4°C), 16/10 (29.5/19.3°C, Sunny) | *"Dự báo thời tiết 3 ngày tới tại Đà Nẵng, Việt Nam"* |
| 3 | So sánh thời tiết Hà Nội và TP. Hồ Chí Minh. | `get_current_weather` × **2** (`Hanoi`, `Ho Chi Minh`) | **Hanoi 31.6°C** và **Ho Chi Minh City 29.5°C** — hai giá trị KHÁC nhau | *"Dưới đây là so sánh thời tiết hiện tại giữa Hà Nội và TP. Hồ Chí Minh"* |
| 4 | MCP Server hiện có hoạt động không? | `health_check()` | `{"status": "ok", "transport": "streamable-http", ...}` | *"MCP Server hiện đang hoạt động bình thường! 🎉"* |
| 5 | Dự báo thời tiết -2 ngày tới. | *(không gọi tool nào)* | — | *"Tôi chỉ có thể dự báo thời tiết trong 1 đến 3 ngày tới..."* — **không gọi tool sai, không bịa** |

**Chế độ suy giảm** (server dùng key KHÔNG hợp lệ → WeatherAPI từ chối):

```
[E2E degraded] tool results: ["❌ Không lấy được thời tiết hiện tại cho 'Hanoi': WeatherAPI từ chối API key (HTTP 401) — ..."]
[E2E degraded] is_error    : [True]
[E2E degraded] answer      : "Rất tiếc, tôi không thể lấy được thời tiết hiện tại cho Hà Nội do API key không hợp lệ."
```

→ Khi tool lỗi, agent **báo trung thực** và **không đưa ra số °C nào**.

Kèm 3 chốt chống "PASS giả" (đều pass trong lần chạy thật):
```
[E2E] đã thu 5 kết quả tool (không rỗng)
[E2E] kiểm tra dùng dữ liệu tool: 3 câu
[E2E] kiểm tra chống bịa: 0 câu có tool lỗi   ← 0 vì mọi tool đều thành công (đúng ở chế độ thật)
```

---

## 3. Kiểm chứng các lỗi đã sửa (regression)

| Bug | Bằng chứng |
|---|---|
| `days` âm gửi tới WeatherAPI | 60 unit test + khẳng định `mock_weather_api.requests == []` cho `days ∈ {-5,-2,-1,0,4,5,10,100}`; và E2E Q5 |
| `httpx.Timeout` vs `httpx2` | `auth_client.py` chạy thật in ra 4 status code đúng |
| Transport phụ thuộc TTY | `test_transport_ignores_tty_and_behaves_the_same` |
| stdout bị `print()` làm hỏng | `test_stdio_stdout_carries_only_jsonrpc` + `test_stdio_stdout_is_pure_jsonrpc` (parse **từng dòng**) |
| `.env` `GEMINI_API_KEY` vs ADK `GOOGLE_API_KEY` | `test_apply_alias_from_gemini_to_google`; `verify_setup` tầng 1 báo `nguồn: GEMINI_API_KEY` |
| `agent.py` tuyên bố kết nối sai | `test_agent_module_did_not_claim_connection` |
| `verify_setup` coi HTTP < 500 = MCP OK | `test_verify_http_unreachable_is_fail_not_pass`, `test_verify_http_reachable_never_implies_mcp_ok` |
| Registry JSON hỏng/thiếu field | 10 test nhánh lỗi |
| `units` sai âm thầm thành celsius | `test_v2_invalid_units_returns_error_not_crash` |
| Key rò qua thông báo lỗi | `test_current_weather_scrubs_api_key_from_errors`, `test_run_reports_api_error_without_leaking_key` |
| Token rò trong log | `test_tokens_never_appear_in_server_log` |
| Assertion E2E vô nghĩa | `test_e2e_harness.py` (16 test) + `test_tool_result_capture_is_not_vacuous` |
| Rò rỉ env giữa các test | `isolate_api_keys` — đo được `[E2E] GOOGLE_API_KEY: set (len=53)` thay vì key giả |
| Agent hỏi lại thay vì gọi tool 2 thành phố | `test_agent_instruction_handles_multi_city_questions` + E2E Q3 gọi tool **2 lần** |
| `.env` bị tài liệu hoá nhưng server không đọc | `test_dotenv_next_to_server_is_loaded_when_present` + log `[weather-mcp] .env đã nạp: ...` |
| Chế độ degraded mất tác dụng sau khi thêm `.env` | E2E degraded dùng key sai → `is_error: [True]`, agent báo trung thực |

---

## 4. Trạng thái xác minh từng hạng mục

| Hạng mục | Trạng thái | Bằng chứng |
|---|---|---|
| Function Calling (mock, offline) | ✅ **VERIFIED** | 29 unit test, chạy thật |
| MCP Basics stdio | ✅ **VERIFIED** | 12 test với server thật |
| MCP Streamable HTTP | ✅ **VERIFIED** | Lab transports test + Docker container |
| Authentication 401 | ✅ **VERIFIED** | Đo thật trên HTTP |
| Authorization 403 | ✅ **VERIFIED** | Token thiếu scope → 403 `insufficient_scope` |
| Tool Registry | ✅ **VERIFIED** | 29 test + chạy thật |
| Versioning v1/v2 | ✅ **VERIFIED** | 18 test với server thật |
| **WeatherAPI dữ liệu THẬT** | ✅ **VERIFIED** | Hà Nội **31.6°C**, Đà Nẵng **3 ngày thật**; `verify_setup` tầng 8 PASS |
| **E2E toàn chuỗi (dữ liệu thật)** | ✅ **VERIFIED** | 13/13 test, `mode = real-weatherapi` |
| **Gemini API** | ✅ **VERIFIED** | `verify_setup` tầng 9 PASS; E2E 5/5 câu có câu trả lời |
| Docker build + run | ✅ **VERIFIED** | Image 429 MB, container healthy, MCP handshake OK |
| Cloud Run deploy | ➖ **NOT ATTEMPTED** | Không deploy để tránh phát sinh chi phí |
| `adk web` UI | ➖ **NOT AUTOMATED** | E2E dùng `InMemoryRunner` cùng `root_agent`; `verify_setup` xác minh import + kết nối |

---

## 5. Ghi chú về độ ổn định của môi trường

Key Gemini dùng trong bài **bị giới hạn IP** và IP egress của máy **quay vòng**,
nên tỉ lệ request thành công thay đổi theo thời điểm. Điều này ảnh hưởng đến
**độ ổn định của lần chạy**, không phải tính đúng đắn của code:

| Thời điểm | Kết quả E2E |
|---|---|
| Lúc có key WeatherAPI (và egress IP được phép) | ✅ **55 passed / 0 FAIL**, `mode=real-weatherapi`, dữ liệu THẬT |
| Sau đó (egress IP bị chặn hoàn toàn) | ✅ **47 passed + 9 skipped / 0 FAIL** — mọi câu in rõ *"Đây KHÔNG phải PASS"* |
| Đã từng có lần cả 5 câu FAIL với `API_KEY_INVALID` | Đó là **bug thật trong test** (rò rỉ env), đã sửa; xem `implementation-summary.md` C2 #18 |

Điểm quan trọng: **số FAIL luôn là 0**. Khi môi trường chặn, test chuyển thành
SKIP chứ không báo FAIL giả và cũng không báo PASS giả.

Harness phân biệt **3 kết quả**, không phải 2:

| Kết quả | Ý nghĩa |
|---|---|
| PASS | Có bằng chứng agent chạy đúng |
| SKIP | Lỗi **tạm thời** của môi trường → **CHƯA xác minh được**, không phải PASS |
| FAIL | Lỗi **logic** của agent (không gọi tool, bịa dữ liệu, sai tham số) |

## 6. Ba cơ chế chống "PASS giả"

1. **Chốt chống assertion vô nghĩa** — `test_tool_result_capture_is_not_vacuous`
   fail nếu harness không thu được nội dung tool (đúng bug đã gặp).
2. **Phân biệt 3 kết quả** (bảng trên) — SKIP nói rõ *"Đây KHÔNG phải PASS"*.
3. **Chốt chống "0 câu kiểm tra"** — `test_agent_uses_tool_data_when_tool_succeeded`
   yêu cầu `checked > 0` ở chế độ mock.

Ngoài ra `verify_setup.py` là bằng chứng **độc lập với bộ test**: nó báo
NOT VERIFIED cho tầng chưa kiểm tra được thay vì PASS, và ghi rõ tầng 4
(HTTP reachable) **không** chứng minh MCP hoạt động.
