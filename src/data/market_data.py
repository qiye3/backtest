"""
通过 YAML 构建和复用指数增强研究所需的日频市场数据。

本模块是数据层面向 Factors 和回测模块的公共入口。``MarketData.from_yaml`` 按顺序
建立基准交易日历、中证800与中证1000历史成员并集以及配置点名的来源数据，并把每个
来源保存为独立 Parquet。``get_panel`` 读取标准二维面板，``get_records`` 读取不能
无损透视的明细长表；本模块不计算因子、不决定调仓频率，也不搜索配置之外的数据路径。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd
import yaml

from src.data.cache import (
    load_financial_records,
    load_source_data,
    load_source_metadata,
    resolve_market_cache_directory,
    save_financial_records,
    save_source_cache,
)
from src.data.calendar import build_trading_calendar
from src.data.load_data import DATA_SOURCE_SPECS, load_data, load_index_members
from src.data.process_data import build_membership_panel, build_source_panel

MEMBERSHIP_SOURCE = "index_membership"
REQUIRED_UNIVERSE_INDICES = {"000906.SH", "000852.SH"}
CACHE_FORMAT_VERSION = 2
MARKET_UPDATE_STATE = ".state/market_update.json"


def _load_market_revision(cache_directory: Path) -> int:
    """读取独立更新命令发布的市场版本；普通旧缓存使用版本零。"""
    state_path = cache_directory / MARKET_UPDATE_STATE
    if not state_path.exists():
        return 0
    state = json.loads(state_path.read_text(encoding="utf-8"))
    return int(state["revision"])


class MarketData:
    """
    保存已完成规范化的市场数据。

    输入：
    - source_panels：按标准来源名组织的日频面板或明细长表。
    - calendar：由基准指数行情确定的交易日日历。
    - membership：中证800与中证1000逐日历史成份并集。
    - benchmark_index：回测基准指数 Wind 代码。
    - cache_directory：来源缓存和全周期派生缓存共用的目录；内存测试可省略。
    - financial_records：按真实公告日保留全部报告期版本的财务事件。

    输出：
    - 该类实例向下游公开 ``calendar``、``membership``、``benchmark_index`` 和
      ``get_panel``、``get_records``，不直接暴露缓存构建状态。

    功能和用途：
    - 作为 Factors、分组评价和回测共同使用的数据容器。
    - 构造器只保存已经完成的数据；文件读取和缓存写入由 ``from_yaml`` 负责。
    """

    # 保存已经完成规范化的来源数据和公共时间、股票池信息。
    def __init__(
        self,
        source_panels: Mapping[str, pd.DataFrame],
        calendar: pd.DatetimeIndex,
        membership: pd.DataFrame,
        benchmark_index: str,
        cache_directory: Path | None = None,
        financial_records: Mapping[str, pd.DataFrame] | None = None,
        revision: int = 0,
    ) -> None:
        """
        初始化可供下游直接读取的市场数据对象。

        输入：
        - source_panels：来源名到完整缓存面板或明细长表的映射。
        - calendar：所有来源共享的交易日索引。
        - membership：日期乘股票的布尔研究股票池。
        - benchmark_index：用于构造日历和回测对照的基准指数代码。
        - cache_directory：共享市场缓存目录；为空时派生数据只在内存中计算。
        - financial_records：财务来源名到规范化公告事件长表的映射。

        输出：
        - 无返回值；参数保存为实例状态。

        功能和用途：
        - 保持对象初始化无磁盘副作用，使测试可以直接用内存面板构造实例。
        - 来源数据保存在私有映射中，避免下游绕过标准读取接口依赖内部结构。
        """
        self._source_panels = dict(source_panels)
        self.calendar = calendar
        self.membership = membership
        self.benchmark_index = benchmark_index
        self.cache_directory = cache_directory
        self._financial_records = dict(financial_records or {})
        self.revision = revision

    # 根据 YAML 配置读取缓存或构建完整市场数据对象。
    @classmethod
    def from_yaml(
        cls,
        config_path: str | Path,
        refresh: bool = False,
        market_data_config: Mapping[str, Any] | None = None,
        refresh_sources: Sequence[str] = (),
        incremental_from: pd.Timestamp | None = None,
    ) -> MarketData:
        """
        从 YAML 构建或复用市场数据面板。

        输入：
        - config_path：包含 ``market_data`` 分区的 YAML 路径。
        - refresh：为假时优先复用已有来源 Parquet；为真时从原始 CSV 重建并覆盖。
        - market_data_config：已由主配置器补全的数据分区；直接调用时可省略。
        - refresh_sources：只强制重建这些发生原始文件变化的来源。
        - incremental_from：原始年度文件变化的最早日期；日频来源仅重建该日起的尾部。

        输出：
        - 返回包含交易日历、历史股票池和全部配置来源的 ``MarketData``。

        功能和用途：
        - 先构建指数行情以确定唯一交易日日历，再构建历史成员和股票列范围。
        - 之后逐个来源执行缓存读取；面板来源完成日频对齐，明细来源保留长表。
        - 原始数据、缓存路径、日期、来源与字段全部由 YAML 决定。
        """
        resolved_config_path = Path(config_path).expanduser().resolve()
        if market_data_config is None:
            resolved_market_data_config = _read_market_data_config(resolved_config_path)
        else:
            resolved_market_data_config = dict(market_data_config)
            _validate_market_data_config(resolved_market_data_config)
        cache_directory = resolve_market_cache_directory(
            resolved_config_path,
            resolved_market_data_config["cache_root"],
        )
        data_root = Path(resolved_market_data_config["source_root"]).expanduser()
        if not data_root.is_absolute():
            data_root = resolved_config_path.parent / data_root
        data_root = data_root.resolve()
        start_date = pd.Timestamp(resolved_market_data_config["start_date"])
        end_date = pd.Timestamp(resolved_market_data_config["end_date"])
        benchmark_index = str(resolved_market_data_config["benchmark_index"])
        universe_indices = tuple(
            str(index_code) for index_code in resolved_market_data_config["universe_indices"]
        )
        source_configs = resolved_market_data_config["sources"]
        sources_to_refresh = set(refresh_sources)

        index_price_panel, index_price_metadata = _load_index_price_panel(
            data_root=data_root,
            cache_directory=cache_directory,
            source_config=source_configs["index_price"],
            benchmark_index=benchmark_index,
            universe_indices=universe_indices,
            start_date=start_date,
            end_date=end_date,
            refresh=refresh or "index_price" in sources_to_refresh,
            incremental_from=(
                incremental_from
                if "index_price" in sources_to_refresh and not refresh
                else None
            ),
        )
        shared_calendar = pd.DatetimeIndex(index_price_panel.index, name="date")
        membership_panel, universe_codes = _load_membership_panel(
            data_root=data_root,
            cache_directory=cache_directory,
            universe_indices=universe_indices,
            trading_calendar=shared_calendar,
            start_date=pd.Timestamp(index_price_metadata["start_date"]),
            end_date=pd.Timestamp(index_price_metadata["end_date"]),
            refresh=refresh or MEMBERSHIP_SOURCE in sources_to_refresh,
        )

        source_panels = {
            "index_price": index_price_panel,
            MEMBERSHIP_SOURCE: membership_panel,
        }
        financial_records = {}
        for source_name, source_config in source_configs.items():
            if source_name == "index_price":
                continue
            source_data, source_financial_records = _load_or_build_source_data(
                data_root=data_root,
                cache_directory=cache_directory,
                source_name=source_name,
                source_config=source_config,
                start_date=start_date,
                end_date=end_date,
                trading_calendar=shared_calendar,
                universe_codes=universe_codes,
                universe_indices=universe_indices,
                refresh=refresh or source_name in sources_to_refresh,
                incremental_from=(
                    incremental_from
                    if source_name in sources_to_refresh and not refresh
                    else None
                ),
            )
            source_panels[source_name] = source_data
            if source_financial_records is not None:
                financial_records[source_name] = source_financial_records

        trading_calendar = shared_calendar[
            (shared_calendar >= start_date) & (shared_calendar <= end_date)
        ]
        requested_source_configs = dict(source_configs)
        requested_source_configs[MEMBERSHIP_SOURCE] = {
            "fields": ["membership"],
            "codes": universe_indices,
        }
        source_panels = {
            source_name: _slice_source_data(
                source_name=source_name,
                source_data=source_data,
                source_config=requested_source_configs[source_name],
                trading_calendar=trading_calendar,
                start_date=start_date,
                end_date=end_date,
            )
            for source_name, source_data in source_panels.items()
        }
        financial_records = {
            source_name: _slice_financial_records(
                source_records=source_records,
                source_config=source_configs[source_name],
                start_date=start_date,
                end_date=end_date,
            )
            for source_name, source_records in financial_records.items()
        }
        membership = _merge_universe_membership(
            source_panels[MEMBERSHIP_SOURCE],
            universe_codes,
        )

        return cls(
            source_panels=source_panels,
            calendar=trading_calendar,
            membership=membership,
            benchmark_index=benchmark_index,
            cache_directory=cache_directory,
            financial_records=financial_records,
            revision=_load_market_revision(cache_directory),
        )

    # 从来源缓存中切出指定字段的标准二维面板。
    def get_panel(
        self,
        source_name: str,
        field_name: str,
        index_code: str | None = None,
        forecast_year_offset: int | None = None,
    ) -> pd.DataFrame:
        """
        获取 Factors 或回测需要的单字段面板。

        输入：
        - source_name：已配置的数据来源名，例如 ``stock_quote``。
        - field_name：来源内的字段名，例如 ``S_DQ_ADJCLOSE``；历史成员使用
          ``membership``。
        - index_code：指数权重或指数成员来源必须指定的指数代码；普通来源省略。
        - forecast_year_offset：多期限一致预期来源必须指定的预测年度偏移。

        输出：
        - 返回索引为 ``calendar``、列为股票或指数代码的二维 DataFrame。

        功能和用途：
        - 先选择来源级 MultiIndex 的 ``field`` 层，再按需选择 ``index_code`` 层。
        - 下游不需要了解每来源一个 Parquet 的内部列组织方式。
        """
        if source_name != MEMBERSHIP_SOURCE and DATA_SOURCE_SPECS[source_name].kind == "records":
            raise ValueError(f"明细来源应使用 get_records: {source_name}")
        source_panel = self._source_panels[source_name]
        field_panel = source_panel.xs(
            field_name,
            axis=1,
            level="field",
            drop_level=True,
        )
        if "index_code" in field_panel.columns.names:
            if index_code is None:
                raise ValueError(f"该来源必须指定 index_code: {source_name}")
            field_panel = field_panel.xs(
                index_code,
                axis=1,
                level="index_code",
                drop_level=True,
            )
        elif index_code is not None:
            raise ValueError(f"该来源不使用 index_code: {source_name}")
        if "forecast_year_offset" in field_panel.columns.names:
            if forecast_year_offset is None:
                raise ValueError(f"该来源必须指定 forecast_year_offset: {source_name}")
            field_panel = field_panel.xs(
                forecast_year_offset,
                axis=1,
                level="forecast_year_offset",
                drop_level=True,
            )
        elif forecast_year_offset is not None:
            raise ValueError(f"该来源不使用 forecast_year_offset: {source_name}")
        return field_panel

    def get_records(self, source_name: str) -> pd.DataFrame:
        """
        获取不能无损转换为二维面板的来源明细。

        输入：
        - source_name：YAML 已配置且类型为 ``records`` 的标准来源名。

        输出：
        - 返回已按配置日期、历史股票池和字段裁剪的长表。
        - 可用标准键包括 ``asset_code``、``source_date`` 和 ``report_period``。

        功能和用途：
        - 保留同一股票、同一日期的全部业务记录，供 Factor 按自身口径聚合。
        - ``source_date`` 仅表示来源原始日期，不自动解释为无前视的可得日。
        """
        if DATA_SOURCE_SPECS[source_name].kind != "records":
            raise ValueError(f"面板来源应使用 get_panel: {source_name}")
        return self._source_panels[source_name]

    def get_financial_records(self, source_name: str) -> pd.DataFrame:
        """返回按真实公告日规范化且保留全部报告期版本的财务事件。"""
        if DATA_SOURCE_SPECS[source_name].kind != "financial":
            raise ValueError(f"该来源不是财务来源: {source_name}")
        return self._financial_records[source_name]

    def window(self, start_date: pd.Timestamp) -> MarketData:
        """构造共享底层数组的尾部只读视图，供有界历史因子增量计算。"""
        window_calendar = self.calendar[self.calendar >= start_date]
        source_panels = {}
        for source_name, source_data in self._source_panels.items():
            if source_name in DATA_SOURCE_SPECS:
                if DATA_SOURCE_SPECS[source_name].kind == "records":
                    source_panels[source_name] = source_data
                    continue
            source_panels[source_name] = source_data.loc[window_calendar]
        return MarketData(
            source_panels=source_panels,
            calendar=window_calendar,
            membership=self.membership.loc[window_calendar],
            benchmark_index=self.benchmark_index,
            cache_directory=self.cache_directory,
            financial_records=self._financial_records,
            revision=self.revision,
        )


# ===================== YAML 配置边界 ===================== #


# 读取并校验构建 MarketData 必需的配置内容。
def _read_market_data_config(config_path: Path) -> dict[str, Any]:
    """
    读取 YAML 中的数据层配置。

    输入：
    - config_path：实际存在的 YAML 文件路径。

    输出：
    - 返回 ``market_data`` 分区的普通字典。

    功能和用途：
    - 在文件输入边界检查数据根、日期、基准、股票池和来源字段这些必要不变量。
    - 只接受当前项目定义的一种配置结构，不兼容旧字段名或其他配置层级。
    """
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    market_data_config = config["market_data"]
    _validate_market_data_config(market_data_config)
    return market_data_config


# 对会改变数据口径的必要配置执行一次集中校验。
def _validate_market_data_config(market_data_config: Mapping[str, Any]) -> None:
    """
    校验 MarketData 构建需要的配置不变量。

    输入：
    - market_data_config：YAML 的 ``market_data`` 映射。

    输出：
    - 无返回值；配置违反明确约束时抛出 ``ValueError`` 或 ``KeyError``。

    功能和用途：
    - 确认日期顺序、中证800与中证1000股票池、必要价格字段和指数代码完整。
    - 确认每个来源属于固定来源表并声明非空字段；一致预期必须明确年度偏移。
    """
    required_keys = {
        "source_root",
        "cache_root",
        "start_date",
        "end_date",
        "benchmark_index",
        "universe_indices",
        "sources",
    }
    missing_keys = required_keys - market_data_config.keys()
    if missing_keys:
        raise KeyError(f"market_data 缺少配置项: {sorted(missing_keys)}")

    start_date = pd.Timestamp(market_data_config["start_date"])
    end_date = pd.Timestamp(market_data_config["end_date"])
    if start_date > end_date:
        raise ValueError("market_data.start_date 不能晚于 end_date")

    universe_indices = {str(index_code) for index_code in market_data_config["universe_indices"]}
    if universe_indices != REQUIRED_UNIVERSE_INDICES:
        raise ValueError("universe_indices 必须是 000906.SH 与 000852.SH")

    source_configs = market_data_config["sources"]
    stock_quote_fields = source_configs["stock_quote"]["fields"]
    if "S_DQ_ADJCLOSE" not in stock_quote_fields:
        raise ValueError("stock_quote 必须包含 S_DQ_ADJCLOSE")

    index_price_config = source_configs["index_price"]
    if "S_DQ_CLOSE" not in index_price_config["fields"]:
        raise ValueError("index_price 必须包含 S_DQ_CLOSE")
    benchmark_index = str(market_data_config["benchmark_index"])
    index_price_codes = {str(index_code) for index_code in index_price_config["codes"]}
    if benchmark_index not in index_price_codes:
        raise ValueError("index_price.codes 必须包含 benchmark_index")

    for source_name, source_config in source_configs.items():
        if source_name not in DATA_SOURCE_SPECS:
            raise ValueError(f"未知 market_data 数据源: {source_name}")
        if not source_config["fields"]:
            raise ValueError(f"数据源 fields 不能为空: {source_name}")
        source_spec = DATA_SOURCE_SPECS[source_name]
        if source_spec.index_files and not source_config["codes"]:
            raise ValueError(f"指数来源必须配置 codes: {source_name}")
        if source_spec.forecast_period_column is not None:
            forecast_keys = {
                "forecast_year_offset",
                "forecast_year_offsets",
            } & source_config.keys()
            if len(forecast_keys) != 1:
                raise ValueError(
                    "一致预期来源必须配置一个 forecast_year_offset 或 "
                    f"forecast_year_offsets: {source_name}"
                )
            if "forecast_year_offsets" in source_config:
                forecast_offsets = source_config["forecast_year_offsets"]
                if (
                    not isinstance(forecast_offsets, list)
                    or not forecast_offsets
                    or len(forecast_offsets) != len(set(forecast_offsets))
                    or any(not isinstance(offset, int) for offset in forecast_offsets)
                ):
                    raise ValueError(
                        f"forecast_year_offsets 必须是非空且不重复的整数列表: {source_name}"
                    )


# ===================== 共享缓存请求 ===================== #

SEMANTIC_METADATA_KEYS = (
    "cache_format_version",
    "source_root",
    "universe_indices",
    "filters",
)


def _source_metadata(
    data_root: Path,
    source_config: Mapping[str, Any],
    universe_indices: Sequence[str],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> dict[str, Any]:
    """把会影响来源缓存内容的配置规范为可持久化 metadata。"""
    filters = {
        str(filter_name): str(filter_value)
        for filter_name, filter_value in sorted(source_config.get("filters", {}).items())
    }
    forecast_year_offsets = _configured_forecast_offsets(source_config)

    return {
        "cache_format_version": CACHE_FORMAT_VERSION,
        "source_root": str(data_root),
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "fields": list(dict.fromkeys(str(field) for field in source_config["fields"])),
        "codes": list(dict.fromkeys(str(code) for code in source_config.get("codes", ()))),
        "universe_indices": sorted(str(code) for code in universe_indices),
        "filters": filters,
        "forecast_year_offsets": forecast_year_offsets,
    }


def _configured_forecast_offsets(
    source_config: Mapping[str, Any],
) -> list[int] | None:
    """把新旧一致预期配置统一为缓存使用的期限列表。"""
    forecast_year_offsets = source_config.get("forecast_year_offsets")
    if forecast_year_offsets is not None:
        return [int(offset) for offset in forecast_year_offsets]
    forecast_year_offset = source_config.get("forecast_year_offset")
    if forecast_year_offset is not None:
        return [int(forecast_year_offset)]
    return None


def _prepare_source_cache(
    cache_directory: Path,
    source_name: str,
    requested_metadata: Mapping[str, Any],
    refresh: bool,
) -> tuple[pd.DataFrame | None, dict[str, Any], bool]:
    """判断来源缓存是否命中，并生成必要重建时使用的并集范围。"""
    cached_metadata = load_source_metadata(cache_directory, source_name)
    if cached_metadata is None:
        return None, dict(requested_metadata), True

    if cached_metadata.get("cache_format_version") != CACHE_FORMAT_VERSION:
        return None, dict(requested_metadata), True

    semantic_conflicts = [
        key for key in SEMANTIC_METADATA_KEYS if cached_metadata.get(key) != requested_metadata[key]
    ]
    if semantic_conflicts:
        if refresh:
            return None, dict(requested_metadata), True
        conflict_names = ", ".join(semantic_conflicts)
        raise ValueError(f"共享缓存来源口径不一致: {source_name}: {conflict_names}")

    build_metadata = dict(requested_metadata)
    build_start = min(
        pd.Timestamp(cached_metadata["start_date"]),
        pd.Timestamp(requested_metadata["start_date"]),
    )
    build_end = max(
        pd.Timestamp(cached_metadata["end_date"]),
        pd.Timestamp(requested_metadata["end_date"]),
    )
    build_metadata["start_date"] = build_start.strftime("%Y-%m-%d")
    build_metadata["end_date"] = build_end.strftime("%Y-%m-%d")
    for collection_name in ("fields", "codes"):
        build_metadata[collection_name] = list(
            dict.fromkeys(
                [
                    *cached_metadata[collection_name],
                    *requested_metadata[collection_name],
                ]
            )
        )

    cached_offsets = _configured_forecast_offsets(cached_metadata)
    requested_offsets = _configured_forecast_offsets(requested_metadata)
    if requested_offsets is not None:
        build_metadata["forecast_year_offsets"] = list(
            dict.fromkeys([*(cached_offsets or []), *requested_offsets])
        )

    needs_expansion = any(
        build_metadata[key] != cached_metadata[key]
        for key in ("start_date", "end_date", "fields", "codes")
    )
    needs_expansion |= (
        requested_offsets is not None and build_metadata["forecast_year_offsets"] != cached_offsets
    )
    rebuild = refresh or needs_expansion
    if rebuild:
        return None, build_metadata, True
    cached_data = load_source_data(cache_directory, source_name)
    return cached_data, build_metadata, False


def _build_source_config(
    source_config: Mapping[str, Any],
    build_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """用缓存并集字段和代码生成一次原始数据读取配置。"""
    build_config = dict(source_config)
    build_config["fields"] = build_metadata["fields"]
    if build_metadata["codes"]:
        build_config["codes"] = build_metadata["codes"]
    forecast_year_offsets = build_metadata.get("forecast_year_offsets")
    if forecast_year_offsets is not None:
        build_config.pop("forecast_year_offset", None)
        build_config["forecast_year_offsets"] = forecast_year_offsets
    return build_config


# ===================== 基准日历和历史股票池 ===================== #


def _load_index_price_panel(
    data_root: Path,
    cache_directory: Path,
    source_config: Mapping[str, Any],
    benchmark_index: str,
    universe_indices: Sequence[str],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    refresh: bool,
    incremental_from: pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """读取共享指数行情，必要时按新旧请求的并集重建。"""
    requested_metadata = _source_metadata(
        data_root=data_root,
        source_config=source_config,
        universe_indices=universe_indices,
        start_date=start_date,
        end_date=end_date,
    )
    cached_panel, build_metadata, rebuild = _prepare_source_cache(
        cache_directory=cache_directory,
        source_name="index_price",
        requested_metadata=requested_metadata,
        refresh=refresh,
    )
    if not rebuild:
        return cached_panel, build_metadata

    cached_panel = _incremental_daily_cache(
        cache_directory,
        "index_price",
        build_metadata,
        incremental_from,
    )
    build_config = _build_source_config(source_config, build_metadata)
    build_start = pd.Timestamp(build_metadata["start_date"])
    build_end = pd.Timestamp(build_metadata["end_date"])
    read_start = incremental_from if cached_panel is not None else build_start
    index_records = load_data(
        data_root=data_root,
        source_name="index_price",
        source_config=build_config,
        start_date=read_start,
        end_date=build_end,
        universe_codes=(),
    )
    trading_calendar = build_trading_calendar(
        index_records=index_records,
        benchmark_index=benchmark_index,
        start_date=read_start,
        end_date=build_end,
    )
    index_price_panel = build_source_panel(
        source_name="index_price",
        source_data=index_records,
        source_fields=build_config["fields"],
        trading_calendar=trading_calendar,
        asset_codes=build_config["codes"],
    )
    if cached_panel is not None:
        index_price_panel = _merge_daily_panel_tail(
            cached_panel,
            index_price_panel,
            read_start,
        )
    save_source_cache(
        cache_directory,
        "index_price",
        index_price_panel,
        build_metadata,
    )
    return index_price_panel, build_metadata


def _load_membership_panel(
    data_root: Path,
    cache_directory: Path,
    universe_indices: Sequence[str],
    trading_calendar: pd.DatetimeIndex,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    refresh: bool,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    """读取或重建覆盖共享交易日历的指数历史成员面板。"""
    source_config = {
        "fields": ["membership"],
        "codes": list(universe_indices),
    }
    requested_metadata = _source_metadata(
        data_root=data_root,
        source_config=source_config,
        universe_indices=universe_indices,
        start_date=start_date,
        end_date=end_date,
    )
    cached_panel, build_metadata, rebuild = _prepare_source_cache(
        cache_directory=cache_directory,
        source_name=MEMBERSHIP_SOURCE,
        requested_metadata=requested_metadata,
        refresh=refresh,
    )
    if not rebuild:
        universe_codes = tuple(cached_panel.columns.get_level_values("asset_code").unique())
        return cached_panel, universe_codes

    member_intervals = load_index_members(data_root, universe_indices)
    universe_codes = tuple(sorted(member_intervals["asset_code"].unique()))
    build_calendar = trading_calendar[
        (trading_calendar >= pd.Timestamp(build_metadata["start_date"]))
        & (trading_calendar <= pd.Timestamp(build_metadata["end_date"]))
    ]
    membership_panel = build_membership_panel(
        member_intervals=member_intervals,
        trading_calendar=build_calendar,
        asset_codes=universe_codes,
        index_codes=universe_indices,
    )
    save_source_cache(
        cache_directory,
        MEMBERSHIP_SOURCE,
        membership_panel,
        build_metadata,
    )
    return membership_panel, universe_codes


def _merge_universe_membership(
    membership_panel: pd.DataFrame,
    universe_codes: Sequence[str],
) -> pd.DataFrame:
    """把各指数成员资格按股票代码取逻辑或。"""
    index_membership = membership_panel.xs(
        "membership",
        axis=1,
        level="field",
        drop_level=True,
    )
    membership = (
        index_membership.T.groupby(
            level="asset_code",
            sort=False,
        )
        .any()
        .T
    )
    return membership.reindex(columns=universe_codes).astype(bool)


# ===================== 其他配置来源 ===================== #


def _load_or_build_source_data(
    data_root: Path,
    cache_directory: Path,
    source_name: str,
    source_config: Mapping[str, Any],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    trading_calendar: pd.DatetimeIndex,
    universe_codes: Sequence[str],
    universe_indices: Sequence[str],
    refresh: bool,
    incremental_from: pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """读取一个来源缓存，或按共享范围和字段并集覆盖重建。"""
    requested_metadata = _source_metadata(
        data_root=data_root,
        source_config=source_config,
        universe_indices=universe_indices,
        start_date=start_date,
        end_date=end_date,
    )
    cached_panel, build_metadata, rebuild = _prepare_source_cache(
        cache_directory=cache_directory,
        source_name=source_name,
        requested_metadata=requested_metadata,
        refresh=refresh,
    )
    source_spec = DATA_SOURCE_SPECS[source_name]
    if not rebuild:
        if source_spec.kind != "financial":
            return cached_panel, None
        cached_records = load_financial_records(cache_directory, source_name)
        if cached_records is not None:
            return cached_panel, cached_records
        rebuild = True

    cached_daily_panel = None
    if source_spec.kind == "daily":
        cached_daily_panel = _incremental_daily_cache(
            cache_directory,
            source_name,
            build_metadata,
            incremental_from,
        )
    build_config = _build_source_config(source_config, build_metadata)
    build_start = pd.Timestamp(build_metadata["start_date"])
    build_end = pd.Timestamp(build_metadata["end_date"])
    read_start = incremental_from if cached_daily_panel is not None else build_start
    build_calendar = trading_calendar[
        (trading_calendar >= read_start) & (trading_calendar <= build_end)
    ]
    source_records = load_data(
        data_root=data_root,
        source_name=source_name,
        source_config=build_config,
        start_date=read_start,
        end_date=build_end,
        universe_codes=universe_codes,
    )
    if source_spec.kind == "records":
        save_source_cache(
            cache_directory,
            source_name,
            source_records,
            build_metadata,
        )
        return source_records, None

    output_asset_codes = universe_codes
    if source_spec.asset_column is None:
        output_asset_codes = tuple(build_config["codes"])
    source_panel = build_source_panel(
        source_name=source_name,
        source_data=source_records,
        source_fields=build_config["fields"],
        trading_calendar=build_calendar,
        asset_codes=output_asset_codes,
    )
    if cached_daily_panel is not None:
        source_panel = _merge_daily_panel_tail(
            cached_daily_panel,
            source_panel,
            read_start,
        )
    save_source_cache(
        cache_directory,
        source_name,
        source_panel,
        build_metadata,
    )
    if source_spec.kind == "financial":
        save_financial_records(
            cache_directory,
            source_name,
            source_records,
        )
        return source_panel, source_records
    return source_panel, None


def _incremental_daily_cache(
    cache_directory: Path,
    source_name: str,
    build_metadata: Mapping[str, Any],
    incremental_from: pd.Timestamp | None,
) -> pd.DataFrame | None:
    """在失效日晚于缓存起点时读取可保留的日频前缀。"""
    if incremental_from is None:
        return None
    cache_metadata = load_source_metadata(cache_directory, source_name)
    if cache_metadata is None:
        return None
    if incremental_from <= pd.Timestamp(build_metadata["start_date"]):
        return None
    return load_source_data(cache_directory, source_name)


def _merge_daily_panel_tail(
    cached_panel: pd.DataFrame,
    updated_tail: pd.DataFrame,
    tail_start: pd.Timestamp,
) -> pd.DataFrame:
    """保留失效日前的日频缓存，用重读年度文件覆盖尾部。"""
    cached_prefix = cached_panel.loc[cached_panel.index < tail_start]
    cached_prefix = cached_prefix.reindex(columns=updated_tail.columns)
    return pd.concat([cached_prefix, updated_tail])


def _slice_financial_records(
    source_records: pd.DataFrame,
    source_config: Mapping[str, Any],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> pd.DataFrame:
    """切出当前运行需要的财务公告、业务键和配置字段。"""
    earliest_event_date = start_date - pd.DateOffset(years=1)
    date_mask = source_records["date"].between(earliest_event_date, end_date)
    standard_columns = [
        column_name
        for column_name in (
            "date",
            "asset_code",
            "report_period",
            "operation_time",
            "source_order",
        )
        if column_name in source_records.columns
    ]
    output_columns = list(
        dict.fromkeys([*standard_columns, *source_config["fields"]])
    )
    return source_records.loc[date_mask, output_columns].reset_index(drop=True)


def _slice_source_data(
    source_name: str,
    source_data: pd.DataFrame,
    source_config: Mapping[str, Any],
    trading_calendar: pd.DatetimeIndex,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> pd.DataFrame:
    """从共享缓存切出当前 YAML 声明的数据范围和字段。"""
    if source_name in DATA_SOURCE_SPECS:
        if DATA_SOURCE_SPECS[source_name].kind == "records":
            return _slice_source_records(
                source_data=source_data,
                source_config=source_config,
                start_date=start_date,
                end_date=end_date,
            )

    source_panel = source_data
    output_fields = list(source_config["fields"])
    if source_name in DATA_SOURCE_SPECS:
        if DATA_SOURCE_SPECS[source_name].kind == "financial":
            output_fields.append("REPORT_PERIOD")
    column_mask = source_panel.columns.get_level_values("field").isin(output_fields)
    requested_codes = tuple(str(code) for code in source_config.get("codes", ()))
    if requested_codes and "index_code" in source_panel.columns.names:
        column_mask &= source_panel.columns.get_level_values("index_code").isin(requested_codes)
    elif requested_codes and "asset_code" in source_panel.columns.names:
        column_mask &= source_panel.columns.get_level_values("asset_code").isin(requested_codes)
    sliced_panel = source_panel.loc[trading_calendar, column_mask]
    if "forecast_year_offsets" in source_config:
        requested_offsets = source_config["forecast_year_offsets"]
        offset_mask = sliced_panel.columns.get_level_values("forecast_year_offset").isin(
            requested_offsets
        )
        return sliced_panel.loc[:, offset_mask]
    if (
        "forecast_year_offset" in source_config
        and "forecast_year_offset" in sliced_panel.columns.names
    ):
        return sliced_panel.xs(
            int(source_config["forecast_year_offset"]),
            axis=1,
            level="forecast_year_offset",
            drop_level=True,
        )
    return sliced_panel


def _slice_source_records(
    source_data: pd.DataFrame,
    source_config: Mapping[str, Any],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> pd.DataFrame:
    """从共享明细缓存保留当前 YAML 请求的时间范围、标准键和业务字段。"""
    sliced_records = source_data
    if "source_date" in sliced_records.columns:
        date_mask = sliced_records["source_date"].between(start_date, end_date)
        sliced_records = sliced_records.loc[date_mask]
    elif "report_period" in sliced_records.columns:
        period_mask = sliced_records["report_period"].between(start_date, end_date)
        sliced_records = sliced_records.loc[period_mask]

    standard_columns = [
        column_name
        for column_name in ("asset_code", "source_date", "report_period")
        if column_name in sliced_records.columns
    ]
    output_columns = list(dict.fromkeys([*standard_columns, *source_config["fields"]]))
    return sliced_records.loc[:, output_columns].reset_index(drop=True)
