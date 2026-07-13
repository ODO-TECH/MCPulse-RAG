import os
import time
import logging
from pathlib import Path
from typing import List, Dict, Any

import requests
from mcp.server.fastmcp import FastMCP
from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models

from utils import load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

cfg = load_config()

mcp = FastMCP(
    "knowledge-base",
    host=os.getenv("MCP_HOST", "0.0.0.0"),
    port=int(os.getenv("MCP_PORT", "6646")),
)

API_BASE = cfg["models"]["api_base"]
API_KEY = os.getenv("SILICONFLOW_API_KEY", "")
EMBED_MODEL = cfg["models"]["embed_model"]
RERANK_MODEL = cfg["models"]["rerank_model"]

QDRANT_HOST = cfg["qdrant"]["host"]
QDRANT_PORT = int(cfg["qdrant"]["port"])


def _connect_qdrant() -> QdrantClient:
    for attempt in range(10):
        try:
            c = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
            c.get_collections()
            logger.info("Qdrant 连接成功")
            return c
        except Exception as e:
            logger.warning("等待 Qdrant 就绪... (%d/10) %s", attempt + 1, e)
            time.sleep(3)
    raise RuntimeError("无法连接 Qdrant")


client = _connect_qdrant()


def embed_query(text: str) -> List[float]:
    url = f"{API_BASE}/embeddings"
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {"model": EMBED_MODEL, "input": [text]}
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()["data"][0]["embedding"]


def do_rerank(query: str, chunks: List[Dict[str, Any]], top_n: int) -> List[Dict[str, Any]]:
    if not chunks:
        return []
    url = f"{API_BASE}/rerank"
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": RERANK_MODEL,
        "query": query,
        "documents": [c["text"] for c in chunks],
        "top_n": top_n,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    results = []
    for item in resp.json().get("results", []):
        idx = item["index"]
        results.append({
            "score": item["relevance_score"],
            "text": chunks[idx]["text"],
            "payload": chunks[idx]["payload"],
        })
    return results


def search_collection(
    collection_name: str,
    query: str,
    top_k: int,
    rerank_top_n: int,
    dir_filter: str | None = None,
) -> List[Dict[str, Any]]:
    query_vec = embed_query(query)

    qdrant_filter = None
    if dir_filter:
        qdrant_filter = qdrant_models.Filter(
            must=[qdrant_models.FieldCondition(
                key="relative_path",
                match=qdrant_models.MatchValue(value=dir_filter),
            )]
        )

    try:
        try:
            result = client.query_points(
                collection_name=collection_name,
                query=query_vec,
                query_filter=qdrant_filter,
                limit=top_k,
                with_payload=True,
            )
            hits = [
                type("Hit", (), {"payload": p.payload, "score": p.score})()
                for p in result.points
            ]
        except AttributeError:
            hits = client.search(
                collection_name=collection_name,
                query_vector=query_vec,
                query_filter=qdrant_filter,
                limit=top_k,
                with_payload=True,
            )
    except Exception as e:
        logger.error("Qdrant 搜索失败 [%s]: %s", collection_name, e)
        return []

    chunks = []
    for h in hits:
        text = h.payload.get("text", "") if h.payload else ""
        chunks.append({"text": text, "payload": h.payload or {}, "score": h.score})

    if not chunks:
        return []

    if not chunks[0]["text"]:
        return [
            {"score": c["score"], "text": c["payload"].get("file_name", ""), "payload": c["payload"]}
            for c in chunks
        ]

    reranked = do_rerank(query, chunks, rerank_top_n)
    if reranked:
        return reranked
    return [
        {"score": c["score"], "text": c["text"], "payload": c["payload"]}
        for c in chunks[:rerank_top_n]
    ]


def _make_search(base_name: str, collection: str, description: str):
    def search(query: str, dir_filter: str = "") -> str:
        top_k = cfg["retrieval"]["similarity_top_k"]
        rerank_top_n = cfg["retrieval"]["rerank_top_n"]
        results = search_collection(
            collection, query, top_k, rerank_top_n,
            dir_filter=dir_filter if dir_filter else None,
        )
        if not results:
            return f"[{base_name}] 未找到相关内容。"
        lines = []
        for i, item in enumerate(results, 1):
            payload = item.get("payload", {})
            src = payload.get("relative_path", "unknown")
            score = item.get("score", 0)
            text = item.get("text", "")
            lines.append(
                f"## 结果 {i}\n"
                f"- 来源: {src}\n"
                f"- 相关度: {score:.4f}\n"
                f"内容:\n{text}\n"
            )
        return "\n".join(lines)

    search.__name__ = f"search_{base_name}"
    search.__qualname__ = f"search_{base_name}"
    search.__doc__ = description
    return search


