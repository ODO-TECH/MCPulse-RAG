import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List

from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models

from utils import ALLOWED_EXT, chunk_text, file_hash, get_embeddings, load_config, make_point_id, read_file

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

STATE_DIR = Path("/app/state")


def get_state_path(base_name: str) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / f"{base_name}.json"


def load_state(base_name: str) -> Dict[str, str]:
    state_path = get_state_path(base_name)
    if not state_path.exists():
        return {}
    return json.loads(state_path.read_text(encoding="utf-8"))


def save_state(base_name: str, state: Dict[str, str]):
    state_path = get_state_path(base_name)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_collection(client: QdrantClient, name: str, vector_size: int):
    collections = [collection.name for collection in client.get_collections().collections]
    if name in collections:
        try:
            info = client.get_collection(name)
            existing_size = info.config.params.vectors.size
            if existing_size == vector_size:
                return

            logger.warning(
                "Collection %s vector size mismatch: existing=%d expected=%d. Recreating.",
                name,
                existing_size,
                vector_size,
            )
            client.delete_collection(name)
        except Exception:
            return

    client.create_collection(
        collection_name=name,
        vectors_config=qdrant_models.VectorParams(
            size=vector_size,
            distance=qdrant_models.Distance.COSINE,
        ),
    )
    for field in ["relative_path", "dir_path", "level1", "level2", "level3"]:
        client.create_payload_index(
            collection_name=name,
            field_name=field,
            field_schema=qdrant_models.KeywordIndexParams(type="keyword", on_disk=True),
        )
    logger.info("Created collection %s with vector_size=%d", name, vector_size)


def _list_supported_files(base_path: Path) -> List[Path]:
    return [path for path in base_path.rglob("*") if path.is_file() and path.suffix.lower() in ALLOWED_EXT]


def _delete_file_points(client: QdrantClient, collection: str, rel_path: str):
    client.delete(
        collection_name=collection,
        points_selector=qdrant_models.FilterSelector(
            filter=qdrant_models.Filter(
                must=[
                    qdrant_models.FieldCondition(
                        key="relative_path",
                        match=qdrant_models.MatchValue(value=rel_path),
                    )
                ]
            )
        ),
    )


def _build_chunk_records(root: Path, file_path: Path, chunk_size: int, chunk_overlap: int) -> List[Dict[str, Any]]:
    text = read_file(file_path)
    if not text.strip():
        return []

    rel_path = file_path.relative_to(root).as_posix()
    dir_path = file_path.parent.relative_to(root).as_posix()
    parts = rel_path.split("/")
    metadata = {
        "file_name": file_path.name,
        "relative_path": rel_path,
        "dir_path": dir_path,
        "level1": parts[0] if len(parts) > 0 else "",
        "level2": parts[1] if len(parts) > 1 else "",
        "level3": parts[2] if len(parts) > 2 else "",
    }

    return [
        {
            "text": chunk,
            "metadata": metadata,
            "rel_path": rel_path,
            "chunk_index": chunk_index,
        }
        for chunk_index, chunk in enumerate(chunk_text(text, chunk_size, chunk_overlap))
    ]


