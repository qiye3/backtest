# v5 配置参考

完整可运行模板为 `configs/experiment_v5.yaml`。所有相对文件路径相对于所在实验 YAML 的目录；标准因子 YAML 列表的路径也以实验 YAML 为基准。未选中的计算模块不要求完整配置。已选中模块出现未知字段立即报错。

## 运行、数据与输入

| 字段 | 默认值/示例 | 含义 |
|---|---|---|
| `experiment.name` | `single_factor_v5` | 输出子目录；字母、数字、下划线和连字符 |
| `run.modules` | 三项计算和 plotting | 选择 factors/group_return/simple_backtest/account_backtest/plotting；完整模板额外包含 factors |
| `data.root` | `../data` | 原始数据根目录 |
| `data.calendar_path` | null | 可选 CSV，`date` 列是完整、升序、无重复的交易日；空时按所读取行情的日期并集 |
| `data.benchmark` | `000906.SH` | 两种回测比较的基准；评估不需要基准 |
| `data.benchmark_return` | `total_return` / `price` | 读取 `index/prices_total_return` 或 `index/prices` |
| `parallel.enabled` | true | 多因子是否并行 |
| `parallel.backend` | `process` / `thread` | 进程或线程；线程绘图有互斥锁 |
| `parallel.workers` | 4 | 并行因子数量；同一因子的周期与区间在该任务内依次执行 |
| `parallel.on_error` | `continue` / `stop` | 单因子失败后继续或停止提交结果处理；已经在运行的任务可能仍完成；任一失败最终都会报错 |
| `factor_input.source` | `generated` / `external` | 读取标准 Factor 文件目录，或外部文件列表 |
| `factor_input.values_dir` | `../outputs/factor_values` | generated 输入目录，需与之前生成位置一致 |
| `factor_input.ids` | `[]` | 空为全部来源；非空只选指定完整标识 |
| `factor_input.files` | `[{id: my_factor, path: ../inputs/factor.csv}]` | external 输入；每个文件一个因子，标识不可重复 |
| `factor_input.layout` | `wide` | 当前支持日期×股票宽表 |
| `factor_input.date_column` | `date` | CSV/Parquet 日期列名；Parquet 也可保留日期索引 |
| `factor_input.alignment` | `exact` / `asof` | exact 要求所选因子日期存在；asof 使用该日期以前最近的整张快照，显式 NaN 不逐股票填补 |

因子文件可用 `.csv`、`.csv.gz`、`.parquet`。日期支持 YYYY-MM-DD 或 YYYYMMDD，日级、无时区。其余列名必须与行情的股票代码一致（如 `000001.SZ`），内容为数值或缺失；重复日期/股票列报错。非有限数值转为缺失，交给模块缺失规则。

generated 输入检查 manifest 中的文件内容摘要；下游不重新运行 Factor，也不要求当前构造代码与生成时相同。各结果保留输入摘要，可识别同名因子文件已经改变的旧结果。

## 标准 Factor 模块

| `factors` 字段 | 要求 |
|---|---|
| `start`、`end` | 生成因子矩阵的正式区间；与三个计算模块的区间独立 |
| `universe_indices` | 数据加载所覆盖的历史指数成员并集，例如 800+1000 |
| `values_dir` | 输出因子目录，保存矩阵、manifest 和 resolved_config |
| `configs` | 单个 Factor YAML 路径列表 |

各 Factor YAML 保留原有结构：

