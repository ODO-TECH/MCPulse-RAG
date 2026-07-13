import os
import time
import logging
import schedule

from healthcheck import run_all_checks
from report import render_html, save_report, cleanup_old_reports
from mailer import send_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

CHECK_INTERVAL_DAYS = int(os.getenv("CHECK_INTERVAL_DAYS", "3"))
REPORT_RETENTION_DAYS = int(os.getenv("REPORT_RETENTION_DAYS", "30"))


def do_check():
    logger.info("开始健康检查...")
    report = run_all_checks()
    html = render_html(report)
    save_report(report, html)
    cleanup_old_reports(REPORT_RETENTION_DAYS)

    status = report["overall"]
    subject = f"[知识库检查] {status} - {report['timestamp']}"
    send_report(subject, html)

    logger.info("检查完成: %s (%d/%d)", status, report["passed"], report["total"])


def main():
    logger.info("RAGcheck 启动")
    logger.info("检查间隔: %d 天", CHECK_INTERVAL_DAYS)
    logger.info("报告保留: %d 天", REPORT_RETENTION_DAYS)

    do_check()

    schedule.every(CHECK_INTERVAL_DAYS).days.at("09:00").do(do_check)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