def index_base(client: QdrantClient, cfg: Dict[str, Any], base: Dict[str, str], force: bool = False):
    root = Path(cfg["knowledge"]["root"])
    base_path = root / base["path"]
    collection = base["collection"]
    base_name = base["name"]

    if not base_path.exists():
        logger.warning("Knowledge base path does not exist, skipping %s: %s", base_name, base_path)
        return

    collections = [collection_info.name for collection_info in client.get_collections().collections]
    if collection not in collections and not force:
        logger.warning(
            "Collection %s is missing while state may exist; rebuilding base=%s",
            collection,
            base_name,
        )
        force = True

    logger.info("Scanning knowledge base: %s", base_name)

    file_list = _list_supported_files(base_path)
    logger.info("Discovered %d supported files in base=%s", len(file_list), base_name)

    chunk_size = int(cfg["retrieval"]["chunk_size"])
    chunk_overlap = int(cfg["retrieval"]["chunk_overlap"])
    old_state = {} if force else load_state(base_name)
    new_state: Dict[str, str] = {}
    changed_files: List[str] = []
    file_chunks: Dict[str, List[Dict[str, Any]]] = {}

    for file_path in file_list:
        rel_path = file_path.relative_to(root).as_posix()
        new_hash = file_hash(file_path)
        new_state[rel_path] = new_hash

        if not force and old_state.get(rel_path) == new_hash:
            continue

        changed_files.append(rel_path)
        file_chunks[rel_path] = _build_chunk_records(root, file_path, chunk_size, chunk_overlap)

    deleted_files = list(old_state.keys()) if force else [rel_path for rel_path in old_state if rel_path not in new_state]

    if not changed_files and not deleted_files:
        logger.info("No content changes detected for base=%s", base_name)
        return

    if force and collection in collections:
        client.delete_collection(collection)
        logger.info("Deleted existing collection before full rebuild: %s", collection)

    all_chunks: List[Dict[str, Any]] = []
    for rel_path in changed_files:
        all_chunks.extend(file_chunks.get(rel_path, []))

    logger.info(
        "Indexing base=%s changed_files=%d deleted_files=%d chunks=%d force=%s",
        base_name,
        len(changed_files),
        len(deleted_files),
        len(all_chunks),
        force,
    )

    if all_chunks:
        batch_size = 32
        first_embeddings = get_embeddings([chunk["text"] for chunk in all_chunks[:batch_size]], cfg)
        ensure_collection(client, collection, len(first_embeddings[0]))

        for rel_path in changed_files:
            try:
                _delete_file_points(client, collection, rel_path)
            except Exception:
                logger.warning("Failed to delete old vectors before reindexing file=%s", rel_path, exc_info=True)

        for start in range(0, len(all_chunks), batch_size):
            batch = all_chunks[start:start + batch_size]
            embeddings = get_embeddings([chunk["text"] for chunk in batch], cfg)
            points = [
                qdrant_models.PointStruct(
                    id=make_point_id(chunk["rel_path"], chunk["chunk_index"]),
                    vector=embedding,
                    payload={"text": chunk["text"], **chunk["metadata"]},
                )
                for chunk, embedding in zip(batch, embeddings)
            ]
            client.upsert(collection_name=collection, points=points)
            logger.info("Upsert progress for base=%s: %d/%d", base_name, min(start + batch_size, len(all_chunks)), len(all_chunks))

    for rel_path in deleted_files:
        try:
            _delete_file_points(client, collection, rel_path)
        except Exception:
            logger.warning("Failed to delete removed file vectors for file=%s", rel_path, exc_info=True)

    save_state(base_name, new_state)
    logger.info("Indexing complete for base=%s", base_name)


def index_bases(
    client: QdrantClient,
    cfg: Dict[str, Any],
    base_names: Iterable[str] | None = None,
    force: bool = False,
) -> List[Dict[str, str]]:
    all_bases = {base["name"]: base for base in cfg["knowledge"]["bases"]}
    selected_names = list(base_names) if base_names else list(all_bases.keys())

    results: List[Dict[str, str]] = []
    for base_name in selected_names:
        base = all_bases.get(base_name)
        if base is None:
            results.append({"base": base_name, "status": "error", "message": "unknown knowledge base"})
            continue

        try:
            index_base(client, cfg, base, force=force)
            results.append({"base": base_name, "status": "ok", "message": "indexed"})
        except Exception as exc:
            logger.error("Indexing failed for base=%s: %s", base_name, exc, exc_info=True)
            results.append({"base": base_name, "status": "error", "message": str(exc)})

    return results


def _connect_qdrant(host: str, port: int) -> QdrantClient:
    for attempt in range(10):
        try:
            client = QdrantClient(host=host, port=port)
            client.get_collections()
            return client
        except Exception as exc:
            logger.warning("Waiting for Qdrant... (%d/10) %s", attempt + 1, exc)
            time.sleep(3)
    raise RuntimeError("Unable to connect to Qdrant")


def main(force: bool = False):
    cfg = load_config()
    client = _connect_qdrant(cfg["qdrant"]["host"], int(cfg["qdrant"]["port"]))
    results = index_bases(client, cfg, force=force)
    for result in results:
        logger.info("Base %s -> %s (%s)", result["base"], result["status"], result["message"])
    logger.info("All indexing tasks completed")


if __name__ == "__main__":
    import sys

    main(force="--force" in sys.argv)
