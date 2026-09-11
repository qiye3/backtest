"""
通过 YAML 构建和复用指数增强研究所需的日频市场数据。

本模块是数据层面向 Factors 和回测模块的公共入口。``MarketData.from_yaml`` 按顺序
建立基准交易日历、中证800与中证1000历史成员并集以及配置点名的来源面板，并把每个
来源保存为独立 Parquet。``get_panel`` 从来源级 MultiIndex 宽表中取出标准二维面板；
本模块不计算因子、不决定调仓频率，也不搜索配置之外的数据路径。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd
import yaml

from src.data.cache import (
    load_source_cache,
    resolve_market_cache_directory,
    save_source_cache,
)
from src.data.calendar import build_trading_calendar
from src.data.load_data import DATA_SOURCE_SPECS, load_data, load_index_members
from src.data.process_data import build_membership_panel, build_source_panel


MEMBERSHIP_SOURCE = "index_membership"
REQUIRED_UNIVERSE_INDICES = {"000906.SH", "000852.SH"}


class MarketData:
    """
    保存已完成日期和证券列对齐的市场数据面板。

    输入：
    - source_panels：按标准来源名组织的来源级 MultiIndex 宽表。
    - calendar：由基准指数行情确定的交易日日历。
    - membership：中证800与中证1000逐日历史成份并集。
    - benchmark_index：回测基准指数 Wind 代码。

    输出：
    - 该类实例向下游公开 ``calendar``、``membership``、``benchmark_index`` 和
      ``get_panel``，不直接暴露缓存构建状态。

    功能和用途：
    - 作为 Factors、分组评价和回测共同使用的数据容器。
    - 构造器只保存已经完成的数据；文件读取和缓存写入由 ``from_yaml`` 负责。
    """

    # 保存已经完成对齐的来源面板和公共时间、股票池信息。
    def __init__(
        self,
        source_panels: Mapping[str, pd.DataFrame],
        calendar: pd.DatetimeIndex,
        membership: pd.DataFrame,
        benchmark_index: str,
    ) -> None:
        """
        初始化可供下游直接读取的市场数据对象。

        输入：
        - source_panels：来源名到完整缓存面板的映射。
        - calendar：所有来源共享的交易日索引。
        - membership：日期乘股票的布尔研究股票池。
        - benchmark_index：用于构造日历和回测对照的基准指数代码。

        输出：
        - 无返回值；参数保存为实例状态。

        功能和用途：
        - 保持对象初始化无磁盘副作用，使测试可以直接用内存面板构造实例。
        - 来源面板保存在私有映射中，避免下游绕过字段选择接口依赖内部列结构。
        """
        self._source_panels = dict(source_panels)
        self.calendar = calendar
        self.membership = membership
        self.benchmark_index = benchmark_index

    # 根据 YAML 配置读取缓存或构建完整市场数据对象。
    @classmethod
    def from_yaml(
        cls,
        config_path: str | Path,
        refresh: bool = False,
    ) -> MarketData:
        """
        从 YAML 构建或复用市场数据面板。

        输入：
        - config_path：包含 ``market_data`` 分区的 YAML 路径。
        - refresh：为假时优先复用已有来源 Parquet；为真时从原始 CSV 重建并覆盖。

        输出：
        - 返回包含交易日历、历史股票池和全部配置来源的 ``MarketData``。

        功能和用途：
        - 先构建指数行情以确定唯一交易日日历，再构建历史成员和股票列范围。
        - 之后逐个来源执行缓存读取或“原始长表→日频面板→Parquet”的构建链路。
        - 原始数据路径、日期、来源与字段全部由 YAML 决定，缓存固定写入项目 ``data``。
        """
        resolved_config_path = Path(config_path).expanduser().resolve()
        market_data_config = _read_market_data_config(resolved_config_path)
        cache_directory = resolve_market_cache_directory(resolved_config_path)
        data_root = Path(market_data_config["source_root"]).expanduser().resolve()
        start_date = pd.Timestamp(market_data_config["start_date"])
        end_date = pd.Timestamp(market_data_config["end_date"])
        benchmark_index = str(market_data_config["benchmark_index"])
        universe_indices = tuple(
            str(index_code)
            for index_code in market_data_config["universe_indices"]
        )
        source_configs = market_data_config["sources"]

        index_price_panel, trading_calendar = _load_index_price_panel(
            data_root=data_root,
            cache_directory=cache_directory,
            source_config=source_configs["index_price"],
            benchmark_index=benchmark_index,
            start_date=start_date,
            end_date=end_date,
            refresh=refresh,
        )
        membership_panel, universe_codes = _load_membership_panel(
            data_root=data_root,
            cache_directory=cache_directory,
            universe_indices=universe_indices,
            trading_calendar=trading_calendar,
            refresh=refresh,
        )
        membership = _merge_universe_membership(
            membership_panel,
            universe_codes,
        )

        source_panels = {
            "index_price": index_price_panel,
            MEMBERSHIP_SOURCE: membership_panel,
        }
        for source_name, source_config in source_configs.items():
            if source_name == "index_price":
                continue
            source_panels[source_name] = _load_or_build_source_panel(
                data_root=data_root,
                cache_directory=cache_directory,
                source_name=source_name,
                source_config=source_config,
                start_date=start_date,
                end_date=end_date,
                trading_calendar=trading_calendar,
                universe_codes=universe_codes,
                refresh=refresh,
            )

        return cls(
            source_panels=source_panels,
            calendar=trading_calendar,
            membership=membership,
            benchmark_index=benchmark_index,
        )

    # 从来源缓存中切出指定字段的标准二维面板。
    def get_panel(
        self,
        source_name: str,
        field_name: str,
        index_code: str | None = None,
    ) -> pd.DataFrame:
        """
        获取 Factors 或回测需要的单字段面板。

        输入：
        - source_name：已配置的数据来源名，例如 ``stock_quote``。
        - field_name：来源内的字段名，例如 ``S_DQ_ADJCLOSE``；历史成员使用
          ``membership``。
        - index_code：指数权重或指数成员来源必须指定的指数代码；普通来源省略。

        输出：
        - 返回索引为 ``calendar``、列为股票或指数代码的二维 DataFrame。

        功能和用途：
        - 先选择来源级 MultiIndex 的 ``field`` 层，再按需选择 ``index_code`` 层。
        - 下游不需要了解每来源一个 Parquet 的内部列组织方式。
        """
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
        return field_panel


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

    universe_indices = {
        str(index_code)
        for index_code in market_data_config["universe_indices"]
    }
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
    index_price_codes = {
        str(index_code)
        for index_code in index_price_config["codes"]
    }
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
            if "forecast_year_offset" not in source_config:
                raise ValueError(
                    f"一致预期来源必须配置 forecast_year_offset: {source_name}"
                )


# ===================== 基准日历和历史股票池 ===================== #

# 优先读取指数行情缓存，未命中时先用原始行情建立交易日历。
def _load_index_price_panel(
    data_root: Path,
    cache_directory: Path,
    source_config: Mapping[str, Any],
    benchmark_index: str,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    refresh: bool,
) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    """
    读取或构建指数行情面板和交易日日历。

    输入：
    - data_root、cache_directory：原始数据根和当前配置缓存目录。
    - source_config：``index_price`` 的代码和字段配置。
    - benchmark_index：用于定义交易日的指数代码。
    - start_date、end_date：面板日期范围。
    - refresh：是否跳过已有缓存强制重建。

    输出：
    - 返回 ``(指数行情来源面板, 交易日日历)``。

    功能和用途：
    - 缓存命中时直接使用其索引作为日历；重建时从基准指数原始记录提取真实交易日。
    - 指数行情必须先于其他来源完成，因为所有后续面板都依赖同一时间轴。
    """
    cached_panel = None
    if not refresh:
        cached_panel = load_source_cache(cache_directory, "index_price")
    if cached_panel is not None:
        trading_calendar = pd.DatetimeIndex(cached_panel.index, name="date")
        return cached_panel, trading_calendar

    index_records = load_data(
        data_root=data_root,
        source_name="index_price",
        source_config=source_config,
        start_date=start_date,
        end_date=end_date,
        universe_codes=(),
    )
    trading_calendar = build_trading_calendar(
        index_records=index_records,
        benchmark_index=benchmark_index,
        start_date=start_date,
        end_date=end_date,
    )
    index_codes = tuple(str(code) for code in source_config["codes"])
    index_price_panel = build_source_panel(
        source_name="index_price",
        source_data=index_records,
        source_fields=source_config["fields"],
        trading_calendar=trading_calendar,
        asset_codes=index_codes,
    )
    save_source_cache(cache_directory, "index_price", index_price_panel)
    return index_price_panel, trading_calendar


# 读取或构建历史指数成员面板，并确定全部个股来源的列范围。
def _load_membership_panel(
    data_root: Path,
    cache_directory: Path,
    universe_indices: Sequence[str],
    trading_calendar: pd.DatetimeIndex,
    refresh: bool,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    """
    读取或构建配置股票池的历史成员面板。

    输入：
    - data_root、cache_directory：原始数据根和当前配置缓存目录。
    - universe_indices：中证800和中证1000指数代码及顺序。
    - trading_calendar：需要展开成员区间的交易日历。
    - refresh：是否强制重新读取成员 CSV。

    输出：
    - 返回 ``(成员来源面板, 历史成员股票代码元组)``。

    功能和用途：
    - 缓存命中时从列索引恢复股票范围；未命中时读取成员区间并按左闭右开展开。
    - 历史成员并集成为所有个股行情和因子原始字段的统一列范围。
    """
    cached_panel = None
    if not refresh:
        cached_panel = load_source_cache(cache_directory, MEMBERSHIP_SOURCE)
    if cached_panel is not None:
        universe_codes = tuple(
            cached_panel.columns.get_level_values("asset_code").unique()
        )
        return cached_panel, universe_codes

    member_intervals = load_index_members(data_root, universe_indices)
    universe_codes = tuple(sorted(member_intervals["asset_code"].unique()))
    membership_panel = build_membership_panel(
        member_intervals=member_intervals,
        trading_calendar=trading_calendar,
        asset_codes=universe_codes,
        index_codes=universe_indices,
    )
    save_source_cache(cache_directory, MEMBERSHIP_SOURCE, membership_panel)
    return membership_panel, universe_codes


# 合并各配置指数的成员资格，形成 Factors 使用的逐日股票池。
def _merge_universe_membership(
    membership_panel: pd.DataFrame,
    universe_codes: Sequence[str],
) -> pd.DataFrame:
    """
    合并中证800和中证1000历史成员面板。

    输入：
    - membership_panel：三层列的指数成员来源面板。
    - universe_codes：最终股票列顺序。

    输出：
    - 返回日期乘股票的布尔 DataFrame，任一配置指数当日包含该股票即为真。

    功能和用途：
    - 保留各指数独立缓存的同时，为 Factors 和回测提供直接可用的统一研究股票池。
    """
    index_membership = membership_panel.xs(
        "membership",
        axis=1,
        level="field",
        drop_level=True,
    )
    membership = index_membership.T.groupby(
        level="asset_code",
        sort=False,
    ).any().T
    return membership.reindex(columns=universe_codes).astype(bool)


# ===================== 其他配置来源 ===================== #

# 对单个配置来源执行缓存读取或原始数据构建链路。
def _load_or_build_source_panel(
    data_root: Path,
    cache_directory: Path,
    source_name: str,
    source_config: Mapping[str, Any],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    trading_calendar: pd.DatetimeIndex,
    universe_codes: Sequence[str],
    refresh: bool,
) -> pd.DataFrame:
    """
    读取或构建一个非基准行情来源的缓存面板。

    输入：
    - data_root、cache_directory：原始数据根和当前配置缓存目录。
    - source_name、source_config：来源名及其字段、指数、筛选和预测年度配置。
    - start_date、end_date：原始记录读取范围。
    - trading_calendar：所有来源共享的最终日期索引。
    - universe_codes：中证800与中证1000历史成员股票列。
    - refresh：是否跳过已有来源缓存。

    输出：
    - 返回完成处理并与交易日历对齐的来源级 MultiIndex 面板。

    功能和用途：
    - 缓存未命中时串起原始长表加载、来源口径处理和 Parquet 保存。
    - 指数行情列采用配置的指数代码，个股与指数权重列采用统一历史成员范围。
    """
    if not refresh:
        cached_panel = load_source_cache(cache_directory, source_name)
        if cached_panel is not None:
            return cached_panel

    source_records = load_data(
        data_root=data_root,
        source_name=source_name,
        source_config=source_config,
        start_date=start_date,
        end_date=end_date,
        universe_codes=universe_codes,
    )
    source_spec = DATA_SOURCE_SPECS[source_name]
    if source_spec.asset_column is None:
        output_asset_codes = tuple(
            str(code)
            for code in source_config["codes"]
        )
    else:
        output_asset_codes = universe_codes
    source_panel = build_source_panel(
        source_name=source_name,
        source_data=source_records,
        source_fields=source_config["fields"],
        trading_calendar=trading_calendar,
        asset_codes=output_asset_codes,
    )
    save_source_cache(cache_directory, source_name, source_panel)
    return source_panel
