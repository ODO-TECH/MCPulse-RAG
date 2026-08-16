import logging
import os
import time

import schedule

from healthcheck import run_all_checks
from notifier import send_report
from report import cleanup_old_reports, render_html, render_markdown, render_text, save_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

CHECK_INTERVAL_DAYS = int(os.getenv("CHECK_INTERVAL_DAYS", "3"))
REPORT_RETENTION_DAYS = int(os.getenv("REPORT_RETENTION_DAYS", "30"))


def do_check():
    logger.info("Starting health checks...")
    report = run_all_checks()
    html = render_html(report)
    markdown = render_markdown(report)
    text = render_text(report)

    save_report(report, html)
    cleanup_old_reports(REPORT_RETENTION_DAYS)

    status = report["overall"]
    subject = f"[RAGcheck] {status} - {report['timestamp']}"
    send_report(subject, text, html, markdown, report)

    logger.info("Check finished: %s (%d/%d)", status, report["passed"], report["total"])


def main():
    logger.info("RAGcheck started")
    logger.info("Check interval: %d day(s)", CHECK_INTERVAL_DAYS)
    logger.info("Report retention: %d day(s)", REPORT_RETENTION_DAYS)

    do_check()
    schedule.every(CHECK_INTERVAL_DAYS).days.at("09:00").do(do_check)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
