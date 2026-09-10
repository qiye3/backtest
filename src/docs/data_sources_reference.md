# 指数增强策略数据获取：数据字典

> 生成日期：2026-09-09；范围：`【指数增强策略】数据获取/data/` 下当前可获取的 CSV 数据表、元数据表和回填状态表。
> 字段含义与类型优先取自 `API_开放平台_全量文档.md` 对应接口；本地复刻公式取自 `因子指标计算说明.md`、`一致预期数据说明.md` 和 `scripts/14_replicate_growth100.py`。
> “取值范围”以字段类型、单位、代码/日期格式和业务域说明为主，不逐一统计历史极值。

## 一、原始总表（来自数据总表.md）

> 快照时间：2026-09-01 CST。全收益指数已补；Wind 与朝阳永续一致预期均已补齐，字段与命令见 `一致预期数据说明.md`。
>
> 完整字段清单见 `字段字典.csv`；逐文件明细见 `数据集总表.csv` 与 `data_inventory.csv`。

#### 数据来源性质速览

- **内部数据库 taidb**：公司内部数据服务（泰康/易链），直接可查，含指数成分/权重、行业维度、证券主数据。
- **外部 Wind 资讯**：万得数据，通过公司内部 API 网关转发（`queryAShare*` / `queryAIndex*` 系列接口）。
- **外部财汇资讯 CAIHUI**：财汇指数权重数据（已删除），通过公司内部 API 网关转发。
- **本地 derived**：由原始成分区间本地推导的调仓日期，非外部数据。

#### 总表

| 数据集 | 文件/目录 | 存储内容 | 起始日期 | 结束日期 | 覆盖数 | 文件数 | 行数 | 大小(MB) | 数据来源 | 来源性质 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 指数成份股区间 | `index/members/<code>.csv` | 各指数每只成份股的纳入日期、剔除日期、当前是否在指数 | 2005-04-08 | 2026-08-17 | 5108 | 5 | 13236 | 0.5 | 内部 taidb（泰康/易链数据服务，A股指数成份股） | 内部数据库 taidb（公司内部 API） | 完整 |
| 指数成份调整日期 | `index/adjust_dates/<code>*.csv` | 指数定期/临时调整的调仓日期；derived 文件由成份区间生成 | 2005-04-08 | 2026-08-17 | 5 | 7 | 654 | 0.02 | 内部 taidb + 本地 derived | 内部数据库 taidb + 本地 derived | 完整（5 个指数） |
| Wind指数权重(月/定期) | `index/weights_monthly/<code>_<year>.csv` | 指数成分券权重，2010-2011日频，2012后多月/半年频 | 2010-01-04 | 2026-08-03 | 5067 | 68 | 1194900 | 118.53 | Wind via 内部网关 queryAIndexHS300FreeWeight | 外部 Wind 资讯（经内部 API 网关） | 完整 |
| 沪深300日收盘权重 | `index/weights_daily_close/000300.SH_<year>.csv` | 沪深300成分股每日收盘权重 I_WEIGHT 等 | 2010-01-04 | 2026-08-25 | 800 | 17 | 1212600 | 199.49 | Wind via 内部网关 queryAIndexHS300CloseWeight | 外部 Wind 资讯（经内部 API 网关） | 完整 |
| A股日行情 | `stock/daily_quote/quote_<year>.csv` | 全A日线OHLC、复权价/复权因子、成交量额、涨跌幅 | 2010-01-04 | 2026-03-03 | 5738 | 17 | 13924738 | 3204.45 | Wind via 内部网关 queryAShareEODPrices | 外部 Wind 资讯（经内部 API 网关） | 部分缺口（2026 年仅到 03-03） |
| A股日频估值衍生 | `stock/daily_valuation/valuation_<year>.csv` | PE/PB/PS/PCF、市值/股本、换手率、股息率等日频衍生指标 | 2010-01-01 | 2026-01-01 | 5713 | 17 | 14274186 | 5377.62 | Wind via 内部网关 queryAShareEODDerivativeIndicator | 外部 Wind 资讯（经内部 API 网关） | 部分缺口（2017/2020/2021/2024/2025/2026 不全） |
| 利润表 | `stock/financial/income/income_<year>.csv` | 按报告期的利润表科目 | 2010-03-31 | 2026-06-30 | 8546 | 17 | 2008966 | 1017.76 | Wind via 内部网关 queryAShareIncome | 外部 Wind 资讯（经内部 API 网关） | 完整（截至 2026 中报） |
| 资产负债表 | `stock/financial/balance_sheet/balance_sheet_<year>.csv` | 按报告期的资产负债表科目 | 2010-03-31 | 2026-06-30 | 8541 | 17 | 714928 | 572.02 | Wind via 内部网关 queryAShareBalanceSheet | 外部 Wind 资讯（经内部 API 网关） | 完整（截至 2026 中报） |
| 现金流量表 | `stock/financial/cashflow/cashflow_<year>.csv` | 按报告期的现金流量表科目 | 2010-03-31 | 2026-06-30 | 8518 | 17 | 1993044 | 1149.78 | Wind via 内部网关 queryAShareCashFlow | 外部 Wind 资讯（经内部 API 网关） | 完整（截至 2026 中报） |
| 财务指标 | `stock/financial/indicators/indicators_<year>.csv` | ROE/ROA/毛利率/每股指标等财务比率 | 2010-03-31 | 2026-06-30 | 8204 | 17 | 309515 | 401.45 | Wind via 内部网关 queryAShareFinancialIndicator | 外部 Wind 资讯（经内部 API 网关） | 完整（截至 2026 中报） |
| 投资评级汇总 | `stock/ratings/ratings_<year>.csv` | 买入/增持/中性/减持/卖出家数、目标价、评级变化 | 2010-01-01 | 2026-08-25 | 5330 | 17 | 2522378 | 360.25 | Wind via 内部网关 queryAShareStockRatingConsus | 外部 Wind 资讯（经内部 API 网关） | 完整 |
| 行业分类 | `stock/industry/current_industry.csv, industry_history.csv` | 当前与历史申万/中信/Wind/证监会/GICS 等多套行业归属 | 1984-05-09 | 2026-08-21 | 9209 | 2 | 42292 | 5.64 | 内部 taidb 行业维度表 | 内部数据库 taidb（公司内部 API） | 完整 |
| 证券主数据/代码变更 | `stock/meta/basic_desc.csv, code_change.csv` | 证券简称/全称、上市日/退市日、板别、股票代码变更记录 | 1990-12-10 | 2026-08-25 | 5107 | 2 | 8593 | 1.11 | 内部 taidb 证券主数据 | 内部数据库 taidb（公司内部 API） | 完整（basic_desc 5107；code_change 3486 条） |
| 自由流通股本 | `stock/ownership/free_float_<year>.csv` | 自由流通股本变动日期与数量 | 2009-12-29 | 2026-08-25 | 5818 | 17 | 198957 | 23.28 | Wind via 内部网关 queryAShareFreeFloat | 外部 Wind 资讯（经内部 API 网关） | 完整 |
| 股东户数 | `stock/ownership/holder_number_<year>.csv` | 报告期末股东户数、总户数及公告日期 | 2009-12-31 | 2026-08-25 | 5804 | 17 | 459734 | 51.84 | Wind via 内部网关 queryAShareHolderNumber | 外部 Wind 资讯（经内部 API 网关） | 完整 |
| 融资融券明细 | `stock/ownership/margin_trade_<year>.csv` | 融资/融券余额、买入偿还、融资融券交易额等 | 2010-03-31 | 2026-08-25 | 4989 | 17 | 6787030 | 1411.02 | Wind via 内部网关 queryAShareMarginTrade | 外部 Wind 资讯（经内部 API 网关） | 完整 |
| 资金流向 | `stock/ownership/money_flow_<year>.csv` | 大中小单/特大单资金流向、主动买卖、净流入等 | 2012-01-04 | 2022-07-20 | 4843 | 15 | 5684360 | 4308.26 | Wind via 内部网关 queryAShareMoneyFlow | 外部 Wind 资讯（经内部 API 网关） | 部分缺口（2016/2019/2020/2022 不全，2023-2026 缺失） |
| 指数日收盘价 | `index/prices/<code>_<year>.csv` | 沪深300/中证500/中证800/中证1000/中证2000 五个指数的日线 OHLC、涨跌幅、成交量额 | 2010-01-04 | 2026-08-26 | 5 | 85 | 19246 | 3.51 | Wind via 内部网关 queryAIndexEODPrices | 外部 Wind 资讯（经内部 API 网关） | 完整（中证2000 自 2013-12-31/2014 起） |
| 全收益指数日收盘价 | `index/prices_total_return/<code>_<year>.csv` | 沪深300/中证500/中证800/中证1000 全收益指数日线 OHLC、涨跌幅、成交量额 | 2010-01-04 | 2026-08-27 | 4 | 68 | 16176 | 2.24 | Wind via 内部网关 queryAIndexEODPrices（全收益 Wind 代码） | 外部 Wind 资讯（经内部 API 网关） | 完整（中证2000 全收益 Wind 代码未命中，暂缺） |

> 以上总表按源文件原样保留；个别日期/状态可能滞后于 `数据集总表.csv` 与 `data_inventory.csv`，下文表清单以当前清单为准。

## 二、当前表清单

| 表 | 文件/目录 | 文件数 | 行数 | 大小(MB) | 状态/说明 |
|---|---|---:|---:|---:|---|
| 指数成份股区间 | `index/members/<code>.csv` | 5 | 13,236 | 0.50 | 完整 |
| 指数成份调整日期（API原始） | `index/adjust_dates/<code>.csv` | 2 | 95 | 0.00 | 300/800有原始记录 |
| 指数成份调整日期（derived） | `index/adjust_dates/<code>_derived.csv` | 5 | 559 | 0.02 | 5个指数均有 |
| Wind指数权重（月/定期） | `index/weights_monthly/<code>_<year>.csv` | 68 | 1,194,900 | 118.53 | 完整 |
| 沪深300日收盘权重 | `index/weights_daily_close/000300.SH_<year>.csv` | 17 | 1,212,600 | 199.49 | 完整 |
| 指数日收盘价 | `index/prices/<code>_<year>.csv` | 85 | 19,246 | 3.51 | 完整（中证2000 自 2013-12-31/2014 起） |
| 全收益指数日收盘价 | `index/prices_total_return/<code>_<year>.csv` | 82 | 16,176 | 2.24 | 完整（中证2000 自 2013-12-31/2014 起） |
| 国证成长100成份股 | `index/cni_growth100/980080.CNI_members.csv` | 1 | 461 | 0.06 | 成份2024起 |
| 国证成长100日行情 | `index/cni_growth100/980080.CNI_prices.csv` | 1 | 3,318 | 0.48 | 自基日起 |
| 国证成长100月度权重 | `index/cni_growth100/980080.CNI_weights_monthly.csv` | 1 | 3,743 | 0.46 | 权重2021起 |
| A股日行情 | `stock/daily_quote/quote_<year>.csv` | 17 | 13,924,738 | 3204.45 | 完整（截至 2026-09-01） |
| A股日频估值衍生 | `stock/daily_valuation/valuation_<year>.csv` | 17 | 14,274,186 | 5377.62 | 完整（截至 2026-09-02） |
| 利润表 | `stock/financial/income/income_<year>.csv` | 17 | 2,008,966 | 1017.76 | 完整（截至 2026 中报） |
| 资产负债表 | `stock/financial/balance_sheet/balance_sheet_<year>.csv` | 17 | 714,928 | 572.02 | 完整（截至 2026 中报） |
| 现金流量表 | `stock/financial/cashflow/cashflow_<year>.csv` | 17 | 1,993,044 | 1149.78 | 完整（截至 2026 中报） |
| 财务指标 | `stock/financial/indicators/indicators_<year>.csv` | 17 | 309,515 | 401.45 | 完整（截至 2026 中报） |
| 投资评级汇总 | `stock/ratings/ratings_<year>.csv` | 17 | 2,522,378 | 360.25 | 完整 |
| Wind一致预测个股指标 | `stock/consensus/wind/wind_<year>.csv` | 17 | 2,620,283 | 205.77 | 完整 |
| 朝阳永续一致预期 | `stock/consensus/suntime/suntime_<year>.csv` | 17 | 57,904,264 | 7997.82 | 完整 |
| 行业分类（当前） | `stock/industry/current_industry.csv` | 1 | 8,817 | 3.51 | 当前快照 |
| 行业分类（历史） | `stock/industry/industry_history.csv` | 1 | 33,475 | 2.13 | 历史归属 |
| 证券主数据 | `stock/meta/basic_desc.csv` | 1 | 5,107 | 0.98 | 可用 |
| 代码变更 | `stock/meta/code_change.csv` | 1 | 3,486 | 0.13 | 可用 |
| 自由流通股本 | `stock/ownership/free_float_<year>.csv` | 17 | 198,957 | 23.28 | 完整 |
| 股东户数 | `stock/ownership/holder_number_<year>.csv` | 17 | 459,734 | 51.84 | 完整 |
| 融资融券明细 | `stock/ownership/margin_trade_<year>.csv` | 17 | 6,787,030 | 1411.02 | 完整 |
| 资金流向 | `stock/ownership/money_flow_<year>.csv` | 15 | 5,684,360 | 4308.26 | 完整（2012-2026，截至 2026-09-01） |
| 国证成长100复刻候选池 | `index/growth100_replication/growth100_all_a_candidate_pool.csv` | 1 | 10,808 | 4.49 | 完整候选池 |
| 国证成长100复刻净值 | `index/growth100_replication/growth100_all_a_nav.csv` | 1 | 447 | 0.03 | 基期1000 |
| 国证成长100复刻调仓组合 | `index/growth100_replication/growth100_all_a_rebalance_portfolios.csv` | 1 | 900 | 0.10 | 每次100只 |
| 复刻重合度 | `index/growth100_replication/growth100_all_a_overlap_by_rebalance.csv` | 1 | 9 | 0.00 | 9个调仓日 |
| 复刻重合度与中证覆盖 | `index/growth100_replication/growth100_all_a_overlap_and_csi_coverage.csv` | 1 | 9 | 0.00 | 9个调仓日 |
| 字段字典 | `字段字典.csv` | 1 | 21 | 0.02 | 21个数据集 |
| 数据集总表 | `数据集总表.csv` | 1 | 22 | 0.02 | 22个数据集 |
| 文件清单 | `data_inventory.csv` | 1 | 499 | 0.02 | 499个CSV |
| Wind一致预期进度 | `stock/consensus/.progress/wind.csv` | 1 | 5,886 | 0.11 | 断点续传 |
| 朝阳永续进度 | `stock/consensus/.progress/suntime.csv` | 1 | 9,956 | 0.19 | 断点续传 |

> 非表格文件（`growth100_all_a_summary.json`、PNG 图、`.weekly_state.json`）不在逐字段表格中展开；`logs/`、`scripts/` 为过程文件和代码，不属于数据表。

## 三、指数与成份数据

### 表 1：指数成份股区间

- 文件/目录：`index/members/<code>.csv`
- 文件数 / 行数 / 大小：5 / 13,236 / 0.50 MB
- 来源：内部 taidb
- 状态：完整

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| s_con_indate | 纳入日期 | YYYYMMDD字符串 | T时点：纳入日期≤T。 |
| s_info_windcode | 指数Wind代码 | Wind证券/指数代码字符串；可为空 | 指数Wind代码 |
| s_con_outdate | 剔除日期 | YYYYMMDD字符串；可为空 | T时点：为空或≥T仍在指数内。 |
| cur_sign | 最新标志 | 0/1或空 | 最新标志 |
| s_con_windcode | 成份股Wind代码 | Wind证券/指数代码字符串；可为空 | 成份股Wind代码 |

### 表 2：指数成份调整日期（API原始）

- 文件/目录：`index/adjust_dates/<code>.csv`
- 文件数 / 行数 / 大小：2 / 95 / 0.00 MB
- 来源：内部 taidb
- 状态：300/800有原始记录

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| adjust_dt | 调仓日期 | YYYYMMDD字符串；可为空 | 调仓日期 |
| index_code | 指数Wind代码 | 字符串（字符串）；可为空 | 指数Wind代码 |
| id | 记录ID | 整数 | 数据库记录唯一标识。 |

### 表 3：指数成份调整日期（derived）

- 文件/目录：`index/adjust_dates/<code>_derived.csv`
- 文件数 / 行数 / 大小：5 / 559 / 0.02 MB
- 来源：本地derived
- 状态：5个指数均有

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| adjust_dt | 调仓日期 | YYYYMMDD字符串；可为空 | 调仓日期 |
| index_code | 业绩基准指数代码 | 字符串（字符串）；可为空 | 业绩基准指数代码 |
| source | 来源标识 | 字符串，derived | 由成份股区间推导。 |

### 表 4：Wind指数权重（月/定期）

- 文件/目录：`index/weights_monthly/<code>_<year>.csv`
- 文件数 / 行数 / 大小：68 / 1,194,900 / 118.53 MB
- 来源：Wind
- 状态：完整

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| TRADE_DT | 交易日期 | YYYYMMDD字符串；可为空 | 原始字段，非本地计算。 |
| S_INFO_WINDCODE | 指数Wind代码 | Wind证券/指数代码字符串；可为空 | 原始字段，非本地计算。 |
| OBJECT_ID | 数据库记录对象ID | 字符串/整数；可为空 | 接口同步元数据。 |
| I_WEIGHT | 权重 | 数值，权重百分比；截面合计约100 | 原始字段，非本地计算。 |
| OPDATE | 数据操作/入库时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| gmt_modified | GMT修改时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_CON_WINDCODE | 成份股Wind代码 | Wind证券/指数代码字符串；可为空 | 原始字段，非本地计算。 |
| OPMODE | 操作/写入模式 | 字符串；可为空 | 接口同步元数据。 |
| gmt_created | GMT创建时间 | 时间戳字符串；可为空 | 接口同步元数据。 |

### 表 5：沪深300日收盘权重

