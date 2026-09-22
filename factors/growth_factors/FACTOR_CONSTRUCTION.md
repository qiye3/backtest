# 成长因子构造表（2026-09-16）

本表逐项对应 config/*.yaml，公式依据 code/base_factors.py、code/utils.py 与 code/GrowthFactor.py。不根据因子名称推测方向，只记录当前实现。

## 统一口径

- 日频窗口按交易日计：K1＝20 日，K12/M12＝240 日，K24/M24＝480 日。
- 季度数据按公告日生效，使用 REPORT_PERIOD 识别自然季度，避免直接按日频 shift 造成重复状态偏差。
- 当前 56 个 YAML 均配置为 rolling_mean_window=1、neutralize=false、不缩尾、reverse=false。

## 因子构造表

| factor_name | 核心构造逻辑（使用指标） | 处理方式 |
|---|---|---|
| <code>analyst_coverage</code> | 分析师覆盖人数，直接读取 prediction_number。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>analyst_coverage__chg_K1</code> | 分析师覆盖人数，直接读取 prediction_number。 | 减去 20 个交易日前的值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>analyst_coverage__qtile_M12</code> | 分析师覆盖人数，直接读取 prediction_number。 | 逐股票 240 日滚动历史百分位，至少 120 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>analyst_coverage__qtile_M24</code> | 分析师覆盖人数，直接读取 prediction_number。 | 逐股票 480 日滚动历史百分位，至少 240 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>analyst_coverage__qtilechg_K24_K1</code> | 分析师覆盖人数，直接读取 prediction_number。 | 先算 480 日历史百分位（至少 240 个观测），再减去 20 个交易日前的百分位。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>analyst_coverage__zchg_K24_K1</code> | 分析师覆盖人数，直接读取 prediction_number。 | 先算 480 日滚动 Z-score（至少 240 个观测），再减去 20 个交易日前的 Z-score。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>analyst_coverage__zscore_K12</code> | 分析师覆盖人数，直接读取 prediction_number。 | 逐股票 240 日滚动 Z-score，至少 120 个观测，使用样本标准差。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>analyst_coverage__zscore_K24</code> | 分析师覆盖人数，直接读取 prediction_number。 | 逐股票 480 日滚动 Z-score，至少 240 个观测，使用样本标准差。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>consensus_13w_revision</code> | 13 周一致预期净利润增速调整，直接读取 con_npgrate_13w。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>consensus_13w_revision__chg_K1</code> | 13 周一致预期净利润增速调整，直接读取 con_npgrate_13w。 | 减去 20 个交易日前的值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>consensus_13w_revision__qtile_M12</code> | 13 周一致预期净利润增速调整，直接读取 con_npgrate_13w。 | 逐股票 240 日滚动历史百分位，至少 120 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>consensus_13w_revision__qtile_M24</code> | 13 周一致预期净利润增速调整，直接读取 con_npgrate_13w。 | 逐股票 480 日滚动历史百分位，至少 240 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>consensus_13w_revision__qtilechg_K24_K1</code> | 13 周一致预期净利润增速调整，直接读取 con_npgrate_13w。 | 先算 480 日历史百分位（至少 240 个观测），再减去 20 个交易日前的百分位。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>consensus_13w_revision__zchg_K24_K1</code> | 13 周一致预期净利润增速调整，直接读取 con_npgrate_13w。 | 先算 480 日滚动 Z-score（至少 240 个观测），再减去 20 个交易日前的 Z-score。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>consensus_13w_revision__zscore_K12</code> | 13 周一致预期净利润增速调整，直接读取 con_npgrate_13w。 | 逐股票 240 日滚动 Z-score，至少 120 个观测，使用样本标准差。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>consensus_13w_revision__zscore_K24</code> | 13 周一致预期净利润增速调整，直接读取 con_npgrate_13w。 | 逐股票 480 日滚动 Z-score，至少 240 个观测，使用样本标准差。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>consensus_eps</code> | 一致预期 EPS，直接读取 con_eps。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>consensus_eps__chg_K1</code> | 一致预期 EPS，直接读取 con_eps。 | 减去 20 个交易日前的值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>consensus_eps__qtile_M12</code> | 一致预期 EPS，直接读取 con_eps。 | 逐股票 240 日滚动历史百分位，至少 120 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>consensus_eps__qtile_M24</code> | 一致预期 EPS，直接读取 con_eps。 | 逐股票 480 日滚动历史百分位，至少 240 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>consensus_eps__qtilechg_K24_K1</code> | 一致预期 EPS，直接读取 con_eps。 | 先算 480 日历史百分位（至少 240 个观测），再减去 20 个交易日前的百分位。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>consensus_eps__zchg_K24_K1</code> | 一致预期 EPS，直接读取 con_eps。 | 先算 480 日滚动 Z-score（至少 240 个观测），再减去 20 个交易日前的 Z-score。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>consensus_eps__zscore_K12</code> | 一致预期 EPS，直接读取 con_eps。 | 逐股票 240 日滚动 Z-score，至少 120 个观测，使用样本标准差。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>consensus_eps__zscore_K24</code> | 一致预期 EPS，直接读取 con_eps。 | 逐股票 480 日滚动 Z-score，至少 240 个观测，使用样本标准差。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>consensus_np_sue</code> | 公告日单季度归母净利润－当日一致预期年度净利润/4，再相对公告前历次 surprise 做历史样本 Z-score。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>consensus_np_sue__qoq</code> | 公告日单季度归母净利润－当日一致预期年度净利润/4，再相对公告前历次 surprise 做历史样本 Z-score。 | 季频 PIT 公告状态延续到下一次公告；按自然报告季度减去上一季度值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>consensus_np_sue__qtile8</code> | 公告日单季度归母净利润－当日一致预期年度净利润/4，再相对公告前历次 surprise 做历史样本 Z-score。 | 季频 PIT 公告状态延续到下一次公告；在连续 8 个自然季度内计算当前值的平均名次百分位；窗口必须完整。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>consensus_np_sue__yoy</code> | 公告日单季度归母净利润－当日一致预期年度净利润/4，再相对公告前历次 surprise 做历史样本 Z-score。 | 季频 PIT 公告状态延续到下一次公告；按自然报告季度减去上年同期值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>earnings_sue</code> | 单季度归母净利润同比差额，相对公告前历次同比差额做历史样本 Z-score。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>earnings_sue__qoq</code> | 单季度归母净利润同比差额，相对公告前历次同比差额做历史样本 Z-score。 | 季频 PIT 公告状态延续到下一次公告；按自然报告季度减去上一季度值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>earnings_sue__qtile8</code> | 单季度归母净利润同比差额，相对公告前历次同比差额做历史样本 Z-score。 | 季频 PIT 公告状态延续到下一次公告；在连续 8 个自然季度内计算当前值的平均名次百分位；窗口必须完整。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>earnings_sue__yoy</code> | 单季度归母净利润同比差额，相对公告前历次同比差额做历史样本 Z-score。 | 季频 PIT 公告状态延续到下一次公告；按自然报告季度减去上年同期值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>quarterly_net_profit</code> | 累计归母净利润 NET_PROFIT_EXCL_MIN_INT_INC 按报告期还原为单季度值。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>quarterly_net_profit__qoq</code> | 累计归母净利润 NET_PROFIT_EXCL_MIN_INT_INC 按报告期还原为单季度值。 | 季频 PIT 公告状态延续到下一次公告；按自然报告季度减去上一季度值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>quarterly_net_profit__qtile8</code> | 累计归母净利润 NET_PROFIT_EXCL_MIN_INT_INC 按报告期还原为单季度值。 | 季频 PIT 公告状态延续到下一次公告；在连续 8 个自然季度内计算当前值的平均名次百分位；窗口必须完整。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>quarterly_net_profit__yoy</code> | 累计归母净利润 NET_PROFIT_EXCL_MIN_INT_INC 按报告期还原为单季度值。 | 季频 PIT 公告状态延续到下一次公告；按自然报告季度减去上年同期值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>quarterly_revenue</code> | 累计营业总收入 TOT_OPER_REV 按报告期还原为单季度值；一季度取累计值，其余季度减上一季度累计值。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>quarterly_revenue__qoq</code> | 累计营业总收入 TOT_OPER_REV 按报告期还原为单季度值；一季度取累计值，其余季度减上一季度累计值。 | 季频 PIT 公告状态延续到下一次公告；按自然报告季度减去上一季度值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>quarterly_revenue__qtile8</code> | 累计营业总收入 TOT_OPER_REV 按报告期还原为单季度值；一季度取累计值，其余季度减上一季度累计值。 | 季频 PIT 公告状态延续到下一次公告；在连续 8 个自然季度内计算当前值的平均名次百分位；窗口必须完整。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>quarterly_revenue__yoy</code> | 累计营业总收入 TOT_OPER_REV 按报告期还原为单季度值；一季度取累计值，其余季度减上一季度累计值。 | 季频 PIT 公告状态延续到下一次公告；按自然报告季度减去上年同期值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>quarterly_roe</code> | 单季度 ROE，直接读取 S_QFA_ROE。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>quarterly_roe__qoq</code> | 单季度 ROE，直接读取 S_QFA_ROE。 | 季频 PIT 公告状态延续到下一次公告；按自然报告季度减去上一季度值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>quarterly_roe__qtile8</code> | 单季度 ROE，直接读取 S_QFA_ROE。 | 季频 PIT 公告状态延续到下一次公告；在连续 8 个自然季度内计算当前值的平均名次百分位；窗口必须完整。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>quarterly_roe__yoy</code> | 单季度 ROE，直接读取 S_QFA_ROE。 | 季频 PIT 公告状态延续到下一次公告；按自然报告季度减去上年同期值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>rating_upgrade_ratio_90d</code> | 90 日评级上调、下调、维持次数；计算（上调次数－下调次数）/ 全部评级动作次数。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>rating_upgrade_ratio_90d__chg_K1</code> | 90 日评级上调、下调、维持次数；计算（上调次数－下调次数）/ 全部评级动作次数。 | 减去 20 个交易日前的值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>rating_upgrade_ratio_90d__qtile_M12</code> | 90 日评级上调、下调、维持次数；计算（上调次数－下调次数）/ 全部评级动作次数。 | 逐股票 240 日滚动历史百分位，至少 120 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>rating_upgrade_ratio_90d__qtile_M24</code> | 90 日评级上调、下调、维持次数；计算（上调次数－下调次数）/ 全部评级动作次数。 | 逐股票 480 日滚动历史百分位，至少 240 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>rating_upgrade_ratio_90d__qtilechg_K24_K1</code> | 90 日评级上调、下调、维持次数；计算（上调次数－下调次数）/ 全部评级动作次数。 | 先算 480 日历史百分位（至少 240 个观测），再减去 20 个交易日前的百分位。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>rating_upgrade_ratio_90d__zchg_K24_K1</code> | 90 日评级上调、下调、维持次数；计算（上调次数－下调次数）/ 全部评级动作次数。 | 先算 480 日滚动 Z-score（至少 240 个观测），再减去 20 个交易日前的 Z-score。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>rating_upgrade_ratio_90d__zscore_K12</code> | 90 日评级上调、下调、维持次数；计算（上调次数－下调次数）/ 全部评级动作次数。 | 逐股票 240 日滚动 Z-score，至少 120 个观测，使用样本标准差。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>rating_upgrade_ratio_90d__zscore_K24</code> | 90 日评级上调、下调、维持次数；计算（上调次数－下调次数）/ 全部评级动作次数。 | 逐股票 480 日滚动 Z-score，至少 240 个观测，使用样本标准差。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>revenue_sur</code> | 单季度营业收入同比差额，相对公告前历次同比差额做历史样本 Z-score。 | 季频 PIT 公告状态延续到下一次公告；保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>revenue_sur__qoq</code> | 单季度营业收入同比差额，相对公告前历次同比差额做历史样本 Z-score。 | 季频 PIT 公告状态延续到下一次公告；按自然报告季度减去上一季度值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>revenue_sur__qtile8</code> | 单季度营业收入同比差额，相对公告前历次同比差额做历史样本 Z-score。 | 季频 PIT 公告状态延续到下一次公告；在连续 8 个自然季度内计算当前值的平均名次百分位；窗口必须完整。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>revenue_sur__yoy</code> | 单季度营业收入同比差额，相对公告前历次同比差额做历史样本 Z-score。 | 季频 PIT 公告状态延续到下一次公告；按自然报告季度减去上年同期值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
