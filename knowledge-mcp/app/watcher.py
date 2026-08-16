import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict

from qdrant_client import QdrantClient
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from indexer import index_base
from utils import ALLOWED_EXT, load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class KBEventHandler(FileSystemEventHandler):
    def __init__(self, cfg: Dict[str, Any], client: QdrantClient):
        super().__init__()
        self.cfg = cfg
        self.client = client
        self.root = Path(cfg["knowledge"]["root"]).resolve()
        self.bases = {base["name"]: base for base in cfg["knowledge"]["bases"]}
        self.debounce_sec = int(cfg.get("watcher", {}).get("debounce_seconds", 30))
        self._pending: Dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def _is_target_file(self, path: str) -> bool:
        return Path(path).suffix.lower() in ALLOWED_EXT

    def _resolve_base_name(self, path: str) -> str | None:
        try:
            rel = Path(path).resolve().relative_to(self.root)
        except ValueError:
            return None

        if not rel.parts:
            return None

        base_name = rel.parts[0]
        if base_name in self.bases:
            return base_name
        return None

    def _queue_event(self, path: str):
        if not self._is_target_file(path):
            return

        base_name = self._resolve_base_name(path)
        if not base_name:
            return

        logger.info("Detected knowledge file change: %s -> base=%s", path, base_name)
        self._schedule_reindex(base_name)

    def on_created(self, event: FileSystemEvent):
        if not event.is_directory:
            self._queue_event(event.src_path)

    def on_modified(self, event: FileSystemEvent):
        if not event.is_directory:
            self._queue_event(event.src_path)

    def on_deleted(self, event: FileSystemEvent):
        if not event.is_directory:
            self._queue_event(event.src_path)

    def on_moved(self, event: FileSystemEvent):
        if event.is_directory:
            return

        self._queue_event(event.src_path)
        dest_path = getattr(event, "dest_path", "")
        if dest_path:
            self._queue_event(dest_path)

    def _schedule_reindex(self, base_name: str):
        with self._lock:
            existing = self._pending.get(base_name)
            if existing is not None:
                existing.cancel()

            timer = threading.Timer(self.debounce_sec, self._run_incremental_index, args=(base_name,))
            timer.daemon = True
            timer.start()
            self._pending[base_name] = timer

        logger.info("Scheduled incremental indexing for base=%s in %ss", base_name, self.debounce_sec)

    def _run_incremental_index(self, base_name: str):
        with self._lock:
            self._pending.pop(base_name, None)

        base = self.bases.get(base_name)
        if base is None:
            logger.warning("Skipping unknown base during watcher indexing: %s", base_name)
            return

        try:
            logger.info("Starting watcher-triggered incremental indexing for base=%s", base_name)
            index_base(self.client, self.cfg, base, force=False)
            logger.info("Watcher-triggered indexing completed for base=%s", base_name)
        except Exception as exc:
            logger.error("Watcher-triggered indexing failed for base=%s: %s", base_name, exc, exc_info=True)

    def shutdown(self):
        with self._lock:
            for timer in self._pending.values():
                timer.cancel()
            self._pending.clear()


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


def _build_observer(cfg: Dict[str, Any]):
    watcher_cfg = cfg.get("watcher", {})
    observer_type = str(watcher_cfg.get("observer", "polling")).lower()
    polling_interval = float(watcher_cfg.get("polling_interval_seconds", 5))

    if observer_type == "event":
        return Observer(), observer_type, polling_interval
    return PollingObserver(timeout=polling_interval), observer_type, polling_interval


def run_watcher(cfg: Dict[str, Any]):
    client = _connect_qdrant(cfg["qdrant"]["host"], int(cfg["qdrant"]["port"]))
    root = cfg["knowledge"]["root"]
    handler = KBEventHandler(cfg, client)
    observer, observer_type, polling_interval = _build_observer(cfg)

    observer.schedule(handler, root, recursive=True)
    observer.start()
    logger.info(
        "Knowledge watcher started on %s (observer=%s, interval=%ss)",
        root,
        observer_type,
        polling_interval,
    )

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        handler.shutdown()
        observer.stop()

    observer.join()


if __name__ == "__main__":
    run_watcher(load_config())
