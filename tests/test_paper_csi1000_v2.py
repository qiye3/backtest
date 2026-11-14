"""中证1000动态成份、可配置执行时刻、免费分钟数据和跨日账户续跑。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from src.intraday.config import (
    AccountConfig, CostConfig, ExecutionConfig, MinuteBacktestConfig,
    MinuteDataConfig, TargetConfig, _derive_execution_window,
)
from src.intraday.engine import MinuteBacktestEngine
from src.intraday.free_minute import normalize_eastmoney_minute
from src.intraday.strategy import generate_daily_strategy_targets
from src.intraday.universe import HistoricalIndexUniverse


def _member_source(tmp_path: Path) -> Path:
    root = tmp_path / "index" / "members"
    root.mkdir(parents=True)
    pd.DataFrame([
        ("000001.SZ", "20250102", "20250106"),
        ("000002.SZ", "20250106", None),
    ], columns=["s_con_windcode", "s_con_indate", "s_con_outdate"]).to_csv(
        root / "000852.SH.csv", index=False,
    )
    return root


def _config() -> MinuteBacktestConfig:
    return MinuteBacktestConfig(
        path=Path("unused.yml"), run_name="csi1000", output_root=Path("runs"),
        data=MinuteDataConfig(
            minute_root=Path("data"), daily_root=None, cache_root=Path("cache"),
            universe_name="csi1000", start_date=pd.Timestamp("2025-01-02"),
            end_date=pd.Timestamp("2025-01-10"),
        ),
        targets=TargetConfig(path=Path("targets.csv"), date_only_signal_time="15:00:00"),
        account=AccountConfig(initial_capital=100_000),
        execution=ExecutionConfig(
            slippage_bps=0, max_participation_rate=1.0, block_one_price_limit=False,
            enforce_t_plus_one=True, order_time="13:20:00", window_start="13:21:00", window_end="13:25:00",
            retry_unfilled_days=5,
        ),
        costs=CostConfig(
            commission_rate=0, minimum_commission=0, transfer_fee_rate=0,
            stamp_duty_rate_before_20230828=0,
            stamp_duty_rate_from_20230828=0,
        ),
        raw={},
    )


def _bars(day: str, close: float) -> pd.DataFrame:
    return pd.DataFrame([{
        "timestamp": pd.Timestamp(f"{day} {clock}", tz="Asia/Shanghai"),
        "code": "000001.SZ", "open": close, "high": close + 0.2,
        "low": close - 0.2, "close": close,
        "vwap": close, "volume": 100_000, "amount": close * 100_000,
    } for clock in ("13:18", "13:19", "13:20", "13:21", "13:25", "15:00")])


def _targets() -> pd.DataFrame:
    return pd.DataFrame({
        "signal_timestamp": [pd.Timestamp("2025-01-02 15:00:00", tz="Asia/Shanghai")],
        "code": ["000001.SZ"], "target_weight": [0.5],
    })


def test_history_membership_changes_and_exit_is_still_tradable(tmp_path) -> None:
    uni = HistoricalIndexUniverse(_member_source(tmp_path))
    assert uni.codes_on("2025-01-02") == ("000001.SZ",)
    assert uni.codes_on("2025-01-06") == ("000002.SZ",)
    assert uni.codes_between("2025-01-02", "2025-01-07") == (
        "000001.SZ", "000002.SZ",
    )
    assert "000001.SZ" in uni.execution_codes("2025-01-07", ["000001.SZ"])
    valid = pd.DataFrame({
        "signal_timestamp": [pd.Timestamp("2025-01-02 15:00", tz="Asia/Shanghai")],
        "code": ["000001.SZ"], "target_weight": [0.5],
    })
    uni.validate_targets(valid)
    with pytest.raises(ValueError, match="非当日中证1000"):
        uni.validate_targets(valid.assign(
            signal_timestamp=pd.Timestamp("2025-01-06 15:00", tz="Asia/Shanghai")
        ))
    uni.validate_targets(valid.assign(
        signal_timestamp=pd.Timestamp("2025-01-06 15:00", tz="Asia/Shanghai"),
        target_weight=0.0,
    ))


def test_order_time_does_not_need_to_be_ten_oclock() -> None:
    assert _derive_execution_window("13:20:00", 5) == ("13:21:00", "13:25:00")
    # 午休跳过：11:29 之后是 11:30、13:01、13:02
    assert _derive_execution_window("11:29:00", 3) == ("11:30:00", "13:02:00")
    with pytest.raises(ValueError):
        _derive_execution_window("12:00:00", 5)
    result = MinuteBacktestEngine(_config()).run_stream(
        [_bars("2025-01-02", 10), _bars("2025-01-03", 10)], _targets(),
    )
    assert result.orders.iloc[0]["created_at"] == pd.Timestamp(
        "2025-01-03 13:20", tz="Asia/Shanghai"
    )
    assert result.fills.iloc[0]["timestamp"] == pd.Timestamp(
        "2025-01-03 13:21", tz="Asia/Shanghai"
    )


def test_account_restoration_matches_full_stream() -> None:
    config = _config()
    days = [_bars("2025-01-02", 10), _bars("2025-01-03", 10), _bars("2025-01-06", 11)]
    targets = _targets()
    batch = MinuteBacktestEngine(config).run_stream(days, targets)
    first = MinuteBacktestEngine(config)
    first.run_stream(days[:2], targets)
    state = first.export_state()
    assert state["previous_date"] == "2025-01-03"
    assert state["last_applied_signal_timestamp"].startswith("2025-01-02")
    resumed = MinuteBacktestEngine(config)
    resumed.import_state(state)
    second = resumed.run_stream([days[2]], targets)
    assert resumed.cash == pytest.approx(batch.nav.iloc[-1]["cash"])
    assert resumed.positions["000001.SZ"].shares == 5_000
    assert second.orders.empty and second.fills.empty
    assert second.nav.iloc[-1]["nav"] == pytest.approx(batch.nav.iloc[-1]["nav"])


def test_retried_target_does_not_reset_after_restoring() -> None:
    config = _config()
    a = _bars("2025-01-03", 10)
    a.loc[a["timestamp"].dt.strftime("%H:%M") == "13:21", "volume"] = 0
    a.loc[a["timestamp"].dt.strftime("%H:%M") == "13:25", "volume"] = 0
    a.loc[a["timestamp"].dt.strftime("%H:%M") == "13:21", "amount"] = 0
    a.loc[a["timestamp"].dt.strftime("%H:%M") == "13:25", "amount"] = 0
    first = MinuteBacktestEngine(config)
    first.run_stream([_bars("2025-01-02", 10), a], _targets())
    assert "000001.SZ" in first.export_state()["pending_target_codes"]
    restored = MinuteBacktestEngine(config)
    restored.import_state(first.export_state())
    result = restored.run_stream([_bars("2025-01-06", 10)], _targets())
    assert len(result.fills) == 1
    assert restored.export_state()["retry_days_used"] == 1


def test_eastmoney_one_minute_volumes_are_in_shares_and_vwap_is_per_bar() -> None:
    raw = pd.DataFrame({
        "时间": ["2025-01-02 09:30:00", "2025-01-02 09:31:00", "2025-01-02 09:32:00"],
        "开盘": [10, 0, 0], "最高": [10, 10, 10.2], "最低": [10, 10, 10],
        "收盘": [10, 10, 10.2], "成交量": [1, 2, 3],
        "成交额": [1000.0, 2000.0, 3030.0],
        "均价": [10, 10, 10.06],
    })
    out = normalize_eastmoney_minute(raw, "000001.SZ", "2025-01-02")
    assert out["timestamp"].dt.strftime("%H:%M").tolist() == ["09:31", "09:32"]
    assert out["volume"].tolist() == [200, 300]
    assert out["vwap"].tolist() == [10.0, 10.1]
    assert (out["open"] > 0).all()


def test_daily_strategy_uses_active_historical_members() -> None:
    class MockStrategy:
        def on_day_close(self, trading_date, bars, context):
            assert set(bars["code"]) == set(context.universe_codes)
            return pd.DataFrame({"code": [context.universe_codes[0]], "target_weight": [1.0]})

    bars = []
    for day in ("2025-01-02", "2025-01-06"):
        frame = _bars(day, 10)
        other = frame.assign(code="000002.SZ")
        bars.append(pd.concat([frame, other]))
    targets = generate_daily_strategy_targets(
        MockStrategy(), bars, ["000001.SZ", "000002.SZ"],
        universe_for_date=lambda day: ["000001.SZ"] if day.day == 2 else ["000002.SZ"],
    )
    assert targets["code"].tolist() == ["000001.SZ", "000002.SZ"]


def test_daily_incremental_update_resumes_and_paper_account_is_idempotent(
    tmp_path, monkeypatch,
) -> None:
    """在无 pyarrow 的测试环境用 pickle 后端运行完整调度逻辑；生产仍用 Parquet。"""
    import json
    from src.intraday import data as data_module
    from src.intraday import free_minute
    from src.intraday.config import UniverseConfig
    from src.intraday.paper import run_paper_day

    def fake_write(frame, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_pickle(path)

    def fake_read(path, *, columns=None, filters=None, **_kwargs):
        frame = pd.read_pickle(path)
        if filters:
            for name, operator, values in filters:
                if operator == "in":
                    frame = frame[frame[name].isin(values)]
        return frame[list(columns)].copy() if columns else frame.copy()

    monkeypatch.setattr(data_module, "_write_parquet_atomic", fake_write)
    monkeypatch.setattr(free_minute, "_write_parquet_atomic", fake_write)
    monkeypatch.setattr(pd, "read_parquet", fake_read)
    monkeypatch.setattr(pd.DataFrame, "to_parquet", lambda frame, path, **kwargs: fake_write(frame, path))

    target_path = tmp_path / "targets.csv"
    _targets().to_csv(target_path, index=False)
    members = _member_source(tmp_path)
    config = _config()
    config = replace(
        config, path=tmp_path / "config.yml", run_name="daily_paper_csi1000",
        output_root=tmp_path / "runs",
        universe=UniverseConfig(members_root=members),
        data=replace(
            config.data, minute_root=tmp_path / "minute", cache_root=tmp_path / "cache",
            start_date=pd.Timestamp("2025-01-02"), end_date=pd.Timestamp("2025-01-06"),
        ),
        targets=replace(config.targets, path=target_path),
    )
    calls = []

    def fake_fetch(code, date):
        calls.append((code, str(date.date())))
        return pd.DataFrame({
            "时间": [f"{date:%Y-%m-%d} {clock}" for clock in (
                "09:31:00", "13:19:00", "13:20:00", "13:21:00",
                "13:22:00", "13:23:00", "13:24:00", "13:25:00", "15:00:00",
            )],
            "开盘": [10] * 9, "最高": [10.2] * 9,
            "最低": [9.8] * 9, "收盘": [10] * 9,
            "成交量": [1000] * 9, "成交额": [1_000_000.0] * 9,
        })

    # 单次失败后已有下载缓存保留，再次执行时不会重复下载已缓存股票。
    original_fetcher = free_minute.fetch_eastmoney_1min
    monkeypatch.setattr(free_minute, "fetch_eastmoney_1min", fake_fetch)
    # __init__ 默认参数在定义时已经绑定，因此直接替换所创建类的构造器默认值。
    original_init = free_minute.FreeMinuteDailyUpdater.__init__
    def init_patched(self, minute_root, fetcher=None, **kwargs):
        original_init(self, minute_root, fake_fetch if fetcher is None else fetcher, **kwargs)
    monkeypatch.setattr(free_minute.FreeMinuteDailyUpdater, "__init__", init_patched)

    day_one = run_paper_day(config, "2025-01-02", delay_seconds=0)
    assert (day_one / "snapshot.json").exists()
    assert json.loads((day_one / "snapshot.json").read_text())["end_nav"] == 100_000
    day_two = run_paper_day(config, "2025-01-03", delay_seconds=0)
    restored = json.loads((day_two / "snapshot.json").read_text())
    assert restored["state"]["positions"]["000001.SZ"]["shares"] == 5_000
    assert restored["state"]["previous_date"] == "2025-01-03"
    assert pd.read_pickle(day_two / "fills.parquet")["shares"].tolist() == [5_000]
    with pytest.raises(FileExistsError, match="拒绝重复记账"):
        run_paper_day(config, "2025-01-03", delay_seconds=0)
    assert calls == [("000001.SZ", "2025-01-02"), ("000001.SZ", "2025-01-03")]


def test_yaml_paper_example_supports_one_field_execution_time(tmp_path) -> None:
    import yaml
    from src.intraday.config import load_minute_config

    members = _member_source(tmp_path)
    for directory in ("minute", "daily", "cache"):
        (tmp_path / directory).mkdir()
    target_file = tmp_path / "targets.csv"
    _targets().to_csv(target_file, index=False)
    example = Path("configs/paper_csi1000.example.yaml")
    yaml_dict = yaml.safe_load(example.read_text(encoding="utf-8"))
    yaml_dict["universe"]["members_root"] = str(members)
    yaml_dict["data"]["minute_root"] = str(tmp_path / "minute")
    yaml_dict["data"]["daily_root"] = str(tmp_path / "daily")
    yaml_dict["data"]["cache_root"] = str(tmp_path / "cache")
    yaml_dict["targets"]["path"] = str(target_file)
    yaml_dict["output_root"] = str(tmp_path / "results")
    yaml_dict["execution"]["order_time"] = "10:42:00"
    config_file = tmp_path / "paper.yml"
    config_file.write_text(yaml.safe_dump(yaml_dict), encoding="utf-8")
    config = load_minute_config(config_file)
    assert config.universe.index_code == "000852.SH"
    assert config.execution.order_time == "10:42:00"
    assert config.execution.window_start == "10:43:00"
    assert config.execution.window_end == "10:47:00"


def test_free_minute_download_uses_checkpoint_after_error(tmp_path, monkeypatch) -> None:
    from src.intraday import free_minute
    monkeypatch.setattr(free_minute, "_write_parquet_atomic", lambda frame, path: frame.to_pickle(path))
    monkeypatch.setattr(pd, "read_parquet", lambda path, **kwargs: pd.read_pickle(path))
    counter = {"000001.SZ": 0, "000002.SZ": 0}
    fail_once = {"000002.SZ": True}

    def fetcher(code, date):
        counter[code] += 1
        if fail_once.get(code):
            fail_once[code] = False
            raise ConnectionError("模拟限流，须保留已下载数据")
        return pd.DataFrame({
            "时间": ["2025-01-02 09:31:00"], "开盘": [10],
            "最高": [10], "最低": [10], "收盘": [10],
            "成交量": [1], "成交额": [1000],
        })

    updater = free_minute.FreeMinuteDailyUpdater(
        tmp_path, fetcher, delay_seconds=0, min_coverage=1.0,
    )
    with pytest.raises(ConnectionError):
        updater.update_day("2025-01-02", ["000001.SZ", "000002.SZ"])
    assert (tmp_path / "_ingest_cache" / "2025-01-02" / "000001.SZ.parquet").exists()
    done = updater.update_day("2025-01-02", ["000001.SZ", "000002.SZ"])
    assert done.received_codes == 2
    assert done.rows == 2
    assert counter == {"000001.SZ": 1, "000002.SZ": 2}
    assert not (tmp_path / "_ingest_cache" / "2025-01-02").exists()


def test_strategy_output_adapter_reads_sparse_targets_and_cash_only_date(tmp_path) -> None:
    from src.intraday.targets import load_strategy_output_targets

    path = tmp_path / "strategy_targets.csv"
    pd.DataFrame({
        "date": ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-02"],
        "stock_code": ["000001.SZ", None, "000002.SZ", "000003.SZ"],
        "target_weight": [0.5, 0.0, 0.5, 0.75],
        "rebalance_interval": [1, 1, 1, 4],
        "factor_name": ["test"] * 4,
        "rebalance_frequency": ["weekly"] * 4,
    }).to_csv(path, index=False)
    result = load_strategy_output_targets(path, 1)
    assert result["code"].tolist() == ["000001.SZ", "000001.SZ", "000002.SZ"]
    assert result["target_weight"].tolist() == [0.5, 0.0, 0.5]
    assert result["signal_timestamp"].dt.strftime("%Y-%m-%d").tolist() == [
        "2025-01-02", "2025-01-03", "2025-01-06",
    ]