- 文件/目录：`index/weights_daily_close/000300.SH_<year>.csv`
- 文件数 / 行数 / 大小：17 / 1,212,600 / 199.49 MB
- 来源：Wind
- 状态：完整

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| TRADE_DT | 交易日期 | YYYYMMDD字符串；可为空 | 原始字段，非本地计算。 |
| I_WEIGHT_17 | 总市值 | 数值（NUMBER(20,2)）；可为空 | 原始字段，非本地计算。 |
| I_WEIGHT_16 | 调整后开盘参考价 | 字符串（VARCHAR2(2)）；可为空 | 原始字段，非本地计算。 |
| I_WEIGHT_15 | 收盘 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| I_WEIGHT_14 | 权重因子 | 数值（NUMBER(20,8)）；可为空 | 原始字段，非本地计算。 |
| I_WEIGHT_12 | 自由流通比例(%)(归档后) | 字符串（VARCHAR2(2)）；可为空 | 原始字段，非本地计算。 |
| I_WEIGHT_11 | 总股本(股) | 数值（NUMBER(20,2)）；可为空；单位：股 | 原始字段，非本地计算。 |
| I_WEIGHT | 权重 | 数值，权重百分比；当日合计约100 | 沪深300日收盘权重。 |
| gmt_modified | GMT修改时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| I_WEIGHT_18 | 计算用市值 | 数值（NUMBER(20,2)）；可为空 | 原始字段，非本地计算。 |
| S_INFO_WINDCODE | 指数Wind代码 | Wind证券/指数代码字符串；可为空 | 原始字段，非本地计算。 |
| S_IN_INDEX | 计算用股本(股) | 数值（NUMBER(20,2)）；可为空；单位：股 | 原始字段，非本地计算。 |
| OBJECT_ID | 数据库记录对象ID | 字符串/整数；可为空 | 接口同步元数据。 |
| OPDATE | 数据操作/入库时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_CON_WINDCODE | 成份股Wind代码 | Wind证券/指数代码字符串；可为空 | 原始字段，非本地计算。 |
| OPMODE | 操作/写入模式 | 字符串；可为空 | 接口同步元数据。 |
| gmt_created | GMT创建时间 | 时间戳字符串；可为空 | 接口同步元数据。 |

### 表 6：指数日收盘价

