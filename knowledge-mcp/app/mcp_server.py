import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List

import requests
try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError as exc:
    raise ModuleNotFoundError(
        "FastMCP is missing. Rebuild the Docker image after installing the pinned MCP SDK "
        "from requirements.txt, then restart the container."
    ) from exc
from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models

from indexer import index_base
from utils import ALLOWED_EXT, load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

cfg = load_config()

mcp = FastMCP(
    "knowledge-base",
    host=os.getenv("MCP_HOST", "0.0.0.0"),
    port=int(os.getenv("MCP_PORT", "6646")),
)

API_BASE = cfg["models"]["api_base"]
API_KEY = os.getenv("MODEL_API_KEY", "")
EMBED_MODEL = cfg["models"]["embed_model"]
RERANK_MODEL = cfg["models"]["rerank_model"]
QDRANT_HOST = cfg["qdrant"]["host"]
QDRANT_PORT = int(cfg["qdrant"]["port"])


def _connect_qdrant() -> QdrantClient:
    for attempt in range(10):
        try:
            qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
            qdrant_client.get_collections()
            logger.info("Connected to Qdrant")
            return qdrant_client
        except Exception as exc:
            logger.warning("Waiting for Qdrant... (%d/10) %s", attempt + 1, exc)
            time.sleep(3)
    raise RuntimeError("Unable to connect to Qdrant")


client = _connect_qdrant()


def embed_query(text: str) -> List[float]:
    url = f"{API_BASE}/embeddings"
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {"model": EMBED_MODEL, "input": [text]}
    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()["data"][0]["embedding"]


def do_rerank(query: str, chunks: List[Dict[str, Any]], top_n: int) -> List[Dict[str, Any]]:
    if not chunks:
        return []

    url = f"{API_BASE}/rerank"
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": RERANK_MODEL,
        "query": query,
        "documents": [chunk["text"] for chunk in chunks],
        "top_n": top_n,
    }
    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()

    reranked: List[Dict[str, Any]] = []
    for item in response.json().get("results", []):
        index = item["index"]
        reranked.append(
            {
                "score": item["relevance_score"],
                "text": chunks[index]["text"],
                "payload": chunks[index]["payload"],
            }
        )
    return reranked


def search_collection(
    collection_name: str,
    query: str,
    top_k: int,
    rerank_top_n: int,
    dir_filter: str | None = None,
) -> List[Dict[str, Any]]:
    query_vector = embed_query(query)

    query_filter = None
    if dir_filter:
        query_filter = qdrant_models.Filter(
            must=[
                qdrant_models.FieldCondition(
                    key="dir_path",
                    match=qdrant_models.MatchValue(value=dir_filter),
                )
            ]
        )

    try:
        try:
            result = client.query_points(
                collection_name=collection_name,
                query=query_vector,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )
            hits = [type("Hit", (), {"payload": point.payload, "score": point.score})() for point in result.points]
        except AttributeError:
            hits = client.search(
                collection_name=collection_name,
                query_vector=query_vector,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )
    except Exception as exc:
        logger.error("Qdrant search failed for collection=%s: %s", collection_name, exc)
        return []

    chunks: List[Dict[str, Any]] = []
    for hit in hits:
        payload = hit.payload or {}
        chunks.append(
            {
                "text": payload.get("text", ""),
                "payload": payload,
                "score": hit.score,
            }
        )

    if not chunks:
        return []

    if not chunks[0]["text"]:
        return [
            {
                "score": chunk["score"],
                "text": chunk["payload"].get("file_name", ""),
                "payload": chunk["payload"],
            }
            for chunk in chunks
        ]

    reranked = do_rerank(query, chunks, rerank_top_n)
    if reranked:
        return reranked

    return [
        {
            "score": chunk["score"],
            "text": chunk["text"],
            "payload": chunk["payload"],
        }
        for chunk in chunks[:rerank_top_n]
    ]


def _format_results(results: List[Dict[str, Any]], include_base: bool = False) -> str:
    if not results:
        return "No relevant content found."

    lines: List[str] = []
    for index, item in enumerate(results, start=1):
        payload = item.get("payload", {})
        lines.append(f"## Result {index}")
        if include_base:
            lines.append(f"- Knowledge base: {item.get('base', 'unknown')}")
        lines.append(f"- Source: {payload.get('relative_path', 'unknown')}")
        lines.append(f"- Score: {item.get('score', 0):.4f}")
        lines.append("Content:")
        lines.append(item.get("text", ""))
        lines.append("")
    return "\n".join(lines).strip()


def _make_search(base_name: str, collection: str, description: str):
    def search(query: str, dir_filter: str = "") -> str:
        results = search_collection(
            collection_name=collection,
            query=query,
            top_k=cfg["retrieval"]["similarity_top_k"],
            rerank_top_n=cfg["retrieval"]["rerank_top_n"],
            dir_filter=dir_filter or None,
        )
        if not results:
            return f"[{base_name}] No relevant content found."
        return _format_results(results)

    search.__name__ = f"search_{base_name}"
    search.__qualname__ = f"search_{base_name}"
    search.__doc__ = description
    return search


