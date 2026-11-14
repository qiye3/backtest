"""分钟线发布成功后，经 QQ SMTP 发送一次当日完成通知。"""

from __future__ import annotations

import json
import logging
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

from src.intraday.data import _write_json_atomic

MAIL_ADDRESS = "783829986@qq.com"
AUTHORIZATION_PATH = Path("/home/qiye/.config/backtest/qq_smtp_authorization")
LOGGER = logging.getLogger(__name__)


def notify_minute_completion(status_path: Path) -> str:
    status = json.loads(status_path.read_text())
    day = status["latest_date"]
    receipt_path = status_path.parent / "mail_receipts" / f"{day}.json"
    if receipt_path.exists():
        return "sent"
    if not AUTHORIZATION_PATH.exists() or not AUTHORIZATION_PATH.read_text().strip():
        LOGGER.warning("下载完成，邮件等待配置 QQ SMTP 授权码")
        return "authorization_required"

    minute_path = Path(status["minute_root"]) / day[:4] / f"{day}.parquet"
    manifest = json.loads(minute_path.with_suffix(".source.json").read_text())
    received = len(manifest["present_codes"])
    requested = len(manifest["requested_codes"])
    empty_codes = manifest["empty_codes"]
    partial_count = sum(count != 240 for count in manifest["rows_per_code"].values())
    empty_summary = "、".join(empty_codes) if empty_codes else "无"
    body = "\n".join([
        f"中证1000一分钟行情已更新完成，交易日期 {day}。",
        "",
        f"目标股票 {requested} 只，有行情 {received} 只，覆盖率 {received / requested:.2%}。",
        f"分钟记录 {manifest['rows']:,} 行。",
        f"空数据股票 {len(empty_codes)} 只。",
        f"分钟记录少于或多于240根的股票 {partial_count} 只。",
        f"空数据股票代码 {empty_summary}。",
        "",
        "行情为未复权价格，成交量单位为股，成交额单位为人民币元。",
        f"工作站数据文件 {minute_path}",
        f"完成时间 {status['updated_at']}",
    ])
    message = EmailMessage()
    message["From"] = MAIL_ADDRESS
    message["To"] = MAIL_ADDRESS
    message["Subject"] = f"[量化工作站] 中证1000分钟线更新完成 {day}"
    message.set_content(body)
    with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=30, context=ssl.create_default_context()) as smtp:
        smtp.login(MAIL_ADDRESS, AUTHORIZATION_PATH.read_text().strip())
        smtp.send_message(message)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic({
        "date": day,
        "recipient": MAIL_ADDRESS,
        "sent_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
    }, receipt_path)
    LOGGER.info("完成邮件已发送至 %s", MAIL_ADDRESS)
    return "sent"