| 字段 | 含义与取值 |
|---|---|
| `name` | 固定公式标识；更换公式、输入字段、变换算子应使用新因子名 |
| `implementation` | registry 注册项：financial / financial_history / income / income_surprise / consensus / rating / residual_momentum |
| `direction` | 1 或 −1，在输出矩阵中乘入 |
| `data` | 所需源字段列表，如 financial_indicators、stock_price、index_price_codes、consensus_suntime；允许键由 Factor 实现声明 |
| `params` | 固定公式参数；取决于实现，下表列举 |
| `history.trading_days` | 正式开始日前所需行情预热长度，正整数；不足时停止 |
| `smoothing.method` | mean / median，固定为该 Factor 构造的一部分 |
| `smoothing.unit` | trading_days / weekly_closes；后者观察已完成的周五截面，假日回退当周最后交易日 |
| `time_transform` | 可选固定时序算子：change / relative_change 配 lag_days；zscore / quantile 配 min_fraction |
| `window_defaults` | 全部允许窗口的默认值；包括 smooth_window 和具体 Factor 的内部聚合窗口 |
| `variants` | `{name, windows}` 列表；只能覆盖窗口，不能换公式、输入、方向或算子；有效窗口完全相同的重复变体报错 |

`smooth_window: 1` 表示不平滑。完整因子输入标识为 `name.variant_name`，例如 `roe_level.smooth_1d`。研究未来周期没有进入标识。

| 实现 | 固定参数和窗口 |
|---|---|
| financial | params.value_field；method = level / yoy_difference / qoq_difference / yoy_relative / qoq_relative；仅 smooth_window |
| financial_history | params.value_field；method = zscore / sue / quantile；history_quarters + smooth_window |
| residual_momentum | params.index_code、volatility_min_fraction；return_window、volatility_window + smooth_window |
| consensus | params.value_field、source = wind/suntime；suntime 需 target_year_rule=current_year；smooth_window |
| income / income_surprise | params.value_field、method=level / seasonal_sue；income_surprise 另有 history_quarters；完整声明见对应 Factor 类 |
| rating | params.upgrade_field、downgrade_field、maintain_field、rating_cycle；净上调比例=(上调−下调)/(上调+下调+维持)；smooth_window；非默认实验因子 |

默认 14 个因子的逐项公式、字段和 20 个窗口组合见 `factor_catalog.md`。新增计算类继承 `Factor`，实现 `compute(data, definition, windows)` 并声明 `data_keys/param_keys/window_keys`，在 registry 注册后使用 YAML。下游评估无需改动。

## 三个计算模块独立拥有的字段

以下字段分别放在 `group_return`、`simple_backtest`、`account_backtest` 下，不设置跨模块共享分组。

| 字段 | 默认 | 含义 |
|---|---|---|
| `start`、`end` | 必填 | 本模块区间；group_return 的 end 也是未来收益实现截止日 |
| `factor_ids` | `[]` | 本模块从已选输入中使用哪些因子，空为全部 |
| `universe_indices` | `[000906.SH, 000852.SH]` | 本模块按日历史成员并集 |
| `factor_lag_days` | 0 | 因子截面相对参考/交易日期滞后多少交易日 |
| `grouping.quantile_edges` | 十个 `[0,0.1]` … `[0.9,1]` 区间 | 独立区间列表；允许不等宽、重叠、只取尾部；不自动补齐 |
| `grouping.min_stocks` | 200 | 分组前有效股票截面的最少数量，不是每组人数 |
| `grouping.missing_factor_policy` | exclude / error | 当期因子缺失时排除或报错；不使用未来价格决定资格 |
| `grouping.weighting.method` | equal / field | 组内等权或正字段归一加权 |
| `grouping.weighting.field` | null | field 模式必填，例如 S_DQ_MV |
| `grouping.weighting.lag_days` | 0 | 字段加权值的独立交易日滞后；equal 时 field 必须为 null，lag 为 0 |
| `missing_price_policy` | 评估 previous_close；回测 error | 必需价格缺失时直接报错，或按历史参考收盘补齐 |
| `max_stale_days` | null | previous_close 的最大陈旧交易日数；null 无额外期限，0 禁止陈旧值；来源可追溯 |

## group_return 专属字段

