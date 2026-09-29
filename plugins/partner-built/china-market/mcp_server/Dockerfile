FROM python:3.11-slim
WORKDIR /app

# 依赖单独一层, 便于缓存。
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 数据层 + server (单一源, 与 stdio 插件共用同一份代码)。
COPY server.py sources.py cache.py config.yaml __init__.py ./

# 容器里以 SSE 跑, 扁平 /app 布局: 用 env 指定 config / cache 路径,
# 覆盖 server.py 默认的 PLUGIN_ROOT/mcp_server 相对定位。
ENV MCP_TRANSPORT=sse \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8080 \
    CHINA_MARKET_CONFIG=/app/config.yaml \
    CHINA_MARKET_CACHE_DIR=/app/data_cache/market

EXPOSE 8080
CMD ["python", "server.py"]
