FROM python:3.12-slim

WORKDIR /app

# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 复制依赖文件
COPY pyproject.toml uv.lock ./

# 安装依赖
RUN uv sync --frozen --no-dev

# 复制源码
COPY src/ ./src/

# 创建数据目录
RUN mkdir -p /data

# 暴露端口
EXPOSE 8100 8101

# 启动
CMD ["uv", "run", "python", "-m", "kb_mcp_server"]
