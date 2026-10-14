# Implementation Summary — Day 26

**Repo:** `KX-Day26-TaVanTuan-2A202602806`
**Ngày thực hiện:** 2026-10-14
**Môi trường:** Windows 11 · PowerShell 5.1 · Python 3.12.13 · Docker 29.8.2
**Môi trường Python tách biệt:**

| Nhóm | Venv | Phiên bản chính |
|---|---|---|
| Module 01–03 | `.venv` (repo root) | `mcp` 2.3.0, `google-genai` 2.30.1 |
| Lab 04 server | `04-lab/mcp-server/.venv` (`uv`) | `mcp` 1.28.1, `fastmcp` 3.4.2, `httpx` 0.28.1 |
| Lab 04 client | `04-lab/mcp-client/.venv` (`uv`) | `google-adk` 2.3.0, `mcp` 1.28.1, `google-genai` 2.10.0 |

> Hai môi trường **không** trộn dependency. `requirements.txt` và cả hai `uv.lock`
> **không bị sửa** trong quá trình làm bài (không nâng cấp dependency nào).

---

## A. Việc đã làm

### A.1. File TẠO MỚI

| File | Mục đích |
|---|---|
| `pytest.ini` | Cấu hình test suite gốc |
| `requirements-dev.txt` | `pytest` (dev-only, tách khỏi runtime) |
| `.env.example` | Mẫu cấu hình cho module 01–03 |
| `tests/__init__.py`, `tests/conftest.py` | Hạ tầng test + helper dùng chung |
| `tests/test_01_function_calling.py` | 29 unit test cho module 01 |
| `tests/test_02_mcp_stdio.py` | 12 integration test MCP stdio thật |
| `tests/test_03_auth_http.py` | 8 integration test HTTP auth (server thật) |
| `tests/test_03_registry.py` | 29 unit test cho Tool Registry |
| `tests/test_03_versioning.py` | 18 integration test versioning (stdio thật) |
| `04-lab/mcp-server/.dockerignore` | Loại `.venv` và `.env` khỏi build context |
| `04-lab/mcp-server/.env.example` | Mẫu cấu hình server |
| `04-lab/mcp-server/tests/{conftest,test_weather_tools,test_mcp_transports}.py` | 139 test (unit + mock WeatherAPI + MCP stdio + MCP HTTP + nested JSON + `.env`) |
| `04-lab/mcp-client/.env.example` | Mẫu cấu hình client |
| `04-lab/mcp-client/env_setup.py` | **Nguồn cấu hình `.env` duy nhất** cho client |
| `04-lab/mcp-client/tests/{conftest,test_agent_config,test_e2e_harness,test_e2e_agent,e2e_runner}.py` | Unit + E2E harness + 5 câu hỏi E2E |
| `reports/implementation-summary.md` | File này |
| `reports/test-results.md` | Báo cáo kiểm thử trung thực |

### A.2. File SỬA

