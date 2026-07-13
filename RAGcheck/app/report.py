import os
import glob
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

REPORT_DIR = Path("/app/reports")


REPORT_TEMPLATE = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><style>
body {{ font-family: -apple-system, sans-serif; margin: 20px; color: #333; }}
h1 {{ color: {title_color}; }}
table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
th {{ background: #f5f5f5; }}
.ok {{ color: #22c55e; font-weight: bold; }}
.fail {{ color: #ef4444; font-weight: bold; }}
.footer {{ color: #999; font-size: 12px; margin-top: 24px; }}
</style></head>
<body>
<h1>知识库 MCP 健康检查报告</h1>
<p><strong>检查时间：</strong>{timestamp}</p>
<p><strong>总体状态：</strong><span class="{status_class}">{overall} ({passed}/{total})</span></p>
<table>
<tr><th>检查项</th><th>状态</th><th>详情</th></tr>
{rows}
</table>
<p class="footer">由 RAGcheck 自动生成</p>
</body>
</html>"""


def render_html(report: dict) -> str:
    rows = ""
    for c in report["checks"]:
        status = '<span class="ok">\u2713 正常</span>' if c["ok"] else '<span class="fail">\u2717 异常</span>'
        rows += f'<tr><td>{c["name"]}</td><td>{status}</td><td>{c["detail"]}</td></tr>\n'

    title_color = "#22c55e" if report["all_ok"] else "#ef4444"
    status_class = "ok" if report["all_ok"] else "fail"

    return REPORT_TEMPLATE.format(
        title_color=title_color,
        timestamp=report["timestamp"],
        overall=report["overall"],
        status_class=status_class,
        passed=report["passed"],
        total=report["total"],
        rows=rows,
    )


def save_report(report: dict, html: str) -> str:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    path = REPORT_DIR / filename
    path.write_text(html, encoding="utf-8")
    logger.info("报告已保存: %s", path)
    return str(path)


def cleanup_old_reports(retention_days: int):
    cutoff = datetime.now() - timedelta(days=retention_days)
    pattern = str(REPORT_DIR / "report_*.html")
    removed = 0

    for fpath in glob.glob(pattern):
        try:
            fname = Path(fpath).stem
            date_str = fname.replace("report_", "")[:8]
            file_date = datetime.strptime(date_str, "%Y%m%d")
            if file_date < cutoff:
                os.remove(fpath)
                removed += 1
        except (ValueError, OSError):
            pass

    if removed:
        logger.info("已清理 %d 份过期报告", removed)