- 文件/目录：`index/prices/<code>_<year>.csv`
- 文件数 / 行数 / 大小：85 / 19,246 / 3.51 MB
- 来源：Wind
- 状态：完整（中证2000 自 2013-12-31/2014 起）

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| TRADE_DT | 交易日期 | YYYYMMDD字符串；可为空 | 原始字段，非本地计算。 |
| S_DQ_VOLUME | 成交量(手) | 数值（NUMBER(20,4)）；可为空；单位：手 | 原始字段，非本地计算。 |
| S_DQ_PRECLOSE | 昨收盘价(点) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SEC_ID | 证券ID | Wind证券/指数代码字符串；可为空 | 原始字段，非本地计算。 |
| CRNCY_CODE | 货币代码 | 字符串（VARCHAR2(10)）；可为空 | 原始字段，非本地计算。 |
| gmt_modified | GMT修改时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_DQ_AMOUNT | 成交金额(千元) | 数值（NUMBER(20,4)）；可为空；单位：千元 | 原始字段，非本地计算。 |
| S_DQ_OPEN | 开盘价(点) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_INFO_WINDCODE | Wind代码 | Wind证券/指数代码字符串；可为空 | 原始字段，非本地计算。 |
| S_DQ_LOW | 最低价(点) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OBJECT_ID | 数据库记录对象ID | 字符串/整数；可为空 | 接口同步元数据。 |
| S_DQ_HIGH | 最高价(点) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_DQ_PCTCHANGE | 涨跌幅(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| OPDATE | 数据操作/入库时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_DQ_CHANGE | 涨跌(点) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OPMODE | 操作/写入模式 | 字符串；可为空 | 接口同步元数据。 |
| gmt_created | GMT创建时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_DQ_CLOSE | 收盘价(点) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |

### 表 7：全收益指数日收盘价

- 文件/目录：`index/prices_total_return/<code>_<year>.csv`
- 文件数 / 行数 / 大小：82 / 16,176 / 2.24 MB
- 来源：Wind全收益代码
- 状态：完整（中证2000 自 2013-12-31/2014 起）

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| TRADE_DT | 交易日期 | YYYYMMDD字符串；可为空 | 原始字段，非本地计算。 |
| S_DQ_VOLUME | 成交量(手) | 数值（NUMBER(20,4)）；可为空；单位：手 | 原始字段，非本地计算。 |
| S_DQ_PRECLOSE | 昨收盘价(点) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SEC_ID | 证券ID | Wind证券/指数代码字符串；可为空 | 原始字段，非本地计算。 |
| CRNCY_CODE | 货币代码 | 字符串（VARCHAR2(10)）；可为空 | 原始字段，非本地计算。 |
| gmt_modified | GMT修改时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_DQ_AMOUNT | 成交金额(千元) | 数值（NUMBER(20,4)）；可为空；单位：千元 | 原始字段，非本地计算。 |
| S_DQ_OPEN | 开盘价(点) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_INFO_WINDCODE | Wind代码 | Wind证券/指数代码字符串；可为空 | 原始字段，非本地计算。 |
| S_DQ_LOW | 最低价(点) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OBJECT_ID | 数据库记录对象ID | 字符串/整数；可为空 | 接口同步元数据。 |
| S_DQ_HIGH | 最高价(点) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_DQ_PCTCHANGE | 涨跌幅(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| OPDATE | 数据操作/入库时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_DQ_CHANGE | 涨跌(点) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OPMODE | 操作/写入模式 | 字符串；可为空 | 接口同步元数据。 |
| gmt_created | GMT创建时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_DQ_CLOSE | 收盘价(点) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |

### 表 8：国证成长100成份股

- 文件/目录：`index/cni_growth100/980080.CNI_members.csv`
- 文件数 / 行数 / 大小：1 / 461 / 0.06 MB
- 来源：Wind
- 状态：成份2024起

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| S_INFO_WINDCODE | 指数Wind代码 | Wind证券/指数代码字符串；可为空 | 原始字段，非本地计算。 |
| CUR_SIGN | 最新标志 | 数值（NUMBER(1,0)）；可为空 | 原始字段，非本地计算。 |
| OBJECT_ID | 数据库记录对象ID | 字符串/整数；可为空 | 接口同步元数据。 |
| OPDATE | 数据操作/入库时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_CON_INDATE | 纳入日期 | YYYYMMDD字符串；可为空 | 原始字段，非本地计算。 |
| gmt_modified | GMT修改时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_CON_WINDCODE | 成份股Wind代码 | Wind证券/指数代码字符串；可为空 | 原始字段，非本地计算。 |
| S_CON_OUTDATE | 剔除日期 | YYYYMMDD字符串；可为空 | 原始字段，非本地计算。 |
| OPMODE | 操作/写入模式 | 字符串；可为空 | 接口同步元数据。 |
| gmt_created | GMT创建时间 | 时间戳字符串；可为空 | 接口同步元数据。 |

### 表 9：国证成长100日行情

- 文件/目录：`index/cni_growth100/980080.CNI_prices.csv`
- 文件数 / 行数 / 大小：1 / 3,318 / 0.48 MB
- 来源：Wind
- 状态：自基日起

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| TRADE_DT | 交易日期 | YYYYMMDD字符串；可为空 | 原始字段，非本地计算。 |
| S_DQ_VOLUME | 成交量(手) | 数值（NUMBER(20,4)）；可为空；单位：手 | 原始字段，非本地计算。 |
| S_DQ_PRECLOSE | 昨收盘价(点) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SEC_ID | 证券ID | Wind证券/指数代码字符串；可为空 | 原始字段，非本地计算。 |
| CRNCY_CODE | 货币代码 | 字符串（VARCHAR2(10)）；可为空 | 原始字段，非本地计算。 |
| gmt_modified | GMT修改时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_DQ_AMOUNT | 成交金额(千元) | 数值（NUMBER(20,4)）；可为空；单位：千元 | 原始字段，非本地计算。 |
| S_DQ_OPEN | 开盘价(点) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_INFO_WINDCODE | Wind代码 | Wind证券/指数代码字符串；可为空 | 原始字段，非本地计算。 |
| S_DQ_LOW | 最低价(点) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OBJECT_ID | 数据库记录对象ID | 字符串/整数；可为空 | 接口同步元数据。 |
| S_DQ_HIGH | 最高价(点) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_DQ_PCTCHANGE | 涨跌幅(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| OPDATE | 数据操作/入库时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_DQ_CHANGE | 涨跌(点) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OPMODE | 操作/写入模式 | 字符串；可为空 | 接口同步元数据。 |
| gmt_created | GMT创建时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_DQ_CLOSE | 收盘价(点) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |

### 表 10：国证成长100月度权重

- 文件/目录：`index/cni_growth100/980080.CNI_weights_monthly.csv`
- 文件数 / 行数 / 大小：1 / 3,743 / 0.46 MB
- 来源：Wind
- 状态：权重2021起

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| TRADE_DT | 交易日期 | YYYYMMDD字符串；可为空 | 原始字段，非本地计算。 |
| S_INFO_WINDCODE | 指数Wind代码 | Wind证券/指数代码字符串；可为空 | 原始字段，非本地计算。 |
| OBJECT_ID | 数据库记录对象ID | 字符串/整数；可为空 | 接口同步元数据。 |
| I_WEIGHT | 权重 | 数值，权重百分比；截面合计约100 | 原始字段，非本地计算。 |
| OPDATE | 数据操作/入库时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| gmt_modified | GMT修改时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_CON_WINDCODE | 成份股Wind代码 | Wind证券/指数代码字符串；可为空 | 原始字段，非本地计算。 |
| OPMODE | 操作/写入模式 | 字符串；可为空 | 接口同步元数据。 |
| gmt_created | GMT创建时间 | 时间戳字符串；可为空 | 接口同步元数据。 |

## 四、个股行情与估值

### 表 11：A股日行情

- 文件/目录：`stock/daily_quote/quote_<year>.csv`
- 文件数 / 行数 / 大小：17 / 13,924,738 / 3204.45 MB
- 来源：Wind
- 状态：完整（截至 2026-09-01）

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| TRADE_DT | 交易日期 | YYYYMMDD字符串；可为空 | 原始字段，非本地计算。 |
| S_DQ_ADJCLOSE | 复权收盘价 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_DQ_ADJHIGH | 复权最高价 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_DQ_TRADESTATUS | 交易状态 | 字符串（VARCHAR2(10)）；可为空 | 原始字段，非本地计算。 |
| S_DQ_PRECLOSE | 昨收盘价(元) | 数值（NUMBER(20,4)）；可为空；单位：元 | 原始字段，非本地计算。 |
| S_DQ_ADJCLOSE_BACKWARD | 前复权收盘价(元) | 数值（NUMBER(20,4)）；可为空；单位：元 | 原始字段，非本地计算。 |
| S_DQ_STOPPING | 跌停价(元) | 数值（NUMBER(20,4)）；可为空；单位：元 | 原始字段，非本地计算。 |
| CRNCY_CODE | 货币代码 | 字符串（VARCHAR2(10)）；可为空 | 原始字段，非本地计算。 |
| gmt_modified | GMT修改时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_DQ_AMOUNT | 成交金额 | 数值；单位：千元；可为空 | 近半年均值=mean(S_DQ_AMOUNT)。 |
| S_INFO_WINDCODE | Wind代码 | Wind证券/指数代码字符串；可为空 | 万得证券唯一编码。 |
| OBJECT_ID | 数据库记录对象ID | 字符串/整数；可为空 | 接口同步元数据。 |
| S_DQ_HIGH | 最高价(元) | 数值（NUMBER(20,4)）；可为空；单位：元 | 原始字段，非本地计算。 |
| OPDATE | 数据操作/入库时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_DQ_CHANGE | 涨跌(元) | 数值（NUMBER(20,4)）；可为空；单位：元 | 原始字段，非本地计算。 |
| S_DQ_ADJLOW | 复权最低价 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_DQ_LIMIT | 涨停价(元) | 数值（NUMBER(20,4)）；可为空；单位：元 | 原始字段，非本地计算。 |
| OPMODE | 操作/写入模式 | 字符串；可为空 | 接口同步元数据。 |
| gmt_created | GMT创建时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_DQ_CLOSE | 收盘价(元) | 数值（NUMBER(20,4)）；可为空；单位：元 | 原始字段，非本地计算。 |
| S_DQ_VOLUME | 成交量(手) | 数值（NUMBER(20,4)）；可为空；单位：手 | 原始字段，非本地计算。 |
| S_DQ_ADJFACTOR | 复权因子 | 数值（NUMBER(20,6)）；可为空 | 原始字段，非本地计算。 |
| S_DQ_ADJOPEN | 复权开盘价 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_DQ_OPEN | 开盘价(元) | 数值（NUMBER(20,4)）；可为空；单位：元 | 原始字段，非本地计算。 |
| S_DQ_LOW | 最低价(元) | 数值（NUMBER(20,4)）；可为空；单位：元 | 原始字段，非本地计算。 |
| S_DQ_TRADESTATUSCODE | 交易状态代码 | 数值（NUMBER(5,0)）；可为空 | 原始字段，非本地计算。 |
| S_DQ_PCTCHANGE | 涨跌幅(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| S_DQ_ADJPRECLOSE | 复权昨收盘价 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_DQ_AVGPRICE | 均价(VWAP) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |

### 表 12：A股日频估值衍生

- 文件/目录：`stock/daily_valuation/valuation_<year>.csv`
- 文件数 / 行数 / 大小：17 / 14,274,186 / 5377.62 MB
- 来源：Wind
- 状态：完整（截至 2026-09-02）

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| TRADE_DT | 交易日期 | YYYYMMDD字符串；可为空 | 原始字段，非本地计算。 |
| NET_INCR_CASH_CASH_EQU_LYR | 现金及现金等价物净增加额（上年同期） | 数值；可为空 | 财务报表原始字段。 |
| S_DQ_TURN | 换手率 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NET_ASSETS_TODAY | 当日净资产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_VAL_PB_NEW | 市净率(PB) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_INFO_ASHARECODE | 证券ID | 字符串（VARCHAR2(10)）；可为空 | 原始字段，非本地计算。 |
| S_PQ_ADJLOW_52W | 近1年最低价(后复权) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_VAL_PCF_OCFTTM | 市现率(PCF,经营现金流TTM) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NET_CASH_FLOWS_OPER_ACT_LYR | 经营活动产生的现金流量净额(LYR) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_VAL_PS | 市销率(PS) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| AVGVOLUME_3M | 最近3个月平均成交量 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_DQ_MV | 当日流通市值 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| LOWEST_HIGHEST_STATUS | 最高最低价状态 | 数值（NUMBER(2,0)）；可为空 | 原始字段，非本地计算。 |
| ABPRICERATIO | AB股比价 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CRNCY_CODE | 交易货币代码 | 字符串（VARCHAR2(10)）；可为空 | 原始字段，非本地计算。 |
| gmt_modified | GMT修改时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_DQ_CLOSE_TODAY | 当日收盘价 | 数值；单位：元；可为空 | free_float_mv=FREE_SHARES_TODAY×收盘价。 |
| OPER_REV_LYR | 营业收入(LYR) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_DQ_FREETURNOVER | 换手率(基准.自由流通股本) | 数值（NUMBER(20,4)）；可为空；单位：基准.自由流通股 | 原始字段，非本地计算。 |
| S_INFO_WINDCODE | Wind代码 | Wind证券/指数代码字符串；可为空 | 万得证券唯一编码。 |
| S_VAL_PCF_NCFTTM | 市现率(PCF,现金净流量TTM) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NET_PROFIT_PARENT_COMP_TTM | 浮点型 | 字符串；可为空 | 归属于母公司的净利润（TTM） |
| OBJECT_ID | 数据库记录对象ID | 字符串/整数；可为空 | 接口同步元数据。 |
| FLOAT_A_SHR_TODAY | 当日流通股本 | 数值（NUMBER(24,8)）；可为空 | 原始字段，非本地计算。 |
| OPER_REV_TTM | 营业收入(TTM) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_PQ_HIGH_52W_ | 近1年最高价 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OPDATE | 数据操作/入库时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| OPMODE | 操作/写入模式 | 字符串；可为空 | 接口同步元数据。 |
| gmt_created | GMT创建时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| FREE_SHARES_TODAY | 当日自由流通股本 | 数值；单位：万股；可为空 | free_float_mv=FREE_SHARES_TODAY×收盘价。 |
| SWING | 振幅 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_VAL_PE_TTM | 市盈率(PE,TTM) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NET_INCR_CASH_CASH_EQU_TTM | 浮点型 | 字符串；可为空 | 现金净流量（TTM） |
| UP_DOWN_LIMIT_STATUS | 涨跌停状态 | 数值（NUMBER(2,0)）；可为空 | 原始字段，非本地计算。 |
| S_PRICE_DIV_DPS | 股价/每股派息 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_PQ_LOW_52W_ | 近1年最低价 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_VAL_PCF_OCF | 市现率(PCF,经营现金流) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_VAL_PCF_NCF | 市现率(PCF,现金净流量) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_VAL_PE | 市盈率(PE) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_VAL_PS_TTM | 市销率(PS,TTM) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_VAL_MV | 当日总市值 | 数值；单位：万元；可为空 | 近半年均值=mean(S_VAL_MV)。 |
| TOT_SHR_TODAY | 当日总股本 | 数值（NUMBER(24,8)）；可为空 | 原始字段，非本地计算。 |
| NET_PROFIT_PARENT_COMP_LYR | 归属母公司净利润（上年同期） | 数值；可为空 | 财务报表原始字段。 |
| S_PQ_ADJHIGH_52W | 近1年最高价(后复权) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NET_CASH_FLOWS_OPER_ACT_TTM | 经营活动产生的现金流量净额(TTM) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CRNCY_CODE2 | 面值货币代码 | 字符串（VARCHAR2(10)）；可为空 | 原始字段，非本地计算。 |

## 五、财务报表与财务指标

### 表 13：利润表

- 文件/目录：`stock/financial/income/income_<year>.csv`
- 文件数 / 行数 / 大小：17 / 2,008,966 / 1017.76 MB
- 来源：Wind
- 状态：完整（截至 2026 中报）

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| LESS_OPER_COST | 减:营业成本 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_COMPREH_INC_MIN_SHRHLDR | 高精度浮点型 | 字符串；可为空 | TOT_COMPREH_INC_MIN_SHRHLDR |
| NET_INC_SEC_TRADING_BROK_BUS | 高精度浮点型 | 字符串；可为空 | NET_INC_SEC_TRADING_BROK_BUS |
| LESS_NON_OPER_EXP | 减:营业外支出 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| REINSURANCE_EXP | 分保费用 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NET_PROFIT_UNDER_INTL_ACC_STA | 高精度浮点型 | 字符串；可为空 | NET_PROFIT_UNDER_INTL_ACC_STA |
| INSUR_PREM_UNEARNED | 已赚保费 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| LESS_TAXES_SURCHARGES_OPS | 减:营业税金及附加 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CAPITALIZED_COMSTOCK_DIV | 转作股本的普通股股利 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| IL_NET_LOSS_DISP_NONCUR_ASSET | 其中:减:非流动资产处置净损失 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SPE_BAL_NET_PROFIT | 净利润差额(特殊报表科目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TRANSFER_FROM_OTHERS | 其他转入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| WITHDR_LEGALSURPLUS | 提取法定盈余公积 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| INC_TAX | 所得税 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| HANDLING_CHRG_COMM_INC | 手续费及佣金收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| DISTRIBUTABLE_PROFIT | 可分配利润 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CHG_INSUR_CONT_RSRV | 提取保险责任准备金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| MEMO | 备注 | 字符串（VARCHAR2(1000)）；可为空 | 原始字段，非本地计算。 |
| PLUS_NET_INVEST_INC | 加:投资净收益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| INCL_INC_INVEST_ASSOC_JV_ENTP | 其中:对联营企业和合营企业的投资收益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| COMSHARE_DVD_PAYABLE | 应付普通股股利 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| RD_EXPENSE | 研发费用 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| WITHDR_LEGALPUBWELFUNDS | 高精度浮点型 | 字符串；可为空 | WITHDR_LEGALPUBWELFUNDS |
| TOT_OPT_INC_DIF | 营业总收入差额(特殊报表科目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_BAL_TOT_PROFIT | 利润总额差额(合计平衡项目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| PRFSHARE_DVD_PAYABLE | 应付优先股股利 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| LESS_SELLING_DIST_EXP | 减:销售费用 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_EPS_BASIC | 基本每股收益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| PLUS_NET_GAIN_FX_TRANS | 加:汇兑净收益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_OPT_COST_DIF | 营业总成本差额(特殊报表科目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CRNCY_CODE | 货币代码 | 字符串（VARCHAR2(10)）；可为空 | 原始字段，非本地计算。 |
| STMNOTE_FINEXP | 财务费用:利息费用 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| gmt_modified | GMT修改时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| LESS_CEDED_OUT_PREM | 减:分出保费 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OPER_EXP | 营业支出 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| DISTRIBUTABLE_PROFIT_SHRHDER | 可供股东分配的利润 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OBJECT_ID | 数据库记录对象ID | 字符串/整数；可为空 | 接口同步元数据。 |
| NET_PROFIT_INCL_MIN_INT_INC | 净利润(含少数股东损益) | 数值（NUMBER(20,4)）；可为空；单位：含少数股 | 原始字段，非本地计算。 |
| LESS_CLAIM_RECB_REINSURER | 减:摊回赔付支出 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TRANSFER_FROM_SURPLUSRESERVE | 盈余公积转入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_OPER_COST2 | 营业总成本2 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| IS_CALCULATION | 是否计算值 | 0/1或空 | 接口标记字段。 |
| CHG_UNEARNED_PREM_RES | 提取未到期责任准备金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| END_NET_PROFIT | 终止经营净利润 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OPDATE | 数据操作/入库时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| OTHER_INCOME | 其他收益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OPMODE | 操作/写入模式 | 字符串；可为空 | 接口同步元数据。 |
| TOT_OPER_REV | 营业总收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| INCL_REINSURANCE_PREM_INC | 其中:分保费收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OTHER_BUS_INC | 其他业务收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| LESS_GERL_ADMIN_EXP | 减:管理费用 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NET_INC_OTHER_OPS | 其他经营净收益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| DVD_EXP_INSURED | 保户红利支出 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CREDIT_IMPAIRMENT_LOSS | 信用减值损失 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SPE_BAL_OPER_PROFIT | 营业利润差额(特殊报表科目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TRANSFER_FROM_HOUSINGIMPREST | 住房周转金转入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_BAL_NET_PROFIT | 净利润差额(合计平衡项目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_INFO_COMPCODE | 公司id | 字符串（VARCHAR2(10)）；可为空 | 原始字段，非本地计算。 |
| PREM_INC | 保费业务收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| PLUS_NET_GAIN_CHG_FV | 加:公允价值变动净收益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_OPER_COST | 营业总成本 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| PREPAY_SURR | 退保金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| MINORITY_INT_INC | 少数股东损益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| UNCONFIRMED_INVEST_LOSS | 未确认投资损失 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NET_INT_INC | 利息净收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| EBITDA | 息税折旧摊销前利润 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NET_PROFIT_AFTER_DED_NR_LP | 扣除非经常性损益后的净利润(扣除少数股东损益) | 数值（NUMBER(20,4)）；可为空；单位：扣除少数股 | 原始字段，非本地计算。 |
| TOT_COMPREH_INC | 高精度浮点型 | 字符串；可为空 | TOT_COMPREH_INC |
| OTHER_IMPAIR_LOSS_ASSETS | 其他资产减值损失 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| ANN_DT | 公告日期 | YYYYMMDD字符串；可为空 | 原始字段，非本地计算。 |
| NET_INC_SEC_UW_BUS | 证券承销业务净收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| LESS_INT_EXP | 减:利息支出 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_CLAIM_EXP | 赔付总支出 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NET_AFTER_DED_NR_LP_CORRECT | 扣除非经常性损益后的净利润(财务重要指标(更正前)) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| REPORT_PERIOD | 报告期 | YYYYMMDD字符串；可为空 | 原始字段，非本地计算。 |
| EBIT | 息税前利润 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| ACTUAL_ANN_DT | 实际公告日期 | YYYYMMDD字符串；可为空 | 原始字段，非本地计算。 |
| CONTINUED_NET_PROFIT | 持续经营净利润 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| LESS_HANDLING_CHRG_COMM_EXP | 减:手续费及佣金支出 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| LESS_INS_RSRV_RECB_REINSURER | 减:摊回保险责任准备金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_PROFIT | 利润总额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| FIN_EXP_INT_INC | 财务费用:利息收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| INT_INC | 利息收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| WITHDR_OTHERSURPRESERVE | 提取任意盈余公积金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| ASSET_DISPOSAL_INCOME | 资产处置收益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| WIND_CODE | Wind代码 | Wind证券/指数代码字符串；可为空 | 原始字段，非本地计算。 |
| LESS_IMPAIR_LOSS_ASSETS | 减:资产减值损失 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| COMP_TYPE_CODE | 公司类型代码 | 字符串（VARCHAR2(10)）；可为空 | 原始字段，非本地计算。 |
| WITHDR_RESERVEFUND | 提取储备基金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OTHER_BUS_COST | 其他业务成本 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_BAL_OPER_PROFIT | 营业利润差额(合计平衡项目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OPER_REV | 营业收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NET_INC_EC_ASSET_MGMT_BUS | 受托客户资产管理业务净收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SPE_BAL_TOT_PROFIT | 利润总额差额(特殊报表科目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_INFO_WINDCODE | Wind代码 | Wind证券/指数代码字符串；可为空 | 万得证券唯一编码。 |
| INSURANCE_EXPENSE | 保险业务支出 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| STATEMENT_TYPE | 报表类型 | 字符串（VARCHAR2(10)）；可为空 | 原始字段，非本地计算。 |
| TOT_OPT_COST_DIF_MEMO | 营业总成本差额说明(特殊报表科目) | 字符串（VARCHAR2(200)）；可为空 | 原始字段，非本地计算。 |
| PLUS_NET_INC_OTHER_BUS | 加:其他业务净收益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| gmt_created | GMT创建时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| OPER_PROFIT | 营业利润 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_COMPREH_INC_PARENT_COMP | 高精度浮点型 | 字符串；可为空 | TOT_COMPREH_INC_PARENT_COMP |
| S_FA_EPS_DILUTED | 稀释每股收益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| UNDISTRIBUTED_PROFIT | 年初未分配利润 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NET_EXPOSURE_HEDGING_BENEFITS | 净敞口套期收益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_OPT_INC_DIF_MEMO | 营业总收入差额说明(特殊报表科目) | 字符串（VARCHAR2(200)）；可为空 | 原始字段，非本地计算。 |
| NET_HANDLING_CHRG_COMM_INC | 手续费及佣金净收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| LESS_FIN_EXP | 减:财务费用 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| LESS_EXP_RECB_REINSURER | 减:摊回分保费用 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OTHER_COMPREH_INC | 高精度浮点型 | 字符串；可为空 | OTHER_COMPREH_INC |
| PLUS_NON_OPER_REV | 加:营业外收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| ADJLOSSGAIN_PREVYEAR | 调整以前年度损益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| WORKERS_WELFARE | 职工奖金福利 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| WITHDR_BUZEXPWELFARE | 提取企业发展基金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NET_PROFIT_EXCL_MIN_INT_INC | 归母净利润 | 数值；可为空 | 取ANN_DT≤T最新报告期；要求>0。 |
| AMODCOST_FIN_ASSETS | 以摊余成本计量的金融资产终止确认收益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |

### 表 14：资产负债表

- 文件/目录：`stock/financial/balance_sheet/balance_sheet_<year>.csv`
- 文件数 / 行数 / 大小：17 / 714,928 / 572.02 MB
- 来源：Wind
- 状态：完整（截至 2026 中报）

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| TOT_LIAB | , | 数值（NUMBER(20,4)）；可为空 | , |
| PREPAY | 预付款项 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| RCV_FROM_REINSURER | 应收分保账款 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| FIN_ASSETS_AVAIL_FOR_SALE | 可供出售金融资产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CUST_BANK_DEP | 吸收存款 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| LOANS_TO_OTH_BANKS | 拆出资金 | 数值（NUMBER(20,4)）；可为空 | 一个企业（金融）拆借给境内、境外其他金融机构的款项；指一个企业（金融）拆借给境内、境外其他金融机构的款项； |
| STM_BS_TOT | 固定资产(合计)(元) | 数值（NUMBER(20,4)）；可为空；单位：元 | 原始字段，非本地计算。 |
| INSURED_PLEDGE_LOAN | 保户质押贷款 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SPE_CUR_ASSETS_DIFF | 专项平衡流动资产差额 | 数值；可为空 | 财务报表平衡校验字段。 |
| SPE_BAL_LIAB_DIFF_MEMO | 负债差额说明(特殊报表科目) | 字符串（VARCHAR2(500)）；可为空 | 原始字段，非本地计算。 |
| TRADABLE_FIN_LIAB | 交易性金融负债 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_LIAB_SHRHLDR_EQY | 负债及股东权益总计 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| DEFERRED_INC_NON_CUR_LIAB | 递延收益-非流动负债 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NON_CUR_LIAB_DUE_WITHIN_1Y | 一年内到期的非流动负债 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| ST_FINANCING_PAYABLE | 应付短期融资款 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| DEBT_INVESTMENT | 债权投资(元) | 数值（NUMBER(20,4)）；可为空；单位：元 | 原始字段，非本地计算。 |
| ACTING_TRADING_SEC | 代理买卖证券款 | 数值（NUMBER(20,4)）；可为空 | 公司接受客户委托，代理客户买卖股票、债券和基金等有价证券而收到的款项，包括公司代理客户认购新股的款项、代理客户领取的现金股利和债券利息，代客户向证券交易所支付的配股款等；指公司接受客户委托，代理客户买 |
| OTHER_EQUITY_TOOLS_P_SHR | 其他权益工具:优先股 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SURPLUS_RSRV | 盈余公积金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| HANDLING_CHARGES_COMM_PAYABLE | 应付手续费及佣金 | 数值（NUMBER(20,4)）；可为空 | 企业在接受金融服务时应支付但未支付的手续费和佣金；企业或个人在接受金融服务时应支付但尚未支付的手续费和佣金收入； |
| ADV_FROM_CUST | 预收款项 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| ST_BONDS_PAYABLE | 应付短期债券 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| ACCOUNTS_RECEIVABLE | 应收款项 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| INTANG_ASSETS | 无形资产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| MINORITY_INT | 少数股东权益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CAP_STK | 股本 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| PROV_NOM_RISKS | 一般风险准备 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| AGENCY_BUS_ASSETS | 代理业务资产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OTHER_DEBT_INVESTMENT | 其他债权投资(元) | 数值（NUMBER(20,4)）；可为空；单位：元 | 原始字段，非本地计算。 |
| OTH_NON_CUR_ASSETS | 其他非流动资产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CRNCY_CODE | 货币代码 | 字符串（VARCHAR2(10)）；可为空 | 原始字段，非本地计算。 |
| OTH_CUR_LIAB | 其他流动负债 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| gmt_modified | GMT修改时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| LT_BORROW | 长期借款 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| HELD_TO_MTY_INVEST | 持有至到期投资 | 数值（NUMBER(20,4)）；可为空 | 企业打算并且能够持有至到期的债权证券；指企业打算并且能够持有到期的债权证券； |
| LT_PAYROLL_PAYABLE | 长期应付职工薪酬 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| INT_RCV | 应收利息 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OTH_LIAB | 其他负债 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OPDATE | 数据操作/入库时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| R_AND_D_COSTS | 开发支出 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| ACTING_UW_SEC | 代理承销证券款 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OPMODE | 操作/写入模式 | 字符串；可为空 | 接口同步元数据。 |
| LOANS_AND_ADV_GRANTED | 发放贷款及垫款 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_BAL_SHRHLDR_EQY_DIFF | 股东权益差额(合计平衡项目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CONTRACTUAL_ASSETS | 合同资产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_BAL_LIAB_EQY_DIFF | 负债及股东权益差额(合计平衡项目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| DVD_PAYABLE_INSURED | 应付保单红利 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| FIN_ASSETS_FAIR_VALUE | 以公允价值计量且其变动计入其他综合收益的金融资产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| LESS_TSY_STK | 减:库存股 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| LENDING_FUNDS | 融出资金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OTH_RCV_TOT | 其他应收款(合计)（元） | 数值（NUMBER(20,4)）；可为空；单位：元 | 原始字段，非本地计算。 |
| OTH_PAYABLE_TOT | 其他应付款(合计)(元) | 数值（NUMBER(20,4)）；可为空；单位：元 | 原始字段，非本地计算。 |
| OTHER_ILLIQUIDFINANCIAL_ASSETS | 其他非流动金融资产(元) | 数值（NUMBER(20,4)）；可为空；单位：元 | 原始字段，非本地计算。 |
| EMPL_BEN_PAYABLE | 应付职工薪酬 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| ACC_STA_CODE | 原始报表采用会计准则代码 | 字符串（VARCHAR2(2)）；可为空 | 原始字段，非本地计算。 |
| RED_MONETARY_CAP_FOR_SALE | 买入返售金融资产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| ANN_DT | 公告日期 | YYYYMMDD字符串；可为空 | 原始字段，非本地计算。 |
| TOT_CUR_ASSETS_DIFF | 流动资产差额合计 | 数值；可为空 | 财务报表平衡校验字段。 |
| INVENTORIES | 存货 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| LT_PAYABLE | 长期应付款 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| PROJ_MATL | 工程物资 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_SHRHLDR_EQY_INCL_MIN_INT | 股东权益合计(含少数股东权益) | 数值（NUMBER(20,4)）；可为空；单位：含少数股 | 原始字段，非本地计算。 |
| DVD_PAYABLE | 应付股利 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| RCV_INVEST | 应收款项投资 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CLAIMS_PAYABLE | 应付赔付款 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SPECIAL_RSRV | 专项储备 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| ACTUAL_ANN_DT | 实际公告日期 | YYYYMMDD字符串；可为空 | 原始字段，非本地计算。 |
| TOT_CUR_LIAB_DIFF | 流动负债差额(合计平衡项目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SPE_NON_CUR_LIAB_DIFF_MEMO | 非流动负债差额说明(特殊报表科目) | 字符串（VARCHAR2(500)）；可为空 | 原始字段，非本地计算。 |
| LONG_TERM_EQY_INVEST | 长期股权投资 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| ACCOUNTS_RECEIVABLE_BILL | 应收票据及应收账款 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| LIFE_INSUR_RSRV | 寿险责任准备金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| PRODUCTIVE_BIO_ASSETS | 生产性生物资产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SPE_CUR_LIAB_DIFF_MEMO | 流动负债差额说明(特殊报表科目) | 字符串（VARCHAR2(500)）；可为空 | 原始字段，非本地计算。 |
| RCV_CEDED_UNEARNED_PREM_RSRV | 应收分保未到期责任准备金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| FIN_ASSETS_COST_SHARING | 以摊余成本计量的金融资产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_CUR_ASSETS | 流动资产合计 | 数值（NUMBER(20,4)）；可为空 | 流动资产类科目合计值；指在一年内或者超过一年的一个营业周期内变现或者耗用的资产； |
| RCV_CEDED_LT_HEALTH_INSUR_RSRV | 应收分保长期健康险责任准备金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| INDEPENDENT_ACCT_LIAB | 独立账户负债 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SPE_CUR_ASSETS_DIFF_MEMO | 流动资产差额说明(特殊报表科目) | 字符串（VARCHAR2(500)）；可为空 | 原始字段，非本地计算。 |
| S_INFO_WINDCODE | Wind代码 | Wind证券/指数代码字符串；可为空 | 原始字段，非本地计算。 |
| TOT_NON_CUR_ASSETS_DIFF | 非流动资产差额合计 | 数值；可为空 | 财务报表平衡校验字段。 |
| PAYABLES | 应付款项 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| MRGN_PAID | 存出保证金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| ACCOUNTS_PAYABLE | 应付票据及应付账款 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SPE_NON_CUR_ASSETS_DIFF | 专项平衡非流动资产差额 | 数值；可为空 | 财务报表平衡校验字段。 |
| DEPOSIT_RECEIVED | 存入保证金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_BAL_LIAB_DIFF | 负债差额(合计平衡项目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| UNDISTRIBUTED_PROFIT | 未分配利润 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SPE_BAL_SHRHLDR_EQY_DIFF | 股东权益差额(特殊报表科目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| ASSET_DEP_OTH_BANKS_FIN_INST | 存放同业和其他金融机构款项 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| DEFERRED_TAX_ASSETS | 递延所得税资产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OIL_AND_NATURAL_GAS_ASSETS | 油气资产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| LONG_TERM_REC | 长期应收款 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| PREM_RCV | 应收保费 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SPE_BAL_LIAB_EQY_DIFF | 负债及股东权益差额(特殊报表项目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NOTES_RCV | 应收票据 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CLIENTS_RSRV_SETTLE | 客户备付金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SPECIFIC_ITEM_PAYABLE | 专项应付款 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CAP_RSRV | 资本公积金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OTH_PAYABLE | 其他应付款 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| HFS_SALES | 持有待售的负债 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| RCV_FROM_CEDED_INSUR_CONT_RSRV | 分出保险合同准备金应收款 | 数值；可为空 | 保险类财务报表科目。 |
| CNVD_DIFF_FOREIGN_CURR_STAT | 外币报表折算差额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OTH_NON_CUR_LIAB | 其他非流动负债 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| INT_PAYABLE | 应付利息 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OTHER_SUSTAINABLE_BOND | 其他权益工具:永续债(元) | 数值（NUMBER(20,4)）；可为空；单位：元 | 原始字段，非本地计算。 |
| DERIVATIVE_FIN_LIAB | 衍生金融负债 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| RECEIVABLES_FINANCING | 应收款项融资 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| FIX_ASSETS | 固定资产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SUBR_REC | 应收代位追偿款 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_BAL_ASSETS_DIFF | 资产差额(合计平衡项目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| AGENCY_BUS_LIAB | 代理业务负债 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| INCL_SEAT_FEES_EXCHANGE | 其中:交易席位费 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| ST_BORROW | 短期借款 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| INDEPENDENT_ACCT_ASSETS | 独立账户资产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| RCV_CEDED_CLAIM_RSRV | 应收分保未决赔款准备金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SPE_NON_CUR_ASSETS_DIFF_MEMO | 非流动资产差额说明(特殊报表科目) | 字符串（VARCHAR2(500)）；可为空 | 原始字段，非本地计算。 |
| SPE_NON_CUR_LIAB_DIFF | 专项平衡非流动负债差额 | 数值；可为空 | 财务报表平衡校验字段。 |
| OTHER_EQUITY_TOOLS | 其他权益工具 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| GOODWILL | 商誉 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OUT_LOSS_RSRV | 未决赔款准备金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TIME_DEPOSITS | 定期存款 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| PRECIOUS_METALS | 贵金属 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TRADABLE_FIN_ASSETS | 交易性金融资产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OBJECT_ID | 数据库记录对象ID | 字符串/整数；可为空 | 接口同步元数据。 |
| OTH_CUR_ASSETS | 其他流动资产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TAXES_SURCHARGES_PAYABLE | 应交税费 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| RIGHT_USE_ASSETS | 使用权资产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| FUND_SALES_FIN_ASSETS_RP | 卖出回购金融资产款 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| UNEARNED_PREM_RSRV | 未到期责任准备金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_ASSETS | 资产总计 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_CUR_LIAB | 流动负债合计 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| MONETARY_CAP | 货币资金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_INFO_COMPCODE | Wind公司ID | 字符串；可为空 | 万得公司唯一编码。 |
| LEASE_LIAB | 租赁负债 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NOTES_PAYABLE | 应付票据 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| DEFERRED_TAX_LIAB | 递延所得税负债 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SETTLE_RSRV | 结算备付金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| RSRV_INSUR_CONT | 保险合同准备金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| UNCONFIRMED_INVEST_LOSS | 未确认的投资损失 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| LT_HEALTH_INSUR_V | 长期健康险责任准备金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| DEFERRED_EXP | 待摊费用 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| LOANS_OTH_BANKS | 拆入资金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NON_CUR_ASSETS_DUE_WITHIN_1Y | 一年内到期的非流动资产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SPE_BAL_ASSETS_DIFF | 资产差额(特殊报表科目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OTHER_COMP_INCOME | 其他综合收益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SPE_BAL_ASSETS_DIFF_MEMO | 资产差额说明(特殊报表科目) | 字符串（VARCHAR2(1000)）；可为空 | 原始字段，非本地计算。 |
| INCL_PLEDGE_LOAN | 其中:质押借款 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OTH_RCV | 其他应收款 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CLIENTS_CAP_DEPOSIT | 客户资金存款 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CONST_IN_PROG_TOT | 在建工程(合计)(元) | 数值（NUMBER(20,4)）；可为空；单位：元 | 原始字段，非本地计算。 |
| TOT_NON_CUR_LIAB_DIFF | 非流动负债差额合计 | 数值；可为空 | 财务报表平衡校验字段。 |
| ACCT_RCV | 应收账款 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_SHRHLDR_EQY_EXCL_MIN_INT | 股东权益合计(不含少数股东权益) | 数值（NUMBER(20,4)）；可为空；单位：不含少数股 | 原始字段，非本地计算。 |
| PREM_RECEIVED_ADV | 预收保费 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| INSURED_DEPOSIT_INVEST | 保户储金及投资款 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| LIAB_DEP_OTH_BANKS_FIN_INST | 同业和其它金融机构存放款项 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| REPORT_PERIOD | 报告期 | YYYYMMDD字符串；可为空 | 原始字段，非本地计算。 |
| HFS_ASSETS | 持有待售的资产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SPE_BAL_SHRHLDR_EQY_DIFF_MEMO | 其他股东权益说明(特殊报表科目) | 字符串；可为空 | 资产负债表中，股东权益(不含少数股东)中非标准科目的科目和金额 |
| ACCT_PAYABLE | 应付账款 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_NON_CUR_ASSETS | 非流动资产合计 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| LONG_TERM_DEFERRED_EXP | 长期待摊费用 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_NON_CUR_LIAB | 非流动负债合计 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SPE_CUR_LIAB_DIFF | 流动负债差额(特殊报表科目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| DVD_RCV | 应收股利 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| BORROW_CENTRAL_BANK | 向中央银行借款 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_SHR | 期末总股本 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| PAYABLE_TO_REINSURER | 应付分保账款 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SPE_BAL_LIAB_EQY_DIFF_MEMO | 负债及股东权益差额说明(特殊报表项目) | 字符串（VARCHAR2(200)）；可为空 | 原始字段，非本地计算。 |
| OTH_ASSETS | 其他资产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| ACC_EXP | 预提费用 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CAP_MRGN_PAID | 存出资本保证金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| INVEST_REAL_ESTATE | 投资性房地产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| DEFERRED_INC | 递延收益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CASH_DEPOSITS_CENTRAL_BANK | 现金及存放中央银行款项 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| DERIVATIVE_FIN_ASSETS | 衍生金融资产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| WIND_CODE | Wind代码 | Wind证券/指数代码字符串；可为空 | 原始字段，非本地计算。 |
| PROVISIONS | 预计负债 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| COMP_TYPE_CODE | 公司类型代码 | 字符串（VARCHAR2(2)）；可为空 | 原始字段，非本地计算。 |
| CONSUMPTIVE_BIO_ASSETS | 消耗性生物资产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| DEPOSIT_RECEIVED_IB_DEPOSITS | 吸收存款及同业存放 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CONTRACT_LIABILITIES | 合同负债 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| STATEMENT_TYPE | 报表类型 | 数值（NUMBER(9,0)）；可为空 | 原始字段，非本地计算。 |
| gmt_created | GMT创建时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| IFLISTED_DATA | 是否上市后数据 | 数值（NUMBER(1,0)）；可为空 | 原始字段，非本地计算。 |
| SPE_BAL_LIAB_DIFF | 负债差额(特殊报表科目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| FIX_ASSETS_DISP | 固定资产清理 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OTHER_EQUITY_INVESTMENT | 其他权益工具投资 | 数值；可为空 | 财务报表原始字段。 |
| RCV_CEDED_LIFE_INSUR_RSRV | 应收分保寿险责任准备金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CONST_IN_PROG | 在建工程 | 数值（NUMBER(20,4)）；可为空 | 企业资产的新建、改建、扩建或技术改造、设备更新和大修工程等尚未完工的工程支出；指企业资产的新建、改建、扩建，或技术改造、设备更新和大修工程等尚未完工的工程支出； |
| LT_PAYABLE_TOT | 长期应付款(合计)(元) | 数值（NUMBER(20,4)）；可为空；单位：元 | 原始字段，非本地计算。 |
| BONDS_PAYABLE | 应付债券 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |

### 表 15：现金流量表

- 文件/目录：`stock/financial/cashflow/cashflow_<year>.csv`
- 文件数 / 行数 / 大小：17 / 1,993,044 / 1149.78 MB
- 来源：Wind
- 状态：完整（截至 2026 中报）

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| IM_NET_CASH_FLOWS_OPER_ACT | , | 数值（NUMBER(20,4)）；可为空 | , |
| NET_INCR_LOANS_OTHER_BANK | , | 数值（NUMBER(20,4)）；可为空 | , |
| STOT_CASH_INFLOWS_FNC_ACT | , | 数值（NUMBER(20,4)）；可为空 | , |
| SPE_BAL_NETCASH_EQU_UNDIR | 间接法-经营活动现金流量净额差额(特殊报表科目) | 数值（NUMBER(20,4)）；可为空 | 企业根据本身业务披露的，非万得标准的间接法-经营活动现金流量净额科目明细；现金流量表补充数据中，经营活动现金流量净额中非标准科目的科目和金额； |
| STOT_CASH_OUTFLOWS_INV_ACT | , | 数值（NUMBER(20,4)）；可为空 | , |
| DEPR_FA_COGA_DPBA | 固定资产折旧、油气资产折耗、生产性生物资产折旧 | 数值；可为空 | 现金流量表补充资料。 |
| TOT_BAL_NETCASH_OUTFLOWS_FNC | 筹资活动现金流出总额（平衡口径） | 数值；可为空 | 财务报表平衡校验字段。 |
| CASH_PREPAY_AMT_BORR | 偿还债务支付的现金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NET_CASH_RECEIVED_REINSU_BUS | 收到再保业务现金净额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| PLUS_PROV_DEPR_ASSETS | 加:资产减值准备 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CASH_CASH_EQU_END_PERIOD | 期末现金及现金等价物余额 | 数值（NUMBER(20,4)）；可为空 | 报表截止日期现金及融资期限为三个月或三个月内的，具有高度流动性且内购赚取利息的投资的余额；企业年末时的现金及现金等价物余额； |
| CASH_PAY_ACQ_CONST_FIOLTA | , | 数值（NUMBER(20,4)）；可为空 | , |
| TOT_BAL_CASH_INFLOWS_OPER | 经营活动现金流入差额(合计平衡项目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NET_INCR_DISP_FAAS | 处置可供出售金融资产净增加额 | 数值（NUMBER(20,4)）；可为空 | 企业对交易性金融资产和持有至到期投资以外的其他债券证券和权益证券的处置所产生的增加净额；反映证券公司本期自行买卖可供出售金融资产所取得的现金净增加额； |
| COMM_INSUR_PLCY_PAID | 支付保单红利的现金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NET_PROFIT | 净利润 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| FA_FNC_LEASES | 融资租入固定资产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| DECR_DEFERRED_INC_TAX_ASSETS | 递延所得税资产减少 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CASH_PAY_GOODS_PURCH_SERV_REC | 购买商品、接受劳务支付的现金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OTHER_CASH_RECP_RAL_INV_ACT | 收到其他与投资活动有关的现金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| LOSS_SCR_FA | 固定资产报废损失 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SPE_BAL_CASH_OUTFLOWS_OPER | 经营活动现金流出差额(特殊报表科目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_BAL_CASH_OUTFLOWS_FNC | 筹资活动现金流出差额(合计平衡项目) | 数值（NUMBER(20,4)）；可为空 | 现金流量表中，筹资活动现金流出合计与明细科目之间的差额；根据筹资活动现金流出平衡关系计算得出的因财报公布不平导致的差额； |
| CASH_RECP_SG_AND_RS | 销售商品、提供劳务收到的现金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NET_INCR_LOANS_CENTRAL_BANK | 向中央银行借款净增加额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CASH_PAY_DIST_DPCP_INT_EXP | 分配股利、利润或偿付利息支付的现金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OTHER_CASH_PAY_RAL_FNC_ACT | 支付其他与筹资活动有关的现金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| STOT_CASH_INFLOWS_OPER_ACT | 经营活动现金流入小计 | 数值（NUMBER(20,4)）；可为空 | 与经营活动相关的现金流量的明细统计；指企业从事经营所获得的收入； |
| TOT_BAL_CASH_INFLOWS_FNC | 筹资活动现金流入差额(合计平衡项目) | 数值（NUMBER(20,4)）；可为空 | 现金流量表中，筹资活动现金流入合计与明细科目之间的差额；根据筹资活动现金流入平衡关系计算得出的因财报公布不平导致的差额； |
| NET_INCR_CASH_CASH_EQU | 现金及现金等价物净增加额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SEC_FA_NET_FINA_INSTRUMENTS | 以公允价值计量且其变动计入当期损益的金融工具净增加额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CASH_PAY_CLAIMS_ORIG_INCO | 支付原保险合同赔付款项的现金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CASH_CASH_EQU_BEG_PERIOD | 期初现金及现金等价物余额 | 数值（NUMBER(20,4)）；可为空 | 报表起始日期现金及融资期限为三个月或三个月内的，具有高度流动性且内购赚取利息的投资的余额；企业年初时的现金及现金等价物余额； |
| AMORT_INTANG_ASSETS | 无形资产摊销 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_BAL_NETCASH_INC | 现金净增加额合计（平衡口径） | 数值；可为空 | 财务报表平衡校验字段。 |
| NET_INCR_REPURCH_BUS_FUND | 回购业务资金净增加额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| INCL_CASH_REC_SAIMS | 其中:子公司吸收少数股东投资收到的现金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CASH_RECP_RETURN_INVEST | 取得投资收益收到的现金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CRNCY_CODE | 货币代码 | 字符串（VARCHAR2(10)）；可为空 | 原始字段，非本地计算。 |
| gmt_modified | GMT修改时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| END_BAL_CASH | 现金的期末余额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NET_CASH_FLOWS_OPER_ACT | 经营活动产生的现金流量净额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SPE_BAL_CASH_INFLOWS_INV | 投资活动现金流入差额(特殊报表科目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OBJECT_ID | 数据库记录对象ID | 字符串/整数；可为空 | 接口同步元数据。 |
| FIN_EXP | 财务费用 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NET_INCR_DEP_CBOB | 存放央行和同业款项净增加额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| IS_CALCULATION | 是否计算报表 | 0/1或空 | 原始字段，非本地计算。 |
| NET_CASH_RECP_DISP_SOBU | 处置子公司及其他营业单位收到的现金净额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SPE_BAL_CASH_OUTFLOWS_FNC | 筹资活动现金流出差额(特殊报表科目) | 数值（NUMBER(20,4)）；可为空 | 企业根据本身业务披露的，非万得标准的筹资活动现金流出科目明细；筹资活动现金流出中非标准科目的科目和金额； |
| OPDATE | 数据操作/入库时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| INCL_DVD_PROFIT_PAID_SC_MS | 分配股利、利润或偿付利息支付的现金 | 数值；可为空 | 现金流量表科目。 |
| NET_INCR_CLIENTS_LOAN_ADV | 客户贷款及垫款净增加额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CASH_RECP_BORROW | 取得借款收到的现金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OPMODE | 操作/写入模式 | 字符串；可为空 | 接口同步元数据。 |
| RIGHT_USE_ASSETS_DEP | 使用权资产折旧 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| MELT_MONEY_NET_INCREASE | 融出资金净增加额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NET_INCR_INSURED_DEP | 保户储金净增加额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CREDIT_IMPAIRMENT_LOSS | 信用减值损失 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_INFO_COMPCODE | Wind公司ID | 字符串；可为空 | 万得公司唯一编码。 |
| OTHER_ACCOUNTS | 其他会计科目 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_BAL_NETCASH_OUTFLOWS_OPER | 经营活动产生的现金流量净额差额(合计平衡项目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CASH_RECP_DISP_WITHDRWL_INVEST | 收回投资收到的现金 | 数值（NUMBER(20,4)）；可为空 | 反映企业出售、转让或者到期收回除现金等价物外的交易性金融资产、持有至到期投资、可供出售金融资产、长期股权投资等而收回的现金；反映企业出售、转让或到期收回除现金等价物以外的交易性金融资产、持有至到期投资 |
| EFF_FX_FLU_CASH | 汇率变动对现金的影响 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NET_INCR_DISP_TFA | 处置交易性金融资产净增加额 | 数值（NUMBER(20,4)）；可为空 | 企业对打算通过积极管理和交易获取利润的债券证券和权益证券的处置所产生的净增加额；反映证券公司本期自行买卖交易性金融资产所取得的现金净增加额； |
| CONV_CORP_BONDS_DUE_WITHIN_1Y | 一年内到期的可转换公司债券 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NET_INCR_FUND_BORR_OFI | 向其他金融机构拆入资金净增加额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| UNCONFIRMED_INVEST_LOSS | 未确认投资损失 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NET_CASH_RECP_DISP_FIOLTA | 处置固定资产、无形资产和其他长期资产收回的现金净额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| STOT_CASH_OUTFLOWS_FNC_ACT | 筹资活动现金流出小计 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OTHER_CASH_PAY_RAL_INV_ACT | 支付其他与投资活动有关的现金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OTHER_CASH_PAY_RAL_OPER_ACT | 支付其他与经营活动有关的现金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CASH_RECP_PREM_ORIG_INCO | 收到原保险合同保费取得的现金 | 数值（NUMBER(20,4)）；可为空 | 保险公司确认的，获取的根据原保险合同的保费收入；反映保险公司本期收取的原保险合同保费和再保险合同分保费款项； |
| OTHER_CASH_RECP_RAL_OPER_ACT | 收到其他与经营活动有关的现金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| INCR_ACC_EXP | 预提费用增加 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_BAL_CASH_OUTFLOWS_OPER | 经营活动现金流出差额(合计平衡项目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| INVEST_LOSS | 投资损失 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| LESS_BEG_BAL_CASH | 减:现金的期初余额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OTHER_IMPAIR_LOSS_ASSETS | 其他资产减值损失 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| ANN_DT | 公告日期 | YYYYMMDD字符串；可为空 | 原始字段，非本地计算。 |
| PLUS_END_BAL_CASH_EQU | 加:现金等价物的期末余额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| INCR_OPER_PAYABLE | 经营性应付项目的增加 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_BAL_NETCASH_INC_UNDIR | 未直接列示现金净增加额合计 | 数值；可为空 | 财务报表平衡校验字段。 |
| REPORT_PERIOD | 报告期 | YYYYMMDD字符串；可为空 | 原始字段，非本地计算。 |
| TOT_BAL_NETCASH_OUTFLOWS_INV | 投资活动产生的现金流量净额差额(合计平衡项目) | 数值（NUMBER(20,4)）；可为空 | 现金流量表中，投资活动产生的现金流量净额合计与明细科目之间的差额；按照科目明细项的公布值计算所得的科目值，与该科目公布值的差额，计入该指标； |
| NET_INCR_INT_HANDLING_CHRG | 收取利息和手续费净增加额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| LOSS_FV_CHG | 公允价值变动损失 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| STOT_CASH_INFLOWS_INV_ACT | 投资活动现金流入小计 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| DECR_DEFERRED_EXP | 待摊费用减少 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| LESS_BEG_BAL_CASH_EQU | 减:现金等价物的期初余额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| IM_NET_INCR_CASH_CASH_EQU | 间接法-现金及现金等价物净增加额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| ACTUAL_ANN_DT | 实际公告日期 | YYYYMMDD字符串；可为空 | 原始字段，非本地计算。 |
| SPE_BAL_NETCASH_INC | 现金净增加额差额(特殊报表科目) | 数值（NUMBER(20,4)）；可为空 | 企业根据本身业务披露的，非万得标准的现金净增加额科目明细；现金及现金等价物净增加额中非标准科目的科目和金额； |
| CASH_RECP_CAP_CONTRIB | 吸收投资收到的现金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OTHER_CASH_RECP_RAL_FNC_ACT | 收到其他与筹资活动有关的现金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SECURITIE_NETCASH_RECEIVED | 代理买卖证券收到的现金净额(元) | 数值（NUMBER(20,4)）；可为空；单位：元 | 原始字段，非本地计算。 |
| NET_CASH_PAY_AQUIS_SOBU | 取得子公司及其他营业单位支付的现金净额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| INCR_DEFERRED_INC_TAX_LIAB | 递延所得税负债增加 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_DISMANTLE_CAPITAL_ADD_NET | 拆出资金净增加额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| WIND_CODE | Wind代码 | Wind证券/指数代码字符串；可为空 | 原始字段，非本地计算。 |
| AMORT_LT_DEFERRED_EXP | 长期待摊费用摊销 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| COMP_TYPE_CODE | 公司类型代码 | 字符串（VARCHAR2(2)）；可为空 | 原始字段，非本地计算。 |
| NET_INCR_PLEDGE_LOAN | 质押贷款净增加额 | 数值；可为空 | 现金流量表科目。 |
| CASH_PAID_INVEST | 投资支付的现金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NET_CASH_FLOWS_INV_ACT | 投资活动产生的现金流量净额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_INFO_WINDCODE | Wind代码 | Wind证券/指数代码字符串；可为空 | 原始字段，非本地计算。 |
| STATEMENT_TYPE | 报表类型 | 字符串（VARCHAR2(10)）；可为空 | 原始字段，非本地计算。 |
| CASH_PAY_BEH_EMPL | 支付给职工以及为职工支付的现金 | 数值（NUMBER(20,4)）；可为空 | 企业实际支付给职工的现金以及为职工支付的现金，包括职工的工资、将近、各种津贴和补贴等；反映企业实际支付给职工的现金以及为职工支付的现金，包括企业为获得职工提供的服务，本期实际给予各种形式的报酬以及其它 |
| DECR_OPER_PAYABLE | 经营性应收项目的减少 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| PAY_ALL_TYP_TAX | 支付的各项税费 | 数值（NUMBER(20,4)）；可为空 | 企业支付的所得税、增值税、营业税、消费税、印花税、房产税、土地增值税、车船税、教育费附加、矿产资源补偿费等等费用的金额；反映企业按规定支付的各类税费，包括本期发生并支付的税费，以及本期支付以前各期发生 |
| HANDLING_CHRG_PAID | 支付手续费的现金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| STOT_CASH_OUTFLOWS_OPER_ACT | 经营活动现金流出小计 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| DECR_INVENTORIES | 存货的减少 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CONV_DEBT_INTO_CAP | 债务转为资本 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| gmt_created | GMT创建时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| SPE_BAL_CASH_OUTFLOWS_INV | 投资活动现金流出差额(特殊报表科目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| NET_INCR_DEP_COB | 客户存款和同业存放款项净增加额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SPE_BAL_NETCASH_INC_UNDIR | 间接法-现金净增加额差额(特殊报表科目) | 数值（NUMBER(20,4)）；可为空 | 企业根据本身业务披露的，非万得标准的间接法-现金净增加类科目明细；现金流量表补充数据中，现金及现金等价物净增加额中非标准科目的科目和金额； |
| NET_CASH_FLOWS_FNC_ACT | 筹资活动产生的现金流量净额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SPE_BAL_CASH_INFLOWS_FNC | 筹资活动现金流入差额(特殊报表科目) | 数值（NUMBER(20,4)）；可为空 | 企业根据本身业务披露的，非万得标准的筹资活动现金流入科目明细；筹资活动现金流入中非标准科目的科目和金额； |
| SPE_BAL_CASH_INFLOWS_OPER | 经营活动现金流入差额(特殊报表科目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| RECP_TAX_RENDS | 收到的税费返还 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_BAL_NETCASH_EQU_UNDIR | 未直接列示现金及现金等价物净增加额合计 | 数值；可为空 | 财务报表平衡校验字段。 |
| PROC_ISSUE_BONDS | 发行债券收到的现金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| FREE_CASH_FLOW | 企业自由现金流量(FCFF) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| LOSS_DISP_FIOLTA | 处置固定、无形资产和其他长期资产的损失 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OTHERS | 其他(废弃) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_BAL_CASH_OUTFLOWS_INV | 投资活动现金流出差额(合计平衡项目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_BAL_CASH_INFLOWS_INV | 投资活动现金流入差额(合计平衡项目) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |

### 表 16：财务指标

- 文件/目录：`stock/financial/indicators/indicators_<year>.csv`
- 文件数 / 行数 / 大小：17 / 309,515 / 401.45 MB
- 来源：Wind
- 状态：完整（截至 2026 中报）

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| S_FA_CAPITALIZEDTODA | , | 数值（NUMBER(20,4)）；可为空 | , |
| S_QFA_ROE | 单季度净资产收益率 | 数值；可为空 | ROE环比=(当前−上期)/abs(上期)×100。 |
| S_STM_BS | , | 数值（NUMBER(20,4)）；可为空 | , |
| S_FA_OPTOGR | , | 数值（NUMBER(20,4)）；可为空 | , |
| S_FA_BPS | , | 数值（NUMBER(20,4)）；可为空 | , |
| S_FA_ARTURN | , | 数值（NUMBER(20,4)）；可为空 | , |
| S_QFA_ROA | 单季度.总资产净利润 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_QFA_CGRSALES | 单季度.营业收入环比增长率(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| S_FA_TANGASSETTOINTDEBT | 有形资产/带息债务 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_DEBTTOEQUITY | 产权比率 | 数值（NUMBER(20,4)）；可为空 | 一般指负债权益比率反映债权人与股东提供的资本的相对比例，反映企业的资本结构是否合理、稳定，同时也表明债权人投入资本收到股东权益的保障程度；负债总额与股东权益总额之比率，也叫作债务权益比率，是衡量长期偿 |
| S_FA_OCFTOINTERESTDEBT | 经营活动产生的现金流量净额/带息债务 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_QFA_OCFTOOR | 单季度.经营活动产生的现金流量净额／经营活动净收益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_DEDUCTEDPROFITTOPROFIT | 扣除非经常损益后的净利润/净利润 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_PROFITTOOP | 利润总额／营业收入 | 数值（NUMBER(20,4)）；可为空 | 利润率，利润率反映企业一定时期利润水平的相对指标；利润总额与营业收入比值。 |
| S_FA_EBITDA | 息税折旧摊销前利润 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_TANGIBLEASSETTODEBT | 有形资产/负债合计 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_EBITTOINTEREST | 已获利息倍数(EBIT/利息费用) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_QFA_OPTOGR | 单季度.营业利润／营业总收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_QFA_YOYPROFIT | 单季度.净利润同比增长率(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| S_FA_GCTOGR | 营业总成本/营业总收入 | 数值（NUMBER(20,4)）；可为空 | 主要用于观察主营业务成本是否存在异常波动，还可以直接观察出利润变动的趋势，即指标的数值越大，利润就越少；营业总成本占营业总收入百分比； |
| S_FA_EBITTOGR | 息税前利润/营业总收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_ROA2 | 总资产报酬率 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_CASHRATIO | 保守速动比率 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| RD_EXPENSE | 研发费用 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_ROA | 总资产净利率 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_DEDUCTEDPROFIT | 扣除非经常性损益后的净利润(扣除少数股东损益) | 数值（NUMBER(20,4)）；可为空；单位：扣除少数股 | 原始字段，非本地计算。 |
| S_FA_TAXTOEBT | 所得税/利润总额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_RETAINEDEARNINGS | 留存收益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_NOPTOEBT | 非营业利润／利润总额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_ROIC | 投入资本回报率 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_OCFTOSHORTDEBT | 经营活动产生的现金流量净额/流动负债 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_CURRENT | 流动比率 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_QFA_YOYGR | 单季度.营业总收入同比增长率(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| S_FA_ROE | 净资产收益率 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_YOYNETPROFIT | 同比增长率-归属母公司股东的净利润(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| S_FA_CURRENTDEBTTODEBT | 流动负债/负债合计 | 数值（NUMBER(20,4)）；可为空 | 流动负债占负债合计的比重，反映流动性负债占整体负债的情况；流动负债与负债合计的比值，反映债务结构的指标； |
| S_FA_FATURN | 固定资产周转率 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_QFA_YOYOP | 单季度.营业利润同比增长率(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| S_FA_CATURN | 流动资产周转率 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_NETWORKINGCAPITAL | 营运流动资本 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_YOYOCF | 同比增长率-经营活动产生的现金流量净额(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| S_FA_INTDEBTTOTOTALCAP | 带息债务/全部投入资本 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_QFA_OCFTOSALES | 单季度.经营活动产生的现金流量净额／营业收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_EPS_BASIC | 基本每股收益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_QUICK | 速动比率 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_INTERESTDEBT | 带息债务 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_TANGIBLEASSET | 有形资产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_EXTRAORDINARY | 非经常性损益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_CFPS | 每股现金流量净额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_GROSSPROFITMARGIN | 销售毛利率 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_OCFTOOPERATEINCOME | 经营活动产生的现金流量净额/经营活动净收益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| CRNCY_CODE | 货币代码 | 字符串（VARCHAR2(10)）；可为空 | 原始字段，非本地计算。 |
| S_FA_YOYASSETS | 相对年初增长率-资产总计(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| gmt_modified | GMT修改时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_FA_YOY_TR | 营业总收入同比增长率(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| S_QFA_EXPENSETOSALES | 单季度费用/营业收入 | 数值；可为空 | 单季度财务比率。 |
| S_FA_OPERATEINCOME | 经营活动净收益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OBJECT_ID | 数据库记录对象ID | 字符串/整数；可为空 | 接口同步元数据。 |
| S_FA_LONGDEBTTOWORKINGCAPITAL | 长期债务与营运资金比率 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_QFA_IMPAIRTOGR_TTM | 单季度.资产减值损失／营业总收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_EBIT | 息税前利润 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OPDATE | 数据操作/入库时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_FA_OPERATEINCOMETOEBT | 经营活动净收益/利润总额 | 数值（NUMBER(20,4)）；可为空 | 判断企业收益质量的指标，企业生产经营收入扣除生产成本和运营成本后的盈利，反映企业实体经营的获利能力；企业生产经营收入扣减生产成本和运营成本后的盈利与利润总额的比值； |
| S_FA_CATOASSETS | 流动资产/总资产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OPMODE | 操作/写入模式 | 字符串；可为空 | 接口同步元数据。 |
| S_FA_YOY_EQUITY | 净资产(同比增长率) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_OCFTONETDEBT | 经营活动产生的现金流量净额/净债务 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_TOT_FATURN | 固定资产合计周转率 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_TANGIBLEASSETSTOASSETS | 有形资产/总资产 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_NETDEBT | 净债务 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_STMNOTE_FINEXP | 利息费用 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_QFA_DEDUCTEDPROFIT | 单季度扣除非经常性损益后净利润 | 数值；可为空 | 单季度财务指标。 |
| S_FA_YOYEQUITY | 相对年初增长率-归属母公司股东的股东权益(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| S_INFO_COMPCODE | 公司ID | 字符串（VARCHAR2(10)）；可为空 | 原始字段，非本地计算。 |
| S_FA_EQUITYTOINTERESTDEBT | 归属于母公司的股东权益/带息债务 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_INVESTINCOMETOEBT | 价值变动净收益/利润总额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_YOYOP | 同比增长率-营业利润(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| S_FA_EPS_DILUTED2 | 期末摊薄每股收益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_QFA_CGRNETPROFIT | 单季度.归属母公司股东的净利润环比增长率(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| S_FA_OPTOEBT | 营业利润／利润总额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_OCFTOPROFIT | 经营活动产生的现金流量净额／营业利润 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_NONOPERATEPROFITTOEBT | 营业外收支净额/利润总额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_QFA_SALEEXPENSETOGR | 单季度.销售费用／营业总收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_QFA_YOYSALES | 单季度.营业收入同比增长率(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| S_STM_IS | 折旧与摊销 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_ASSETSTOEQUITY | 权益乘数 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_FINAEXPENSETOGR | 财务费用/营业收入 | 数值；可为空 | 财务比率。 |
| S_QFA_CGRPROFIT | 单季度.净利润环比增长率(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| S_FA_ROE_AVG | 平均净资产收益率(增发条件) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_DEBTTOASSETS | 资产负债率 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_EXINTERESTDEBT_NONCURRENT | 无息非流动负债 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_OCFPS | 每股经营活动产生的现金流量净额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_EQUITYTOTOTALCAPITAL | 归属于母公司的股东权益/全部投入资本 | 数值（NUMBER(20,4)）；可为空 | 归属于母公司的股东权益占全部投入资本的比重；归属于母公司的股东权益与全部投入资本的比值； |
| S_FA_LONGDEBTODEBT | 非流动负债/负债合计 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_SALESCASHINTOOR | 销售商品提供劳务收到的现金/营业收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_QFA_ROE_DEDUCTED | 单季度.净资产收益率(扣除非经常损益) | 数值（NUMBER(24,6)）；可为空 | 在某个单季度内扣除非经常性损益后的净利润与平均净资产的比率；按单季度统计的扣除非经常损益的净资产收益率； |
| ANN_DT | 公告日期 | YYYYMMDD字符串；可为空 | 原始字段，非本地计算。 |
| S_FA_PREFINEXPENSE_OPPROFIT | 扣除财务费用前营业利润 | 数值（NUMBER(20,4)）；可为空 | 企业扣除财务费用前的营业利润；报告期内不扣除财务费用的营业利润。 |
| S_FA_YOYEBT | 同比增长率-利润总额(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| S_QFA_INVESTINCOMETOEBT | 单季度.价值变动净收益／利润总额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| REPORT_PERIOD | 报告期 | YYYYMMDD字符串；可为空 | 原始字段，非本地计算。 |
| S_FA_EBITDATODEBT | 息税折旧摊销前利润/负债合计 | 数值（NUMBER(20,4)）；可为空 | 息税折旧摊销前利润占负债合计的比，反映企业偿债能力的指标；息税折旧摊销前利润与债务总额的比值该比值如果等于1代表企业当期全部经营收益(未计提折旧和摊销)刚好用来偿债； |
| S_QFA_OPERATEINCOME | 单季度.经营活动净收益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_YOYEPS_DILUTED | 同比增长率-稀释每股收益(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| S_FA_SURPLUSCAPITALPS | 每股资本公积 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_EBITPS | 每股息税前利润 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_CASHTOLIQDEBT | 货币资金／流动负债 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_NONOPPROFIT | 非营业利润 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_QFA_FINAEXPENSETOGR | 单季度财务费用/营业收入 | 数值；可为空 | 单季度财务比率。 |
| S_FA_OCFTOOR | 经营活动产生的现金流量净额/营业收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_NETPROFITMARGIN | 销售净利率 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_INVTURN | 存货周转率 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_FCFEPS | 每股股东自由现金流量 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_ASSETSTURN | 总资产周转率 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_YOY_OR | 营业收入同比增长率(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| S_FA_FCFE | 股权自由现金流量(FCFE) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_FCFF | 企业自由现金流量(FCFF) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_EQUITYTODEBT | 归属于母公司的股东权益/负债合计 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_QFA_DEDUCTEDPROFITTOPROFIT | 单季度.扣除非经常损益后的净利润／净利润 | 数值（NUMBER(20,4)）；可为空 | 该单季度扣除非经常损益后的净利润占净利润的比重，反映企业正常经营收入产生的净利润所占比重；按单季度统计的扣除非经常损益后的净利润与净利润的比值； |
| S_QFA_CGROP | 单季度.营业利润环比增长率(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| S_QFA_INVESTINCOME | 单季度.价值变动净收益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_NCATOASSETS | 非流动资产/总资产 | 数值（NUMBER(20,4)）；可为空 | 非流动资产占总资产的比重，一般来说比重越大，则公司的运营空间越大；非流动资产与总资产的比值，反映总资产构成的指标； |
| S_QFA_SALESCASHINTOOR | 单季度.销售商品提供劳务收到的现金／营业收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_SURPLUSRESERVEPS | 每股盈余公积 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_QFA_CGRGR | 单季度.营业总收入环比增长率(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| S_FA_INVESTCAPITAL | 全部投入资本 | 数值（NUMBER(20,4)）；可为空 | 股东权益(不含少数股东权益)+负债合计-无息流动负债-无息长期负债；所有投资者(股权人、债权人)投入的资金总和，这些资金都是意图分享企业经营回报的投入资本与总资产的核心差别在于投资资本中不包括无息负债 |
| S_FA_GRPS | 每股营业总收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_EXPENSETOSALES | 销售期间费用率 | 数值（NUMBER(20,4)）；可为空 | 企业期间费用与销售收入净额之间的比率该指标越低越好，当销售期间费用率大于销售毛利率时，说明企业盈利相当困难；反映生产成本以外的企业运营费用率； |
| S_FA_ROIC_YEARLY | 年化投入资本回报率 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_ORPS | 每股营业收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_CASHTOLIQDEBTWITHINTEREST | 货币资金／带息流动负债 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_INVTURNDAYS | 存货周转天数 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_QFA_GROSSPROFITMARGIN | 单季度销售毛利率 | 数值；单位：%；可为空 | 毛利率变化=当前−上期。 |
| S_FA_YOYOCFPS | 同比增长率-每股经营活动产生的现金流量净额(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| S_FA_TURNDAYS | 营业周期 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| WIND_CODE | Wind代码（上同） | Wind证券/指数代码字符串；可为空 | 原始字段，非本地计算。 |
| S_FA_YOYROE | 同比增长率-净资产收益率(摊薄)(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| S_QFA_GCTOGR | 单季度.营业总成本／营业总收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_YOYNETPROFIT_DEDUCTED | 扣非净利润同比增长率 | 数值；单位：%；可为空 | 财务增长指标。 |
| WAA_ROE | 加权平均净资产收益率 | 数值（NUMBER(24,6)）；可为空 | 原始字段，非本地计算。 |
| S_QFA_NETPROFITMARGIN | 单季度.销售净利率 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_ROA2_YEARLY | 年化总资产报酬率 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_QFA_OPERATEINCOMETOEBT | 单季度.经营活动净收益／利润总额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_INFO_WINDCODE | Wind代码 | Wind证券/指数代码字符串；可为空 | 原始字段，非本地计算。 |
| S_QFA_YOYNETPROFIT | 单季度归母净利润同比增长率 | 数值；单位：%；可为空 | G1=(当前−前8期均值)/前8期标准差。 |
| S_FA_ROA_YEARLY | 年化总资产净利率 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_OPTOLIQDEBT | 营业利润／流动负债 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_OCFTODEBT | 经营活动产生的现金流量净额/负债合计 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_INVESTINCOME | 价值变动净收益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_ROE_YEARLY | 年化净资产收益率 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| STATEMENT_TYPE | 报表类型 | 字符串（VARCHAR2(80)）；可为空 | 原始字段，非本地计算。 |
| S_FA_SALEEXPENSETOGR | 销售费用/营业收入 | 数值；可为空 | 财务比率。 |
| S_FA_DUPONT_ROA | 总资产净利率(杜邦分析) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_WORKINGCAPITAL | 营运资金 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| gmt_created | GMT创建时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_FA_GROSSMARGIN | 毛利 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_YOYEPS_BASIC | 同比增长率-基本每股收益(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| S_FA_ADMINEXPENSETOGR | 管理费用/营业收入 | 数值；可为空 | 财务比率。 |
| S_FA_ARTURNDAYS | 应收账款周转天数 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_YOYBPS | 相对年初增长率-每股净资产(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| S_QFA_EPS | 单季度.每股收益 | 数值（NUMBER(24,6)）；可为空 | 原始字段，非本地计算。 |
| S_FA_EPS_DILUTED | 稀释每股收益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_IMPAIRTOGR_TTM | 资产减值损失/营业总收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_FCFFPS | 每股企业自由现金流量 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_PROFITTOGR | 净利润/营业总收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_EXINTERESTDEBT_CURRENT | 无息流动负债 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_TANGIBLEASSETTONETDEBT | 有形资产/净债务 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_UNDISTRIBUTEDPS | 每股未分配利润 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_ROE_DEDUCTED | 净资产收益率(扣除非经常损益) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_QFA_PROFITTOGR | 单季度.净利润／营业总收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_RETAINEDPS | 每股留存收益 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_COGSTOSALES | 销售成本率 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_DUPONT_ASSETSTOEQUITY | 权益乘数(用于杜邦分析) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_QFA_ADMINEXPENSETOGR | 单季度.管理费用／营业总收入 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_FA_OPTODEBT | 营业利润／负债合计 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |

## 六、一致预期与评级

### 表 17：投资评级汇总

- 文件/目录：`stock/ratings/ratings_<year>.csv`
- 文件数 / 行数 / 大小：17 / 2,522,378 / 360.25 MB
- 来源：Wind
- 状态：完整

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| S_WRATING_UPGRADE | 调高家数（相比一月前） | 数值（NUMBER(20,4)）；可为空；单位：相比一月 | 原始字段，非本地计算。 |
| S_WRATING_NUMOFHOLD | 中性家数 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_WRATING_NUMOFUNDERPERFORM | 减持家数 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_WRATING_AVG | 综合评级 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_WRATING_NUMOFBUY | 买入家数 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_EST_PRICEINSTNUM | 目标价预测机构数 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_EST_PRICE | 一致预测目标价 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| gmt_modified | GMT修改时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_WRATING_MAINTAIN | 维持家数（相比一月前） | 数值（NUMBER(20,4)）；可为空；单位：相比一月 | 原始字段，非本地计算。 |
| RATING_DT | 日期 | 字符串；可为空 | 原始字段，非本地计算。 |
| S_INFO_WINDCODE | Wind代码 | Wind证券/指数代码字符串；可为空 | 原始字段，非本地计算。 |
| S_WRATING_NUMOFSELL | 卖outfile | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_WRATING_INSTNUM | 评级机构数量 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_WRATING_DOWNGRADE | 调低家数（相比一月前） | 数值（NUMBER(20,4)）；可为空；单位：相比一月 | 原始字段，非本地计算。 |
| OBJECT_ID | 数据库记录对象ID | 字符串/整数；可为空 | 接口同步元数据。 |
| S_WRATING_CYCLE | 周期 | 字符串（VARCHAR2(10)）；可为空 | 原始字段，非本地计算。 |
| OPDATE | 数据操作/入库时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_WRATING_NUMOFOUTPERFORM | 增持家数 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OPMODE | 操作/写入模式 | 字符串；可为空 | 接口同步元数据。 |
| gmt_created | GMT创建时间 | 时间戳字符串；可为空 | 接口同步元数据。 |

### 表 18：Wind一致预测个股指标

- 文件/目录：`stock/consensus/wind/wind_<year>.csv`
- 文件数 / 行数 / 大小：17 / 2,620,283 / 205.77 MB
- 来源：Wind via内部网关
- 状态：完整

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| ann_dt | 日期 | YYYYMMDD字符串；可为空 | 日期 |
| stock_code | 股票代码 | Wind证券/指数代码字符串；可为空 | 股票代码 |
| con_date | 日期 | YYYYMMDD字符串；可为空 | 日期 |
| est_report_dt | 报告期 | YYYYMMDD字符串；可为空 | 报告期 |
| prediction_number | 预测家数 | 非负整数；可为空 | 预测家数 |
| est_eps | 每股收益 | 数值；可为空 | 每股收益 |
| est_oper_revenue | 主营业务收入 | 数值；可为空 | 主营业务收入 |
| net_profit | 净利润 | 数值；可为空 | 净利润 |
| est_eps_max | 每股收益最大值 | 数值；可为空 | 每股收益最大值 |
| est_eps_min | 每股收益最小值 | 数值；可为空 | 每股收益最小值 |

### 表 19：朝阳永续一致预期

- 文件/目录：`stock/consensus/suntime/suntime_<year>.csv`
- 文件数 / 行数 / 大小：17 / 57,904,264 / 7997.82 MB
- 来源：朝阳永续 via内部网关
- 状态：完整

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| stock_code | 股票代码 | Wind证券/指数代码字符串；可为空 | 股票代码 |
| con_date | 一致预期日期 | YYYYMMDD字符串；可为空 | 一致预期日期 |
| con_year | 一致预期年度 | 整数；可为空 | 一致预期年度 |
| con_or | 一致预期营业收入 | 数值；可为空 | 一致预期营业收入 |
| con_np | 一致预期净利润 | 数值；可为空 | 一致预期净利润 |
| con_eps | 一致预期每股收益 | 数值；可为空 | 一致预期每股收益 |
| con_na | 一致预期净资产 | 数值；可为空 | 一致预期净资产 |
| con_pb | 一致预期市净率 | 数值；可为空 | 一致预期市净率 |
| con_ps | 一致预期市销率 | 数值；可为空 | 一致预期市销率 |
| con_pe | 一致预期市盈率 | 数值；可为空 | 一致预期市盈率 |
| con_peg | 一致预期PEG | 数值；可为空 | 一致预期PEG |
| con_roe | 一致预期净资产收益率 | 数值；单位：%；可为空 | G4=(次年−当年)/abs(当年)×100。 |
| con_or_yoy | 一致预期营业收入同比 | 数值；可为空 | 一致预期营业收入同比 |
| con_np_yoy | 一致预期净利润同比 | 数值；可为空 | 一致预期净利润同比 |
| con_npcgrate_2y | 一致预期净利润两年复合增长率 | 数值；单位：%；可为空 | G3直接取最新快照。 |
| con_npgrate_1w | 1周一致预期净利润变化率 | 数值；可为空 | 1周一致预期净利润变化率 |
| con_npgrate_4w | 4周一致预期净利润变化率 | 数值；可为空 | 4周一致预期净利润变化率 |
| con_npgrate_13w | 13周一致预期净利润变化率 | 数值；单位：%；可为空 | G2直接取最新快照。 |
| con_npgrate_26w | 26周一致预期净利润变化率 | 数值；可为空 | 26周一致预期净利润变化率 |

## 七、行业与证券主数据

### 表 20：行业分类（当前）

- 文件/目录：`stock/industry/current_industry.csv`
- 文件数 / 行数 / 大小：1 / 8,817 / 3.51 MB
- 来源：内部taidb
- 状态：当前快照

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| hs_industry_code3 | 恒生行业三级代码 | 行业代码字符串 | 行业归属字段。 |
| hs_industry_code2 | 恒生行业二级代码 | 行业代码字符串 | 行业归属字段。 |
| sw_industry_name1 | 申万行业一级名称 | 行业名称字符串 | 行业归属字段。 |
| hs_industry_code1 | 恒生行业一级代码 | 行业代码字符串 | 行业归属字段。 |
| sw_industry_name2 | 申万行业二级名称 | 行业名称字符串 | 行业归属字段。 |
| sw_industry_name3 | 申万行业三级名称 | 行业名称字符串 | 行业归属字段。 |
| hs_industry_name1 | 恒生行业一级名称 | 行业名称字符串 | 行业归属字段。 |
| hs_industry_name2 | 恒生行业二级名称 | 行业名称字符串 | 行业归属字段。 |
| hs_industry_name3 | 恒生行业三级名称 | 行业名称字符串 | 行业归属字段。 |
| sw_industry_code3 | 申万行业三级代码 | 行业代码字符串 | 行业归属字段。 |
| wind_industry_code1 | Wind行业一级代码 | 行业代码字符串 | 行业归属字段。 |
| tk_industry_code | 权益泰康行业一级代码 | 行业代码字符串 | 内部行业口径。 |
| wind_industry_code2 | Wind行业二级代码 | 行业代码字符串 | 行业归属字段。 |
| wind_industry_code3 | Wind行业三级代码 | 行业代码字符串 | 行业归属字段。 |
| wind_industry_code4 | Wind行业四级代码 | 行业代码字符串 | 行业归属字段。 |
| security_name | 证券名称 | 证券名称字符串 | 行业归属字段。 |
| citics_industry_code1 | 中信行业一级代码 | 行业代码字符串 | 行业归属字段。 |
| citics_industry_code2 | 中信行业二级代码 | 行业代码字符串 | 行业归属字段。 |
| stib_industry_name1 | 战略性新兴行业一级名称 | 行业名称字符串 | 行业归属字段。 |
| citics_industry_code3 | 中信行业三级代码 | 行业代码字符串 | 行业归属字段。 |
| stib_industry_name2 | 战略性新兴行业二级名称 | 行业名称字符串 | 行业归属字段。 |
| csrc_industry_name3 | 证监会行业三级名称 | 行业名称字符串 | 行业归属字段。 |
| gics_industry_code2 | GICS行业二级代码 | 行业代码字符串 | 行业归属字段。 |
| csrc_industry_name2 | 证监会行业二级名称 | 行业名称字符串 | 行业归属字段。 |
| gics_industry_code1 | GICS行业一级代码 | 行业代码字符串 | 行业归属字段。 |
| gics_industry_code4 | GICS行业四级代码 | 行业代码字符串 | 行业归属字段。 |
| gics_industry_code3 | GICS行业三级代码 | 行业代码字符串 | 行业归属字段。 |
| csrc_industry_name1 | 证监会行业一级名称 | 行业名称字符串 | 行业归属字段。 |
| sw_index_code3 | 申万行业三级对应指数代码 | 行业指数代码字符串 | 行业到指数映射。 |
| citics_industry_name1 | 中信行业一级名称 | 行业名称字符串 | 行业归属字段。 |
| tk_industry_name | 权益泰康行业一级名称 | 行业名称字符串 | 内部行业口径。 |
| sw_index_code2 | 申万行业二级对应指数代码 | 行业指数代码字符串 | 行业到指数映射。 |
| citics_industry_name2 | 中信行业二级名称 | 行业名称字符串 | 行业归属字段。 |
| sw_index_code1 | 申万行业一级对应指数代码 | 行业指数代码字符串 | 行业到指数映射。 |
| citics_industry_name3 | 中信行业三级名称 | 行业名称字符串 | 行业归属字段。 |
| wind_index_code2 | Wind行业二级对应指数代码 | 行业指数代码字符串 | 行业到指数映射。 |
| csrc_industry_code1 | 证监会行业一级代码 | 行业代码字符串 | 行业归属字段。 |
| wind_index_code1 | Wind行业一级对应指数代码 | 行业指数代码字符串 | 行业到指数映射。 |
| csrc_industry_code2 | 证监会行业二级代码 | 行业代码字符串 | 行业归属字段。 |
| wind_index_code4 | Wind行业四级对应指数代码 | 行业指数代码字符串 | 行业到指数映射。 |
| gics_industry_name3 | GICS行业三级名称 | 行业名称字符串 | 行业归属字段。 |
| csrc_industry_code3 | 证监会行业三级代码 | 行业代码字符串 | 行业归属字段。 |
| wind_index_code3 | Wind行业三级对应指数代码 | 行业指数代码字符串 | 行业到指数映射。 |
| gics_industry_name4 | GICS行业四级名称 | 行业名称字符串 | 行业归属字段。 |
| gics_industry_name1 | GICS行业一级名称 | 行业名称字符串 | 行业归属字段。 |
| gics_industry_name2 | GICS行业二级名称 | 行业名称字符串 | 行业归属字段。 |
| cs_citics_index_code3 | 中信行业三级对应指数代码（中证编制） | 行业指数代码字符串 | 行业到指数映射。 |
| wind_csrc_index_code2 | 证监会行业二级对应指数代码（Wind编制） | 行业指数代码字符串 | 行业到指数映射。 |
| wind_csrc_index_code1 | 证监会行业一级对应指数代码（Wind编制） | 行业指数代码字符串 | 行业到指数映射。 |
| wind_csrc_index_code3 | 证监会行业三级对应指数代码（Wind编制） | 行业指数代码字符串 | 行业到指数映射。 |
| stock_code | 股票代码 | 股票代码字符串 | 行业归属主键。 |
| cs_citics_index_code1 | 中信行业一级对应指数代码（中证编制） | 行业指数代码字符串 | 行业到指数映射。 |
| cs_citics_index_code2 | 中信行业二级对应指数代码（中证编制） | 行业指数代码字符串 | 行业到指数映射。 |
| cs_csrc_index_code1 | 证监会行业一级对应指数代码（中证编制） | 行业指数代码字符串 | 行业到指数映射。 |
| cs_csrc_index_code2 | 证监会行业二级对应指数代码（中证编制） | 行业指数代码字符串 | 行业到指数映射。 |
| cs_csrc_index_code3 | 证监会行业三级对应指数代码（中证编制） | 行业指数代码字符串 | 行业到指数映射。 |
| sw_industry_code2 | 申万行业二级代码 | 行业代码字符串 | 行业归属字段。 |
| sw_industry_code1 | 申万行业一级代码 | 行业代码字符串 | 行业归属字段。 |
| wind_citics_index_code2 | 中信行业二级对应指数代码（Wind编制） | 行业指数代码字符串 | 行业到指数映射。 |
| wind_industry_name1 | Wind行业一级名称 | 行业名称字符串 | 行业归属字段。 |
| wind_citics_index_code1 | 中信行业一级对应指数代码（Wind编制） | 行业指数代码字符串 | 行业到指数映射。 |
| wind_industry_name2 | Wind行业二级名称 | 行业名称字符串 | 行业归属字段。 |
| wind_industry_name3 | Wind行业三级名称 | 行业名称字符串 | 行业归属字段。 |
| wind_industry_name4 | Wind行业四级名称 | 行业名称字符串 | 行业归属字段。 |
| stib_industry_code1 | 战略性新兴行业一级代码 | 行业代码字符串 | 行业归属字段。 |
| wind_citics_index_code3 | 中信行业三级对应指数代码（Wind编制） | 行业指数代码字符串 | 行业到指数映射。 |
| stib_industry_code2 | 战略性新兴行业二级代码 | 行业代码字符串 | 行业归属字段。 |
| hs_index_code3 | 恒生行业三级对应指数代码 | 行业指数代码字符串 | 行业到指数映射。 |
| hs_index_code2 | 恒生行业二级对应指数代码 | 行业指数代码字符串 | 行业到指数映射。 |
| hs_index_code1 | 恒生行业一级对应指数代码 | 行业指数代码字符串 | 行业到指数映射。 |

### 表 21：行业分类（历史）

- 文件/目录：`stock/industry/industry_history.csv`
- 文件数 / 行数 / 大小：1 / 33,475 / 2.13 MB
- 来源：内部taidb
- 状态：历史归属

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| end_date | 截止日期 | 字符串（字符串）；可为空 | 截止日期 |
| ind_class_code | 行业代码 | 字符串（字符串）；可为空 | 行业代码 |
| industry_class_name | 行业分类名称 | 字符串（字符串）；可为空 | 行业分类名称 |
| begin_date | 开始日期 | 字符串（字符串）；可为空 | 开始日期 |
| industry_class_code | CITICS | 字符串（字符串）；可为空 | CITICS |
| cur_sign | 最新标志 | 0/1或空 | 原始字段，非本地计算。 |
| stock_code | 股票代码 | 股票代码字符串 | 行业归属主键。 |

### 表 22：证券主数据

- 文件/目录：`stock/meta/basic_desc.csv`
- 文件数 / 行数 / 大小：1 / 5,107 / 0.98 MB
- 来源：内部taidb
- 状态：可用

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| country | 国家及地区代码 | 字符串（字符串）；可为空 | 国家及地区代码 |
| is_st_flag | 是否ST股票：1 是ST <br>0 不是ST,非A股为空 | 0非ST/1ST/空 | 是否ST股票：1 是ST <br>0 不是ST,非A股为空 |
| stock_fname | 证券中文全称 | 字符串（字符串）；可为空 | 证券中文全称 |
| cmp_full_name | 公司全称 | 字符串（字符串）；可为空 | 公司全称 |
| ISINCODE | ISIN代码 | 字符串（字符串）；可为空 | ISIN代码 |
| s_info_listboardname | 上市板 | 字符串（字符串）；可为空 | 上市板 |
| market_code | 交易所 | 字符串（字符串）；可为空 | 交易所 |
| LISTDATE | 上市日期 | YYYYMMDD字符串；可为空 | 上市日期 |
| cmp_code_fin | 财汇公司代码 | 字符串（字符串）；可为空 | 财汇公司代码 |
| cmp_name_eng | 公司英文名 | 字符串（字符串）；可为空 | 公司英文名 |
| S_INFO_LISTBOARD | 上市板类型 | 字符串（字符串）；可为空 | 上市板类型 |
| IS_SHSC | 是否在沪股通或深股通范围内，A股：0:否;1:沪股通;2:深股通,港股：NULL | 0否/1沪股通/2深股通/空 | 是否在沪股通或深股通范围内，A股：0:否;1:沪股通;2:深股通,港股：NULL |
| IS_H | 是否是H股，A股：NULL,港股：0:否;1:是 | 0/1或空 | 是否是H股，A股：NULL,港股：0:否;1:是 |
| cmp_code_wind | wind公司代码 | Wind证券/指数代码字符串；可为空 | wind公司代码 |
| market_region | 股票上市地区 | 字符串（字符串）；可为空 | 股票上市地区 |
| S_INFO_STATUS | 存续状态 | 字符串（字符串）；可为空 | 存续状态 |
| stock_sname | 证券中文简称 | 字符串（字符串）；可为空 | 证券中文简称 |
| DELISTDATE | 退市日期 | YYYYMMDD字符串；可为空 | 退市日期 |
| stock_code | 股票代码（A H 股） | Wind证券/指数代码字符串；可为空 | 股票代码（A H 股） |
| security_name_pinyin_short | 证券名称拼音缩写 | 字符串（字符串）；可为空 | 证券名称拼音缩写 |

### 表 23：代码变更

- 文件/目录：`stock/meta/code_change.csv`
- 文件数 / 行数 / 大小：1 / 3,486 / 0.13 MB
- 来源：内部taidb
- 状态：可用

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| s_info_oldwindcode | 变更前代码 | Wind证券/指数代码字符串；可为空 | 变更前代码 |
| s_info_newwindcode | 变更后代码 | Wind证券/指数代码字符串；可为空 | 变更后代码 |
| s_info_windcode | Wind代码 | Wind证券/指数代码字符串；可为空 | Wind代码 |
| change_date | 代码变更日期 | YYYYMMDD字符串；可为空 | 代码变更日期 |

## 八、股权、融资与资金流

### 表 24：自由流通股本

- 文件/目录：`stock/ownership/free_float_<year>.csv`
- 文件数 / 行数 / 大小：17 / 198,957 / 23.28 MB
- 来源：Wind
- 状态：完整

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| S_INFO_WINDCODE | Wind代码 | Wind证券/指数代码字符串；可为空 | 万得证券唯一编码。 |
| OBJECT_ID | 数据库记录对象ID | 字符串/整数；可为空 | 接口同步元数据。 |
| ANN_DT | 公告日期 | YYYYMMDD字符串；可为空 | 原始字段，非本地计算。 |
| CHANGE_DT1 | 变动日期(上市日) | YYYYMMDD字符串；可为空 | 原始字段，非本地计算。 |
| CHANGE_DT | 变动日期(除权日) | YYYYMMDD字符串；可为空 | 原始字段，非本地计算。 |
| S_SHARE_FREESHARES | 自由流通股本(万股) | 数值（NUMBER(24,8)）；可为空；单位：万股 | 原始字段，非本地计算。 |
| OPDATE | 数据操作/入库时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| gmt_modified | GMT修改时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| OPMODE | 操作/写入模式 | 字符串；可为空 | 接口同步元数据。 |
| gmt_created | GMT创建时间 | 时间戳字符串；可为空 | 接口同步元数据。 |

### 表 25：股东户数

- 文件/目录：`stock/ownership/holder_number_<year>.csv`
- 文件数 / 行数 / 大小：17 / 459,734 / 51.84 MB
- 来源：Wind
- 状态：完整

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| S_INFO_WINDCODE | Wind代码 | Wind证券/指数代码字符串；可为空 | 原始字段，非本地计算。 |
| S_HOLDER_ENDDATE | 截止日期 | YYYYMMDD字符串；可为空 | 原始字段，非本地计算。 |
| S_HOLDER_NUM | A股股东户数 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OBJECT_ID | 数据库记录对象ID | 字符串/整数；可为空 | 接口同步元数据。 |
| ANN_DT | 公告日期 | YYYYMMDD字符串；可为空 | 原始字段，非本地计算。 |
| OPDATE | 数据操作/入库时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_HOLDER_TOTAL_NUM | 股东总户数 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| gmt_modified | GMT修改时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| OPMODE | 操作/写入模式 | 字符串；可为空 | 接口同步元数据。 |
| gmt_created | GMT创建时间 | 时间戳字符串；可为空 | 接口同步元数据。 |

### 表 26：融资融券明细

- 文件/目录：`stock/ownership/margin_trade_<year>.csv`
- 文件数 / 行数 / 大小：17 / 6,787,030 / 1411.02 MB
- 来源：Wind
- 状态：完整

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| TRADE_DT | 日期 | 字符串；可为空 | 利率公布日期 |
| S_REFIN_SB_VOL_3D | 转融券融入数量(3天) | 数值（NUMBER(20,0)）；可为空；单位：3天 | 原始字段，非本地计算。 |
| S_REFIN_SB_VOL_14D | 转融券融入数量(14天) | 数值（NUMBER(20,0)）；可为空；单位：14天 | 原始字段，非本地计算。 |
| S_MARGIN_SECLENDINGBALANCEVOL | 高精度浮点型 | 字符串；可为空 | 融券余量（股,份,手） |
| S_MARGIN_REPAYMENTOFBORROWSEC | 融券偿还量(股,份,手) | 数值（NUMBER(20,4)）；可为空；单位：股 | 原始字段，非本地计算。 |
| S_MARGIN_MARGINTRADEBALANCE | 融资融券余额(元) | 数值（NUMBER(20,4)）；可为空；单位：元 | 原始字段，非本地计算。 |
| S_REFIN_SB_VOL_7D | 转融券融入数量(7天) | 数值（NUMBER(20,0)）；可为空；单位：7天 | 原始字段，非本地计算。 |
| gmt_modified | GMT修改时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_INFO_WINDCODE | Wind代码 | Wind证券/指数代码字符串；可为空 | 原始字段，非本地计算。 |
| S_SB_VOL_28D | 转融券融入数量(28天) | 数值（NUMBER(20,0)）；可为空；单位：28天 | 原始字段，非本地计算。 |
| OBJECT_ID | 数据库记录对象ID | 字符串/整数；可为空 | 接口同步元数据。 |
| OPDATE | 数据操作/入库时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_REFIN_SL_VOL_28D | 转融券融出数量(28天) | 数值（NUMBER(20,0)）；可为空；单位：28天 | 原始字段，非本地计算。 |
| S_SB_VOL_182D | 转融券融入数量(182天) | 数值（NUMBER(20,0)）；可为空；单位：182天 | 原始字段，非本地计算。 |
| OPMODE | 操作/写入模式 | 字符串；可为空 | 接口同步元数据。 |
| gmt_created | GMT创建时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| S_MARGIN_SALESOFBORROWEDSEC | 融券卖出量(股,份,手) | 数值（NUMBER(20,4)）；可为空；单位：股 | 原始字段，非本地计算。 |
| S_MARGIN_SALETRADINGAMOUNT | 融券卖出额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_REFIN_SL_VOL_182D | 转融券融出数量(182天) | 数值（NUMBER(20,0)）；可为空；单位：182天 | 原始字段，非本地计算。 |
| S_MARGIN_SECLENDINGBALANCE | 高精度浮点型 | 字符串；可为空 | 融券余额（元） |
| S_REFIN_SL_VOL_14D | 转融券融出数量(14天) | 数值（NUMBER(20,0)）；可为空；单位：14天 | 原始字段，非本地计算。 |
| S_REFIN_SL_VOL_7D | 转融券融出数量(7天) | 数值（NUMBER(20,0)）；可为空；单位：7天 | 原始字段，非本地计算。 |
| S_MARGIN_REPAYMENTTOBROKER | 融资偿还额(元) | 数值（NUMBER(20,4)）；可为空；单位：元 | 原始字段，非本地计算。 |
| S_REFIN_REPAY_VOL | 转融券偿还量 | 数值（NUMBER(20,0)）；可为空 | 原始字段，非本地计算。 |
| S_REFIN_SB_EOD_VOL | 转融券融入期末数量 | 数值；可为空 | 两融原始字段。 |
| S_MARGIN_TRADINGBALANCE | 融资余额(元) | 数值（NUMBER(20,4)）；可为空；单位：元 | 原始字段，非本地计算。 |
| S_REFIN_SL_EOD_VOL | 转融券融出期末数量 | 数值；可为空 | 两融原始字段。 |
| S_REFIN_SL_EOP_BAL | 转融券融出期末余额 | 数值；可为空 | 两融原始字段。 |
| S_REFIN_SL_EOP_VOL | 转融券融出期末量 | 数值；可为空 | 两融原始字段。 |
| S_REFIN_SL_VOL_3D | 转融券融出数量(3天) | 数值（NUMBER(20,0)）；可为空；单位：3天 | 原始字段，非本地计算。 |
| I_MARGIN_TRADINGBALANCEVOLUME | 融资余量 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_MARGIN_SALEREPAYAMOUNT | 融券偿还额 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_MARGIN_PURCHWITHBORROWMONEY | 高精度浮点型 | 字符串；可为空 | 融资买入额（元） |

### 表 27：资金流向

- 文件/目录：`stock/ownership/money_flow_<year>.csv`
- 文件数 / 行数 / 大小：15 / 5,684,360 / 4308.26 MB
- 来源：Wind
- 状态：完整（2012-2026，截至 2026-09-01）

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| TRADE_DT | 日期 | 字符串；可为空 | 利率公布日期 |
| VOLUME_DIFF_LARGE_TRADER_ACT | 大户量差(仅主动)(手) | 数值（NUMBER(20,4)）；可为空 | 大户量差(仅主动)(手) |
| BUY_VOLUME_LARGE_ORDER | 大户买入总量(手) | 数值（NUMBER(20,4)）；可为空；单位：手 | 原始字段，非本地计算。 |
| CLOSE_MONEYFLOW_PCT_VOLUME_L | 大单尾盘资金流向占比(量)(%) | 数值（NUMBER(20,6)）；可为空；单位：% | 原始字段，非本地计算。 |
| SELL_VALUE_EXLARGE_ORDER | 机构卖出金额(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| VALUE_DIFF_LARGE_TRADER_ACT | 大户金额差(仅主动)(万元) | 数值（NUMBER(20,4)）；可为空 | 大户金额差(仅主动)(万元) |
| S_MFD_INFLOW_CLOSE_LARGE_ORDER | 大单尾盘资金流入金额(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| MONEYFLOW_PCT_VOLUME_L | 大单资金流向占比(量)(%) | 数值（NUMBER(20,6)）；可为空；单位：% | 原始字段，非本地计算。 |
| VALUE_DIFF_INSTITUTE | 机构金额差(含主动被动)(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| S_MFD_INFLOWVOLUME_LARGE_ORDER | 大单净流入量(手) | 数值（NUMBER(20,4)）；可为空；单位：手 | 原始字段，非本地计算。 |
| VOLUME_DIFF_INSTITUTE | 机构量差(含主动被动)(手) | 数值（NUMBER(20,4)）；可为空；单位：手 | 原始字段，非本地计算。 |
| MONEYFLOW_PCT_VALUE_L | [内部]大单资金流向占比(金额)(%) | 数值（NUMBER(20,6)）；可为空；单位：% | 原始字段，非本地计算。 |
| VALUE_DIFF_SMALL_TRADER | 散户金额差(含主动被动)(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| BUY_VALUE_LARGE_ORDER_ACT | 大户买入金额(仅主动)(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| BUY_VOLUME_SMALL_ORDER | 散户买入总量(手) | 数值（NUMBER(20,4)）；可为空；单位：手 | 原始字段，非本地计算。 |
| SELL_VOLUME_LARGE_ORDER_ACT | 大户卖出总量(仅主动)(万股) | 数值（NUMBER(20,4)）；可为空；单位：万股 | 原始字段，非本地计算。 |
| SELL_VOLUME_MED_ORDER_ACT | 中户卖出总量(仅主动)(万股) | 数值（NUMBER(20,4)）；可为空；单位：万股 | 原始字段，非本地计算。 |
| CLOSE_NET_INFLOW_RATE_VALUE | 尾盘资金流入率(金额) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| TOT_VOLUME_BID | 委买总量(手) | 数值（NUMBER(20,4)）；可为空；单位：手 | 原始字段，非本地计算。 |
| SELL_TRADES_SMALL_ORDER | 散户卖出单数(单) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OPEN_MONEYFLOW_PCT_VOLUME_L | [内部]大单开盘资金流向占比(量)(%) | 数值（NUMBER(20,6)）；可为空；单位：% | 原始字段，非本地计算。 |
| S_MFD_INFLOW_OPENVOLUME_L | 大单开盘资金流入量(手) | 数值（NUMBER(20,4)）；可为空；单位：手 | 原始字段，非本地计算。 |
| S_MFD_INFLOW_CLOSEVOLUME_L | 大单尾盘资金流入量(手) | 数值（NUMBER(20,4)）；可为空；单位：手 | 原始字段，非本地计算。 |
| VOLUME_DIFF_LARGE_TRADER | 大户量差(含主动被动)(手) | 数值（NUMBER(20,4)）；可为空 | 大户量差(含主动被动)(手) |
| SELL_VOLUME_EXLARGE_ORDER_ACT | 机构卖出总量(仅主动)(万股) | 数值（NUMBER(20,4)）；可为空；单位：万股 | 原始字段，非本地计算。 |
| NET_INFLOW_RATE_VALUE_L | [内部]大单流入率(金额)(%) | 数值（NUMBER(20,6)）；可为空；单位：% | 原始字段，非本地计算。 |
| BUY_VOLUME_SMALL_ORDER_ACT | 散户买入总量(仅主动)(万股) | 数值（NUMBER(20,4)）；可为空；单位：万股 | 原始字段，非本地计算。 |
| VOLUME_DIFF_SMALL_TRADER_ACT | 散户量差(仅主动)(手) | 数值（NUMBER(20,4)）；可为空；单位：手 | 原始字段，非本地计算。 |
| BUY_VOLUME_EXLARGE_ORDER | 机构买入总量(手) | 数值（NUMBER(20,4)）；可为空；单位：手 | 原始字段，非本地计算。 |
| BUY_VALUE_EXLARGE_ORDER | 机构买入金额(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| SELL_TRADES_EXLARGE_ORDER | 机构卖出单数(单) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| BUY_TRADES_MED_ORDER | 中户买入单数(单) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| VOLUME_DIFF_INSTITUTE_ACT | 机构量差(仅主动)(手) | 数值（NUMBER(20,4)）；可为空；单位：手 | 原始字段，非本地计算。 |
| MONEYFLOW_PCT_VOLUME | 资金流向占比(量)(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| S_MFD_INFLOW_OPEN_LARGE_ORDER | 大单开盘资金流入金额(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| gmt_modified | GMT修改时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| SELL_TRADES_LARGE_ORDER | 大户卖出单数(单) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_MFD_INFLOW_OPEN | 开盘资金流入金额(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| OBJECT_ID | 数据库记录对象ID | 字符串/整数；可为空 | 接口同步元数据。 |
| VALUE_DIFF_SMALL_TRADER_ACT | 散户金额差(仅主动)(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| OPEN_MONEYFLOW_PCT_VOLUME | 开盘资金流向占比(量)(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| OPDATE | 数据操作/入库时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| BUY_VALUE_SMALL_ORDER | 散户买入金额(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| VOLUME_DIFF_MED_TRADER_ACT | 中户量差(仅主动)(手) | 数值（NUMBER(20,4)）；可为空；单位：手 | 原始字段，非本地计算。 |
| OPMODE | 操作/写入模式 | 字符串；可为空 | 接口同步元数据。 |
| VOLUME_DIFF_SMALL_TRADER | 散户量差(含主动被动)(手) | 数值（NUMBER(20,4)）；可为空；单位：手 | 原始字段，非本地计算。 |
| S_MFD_INFLOW_CLOSEVOLUME | 尾盘资金流入量(手) | 数值（NUMBER(20,4)）；可为空；单位：手 | 原始字段，非本地计算。 |
| SELL_VALUE_LARGE_ORDER | 大户卖出金额(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| BUY_VALUE_MED_ORDER_ACT | 中户买入金额(仅主动)(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| BUY_VOLUME_LARGE_ORDER_ACT | 大户买入总量(仅主动)(万股) | 数值（NUMBER(20,4)）；可为空；单位：万股 | 原始字段，非本地计算。 |
| OPEN_NET_INFLOW_RATE_VOLUME_L | [内部]大单开盘资金流入率(量)(%) | 数值（NUMBER(20,6)）；可为空；单位：% | 原始字段，非本地计算。 |
| BUY_TRADES_SMALL_ORDER | 散户买入单数(单) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OPEN_NET_INFLOW_RATE_VALUE | 开盘资金流入率(金额) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SELL_VALUE_EXLARGE_ORDER_ACT | 机构卖出金额(仅主动)(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| S_MFD_INFLOWVOLUME | 净流入量(手) | 数值（NUMBER(20,4)）；可为空；单位：手 | 原始字段，非本地计算。 |
| SELL_VOLUME_SMALL_ORDER_ACT | 散户卖出总量(仅主动)(万股) | 数值（NUMBER(20,4)）；可为空；单位：万股 | 原始字段，非本地计算。 |
| CLOSE_NET_INFLOW_RATE_VALU_L | [内部]大单尾盘资金流入率(金额)(%) | 数值（NUMBER(20,6)）；可为空；单位：% | 原始字段，非本地计算。 |
| VALUE_DIFF_LARGE_TRADER | 大户金额差(含主动被动)(万元) | 数值（NUMBER(20,4)）；可为空 | 大户金额差(含主动被动)(万元) |
| SELL_VALUE_MED_ORDER_ACT | 中户卖出金额(仅主动)(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| S_MFD_INFLOW_OPENVOLUME | 开盘资金流入量(手) | 数值（NUMBER(20,4)）；可为空；单位：手 | 原始字段，非本地计算。 |
| CLOSE_NET_INFLOW_RATE_VOLUME | 尾盘资金流入率(量)(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| BUY_VALUE_SMALL_ORDER_ACT | 散户买入金额(仅主动)(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| SELL_VOLUME_LARGE_ORDER | 大户卖出总量(手) | 数值（NUMBER(20,4)）；可为空；单位：手 | 原始字段，非本地计算。 |
| TRADES_COUNT | 成交笔数(笔) | 非负整数；可为空 | 原始字段，非本地计算。 |
| SELL_VALUE_MED_ORDER | 中户卖出金额(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| NET_INFLOW_RATE_VOLUME | 流入率(量)(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| NET_INFLOW_RATE_VALUE | 流入率(金额) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OPEN_NET_INFLOW_RATE_VOLUME | 开盘资金流入率(量)(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| TOT_VOLUME_ASK | 委卖总量(手) | 数值（NUMBER(20,4)）；可为空；单位：手 | 原始字段，非本地计算。 |
| VALUE_DIFF_INSTITUTE_ACT | 机构金额差(仅主动)(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| BUY_TRADES_EXLARGE_ORDER | 机构买入单数(单) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_MFD_INFLOW | 净流入金额(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| SELL_VALUE_LARGE_ORDER_ACT | 大户卖出金额(仅主动)(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| NET_INFLOW_RATE_VOLUME_L | 大单流入率(量)(%) | 数值（NUMBER(20,6)）；可为空；单位：% | 原始字段，非本地计算。 |
| BUY_VALUE_LARGE_ORDER | 大户买入金额(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| SELL_TRADES_MED_ORDER | 中户卖出单数(单) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| VOLUME_DIFF_MED_TRADER | 中户量差(含主动被动)(手) | 数值（NUMBER(20,4)）；可为空；单位：手 | 原始字段，非本地计算。 |
| VALUE_DIFF_MED_TRADER_ACT | 中户金额差(仅主动)(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| CLOSE_MONEYFLOW_PCT_VOLUME | 尾盘资金流向占比(量)(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 原始字段，非本地计算。 |
| BUY_TRADES_LARGE_ORDER | 大户买入单数(单) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| BUY_VOLUME_EXLARGE_ORDER_ACT | 机构买入总量(仅主动)(万股) | 数值（NUMBER(20,4)）；可为空；单位：万股 | 原始字段，非本地计算。 |
| S_INFO_WINDCODE | Wind代码 | Wind证券/指数代码字符串；可为空 | 原始字段，非本地计算。 |
| CLOSE_MONEYFLOW_PCT_VALUE_L | [内部]大单尾盘资金流向占比(金额)(%) | 数值（NUMBER(20,6)）；可为空；单位：% | 原始字段，非本地计算。 |
| SELL_VOLUME_MED_ORDER | 中户卖出总量(手) | 数值（NUMBER(20,4)）；可为空；单位：手 | 原始字段，非本地计算。 |
| BUY_VOLUME_MED_ORDER | 中户买入总量(手) | 数值（NUMBER(20,4)）；可为空；单位：手 | 原始字段，非本地计算。 |
| OPEN_MONEYFLOW_PCT_VALUE | 开盘资金流向占比(金额) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SELL_VALUE_SMALL_ORDER | 散户卖出金额(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| BUY_VOLUME_MED_ORDER_ACT | 中户买入总量(仅主动)(万股) | 数值（NUMBER(20,4)）；可为空；单位：万股 | 原始字段，非本地计算。 |
| gmt_created | GMT创建时间 | 时间戳字符串；可为空 | 接口同步元数据。 |
| SELL_VALUE_SMALL_ORDER_ACT | 散户卖出金额(仅主动)(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| S_MFD_INFLOW_CLOSE | 尾盘资金流入金额(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| MONEYFLOW_PCT_VALUE | 资金流向占比(金额) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| SELL_VOLUME_EXLARGE_ORDER | 机构卖出总量(手) | 数值（NUMBER(20,4)）；可为空；单位：手 | 原始字段，非本地计算。 |
| CLOSE_MONEYFLOW_PCT_VALUE | 尾盘资金流向占比(金额) | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| OPEN_NET_INFLOW_RATE_VALUE_L | [内部]大单开盘资金流入率(金额)(%) | 数值（NUMBER(20,6)）；可为空；单位：% | 原始字段，非本地计算。 |
| BUY_VALUE_EXLARGE_ORDER_ACT | 机构买入金额(仅主动)(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| BUY_VALUE_MED_ORDER | 中户买入金额(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| CLOSE_NET_INFLOW_RATE_VOLUME_L | [内部]大单尾盘资金流入率(量)(%) | 数值（NUMBER(20,6)）；可为空；单位：% | 原始字段，非本地计算。 |
| S_MFD_INFLOW_LARGE_ORDER | 大单净流入金额(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| VALUE_DIFF_MED_TRADER | 中户金额差(含主动被动)(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| SELL_VOLUME_SMALL_ORDER | 散户卖出总量(手) | 数值（NUMBER(20,4)）；可为空；单位：手 | 原始字段，非本地计算。 |
| OPEN_MONEYFLOW_PCT_VALUE_L | 大单开盘资金流向占比(金额)(%) | 数值（NUMBER(20,6)）；可为空；单位：% | 原始字段，非本地计算。 |

## 九、国证成长100复刻结果

### 表 28：国证成长100复刻候选池

- 文件/目录：`index/growth100_replication/growth100_all_a_candidate_pool.csv`
- 文件数 / 行数 / 大小：1 / 10,808 / 4.49 MB
- 来源：本地derived
- 状态：完整候选池

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| code | 股票代码 | Wind证券代码字符串；可为空 | 复刻结果中的股票代码。 |
| amount_mean | 近半年日均成交额 | 数值；单位：千元 | mean(S_DQ_AMOUNT)。 |
| mv_mean | 近半年日均总市值 | 数值；单位：万元 | mean(S_VAL_MV)。 |
| FREE_SHARES_TODAY | 当日自由流通股本 | 数值（NUMBER(24,8)）；可为空 | 原始字段，非本地计算。 |
| S_DQ_CLOSE_TODAY | 当日收盘价 | 数值（NUMBER(20,4)）；可为空 | 原始字段，非本地计算。 |
| S_VAL_MV | 总市值(万元) | 数值（NUMBER(20,4)）；可为空；单位：万元 | 原始字段，非本地计算。 |
| free_float_mv | 自由流通市值 | 数值；单位：万元 | 自由流通股本×收盘价。 |
| S_QFA_ROE | 单季度.净资产收益率 | 数值（NUMBER(24,6)）；可为空 | 在某个单季度内净利润与平均净资产的比率企业的净资产收益率下降，代表企业净利润中属于股东权益部分的收益率降低了，对股东有不利影响；按单季度统计的企业净利润(不含少数股东损益)与平均净资产的比率； |
| ANN_DT | 公告日期 | YYYYMMDD字符串；可为空 | 公告发布当天的日期；公告的发布日期；债券发行公告公布当天日期； |
| REPORT_PERIOD | 报告期 | YYYYMMDD字符串；可为空 | 见附注 |
| S_QFA_GROSSPROFITMARGIN | 单季度.销售毛利率 | 数值（NUMBER(20,4)）；可为空 | 单季度毛利占销售净值的百分比；按单季度统计的毛利与按单季度统计的销售收入的比值，反映单季度每1元销售收入扣减生产成本后还有多少盈余可以用来支付企业运营费用并最终形成收益。 |
| S_INFO_WINDCODE | Wind代码 | Wind证券/指数代码字符串；可为空 | 万得自定义的用来识别证券的唯一编码,后缀为交易场所 |
| S_QFA_YOYNETPROFIT | 单季度.归属母公司股东的净利润同比增长率(%) | 数值（NUMBER(20,4)）；可为空；单位：% | 单季度归属母公司股东的净利润相对于上年同期的增长情况；按单季度统计的归属母公司股东的净利润的同比增长率(%)； |
| key | 股票+报告期唯一键 | 字符串 | 代码_REPORT_PERIOD。 |
| ann_fill | 公告日期填充值 | YYYYMMDD整数；空值按0 | 取最新披露。 |
| prev_S_QFA_ROE | 上一期单季度ROE | 数值 | shift(1)。 |
| prev_S_QFA_GROSSPROFITMARGIN | 上一期单季度毛利率 | 数值 | shift(1)。 |
| prev_S_QFA_YOYNETPROFIT | 上一期单季度净利润同比 | 数值 | shift(1)。 |
| roe_chg | ROE环比变化 | 数值；单位：% | (当前−上期)/abs(上期)×100。 |
| gm_chg | 毛利率变化 | 数值；单位：百分点 | 当前−上期。 |
| g1 | 单季度净利润SUE | 数值 | (当前−前8期均值)/标准差。 |
| S_INFO_WINDCODE_inc | 股票Wind代码（合并后缀） | Wind证券代码字符串；可为空 | 合并估值/财务表时用于消歧的字段。 |
| np_cum | 最新累计归母净利润 | 数值 | 最新报告期归母净利润；要求>0。 |
| con_npgrate_13w | 13周一致预期净利润变化率 | 数值；可为空 | 13周一致预期净利润变化率 |
| con_npcgrate_2y | 一致预期净利润两年复合增长率 | 数值；可为空 | 一致预期净利润两年复合增长率 |
| roe_cur | 当年一致预期ROE | 数值；单位：% | con_year=T。 |
| roe_next | 次年一致预期ROE | 数值；单位：% | con_year=T+1。 |
| g4 | 次年ROE同比增速 | 数值；单位：% | (roe_next−roe_cur)/abs(roe_cur)×100。 |
| r_g1 | G1排名 | 正整数；1最优 | 降序排名。 |
| r_con_npgrate_13w | G2排名 | 正整数；1最优 | 降序排名。 |
| r_con_npcgrate_2y | G3排名 | 正整数；1最优 | 降序排名。 |
| r_g4 | G4排名 | 正整数；1最优 | 降序排名。 |
| score | 综合得分 | 数值；越小越优 | 四因子排名等权加总。 |
| asof | 调仓日期 | YYYYMMDD整数 | 每年2/5/8/11月第六个交易日。 |

### 表 29：国证成长100复刻净值

- 文件/目录：`index/growth100_replication/growth100_all_a_nav.csv`
- 文件数 / 行数 / 大小：1 / 447 / 0.03 MB
- 来源：本地derived
- 状态：基期1000

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| TRADE_DT | 交易日期 | YYYYMMDD字符串；可为空 | 交易发生的日期；发生交易的日期； |
| replicated_close | 复刻净值 | 数值；基期1000 | 按日收益累计。 |
| official_close | 官方收盘价 | 数值；指数点 | 官方价格指数。 |
| replicated_return | 复刻日收益率 | 数值；可为空 | 净值pct_change。 |
| official_return | 官方日收益率 | 数值；可为空 | 收盘价pct_change。 |

### 表 30：国证成长100复刻调仓组合

- 文件/目录：`index/growth100_replication/growth100_all_a_rebalance_portfolios.csv`
- 文件数 / 行数 / 大小：1 / 900 / 0.10 MB
- 来源：本地derived
- 状态：每次100只

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| asof | 调仓/截面日期 | YYYYMMDD整数 | 每年2/5/8/11月第六个交易日。 |
| code | 股票代码 | Wind证券代码字符串；可为空 | 复刻结果中的股票代码。 |
| weight | 复刻权重 | 数值；单位：%；单票上限10 | 调整自由流通市值/合计×100。 |
| score | 综合得分 | 数值；越小越优 | 四因子排名等权加总。 |
| g1 | G1单季度净利润SUE | 数值 | (当前值−前8期均值)/前8期标准差。 |
| con_npgrate_13w | 13周一致预期净利润变化率 | 数值；可为空 | 13周一致预期净利润变化率 |
| con_npcgrate_2y | 一致预期净利润两年复合增长率 | 数值；可为空 | 一致预期净利润两年复合增长率 |
| g4 | G4一致预期次年ROE同比增速 | 数值；单位：% | (次年ROE−当年ROE)/abs(当年ROE)×100。 |
| free_float_mv | 自由流通市值 | 数值；单位：万元 | 自由流通股本×收盘价。 |
| tilt | 倾斜因子 | 数值；默认约1–2 | 1+strength×(1−score_pct)。 |

### 表 31：复刻重合度

- 文件/目录：`index/growth100_replication/growth100_all_a_overlap_by_rebalance.csv`
- 文件数 / 行数 / 大小：1 / 9 / 0.00 MB
- 来源：本地derived
- 状态：9个调仓日

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| asof | 调仓/截面日期 | YYYYMMDD整数 | 每年2/5/8/11月第六个交易日。 |
| official_weight_date | 官方权重快照日期 | YYYYMMDD字符串 | 调仓日最近可得的官方权重日期。 |
| official_active_count | 官方有效成分数量 | 非负整数 | 官方指数当期有效成分数量。 |
| overlap_count | 重合成分数量 | 非负整数 | 复刻组合与官方成分交集数量。 |
| overlap_pct | 数量重合率 | 数值；单位：% | 重合数/官方数×100。 |
| official_weight_captured_pct | 官方权重被覆盖比例 | 数值；单位：% | 重合股官方权重/官方权重合计×100。 |
| replicated_weight_in_overlap_pct | 复刻权重落在官方成分比例 | 数值；单位：% | 重合股复刻权重合计。 |
| weight_similarity_min_pct | 权重相似度 | 数值；单位：% | sum(min(复刻权重,官方权重))。 |

### 表 32：复刻重合度与中证覆盖

- 文件/目录：`index/growth100_replication/growth100_all_a_overlap_and_csi_coverage.csv`
- 文件数 / 行数 / 大小：1 / 9 / 0.00 MB
- 来源：本地derived
- 状态：9个调仓日

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| asof | 调仓/截面日期 | YYYYMMDD整数 | 每年2/5/8/11月第六个交易日。 |
| official_weight_date_x | 官方权重快照日期（合并后缀x） | YYYYMMDD字符串 | 合并表后保留的官方权重日期。 |
| official_active_count | 官方有效成分数量 | 非负整数 | 官方指数当期有效成分数量。 |
| overlap_count | 重合成分数量 | 非负整数 | 复刻组合与官方成分交集数量。 |
| overlap_pct | 数量重合率 | 数值；单位：% | 重合数/官方数×100。 |
| official_weight_captured_pct | 官方权重被覆盖比例 | 数值；单位：% | 重合股官方权重/官方权重合计×100。 |
| replicated_weight_in_overlap_pct | 复刻权重落在官方成分比例 | 数值；单位：% | 重合股复刻权重合计。 |
| weight_similarity_min_pct | 权重相似度 | 数值；单位：% | sum(min(复刻权重,官方权重))。 |
| official_weight_date_y | 官方权重快照日期（合并后缀y） | YYYYMMDD字符串 | 合并表后保留的官方权重日期。 |
| our_csi800_count | 复刻中证800数量 | 非负整数 | 交集数量。 |
| our_csi800_weight_pct | 复刻中证800权重 | 数值；单位：% | 权重合计。 |
| off_csi800_count | 官方中证800数量 | 非负整数 | 交集数量。 |
| off_csi800_weight_pct | 官方中证800权重 | 数值；单位：% | 权重合计。 |
| our_csi1800_count | 复刻中证1800数量 | 非负整数 | 交集数量。 |
| our_csi1800_weight_pct | 复刻中证1800权重 | 数值；单位：% | 权重合计。 |
| off_csi1800_count | 官方中证1800数量 | 非负整数 | 交集数量。 |
| off_csi1800_weight_pct | 官方中证1800权重 | 数值；单位：% | 权重合计。 |

## 十、元数据与运行状态

### 表 33：字段字典

- 文件/目录：`字段字典.csv`
- 文件数 / 行数 / 大小：1 / 21 / 0.02 MB
- 来源：本地元数据
- 状态：21个数据集

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| dataset | 数据集名称 | 字符串 | 字段清单所属数据集。 |
| file_pattern | 文件模式 | 字符串 | 路径模式。 |
| fields | 字段清单 | 分号分隔字符串 | 全部字段。 |

### 表 34：数据集总表

- 文件/目录：`数据集总表.csv`
- 文件数 / 行数 / 大小：1 / 22 / 0.02 MB
- 来源：本地元数据
- 状态：22个数据集

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| dataset | 数据集名称 | 字符串 | 汇总主键。 |
| file_pattern | 文件模式 | 字符串 | 路径模式。 |
| files | 文件数 | 非负整数 | 落地文件数。 |
| rows | 总行数 | 非负整数 | 不含表头。 |
| size_mb | 总大小 | 非负数值，单位MB | 大小合计。 |
| stock_count | 覆盖证券数 | 非负整数 | 去重证券数。 |
| date_start | 起始日期 | YYYY-MM-DD | 最早日期。 |
| date_end | 结束日期 | YYYY-MM-DD | 最新日期。 |
| source | 数据来源 | 字符串 | 来源及接口。 |
| content | 内容摘要 | 字符串 | 人工说明。 |
| fields | 字段清单 | 分号分隔字符串 | 全部字段。 |
| status | 状态 | 字符串 | 完整/缺口等。 |

### 表 35：文件清单

- 文件/目录：`data_inventory.csv`
- 文件数 / 行数 / 大小：1 / 499 / 0.02 MB
- 来源：本地元数据
- 状态：499个CSV

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| file | 文件路径 | 字符串 | 相对data/。 |
| rows | 文件行数 | 非负整数 | 不含表头。 |
| size_mb | 文件大小 | 非负数值，单位MB | 单文件大小。 |

### 表 36：Wind一致预期进度

- 文件/目录：`stock/consensus/.progress/wind.csv`
- 文件数 / 行数 / 大小：1 / 5,886 / 0.11 MB
- 来源：本地状态
- 状态：断点续传

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| code | 已完成股票代码 | Wind代码字符串 | 断点续传。 |
| last_date | 最新已拉取日期 | YYYYMMDD字符串 | 续传起点。 |

### 表 37：朝阳永续进度

- 文件/目录：`stock/consensus/.progress/suntime.csv`
- 文件数 / 行数 / 大小：1 / 9,956 / 0.19 MB
- 来源：本地状态
- 状态：断点续传

| 字段名 | 含义 | 取值范围 | 计算方式/备注 |
|---|---|---|---|
| code | 已完成股票代码 | Wind代码字符串 | 断点续传。 |
| last_date | 最新已拉取日期 | YYYYMMDD字符串 | 续传起点。 |

## 附：主要本地计算公式

```text
amount_mean_6m = mean(S_DQ_AMOUNT)
mv_mean_6m = mean(S_VAL_MV)
free_float_mv = FREE_SHARES_TODAY * S_DQ_CLOSE_TODAY
roe_qoq = (S_QFA_ROE[t] - S_QFA_ROE[t-1]) / abs(S_QFA_ROE[t-1]) * 100
gm_qoq = S_QFA_GROSSPROFITMARGIN[t] - S_QFA_GROSSPROFITMARGIN[t-1]
G1 = (S_QFA_YOYNETPROFIT[t] - mean(past_8)) / std(past_8)
G2 = con_npgrate_13w
G3 = con_npcgrate_2y
G4 = (con_roe[Y+1] - con_roe[Y]) / abs(con_roe[Y]) * 100
score = 0.25*r_G1 + 0.25*r_G2 + 0.25*r_G3 + 0.25*r_G4
tilt = 1 + 1.0 * (1 - score_pct)
weight = free_float_mv * tilt / sum(free_float_mv * tilt) * 100
```

时点规则：行情与估值用 `TRADE_DT <= T`；财务数据用 `ANN_DT <= T`；一致预期取 `con_date <= T` 的最新快照；指数成分要求纳入日期 ≤ T 且剔除日期为空或 ≥ T。