| File | Lý do sửa (ngắn) |
|---|---|
| `README.md` | Viết lại toàn bộ: kiến trúc, setup Windows/Linux, API key, lệnh chạy, test, troubleshooting, security, limitations, kết quả xác minh |
| `01-function-calling/weather_function_calling.py` | Thêm xử lý lỗi, giới hạn vòng lặp, dispatch table, chế độ offline, che secret |
| `01-function-calling/README.md` | Phản ánh code mới + cách chạy + test |
| `02-mcp-basics/weather_server.py` | `ToolError` cho lỗi nghiệp vụ, tra cứu không phân biệt hoa/thường, `log_level`, ghi rõ quy tắc stdout |
| `02-mcp-basics/weather_client.py` | UTF-8, đường dẫn theo `__file__`, bắt tay MCP, in schema tự sinh, xử lý 4 loại tool error |
| `02-mcp-basics/README.md` | Thêm mục stdout/giao thức stdio + `ToolError` |
| `03-production/auth_server.py` | `HOST`/`PORT` cấu hình được, `required_scopes` (authorization), token thiếu scope để demo 403, che token trong log, `validate_token_resource=False` tường minh |
| `03-production/auth_client.py` | UTF-8, URL/token từ env, đo status code THẬT 401/403/200, sửa lỗi `httpx.Timeout` vs `httpx2` |
| `03-production/registry_client.py` | `RegistryError`, validate cấu trúc JSON, chịu được entry hỏng, semantic version an toàn, timeout, không gọi endpoint minh hoạ |
| `03-production/versioned_server.py` | Validate `units`, tra cứu không phân biệt hoa/thường, công bố `version`/`tools` trong metadata |
| `03-production/versioned_client.py` | UTF-8, đường dẫn theo `__file__`, test default của tham số optional, test `units` sai |
| `03-production/README.md` | **Sửa tài liệu sai về 401/403** + bảng xử lý lỗi registry + validate `units` |
| `04-lab/README.md` | Viết lại: kiến trúc, setup, bảng biến môi trường, 9 tầng verify, test, Docker, troubleshooting |
| `04-lab/mcp-client/README.md` | Viết lại: fallback mode, `.env` ở đâu, 3 kết quả test, troubleshooting |
| `04-lab/mcp-client/weather_agent/agent.py` | **Bỏ tuyên bố "kết nối thành công" sai sự thật**; system instruction nghiêm ngặt; timeout 30s; fallback cảnh báo rõ; nạp `.env` qua `env_setup` |
| `04-lab/mcp-client/verify_setup.py` | Viết lại thành 9 tầng xác minh độc lập (PASS/FAIL/WARN/NOT VERIFIED) |
| `04-lab/mcp-server/weather.py` | Validate `days` 1–3, parsing phòng thủ, ánh xạ lỗi WeatherAPI, timeout, che key, transport không phụ thuộc TTY, log ra stderr, **nạp `.env`** |
| `04-lab/mcp-server/Dockerfile` | Base image `uv`, `uv sync --frozen`, non-root, HEALTHCHECK TCP, không có secret |

### A.3. File **KHÔNG** sửa (đã kiểm tra và thấy đúng)

`requirements.txt`, cả hai `uv.lock`, cả hai `pyproject.toml`,
`03-production/registry.json`, `04-lab/mcp-client/weather_agent/__init__.py`.

---

## B. Tính năng đã hoàn thành

### Module 01 — Function Calling
- Schema `get_weather` chính xác; dispatch qua bảng `TOOL_FUNCTIONS`.
- Hỗ trợ **nhiều function call trong một lượt** (1 vòng gửi lại chứa cả 2 kết quả).
- Giới hạn `MAX_TOOL_ROUNDS = 5` → `MaxToolRoundsExceeded`, chặn vòng lặp vô hạn.
- Xử lý: tên function lạ, thiếu/thừa/sai kiểu tham số, function ném exception, lỗi Gemini API, response rỗng.
- Che API key khỏi mọi thông báo lỗi.
- Chế độ offline có nhãn rõ (`[OFFLINE]`, `MOCK`) — không giả vờ là kết quả model.

### Module 02 — MCP Basics
- Server + client thật qua stdio; bắt tay `initialize`, `list_tools`, `call_tool`.
- Schema sinh tự động từ type hints (`{"city": {"type": "string"}}, required ["city"]`).
- Client xử lý 4 nhóm lỗi: thiếu tham số, sai kiểu, tool không tồn tại, lỗi nghiệp vụ.
- Test khẳng định **stdout chỉ chứa JSON-RPC** (không bị `print()` làm hỏng).

### Module 03 — Production
- **Authentication**: bearer token qua Streamable HTTP; 401 khi thiếu/sai token.
- **Authorization (mới)**: `required_scopes=["weather:read"]` + token thiếu scope → **403 insufficient_scope**. Phân biệt rõ auth vs authz bằng số liệu đo được.
- **Tool Registry**: tìm theo tag/keyword/tên/tags; chọn best match theo semantic version + ưu tiên không deprecated; 10 nhánh lỗi được xử lý và test.
- **Versioning**: v1 giữ nguyên hợp đồng cũ, v2 thêm `include_forecast`/`units` với default hợp lệ; `units` được validate; `server://info` công bố metadata.

