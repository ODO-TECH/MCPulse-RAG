import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List

import requests

logger = logging.getLogger(__name__)

MCP_URL = os.getenv("MCP_CHECK_URL", "http://knowledge-mcp:6646")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
MCP_PROTOCOL_VERSION = os.getenv("MCP_PROTOCOL_VERSION", "2025-03-26")
DEFAULT_REQUIRED_TOOLS = ",".join(
    [
        "search_knowledge_01",
        "search_knowledge_02",
        "search_knowledge_03",
        "search_knowledge_04",
        "search_all",
        "list_topics",
        "get_doc_info",
        "reindex",
        "ingest_knowledge",
        "kb_stats",
    ]
)
REQUIRED_MCP_TOOLS = [
    tool.strip()
    for tool in os.getenv("REQUIRED_MCP_TOOLS", DEFAULT_REQUIRED_TOOLS).split(",")
    if tool.strip()
]


def _mcp_endpoint() -> str:
    return MCP_URL.rstrip("/") if MCP_URL.rstrip("/").endswith("/mcp") else f"{MCP_URL.rstrip('/')}/mcp"


def _post_mcp(payload: Dict[str, Any], session_id: str = "") -> requests.Response:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    return requests.post(_mcp_endpoint(), headers=headers, json=payload, timeout=15)


def _extract_json(response: requests.Response) -> Dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        data = None

    if data is None:
        for line in response.text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line.removeprefix("data:").strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                parsed = json.loads(payload)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                return parsed
        return {}

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("jsonrpc") == "2.0":
                return item
        return {}
    if isinstance(data, dict):
        return data
    return {}


async def _list_mcp_tools_with_sdk() -> List[str]:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(_mcp_endpoint()) as streams:
        read_stream, write_stream = streams[0], streams[1]
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            response = await session.list_tools()
            return [tool.name for tool in response.tools]


async def _call_mcp_tool_with_sdk(tool_name: str) -> str:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(_mcp_endpoint()) as streams:
        read_stream, write_stream = streams[0], streams[1]
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            response = await session.call_tool(tool_name, {})
            return str(response)


def _list_mcp_tools_with_http() -> Dict[str, Any]:
    init_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "ragcheck", "version": "1.0.0"},
        },
    }
    init_response = _post_mcp(init_payload)
    init_ok = init_response.status_code == 200
    init_body = _extract_json(init_response) if init_ok else {}
    if not init_ok or "error" in init_body:
        error_detail = init_body.get("error") if isinstance(init_body, dict) else None
        return {
            "ok": False,
            "detail": f"initialize failed: HTTP {init_response.status_code}, error={error_detail}",
            "tools": [],
        }

    session_id = init_response.headers.get("Mcp-Session-Id", "")

    initialized_payload = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    try:
        _post_mcp(initialized_payload, session_id=session_id)
    except Exception:
        logger.debug("initialized notification failed", exc_info=True)

    tools_payload = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    tools_response = _post_mcp(tools_payload, session_id=session_id)
    tools_ok = tools_response.status_code == 200
    tools_body = _extract_json(tools_response) if tools_ok else {}
    if not tools_ok or "error" in tools_body:
        error_detail = tools_body.get("error") if isinstance(tools_body, dict) else None
        return {
            "ok": False,
            "detail": f"tools/list failed: HTTP {tools_response.status_code}, error={error_detail}",
            "tools": [],
        }

    tools = tools_body.get("result", {}).get("tools", [])
    tool_names = [tool.get("name", "") for tool in tools if isinstance(tool, dict)]
    return {
        "ok": True,
        "detail": f"listed {len(tool_names)} tools",
        "tools": tool_names,
    }


def _list_mcp_tools() -> Dict[str, Any]:
    try:
        tool_names = asyncio.run(_list_mcp_tools_with_sdk())
        return {
            "ok": True,
            "detail": f"listed {len(tool_names)} tools via MCP SDK",
            "tools": tool_names,
        }
    except Exception as sdk_exc:
        sdk_error = str(sdk_exc)
        logger.warning("MCP SDK tools/list failed, falling back to raw HTTP: %s", sdk_error)

    fallback = _list_mcp_tools_with_http()
    if fallback["ok"]:
        fallback["detail"] = f"{fallback['detail']} via raw HTTP fallback after SDK error: {sdk_error}"
    else:
        fallback["detail"] = f"{fallback['detail']}; SDK error: {sdk_error}"
    return fallback


