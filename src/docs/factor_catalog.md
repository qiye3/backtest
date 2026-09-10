# 因子构造表

默认14个固定因子、20个窗口变体。财务计算使用股票代码、公告日期、实际公告日期（可用时）、报告期和可选版本；行情与一致预期使用各自日期和股票标识。

| 因子 | 固定构造 | 使用到的原始字段 | 窗口变体 |
|---|---|---|---|
| `consensus_13w_revision` | 当年预测口径的净利润增速13周修正字段；最近S个交易日均值 | `con_npgrate_13w` | smooth_1d：smooth_window=1 |
| `consensus_13w_revision_change_20d` | 当年预测口径的净利润增速13周修正字段；再减去20交易日前的值；最近S个交易日均值 | `con_npgrate_13w` | smooth_1d：smooth_window=1 |
| `consensus_13w_revision_change_5d` | 当年预测口径的净利润增速13周修正字段；再减去5交易日前的值；最近S个交易日均值 | `con_npgrate_13w` | smooth_1d：smooth_window=1 |
| `consensus_13w_revision_zscore` | 当年预测口径的净利润增速13周修正字段；再按N交易日均值和样本标准差标准化（含当日）；最近S个交易日均值 | `con_npgrate_13w` | window_65d：smooth_window=1, transform_window=65；window_130d：smooth_window=1, transform_window=130 |
| `growth_np_sue` | 当前单季净利润同比指标相对过去N季度该指标的均值和样本标准差标准化；最近S个交易日均值 | `S_QFA_YOYNETPROFIT` | smooth_1d：smooth_window=1, history_quarters=8 |
| `residual_momentum` | 过去R日个股收益减个股/指数V日波动率比值乘指数R日收益；最近S个周末均值 | `S_DQ_ADJCLOSE`, `指数S_DQ_CLOSE（000906.SH）` | smooth_4w：smooth_window=4, return_window=20, volatility_window=63；smooth_1w：smooth_window=1, return_window=20, volatility_window=63 |
| `residual_momentum_change_20d` | 过去R日个股收益减个股/指数V日波动率比值乘指数R日收益；再减去20交易日前的值；最近S个周末均值 | `S_DQ_ADJCLOSE`, `指数S_DQ_CLOSE（000906.SH）` | smooth_4w：smooth_window=4, return_window=20, volatility_window=63 |
| `residual_momentum_change_5d` | 过去R日个股收益减个股/指数V日波动率比值乘指数R日收益；再减去5交易日前的值；最近S个周末均值 | `S_DQ_ADJCLOSE`, `指数S_DQ_CLOSE（000906.SH）` | smooth_4w：smooth_window=4, return_window=20, volatility_window=63 |
| `residual_momentum_quantile` | 过去R日个股收益减个股/指数V日波动率比值乘指数R日收益；再计算N交易日内当日值的并列平均百分位（含当日）；最近S个周末均值 | `S_DQ_ADJCLOSE`, `指数S_DQ_CLOSE（000906.SH）` | window_120d_smooth_4w：smooth_window=4, return_window=20, volatility_window=63, transform_window=120；window_260d_smooth_4w：smooth_window=4, return_window=20, volatility_window=63, transform_window=260 |
| `residual_momentum_zscore` | 过去R日个股收益减个股/指数V日波动率比值乘指数R日收益；再按N交易日均值和样本标准差标准化（含当日）；最近S个周末均值 | `S_DQ_ADJCLOSE`, `指数S_DQ_CLOSE（000906.SH）` | window_120d_smooth_4w：smooth_window=4, return_window=20, volatility_window=63, transform_window=120；window_260d_smooth_4w：smooth_window=4, return_window=20, volatility_window=63, transform_window=260 |
| `roe_history_zscore` | 最新ROE相对过去N季度的均值和样本标准差标准化；最近S个交易日均值 | `S_QFA_ROE` | history_8q：smooth_window=1, history_quarters=8；history_12q：smooth_window=1, history_quarters=12 |
| `roe_level` | 最新已公开报告期ROE；最近S个交易日均值 | `S_QFA_ROE` | smooth_1d：smooth_window=1 |
| `roe_qoq_diff` | 最新季度ROE减上一季度ROE；最近S个交易日均值 | `S_QFA_ROE` | smooth_1d：smooth_window=1 |
| `roe_yoy_diff` | 最新季度ROE减去年同季度ROE；最近S个交易日均值 | `S_QFA_ROE` | smooth_1d：smooth_window=1；smooth_5d：smooth_window=5 |

## 原始字段

| 字段 | 含义 |
|---|---|
| S_QFA_ROE | 单季度净资产收益率，沿用源数据单位；源数据为百分数时差值为百分点 |
| S_QFA_YOYNETPROFIT | 单季度归母净利润同比指标，沿用源定义 |
| con_npgrate_13w | 一致预期净利润增速13周修正指标，沿用源定义 |
| S_DQ_ADJCLOSE / S_DQ_ADJOPEN | 股票复权收盘价/开盘价，用于跨期收益和复权持仓单位估值 |
| S_DQ_CLOSE / S_DQ_OPEN | 指数收盘/开盘价；账户选择 tradability 时，股票未复权成交参考价用于涨跌停判断 |
| S_DQ_LIMIT / S_DQ_STOPPING | 股票当日涨停价/跌停价 |
| S_DQ_TRADESTATUS | 交易状态，含“停”的状态按停牌处理 |
| ANN_DT / ACTUAL_ANN_DT | 公告日期/实际公告日期，优先使用有效的实际公告日期 |
| REPORT_PERIOD | 财务报告期，按日历季度定位比较期 |
| version（可选） | 同一公告日与报告期内的版本序号，越大越新；不能代替真实修订公告日期 |
| con_date / con_year | 一致预期日期/预测年度，current_year选择与该日期年份相同的预测 |
| DELISTDATE | 源数据中的退市日期；当前简化评估/回测不使用该字段进行估算清算 |

当前年度预测跨年时先失效，直到新年度预测可用。同一股票同一日存在无法区分的冲突记录时直接报错。

## 其他保留能力

通用实现支持财务同比/环比相对变化（差值除以比较期绝对值，比较期为0时缺失）、季度分位位置、累计收入表转单季度、季节性利润/收入意外、Wind一致预期字段和评级上调比例。它们需要独立因子配置，不进入默认实验，也不会作为算子变体自动生成。