### Lab 04 — ADK + MCP + WeatherAPI
- MCP server 3 tool qua Streamable HTTP tại `/mcp`, cấu hình bằng env.
- `get_forecast` chỉ nhận `days` 1–3; giá trị âm/0/>3 bị **từ chối và KHÔNG gửi tới WeatherAPI**.
- Timeout, lỗi mạng, lỗi HTTP (401/400/429/5xx), JSON hỏng, payload thiếu trường — đều được xử lý và test.
- ADK agent: MCP URL từ env, timeout 30s, system instruction tiếng Việt cấm bịa dữ liệu, fallback cảnh báo rõ.
- `verify_setup.py`: 9 tầng độc lập, **không** suy ra "MCP OK" từ HTTP `< 500`.
- Docker: build thành công, chạy container và bắt tay MCP thật, **không có secret trong image**.

---

## C. Bug tìm được và cách sửa (đã xác minh bằng thực nghiệm)

### C1. Lỗi làm hỏng chức năng

| # | Bug | Nguyên nhân gốc | Cách sửa |
|---|---|---|---|
| 1 | `UnicodeEncodeError: 'charmap' codec` khi in tiếng Việt | Console Windows dùng cp1252 khi stdout/stderr bị pipe; code không ép encoding | `sys.stdout/stderr.reconfigure(encoding="utf-8")` ở mọi script (module 02, 03, lab) |
| 2 | `from google import genai, types` → `ImportError` | `types` không phải attribute của package `google` | `from google.genai import types` (đã kiểm chứng) |
| 3 | `get_forecast(city, days=-2)` **gửi số âm tới WeatherAPI** | `days = min(days, 3)` không chặn giá trị âm | Validate `1 ≤ days ≤ 3`; từ chối kèm thông báo, **không** gọi upstream (test khẳng định 0 request) |
| 4 | `TypeError: unsupported operand type(s) for +: 'float' and 'Timeout'` | MCP SDK v2 dùng **httpx2**, code truyền `httpx.Timeout` | Truyền số giây (float); ghi chú rõ trong code |
| 5 | `auth_server.py` không khởi động được: `[Errno 10048]` | Cổng 8000 bị **Docker Desktop** chiếm trên máy test | `HOST`/`PORT` cấu hình được; test dùng cổng động; tài liệu hoá |
| 6 | Lab server tự chuyển sang stdio khi chạy trong terminal | `sys.stdin.isatty()` quyết định transport | Mặc định luôn `streamable-http`; stdio chỉ khi `MCP_TRANSPORT=stdio` |
| 7 | Lab server `print()` ra stdout lúc import | Sẽ phá giao thức khi transport là stdio | Chuyển sang stderr; thêm test raw JSON-RPC khẳng định stdout sạch |
| 8 | `KeyError` khi WeatherAPI trả payload thiếu trường | Truy cập trực tiếp `data["current"]`, `current["temp_c"]` | Trích xuất phòng thủ + placeholder `"không rõ"` |
| 9 | ADK báo `GOOGLE_API_KEY: THIẾU` dù `.env` đã có key | `.env` dùng `GEMINI_API_KEY`, ADK chỉ đọc `GOOGLE_API_KEY` | `env_setup.py` đồng bộ alias, dùng chung cho agent và verify_setup |
| 10 | `agent.py` tuyên bố `"Remote MCP connection successful!"` | Chỉ vì **tạo được** `McpToolset` — nó không hề kết nối | Xoá tuyên bố sai; log rõ "kết nối LAZY"; thêm `verify_setup.py` kiểm tra thật |
| 11 | Agent có thể bịa số liệu thời tiết | `Agent(...)` không có `instruction` | Thêm system instruction tiếng Việt: chỉ dùng dữ liệu tool, cấm bịa, báo lỗi trung thực |
| 12 | `verify_setup.py` coi `HTTP status < 500` là "MCP OK" | Suy diễn sai từ tầng transport | Viết lại thành 9 tầng độc lập, không suy diễn |
| 13 | `Dockerfile`: `pip install -e .` không có build backend | `pyproject.toml` không khai báo `[build-system]` | Dùng base image `uv` + `uv sync --frozen --no-install-project` |
| 14 | `registry_client.py` sập khi registry JSON hỏng/thiếu field | Truy cập trực tiếp `data["tools"]`, `tool_cfg["version"]` | `RegistryError` + validate cấu trúc + giá trị mặc định an toàn |
| 15 | `versioned_server.get_weather_v2(units="kelvin")` âm thầm coi là celsius | Không validate `units` | Validate, trả payload lỗi JSON có `supported_units` |
| 16 | Thông báo lỗi có thể chứa API key | In nguyên văn lỗi từ SDK/upstream | `_scrub()` / `_scrub_secrets()` che key; test khẳng định |

