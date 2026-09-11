"""
按配置读取指数增强回测需要的本地原始数据。

本模块位于数据链路的输入层，集中维护数据说明文档中主要行情、指数、财务、
一致预期、行业和资金类数据的标准目录与关键字段。``load_data`` 只读取配置点名的
列并规范日期和证券代码，``load_index_members`` 单独读取指数成份区间；二者都输出
长表，不负责透视日频面板、前向填充或写入 Parquet 缓存。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

import pandas as pd


SourceKind = Literal["daily", "event", "financial", "interval", "index_weight"]


@dataclass(frozen=True)
class DataSourceSpec:
    """
    描述一个标准原始数据源的文件布局和时间语义。

    输入：
    - relative_directory：相对原始数据根的目录。
    - file_pattern：年度文件或单文件使用的 glob 模式。
    - kind：决定后续如何构造面板的数据类型。
    - date_column：日频或事件数据的日期字段。
    - asset_column：记录对应的股票代码字段；指数行情由文件名提供代码时为空。
    - annual_files：文件名是否以末尾四位年份分区。
    - index_files：是否需要按 YAML 中的指数代码逐个匹配文件。
    - report_period_column：财务数据的报告期字段。
    - actual_date_column：财务数据优先使用的实际公告日字段。
    - interval_start_column、interval_end_column：区间数据的起止字段。
    - forecast_period_column：一致预期数据用于选择预测年度的字段。
    - operation_time_column：同一业务键重复时用于识别最后入库版本的字段。

    输出：
    - 该类只保存不可变的数据源定义，不产生文件或 DataFrame。

    功能和用途：
    - 让路径和字段差异集中在数据访问层，YAML 只声明需要的来源和业务字段。
    - 后续加载与面板模块共同使用 ``kind``，避免按文件名猜测时间口径。
    """

    relative_directory: str
    file_pattern: str
    kind: SourceKind
    date_column: str | None
    asset_column: str | None
    annual_files: bool = True
    index_files: bool = False
    report_period_column: str | None = None
    actual_date_column: str | None = None
    interval_start_column: str | None = None
    interval_end_column: str | None = None
    forecast_period_column: str | None = None
    operation_time_column: str | None = "OPDATE"


DATA_SOURCE_SPECS: dict[str, DataSourceSpec] = {
    "stock_quote": DataSourceSpec(
        relative_directory="stock/daily_quote",
        file_pattern="quote_*.csv",
        kind="daily",
        date_column="TRADE_DT",
        asset_column="S_INFO_WINDCODE",
    ),
    "stock_valuation": DataSourceSpec(
        relative_directory="stock/daily_valuation",
        file_pattern="valuation_*.csv",
        kind="daily",
        date_column="TRADE_DT",
        asset_column="S_INFO_WINDCODE",
    ),
    "index_price": DataSourceSpec(
        relative_directory="index/prices",
        file_pattern="{index_code}_*.csv",
        kind="daily",
        date_column="TRADE_DT",
        asset_column=None,
        index_files=True,
        operation_time_column=None,
    ),
    "index_total_return": DataSourceSpec(
        relative_directory="index/prices_total_return",
        file_pattern="{index_code}_*.csv",
        kind="daily",
        date_column="TRADE_DT",
        asset_column=None,
        index_files=True,
        operation_time_column=None,
    ),
    "index_weights_monthly": DataSourceSpec(
        relative_directory="index/weights_monthly",
        file_pattern="{index_code}_*.csv",
        kind="index_weight",
        date_column="TRADE_DT",
        asset_column="S_CON_WINDCODE",
        index_files=True,
    ),
    "index_weights_daily_close": DataSourceSpec(
        relative_directory="index/weights_daily_close",
        file_pattern="{index_code}_*.csv",
        kind="daily",
        date_column="TRADE_DT",
        asset_column="S_CON_WINDCODE",
        index_files=True,
    ),
    "financial_income": DataSourceSpec(
        relative_directory="stock/financial/income",
        file_pattern="income_*.csv",
        kind="financial",
        date_column="ANN_DT",
        asset_column="S_INFO_WINDCODE",
        report_period_column="REPORT_PERIOD",
        actual_date_column="ACTUAL_ANN_DT",
    ),
    "financial_balance_sheet": DataSourceSpec(
        relative_directory="stock/financial/balance_sheet",
        file_pattern="balance_sheet_*.csv",
        kind="financial",
        date_column="ANN_DT",
        asset_column="S_INFO_WINDCODE",
        report_period_column="REPORT_PERIOD",
        actual_date_column="ACTUAL_ANN_DT",
    ),
    "financial_cashflow": DataSourceSpec(
        relative_directory="stock/financial/cashflow",
        file_pattern="cashflow_*.csv",
        kind="financial",
        date_column="ANN_DT",
        asset_column="S_INFO_WINDCODE",
        report_period_column="REPORT_PERIOD",
        actual_date_column="ACTUAL_ANN_DT",
    ),
    "financial_indicators": DataSourceSpec(
        relative_directory="stock/financial/indicators",
        file_pattern="indicators_*.csv",
        kind="financial",
        date_column="ANN_DT",
        asset_column="S_INFO_WINDCODE",
        report_period_column="REPORT_PERIOD",
    ),
    "ratings": DataSourceSpec(
        relative_directory="stock/ratings",
        file_pattern="ratings_*.csv",
        kind="event",
        date_column="RATING_DT",
        asset_column="S_INFO_WINDCODE",
    ),
    "consensus_wind": DataSourceSpec(
        relative_directory="stock/consensus/wind",
        file_pattern="wind_*.csv",
        kind="event",
        date_column="con_date",
        asset_column="stock_code",
        forecast_period_column="est_report_dt",
        operation_time_column=None,
    ),
    "consensus_suntime": DataSourceSpec(
        relative_directory="stock/consensus/suntime",
        file_pattern="suntime_*.csv",
        kind="event",
        date_column="con_date",
        asset_column="stock_code",
        forecast_period_column="con_year",
        operation_time_column=None,
    ),
    "industry_history": DataSourceSpec(
        relative_directory="stock/industry",
        file_pattern="industry_history.csv",
        kind="interval",
        date_column=None,
        asset_column="stock_code",
        annual_files=False,
        interval_start_column="begin_date",
        interval_end_column="end_date",
        operation_time_column=None,
    ),
    "free_float": DataSourceSpec(
        relative_directory="stock/ownership",
        file_pattern="free_float_*.csv",
        kind="event",
        date_column="ANN_DT",
        asset_column="S_INFO_WINDCODE",
    ),
    "holder_number": DataSourceSpec(
        relative_directory="stock/ownership",
        file_pattern="holder_number_*.csv",
        kind="event",
        date_column="ANN_DT",
        asset_column="S_INFO_WINDCODE",
    ),
    "margin_trade": DataSourceSpec(
        relative_directory="stock/ownership",
        file_pattern="margin_trade_*.csv",
        kind="daily",
        date_column="TRADE_DT",
        asset_column="S_INFO_WINDCODE",
    ),
    "money_flow": DataSourceSpec(
        relative_directory="stock/ownership",
        file_pattern="money_flow_*.csv",
        kind="daily",
        date_column="TRADE_DT",
        asset_column="S_INFO_WINDCODE",
    ),
}

CSV_CHUNK_ROWS = 500_000


# ===================== 配置来源数据读取 ===================== #

# 读取配置点名的原始字段，并规范为面板构造使用的长表。
def load_data(
    data_root: Path,
    source_name: str,
    source_config: Mapping[str, Any],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    universe_codes: Sequence[str],
) -> pd.DataFrame:
    """
    加载单个配置数据源的有效记录。

    输入：
    - data_root：包含 ``stock`` 和 ``index`` 子目录的原始数据根。
    - source_name：``DATA_SOURCE_SPECS`` 中定义的标准来源名。
    - source_config：该来源的 YAML 配置，必须包含 ``fields``；指数来源还包含
      ``codes``，可选 ``filters``，一致预期来源必须包含 ``forecast_year_offset``。
    - start_date、end_date：最终面板日期范围；调用方应把因子预热期计入开始日。
    - universe_codes：中证800与中证1000历史成份并集，个股记录和指数权重据此裁剪。

    输出：
    - 返回至少含 ``date``、``asset_code`` 和配置字段的长表。
    - 指数权重额外包含 ``index_code``；财务数据额外包含 ``report_period``；
      历史行业数据改为包含 ``start_date`` 和 ``end_date``。

    功能和用途：
    - 只读取配置字段、业务键及去重所需辅助列，并以固定块大小扫描大 CSV。
    - 日频数据只保留配置区间，事件数据保留开始日前一年以建立首日 PIT 状态。
    - 本函数不做宽表透视和前向填充，输出交给 ``process_data`` 模块处理。
    """
    source_spec = DATA_SOURCE_SPECS[source_name]
    source_fields = tuple(source_config["fields"])
    index_codes = tuple(source_config.get("codes", ()))
    source_files = _select_source_files(
        data_root=data_root,
        source_spec=source_spec,
        start_date=start_date,
        end_date=end_date,
        index_codes=index_codes,
    )
    read_columns = _resolve_read_columns(source_spec, source_fields, source_config)
    universe_code_set = set(universe_codes)
    loaded_parts: list[pd.DataFrame] = []
    source_order = 0

    for source_path, file_index_code in source_files:
        for data_chunk in pd.read_csv(
            source_path,
            usecols=read_columns,
            dtype={source_spec.asset_column: "string"} if source_spec.asset_column else None,
            chunksize=CSV_CHUNK_ROWS,
        ):
            normalized_chunk = _normalize_source_chunk(
                data_chunk=data_chunk,
                source_spec=source_spec,
                source_config=source_config,
                file_index_code=file_index_code,
                start_date=start_date,
                end_date=end_date,
                universe_codes=universe_code_set,
            )
            if normalized_chunk.empty:
                continue
            normalized_chunk["source_order"] = range(
                source_order,
                source_order + len(normalized_chunk),
            )
            source_order += len(normalized_chunk)
            loaded_parts.append(normalized_chunk)

    if not loaded_parts:
        raise ValueError(f"数据源没有匹配到有效记录: {source_name}")
    return pd.concat(loaded_parts, ignore_index=True)


# 读取配置指数的历史纳入和剔除区间。
def load_index_members(data_root: Path, index_codes: Sequence[str]) -> pd.DataFrame:
    """
    加载多个指数的历史成份区间。

    输入：
    - data_root：原始数据根，成员文件位于 ``index/members``。
    - index_codes：需要构建历史股票池的指数代码，本项目使用中证800和中证1000。

    输出：
    - 返回 ``index_code/asset_code/start_date/end_date`` 四列长表。
    - ``end_date`` 允许为空，表示成员资格延续到数据末端。

    功能和用途：
    - 统一读取 ``<index_code>.csv`` 中的纳入日、剔除日和成份股票代码。
    - 该结果既用于确定所有个股来源的股票列范围，也用于构造逐日 PIT 成员面板。
    """
    member_parts: list[pd.DataFrame] = []
    members_directory = data_root / "index" / "members"

    for index_code in index_codes:
        member_path = members_directory / f"{index_code}.csv"
        member_data = pd.read_csv(
            member_path,
            usecols=["s_con_windcode", "s_con_indate", "s_con_outdate"],
            dtype={"s_con_windcode": "string"},
        )
        member_part = pd.DataFrame(
            {
                "index_code": index_code,
                "asset_code": member_data["s_con_windcode"].astype("string"),
                "start_date": _parse_yyyymmdd(member_data["s_con_indate"]),
                "end_date": _parse_yyyymmdd(member_data["s_con_outdate"]),
            }
        )
        member_part = member_part.dropna(subset=["asset_code", "start_date"])
        member_parts.append(member_part)

    return pd.concat(member_parts, ignore_index=True)


# ===================== 文件和字段解析 ===================== #

# 按来源目录、指数代码和年份范围确定需要扫描的 CSV。
def _select_source_files(
    data_root: Path,
    source_spec: DataSourceSpec,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    index_codes: Sequence[str],
) -> list[tuple[Path, str | None]]:
    """
    解析单个数据源本次需要读取的文件。

    输入：
    - data_root：原始数据根。
    - source_spec：固定的数据源目录和文件模式。
    - start_date、end_date：面板日期范围，用于筛选年度文件。
    - index_codes：指数类来源需要读取的代码；股票类来源传空序列。

    输出：
    - 返回按文件名排序的 ``(文件路径, 文件所属指数代码)`` 列表。
    - 股票文件的指数代码为 ``None``。

    功能和用途：
    - 日频来源读取开始年至结束年的文件；事件、财务和月度权重额外读取开始年前一年。
    - 缺少配置要求的来源文件时直接抛出 ``FileNotFoundError``。
    """
    source_directory = data_root / source_spec.relative_directory
    first_year = start_date.year
    if source_spec.kind in {"event", "financial", "index_weight"}:
        first_year -= 1

    selected_files: list[tuple[Path, str | None]] = []
    if source_spec.index_files:
        for index_code in index_codes:
            file_pattern = source_spec.file_pattern.format(index_code=index_code)
            source_paths = sorted(source_directory.glob(file_pattern))
            for source_path in source_paths:
                if _file_matches_year(source_path, source_spec, first_year, end_date.year):
                    selected_files.append((source_path, index_code))
    else:
        source_paths = sorted(source_directory.glob(source_spec.file_pattern))
        for source_path in source_paths:
            if _file_matches_year(source_path, source_spec, first_year, end_date.year):
                selected_files.append((source_path, None))

    if not selected_files:
        raise FileNotFoundError(f"没有找到数据源文件: {source_directory}")
    return selected_files


# 汇总业务字段、时间键和筛选列，限制 CSV 实际读取范围。
def _resolve_read_columns(
    source_spec: DataSourceSpec,
    source_fields: Sequence[str],
    source_config: Mapping[str, Any],
) -> list[str]:
    """
    确定读取单个来源必须包含的原始列。

    输入：
    - source_spec：数据源的日期、代码和辅助字段定义。
    - source_fields：YAML 点名的业务字段。
    - source_config：可能包含等值筛选条件的数据源配置。

    输出：
    - 返回去重后的原始 CSV 列名列表。

    功能和用途：
    - 除业务字段外自动加入日期、证券代码、报告期、实际公告日和入库时间。
    - 筛选列即使不输出也必须读取，保证评级周期和报表类型等口径在加载阶段落实。
    """
    read_columns = list(source_fields)
    auxiliary_columns = (
        source_spec.date_column,
        source_spec.asset_column,
        source_spec.report_period_column,
        source_spec.actual_date_column,
        source_spec.interval_start_column,
        source_spec.interval_end_column,
        source_spec.forecast_period_column,
        source_spec.operation_time_column,
    )
    read_columns.extend(column for column in auxiliary_columns if column is not None)
    read_columns.extend(source_config.get("filters", {}).keys())
    return list(dict.fromkeys(read_columns))


# ===================== 单块数据规范化 ===================== #

# 把一个 CSV 数据块转换成统一业务键，并立即裁剪无关记录。
def _normalize_source_chunk(
    data_chunk: pd.DataFrame,
    source_spec: DataSourceSpec,
    source_config: Mapping[str, Any],
    file_index_code: str | None,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    universe_codes: set[str],
) -> pd.DataFrame:
    """
    规范化单个来源的数据块。

    输入：
    - data_chunk：按限定列读取的原始 CSV 分块。
    - source_spec、source_config：固定来源定义和本次字段、筛选配置。
    - file_index_code：指数文件名对应的指数代码；股票文件为 ``None``。
    - start_date、end_date：最终面板范围。
    - universe_codes：允许保留的历史成份股票集合。

    输出：
    - 返回已统一日期、证券代码、辅助业务键并完成行过滤的长表分块。

    功能和用途：
    - 财务数据以有效实际公告日优先，其他事件使用来源规定的观察日。
    - 个股和权重记录在读取阶段过滤到配置股票池，减少后续拼表内存占用。
    - 一致预期按观察日年份加配置偏移选择报告年度，不混合不同预测期限。
    """
    normalized_data = data_chunk.copy()
    for filter_column, filter_value in source_config.get("filters", {}).items():
        normalized_data = normalized_data[
            normalized_data[filter_column].astype("string") == str(filter_value)
        ]

    if source_spec.kind == "interval":
        normalized_data["start_date"] = _parse_yyyymmdd(
            normalized_data[source_spec.interval_start_column]
        )
        normalized_data["end_date"] = _parse_yyyymmdd(
            normalized_data[source_spec.interval_end_column]
        )
    else:
        normalized_data["date"] = _parse_yyyymmdd(normalized_data[source_spec.date_column])
        if source_spec.actual_date_column is not None:
            actual_dates = _parse_yyyymmdd(normalized_data[source_spec.actual_date_column])
            normalized_data["date"] = actual_dates.combine_first(normalized_data["date"])

    if source_spec.asset_column is None:
        normalized_data["asset_code"] = file_index_code
    else:
        normalized_data["asset_code"] = normalized_data[source_spec.asset_column].astype("string")

    if source_spec.index_files and source_spec.asset_column is not None:
        normalized_data["index_code"] = file_index_code

    if source_spec.report_period_column is not None:
        normalized_data["report_period"] = _parse_yyyymmdd(
            normalized_data[source_spec.report_period_column]
        )

    if source_spec.operation_time_column is not None:
        normalized_data["operation_time"] = pd.to_datetime(
            normalized_data[source_spec.operation_time_column]
        )

    normalized_data = _filter_source_dates(
        normalized_data=normalized_data,
        source_kind=source_spec.kind,
        start_date=start_date,
        end_date=end_date,
    )
    if source_spec.forecast_period_column is not None:
        normalized_data = _filter_forecast_year(
            normalized_data=normalized_data,
            forecast_values=normalized_data[source_spec.forecast_period_column],
            year_offset=int(source_config["forecast_year_offset"]),
        )

    if source_spec.asset_column is not None:
        normalized_data = normalized_data[
            normalized_data["asset_code"].isin(universe_codes)
        ]
    return normalized_data


# 按数据的时间语义保留构建区间内所需记录。
def _filter_source_dates(
    normalized_data: pd.DataFrame,
    source_kind: SourceKind,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> pd.DataFrame:
    """
    裁剪日频、事件和区间数据的有效日期范围。

    输入：
    - normalized_data：已经包含统一日期字段的长表分块。
    - source_kind：来源时间类型。
    - start_date、end_date：面板开始日和结束日。

    输出：
    - 返回可能影响目标面板的记录。

    功能和用途：
    - 日频记录严格限制在配置区间；事件和财务数据额外保留开始日前一年作为首日状态。
    - 区间记录只保留与目标日期范围相交的记录，空结束日视为持续有效。
    """
    if source_kind == "interval":
        overlaps_start = normalized_data["end_date"].isna()
        overlaps_start |= normalized_data["end_date"] > start_date
        return normalized_data[
            overlaps_start & (normalized_data["start_date"] <= end_date)
        ]

    normalized_data = normalized_data.dropna(subset=["date", "asset_code"])
    if source_kind in {"event", "financial", "index_weight"}:
        earliest_event_date = start_date - pd.DateOffset(years=1)
        return normalized_data[
            normalized_data["date"].between(earliest_event_date, end_date)
        ]
    return normalized_data[normalized_data["date"].between(start_date, end_date)]


# 选择观察日对应偏移年度的一致预期记录。
def _filter_forecast_year(
    normalized_data: pd.DataFrame,
    forecast_values: pd.Series,
    year_offset: int,
) -> pd.DataFrame:
    """
    按观察日年份选择一致预期报告年度。

    输入：
    - normalized_data：包含统一 ``date`` 的一致预期记录。
    - forecast_values：朝阳永续年份或 Wind 预计报告期字段。
    - year_offset：相对观察日的年度偏移，0 为当年，1 为下一年。

    输出：
    - 返回预测年度等于 ``date.year + year_offset`` 的记录。

    功能和用途：
    - 防止同一股票同一观察日的多个预测年度在二维面板中互相覆盖。
    - 选择规则由 YAML 明确给出，数据层不默认猜测因子使用当年还是次年预测。
    """
    forecast_text = forecast_values.astype("string").str.replace(r"\.0$", "", regex=True)
    forecast_years = pd.to_numeric(forecast_text.str[:4], errors="coerce")
    target_years = normalized_data["date"].dt.year + year_offset
    return normalized_data[forecast_years == target_years]


# 将 Wind 风格的八位日期转换成 pandas 日期类型。
def _parse_yyyymmdd(values: pd.Series) -> pd.Series:
    """
    解析原始 CSV 中的八位日期列。

    输入：
    - values：可能由 pandas 推断为字符串、整数或带空值浮点数的日期序列。

    输出：
    - 返回 ``datetime64[ns]`` Series；空值和无效日期为 ``NaT``。

    功能和用途：
    - 先转换成可空整数再按 ``YYYYMMDD`` 解析，避免 ``20200101.0`` 破坏日期格式。
    - 同一转换规则供交易日、公告日、报告期和区间边界使用。
    """
    numeric_dates = pd.to_numeric(values, errors="coerce").astype("Int64")
    return pd.to_datetime(
        numeric_dates.astype("string"),
        format="%Y%m%d",
        errors="coerce",
    )


# 判断年度文件是否覆盖本次需要读取的年份。
def _file_matches_year(
    source_path: Path,
    source_spec: DataSourceSpec,
    first_year: int,
    last_year: int,
) -> bool:
    """
    判断文件是否位于目标年度范围内。

    输入：
    - source_path：待判断的 CSV 路径。
    - source_spec：包含是否按年度分区的来源定义。
    - first_year、last_year：允许读取的首尾年份。

    输出：
    - 单文件来源始终返回真；年度文件末尾年份落在闭区间时返回真。

    功能和用途：
    - 避免扫描配置区间之外的大型年度 CSV。
    - 标准年度文件均以 ``_<year>.csv`` 结尾，不增加其他命名格式兼容逻辑。
    """
    if not source_spec.annual_files:
        return True
    file_year = int(source_path.stem.rsplit("_", 1)[-1])
    return first_year <= file_year <= last_year
