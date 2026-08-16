import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "0"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
MAIL_FROM = os.getenv("MAIL_FROM", "")
MAIL_TO = os.getenv("MAIL_TO", "")


def send_report(
    subject: str,
    text_body: str,
    html_body: str,
    markdown_body: Optional[str] = None,
    report: Optional[Dict[str, Any]] = None,
) -> bool:
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASS, MAIL_FROM, MAIL_TO]) or SMTP_PORT <= 0:
        logger.warning("Email configuration is incomplete, skipping report delivery")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = MAIL_FROM
    msg["To"] = MAIL_TO

    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
            server.starttls()

        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(MAIL_FROM, [MAIL_TO], msg.as_string())
        server.quit()
        logger.info("Email report sent: %s", MAIL_TO)
        return True
    except Exception as exc:
        logger.error("Email delivery failed: %s", exc)
        return False
