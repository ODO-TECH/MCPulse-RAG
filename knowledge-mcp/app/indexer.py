import json
import time
import logging
from pathlib import Path
from typing import List, Dict, Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models

from utils import (
    load_config, read_file, chunk_text, file_hash,
    make_point_id, get_embeddings, ALLOWED_EXT,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

STATE_DIR = Path("/app/state")


def get_state_path(base_name: str) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / f"{base_name}.json"


def load_state(base_name: str) -> Dict[str, str]:
    p = get_state_path(base_name)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def save_state(base_name: str, state: Dict[str, str]):
    p = get_state_path(base_name)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_collection(client: QdrantClient, name: str, vector_size: int):
    collections = [c.name for c in client.get_collections().collections]
    if name in collections:
        try:
            info = client.get_collection(name)
            existing_size = info.config.params.vectors.size
            if existing_size != vector_size:
                logger.warning(
                    "Collection %s 向量维度不匹配（现有 %d，需要 %d），重建",
                    name, existing_size, vector_size,
                )
                client.delete_collection(name)
            else:
                return
        except Exception:
            return
    client.create_collection(
        collection_name=name,
        vectors_config=qdrant_models.VectorParams(
            size=vector_size,
            distance=qdrant_models.Distance.COSINE,
        ),
    )
    for field in ["relative_path", "level1", "level2", "level3"]:
        client.create_payload_index(
            collection_name=name,
            field_name=field,
            field_schema=qdrant_models.KeywordIndexParams(type="keyword", on_disk=True),
        )
    logger.info("创建 collection: %s, vector_size=%d", name, vector_size)


def index_base(client: QdrantClient, cfg: Dict[str, Any], base: Dict[str, str], force: bool = False):
    root = Path(cfg["knowledge"]["root"])
    base_path = root / base["path"]
    collection = base["collection"]
    base_name = base["name"]

    if not base_path.exists():
        logger.warning("目录不存在: %s，跳过 %s", base_path, base_name)
        return

    chunk_size = cfg["retrieval"]["chunk_size"]
    chunk_overlap = cfg["retrieval"]["chunk_overlap"]

    logger.info("=== 扫描知识库: %s ===", base_name)

    file_list = [
        f for f in base_path.rglob("*")
        if f.is_file() and f.suffix.lower() in ALLOWED_EXT
    ]
    logger.info("发现 %d 个文件", len(file_list))

    old_state = {} if force else load_state(base_name)
    new_state = {}
    file_chunks: Dict[str, List[Dict]] = {}
    changed_files = []

    for fpath in file_list:
        rel = fpath.relative_to(root).as_posix()
        fh = file_hash(fpath)
        new_state[rel] = fh

        if not force and old_state.get(rel) == fh:
            continue

        changed_files.append(rel)
        text = read_file(fpath)
        if not text.strip():
            continue

        dir_path = fpath.parent.relative_to(root).as_posix()
        parts = rel.split("/")
        meta = {
            "file_name": fpath.name,
            "relative_path": rel,
            "dir_path": dir_path,
            "level1": parts[0] if len(parts) > 0 else "",
            "level2": parts[1] if len(parts) > 1 else "",
            "level3": parts[2] if len(parts) > 2 else "",
        }
        chunks = chunk_text(text, chunk_size, chunk_overlap)
        file_chunks[rel] = [
            {"text": c, "metadata": meta, "rel_path": rel, "chunk_index": ci}
            for ci, c in enumerate(chunks)
        ]

    if force:
        deleted_files = list(old_state.keys())
    else:
        deleted_files = [r for r in old_state if r not in new_state]

    if not changed_files and not deleted_files:
        logger.info("无变更，跳过 %s", base_name)
        return

    all_chunks = []
    for chunks in file_chunks.values():
        all_chunks.extend(chunks)

    logger.info("变更文件 %d，删除文件 %d，共 %d chunk 待索引",
                len(changed_files), len(deleted_files), len(all_chunks))

    if force:
        collections = [c.name for c in client.get_collections().collections]
        if collection in collections:
            client.delete_collection(collection)
            logger.info("已删除旧 collection: %s", collection)

    if all_chunks:
        batch_size = 32
        first_batch_texts = [c["text"] for c in all_chunks[:batch_size]]
        first_embs = get_embeddings(first_batch_texts, cfg)
        vector_size = len(first_embs[0])
        ensure_collection(client, collection, vector_size)

        for rel in file_chunks:
            try:
                client.delete(
                    collection_name=collection,
                    points_selector=qdrant_models.FilterSelector(
                        filter=qdrant_models.Filter(
                            must=[qdrant_models.FieldCondition(
                                key="relative_path",
                                match=qdrant_models.MatchValue(value=rel),
                            )]
                        )
                    ),
                )
            except Exception:
                pass

        for i in range(0, len(all_chunks), batch_size):
            batch = all_chunks[i:i + batch_size]
            texts = [c["text"] for c in batch]
            embs = get_embeddings(texts, cfg)

            points = []
            for rc, emb in zip(batch, embs):
                points.append(qdrant_models.PointStruct(
                    id=make_point_id(rc["rel_path"], rc["chunk_index"]),
                    vector=emb,
                    payload={"text": rc["text"], **rc["metadata"]},
                ))

            client.upsert(collection_name=collection, points=points)
            logger.info("写入进度: %d/%d", min(i + batch_size, len(all_chunks)), len(all_chunks))

    if deleted_files and not force:
        for rel in deleted_files:
            try:
                client.delete(
                    collection_name=collection,
                    points_selector=qdrant_models.FilterSelector(
                        filter=qdrant_models.Filter(
                            must=[qdrant_models.FieldCondition(
                                key="relative_path",
                                match=qdrant_models.MatchValue(value=rel),
                            )]
                        )
                    ),
                )
            except Exception:
                pass
        logger.info("已删除 %d 个文件的旧向量", len(deleted_files))

    save_state(base_name, new_state)
    logger.info("完成: %s，索引 %d chunk", base_name, len(all_chunks))


def _connect_qdrant(host: str, port: int) -> QdrantClient:
    for attempt in range(10):
        try:
            c = QdrantClient(host=host, port=port)
            c.get_collections()
            return c
        except Exception as e:
            logger.warning("等待 Qdrant... (%d/10) %s", attempt + 1, e)
            time.sleep(3)
    raise RuntimeError("无法连接 Qdrant")


def main(force: bool = False):
    cfg = load_config()
    client = _connect_qdrant(cfg["qdrant"]["host"], int(cfg["qdrant"]["port"]))
    for base in cfg["knowledge"]["bases"]:
        try:
            index_base(client, cfg, base, force=force)
        except Exception as e:
            logger.error("索引 %s 失败: %s", base["name"], e, exc_info=True)
    logger.info("全部索引完成")


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    main(force=force)