for base in cfg["knowledge"]["bases"]:
    tool_name = f"search_{base['name']}"
    description = base.get("description", f"Search in the {base['name']} knowledge base")
    mcp.tool(name=tool_name, description=description)(_make_search(base["name"], base["collection"], description))
    logger.info("Registered MCP tool: %s", tool_name)


@mcp.tool(description="Search all knowledge bases and return the best results across them.")
def search_all(query: str, top_k_per_base: int = 3) -> str:
    all_results: List[Dict[str, Any]] = []
    for base in cfg["knowledge"]["bases"]:
        results = search_collection(
            collection_name=base["collection"],
            query=query,
            top_k=min(top_k_per_base + 5, cfg["retrieval"]["similarity_top_k"]),
            rerank_top_n=top_k_per_base,
        )
        for result in results:
            result["base"] = base["name"]
            all_results.append(result)

    all_results.sort(key=lambda item: item.get("score", 0), reverse=True)
    return _format_results(all_results[: top_k_per_base * 2], include_base=True)


@mcp.tool(description="List topic directories under the knowledge root or a specific subdirectory.")
def list_topics(parent_path: str = "") -> str:
    root = Path(cfg["knowledge"]["root"])
    target = root / parent_path if parent_path else root

    if not target.exists():
        return f"Path does not exist: {parent_path or '/'}"

    entries: List[str] = []
    for item in sorted(target.iterdir()):
        if item.is_dir() and not item.name.startswith("."):
            rel_path = item.relative_to(root).as_posix()
            file_count = len(
                [child for child in item.rglob("*") if child.is_file() and child.suffix.lower() in ALLOWED_EXT]
            )
            entries.append(f"- {rel_path}/ ({file_count} files)")

    if not entries:
        return f"No subdirectories found under {parent_path or '/'}"

    return f"Topic directories under {parent_path or '/'}:\n" + "\n".join(entries)


@mcp.tool(description="Show details for a specific file in the knowledge directory.")
def get_doc_info(file_path: str) -> str:
    root = Path(cfg["knowledge"]["root"])
    full_path = root / file_path

    if not full_path.exists():
        return f"File does not exist: {file_path}"

    stat = full_path.stat()
    rel_path = full_path.relative_to(root).as_posix()
    parts = rel_path.split("/")

    return (
        f"File: {rel_path}\n"
        f"Size: {stat.st_size / 1024:.1f} KB\n"
        f"Type: {full_path.suffix.lower()}\n"
        f"Hierarchy: {' > '.join(parts[:-1]) or '/'}\n"
        f"Name: {full_path.name}"
    )


@mcp.tool(
    description=(
        "Force a full rebuild of the vector index. "
        "Use this only when a normal incremental scan is not enough. "
        "If base_name is empty, rebuild all configured knowledge bases. "
        "If base_name is provided, it must be exactly one configured base name such as knowledge_01 or knowledge_02."
    )
)
def reindex(base_name: str = "") -> str:
    bases = cfg["knowledge"]["bases"]
    if base_name:
        bases = [base for base in bases if base["name"] == base_name]
        if not bases:
            return f"Unknown knowledge base: {base_name}"

    lines = ["Reindex results:"]
    for base in bases:
        try:
            index_base(client, cfg, base, force=True)
            lines.append(f"- OK {base['name']}: reindexed")
        except Exception as exc:
            lines.append(f"- ERROR {base['name']}: {exc}")
    return "\n".join(lines)


@mcp.tool(
    description=(
        "Preferred manual sync tool. "
        "Safe default usage is ingest_knowledge() with no arguments. "
        "That scans all configured knowledge bases and ingests new or changed files. "
        "If base_name is provided, only that one knowledge base is scanned incrementally. "
        "Do not use this tool for a full rebuild; use reindex for that."
    )
)
def ingest_knowledge(base_name: str = "") -> str:
    bases = cfg["knowledge"]["bases"]
    if base_name:
        bases = [base for base in bases if base["name"] == base_name]
        if not bases:
            return f"Unknown knowledge base: {base_name}"

    lines = ["Ingest results:"]
    for base in bases:
        try:
            index_base(client, cfg, base, force=False)
            lines.append(f"- OK {base['name']}: scanned for new or changed files")
        except Exception as exc:
            lines.append(f"- ERROR {base['name']}: {exc}")
    return "\n".join(lines)


@mcp.tool(description="Show collection and source file statistics for all knowledge bases.")
def kb_stats() -> str:
    lines = []
    for base in cfg["knowledge"]["bases"]:
        try:
            info = client.get_collection(base["collection"])
            lines.append(
                f"- {base['name']}: {info.points_count} vectors, dimension {info.config.params.vectors.size}"
            )
        except Exception:
            lines.append(f"- {base['name']}: collection missing or not indexed yet")

    root = Path(cfg["knowledge"]["root"])
    total_files = len([path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in ALLOWED_EXT])
    return "Knowledge base stats:\n" + f"Total files: {total_files}\n" + "\n".join(lines)


if __name__ == "__main__":
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "6646"))
    logger.info("MCP server starting on %s:%d (Streamable HTTP)", host, port)
    mcp.run(transport="streamable-http")