### C1b. Bug phát hiện ở giai đoạn xác minh cuối (khi có WeatherAPI key thật)

| # | Bug | Nguyên nhân gốc | Cách sửa |
|---|---|---|---|
| 23 | `04-lab/mcp-server/.env.example` hướng dẫn dùng `.env` nhưng **server không hề đọc `.env`** — tài liệu cho một tính năng chưa tồn tại | `weather.py` chỉ đọc `os.getenv`; không có `load_dotenv` | Thêm `_load_dotenv_files()` (import mềm, không đổi `uv.lock` vì `python-dotenv` đã có sẵn như dependency bắc cầu). Nếu có `.env` mà thiếu package thì **cảnh báo ra stderr**, không im lặng bỏ qua. Log khởi động in rõ file `.env` nào đã nạp |
| 24 | Test "degraded" của E2E mất tác dụng: nó xoá `WEATHERAPI_KEY` khỏi env để ép tool lỗi, nhưng sau khi server tự nạp `.env` thì key thật lọt vào → tool **thành công** → 2 test FAIL | Phụ thuộc vào việc "không có key" trong khi `.env` có thể cấp key | Ép suy giảm bằng **key KHÔNG hợp lệ** qua env (env thắng `.env` vì `override=False`) → WeatherAPI trả 401 → tool lỗi chắc chắn, deterministic |
| 25 | `test_stdio_lists_tools_and_calls_health_check` assert `weatherapi_key_configured is False` | Cùng nguyên nhân #24 | Bỏ assertion phụ thuộc môi trường đó (hành vi "không key → False" đã được kiểm chứng riêng ở `test_weather_check_without_key`); thêm test mới cho tính năng `.env` |

### C2. Lỗi trong chính bộ test (quan trọng — nếu bỏ qua sẽ "PASS giả")

| # | Bug | Nguyên nhân gốc | Cách sửa |
|---|---|---|---|
| 17 | Assertion "agent không bịa dữ liệu" **vô nghĩa nhưng vẫn PASS** | Harness trích xuất kết quả tool ra chuỗi rỗng → `startswith("❌")` luôn False | Trích xuất đúng mọi dạng payload (`{'result': str}`, `{'result': CallToolResult}`, list Content) + cờ `is_error`; thêm `test_e2e_harness.py` chứng minh và một test chốt "kết quả thu được không được rỗng" |
| 18 | E2E fail toàn bộ 5/5 với `API_KEY_INVALID` | `apply_key_alias()` ghi vào **cả hai** biến env, nhưng `monkeypatch` chỉ hoàn tác biến nó tự set → `GEMINI_API_KEY="key-from-gemini"` rò rỉ vĩnh viễn sang test E2E | Fixture `isolate_api_keys` save/restore tường minh cả hai biến (không dựa vào monkeypatch) |
| 19 | Harness E2E crash `Unexpected UTF-8 BOM` | PowerShell ghi JSON kèm BOM | Đọc bằng `encoding="utf-8-sig"` |
| 20 | E2E Q2 fail dù agent đúng | Retry quá ít; key Gemini bị giới hạn IP, IP egress quay vòng (~1/3 request lỗi) | Retry 12 lần với nghỉ ngắn; phân loại lỗi tạm thời thành **SKIP = "chưa xác minh"**, không phải FAIL và tuyệt đối không phải PASS |
| 21 | E2E "dùng dữ liệu tool" fail ngẫu nhiên | Assertion đòi literal `"°C"`, nhưng model lúc viết `"29°C"`, lúc viết `"29 độ C"` | So khớp **giá trị nhiệt độ** lấy từ kết quả tool với mọi con số trong câu trả lời |
| 22 | E2E Q3: agent hỏi lại thay vì gọi tool cho 2 thành phố | Instruction không nói gì về câu hỏi nhiều thành phố | Thêm quy tắc 6: gọi tool cho TỪNG thành phố đã nêu tên, không hỏi lại |

### C2b. Bug phát hiện ở vòng xác minh CUỐI (sau khi có WeatherAPI key thật)

