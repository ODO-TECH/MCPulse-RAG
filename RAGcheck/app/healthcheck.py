import os
import time
import logging
import requests
from datetime import datetime
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

MCP_URL = os.getenv("MCP_CHECK_URL", "http://192.168.1.100:6646")
QDRANT_URL = os.getenv("QDRANT_URL", "http://192.168.1.100:6333")


def check_mcp_sse() -> Dict[str, Any]:
    """检查 MCP SSE 端点是否可达"""
    url = f"{MCP_URL}/sse"
    try:
        resp = requests.get(url, timeout=10, stream=True)
        ok = resp.status_code == 200
        resp.close()
        return {"name": "MCP SSE 端点", "ok": ok, "detail": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"name": "MCP SSE 端点", "ok": False, "detail": str(e)}


def check_qdrant() -> Dict[str, Any]:
    """检查 Qdrant 是否可达"""
    try:
        resp = requests.get(f"{QDRANT_URL}/collections", timeout=10)
        ok = resp.status_code == 200
        data = resp.json() if ok else {}
        collections = [c["name"] for c in data.get("result", {}).get("collections", [])]
        return {
            "name": "Qdrant 数据库",
            "ok": ok,
            "detail": f"HTTP {resp.status_code}, collections: {', '.join(collections) if collections else '无'}",
        }
    except Exception as e:
        return {"name": "Qdrant 数据库", "ok": False, "detail": str(e)}


def check_qdrant_collections() -> List[Dict[str, Any]]:
    """检查各 collection 的向量数量"""
    results = []
    try:
        resp = requests.get(f"{QDRANT_URL}/collections", timeout=10)
        if resp.status_code != 200:
            return results
        collections = resp.json().get("result", {}).get("collections", [])
        for col in collections:
            name = col["name"]
            try:
                detail_resp = requests.get(f"{QDRANT_URL}/collections/{name}", timeout=10)
                if detail_resp.status_code == 200:
                    info = detail_resp.json().get("result", {})
                    points = info.get("points_count", 0)
                    vectors = info.get("indexed_vectors_count", 0)
                    size = info.get("config", {}).get("params", {}).get("vectors", {}).get("size", 0)
                    results.append({
                        "name": f"Collection: {name}",
                        "ok": True,
                        "detail": f"文档块数: {points}, 向量维度: {size}",
                    })
                else:
                    results.append({"name": f"Collection: {name}", "ok": False, "detail": f"HTTP {detail_resp.status_code}"})
            except Exception as e:
                results.append({"name": f"Collection: {name}", "ok": False, "detail": str(e)})
    except Exception:
        pass
    return results


def check_mcp_tools() -> Dict[str, Any]:
    """检查 MCP 服务是否可达"""
    try:
        resp = requests.get(f"{MCP_URL}/sse", timeout=10, stream=True)
        ok = resp.status_code == 200
        resp.close()
        return {"name": "MCP 服务状态", "ok": ok, "detail": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"name": "MCP 服务状态", "ok": False, "detail": str(e)}


def run_all_checks() -> Dict[str, Any]:
    """执行全部检查，返回报告数据"""
    now = datetime.now()
    results = []

    results.append(check_mcp_sse())
    results.append(check_qdrant())
    results.extend(check_qdrant_collections())
    results.append(check_mcp_tools())

    all_ok = all(r["ok"] for r in results)
    passed = sum(1 for r in results if r["ok"])
    total = len(results)

    return {
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "overall": "正常" if all_ok else "异常",
        "all_ok": all_ok,
        "passed": passed,
        "total": total,
        "checks": results,
    }