| 字段 | 默认 | 含义 |
|---|---|---|
| `sampling.weekday` | FRI | MON/TUE/WED/THU/FRI |
| `sampling.every_n_weeks` | 1 | 每几周取一个截面，相当于之前的 K；不是搜索参数 |
| `sampling.anchor_date` | 2021-01-01 | 以其所在周为相位起点，每 N 周选取，不随区间改变 |
| `sampling.holiday_policy` | previous_trading_day / skip | 指定星期非交易日时回退当周或跳过 |
| `reference_price` | close / open | 固定起终点的复权参考价格 |
| `future_return_days` | `[5,20,60]` | 一次计算的未来交易日周期列表，正整数、不可重复 |
| `group_return_agg` | mean / median | 同日同组股票收益合成；mean 支持所配组内权重 |
| `time_return_agg` | mean / median | 多个有效观察日期聚合，同一未来周期内统计 |
| `empty_group_policy` | nan / error | 某区间没有股票时留空或报错 |
| `insufficient_stocks_policy` | nan / error | 总有效股票数不足 min_stocks 时留空或报错 |

这里没有平滑搜索、交易费、模拟账户或可成交判断。某个未来收益周期到 `end` 仍不完整会标记并留空，不改变已完成周期的计算。

## 两种回测各自的专属字段

| 字段 | 默认 | 含义 |
|---|---|---|
| `rebalance.weekday` | FRI | 调仓星期，可选五个工作日 |
| `rebalance.intervals_weeks` | `[1,2,4]` | 对每个周期单独运行，不与评估 future_return_days 绑定 |
| `rebalance.anchor_date` | 2021-01-01 | 调仓相位锚定周 |
| `rebalance.holiday_policy` | previous_trading_day / skip | 同 sampling 规则 |
| `trade_price` | close / open | 调仓成交参考价；日终估值始终为收盘 |
| `initial_entry` | first_rebalance / start | 首个规则调仓日建仓，或区间第一交易日额外建仓 |
| `initial_capital` | 1 | 简易模式必须为 1；账户正数，完整模板为 1000000，影响金额不影响净值 |
| `transaction_cost_rate` | 0 | 每单位实际买入或卖出金额的费用率，范围 [0,1)；0.001=单边千分之一 |
| `charge_initial_cost` | true | 初始建仓是否收取配置费用 |
| `liquidate_at_end` | false | 是否在末日收盘提交零持仓目标并计费；tradability 下仍遵守可成交限制 |
| `empty_group_policy` | cash / hold / error | 空组变现金、保持实际持仓或报错 |
| `insufficient_stocks_policy` | error / cash / hold | 总股票数不足时的动作 |
| `curve_frequency` | both / daily / rebalance | 估值与保存频率需求；始终保存调仓曲线作为核对依据，daily/both 额外估值每日收盘 |
| `execution.policy` | ideal / tradability | 简易仅支持 ideal；账户可选交易状态限制 |
| `execution.block_suspended` | true | tradability 时未知状态或停牌拒绝成交 |
| `execution.block_buy_limit_up` | true | tradability 时涨停不买入 |
| `execution.block_sell_limit_down` | true | tradability 时跌停不卖出 |

若 `metrics.return_frequency: daily`，或本次启用绘图且要求 daily，回测会计算每日估值。要只计算调仓日，设置本模块 `curve_frequency: rebalance`、指标 `return_frequency: rebalance`，绘图也选择 rebalance。open 调仓仍保留开盘事件以及所需收盘估值。

ideal 明确忽略成交限制，后三个 block 开关只在 tradability 下生效；仍必须获得所选价格策略认可的价格。代码不会凭空造出一个可交易价格。

## 指标、绘图和保存