| # | Bug | Nguyên nhân gốc | Cách sửa |
|---|---|---|---|
| 23 | `04-lab/mcp-server/.env.example` hướng dẫn dùng `.env` nhưng **server không hề đọc `.env`** — tài liệu cho tính năng chưa tồn tại | `weather.py` chỉ đọc `os.getenv` | Thêm `_load_dotenv_files()` (import mềm, không đổi `uv.lock` vì `python-dotenv` đã có sẵn như dependency bắc cầu). Có `.env` mà thiếu package thì **cảnh báo ra stderr**, không im lặng bỏ qua |
| 24 | Test "degraded" của E2E mất tác dụng: nó xoá `WEATHERAPI_KEY` khỏi env để ép tool lỗi, nhưng sau khi server tự nạp `.env` thì key thật lọt vào → tool **thành công** → 2 test FAIL | Phụ thuộc vào "không có key" trong khi `.env` có thể cấp key | Ép suy giảm bằng **key KHÔNG hợp lệ** qua env (env thắng `.env` vì `override=False`) → WeatherAPI trả 401 → tool lỗi chắc chắn |
| 25 | `test_stdio_lists_tools_and_calls_health_check` assert `weatherapi_key_configured is False` | Cùng nguyên nhân #24 | Bỏ assertion phụ thuộc môi trường đó (hành vi "không key → False" đã kiểm chứng riêng ở `test_health_check_without_key`); thêm test cho tính năng `.env` |
| 26 | **Docker container chết ngay khi khởi động**: `IndexError: 2` | `_load_dotenv_files()` dùng `Path(__file__).resolve().parents[2]` để tìm `.env` ở repo root. Trong container file nằm ở `/app/weather.py` → `parents` chỉ có 2 phần tử → `IndexError`. **Không lộ ra khi chạy local** vì đường dẫn trong repo đủ sâu | Tách `_env_candidates()` có kiểm tra `len(parents) > 2`; thêm 2 regression test (đường dẫn nông kiểu container + đường dẫn sâu). **Chỉ phát hiện được nhờ rebuild và chạy lại image** |
| 27 | Cùng lớp bug tiềm ẩn ở client: `env_setup.REPO_ROOT = CLIENT_DIR.parents[1]`, `agent.py` dùng `parents[3]` | Đếm cấp thư mục cố định — vỡ nếu layout đổi | Thay bằng `find_repo_root()` tìm gốc repo theo **dấu hiệu** (`requirements.txt`/`.git`), chịu được mọi độ sâu; `agent.py` dùng lại `env_setup.REPO_ROOT` |
| 28 | Chốt chống "PASS giả" `test_tool_result_capture_is_not_vacuous` FAIL khi cả 5 câu E2E đều lỗi tạm thời | Guard yêu cầu `observed > 0` kể cả khi không câu nào chạy được | Rỗng trên câu **đã hoàn tất** → FAIL; rỗng vì **mọi câu lỗi tạm thời** → SKIP ("KHÔNG phải PASS") |
| 29 | Test mới của tôi không portable: assert `Path("/app/.env") == candidates[0]` | Trên Windows `Path.resolve()` gắn thêm ổ đĩa của thư mục hiện hành | So sánh `.name` và **số lượng** ứng viên thay vì đường dẫn tuyệt đối |

### C2c. Bug phát hiện ở vòng hoàn thiện cuối cùng

