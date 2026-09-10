# 输出文件与指标

输出在 `output.root/experiment.name/`。根目录有合并后的 `resolved_config.yaml` 与 `run_status.csv`；每个因子有自己的子目录。生成 Factor 的目录另由 `factors.values_dir` 控制。

## 因子与评估

| 相对因子目录 | 内容 |
|---|---|
| `factor_input.json` | 因子标识、输入文件摘要、本次执行模块 |
| `factor_sample.csv.gz` | 运行所取因子日期的并集，每个日期/股票一次；用于分布图，保留原矩阵股票列，不混合各模块的股票池 |
| `error.txt` | 失败原因和调用栈；该因子下一次成功重跑会清理 |
| `group_return/meta.json`、`resolved_config.yaml` | 输入摘要、数据路径和本模块实际配置 |
| `group_return/definitions.csv` | G01 等稳定编号、分位上下界、完整区间标签、名义比例 |
| `group_return/detail.csv.gz` | 日期×未来周期×组的原始收益、股票数、补价人数、完成状态 |
| `group_return/summary.csv` | 组收益柱图数据、两层聚合方式、有效日期数、平均组规模 |
| `group_return/ic.csv.gz` | 日期×周期的总体 IC、RankIC、有效股票数、补价人数 |
| `group_return/ic_summary.csv` | 每个周期的 IC/RankIC 均值、样本标准差、ICIR、有效日期数、评价区间 |
| `group_return/labels.csv.gz` | 个股未来收益与价格端点、价格实际来源日期和补价方式 |
| `group_return/members.csv.gz` | 可选组成员及因子值、百分位、组内权重 |

`status` 包括 complete、horizon_incomplete、insufficient_stocks，组明细还可能为 empty_group。NaN 会在 CSV 中留空，图中无收益的柱显示 N/A。

## 两种回测

`simple_backtest/` 与 `account_backtest/` 各有 meta、resolved_config、metrics。调仓周期目录为 `W1`、`W2` 等，每个周期有独立 definitions、actions、members 和 target_weights；各组存入其 `G01` 等子目录。G01 在不同模块的意义可以完全不同，必须按该模块 definitions 的上下界解释。

| 组目录中的文件 | 内容 |
|---|---|
| `curves_daily.csv.gz` | 日终曲线与初始点；按运行需求生成 |
| `curves_rebalance.csv.gz` | 调仓事件曲线、初始点和期末收盘 |
| `turnover.csv.gz` | 买入/卖出/半和换手、费用率；账户还保存调仓前资产和费用金额 |
| `trades.csv.gz` | 可选交易明细，参考价格来源和日期；账户含数量/金额/成本/成交状态与拒单原因 |
| `holdings.csv.gz` | 账户可选的每个估值事件持仓：复权数量、价格、价值、权重 |

简易曲线字段是 `cumulative_return`、`gross_cumulative_return`、`benchmark_cumulative_return`；账户为 `nav`、`gross_nav`、`benchmark_nav`，额外有 assets、cash、cash_weight。两者的 date/timestamp、price_kind、event、is_rebalance、is_terminal 用于区分同一天的开盘、收盘和初始扣费点。

目标长表使用 date、portfolio_id、code、target_weight、group_id、rebalance_weeks。portfolio_id 包括因子、组和周期。零权重表示不持有，全 NaN 的目标行表示保持实际持仓，不是还原上一目标权重。actions 记录空组等导致的 cash/hold 动作。

## metrics.csv 每列定义

| 字段 | 定义 |
|---|---|
| factor_id、group_id、quantile_lower、quantile_upper、label、rebalance_weeks、mode | 唯一识别因子、区间、周期、引擎 |
| actual_start、actual_end、years | 实际投入与末日估值时间、实际年数 |
| transaction_cost_rate | 配置的单边成交费用率 |
| metric_frequency、risk_periods、risk_periods_per_year | 风险指标观察频率、有效观察数、年化期数 |
| gross_total_return | 零交易费对照的总收益，简易为累加，账户为 NAV−1 |
| net_total_return、total_return | 两者均表示费后总收益，后者为便利别名 |
| annual_return、gross_annual_return、annual_return_method | 费后/费前年化及 linear/compound 口径 |
| sharpe | 超过无风险收益的均值/样本标准差×sqrt(年化期数) |
| max_drawdown、drawdown_method | 简易为收益百分点回撤；账户为净值相对峰值回撤；为 0 或负值 |
| annual_volatility | 同频收益样本标准差×sqrt(年化期数) |
| mean_turnover、annual_turnover | 所计调仓事件的平均半和换手、总半和换手/年数 |
| buy_turnover、sell_turnover | 所计事件的买入、卖出换手之和 |
| total_cost | 账户扣费金额之和；简易无金额账户，留空 |
| total_cost_rate、annual_cost_rate | 各次费用/各次调仓前资产之和，以及除以年数；不是期末累计损失比例 |
| estimated_trade_fraction | 使用 previous_close 参考价成交的买卖比例之和；用于识别补价假设影响 |
| benchmark_total_return | 与当前引擎、同起点同分段口径一致的基准收益 |
| excess_total_return | 简易为累计收益差；账户为 NAV/benchmark_NAV−1 |
| tracking_error | 同频组合收益减基准收益的标准差年化 |
| information_ratio | 同频主动收益均值×年化期数/跟踪误差 |
| ic_mean_Nd、ic_std_Nd、icir_Nd | 可选附加的 N 日总体 IC 统计 |
| rank_ic_mean_Nd、rank_ic_std_Nd、rank_icir_Nd | 可选附加的 N 日总体 RankIC 统计 |
| start_Nd、end_Nd、ic_scope_Nd | 该 IC 证据的评价区间与 full_universe 范围，可能不同于回测区间 |

IC 是整个因子截面的指标，作为背景证据附到各账户行；它不是某个账户净值的相关系数，也不是组内 IC。仅在同输入摘要的 group_return 输出存在时附加；账户独立运行时不强制存在 IC 数据。

## 图形

`figures/` 默认导出 PNG 和 PDF，可另配 SVG：

1. `00_factor_distribution`：因子值直方图与 KDE。
2. `01_evaluation`：每个未来周期一行，等宽展示深红→暗黄→深绿的分组收益柱图，以及总体 IC/RankIC 时序。
3. `02_simple_backtest`：调仓周期竖向排列；每行展示全部分组费后累加收益与灰色虚线基准，底部是配置分位区间在各周期的指标表。
4. `03_account_backtest`：每个调仓周期的独立账户费后净值与灰色基准。

`plot_config.json` 留存本次绘图设置。绘图只读取结果，单独重新绘图不会改动回测明细。