| 字段 | 默认 | 含义 |
|---|---|---|
| `metrics.risk_free_rate` | 0 | Sharpe 的年化无风险利率，现金本身不计息 |
| `metrics.return_frequency` | daily / rebalance | 风险指标取样频率 |
| `metrics.annual_trading_days` | 252 | 日频风险年化因子 |
| `metrics.annual_weeks` | 52 | 周期风险年化，除以调仓周数 |
| `metrics.include_initial_turnover` | true | 平均/年化/买卖换手中是否包含初始建仓 |
| `metrics.simple_annual_return` | linear / compound | 默认累加收益线性年化；compound 使用段收益连乘的对照年化 |
| `metrics.account_annual_return` | compound / linear | 默认账户 CAGR |
| `metrics.ic_horizons` | `[5,20,60]` | 如存在同因子输入的评估结果，将这些周期的总体 IC 指标及评价日期附到回测指标；不隐式运行评估 |
| `plots.enabled` | true | 全局绘图开关；还需选中 plotting 模块 |
| `plots.formats` | `[png,pdf]` | 可选 png/pdf/svg |
| `plots.dpi` | 160 | 导出分辨率 |
| `plots.width`、`row_height` | 13、3.4 | 图宽与每一周期行高，单位英寸 |
| `plots.font_family` | DejaVu Sans | Matplotlib 字体；可改为本机已安装中文字体 |
| `plots.curve_frequency` | daily / rebalance | 两类回测图读哪个曲线；缺少所需频率时提示重新计算 |
| `plots.missing_results` | skip / error | 对未运行的图对应模块跳过或报错 |
| `plots.note` | 空字符串 | 所有图的附加说明文字 |
| `plots.legend_columns` | 4 | 图例每行列数 |
| `plots.distribution.enabled` | true | 分布图开关 |
| `plots.distribution.bins` | 60 | 直方图箱数 |
| `plots.distribution.density` | true | 密度或频数纵轴 |
| `plots.distribution.kde` | true | 是否叠加核密度曲线 |
| `plots.distribution.clip_quantiles` | null | 可选 `[0.01,0.99]`，仅截取显示样本 |
| `plots.distribution.max_points` | 200000 | 显示最多抽样点数；固定随机种子 |
| `plots.evaluation.enabled` | true | 图 1 开关 |
| `plots.evaluation.group_panel` | left / right | 分组柱图位置，另一侧是 IC 序列 |
| `plots.evaluation.group_colors` | 深红→暗黄→深绿 | 按区间顺序插值，可配置更多颜色端点 |
| `plots.evaluation.ic_color`、`rank_ic_color` | 橙、深蓝 | 总体 Pearson IC 与总体 Spearman RankIC |
| `plots.simple.enabled`、`plots.account.enabled` | true | 图 2/3 分别启用 |
| `plots.simple.layout` | rows | 图 2 固定按调仓周期竖向排列，不接受 columns |
| `plots.simple.group_colors` | 深红→暗黄→深绿 | 图 2 分组曲线渐变色 |
| `plots.simple.benchmark_color` | `#777777` | 图 2 灰色虚线基准 |
| `plots.simple.summary_quantile` | `[0.9,1.0]` | 图 2 底部指标表选择的分位区间；默认 q0.1/Q10 |
| `plots.simple.metric_columns` | 年化收益、波动、Sharpe、回撤、换手 | 图 2 指标表列及顺序；只能从支持的回测指标中选择且不可重复 |
| `plots.account.layout` | rows / columns | 图 3 调仓周期按行或列排列 |
| `plots.account.group_colors`、`benchmark_color` | 红→绿、灰色 | 图 3 保持原账户图配置 |
| `output.root` | `../outputs` | 输出根目录，后续是 experiment.name/factor_id |
| `output.save_group_members` | true | 保存所选股票、百分位或目标权重明细 |
| `output.save_target_weights` | true | 保存两种回测的长格式目标表 |
| `output.save_holdings` | true | 保存账户持仓明细 |
| `output.save_trades` | true | 保存交易明细；换手汇总仍始终保存 |

再次运行某个计算模块会替换该因子该模块的旧结果，其他模块结果保留。更换同名因子文件后，绘图会拒绝混用旧输入摘要的其他模块结果；重新运行这些模块或使用新 experiment.name。