| # | Bug | Nguyên nhân gốc | Cách sửa |
|---|---|---|---|
| 30 | `_format_current()` **crash** khi `current.condition` là chuỗi (không phải object lồng) | `_val(current.get("condition") or {}, "text")` → `_val("Cloudy", "text")` gọi `.get` trên `str` → `AttributeError` | `_val()` nay từ chối mọi `mapping` không phải dict; thêm `_condition()` chấp nhận cả object lồng **và** chuỗi |
| 31 | `_format_current()` / `_format_forecast()` **crash** khi `location.name/region/country` không phải chuỗi | `", ".join((name, region, country))` → `TypeError` nếu là số/list/dict | Thêm `_place()` + `_str_or_empty()` chuẩn hoá an toàn, fallback `"?"` |
| 32 | `_format_forecast()` **báo thành công với dự báo RỖNG** | `forecastday` chỉ được kiểm tra "truthy"; nếu là dict/chuỗi thì vòng lặp chạy qua key/ký tự, mọi entry bị `continue` → trả về **chỉ mỗi dòng tiêu đề** | Bắt buộc `forecastday` là `list` không rỗng; thêm `_day_is_readable()` (phải có ít nhất 1 field số liệu thật); không có block nào → **báo lỗi**, không báo thành công |
| 33 | `_format_current()` trả về trang "toàn không rõ" cho payload vô dụng | Chỉ kiểm tra `current` là dict không rỗng | Yêu cầu có ít nhất một field trong `_CURRENT_FIELDS` đọc được; nếu không → báo lỗi |
| 34 | `health_check()` **nói sai transport** | `"transport": "streamable-http"` hard-code dù server có thể chạy stdio/sse; `endpoint` luôn là URL HTTP | Thêm `ACTIVE_TRANSPORT` + `set_active_transport()` (gọi trong `__main__`) + `current_transport()`; `endpoint` là `null` khi không phải HTTP |
| 35 | Tiếng ồn socket trong test harness | `MockWeatherAPI` chỉ bắt `BrokenPipeError`/`ConnectionResetError`; Windows ném `ConnectionAbortedError [WinError 10053]` | Bắt `OSError` (lớp cha của cả ba) |

**Cải tiến quy trình (yêu cầu item 6):** thêm `.github/workflows/ci.yml` — 3 job chạy
**offline hoàn toàn** (không cần `GOOGLE_API_KEY`/`WEATHERAPI_KEY`, không tiêu quota):
`modules-01-03` (pip + compileall + pytest 96 test), `lab-mcp-server` (uv + pytest 139
test), `lab-mcp-client` (uv + pytest 43 pass/13 skip + khởi động MCP server không key +
`verify_setup.py --no-network`). Test E2E gọi Gemini thật **không** chạy trong CI.
Đã xác minh thật trên GitHub: run [#1](https://github.com/TaVanTuan24/KX-Day26-TaVanTuan-2A202602806/actions/runs/38622142312)
(commit `5f3763f`) — `conclusion=success`, **3/3 job PASS**.

**Dọn dẹp (yêu cầu item 5):** xoá `04-lab/mcp-server/.DS_Store` khỏi Git và đĩa
(`.gitignore` đã có `**/.DS_Store` để không tái phát).

### C3. Tài liệu sai đã được sửa

| Tài liệu | Nội dung sai | Thực tế đo được |
|---|---|---|
| `03-production/README.md` | "Token sai → 403" | Token sai → **401** `invalid_token`; **403** chỉ khi token hợp lệ nhưng **thiếu scope** (`insufficient_scope`) |
| `README.md` | Ghi chung chung, thiếu setup/test/troubleshooting | Đã viết lại đầy đủ và phản ánh đúng code |
| `04-lab/mcp-client/README.md` | "Fallback Mode: agent chạy không tool" không nói rõ hệ quả | Ghi rõ fallback **phải** thông báo không có dữ liệu, cấm bịa |
| `04-lab/README.md` | Không có mục verify 9 tầng, Docker, troubleshooting | Đã bổ sung |

---

## D. Quyết định kỹ thuật có chủ ý

1. **Không** đổi dependency nào → `requirements.txt`, `uv.lock` giữ nguyên.
2. Lab 04 giữ `mcp` 1.x (`mcp.server.fastmcp.FastMCP`) theo `uv.lock`, **không**
   migrate sang mcp 2.x — ADK 2.3.0 yêu cầu mcp 1.x.
3. Test của Lab chạy bằng `uv run --with pytest` → có pytest nhưng **không sửa
   `uv.lock`**.
4. Không dùng `pytest-asyncio`: test async gói trong `asyncio.run()` để tránh
   xung đột event loop với anyio của MCP SDK.
5. `get_forecast` **từ chối** `days` ngoài 1–3 thay vì tự cắt về 3 — cắt ngầm sẽ
   trả kết quả khác với yêu cầu người dùng mà không nói gì.
6. `auth_server.py` bind `127.0.0.1` mặc định (an toàn hơn), Lab server bind
   `0.0.0.0` (bắt buộc cho Docker/Cloud Run).
7. E2E mặc định **TẮT** (`DAY26_E2E=0`) để không tiêu quota Gemini ngoài ý muốn.

---

Xem kết quả kiểm thử thực tế (kèm mọi phần CHƯA xác minh) tại
[`test-results.md`](test-results.md).
