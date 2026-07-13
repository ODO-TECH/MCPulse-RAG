#!/bin/bash
set -e

echo "=== 知识库 MCP 服务启动 ==="

echo "[1/3] 首次全量索引..."
python /app/indexer.py --force || echo "首次索引部分失败，继续启动"

echo "[2/3] 启动文件监控..."
python /app/watcher.py &

echo "[3/3] 启动 MCP 服务 (port ${MCP_PORT:-6646})..."
exec python /app/mcp_server.py
