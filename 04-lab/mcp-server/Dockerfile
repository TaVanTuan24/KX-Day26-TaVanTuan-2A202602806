# syntax=docker/dockerfile:1
#
# Weather MCP Server — image cho Cloud Run / Docker.
#
# Build (từ thư mục 04-lab/mcp-server):
#     docker build -t weather-mcp:local .
#
# Chạy local:
#     docker run --rm -p 8085:8080 -e WEATHERAPI_KEY="key-của-bạn" weather-mcp:local
#     # rồi gọi http://localhost:8085/mcp
#
# ⚠️ KHÔNG có API key nào nằm trong image. Key phải được truyền lúc chạy
#    (`-e` / `--env-file`) hoặc qua Secret Manager trên Cloud Run:
#        gcloud run deploy weather-mcp \
#          --image <IMAGE> --set-secrets WEATHERAPI_KEY=weatherapi-key:latest
#
# Base image của uv đã gồm sẵn Python 3.12 + uv → build tất định theo uv.lock,
# không cần cài setuptools và không cần build backend cho chính project này.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Chạy bằng user không phải root.
RUN useradd --create-home --uid 10001 appuser

WORKDIR /app

# Cài dependency TRƯỚC khi copy code → tận dụng cache layer khi code đổi.
# `--no-install-project`: weather.py chạy trực tiếp, không cần cài như package.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Chỉ copy code cần thiết cho runtime.
COPY weather.py ./

# Cloud Run tự set PORT (thường 8080). HOST=0.0.0.0 để nhận traffic từ ngoài container.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8080

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

# Liveness của CONTAINER: chỉ kiểm tra cổng đã mở (TCP connect).
# LƯU Ý: đây KHÔNG phải kiểm tra MCP hoạt động. Muốn xác minh MCP thật (bắt tay +
# list_tools + call_tool), dùng `04-lab/mcp-client/verify_setup.py` (tầng 5–7).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os,socket,sys; s=socket.create_connection(('127.0.0.1',int(os.environ.get('PORT','8080'))),3); s.close()"]

CMD [".venv/bin/python", "weather.py"]