for base in cfg["knowledge"]["bases"]:
    tool_name = f"search_{base['name']}"
    description = base.get("description", f"在 {base['name']} 知识库中搜索")
    fn = _make_search(base["name"], base["collection"], description)
    mcp.tool(name=tool_name, description=description)(fn)
    logger.info("注册工具: %s", tool_name)


@mcp.tool(description="在所有知识库中同时搜索，返回各库的最佳结果")
def search_all(query: str, top_k_per_base: int = 3) -> str:
    all_results = []
    for base in cfg["knowledge"]["bases"]:
        results = search_collection(
            base["collection"], query,
            top_k=min(top_k_per_base + 5, cfg["retrieval"]["similarity_top_k"]),
            rerank_top_n=top_k_per_base,
        )
        for r in results:
            r["base"] = base["name"]
            all_results.append(r)

    if not all_results:
        return "所有知识库均未找到相关内容。"

    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    top = all_results[:top_k_per_base * 2]

    lines = []
    for i, item in enumerate(top, 1):
        payload = item.get("payload", {})
        src = payload.get("relative_path", "unknown")
        base = item.get("base", "unknown")
        score = item.get("score", 0)
        text = item.get("text", "")
        lines.append(
            f"## 结果 {i}\n"
            f"- 知识库: {base}\n"
            f"- 来源: {src}\n"
            f"- 相关度: {score:.4f}\n"
            f"内容:\n{text}\n"
        )
    return "\n".join(lines)


@mcp.tool(description="列出知识库中所有可用的主题目录层级")
def list_topics(parent_path: str = "") -> str:
    root = Path(cfg["knowledge"]["root"])
    if parent_path:
        target = root / parent_path
    else:
        target = root

    if not target.exists():
        return f"路径不存在: {parent_path}"

    entries = []
    for item in sorted(target.iterdir()):
        if item.is_dir() and not item.name.startswith("."):
            rel = item.relative_to(root).as_posix()
            file_count = len([
                f for f in item.rglob("*")
                if f.is_file() and f.suffix.lower() in {".md", ".txt", ".pdf", ".docx", ".doc"}
            ])
            entries.append(f"- {rel}/ ({file_count} 个文件)")

    if not entries:
        return f"目录 {parent_path or '/'} 下无子目录"

    return f"主题目录 ({parent_path or '根目录'}):\n" + "\n".join(entries)


@mcp.tool(description="查看指定文件的详细信息")
def get_doc_info(file_path: str) -> str:
    root = Path(cfg["knowledge"]["root"])
    full_path = root / file_path

    if not full_path.exists():
        return f"文件不存在: {file_path}"

    stat = full_path.stat()
    size_kb = stat.st_size / 1024
    ext = full_path.suffix.lower()
    rel = full_path.relative_to(root).as_posix()
    parts = rel.split("/")

    return (
        f"文件: {rel}\n"
        f"大小: {size_kb:.1f} KB\n"
        f"类型: {ext}\n"
        f"层级: {' > '.join(parts[:-1])}\n"
        f"文件名: {full_path.name}"
    )


@mcp.tool(description="手动触发指定知识库或全部知识库的重新索引")
def reindex(base_name: str = "") -> str:
    from indexer import index_base
    bases = cfg["knowledge"]["bases"]
    if base_name:
        bases = [b for b in bases if b["name"] == base_name]
        if not bases:
            return f"未找到知识库: {base_name}"

    results = []
    for base in bases:
        try:
            index_base(client, cfg, base, force=True)
            results.append(f"✓ {base['name']}: 索引完成")
        except Exception as e:
            results.append(f"✗ {base['name']}: {e}")

    return "重新索引结果:\n" + "\n".join(results)


@mcp.tool(description="查看知识库统计信息")
def kb_stats() -> str:
    lines = []
    for base in cfg["knowledge"]["bases"]:
        name = base["name"]
        collection = base["collection"]
        try:
            info = client.get_collection(collection)
            count = info.points_count
            vectors = info.config.params.vectors.size
            lines.append(f"- {name}: {count} 个向量, 维度 {vectors}")
        except Exception:
            lines.append(f"- {name}: collection 不存在或未索引")

    root = Path(cfg["knowledge"]["root"])
    total_files = len([
        f for f in root.rglob("*")
        if f.is_file() and f.suffix.lower() in {".md", ".txt", ".pdf", ".docx", ".doc"}
    ])

    return (
        f"知识库统计:\n"
        f"总文件数: {total_files}\n"
        + "\n".join(lines)
    )


if __name__ == "__main__":
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "6646"))
    logger.info("MCP 服务启动: %s:%d (SSE)", host, port)
    mcp.run(transport="sse")