def _probe_mcp_tool(tool_name: str) -> Dict[str, Any]:
    try:
        result = asyncio.run(_call_mcp_tool_with_sdk(tool_name))
        return {
            "ok": True,
            "detail": f"{tool_name} callable, response_length={len(result)}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "detail": f"{tool_name} call failed: {exc}",
        }


def check_qdrant() -> Dict[str, Any]:
    try:
        response = requests.get(f"{QDRANT_URL}/collections", timeout=10)
        ok = response.status_code == 200
        data = response.json() if ok else {}
        collections = [collection["name"] for collection in data.get("result", {}).get("collections", [])]
        return {
            "name": "Qdrant database",
            "ok": ok,
            "detail": f"HTTP {response.status_code}, collections: {', '.join(collections) if collections else 'none'}",
        }
    except Exception as exc:
        return {"name": "Qdrant database", "ok": False, "detail": str(exc)}


def check_qdrant_collections() -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    try:
        response = requests.get(f"{QDRANT_URL}/collections", timeout=10)
        if response.status_code != 200:
            return results

        collections = response.json().get("result", {}).get("collections", [])
        for collection in collections:
            name = collection["name"]
            try:
                detail_response = requests.get(f"{QDRANT_URL}/collections/{name}", timeout=10)
                if detail_response.status_code != 200:
                    results.append(
                        {"name": f"Collection: {name}", "ok": False, "detail": f"HTTP {detail_response.status_code}"}
                    )
                    continue

                info = detail_response.json().get("result", {})
                results.append(
                    {
                        "name": f"Collection: {name}",
                        "ok": True,
                        "detail": (
                            f"points: {info.get('points_count', 0)}, "
                            f"indexed_vectors: {info.get('indexed_vectors_count', 0)}, "
                            f"dimension: {info.get('config', {}).get('params', {}).get('vectors', {}).get('size', 0)}"
                        ),
                    }
                )
            except Exception as exc:
                results.append({"name": f"Collection: {name}", "ok": False, "detail": str(exc)})
    except Exception:
        logger.debug("Unable to enumerate Qdrant collections", exc_info=True)
    return results


def check_mcp_tools() -> Dict[str, Any]:
    try:
        result = _list_mcp_tools()
        if not result["ok"]:
            probe = _probe_mcp_tool("kb_stats")
            if probe["ok"]:
                return {
                    "name": "MCP tools",
                    "ok": True,
                    "detail": f"{probe['detail']}; tools/list diagnostic: {result['detail']}",
                }
            return {"name": "MCP tools", "ok": False, "detail": f"{result['detail']}; {probe['detail']}"}

        available_tools = set(result["tools"])
        if not available_tools:
            probe = _probe_mcp_tool("kb_stats")
            if probe["ok"]:
                return {
                    "name": "MCP tools",
                    "ok": True,
                    "detail": f"{probe['detail']}; tools/list returned no names ({result['detail']})",
                }
            return {
                "name": "MCP tools",
                "ok": False,
                "detail": f"tools/list returned no names ({result['detail']}); {probe['detail']}",
            }

        missing_tools = [tool for tool in REQUIRED_MCP_TOOLS if tool not in available_tools]
        ok = not missing_tools
        detail_parts = [
            result["detail"],
            f"available={', '.join(sorted(available_tools)) if available_tools else 'none'}",
            f"required={', '.join(REQUIRED_MCP_TOOLS) if REQUIRED_MCP_TOOLS else 'none'}",
        ]
        if missing_tools:
            detail_parts.append(f"missing={', '.join(missing_tools)}")
        return {"name": "MCP tools", "ok": ok, "detail": "; ".join(detail_parts)}
    except Exception as exc:
        return {"name": "MCP tools", "ok": False, "detail": str(exc)}


def run_all_checks() -> Dict[str, Any]:
    now = datetime.now()
    results: List[Dict[str, Any]] = []

    results.append(check_qdrant())
    results.extend(check_qdrant_collections())
    results.append(check_mcp_tools())

    all_ok = all(result["ok"] for result in results)
    passed = sum(1 for result in results if result["ok"])
    total = len(results)

    return {
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "overall": "OK" if all_ok else "FAIL",
        "all_ok": all_ok,
        "passed": passed,
        "total": total,
        "checks": results,
    }
