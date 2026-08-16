import logging
import os
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

NOTIFY_MODE = os.getenv("NOTIFY_MODE", "qqbot").strip().lower()
QQ_BOT_WEBHOOK = os.getenv("QQ_BOT_WEBHOOK", "").strip()
QQ_BOT_TOKEN = os.getenv("QQ_BOT_TOKEN", "").strip()
QQ_BOT_TIMEOUT = int(os.getenv("QQ_BOT_TIMEOUT", "20"))
QQ_BOT_TARGET = os.getenv("QQ_BOT_TARGET", "").strip()
QQ_BOT_TARGET_TYPE = os.getenv("QQ_BOT_TARGET_TYPE", "private").strip().lower()


def _build_headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if QQ_BOT_TOKEN:
        headers["Authorization"] = f"Bearer {QQ_BOT_TOKEN}"
    return headers


def send_report(
    subject: str,
    text_body: str,
    html_body: str,
    markdown_body: Optional[str] = None,
    report: Optional[Dict[str, Any]] = None,
) -> bool:
    if NOTIFY_MODE != "qqbot":
        logger.warning("Unsupported NOTIFY_MODE=%s, skipping notification", NOTIFY_MODE)
        return False

    if not QQ_BOT_WEBHOOK:
        logger.warning("QQ bot webhook is not configured, skipping notification")
        return False

    payload: Dict[str, Any] = {
        "title": subject,
        "text": text_body,
        "html": html_body,
        "markdown": markdown_body or text_body,
        "source": "ragcheck",
        "target_type": QQ_BOT_TARGET_TYPE,
    }
    if QQ_BOT_TARGET:
        payload["target"] = QQ_BOT_TARGET
    if report is not None:
        payload["report"] = report

    try:
        response = requests.post(
            QQ_BOT_WEBHOOK,
            json=payload,
            headers=_build_headers(),
            timeout=QQ_BOT_TIMEOUT,
        )
        response.raise_for_status()
        logger.info("QQ bot notification sent successfully")
        return True
    except Exception as exc:
        logger.error("Failed to send QQ bot notification: %s", exc)
        return False
