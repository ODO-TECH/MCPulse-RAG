#!/bin/bash
set -e

echo "=== Knowledge MCP service starting ==="

echo "[0/3] Checking MCP Python SDK..."
python -c "from mcp.server.fastmcp import FastMCP; print('FastMCP import OK')"

echo "[1/3] Starting initial indexing in background..."
python /app/indexer.py &

echo "[2/3] Starting file watcher..."
python /app/watcher.py &

echo "[3/3] Starting MCP service (port ${MCP_PORT:-6646})..."
exec python /app/mcp_server.py
