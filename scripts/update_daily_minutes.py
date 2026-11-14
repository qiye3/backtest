"""收盘后保存中证1000当日成份快照，并增量下载一分钟行情。"""

from __future__ import annotations

import argparse
import io
import json
import logging
from dataclasses import asdict
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from curl_cffi import requests

from scripts.notify_minute_update import notify_minute_completion
from scripts.tencent_minutes import fetch_tencent_minutes
from src.intraday.data import _write_json_atomic
from src.intraday.free_minute import FreeMinuteDailyUpdater

MEMBERS_URL = (
    "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/"
    "file/autofile/cons/000852cons.xls"
)
LOGGER = logging.getLogger(__name__)


def create_session() -> requests.Session:
    return requests.Session(impersonate="chrome")


def save_member_snapshot(
    session: requests.Session, snapshot_root: Path, day: str,
) -> tuple[list[str], Path]:
    snapshot_root.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshot_root / f"{day}.json"
    if snapshot_path.exists():
        return json.loads(snapshot_path.read_text())["codes"], snapshot_path

    response = session.get(MEMBERS_URL, timeout=(10, 45))
    response.raise_for_status()
    members = pd.read_excel(io.BytesIO(response.content), dtype=str)
    markets = members["交易所Exchange"].map({"上海证券交易所": "SH", "深圳证券交易所": "SZ"})
    if markets.isna().any():
        raise ValueError("中证1000成份表出现未识别的交易所")
    codes = sorted((members["成份券代码Constituent Code"].str.zfill(6) + "." + markets).tolist())
    if len(codes) != 1000 or len(set(codes)) != 1000:
        raise ValueError(f"中证1000成份表股票数量异常 {len(codes)}")
    # 仅记录今日观测快照，不把当前名单回填成过去交易日的历史成份。
    _write_json_atomic({
        "index_code": "000852.SH",
        "observation_date": day,
        "observed_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "source": MEMBERS_URL,
        "source_dates": sorted(members["日期Date"].unique().tolist()),
        "codes": codes,
    }, snapshot_path)
    return codes, snapshot_path


def record_minute_completion(
    destination: Path, snapshot_path: Path, status_path: Path,
) -> None:
    manifest_path = destination.with_suffix(".source.json")
    manifest = json.loads(manifest_path.read_text())
    if "sources_by_code" not in manifest:
        manifest["sources_by_code"] = {
            code: manifest["source"] for code in manifest["present_codes"]
        }
    manifest["source"] = " + ".join(sorted(set(manifest["sources_by_code"].values())))
    manifest["constituents_snapshot"] = str(snapshot_path)
    manifest["rows_per_code"] = (
        pd.read_parquet(destination, columns=["code"])
        .groupby("code").size().astype(int).to_dict()
    )
    _write_json_atomic(manifest, manifest_path)
    status = {
        "status": "complete",
        "updated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "latest_date": destination.stem,
        "snapshot": str(snapshot_path),
        "minute_root": str(destination.parent.parent),
    }
    _write_json_atomic(status, status_path)
    status["mail_status"] = notify_minute_completion(status_path)
    _write_json_atomic(status, status_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minute-root", required=True, type=Path)
    parser.add_argument("--snapshot-root", required=True, type=Path)
    parser.add_argument("--status-path", required=True, type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    if now.weekday() >= 5 or now.time() < time(16):
        LOGGER.info("等待交易日收盘后的更新时段")
        return
    day = now.strftime("%Y-%m-%d")
    destination = args.minute_root / day[:4] / f"{day}.parquet"
    snapshot_path = args.snapshot_root / f"{day}.json"
    if destination.exists():
        # 先续发通知，再由 v4 增量下载逻辑重试当天空数据的股票。
        record_minute_completion(destination, snapshot_path, args.status_path)
        manifest = json.loads(destination.with_suffix(".source.json").read_text())
        if not manifest["empty_codes"]:
            return
    with create_session() as session:
        probe = fetch_tencent_minutes(session, "000001.SZ")
        latest_market_day = str(pd.to_datetime(probe["时间"]).max().date())
        if latest_market_day != day:
            LOGGER.info("行情最近交易日为 %s，今日跳过", latest_market_day)
            return
        codes, snapshot_path = save_member_snapshot(session, args.snapshot_root, day)
        LOGGER.info("股票池 %s，只数 %d", day, len(codes))

        def fetch_day(code: str, trading_date: object) -> pd.DataFrame:
            return fetch_tencent_minutes(session, code)

        updater = FreeMinuteDailyUpdater(args.minute_root, fetch_day, delay_seconds=0)
        checkpoint = args.minute_root / "_ingest_cache" / day
        # 空响应可由临时数据延迟导致，重试时重新请求这些股票。
        for empty_marker in checkpoint.glob("*.empty"):
            empty_marker.unlink()
        summary = updater.update_day(day, codes)
        LOGGER.info("日行情 %s", asdict(summary))
        record_minute_completion(Path(summary.path), snapshot_path, args.status_path)


if __name__ == "__main__":
    main()
