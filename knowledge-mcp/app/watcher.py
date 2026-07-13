import time
import logging
import threading
from pathlib import Path
from typing import Dict, Set

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from utils import load_config, ALLOWED_EXT
from indexer import index_base

from qdrant_client import QdrantClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class KBEventHandler(FileSystemEventHandler):
    def __init__(self, cfg: Dict, client: QdrantClient):
        super().__init__()
        self.cfg = cfg
        self.client = client
        self.root = Path(cfg["knowledge"]["root"]).resolve()
        self.bases = {b["name"]: b for b in cfg["knowledge"]["bases"]}
        self.debounce_sec = cfg.get("watcher", {}).get("debounce_seconds", 30)
        self._pending: Dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def _is_target(self, path: str) -> bool:
        p = Path(path)
        return p.suffix.lower() in ALLOWED_EXT

    def _get_base(self, path: str) -> str | None:
        try:
            rel = Path(path).resolve().relative_to(self.root)
            top = rel.parts[0] if rel.parts else None
            if top and top in self.bases:
                return top
        except ValueError:
            pass
        return None

    def _on_change(self, event: FileSystemEvent):
        if event.is_directory:
            return
        if not self._is_target(event.src_path):
            return

        base = self._get_base(event.src_path)
        if not base:
            return

        logger.info("检测到文件变更: %s → 知识库 %s", event.src_path, base)
        self._schedule_reindex(base)

    def on_created(self, event: FileSystemEvent):
        self._on_change(event)

    def on_modified(self, event: FileSystemEvent):
        self._on_change(event)

    def on_deleted(self, event: FileSystemEvent):
        self._on_change(event)

    def on_moved(self, event: FileSystemEvent):
        if event.is_directory:
            return
        self._on_change(event)
        if hasattr(event, "dest_path"):
            base = self._get_base(event.dest_path)
            if base:
                self._schedule_reindex(base)

    def _schedule_reindex(self, base_name: str):
        with self._lock:
            if base_name in self._pending:
                self._pending[base_name].cancel()
            timer = threading.Timer(self.debounce_sec, self._do_reindex, args=(base_name,))
            timer.daemon = True
            timer.start()
            self._pending[base_name] = timer
            logger.info("计划 %d 秒后重建索引: %s", self.debounce_sec, base_name)

    def _do_reindex(self, base_name: str):
        with self._lock:
            self._pending.pop(base_name, None)

        base = self.bases.get(base_name)
        if not base:
            return
        try:
            logger.info("开始重建索引: %s", base_name)
            index_base(self.client, self.cfg, base, force=True)
            logger.info("重建完成: %s", base_name)
        except Exception as e:
            logger.error("重建索引失败 %s: %s", base_name, e, exc_info=True)

    def shutdown(self):
        with self._lock:
            for t in self._pending.values():
                t.cancel()
            self._pending.clear()


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


def run_watcher(cfg: Dict):
    client = _connect_qdrant(cfg["qdrant"]["host"], int(cfg["qdrant"]["port"]))
    root = cfg["knowledge"]["root"]
    handler = KBEventHandler(cfg, client)
    observer = Observer()
    observer.schedule(handler, root, recursive=True)
    observer.start()
    logger.info("文件监控已启动: %s", root)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        handler.shutdown()
        observer.stop()
    observer.join()


if __name__ == "__main__":
    cfg = load_config()
    run_watcher(cfg)
