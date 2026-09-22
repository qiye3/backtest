# 价值因子构造表（2026-09-16）

本表逐项对应 config/*.yaml，公式依据 code/base_factors.py、code/utils.py 与 code/ValueFactor.py。表中方向严格按当前代码记录。

## 统一口径

- 比率使用安全除法：分母非有限或绝对值不大于 1e-12 时返回缺失。
- 总市值 S_VAL_MV 的 Wind 单位为万元；与元口径财务字段组合时先乘 10000。
- 历史百分位均为逐股票时间序列排名，不是当日横截面排名。
- 当前 52 个 YAML 均配置为 rolling_mean_window=1、neutralize=false、不缩尾、reverse=false。

## 因子构造表

| factor_name | 核心构造逻辑（使用指标） | 处理方式 |
|---|---|---|
| <code>bp</code> | 账面市值比：1 / S_VAL_PB_NEW。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>bp_percentile_1y</code> | 账面市值比：1 / S_VAL_PB_NEW。 | 逐股票 240 日滚动历史百分位，至少 120 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>bp_percentile_5y</code> | 账面市值比：1 / S_VAL_PB_NEW。 | 逐股票 1200 日滚动历史百分位，至少 600 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>consensus_valuation</code> | 一致预期 PE、PB、PS 分别取倒数后做每日正向截面百分位，至少 2 项有效后等权平均。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>consensus_valuation_percentile_1y</code> | 一致预期 PE、PB、PS 分别取倒数后做每日正向截面百分位，至少 2 项有效后等权平均。 | 逐股票 240 日滚动历史百分位，至少 120 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>consensus_valuation_percentile_5y</code> | 一致预期 PE、PB、PS 分别取倒数后做每日正向截面百分位，至少 2 项有效后等权平均。 | 逐股票 1200 日滚动历史百分位，至少 600 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>dividend_low_vol_composite</code> | 股息率正向、240 日年化波动率反向、ROE 正向截面百分位等权平均；三项均须有效。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>dividend_quality_composite</code> | 股息率、扣非 ROE S_FA_ROE_DEDUCTED、经营现金流/利润 S_FA_OCFTOPROFIT 的正向截面百分位等权平均；三项均须有效。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>dividend_yield</code> | 股息率：1 / S_PRICE_DIV_DPS（按当前代码实现）。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>dividend_yield_percentile_1y</code> | 股息率：1 / S_PRICE_DIV_DPS（按当前代码实现）。 | 逐股票 240 日滚动历史百分位，至少 120 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>dividend_yield_percentile_5y</code> | 股息率：1 / S_PRICE_DIV_DPS（按当前代码实现）。 | 逐股票 1200 日滚动历史百分位，至少 600 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>ebit_ev</code> | EBIT S_FA_EBIT / 企业价值；企业价值＝总市值 S_VAL_MV×10000＋净债务 S_FA_NETDEBT。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>ebit_ev_percentile_1y</code> | EBIT S_FA_EBIT / 企业价值；企业价值＝总市值 S_VAL_MV×10000＋净债务 S_FA_NETDEBT。 | 逐股票 240 日滚动历史百分位，至少 120 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>ebit_ev_percentile_5y</code> | EBIT S_FA_EBIT / 企业价值；企业价值＝总市值 S_VAL_MV×10000＋净债务 S_FA_NETDEBT。 | 逐股票 1200 日滚动历史百分位，至少 600 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>ep</code> | TTM 盈利收益率：1 / S_VAL_PE_TTM。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>ep_percentile_1y</code> | TTM 盈利收益率：1 / S_VAL_PE_TTM。 | 逐股票 240 日滚动历史百分位，至少 120 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>ep_percentile_5y</code> | TTM 盈利收益率：1 / S_VAL_PE_TTM。 | 逐股票 1200 日滚动历史百分位，至少 600 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>ep_static</code> | 静态盈利收益率：1 / S_VAL_PE。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>ep_static_percentile_1y</code> | 静态盈利收益率：1 / S_VAL_PE。 | 逐股票 240 日滚动历史百分位，至少 120 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>ep_static_percentile_5y</code> | 静态盈利收益率：1 / S_VAL_PE。 | 逐股票 1200 日滚动历史百分位，至少 600 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>ev_ebitda</code> | EBITDA S_FA_EBITDA / 企业价值，即 EV/EBITDA 的倒数。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>ev_ebitda_percentile_1y</code> | EBITDA S_FA_EBITDA / 企业价值，即 EV/EBITDA 的倒数。 | 逐股票 240 日滚动历史百分位，至少 120 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>ev_ebitda_percentile_5y</code> | EBITDA S_FA_EBITDA / 企业价值，即 EV/EBITDA 的倒数。 | 逐股票 1200 日滚动历史百分位，至少 600 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>ev_ocf</code> | TTM 经营现金流 NET_CASH_FLOWS_OPER_ACT_TTM / 企业价值，即 EV/OCF 的倒数。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>ev_ocf_percentile_1y</code> | TTM 经营现金流 NET_CASH_FLOWS_OPER_ACT_TTM / 企业价值，即 EV/OCF 的倒数。 | 逐股票 240 日滚动历史百分位，至少 120 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>ev_ocf_percentile_5y</code> | TTM 经营现金流 NET_CASH_FLOWS_OPER_ACT_TTM / 企业价值，即 EV/OCF 的倒数。 | 逐股票 1200 日滚动历史百分位，至少 600 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>expected_pe_change</code> | （65 个交易日前一致预期 PE－当前一致预期 PE）/ 65 日前一致预期 PE 的绝对值。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>fcf_yield</code> | 企业自由现金流 S_FA_FCFF / 企业价值。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>fcf_yield_percentile_1y</code> | 企业自由现金流 S_FA_FCFF / 企业价值。 | 逐股票 240 日滚动历史百分位，至少 120 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>fcf_yield_percentile_5y</code> | 企业自由现金流 S_FA_FCFF / 企业价值。 | 逐股票 1200 日滚动历史百分位，至少 600 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>irrational_valuation_premium</code> | log(PE_TTM) 对 ROE、净利率、资产负债率和 log(总市值) 做每日截面回归，取残差相反数。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>low_valuation_option</code> | 正 PE 的 1200 日历史百分位不高于 30%，且研发费用/营业收入高于当日中位数时记 1，否则记 0；PE 分位至少需 600 个观测。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>low_volatility</code> | 复权收盘价日收益的 240 日样本标准差×sqrt(252)，至少 120 个观测；当前未反向。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>net_cash_to_mv</code> | 负净债务 -S_FA_NETDEBT /（总市值 S_VAL_MV×10000）。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>net_cash_to_mv_percentile_1y</code> | 负净债务 -S_FA_NETDEBT /（总市值 S_VAL_MV×10000）。 | 逐股票 240 日滚动历史百分位，至少 120 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>net_cash_to_mv_percentile_5y</code> | 负净债务 -S_FA_NETDEBT /（总市值 S_VAL_MV×10000）。 | 逐股票 1200 日滚动历史百分位，至少 600 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>pb_roe_group</code> | 仅保留 ROE 不低于当日中位数股票的 BP（1/PB），其余置缺失。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>pb_roe_regression</code> | log(PB) 对 ROE 做每日截面回归，取残差相反数。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>pcf</code> | 经营现金流市值比：1 / S_VAL_PCF_OCFTTM。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>pcf_percentile_1y</code> | 经营现金流市值比：1 / S_VAL_PCF_OCFTTM。 | 逐股票 240 日滚动历史百分位，至少 120 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>pcf_percentile_5y</code> | 经营现金流市值比：1 / S_VAL_PCF_OCFTTM。 | 逐股票 1200 日滚动历史百分位，至少 600 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>pe_percentile_5y</code> | 正的 TTM PE S_VAL_PE_TTM。 | 逐股票 1200 日滚动历史百分位，至少 600 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>peg</code> | 正的一致预期 PEG con_peg；当前保留倍数原值。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>peg_percentile_1y</code> | 正的一致预期 PEG con_peg；当前保留倍数原值。 | 逐股票 240 日滚动历史百分位，至少 120 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>peg_percentile_5y</code> | 正的一致预期 PEG con_peg；当前保留倍数原值。 | 逐股票 1200 日滚动历史百分位，至少 600 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>sp</code> | 销售收入市值比：1 / S_VAL_PS_TTM。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>sp_percentile_1y</code> | 销售收入市值比：1 / S_VAL_PS_TTM。 | 逐股票 240 日滚动历史百分位，至少 120 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>sp_percentile_5y</code> | 销售收入市值比：1 / S_VAL_PS_TTM。 | 逐股票 1200 日滚动历史百分位，至少 600 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>valuation_composite</code> | EP、BP、PCF、股息率分别做正向每日截面百分位，至少 3 项有效后等权平均。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>valuation_composite_percentile_5y</code> | EP、BP、PCF、股息率分别做正向每日截面百分位，至少 3 项有效后等权平均。 | 逐股票 1200 日滚动历史百分位，至少 600 个观测。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>value_quality_composite</code> | EP、BP、ROE、经营现金流/利润分别做正向每日截面百分位，至少 3 项有效后等权平均。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
| <code>value_trap_filter</code> | 传统估值得分与质量得分各占 1/2；质量得分由 ROE 同比、现金含量正向及低负债反向百分位组成，至少 2 项有效。 | 保留原值。 随后按当日股票池掩码；无平滑、市值中性化、缩尾或反向；无穷值转缺失，输出 float32。 |
