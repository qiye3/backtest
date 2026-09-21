"""
把规范化原始记录构造成回测与因子计算共享的日频面板。

本模块位于原始 CSV 加载和 Parquet 缓存之间。``build_source_panel`` 根据数据源的
时间语义选择日频、公告事件、财务报告、历史区间或指数权重构造逻辑，
``build_membership_panel`` 单独生成逐日指数成份面板。输出统一使用 MultiIndex 列，
本模块不读取文件、不解析 YAML，也不计算具体因子。
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from src.data.load_data import DATA_SOURCE_SPECS

# ===================== 来源面板入口 ===================== #

# 按数据源的真实时间语义构造一个完整的来源级面板。
def build_source_panel(
    source_name: str,
    source_data: pd.DataFrame,
    source_fields: Sequence[str],
    trading_calendar: pd.DatetimeIndex,
    asset_codes: Sequence[str],
) -> pd.DataFrame:
    """
    构造单个配置来源的日频宽表。

    输入：
    - source_name：``DATA_SOURCE_SPECS`` 中定义的数据源名。
    - source_data：``load_data`` 返回的规范化长表。
    - source_fields：YAML 要求保存的业务字段及其顺序。
    - trading_calendar：基准指数定义的完整交易日日历。
    - asset_codes：输出需要保留的股票或指数代码及列顺序。

    输出：
    - 返回索引为交易日、列为 MultiIndex 的来源级 DataFrame。
    - 普通来源列为 ``(field, asset_code)``，指数权重列为
      ``(field, index_code, asset_code)``。

    功能和用途：
    - 日频、PIT、财务、区间和月度权重使用彼此独立的构造规则。
    - 该函数是 ``MarketData`` 编排层构建来源缓存时调用的统一入口。
    """
    source_spec = DATA_SOURCE_SPECS[source_name]
    source_kind = source_spec.kind
    if source_kind == "daily":
        return _build_daily_panel(
            source_data,
            source_fields,
            trading_calendar,
            asset_codes,
        )
    if source_kind == "event":
        return _build_event_panel(
            source_data,
            source_fields,
            trading_calendar,
            asset_codes,
        )
    if source_kind == "financial":
        financial_data = source_data
        if source_spec.effective_next_trading_day:
            financial_data = _move_events_to_next_trading_day(
                source_data,
                trading_calendar,
            )
        return _build_financial_panel(
            financial_data,
            source_fields,
            trading_calendar,
            asset_codes,
        )
    if source_kind == "interval":
        return _build_interval_panel(
            source_data,
            source_fields,
            trading_calendar,
            asset_codes,
        )
    if source_kind == "index_weight":
        return _build_monthly_weight_panel(
            source_data,
            source_fields,
            trading_calendar,
            asset_codes,
        )
    if source_kind == "static":
        return _build_static_panel(
            source_data,
            source_fields,
            trading_calendar,
            asset_codes,
        )
    raise ValueError(f"没有对应的面板构造规则: {source_name}")


def _move_events_to_next_trading_day(
    source_data: pd.DataFrame,
    trading_calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    """把公告记录的生效日移动到公告后的首个交易日。"""
    event_positions = trading_calendar.searchsorted(
        source_data["date"],
        side="right",
    )
    within_calendar = event_positions < len(trading_calendar)
    shifted_data = source_data.loc[within_calendar].copy()
    shifted_data["date"] = trading_calendar.take(
        event_positions[within_calendar]
    )
    return shifted_data


# 将多个指数的纳入剔除区间展开成逐日布尔成员面板。
def build_membership_panel(
    member_intervals: pd.DataFrame,
    trading_calendar: pd.DatetimeIndex,
    asset_codes: Sequence[str],
    index_codes: Sequence[str],
) -> pd.DataFrame:
    """
    构造配置指数各自的历史成份面板。

    输入：
    - member_intervals：包含 ``index_code/asset_code/start_date/end_date`` 的成员长表。
    - trading_calendar：需要展开的交易日日历。
    - asset_codes：中证800和中证1000历史成员并集及固定列顺序。
    - index_codes：YAML 配置的股票池指数及顺序。

    输出：
    - 返回列为 ``(membership, index_code, asset_code)`` 的布尔 DataFrame。

    功能和用途：
    - 成员区间采用左闭右开口径：纳入日开始有效，剔除日当天失效。
    - 每个指数保留独立成员面板，``MarketData`` 再按股票代码取逻辑或得到研究股票池。
    """
    field_panels: list[pd.DataFrame] = []
    asset_index = pd.Index(asset_codes, name="asset_code")

    for index_code in index_codes:
        membership_values = np.zeros(
            (len(trading_calendar), len(asset_index)),
            dtype=bool,
        )
        asset_positions = {
            asset_code: position
            for position, asset_code in enumerate(asset_index)
        }
        index_intervals = member_intervals[
            member_intervals["index_code"] == index_code
        ]
        for interval in index_intervals.itertuples(index=False):
            asset_position = asset_positions[interval.asset_code]
            first_position = trading_calendar.searchsorted(
                interval.start_date,
                side="left",
            )
            if pd.isna(interval.end_date):
                last_position = len(trading_calendar)
            else:
                last_position = trading_calendar.searchsorted(
                    interval.end_date,
                    side="left",
                )
            membership_values[first_position:last_position, asset_position] = True

        index_membership = pd.DataFrame(
            membership_values,
            index=trading_calendar,
            columns=asset_index,
        )
        field_panels.append(index_membership)

    membership_panel = pd.concat(
        field_panels,
        axis=1,
        keys=index_codes,
        names=["index_code", "asset_code"],
    )
    return pd.concat(
        {"membership": membership_panel},
        axis=1,
        names=["field", "index_code", "asset_code"],
    )


# ===================== 日频和公告事件 ===================== #

# 透视真实交易日记录并保留原始缺失，不跨日补值。
def _build_daily_panel(
    source_data: pd.DataFrame,
    source_fields: Sequence[str],
    trading_calendar: pd.DatetimeIndex,
    asset_codes: Sequence[str],
) -> pd.DataFrame:
    """
    构造行情类数据的日频面板。

    输入：
    - source_data：包含 ``date``、证券代码和配置字段的日频长表。
    - source_fields：需要透视的行情或日频指标字段。
    - trading_calendar：最终面板日期索引。
    - asset_codes：股票或指数代码的固定输出顺序。

    输出：
    - 返回按日历对齐的 MultiIndex 列宽表。

    功能和用途：
    - 同一日期、代码的重复记录按入库时间和文件顺序保留最后一条。
    - 只做 reindex，不做前向填充，确保停牌和原始缺口仍表现为缺失值。
    - 日收盘指数权重带有 ``index_code`` 时保留三层列结构。
    """
    column_keys = ["asset_code"]
    index_codes: Sequence[str] = ()
    if "index_code" in source_data.columns:
        column_keys = ["index_code", "asset_code"]
        index_codes = tuple(source_data["index_code"].drop_duplicates())

    daily_panel = _pivot_source_fields(
        source_data=source_data,
        source_fields=source_fields,
        column_keys=column_keys,
        asset_codes=asset_codes,
        index_codes=index_codes,
    )
    return daily_panel.reindex(trading_calendar)


# 将稀疏观察记录展开到交易日，并且只沿时间向前使用已知值。
def _build_event_panel(
    source_data: pd.DataFrame,
    source_fields: Sequence[str],
    trading_calendar: pd.DatetimeIndex,
    asset_codes: Sequence[str],
) -> pd.DataFrame:
    """
    构造公告、评级和一致预期类 PIT 面板。

    输入：
    - source_data：包含 ``date/asset_code`` 和配置字段的事件长表。
    - source_fields：需要保存的事件值字段。
    - trading_calendar：最终交易日日历。
    - asset_codes：股票列及其固定顺序。

    输出：
    - 返回事件值按交易日向前延续的 MultiIndex 列宽表。

    功能和用途：
    - 先把非交易日事件与交易日合并，再前向填充并截回交易日日历。
    - 交易日事件在当天收盘可见，周末事件从下一交易日起可见。
    - 每只股票首次有效事件前保持缺失，不使用未来记录反向填补。
    """
    column_keys = ["asset_code"]
    forecast_offsets: Sequence[int] = ()
    if "forecast_year_offset" in source_data.columns:
        column_keys = ["forecast_year_offset", "asset_code"]
        forecast_offsets = tuple(
            sorted(source_data["forecast_year_offset"].drop_duplicates())
        )
    event_panel = _pivot_source_fields(
        source_data=source_data,
        source_fields=source_fields,
        column_keys=column_keys,
        asset_codes=asset_codes,
        index_codes=forecast_offsets,
    )
    return _align_events_to_calendar(event_panel, trading_calendar)


def _build_static_panel(
    source_data: pd.DataFrame,
    source_fields: Sequence[str],
    trading_calendar: pd.DatetimeIndex,
    asset_codes: Sequence[str],
) -> pd.DataFrame:
    """把证券主数据的静态字段广播到完整交易日历。"""
    latest_records = _select_latest_records(source_data, ["asset_code"])
    field_panels = {}
    for source_field in source_fields:
        field_values = latest_records.set_index("asset_code")[source_field]
        field_values = field_values.reindex(asset_codes)
        repeated_values = np.broadcast_to(
            field_values.to_numpy(),
            (len(trading_calendar), len(asset_codes)),
        ).copy()
        field_panels[source_field] = pd.DataFrame(
            repeated_values,
            index=trading_calendar,
            columns=pd.Index(asset_codes, name="asset_code"),
        )
    return pd.concat(
        field_panels,
        axis=1,
        names=["field", "asset_code"],
    )


# ===================== 财务和区间数据 ===================== #

# 选取每个公告时点已公开的最新报告期，并同时保留报告期面板。
def _build_financial_panel(
    source_data: pd.DataFrame,
    source_fields: Sequence[str],
    trading_calendar: pd.DatetimeIndex,
    asset_codes: Sequence[str],
) -> pd.DataFrame:
    """
    构造财务报表和财务指标的 PIT 面板。

    输入：
    - source_data：包含公告日、股票、报告期、配置字段和来源顺序的财务长表。
    - source_fields：需要保存的财务字段。
    - trading_calendar：最终交易日日历。
    - asset_codes：股票列及其固定顺序。

    输出：
    - 返回配置财务字段和 ``REPORT_PERIOD`` 组成的来源级日频宽表。

    功能和用途：
    - 对每只股票按公告时间推进，只让当时已经公开的最大报告期成为当前报告。
    - 同一报告期后续修订在修订公告日更新，较旧报告期的迟到记录不会覆盖更新报告。
    - 报告期与数值共享同一 PIT 时间轴，Factors 可按自然季度识别历史观测。
    """
    financial_data = source_data.dropna(
        subset=["date", "asset_code", "report_period"]
    ).copy()
    sort_columns = ["asset_code", "date", "report_period"]
    if "operation_time" in financial_data.columns:
        sort_columns.append("operation_time")
    sort_columns.append("source_order")
    financial_data = financial_data.sort_values(sort_columns, kind="mergesort")
    latest_report_period = financial_data.groupby(
        "asset_code",
        sort=False,
    )["report_period"].cummax()
    current_report_data = financial_data[
        financial_data["report_period"] == latest_report_period
    ]

    output_fields = [*source_fields, "REPORT_PERIOD"]
    current_report_data = current_report_data.assign(
        REPORT_PERIOD=current_report_data["report_period"]
    )
    financial_events = _select_latest_records(
        current_report_data,
        ["date", "asset_code"],
    ).reset_index(drop=True)
    event_state_positions = financial_events.assign(
        state_position=np.arange(len(financial_events)),
    ).pivot(
        index="date",
        columns="asset_code",
        values="state_position",
    )
    event_state_positions = event_state_positions.reindex(columns=asset_codes)
    event_state_positions.columns = pd.Index(asset_codes, name="asset_code")
    daily_state_positions = _align_events_to_calendar(
        event_state_positions,
        trading_calendar,
    )

    field_panels = {
        source_field: _materialize_financial_field(
            daily_state_positions=daily_state_positions,
            event_values=financial_events[source_field],
        )
        for source_field in output_fields
    }
    return pd.concat(
        field_panels,
        axis=1,
        names=["field", "asset_code"],
    )


# 根据每日生效的财务事件位置提取同一报告状态下的字段值。
def _materialize_financial_field(
    daily_state_positions: pd.DataFrame,
    event_values: pd.Series,
) -> pd.DataFrame:
    """
    物化一个财务字段的逐日 PIT 状态。

    输入：
    - daily_state_positions：日期乘股票的事件行位置面板；首次公告前为空，公告后保存
      当前最新报告记录在 ``event_values`` 中的位置。
    - event_values：按事件行位置排列的单个财务字段，可以是数值、日期或字符串。

    输出：
    - 返回与 ``daily_state_positions`` 同索引、同列的字段值面板。

    功能和用途：
    - 每个交易日按整条最新报告记录取值，而不是对各字段分别前向填充。
    - 新报告某字段为空时保留该报告的空值，避免旧报告数值与新的
      ``REPORT_PERIOD`` 错误组合。
    """
    state_positions = daily_state_positions.to_numpy()
    valid_states = ~pd.isna(state_positions)

    if pd.api.types.is_datetime64_any_dtype(event_values.dtype):
        field_values = np.full(
            state_positions.shape,
            np.datetime64("NaT", "ns"),
            dtype="datetime64[ns]",
        )
    elif pd.api.types.is_numeric_dtype(event_values.dtype):
        field_values = np.full(state_positions.shape, np.nan)
    else:
        field_values = np.full(state_positions.shape, pd.NA, dtype="object")

    event_positions = state_positions[valid_states].astype(int)
    field_values[valid_states] = event_values.iloc[event_positions].to_numpy()
    return pd.DataFrame(
        field_values,
        index=daily_state_positions.index,
        columns=daily_state_positions.columns,
    )


# 将历史分类有效区间展开为每日股票分类面板。
def _build_interval_panel(
    source_data: pd.DataFrame,
    source_fields: Sequence[str],
    trading_calendar: pd.DatetimeIndex,
    asset_codes: Sequence[str],
) -> pd.DataFrame:
    """
    构造行业历史等区间型 PIT 面板。

    输入：
    - source_data：包含 ``asset_code/start_date/end_date`` 和分类字段的区间长表。
    - source_fields：需要保存的行业代码或名称字段。
    - trading_calendar：目标交易日日历。
    - asset_codes：股票列及其固定顺序。

    输出：
    - 返回列为 ``(field, asset_code)`` 的字符串或分类值宽表。

    功能和用途：
    - 每条记录在左闭右开区间 ``[start_date, end_date)`` 内生效。
    - 空结束日延续到面板末尾；YAML 筛选负责先确定唯一行业分类体系。
    """
    source_panels: dict[str, pd.DataFrame] = {}
    for source_field in source_fields:
        field_panel = pd.DataFrame(
            pd.NA,
            index=trading_calendar,
            columns=pd.Index(asset_codes, name="asset_code"),
            dtype="object",
        )
        field_records = source_data.dropna(
            subset=["asset_code", "start_date", source_field]
        ).sort_values(["start_date", "source_order"], kind="mergesort")
        for interval in field_records.itertuples(index=False):
            active_dates = trading_calendar >= interval.start_date
            if not pd.isna(interval.end_date):
                active_dates &= trading_calendar < interval.end_date
            field_panel.loc[active_dates, interval.asset_code] = getattr(
                interval,
                source_field,
            )
        source_panels[source_field] = field_panel

    return pd.concat(
        source_panels,
        axis=1,
        names=["field", "asset_code"],
    )


# ===================== 指数权重 ===================== #

# 把稀疏月度权重快照沿交易日向前延续，并统一转换为单位权重。
def _build_monthly_weight_panel(
    source_data: pd.DataFrame,
    source_fields: Sequence[str],
    trading_calendar: pd.DatetimeIndex,
    asset_codes: Sequence[str],
) -> pd.DataFrame:
    """
    构造月度指数权重的日频面板。

    输入：
    - source_data：包含日期、指数代码、成份股票代码和权重字段的长表。
    - source_fields：需要保存的权重字段，通常为 ``I_WEIGHT``。
    - trading_calendar：最终交易日日历。
    - asset_codes：股票列及其固定顺序。

    输出：
    - 返回列为 ``(field, index_code, asset_code)`` 的日频权重面板。

    功能和用途：
    - 原始 ``I_WEIGHT`` 百分数除以100，转换为回测直接使用的单位权重。
    - 快照日与交易日合并后只向前填充，开始日前最后一份已知权重可带入样本首日。
    - 不使用未来月份的权重反向填补历史日期。
    """
    weight_data = source_data.copy()
    if "I_WEIGHT" in source_fields:
        weight_data["I_WEIGHT"] = pd.to_numeric(
            weight_data["I_WEIGHT"],
            errors="coerce",
        ) / 100.0

    index_codes = tuple(weight_data["index_code"].drop_duplicates())
    weight_panel = _pivot_source_fields(
        source_data=weight_data,
        source_fields=source_fields,
        column_keys=["index_code", "asset_code"],
        asset_codes=asset_codes,
        index_codes=index_codes,
    )
    if "I_WEIGHT" in source_fields:
        # 新快照未出现的旧成份权重应归零，否则 ffill 会把已经调出的股票继续带入组合。
        for index_code in index_codes:
            snapshot_dates = weight_data.loc[
                weight_data["index_code"] == index_code,
                "date",
            ].drop_duplicates()
            index_weight_columns = pd.IndexSlice[
                "I_WEIGHT",
                index_code,
                :,
            ]
            weight_panel.loc[
                snapshot_dates,
                index_weight_columns,
            ] = weight_panel.loc[
                snapshot_dates,
                index_weight_columns,
            ].fillna(0.0)
    return _align_events_to_calendar(weight_panel, trading_calendar)


# ===================== 透视和时间对齐 ===================== #

# 把多个业务字段透视并拼成来源级 MultiIndex 列面板。
def _pivot_source_fields(
    source_data: pd.DataFrame,
    source_fields: Sequence[str],
    column_keys: Sequence[str],
    asset_codes: Sequence[str],
    index_codes: Sequence[str],
) -> pd.DataFrame:
    """
    透视来源字段并统一列顺序。

    输入：
    - source_data：包含 ``date``、列业务键和字段值的规范化长表。
    - source_fields：需要转换成第一层列索引的字段。
    - column_keys：普通来源为 ``asset_code``，指数权重为
      ``index_code/asset_code``。
    - asset_codes：最终证券代码顺序。
    - index_codes：三层列来源的指数代码顺序；普通来源传空序列。

    输出：
    - 返回第一层为 ``field`` 的 MultiIndex 列 DataFrame。

    功能和用途：
    - 每个字段先删除空值，再按业务键保留最后入库记录并单独透视。
    - 所有字段随后按配置顺序横向拼接，保证缓存结构和 ``get_panel`` 接口稳定。
    """
    field_panels: dict[str, pd.DataFrame] = {}
    business_keys = ["date", *column_keys]
    for source_field in source_fields:
        field_records = source_data.dropna(subset=[source_field])
        field_records = _select_latest_records(field_records, business_keys)
        if field_records.empty:
            raise ValueError(f"配置字段没有有效记录: {source_field}")
        field_panel = field_records.pivot(
            index="date",
            columns=list(column_keys),
            values=source_field,
        )
        if len(column_keys) == 1:
            field_panel = field_panel.reindex(columns=asset_codes)
            field_panel.columns = pd.Index(asset_codes, name="asset_code")
        else:
            expected_columns = pd.MultiIndex.from_product(
                [index_codes, asset_codes],
                names=list(column_keys),
            )
            field_panel = field_panel.reindex(columns=expected_columns)
        field_panels[source_field] = field_panel.sort_index()

    column_names = ["field", *column_keys]
    return pd.concat(field_panels, axis=1, names=column_names)


# 根据业务键、入库时间和读取顺序选择最后一条记录。
def _select_latest_records(
    source_data: pd.DataFrame,
    business_keys: Sequence[str],
) -> pd.DataFrame:
    """
    选择同一业务键的最后入库记录。

    输入：
    - source_data：包含业务键和 ``source_order`` 的长表。
    - business_keys：定义唯一记录的日期、指数和证券代码字段。

    输出：
    - 返回每组业务键恰好一条记录的 DataFrame。

    功能和用途：
    - 有 ``operation_time`` 时优先按入库时间排序，最后以稳定的来源读取顺序决胜。
    - 该规则用于消除年度文件重叠和同日重复记录，不改变不同日期的历史事件。
    """
    sort_columns = list(business_keys)
    if "operation_time" in source_data.columns:
        sort_columns.append("operation_time")
    sort_columns.append("source_order")
    sorted_data = source_data.sort_values(sort_columns, kind="mergesort")
    return sorted_data.drop_duplicates(list(business_keys), keep="last")


# 将事件日期和交易日日历合并后只向未来传播已知值。
def _align_events_to_calendar(
    event_panel: pd.DataFrame,
    trading_calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    """
    把稀疏事件宽表展开到交易日日历。

    输入：
    - event_panel：索引为真实事件日的来源宽表，事件日可以不是交易日。
    - trading_calendar：最终输出使用的交易日日历。

    输出：
    - 返回索引严格等于 ``trading_calendar`` 的前向填充宽表。

    功能和用途：
    - 先保留事件日再执行 ``ffill``，确保周末公告进入下一交易日而不是被直接丢弃。
    - 前向填充不会给首次事件之前造值，也不会把未来事件带回过去。
    """
    combined_dates = trading_calendar.union(event_panel.index).sort_values()
    aligned_panel = event_panel.reindex(combined_dates).ffill()
    return aligned_panel.reindex(trading_calendar)
